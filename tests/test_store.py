from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from translation.store import (
    append_record,
    find_reuse,
    ko_body_preserves_skeleton,
    load_translations,
    source_hash,
)


def _record(text: str, *, source: str = "gemini", placeholder_ok: bool = True) -> dict:
    return {
        "record_id": f"tr_{source_hash(text)[:12]}_1",
        "source_text_hash": source_hash(text),
        "source_text": text,
        "translated_text": "번역",
        "source_path": "a.twee",
        "passage_name": "P",
        "unit_id": "a.twee:P:0",
        "request_id": "req_test",
        "placeholder_ok": placeholder_ok,
        "post_status": "none",
        "source": source,
        "level": "unit",
    }


class StoreTests(unittest.TestCase):
    def test_load_missing_file(self) -> None:
        self.assertEqual(load_translations("/nonexistent/path.jsonl"), {})

    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "t.jsonl"
            rec = _record("Hello")
            append_record(rec, path)
            loaded = load_translations(path)
            self.assertEqual(list(loaded.keys()), [rec["source_text_hash"]])
            self.assertEqual(loaded[rec["source_text_hash"]][0], rec)

    def test_find_reuse_returns_latest_valid(self) -> None:
        rec1 = _record("Hello")
        rec2 = _record("Hello")
        rec2["translated_text"] = "새 번역"
        records = {rec1["source_text_hash"]: [rec1, rec2]}
        found = find_reuse(rec1["source_text_hash"], records)
        self.assertEqual(found, rec2)

    def test_find_reuse_skips_broken_and_superseded(self) -> None:
        rec1 = _record("Hello", placeholder_ok=False)
        rec2 = _record("Hello", source="ko_reuse")
        rec2["superseded"] = True
        rec3 = _record("Hello")
        records = {rec1["source_text_hash"]: [rec1, rec2, rec3]}
        self.assertEqual(find_reuse(rec1["source_text_hash"], records), rec3)

    def test_find_reuse_miss(self) -> None:
        self.assertIsNone(find_reuse("nope", {"x": []}))

    def test_skeleton_preserved(self) -> None:
        ko = "<<if $x>>안녕<</if>>"
        self.assertTrue(ko_body_preserves_skeleton(ko, ["<<if $x>>", "<</if>>"]))
        self.assertFalse(ko_body_preserves_skeleton(ko, ["<<if $y>>", "<</if>>"]))
        self.assertFalse(ko_body_preserves_skeleton(ko, ["<<if $x>>", "<<else>>"]))
        self.assertFalse(ko_body_preserves_skeleton(ko, ["<</if>>", "<<if $x>>"]))


if __name__ == "__main__":
    unittest.main()
