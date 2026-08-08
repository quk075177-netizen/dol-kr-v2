from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH

from translation.assemble_game_ko import assemble, pick_passage_records
from translation.store import source_hash

TWO = (
    ":: One\n\nHello world.\n\n"
    ":: Two\n\nSecond passage here.\n\n"
)


def _record(path: str, name: str, source: str, translated: str) -> dict:
    return {
        "record_id": f"tr_{source_hash(source)[:12]}_ko",
        "source_text_hash": source_hash(source),
        "source_text": source,
        "translated_text": translated,
        "source_path": path,
        "passage_name": name,
        "unit_id": f"{path}:{name}",
        "request_id": "req_test",
        "model": "ko_reuse",
        "placeholder_ok": True,
        "post_status": "none",
        "source": "ko_reuse",
        "level": "passage",
    }


class AssembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.game = self.root / "game"
        self.out = self.root / "game_ko"
        (self.game / "sub").mkdir(parents=True)
        (self.game / "sub" / "main.twee").write_text(TWO, encoding="utf-8")
        (self.game / "app.js").write_text("const x = 1;\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_splice_keeps_other_passage_and_js(self) -> None:
        records = {
            ("sub/main.twee", "Two"): _record(
                "sub/main.twee", "Two", "\nSecond passage here.\n\n", "\n두 번째 패시지입니다.\n\n"
            )
        }
        stats = assemble(records, self.game, self.out)
        self.assertEqual(stats["spliced"], 1)
        self.assertEqual(stats["verify_failed"], 0)
        result = (self.out / "sub" / "main.twee").read_text(encoding="utf-8")
        self.assertIn("Hello world.", result)          # untranslated passage kept
        self.assertIn("두 번째 패시지입니다.", result)   # translated passage spliced
        self.assertNotIn("Second passage here.", result)
        self.assertEqual((self.out / "app.js").read_text(encoding="utf-8"), "const x = 1;\n")

    def test_drift_skipped(self) -> None:
        records = {
            ("sub/main.twee", "Two"): _record(
                "sub/main.twee", "Two", "STALE SOURCE", "두 번째 패시지입니다.\n"
            )
        }
        stats = assemble(records, self.game, self.out)
        self.assertEqual(stats["drift"], 1)
        self.assertEqual(stats["spliced"], 0)
        result = (self.out / "sub" / "main.twee").read_text(encoding="utf-8")
        self.assertIn("Second passage here.", result)

    def test_pick_passage_records_only_latest(self) -> None:
        store = self.root / "store.jsonl"
        rec1 = _record("a.twee", "P", "old", "옛 번역")
        rec2 = _record("a.twee", "P", "old", "새 번역")
        rec2["record_id"] = "tr_x2"
        with store.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(rec1, ensure_ascii=False) + "\n")
            fh.write(json.dumps(rec2, ensure_ascii=False) + "\n")
        chosen, _ = pick_passage_records(store)
        self.assertEqual(chosen[("a.twee", "P")]["translated_text"], "새 번역")

    def test_splice_preserves_boundary_newlines(self) -> None:
        # KO bodies often drop the trailing newline; the next passage header
        # must stay a line start (``::`` at line beginning) or Tweego/SugarCube
        # swallows it into the previous body.
        records = {
            ("sub/main.twee", "Two"): _record(
                "sub/main.twee", "Two", "\nSecond passage here.\n\n", "두 번째 패시지입니다."
            )
        }
        stats = assemble(records, self.game, self.out)
        self.assertEqual(stats["verify_failed"], 0)
        result = (self.out / "sub" / "main.twee").read_text(encoding="utf-8")
        self.assertIn("두 번째 패시지입니다.\n\n", result)
        self.assertIn(":: Two", result)

    def test_multi_passage_same_file_reverse_splice(self) -> None:
        # Two passages of one file must splice correctly: edits are applied
        # in reverse offset order, and each KO body's boundary newlines are
        # preserved so the next passage header stays a line start.
        records = {
            ("sub/main.twee", "One"): _record(
                "sub/main.twee", "One", "\nHello world.\n\n", "안녕하세요."
            ),
            ("sub/main.twee", "Two"): _record(
                "sub/main.twee", "Two", "\nSecond passage here.\n\n", "두 번째 패시지입니다."
            ),
        }
        stats = assemble(records, self.game, self.out)
        self.assertEqual(stats["spliced"], 2)
        self.assertEqual(stats["verify_failed"], 0)
        result = (self.out / "sub" / "main.twee").read_text(encoding="utf-8")
        self.assertIn("안녕하세요.\n\n:: Two", result)
        self.assertIn("두 번째 패시지입니다.\n\n", result)
        self.assertNotIn("Hello world.", result)
        self.assertNotIn("Second passage here.", result)
        # the file still parses into the same two passages
        data = (self.out / "sub" / "main.twee").read_bytes()
        source = parse_file(data, "sub/main.twee", DEFAULT_VALUE_KIND_PATH)
        self.assertEqual([p.name for p in source.passages], ["One", "Two"])

    def test_stale_output_files_removed(self) -> None:
        # A previous run left a stale file; the rebuild must not keep it.
        stale = self.out / "stale.twee"
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text(":: Old\n\nstale\n\n", encoding="utf-8")
        records = {
            ("sub/main.twee", "One"): _record(
                "sub/main.twee", "One", "\nHello world.\n\n", "\n안녕하세요.\n\n"
            )
        }
        assemble(records, self.game, self.out)
        self.assertFalse(stale.exists())
        self.assertTrue((self.out / "sub" / "main.twee").is_file())

    def test_assembled_file_parses(self) -> None:
        records = {
            ("sub/main.twee", "One"): _record(
                "sub/main.twee", "One", "\nHello world.\n\n", "\n안녕하세요.\n\n"
            )
        }
        assemble(records, self.game, self.out)
        data = (self.out / "sub" / "main.twee").read_bytes()
        source = parse_file(data, "sub/main.twee", DEFAULT_VALUE_KIND_PATH)
        names = [p.name for p in source.passages]
        self.assertEqual(names, ["One", "Two"])


if __name__ == "__main__":
    unittest.main()
