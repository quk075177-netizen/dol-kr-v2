from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from pretranslation_cst.verify import verify_unclassified


class VerifyUnclassifiedTests(unittest.TestCase):
    def test_missing_macro_and_argument_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / "kinds.json"
            jsonl = root / "rows.jsonl"
            schema.write_text(json.dumps({"macros": {"known": {"args": {"0": {"kind": "structural"}}}}}), encoding="utf-8")
            row = {"cst": {"source_path": "x.twee", "name": "T", "diagnostics": [
                {"code": "unclassified_argument", "macro_name": "unknown", "argument_index": 0},
                {"code": "unclassified_argument", "macro_name": "known", "argument_index": 1},
            ]}}
            jsonl.write_text(json.dumps(row) + "\n", encoding="utf-8")
            report = verify_unclassified(jsonl, schema)
            self.assertTrue(report.ok)
            self.assertEqual(report.macro_missing, 1)
            self.assertEqual(report.argument_missing, 1)

    def test_existing_macro_argument_is_a_violation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema = root / "kinds.json"
            jsonl = root / "rows.jsonl"
            schema.write_text(json.dumps({"macros": {"known": {"args": {"0": {"kind": "structural"}}}}}), encoding="utf-8")
            row = {"cst": {"source_path": "x.twee", "name": "T", "diagnostics": [
                {"code": "unclassified_argument", "macro_name": "known", "argument_index": 0},
            ]}}
            jsonl.write_text(json.dumps(row) + "\n", encoding="utf-8")
            report = verify_unclassified(jsonl, schema)
            self.assertFalse(report.ok)
            self.assertEqual(len(report.violations), 1)


if __name__ == "__main__":
    unittest.main()
