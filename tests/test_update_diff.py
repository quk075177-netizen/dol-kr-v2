from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH

from translation.store import append_record, source_hash
from translation.update_diff import _classify_one


class UpdateDiffTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.game = self.root / "game"
        self.stores = self.root / "stores"
        self.stores.mkdir(parents=True)
        self.units = self.stores / "ko-units.jsonl"
        body = (
            ":: One\n\nHello world.\n\n"
            ":: Two\n\nSecond passage here.\n\n"
            ":: Three\n\nThird passage here.\n\n"
        )
        self.file = self.game / "sub" / "main.twee"
        self.file.parent.mkdir(parents=True)
        self.file.write_text(body, encoding="utf-8")
        self.passage_file = str(self.file)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _body(self, name: str) -> str:
        data = self.file.read_bytes()
        source = parse_file(data, self.passage_file, DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == name)
        return data[passage.body_span.start:passage.body_span.end].decode("utf-8")

    def test_classify_unchanged_changed_new(self) -> None:
        # One: exact record -> unchanged
        append_record({
            "source_text_hash": source_hash(self._body("One")),
            "source_text": self._body("One"),
            "translated_text": "안녕 세계.",
            "source_path": self.passage_file,
            "passage_name": "One",
            "placeholder_ok": True,
            "level": "passage",
            "source": "ko_reuse",
        }, self.stores / "ko-reuse.jsonl")
        # Two: record for a STALE body -> changed
        append_record({
            "source_text_hash": source_hash("STALE BODY"),
            "source_text": "STALE BODY",
            "translated_text": "옛 번역",
            "source_path": self.passage_file,
            "passage_name": "Two",
            "placeholder_ok": True,
            "level": "passage",
            "source": "ko_reuse",
        }, self.stores / "ko-reuse.jsonl")
        # Three: no record -> new

        rows = _classify_one((
            self.passage_file, [str(self.stores / "ko-reuse.jsonl")],
            str(self.units), str(self.game),
        ))
        by_name = {row["passage_name"]: row for row in rows}
        self.assertEqual(by_name["One"]["status"], "unchanged")
        self.assertEqual(by_name["Two"]["status"], "changed")
        self.assertEqual(by_name["Three"]["status"], "new")
        # changed/new passages carry unit counts
        self.assertGreater(by_name["Three"]["unit_count"], 0)

    def test_classify_reusable_units_counted(self) -> None:
        from pretranslation_cst.chunking import chunk_passage
        from pretranslation_cst.masking import mask_passage

        data = self.file.read_bytes()
        source = parse_file(data, self.passage_file, DEFAULT_VALUE_KIND_PATH)
        passage = next(p for p in source.passages if p.name == "Three")
        artifact = mask_passage(data, passage)
        unit = chunk_passage(passage, artifact, data)[0]
        source_text = unit.masked_text
        for ph in unit.placeholders:
            source_text = source_text.replace(ph.placeholder, ph.original_text, 1)
        append_record({
            "source_text_hash": source_hash(source_text),
            "source_text": source_text,
            "translated_text": source_text,
            "source_path": self.passage_file,
            "passage_name": "Three",
            "placeholder_ok": True,
            "level": "unit",
            "source": "gemini",
        }, self.units)

        rows = _classify_one((
            self.passage_file, [str(self.stores / "ko-reuse.jsonl")],
            str(self.units), str(self.game),
        ))
        three = next(r for r in rows if r["passage_name"] == "Three")
        self.assertEqual(three["status"], "new")
        self.assertGreater(three["reusable_units"], 0)


if __name__ == "__main__":
    unittest.main()
