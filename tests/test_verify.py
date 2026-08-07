from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pretranslation_cst import corpus_verify as corpus_module
from pretranslation_cst.corpus_verify import (
    _write_baseline,
    analyze_passage,
    check_split_round_trip,
    check_tree_invariants,
    compare_baseline,
    compute_exit_code,
    verify_corpus,
)
from pretranslation_cst.model import CstNode, Passage, Span
from pretranslation_cst.parser import split_twee
from pretranslation_cst.verify import verify_unclassified


def _fixture_corpus(root: Path) -> Path:
    (root / "one.twee").write_bytes(
        b":: Welcome\nPlain prose here [[Next|Target]] and done.\n"
        b'<<gagged_speech "C-could you take me with you?">>\n'
        b":: Empty\n"
    )
    (root / "two.twee").write_bytes(
        b":: StoryData\n{\"ifid\":\"x\"}\n"
        b":: Broken\nvisible prose\n/* unterminated comment\n"
    )
    (root / "empty.twee").write_bytes(b"")
    return root


def _empty_allowlist(root: Path) -> Path:
    path = root / "allowlist.json"
    path.write_text(json.dumps({"version": 0, "entries": []}), encoding="utf-8")
    return path


def _report_json(report: dict) -> bytes:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


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


class CorpusVerifyTests(unittest.TestCase):
    def test_counts_round_trip_and_segment_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            report = verify_corpus(root, allowlist_path=_empty_allowlist(root), baseline_path=root / "no-baseline.json")
            self.assertEqual(report["corpus"]["file_count"], 3)
            self.assertEqual(report["corpus"]["files_with_passages"], 2)
            self.assertEqual(report["corpus"]["passage_count"], 4)
            self.assertEqual(report["round_trip"]["failures"], 0)
            self.assertEqual(report["round_trip"]["checked_passages"], 4)
            self.assertEqual(report["tree_invariants"]["failures"], 0)
            self.assertEqual(report["segments"]["by_kind"]["link_label"], 1)
            self.assertEqual(report["segments"]["by_kind"]["macro_arg"], 1)
            self.assertEqual(report["diagnostics"]["by_code"]["unterminated_comment"], 1)
            coverage = {entry["passage"]: entry["coverage"] for entry in report["coverage"]["passages"]}
            self.assertEqual(coverage["StoryData"], 1.0)
            self.assertEqual(coverage["Empty"], 0.0)
            self.assertTrue(0.0 < coverage["Welcome"] < 1.0)

    def test_report_is_byte_identical_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            first = verify_corpus(root, allowlist_path=_empty_allowlist(root), baseline_path=root / "no-baseline.json")
            second = verify_corpus(root, allowlist_path=_empty_allowlist(root), baseline_path=root / "no-baseline.json")
            self.assertEqual(_report_json(first), _report_json(second))

    def test_source_malformed_is_allowlisted_and_separated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            allowlist = root / "allowlist.json"
            no_baseline = root / "no-baseline.json"
            without = verify_corpus(root, allowlist_path=_empty_allowlist(root), baseline_path=no_baseline)
            samples = without["allowlist"]["samples"]
            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["code"], "unterminated_comment")
            entry = {
                "path": samples[0]["path"],
                "passage": samples[0]["passage"],
                "code": samples[0]["code"],
                "span": samples[0]["span"],
                "note": "fixture unterminated comment",
            }
            allowlist.write_text(json.dumps({"version": 1, "entries": [entry]}), encoding="utf-8")
            with_list = verify_corpus(root, allowlist_path=allowlist, baseline_path=no_baseline)
            self.assertEqual(with_list["allowlist"]["matched"], 1)
            self.assertEqual(with_list["allowlist"]["unexpected"], 0)
            self.assertEqual(with_list["exit_code"], 0)

    def test_unexpected_diagnostic_is_a_structural_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            no_baseline = root / "no-baseline.json"
            report = verify_corpus(root, allowlist_path=_empty_allowlist(root), baseline_path=no_baseline)
            self.assertEqual(report["exit_code"], 2)
            self.assertTrue(report["baseline"]["regression"])
            reason = "1 unexpected (non-allowlisted) diagnostics"
            self.assertEqual(report["baseline"]["regression_reasons"].count(reason), 1)

    def test_allowlist_stale_entries_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            allowlist = root / "allowlist.json"
            allowlist.write_text(json.dumps({
                "version": 1,
                "entries": [{
                    "path": "one.twee", "passage": "Welcome", "code": "invalid_macro_name",
                    "span": {"start": 0, "end": 1},
                }],
            }), encoding="utf-8")
            report = verify_corpus(root, allowlist_path=allowlist, baseline_path=root / "no-baseline.json")
            self.assertEqual(len(report["allowlist"]["stale_entries"]), 1)

    def test_baseline_deviations_and_regression_flags(self) -> None:
        baseline = {
            "version": 1,
            "corpus": {"file_count": 1, "passage_count": 1},
            "diagnostics_by_code": {"malformed_args": 0, "unclassified_argument": 5},
            "segments_by_kind": {"link_label": 10, "macro_arg": 2},
            "regression_rules": {
                "defect_codes": ["malformed_args", "mismatched_close"],
                "exposure_kinds": ["link_label", "macro_arg"],
            },
        }
        report = {
            "corpus": {"file_count": 1, "passage_count": 1},
            "diagnostics": {"by_code": {"malformed_args": 3, "unclassified_argument": 4}},
            "segments": {"by_kind": {"link_label": 10, "macro_arg": 1}},
            "allowlist": {"unexpected": 0},
        }
        comparison = compare_baseline(report, baseline)
        self.assertFalse(comparison["matched"])
        self.assertTrue(comparison["regression"])
        reasons = comparison["regression_reasons"]
        self.assertIn("diagnostics.malformed_args increased 0 -> 3", reasons)
        self.assertIn("segments.macro_arg decreased 2 -> 1", reasons)
        keys = {deviation["key"] for deviation in comparison["deviations"]}
        self.assertIn("diagnostics.unclassified_argument", keys)

    def test_missing_baseline_is_not_a_regression(self) -> None:
        comparison = compare_baseline(
            {"corpus": {"file_count": 1, "passage_count": 1},
             "diagnostics": {"by_code": {"malformed_args": 1}},
             "segments": {"by_kind": {}},
             "allowlist": {"unexpected": 0}},
            {},
        )
        self.assertFalse(comparison["present"])
        self.assertTrue(comparison["matched"])
        self.assertFalse(comparison["regression"])

    def test_exit_code_separates_failure_classes(self) -> None:
        def report(round_trip: int, invariants: int, unexpected: int, regression: bool) -> dict:
            return {
                "round_trip": {"failures": round_trip},
                "tree_invariants": {"failures": invariants},
                "allowlist": {"unexpected": unexpected},
                "baseline": {"regression": regression},
            }

        self.assertEqual(compute_exit_code(report(0, 0, 0, False)), 0)
        self.assertEqual(compute_exit_code(report(1, 0, 0, False)), 1)
        self.assertEqual(compute_exit_code(report(0, 1, 0, False)), 2)
        self.assertEqual(compute_exit_code(report(0, 0, 1, False)), 2)
        self.assertEqual(compute_exit_code(report(0, 0, 0, True)), 2)
        self.assertEqual(compute_exit_code(report(1, 1, 0, False)), 3)

    def test_tree_invariant_violations_are_detected(self) -> None:
        root = CstNode(Span(0, 10), "passage_root", role="root", node_id="root")
        child = CstNode(Span(0, 5), "text", role="text", node_id="child", parent_id="ghost", depth=1, sibling_order=0)
        root.children.append(child)
        passage = Passage(
            source_path="x.twee", name="T", tags=[],
            header_span=Span(0, 1), name_span=None, body_span=Span(0, 10), source_span=Span(0, 10),
            root=root, node_index={"root": root, "child": child},
        )
        kinds = {issue["kind"] for issue in check_tree_invariants(passage)}
        self.assertIn("parent_missing", kinds)

    def test_restore_failure_is_captured(self) -> None:
        passage = Passage(
            source_path="x.twee", name="T", tags=[],
            header_span=Span(0, 1), name_span=None, body_span=Span(0, 11), source_span=Span(0, 11),
        )
        passage.exposed_candidates = [(Span(0, 6), "a"), (Span(4, 9), "b")]
        result = analyze_passage(b"hello world", passage)
        self.assertIsNotNone(result["restore_error"])
        self.assertIn("mask/restore failure", result["restore_error"])

    def test_split_failure_is_reported_per_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "broken.twee").write_bytes(b":: T\n\xff\xfe not utf-8")
            report = verify_corpus(root, allowlist_path=_empty_allowlist(root), baseline_path=root / "no-baseline.json")
            self.assertEqual(report["round_trip"]["split_failures"], 1)
            self.assertEqual(report["exit_code"], 1)

    def test_split_round_trip_clean_file_reassembles(self) -> None:
        data = b":: A\nhello\n:: B\nworld\n"
        source = split_twee(data, "x.twee")
        self.assertIsNone(check_split_round_trip(data, source))

    def test_split_round_trip_detects_missing_middle_bytes(self) -> None:
        data = b":: A\nhello\n:: B\nworld\n"
        source = split_twee(data, "x.twee")
        first = copy.copy(source.passages[0])
        first.source_span = Span(first.source_span.start, first.source_span.end - 1)
        source.passages[0] = first
        error = check_split_round_trip(data, source)
        self.assertIsNotNone(error)
        self.assertIn("first diff at byte 10", error)

    def test_reassembly_failure_is_reported_and_exit_one(self) -> None:
        real_split = corpus_module.split_twee

        def broken_split(data: bytes, source_path: str = "<memory>"):
            source = real_split(data, source_path)
            if len(source.passages) >= 2:
                first = copy.copy(source.passages[0])
                first.source_span = Span(first.source_span.start, first.source_span.end - 1)
                source.passages[0] = first
            return source

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.twee").write_bytes(b":: One\nhello\n:: Two\nworld\n")
            (root / "b.twee").write_bytes(b":: Three\nx\n")
            with mock.patch.object(corpus_module, "split_twee", side_effect=broken_split):
                report = verify_corpus(root, allowlist_path=_empty_allowlist(root), baseline_path=root / "no-baseline.json")
            self.assertEqual(report["round_trip"]["reassembly_failures"], 1)
            self.assertEqual(report["exit_code"], 1)

    def test_middle_byte_loss_is_a_baseline_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            baseline = root / "baseline.json"
            allowlist = _empty_allowlist(root)
            first = verify_corpus(root, allowlist_path=allowlist, baseline_path=baseline)
            _write_baseline(baseline, first)
            path = root / "one.twee"
            data = path.read_bytes()
            index = data.index(b"Plain")
            path.write_bytes(data[: index + 4] + data[index + 5 :])
            report = verify_corpus(root, allowlist_path=allowlist, baseline_path=baseline)
            self.assertEqual(report["baseline"]["deviations"], [{
                "key": "corpus.twee_byte_count",
                "baseline": 187,
                "current": 186,
                "direction": "decrease",
            }])
            self.assertEqual(report["exit_code"], 2)
            self.assertIn("corpus.twee_byte_count decreased 187 -> 186", report["baseline"]["regression_reasons"])

    def test_deleted_passage_is_a_baseline_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            baseline = root / "baseline.json"
            allowlist = _empty_allowlist(root)
            first = verify_corpus(root, allowlist_path=allowlist, baseline_path=baseline)
            _write_baseline(baseline, first)
            path = root / "one.twee"
            path.write_bytes(path.read_bytes().replace(b":: Empty\n", b""))
            report = verify_corpus(root, allowlist_path=allowlist, baseline_path=baseline)
            self.assertEqual(report["corpus"]["passage_count"], 3)
            self.assertEqual(report["exit_code"], 2)
            self.assertIn("corpus.passage_count decreased 4 -> 3", report["baseline"]["regression_reasons"])

    def test_deleted_file_is_a_baseline_regression(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _fixture_corpus(root)
            baseline = root / "baseline.json"
            allowlist = _empty_allowlist(root)
            first = verify_corpus(root, allowlist_path=allowlist, baseline_path=baseline)
            _write_baseline(baseline, first)
            (root / "empty.twee").unlink()
            report = verify_corpus(root, allowlist_path=allowlist, baseline_path=baseline)
            self.assertEqual(report["corpus"]["file_count"], 2)
            self.assertEqual(report["exit_code"], 2)
            self.assertIn("corpus.file_count decreased 3 -> 2", report["baseline"]["regression_reasons"])


if __name__ == "__main__":
    unittest.main()
