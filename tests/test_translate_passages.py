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

    def test_separator_repair_survives_reordered_tokens(self) -> None:
        # Option E tolerates reorders of display-only tokens; the separator
        # repair must not abort on the moved token (monotonic cursor bug)
        # — otherwise every later separator stays broken and L3 merges spans.
        from pretranslation_cst.masking import mask_passage

        raw = (
            b":: One\n\n"
            b"$a says as $b reaches for $c phone.\n"
            b"<br><br>\n"
            b"$d moves in front of $e desk.\n\n"
        )
        source = parse_file(raw, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        artifact = mask_passage(raw, passage)
        tokens = [ph.placeholder for ph in artifact.placeholders]
        self.assertEqual(len(tokens), 6)  # $a $b $c <br><br> $d $e
        # swap $b/$c (reordered), and drop the "\n" separator before <br><br>
        joined = (
            tokens[0] + " says as " + tokens[2] + " reaches for " + tokens[1]
            + " phone." + tokens[3] + tokens[4] + " moves in front of desk."
        )
        repaired = repair_separator_newlines(artifact, joined)
        self.assertEqual(len(verify_separator_newlines(artifact, repaired)), 0)
        self.assertIn(tokens[3] + "\n", repaired)
        self.assertIn("\n" + tokens[4], repaired)

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

    def _unit_with(self, masked_text: str, ph_tokens: list[str], segments=None):
        from pretranslation_cst.model import Span

        unit = mock.Mock()
        unit.masked_text = masked_text
        unit.ancestors = None
        unit.preceding_context = None
        unit.following_context = None
        unit.segments = segments if segments is not None else []
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

    def test_verify_unit_structure_content_drop(self) -> None:
        # a content unit whose output is whitespace-only was deleted by the
        # model — invisible to the placeholder checks when there are no
        # tokens (observed: "The " fragment -> "\t")
        from pretranslation_cst.model import Span
        from translation.translate_passages import verify_unit_structure

        seg = mock.Mock()
        seg.text = "The "
        seg.source_span = Span(0, 4)
        seg.kind = "plain_text"
        unit = self._unit_with("The ", [], segments=[seg])
        self.assertEqual(verify_unit_structure(unit, "\t"), ["content_drop"])
        self.assertEqual(verify_unit_structure(unit, "그"), [])
        # glue units (no content) are not flagged
        unit2 = self._unit_with("\n\t", [])
        self.assertEqual(verify_unit_structure(unit2, "\n\t"), [])

    def _unit_with_sensitivity(self, masked_text: str, ph_tokens: list[str], sensitive: bool):
        unit = self._unit_with(masked_text, ph_tokens)
        for ph in unit.placeholders:
            ph.order_sensitive = sensitive
        return unit

    def test_verify_unit_structure_reorder_insensitive_tolerated(self) -> None:
        # display-only tokens (pronouns) may move for Korean word order
        unit = self._unit_with_sensitivity(
            "<0000001> hello <0000002>", ["<0000001>", "<0000002>"], sensitive=False
        )
        self.assertEqual(
            verify_unit_structure(unit, "<0000002> 안녕 <0000001>"), []
        )

    def test_verify_unit_structure_reorder_sensitive_flagged(self) -> None:
        unit = self._unit_with_sensitivity(
            "<0000001> hello <0000002>", ["<0000001>", "<0000002>"], sensitive=True
        )
        self.assertEqual(
            verify_unit_structure(unit, "<0000002> 안녕 <0000001>"), ["reorder"]
        )

    def test_verify_unit_structure_reorder_mixed_sensitive_flagged(self) -> None:
        # only one moved token needs to be sensitive
        unit = self._unit_with(
            "<0000001> hello <0000002>", ["<0000001>", "<0000002>"]
        )
        unit.placeholders[0].order_sensitive = False
        unit.placeholders[1].order_sensitive = True
        self.assertEqual(
            verify_unit_structure(unit, "<0000002> 안녕 <0000001>"), ["reorder"]
        )

    def test_canonical_signature(self) -> None:
        from translation.store import canonical_signature

        # insensitive tokens sorted within runs, sensitive keep order
        sig = ["a", "b", "X", "c", "d"]
        sens = [False, False, True, False, False]
        self.assertEqual(canonical_signature(sig, sens), ["a", "b", "X", "c", "d"])
        self.assertEqual(
            canonical_signature(["b", "a", "X", "d", "c"], sens),
            ["a", "b", "X", "c", "d"],
        )
        # a sensitive token moved changes the canonical form
        self.assertNotEqual(
            canonical_signature(["X", "a", "b"], [True, False, False]),
            canonical_signature(["a", "b", "X"], [False, False, True]),
        )

    def test_skeleton_ok_tolerates_insensitive_swap(self) -> None:
        # <<he>>/<<his>> (display-only) swapped across the sentence is fine
        from pretranslation_cst.masking import mask_passage

        raw = (
            b":: One\n\n"
            b"<<he>> face drops as <<his>> phone rings.\n\n"
        )
        source = parse_file(raw, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        artifact = mask_passage(raw, passage)
        swapped_body = b"<<his>> phone rings as <<he>> face drops.\n\n"
        self.assertTrue(_skeleton_ok(artifact, swapped_body, "One", str(self.file)))

    def test_skeleton_ok_rejects_sensitive_swap(self) -> None:
        # moving a <<set>> across a display token breaks the structure
        from pretranslation_cst.masking import mask_passage

        raw = (
            b":: One\n\n"
            b"<<set $x to 1>> face drops as <<he>> rings.\n\n"
        )
        source = parse_file(raw, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        artifact = mask_passage(raw, passage)
        swapped_body = b"<<he>> rings as <<set $x to 1>> face drops.\n\n"
        self.assertFalse(_skeleton_ok(artifact, swapped_body, "One", str(self.file)))

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
        the masker turns into two placeholder tokens (order-insensitive)."""
        self.file.write_text(
            ":: One\n\nHello $x $y world.\n\n:: Two\n\nSecond passage here.\n\n",
            encoding="utf-8",
        )
        return self._passage(name)

    def _passage_multi_unit(self, name: str = "One") -> object:
        """Passage that chunks into several content units (no-merge policy:
        repeated containers stay separate units) — exercises the multi-item
        batch path.  Long enough to clear the 700-char threshold."""
        self.file.write_text(
            ":: One\n\nIntro text here. "
            + "<<if $flag>>Branch content that is long enough to be its own unit."
              "<</if>> " * 14
            + "\n\n:: Two\n\nSecond passage here.\n\n",
            encoding="utf-8",
        )
        return self._passage(name)

    def _passage_with_set(self, name: str = "One") -> object:
        """Passage whose body contains a <<set>> and a <<run>> macro (two
        order-sensitive placeholder tokens)."""
        self.file.write_text(
            ":: One\n\n<<set $x to 1>> hello <<run $y>> world.\n\n"
            ":: Two\n\nSecond passage here.\n\n",
            encoding="utf-8",
        )
        return self._passage(name)

    def test_translate_passage_variable_reorder_accepted(self) -> None:
        # $x/$y are order-insensitive: a swap is the model naturalising
        # word order — no L2 retry, record is stored as-is
        from translation.client import TranslatedUnit

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(
                unit=unit, translated_text="<0000001> world <0000000> hello"
            )

        passage = self._passage_with_vars()
        with mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(
                self.file, passage, request_id="req_test", store_records={}
            )
        self.assertEqual(reason, "ok")
        assert record is not None
        self.assertEqual(record["l2_retries"], 0)
        # restored: $x and $y sit at the swapped (reordered) positions
        self.assertEqual(record["translated_text"], "$y world $x hello")

    def test_translate_passage_l2_recovers_reorder(self) -> None:
        # First attempt reorders sensitive tokens; the L2 retry returns a
        # clean unit.
        from translation.client import TranslatedUnit

        calls = {"n": 0}

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return TranslatedUnit(
                    unit=unit, translated_text="<0000001> world <0000000> hello"
                )
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        passage = self._passage_with_set()
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

    def test_translate_units_batch_protocol_validation(self) -> None:
        from translation.client import translate_units_batch

        unit_a = self._unit_with("Hello <0000001> world", ["<0000001>"])
        unit_b = self._unit_with("Second <0000002> line", ["<0000002>"])
        real_units = [unit_a, unit_b]
        good_json = json.dumps({
            "translations": [
                {"requestId": "u0000", "target": "안녕 <0000001> 세계"},
                {"requestId": "u0001", "target": "두 번째 <0000002> 문장"},
            ]
        })
        with mock.patch("translation.client._generate", return_value=good_json):
            texts = translate_units_batch(real_units)
        self.assertEqual(len(texts), 2)
        # wrong order → protocol error
        bad_json = json.dumps({
            "translations": [
                {"requestId": "u0001", "target": "x"},
                {"requestId": "u0000", "target": "y"},
            ]
        })
        with mock.patch("translation.client._generate", return_value=bad_json):
            with self.assertRaises(RuntimeError):
                translate_units_batch(real_units)
        # invalid JSON → protocol error
        with mock.patch("translation.client._generate", return_value="not json"):
            with self.assertRaises(RuntimeError):
                translate_units_batch(real_units)

    def test_translate_passage_batch_path_with_escalation(self) -> None:
        # batch translate: each unit's batch output drops a placeholder →
        # flash escalation (single call per unit) recovers them → passage
        # succeeds with the batch path exercised (multiple content units)
        from translation.client import TranslatedUnit
        from translation.translate_passages import translate_units_batch

        passage = self._passage_multi_unit()

        def fake_batch(units, model=None, **kwargs):
            out = []
            for unit in units:
                text = unit.masked_text
                if unit.placeholders:
                    text = text.replace(unit.placeholders[0].placeholder, "", 1)
                out.append(text)
            return out

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            # the escalation call fixes the drop
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        with mock.patch("translation.translate_passages.translate_units_batch", fake_batch), \
             mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(
                self.file, passage, request_id="req_test", store_records={},
                batch_size=2,
            )
        self.assertEqual(reason, "ok")
        assert record is not None
        self.assertIs(record["escalated"], True)
        self.assertGreater(record["escalated_units"], 0)
        self.assertEqual(record["tier"], "escalated")

    def test_translate_passage_batch_fallback_on_protocol_error(self) -> None:
        # batch request fails (bad JSON) → per-unit fallback for that batch
        from translation.client import TranslatedUnit
        from translation.translate_passages import translate_units_batch

        passage = self._passage_multi_unit()

        def fake_batch(units, model=None, **kwargs):
            raise RuntimeError("batch: invalid JSON response")

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        with mock.patch("translation.translate_passages.translate_units_batch", fake_batch), \
             mock.patch("translation.translate_passages.translate_unit", fake_translate):
            record, reason = translate_passage(
                self.file, passage, request_id="req_test", store_records={},
                batch_size=2,
            )
        self.assertEqual(reason, "ok")
        assert record is not None
        self.assertIs(record["escalated"], False)
        self.assertEqual(record["tier"], "base")

    def _tu(self, unit, text):
        from translation.client import TranslatedUnit

        return TranslatedUnit(unit=unit, translated_text=text)

    def test_reuse_unit_hit_and_miss(self) -> None:
        from translation.translate_passages import _reuse_unit, _restore_unit_text

        unit = self._unit_with("<0000001> hello <0000002>", ["<0000001>", "<0000002>"])
        unit.placeholders[0].original_text = "A"
        unit.placeholders[1].original_text = "B"
        key = source_hash(_restore_unit_text(unit))
        # miss: empty store
        self.assertIsNone(_reuse_unit(unit, None))
        self.assertIsNone(_reuse_unit(unit, {}))
        # hit: restored translation is re-tokenised for this unit
        records = {key: [{"source_text_hash": key, "translated_text": "안녕 A 세계 B"}]}
        hit = _reuse_unit(unit, records)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.translated_text, "안녕 <0000001> 세계 <0000002>")
        # corrupt: stored text misses an original -> cannot be reused
        records = {key: [{"source_text_hash": key, "translated_text": "안녕 A"}]}
        self.assertIsNone(_reuse_unit(unit, records))

    def test_translate_passage_unit_reuse_skips_api(self) -> None:
        # A passage whose units all exist in the unit store translates with
        # zero API calls (batch and non-batch paths) and records the count.
        from pretranslation_cst.chunking import chunk_passage
        from pretranslation_cst.masking import mask_passage
        from translation.translate_passages import _restore_unit_text

        long_body = (
            "Intro text that is long enough to split. "
            "<<if $x>>Branch one with prose and a bit more text.<</if>> "
            "<<switch $y>><<case 1>>Case one<<case 2>>Case two<</switch>> "
            "Trailing text here to push the size up a little. "
        ) * 10
        self.file.write_text(":: One\n\n" + long_body + "\n\n", encoding="utf-8")
        data = self.file.read_bytes()
        source = parse_file(data, str(self.file), DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "One")
        artifact = mask_passage(data, passage)
        units = chunk_passage(passage, artifact, data)
        self.assertGreater(len(units), 1)
        units_records: dict[str, list[dict]] = {}
        for unit in units:
            key = source_hash(_restore_unit_text(unit))
            units_records[key] = [{
                "source_text_hash": key,
                "translated_text": _restore_unit_text(unit),
                "placeholder_ok": True,
                "source": "gemini",
                "level": "unit",
            }]
        for batch_size in (1, 2):
            with mock.patch(
                "translation.translate_passages.translate_units_batch",
                side_effect=AssertionError("reuse must skip the batch API"),
            ), mock.patch(
                "translation.translate_passages.translate_unit",
                side_effect=AssertionError("reuse must skip per-unit API"),
            ):
                record, reason = translate_passage(
                    self.file, passage, request_id="req_test", store_records={},
                    batch_size=batch_size, units_records=units_records,
                )
            self.assertEqual(reason, "ok")
            assert record is not None
            # no-merge chunking: units = stored reuse + verbatim glue
            self.assertEqual(
                record["reused_units"] + record.get("glue_units", 0), len(units))
            self.assertGreater(record["reused_units"], 0)

    def test_boundary_prose_drops_detects_merged_boundary(self) -> None:
        from translation.translate_passages import boundary_prose_drops

        artifact = mock.Mock()
        artifact.masked_text = "start <0000001> ENDPROSE <0000002> end"
        unit_a = self._unit_with("<0000001> ENDPROSE", ["<0000001>"])
        unit_b = self._unit_with("ENDPROSE <0000002>", ["<0000002>"])
        # tokens adjacent across the boundary (prose moved away)
        merged = boundary_prose_drops(artifact, [
            self._tu(unit_a, "번역 <0000001>"),
            self._tu(unit_b, "<0000002> 번역"),
        ])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0][0], 0)
        # boundary prose kept → no problem
        kept = boundary_prose_drops(artifact, [
            self._tu(unit_a, "번역 <0000001> 끝"),
            self._tu(unit_b, "시작 <0000002> 번역"),
        ])
        self.assertEqual(kept, [])
        # whitespace-only source gap → separator repair's job, not flagged
        ws_artifact = mock.Mock()
        ws_artifact.masked_text = "start <0000001>\n<0000002> end"
        ws = boundary_prose_drops(ws_artifact, [
            self._tu(unit_a, "번역 <0000001>"),
            self._tu(unit_b, "<0000002> 번역"),
        ])
        self.assertEqual(ws, [])

    def test_translate_passage_l3_terminal_no_whole_retry(self) -> None:
        # L3 skeleton_mismatch is terminal — no whole-passage retry; the
        # fail log collects the data for a later, deliberate re-run
        from translation.client import TranslatedUnit

        calls = {"n": 0}

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            calls["n"] += 1
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        with mock.patch("translation.translate_passages.translate_unit", fake_translate), \
             mock.patch("translation.translate_passages._skeleton_ok", return_value=False):
            record, reason = translate_passage(
                self.file, self._passage("One"), request_id="req_test",
                store_records={},
            )
        self.assertIsNone(record)
        self.assertEqual(reason, "skeleton_mismatch")
        # exactly one pass over the units — no second full run
        self.assertEqual(calls["n"], 1)

    def test_translate_passage_l3_escalation_terminal_failure(self) -> None:
        # both tiers fail L3 → terminal, no further attempts
        from translation.client import TranslatedUnit

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        with mock.patch("translation.translate_passages.translate_unit", fake_translate), \
             mock.patch("translation.translate_passages._skeleton_ok", return_value=False):
            record, reason = translate_passage(
                self.file, self._passage("One"), request_id="req_test",
                store_records={},
            )
        self.assertIsNone(record)
        self.assertEqual(reason, "skeleton_mismatch")

    def test_translate_passage_writes_unit_store(self) -> None:
        # unit-level store: one line per chunk unit, source restored to
        # original bytes, translation stored alongside
        from translation.client import TranslatedUnit
        import tempfile

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        units_path = Path(tempfile.mktemp(suffix=".jsonl"))
        try:
            with mock.patch("translation.translate_passages.translate_unit", fake_translate):
                record, reason = translate_passage(
                    self.file, self._passage_with_vars(), request_id="req_test",
                    store_records={}, units_store=units_path,
                )
            self.assertEqual(reason, "ok")
            lines = [json.loads(l) for l in units_path.read_text(encoding="utf-8").splitlines()]
            self.assertGreaterEqual(len(lines), 1)
            unit_rec = lines[0]
            self.assertEqual(unit_rec["level"], "unit")
            self.assertEqual(unit_rec["source"], "gemini")
            self.assertEqual(unit_rec["unit_index"], 1)
            # source text is the ORIGINAL unit text (no placeholder tokens)
            self.assertNotIn("<0", unit_rec["source_text"])
            self.assertIn("$x", unit_rec["source_text"])
            self.assertEqual(unit_rec["translated_text"], unit_rec["source_text"])
            self.assertEqual(unit_rec["record_id"], f"un_{unit_rec['source_text_hash'][:12]}")
        finally:
            units_path.unlink(missing_ok=True)

    def test_translate_passage_journal_streams_passage_and_fails(self) -> None:
        from translation.client import TranslatedUnit
        import tempfile

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            return TranslatedUnit(unit=unit, translated_text=unit.masked_text)

        journal_path = Path(tempfile.mktemp(suffix=".jsonl"))
        try:
            with mock.patch("translation.translate_passages.translate_unit", fake_translate):
                record, reason = translate_passage(
                    self.file, self._passage("One"), request_id="req_test",
                    store_records={}, journal=journal_path,
                )
            self.assertEqual(reason, "ok")
            lines = [json.loads(l) for l in journal_path.read_text(encoding="utf-8").splitlines()]
            kinds = [l["kind"] for l in lines]
            # no per-unit ok noise — only the passage outcome
            self.assertEqual(kinds, ["passage"])
            self.assertEqual(lines[0]["status"], "ok")
            assert record is not None
            self.assertEqual(lines[0]["record_id"], record["record_id"])
            self.assertNotIn("request_id", lines[0])
        finally:
            journal_path.unlink(missing_ok=True)

    def test_translate_passage_journal_records_fail_events(self) -> None:
        # a unit that fails L1 and is recovered by escalation logs a fail
        # event with the recovery info — the re-run queue
        from translation.client import TranslatedUnit
        import tempfile

        def fake_translate(unit, index=0, total=1, hint=None, model=None):
            if model == "gemini-2.5-flash":
                return TranslatedUnit(unit=unit, translated_text=unit.masked_text)
            return TranslatedUnit(unit=unit, translated_text="<0000000> 안녕")

        journal_path = Path(tempfile.mktemp(suffix=".jsonl"))
        try:
            with mock.patch("translation.translate_passages.translate_unit", fake_translate):
                record, reason = translate_passage(
                    self.file, self._passage_with_vars(), request_id="req_test",
                    store_records={}, journal=journal_path,
                )
            self.assertEqual(reason, "ok")
            lines = [json.loads(l) for l in journal_path.read_text(encoding="utf-8").splitlines()]
            fails = [l for l in lines if l["kind"] == "fail"]
            self.assertGreaterEqual(len(fails), 1)
            self.assertEqual(fails[0]["reason"], "placeholder_drop")
            self.assertEqual(fails[0]["recovered_by"], "gemini-2.5-flash")
            self.assertIn("source_path", fails[0])
            self.assertIn("passage_name", fails[0])
            self.assertNotIn("request_id", fails[0])
            passage_line = [l for l in lines if l["kind"] == "passage"][0]
            self.assertEqual(passage_line["status"], "ok")
        finally:
            journal_path.unlink(missing_ok=True)

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

        passage = self._passage_with_set()
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
