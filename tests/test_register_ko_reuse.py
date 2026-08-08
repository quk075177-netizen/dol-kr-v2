from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from translation.register_ko_reuse import make_record, match_boundaries, register_ko_reuse
from translation.store import source_hash

SOURCE_BODY = (
    "You walk into the shop.\n"
    "<<npc>> looks at you with <<eyes>>.\n"
    "Do you want to buy it?\n"
)


def row_with(ko_body: str, passage_name: str = "Test Passage", source_body: str | None = None) -> dict:
    return {
        "passage_name": passage_name,
        "source_path": "overworld-town/loc-test/main.twee",
        "source_body": source_body or SOURCE_BODY,
        "ko_body": ko_body,
    }


class MatchBoundariesTests(unittest.TestCase):
    def test_leading_trailing_newlines_preserved(self) -> None:
        source = "\n\n" + SOURCE_BODY + "\n\n"
        translated = "상점 안으로 걸어 들어간다.\n"
        self.assertEqual(
            match_boundaries(source, translated),
            "\n\n상점 안으로 걸어 들어간다.\n\n\n",
        )

    def test_no_trailing_newlines(self) -> None:
        self.assertEqual(
            match_boundaries(SOURCE_BODY, "번역본"),
            "번역본\n",
        )


class MakeRecordTests(unittest.TestCase):
    def test_post_status_none(self) -> None:
        record = make_record(row_with("번역본"), "번역본", level="passage")
        self.assertEqual(record["post_status"], "none")
        self.assertEqual(record["source"], "ko_reuse")
        self.assertEqual(record["level"], "passage")
        self.assertTrue(record["placeholder_ok"])
        self.assertEqual(record["record_id"], f"tr_{source_hash(SOURCE_BODY)[:12]}_ko")

    def test_post_status_static_done(self) -> None:
        ko = "길을 걷는다"
        record = make_record(row_with("길【을를】 걷는다"), ko, level="passage")
        self.assertEqual(record["post_status"], "static_done")

    def test_post_status_runtime_remaining(self) -> None:
        ko = "<<npc>>{{post:이가}} 본다"
        record = make_record(row_with("<<npc>>【이가】 본다"), ko, level="passage")
        self.assertEqual(record["post_status"], "runtime_remaining")


class RegisterKoReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.triple = self.root / "triple.jsonl"
        self.out = self.root / "out.jsonl"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_triple(self, rows: list[dict]) -> None:
        self.triple.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )

    def test_marker_passages_registered_with_runtime_markers(self) -> None:
        base = "You enter the shop.\n<<npc>> watches you with <<eyes>>.\nBuy it?\n"
        rows = [
            row_with("상점에 들어선다.\n<<npc>>{{post:이가}} <<eyes>>로 노려본다.\n살까?\n", "Marker One", base + "A"),
            row_with("상점에 들어선다.\n<<npc>>{{post:은는}} <<eyes>>가 따뜻하다.\n살까?\n", "Marker Two", base + "B"),
            row_with("상점에 들어선다.\n<<npc>>가 <<eyes>>를 바라본다.\n살까?\n", "No Marker", base + "C"),
        ]
        self.write_triple(rows)
        stats = register_ko_reuse(self.triple, self.out)
        self.assertEqual(stats["registered"], 3)
        self.assertEqual(stats["with_marker"], 2)
        self.assertEqual(stats["no_marker"], 1)
        records = [json.loads(l) for l in self.out.read_text(encoding="utf-8").splitlines()]
        by_name = {r["passage_name"]: r for r in records}
        self.assertEqual(by_name["Marker One"]["post_status"], "runtime_remaining")
        self.assertIn("{{post:이가}}", by_name["Marker One"]["translated_text"])
        self.assertEqual(by_name["Marker Two"]["post_status"], "runtime_remaining")
        self.assertEqual(by_name["No Marker"]["post_status"], "none")

    def test_re_run_is_idempotent(self) -> None:
        rows = [row_with("상점에 들어선다.\n<<npc>>{{post:이가}} <<eyes>>로 노려본다.\n살까?\n", "Marker One")]
        self.write_triple(rows)
        register_ko_reuse(self.triple, self.out)
        stats = register_ko_reuse(self.triple, self.out)
        self.assertEqual(stats["already_registered"], 1)
        self.assertEqual(stats["registered"], 0)
        records = [json.loads(l) for l in self.out.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)

    def test_skeleton_mismatch_skipped(self) -> None:
        row = row_with("상점에 들어선다.\n<<npc>>{{post:이가}} <<eyes>>로 노려본다.\n살까?\n", "Broken")
        row["ko_body"] = "<<if $x>>깨진 구조"
        self.write_triple([row])
        stats = register_ko_reuse(self.triple, self.out)
        self.assertEqual(stats["registered"], 0)
        self.assertTrue(
            "skeleton_mismatch" in stats["skipped"]
            or "macro_sequence_mismatch" in stats["skipped"]
        )
        self.assertFalse(self.out.exists())

    def test_macro_sequence_mismatch_skipped(self) -> None:
        # KO body drops a macro inside a link label — invisible to the
        # parser's protected spans but caught by the macro-sequence check.
        row = row_with(
            "[[로빈에게 말한다|Temple Confess Self Temptation Goad]]",
            "Link Drop",
        )
        row["source_body"] = (
            "You share your thoughts with <<him>>.\n"
            '[[Tell <<him>> that you are tempted|Temple Confess Self Temptation Goad]]'
        )
        self.write_triple([row])
        stats = register_ko_reuse(self.triple, self.out)
        self.assertEqual(stats["registered"], 0)
        self.assertIn("macro_sequence_mismatch", stats["skipped"])

    def test_marker_normalized_from_legacy_form(self) -> None:
        row = row_with("상점에 들어선다.\n<<npc>>【이가】 <<eyes>>로 노려본다.\n살까?\n", "Legacy")
        self.write_triple([row])
        register_ko_reuse(self.triple, self.out)
        record = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertIn("{{post:이가}}", record["translated_text"])
        self.assertNotIn("【", record["translated_text"])


if __name__ == "__main__":
    unittest.main()
