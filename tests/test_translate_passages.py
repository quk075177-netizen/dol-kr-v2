from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH

from translation.store import source_hash
from translation.translate_passages import (
    L2_RETRIES,
    _l2_retry_hint,
    _rel_source_path,
    _skeleton_ok,
    next_request_id,
    repair_separator_newlines,
    translate_passage,
    verify_malformed_post_markers,
    verify_separator_newlines,
    verify_unit_structure,
)
TWO = (
    ":: One\n\nHello world.\n\n"
    ":: Two\n\nSecond passage here.\n\n"
)


class TranslatePassagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.file = self.root / "main.twee"
        self.file.write_text(TWO, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _passage(self, name: str = "One"):
        data = self.file.read_bytes()
        source = parse_file(data, str(self.file), DEFAULT_VALUE_KIND_PATH)
        return next(p for p in source.passages if p.name == name)

    def test_next_request_id(self) -> None:
        records = {
            "h": [
                {"request_id": "req_20260808_001"},
                {"request_id": "req_20260808_007"},
                {"request_id": "req_20260807_999"},
            ]
        }
        rid = next_request_id(records)
        self.assertEqual(rid, "req_20260808_008")

    def test_skeleton_ok_identity(self) -> None:
        from pretranslation_cst.masking import mask_passage

        data = self.file.read_bytes()
        source = parse_file(data, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        artifact = mask_passage(data, passage)
        body = data[passage.body_span.start : passage.body_span.end]
        self.assertTrue(_skeleton_ok(artifact, body, "One", str(self.file)))
        self.assertFalse(_skeleton_ok(artifact, b"\nBROKEN <<if>> structure\n\n", "One", str(self.file)))

    def test_separator_repair(self) -> None:
        # P1 P2 (whitespace separator between two naked variables) → P1P2
        # must be repaired back to the original space separator.
        from pretranslation_cst.masking import mask_passage

        raw = b":: One\n\nHello $x $y world.\n\n"
        source = parse_file(raw, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        artifact = mask_passage(raw, passage)
        tokens = [ph.placeholder for ph in artifact.placeholders]
        self.assertEqual(len(tokens), 2)
        joined = tokens[0] + tokens[1] + " world.\n"  # space separator dropped
        self.assertEqual(len(verify_separator_newlines(artifact, joined)), 1)
        repaired = repair_separator_newlines(artifact, joined)
        self.assertEqual(len(verify_separator_newlines(artifact, repaired)), 0)
        self.assertIn(tokens[0] + " " + tokens[1], repaired)

    def test_separator_repair_multi_char_gap(self) -> None:
        # A "\n\n" paragraph-break gap must be restored as "\n\n", not a
        # single "\n" (shrunken gaps silently lose paragraph breaks).
        from pretranslation_cst.masking import mask_passage

        raw = b":: One\n\nBefore $x\n\n$y after.\n\n"
        source = parse_file(raw, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        artifact = mask_passage(raw, passage)
        tokens = [ph.placeholder for ph in artifact.placeholders]
        joined = tokens[0] + "\n" + tokens[1] + " after.\n"  # \n\n shrunk to \n
        self.assertEqual(len(verify_separator_newlines(artifact, joined)), 1)
        repaired = repair_separator_newlines(artifact, joined)
        self.assertIn(tokens[0] + "\n\n" + tokens[1], repaired)
        self.assertEqual(len(verify_separator_newlines(artifact, repaired)), 0)

    def test_malformed_post_markers(self) -> None:
        self.assertEqual(verify_malformed_post_markers("x {{post:이가}} y"), [])
        self.assertEqual(len(verify_malformed_post_markers("x {{post:이가} y")), 1)
        self.assertEqual(len(verify_malformed_post_markers("x {{post:이가 y")), 1)
        self.assertEqual(
            len(verify_malformed_post_markers("a {{post:을를}} b {{post:은는} c")), 1
        )

    def _unit_with(self, masked_text: str, ph_tokens: list[str]):
        from pretranslation_cst.model import Span

        unit = mock.Mock()
        unit.masked_text = masked_text
        unit.ancestors = None
        unit.preceding_context = None
        unit.following_context = None
        unit.placeholders = [
            mock.Mock(placeholder=t, source_span=Span(0, 0), original_text="")
            for t in ph_tokens
        ]
        return unit

    def test_verify_unit_structure_ok(self) -> None:
        unit = self._unit_with("<0000001> hello <0000002>", ["<0000001>", "<0000002>"])
        self.assertEqual(verify_unit_structure(unit, "<0000001> 안녕 <0000002>"), [])

    def test_verify_unit_structure_reorder(self) -> None:
        unit = self._unit_with("<0000001> hello <0000002>", ["<0000001>", "<0000002>"])
        self.assertEqual(verify_unit_structure(unit, "<0000002> 안녕 <0000001>"), ["reorder"])

    def test_verify_unit_structure_foreign_token(self) -> None:
        unit = self._unit_with("<0000001> hello", ["<0000001>"])
        self.assertEqual(
            verify_unit_structure(unit, "<0000001> 안녕 <0000002>"), ["foreign_token"]
        )

    def test_verify_unit_structure_format_hallucination(self) -> None:
        # masker grew the prefix (7-digit tokens); the model wrote a 6-digit one
        unit = self._unit_with("<0000000> hello <0000001>", ["<0000000>", "<0000001>"])
        self.assertEqual(
            verify_unit_structure(unit, "<0000000> 안녕 <000000>"), ["format_hallucination"]
        )

    def test_verify_unit_structure_reorder_plus_foreign(self) -> None:
        unit = self._unit_with("<0000001> hello <0000002>", ["<0000001>", "<0000002>"])
        problems = verify_unit_structure(unit, "<0000003> <0000002> 안녕 <0000001>")
        self.assertIn("foreign_token", problems)
        self.assertIn("reorder", problems)

    def test_verify_unit_structure_prose_drop(self) -> None:
        unit = self._unit_with(
            "<0000001> hello <0000002>", ["<0000001>", "<0000002>"]
        )
        self.assertEqual(
            verify_unit_structure(unit, "<0000001><0000002> 안녕"), ["prose_drop"]
        )

    def test_verify_unit_structure_prose_kept_ok(self) -> None:
        unit = self._unit_with(
            "<0000001> hello <0000002>", ["<0000001>", "<0000002>"]
        )
        self.assertEqual(
            verify_unit_structure(unit, "<0000001> 안녕 <0000002>"), []
        )

    def test_verify_unit_structure_whitespace_gap_not_prose_drop(self) -> None:
        # whitespace-only source gaps are the separator-repair's job
        unit = self._unit_with("<0000001>\n<0000002>", ["<0000001>", "<0000002>"])
        self.assertEqual(verify_unit_structure(unit, "<0000001><0000002>"), [])

    def test_separator_gap_grown_prefix_tokens(self) -> None:
        # masker prefix grew to 7-digit tokens — the old 6-digit regex
        # would not find the next token; the token-list look-up must
        from translation.translate_passages import _next_tokens, _separator_gap

        artifact = mock.Mock()
        artifact.masked_text = "<0000000>\n\t<0000001>"
        artifact.placeholders = [
            mock.Mock(placeholder="<0000000>"),
            mock.Mock(placeholder="<0000001>"),
        ]
        self.assertEqual(
            _separator_gap("<0000000>\n\t<0000001>", 9, _next_tokens(artifact, 0)),
            "\n\t",
        )
        self.assertIsNone(
            _separator_gap("<0000000> prose <0000001>", 9, _next_tokens(artifact, 0))
        )

    def test_l2_retry_hint_mentions_problem(self) -> None:
        hint = _l2_retry_hint(["reorder", "foreign_token"])
        self.assertIn("reorder", hint)
        self.assertIn("foreign_token", hint)

    def test_client_singleton_vertex_adc(self) -> None:
        # Vertex (ADC) client: one singleton, project from the environment
        from translation import client

        with mock.patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "test-project"}):
            with mock.patch("translation.client.genai.Client") as fake_client:
                c1 = client.get_client()
                c2 = client.get_client()
        self.assertIs(c1, c2)
        fake_client.assert_called_once_with(
            vertexai=True, project="test-project", location="global"
        )
        # without a project the client must fail loudly
        client._client = None
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                client.get_client()
        client._client = None

    def test_safety_config_default_is_empty(self) -> None:
        # provider default unless a threshold was chosen explicitly
        from translation.client import _safety_config

        self.assertEqual(_safety_config(), {})
        self.assertEqual(_safety_config("default"), {})
        with self.assertRaises(ValueError):
            _safety_config("bogus")

    def test_safety_config_block_none_covers_all_categories(self) -> None:
        from translation.client import _SAFETY_CATEGORIES, _safety_config

        config = _safety_config("block-none")
        settings = config["safety_settings"]
        self.assertEqual(len(settings), len(_SAFETY_CATEGORIES))
        for setting, category in zip(settings, _SAFETY_CATEGORIES):
            self.assertEqual(setting.category, category)
            self.assertEqual(setting.threshold, "BLOCK_NONE")

    def test_is_english_echo(self) -> None:
        from translation.client import _is_english_echo

        prose_unit = self._unit_with("Hello <0000001> world", ["<0000001>"])
        self.assertTrue(_is_english_echo("Hello <0000001> world", prose_unit))
        self.assertFalse(_is_english_echo("안녕 <0000001> 세상", prose_unit))
        # all-placeholder unit: an identical output is correct, not an echo
        tokens_unit = self._unit_with("<0000001>\n\t<0000002>", ["<0000001>", "<0000002>"])
        self.assertFalse(_is_english_echo("<0000001>\n\t<0000002>", tokens_unit))

    def test_translate_unit_retries_english_echo(self) -> None:
        from translation.client import TranslatedUnit, translate_unit

        calls = {"n": 0}

        def fake_generate(user_text, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return "Hello <0000001> world"  # echo
            return "안녕 <0000001> 세계"

        with mock.patch("translation.client._generate", fake_generate):
            tu = translate_unit(self._unit_with("Hello <0000001> world", ["<0000001>"]))
        self.assertEqual(tu.translated_text, "안녕 <0000001> 세계")
        self.assertEqual(calls["n"], 2)

    def test_l2_retry_hint_prose_drop_extra_instruction(self) -> None:
        hint = _l2_retry_hint(["prose_drop"])
        self.assertIn("Keep the text between the placeholder tokens intact", hint)

    def _passage_with_vars(self, name: str = "One") -> object:
        """Passage whose body contains two naked variables ($x $y), which
        the masker turns into two placeholder tokens."""
        self.file.write_text(
            ":: One\n\nHello $x $y world.\n\n:: Two\n\nSecond passage here.\n\n",
            encoding="utf-8",
        )
        return self._passage(name)

    def test_translate_passage_l2_recovers_reorder(self) -> None:
        # First attempt reorders tokens; the L2 retry returns a clean unit.
        from translation.client import TranslatedUnit

        calls = {"n": 0}

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return TranslatedUnit(
                    unit=unit, translated_text="<0000001> world <0000000> hello"
                )
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        passage = self._passage_with_vars()
        with mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(
                self.file, passage, request_id="req_test", store_records={}
            )
        self.assertEqual(reason, "ok")
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record["l2_retries"], 1)
        self.assertEqual(record["api_calls"], calls["n"])

    def test_translate_passage_l2_persistent_foreign_token_fails_with_reason(self) -> None:
        from translation.client import TranslatedUnit

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(
                unit=unit,
                translated_text="<0000000> <0000001> hello <0000002>",
            )

        passage = self._passage_with_vars()
        with mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(
                self.file, passage, request_id="req_test", store_records={}
            )
        self.assertIsNone(record)
        self.assertEqual(reason, "foreign_token")

    def test_translate_passage_l2_retry_drop_reports_placeholder_drop(self) -> None:
        # The L2 retry loop must report the retry's own failure mode, not a
        # stale pre-loop reason (reorder) when the retry dropped a token.
        from translation.client import TranslatedUnit

        calls = {"n": 0}

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return TranslatedUnit(
                    unit=unit, translated_text="<0000001> world <0000000> hello"
                )
            return TranslatedUnit(unit=unit, translated_text="<0000001> hello")

        passage = self._passage_with_vars()
        with mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(
                self.file, passage, request_id="req_test", store_records={}
            )
        self.assertIsNone(record)
        self.assertEqual(reason, "placeholder_drop")

    def test_repaired_flag(self) -> None:
        from translation.client import TranslatedUnit

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            # identity, but drop the whitespace separator between variables
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        data = self.file.read_bytes()
        source = parse_file(data, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        # identity translation never changes separators → repaired False
        with mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(
                self.file, passage, request_id="req_test", store_records={}
            )
        self.assertEqual(reason, "ok")
        assert record is not None
        self.assertFalse(record["repaired"])

    def test_rel_source_path(self) -> None:
        game = self.root / "game"
        p = game / "a" / "b.twee"
        self.assertEqual(_rel_source_path(p, game), "a/b.twee")
        self.assertEqual(_rel_source_path(p, None), p.as_posix())

    def test_translate_passage_identity_mock(self) -> None:
        # Identity translation (unit masked text passed through) must produce
        # a valid record whose translated_text == source body.
        from translation.client import TranslatedUnit

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        data = self.file.read_bytes()
        source = parse_file(data, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        with mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(self.file, passage, request_id="req_test", store_records={})
        self.assertIsNotNone(record)
        self.assertEqual(reason, "ok")
        assert record is not None
        self.assertEqual(record["source"], "gemini")
        self.assertEqual(record["level"], "passage")
        self.assertTrue(record["placeholder_ok"])
        self.assertEqual(record["translated_text"], record["source_text"])
        self.assertEqual(record["created_at"][-6:], "+09:00")

    def test_translate_passage_skip_existing(self) -> None:
        from translation.client import TranslatedUnit

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        data = self.file.read_bytes()
        source = parse_file(data, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        body = data[passage.body_span.start : passage.body_span.end].decode("utf-8")
        existing = {
            source_hash(body): [{
                "source_text_hash": source_hash(body),
                "source_text": body,
                "translated_text": body,
                "source_path": str(self.file),
                "passage_name": "One",
                "placeholder_ok": True,
                "level": "passage",
                "source": "gemini",
            }]
        }
        with mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(self.file, passage, request_id="req_test", store_records=existing)
        self.assertIsNone(record)


if __name__ == "__main__":
    unittest.main()
