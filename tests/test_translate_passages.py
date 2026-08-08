from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH

from translation.store import source_hash
from translation.translate_passages import (
    _rel_source_path,
    _skeleton_ok,
    next_request_id,
    repair_separator_newlines,
    translate_passage,
    verify_separator_newlines,
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

    def test_rel_source_path(self) -> None:
        game = self.root / "game"
        p = game / "a" / "b.twee"
        self.assertEqual(_rel_source_path(p, game), "a/b.twee")
        self.assertEqual(_rel_source_path(p, None), p.as_posix())

    def test_translate_passage_identity_mock(self) -> None:
        # Identity translation (unit masked text passed through) must produce
        # a valid record whose translated_text == source body.
        from translation.client import TranslatedUnit

        def fake_translate(unit, index=0, total=1):
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

        def fake_translate(unit, index=0, total=1):
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
