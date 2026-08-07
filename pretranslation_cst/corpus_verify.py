"""One-command corpus verification for game/**/*.twee.

Produces a deterministic JSON report with:

* file/passage counts, including empty files that hold zero passages
* split round-trip: split_twee output reassembled from prefix_span plus every
  passage source_span must equal the original file bytes
* mask/restore round-trip failures (restore must be byte-exact)
* tree parent/span/sibling invariants
* diagnostic counts by code and by (code, macro)
* exposed segment kind counts and placeholder counts
* per-passage protected coverage ratios
* baseline deltas for corpus counts (file_count, passage_count,
  twee_byte_count), tracked defect codes and exposure kinds

Source-malformed markup is separated from parser defects through a versioned
allowlist keyed by path, passage name, code and byte span.  Diagnostics that
are neither allowlisted nor in NON_STRUCTURAL_CODES are unexpected and count
as a structural regression.

The report is written with sorted keys and sorted arrays only, so two runs
over the same input produce byte-identical JSON.

Exit code is a bitmask that separates failure classes:

* 0  pass
* 1  round-trip failure (decode/split/reassembly/restore)  (bit 0)
* 2  structural regression (tree invariants, unexpected diagnostics,
     corpus count or tracked baseline deviations)          (bit 1)
* 3  both
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

from .masking import mask_passage, restore_mask
from .model import Passage, SourceFile
from .parser import parse_file, split_twee
from .paths import DEFAULT_VALUE_KIND_PATH

MODULE_DIR = Path(__file__).parent
DATA_DIR = MODULE_DIR / "data"
DEFAULT_VALUE_KINDS = DEFAULT_VALUE_KIND_PATH
DEFAULT_ALLOWLIST = DATA_DIR / "corpus-allowlist-v1.json"
DEFAULT_BASELINE = DATA_DIR / "corpus-baseline-v1.json"
REPORT_VERSION = 1

# Diagnostics that are expected to exist without an allowlist entry.  These are
# value-kind coverage gaps, not parser defects.
NON_STRUCTURAL_CODES = frozenset({"unclassified_argument"})

# Codes that signal parser or source-structure defects.  An increase over the
# baseline, or any occurrence without an allowlist entry, is a regression.
DEFECT_CODES = [
    "malformed_args",
    "mismatched_close",
    "unclosed_container",
    "unclosed_widget",
    "unexpected_branch",
    "invalid_macro_name",
    "malformed_macro",
    "unterminated_comment",
    "closing_macro_args",
    "unexpected_macro_args",
]

# Exposed segment kinds whose decrease signals coverage regression.
EXPOSURE_KINDS = ["link_label", "macro_arg"]

SAMPLE_LIMIT = 20


def _load_json(path: Path) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_allowlist(path: str | Path) -> dict[str, Any]:
    payload = _load_json(Path(path))
    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    return {"version": payload.get("version", 0) if isinstance(payload, dict) else 0, "entries": entries}


def _entry_span_matches(entry: Any, span: Any) -> bool:
    if not isinstance(entry, dict) or not isinstance(span, dict):
        return False
    return entry.get("span") == span


def _index_allowlist(allowlist: dict[str, Any]) -> dict[tuple[Any, ...], list[Any]]:
    """Index allowlist entries by (path, passage, code) for O(1) lookup."""
    index: dict[tuple[Any, ...], list[Any]] = {}
    for entry in allowlist["entries"]:
        if not isinstance(entry, dict):
            continue
        key = (entry.get("path"), entry.get("passage"), entry.get("code"))
        index.setdefault(key, []).append(entry)
    return index


def _find_allowlist_entry(code: str, span: Any, path: str, passage: str, index: dict[tuple[Any, ...], list[Any]]) -> Any:
    for entry in index.get((path, passage, code), ()):
        if _entry_span_matches(entry, span):
            return entry
    return None


def check_tree_invariants(passage: Passage) -> list[dict[str, Any]]:
    """Verify parent/span/sibling invariants for one parsed passage."""
    issues: list[dict[str, Any]] = []
    if passage.root is None:
        return issues
    root = passage.root
    index = passage.node_index
    context = {"path": passage.source_path, "passage": passage.name}

    if root.parent_id is not None:
        issues.append({
            **context,
            "kind": "root_parent",
            "node_id": root.node_id,
            "span": root.span.to_dict(),
            "message": "root node must not have a parent",
        })

    seen: set[str] = set()
    stack = [root]
    reachable: list[Any] = []
    while stack:
        node = stack.pop()
        if node.node_id in seen:
            issues.append({
                **context,
                "kind": "duplicate_node_id",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": "two nodes share one node_id",
            })
            continue
        seen.add(node.node_id)
        reachable.append(node)
        stack.extend(node.children)
    if len(index) != len(seen):
        for node_id in sorted(set(index) - seen)[:SAMPLE_LIMIT]:
            node = index[node_id]
            issues.append({
                **context,
                "kind": "orphan_node",
                "node_id": node_id,
                "span": node.span.to_dict(),
                "message": "node is indexed but not reachable from root",
            })

    limit = len(seen) + 1
    # Cache child positions per parent so sibling checks stay O(1) even for
    # parents with thousands of children (e.g. large widget containers).
    position_cache: dict[int, dict[str, int]] = {}
    for node in reachable:
        if node is root:
            continue
        if node.node_id not in index or index[node.node_id] is not node:
            issues.append({
                **context,
                "kind": "node_index_mismatch",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": "node_id resolves to a different node object",
            })
            continue
        if node.parent_id is None:
            issues.append({
                **context,
                "kind": "parent_missing",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": "non-root node has no parent_id",
            })
            continue
        parent = index.get(node.parent_id)
        if parent is None:
            issues.append({
                **context,
                "kind": "parent_missing",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": "parent_id references an unknown node",
            })
            continue
        positions = position_cache.get(id(parent))
        if positions is None:
            positions = {child.node_id: position for position, child in enumerate(parent.children)}
            position_cache[id(parent)] = positions
        if node.node_id not in positions:
            issues.append({
                **context,
                "kind": "child_missing",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": "node is not listed in its parent's children",
            })
        if node.depth != parent.depth + 1:
            issues.append({
                **context,
                "kind": "depth_mismatch",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": f"depth {node.depth} does not equal parent depth + 1",
            })
        order = positions.get(node.node_id, node.sibling_order)
        if node.sibling_order != order:
            issues.append({
                **context,
                "kind": "sibling_order_mismatch",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": f"sibling_order {node.sibling_order} does not match position {order}",
            })
        if not parent.span.contains(node.span):
            issues.append({
                **context,
                "kind": "span_not_within_parent",
                "node_id": node.node_id,
                "span": node.span.to_dict(),
                "message": "node span is not contained in its parent span",
            })
        chain: set[str] = {node.node_id}
        cursor = parent
        steps = 0
        while cursor is not None and cursor is not root and steps <= limit:
            if cursor.node_id in chain:
                issues.append({
                    **context,
                    "kind": "parent_cycle",
                    "node_id": node.node_id,
                    "span": node.span.to_dict(),
                    "message": "parent chain cycles and never reaches root",
                })
                break
            chain.add(cursor.node_id)
            cursor = index.get(cursor.parent_id) if cursor.parent_id else None
            steps += 1

    for parent in reachable:
        children = parent.children
        for position in range(1, len(children)):
            prev, current = children[position - 1], children[position]
            if current.span.start < prev.span.start:
                issues.append({
                    **context,
                    "kind": "sibling_out_of_order",
                    "node_id": current.node_id,
                    "span": current.span.to_dict(),
                    "message": "sibling byte span starts before previous sibling",
                })
            elif current.span.start < prev.span.end:
                issues.append({
                    **context,
                    "kind": "sibling_overlap",
                    "node_id": current.node_id,
                    "span": current.span.to_dict(),
                    "message": "sibling byte spans overlap",
                })
    return issues


def check_split_round_trip(data: bytes, source: SourceFile) -> str | None:
    """Reassemble prefix_span plus every passage source_span and compare with the
    original file bytes.  Returns a description when bytes are lost or duplicated."""
    parts = [data[source.prefix_span.start:source.prefix_span.end]]
    parts.extend(data[passage.source_span.start:passage.source_span.end] for passage in source.passages)
    reassembled = b"".join(parts)
    if reassembled == data:
        return None
    first_diff = next(
        (index for index, (left, right) in enumerate(zip(data, reassembled)) if left != right),
        min(len(data), len(reassembled)),
    )
    return (
        f"split round-trip mismatch: reassembled {len(reassembled)} bytes, "
        f"expected {len(data)}, first diff at byte {first_diff}"
    )


def analyze_passage(data: bytes, passage: Passage) -> dict[str, Any]:
    body = data[passage.body_span.start:passage.body_span.end]
    restore_error: str | None = None
    segment_kinds: Counter[str] = Counter()
    exposed_segment_count = 0
    placeholder_count = 0
    try:
        artifact = mask_passage(data, passage)
        restored = restore_mask(artifact)
        if restored != body:
            restore_error = f"restored {len(restored)} bytes, expected {len(body)}"
        else:
            segment_kinds = Counter(segment.kind for segment in artifact.segments)
            exposed_segment_count = len(artifact.segments)
            placeholder_count = len(artifact.placeholders)
    except ValueError as exc:
        restore_error = f"mask/restore failure: {exc}"

    body_length = passage.body_span.end - passage.body_span.start
    protected_length = 0
    for span in passage.protected_spans:
        start = max(span.start, passage.body_span.start)
        end = min(span.end, passage.body_span.end)
        protected_length += max(0, end - start)
    coverage = protected_length / body_length if body_length else 0.0

    return {
        "path": passage.source_path,
        "passage": passage.name,
        "body_span": passage.body_span.to_dict(),
        "restore_error": restore_error,
        "segment_kinds": dict(segment_kinds),
        "exposed_segment_count": exposed_segment_count,
        "placeholder_count": placeholder_count,
        "body_bytes": body_length,
        "protected_bytes": protected_length,
        "coverage": coverage,
        "diagnostics": [
            {
                "code": diagnostic.code,
                "macro_name": diagnostic.macro_name,
                "span": diagnostic.span.to_dict() if diagnostic.span is not None else None,
                "message": diagnostic.message,
            }
            for diagnostic in passage.diagnostics
        ],
        "invariant_issues": check_tree_invariants(passage),
    }


def analyze_file(path: Path, value_kind_path: Path, source_path: str | None = None) -> dict[str, Any]:
    data = path.read_bytes()
    resolved = source_path or path.as_posix()
    source = parse_file(data, resolved, value_kind_path)
    split_source = split_twee(data, resolved)
    reassembly_error = check_split_round_trip(data, split_source)
    return {
        "path": resolved,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "reassembly_error": reassembly_error,
        "passages": [analyze_passage(data, passage) for passage in source.passages],
    }


def _analyze_one(args: tuple[Path, Path, Path]) -> tuple[str, dict[str, Any] | None, str | None]:
    """Worker for ProcessPoolExecutor: analyze one file, return (rel, result, error)."""
    path, root_path, value_kind_path = args
    rel = path.relative_to(root_path).as_posix()
    try:
        return rel, analyze_file(path, value_kind_path, source_path=rel), None
    except Exception as exc:
        return rel, None, f"{type(exc).__name__}: {exc}"


def _sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    span = item.get("span") or {}
    return (item.get("path", ""), item.get("passage", ""), item.get("kind", item.get("code", "")), span.get("start", -1), span.get("end", -1))


def compare_baseline(report: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    unexpected = report["allowlist"]["unexpected"]
    unexpected_reasons = [f"{unexpected} unexpected (non-allowlisted) diagnostics"] if unexpected else []
    if not baseline:
        return {
            "present": False,
            "version": None,
            "matched": True,
            "deviations": [],
            "regression": bool(unexpected_reasons),
            "regression_reasons": unexpected_reasons,
        }
    rules = baseline.get("regression_rules", {})
    defect_codes = set(rules.get("defect_codes", DEFECT_CODES))
    exposure_kinds = set(rules.get("exposure_kinds", EXPOSURE_KINDS))
    deviations: list[dict[str, Any]] = []
    regression_reasons: list[str] = []

    baseline_corpus = baseline.get("corpus", {})
    current_corpus = report["corpus"]
    for key in ("file_count", "passage_count", "twee_byte_count"):
        base = baseline_corpus.get(key)
        current = current_corpus.get(key)
        if base is not None and base != current:
            direction = "increase" if current > base else "decrease"
            deviations.append({
                "key": f"corpus.{key}",
                "baseline": base,
                "current": current,
                "direction": direction,
            })
            regression_reasons.append(f"corpus.{key} {direction}d {base} -> {current}")

    baseline_diag = baseline.get("diagnostics_by_code", {})
    current_diag = report["diagnostics"]["by_code"]
    for code in sorted(set(baseline_diag) | set(current_diag)):
        base = baseline_diag.get(code, 0)
        current = current_diag.get(code, 0)
        if base != current:
            deviations.append({
                "key": f"diagnostics.{code}",
                "baseline": base,
                "current": current,
                "direction": "increase" if current > base else "decrease",
            })
            if code in defect_codes and current > base:
                regression_reasons.append(f"diagnostics.{code} increased {base} -> {current}")

    baseline_seg = baseline.get("segments_by_kind", {})
    current_seg = report["segments"]["by_kind"]
    for kind in sorted(set(baseline_seg) | set(current_seg)):
        base = baseline_seg.get(kind, 0)
        current = current_seg.get(kind, 0)
        if base != current:
            deviations.append({
                "key": f"segments.{kind}",
                "baseline": base,
                "current": current,
                "direction": "increase" if current > base else "decrease",
            })
            if kind in exposure_kinds and current < base:
                regression_reasons.append(f"segments.{kind} decreased {base} -> {current}")

    unexpected = report["allowlist"]["unexpected"]
    if unexpected:
        regression_reasons.append(f"{unexpected} unexpected (non-allowlisted) diagnostics")

    return {
        "present": True,
        "version": baseline.get("version"),
        "matched": not deviations,
        "deviations": deviations,
        "regression": bool(regression_reasons),
        "regression_reasons": sorted(regression_reasons),
    }


def compute_exit_code(report: dict[str, Any]) -> int:
    code = 0
    if report["round_trip"]["failures"] > 0:
        code |= 1
    if (
        report["tree_invariants"]["failures"] > 0
        or report["allowlist"]["unexpected"] > 0
        or report["baseline"]["regression"]
    ):
        code |= 2
    return code


def verify_corpus(
    root: str | Path,
    *,
    value_kind_path: str | Path = DEFAULT_VALUE_KINDS,
    allowlist_path: str | Path = DEFAULT_ALLOWLIST,
    baseline_path: str | Path | None = DEFAULT_BASELINE,
    workers: int | None = None,
) -> dict[str, Any]:
    """Verify the whole corpus.

    ``workers`` controls file-level parallelism: ``None`` uses up to 16
    processes, ``1`` runs sequentially in-process (needed by tests that
    monkeypatch ``split_twee`` / ``analyze_file``).
    """
    root_path = Path(root)
    files = sorted(root_path.rglob("*.twee"))
    allowlist = _load_allowlist(Path(allowlist_path))
    allowlist_index = _index_allowlist(allowlist)
    matched_entry_ids: set[int] = set()
    baseline = _load_json(Path(baseline_path) if baseline_path else Path()) or {}

    file_hashes: list[dict[str, Any]] = []
    split_failures: list[dict[str, Any]] = []
    reassembly_failures: list[dict[str, Any]] = []
    passages_total = 0
    files_with_passages = 0
    twee_byte_total = 0
    restore_failures: list[dict[str, Any]] = []
    invariant_issues: list[dict[str, Any]] = []
    invariant_by_kind: Counter[str] = Counter()
    diagnostics_total = 0
    by_code: Counter[str] = Counter()
    by_code_macro: Counter[tuple[str, str]] = Counter()
    allowlisted: Counter[str] = Counter()
    unexpected: list[dict[str, Any]] = []
    unexpected_by_code: Counter[str] = Counter()
    stale_entries: list[dict[str, Any]] = []
    segment_total = 0
    placeholder_total = 0
    by_segment_kind: Counter[str] = Counter()
    coverage_entries: list[dict[str, Any]] = []
    body_byte_total = 0
    protected_byte_total = 0

    def consume(relative_path: str, file_analysis: dict[str, Any] | None, error: str | None) -> None:
        nonlocal twee_byte_total, files_with_passages, passages_total
        nonlocal segment_total, placeholder_total, body_byte_total, protected_byte_total
        nonlocal diagnostics_total
        if error is not None:
            split_failures.append({
                "path": relative_path,
                "error": error,
            })
            return
        assert file_analysis is not None
        file_hashes.append({
            "path": file_analysis["path"],
            "sha256": file_analysis["sha256"],
            "bytes": file_analysis["bytes"],
            "passages": len(file_analysis["passages"]),
        })
        twee_byte_total += file_analysis["bytes"]
        if file_analysis["reassembly_error"]:
            reassembly_failures.append({
                "path": file_analysis["path"],
                "error": file_analysis["reassembly_error"],
            })
        if file_analysis["passages"]:
            files_with_passages += 1
        for passage_analysis in file_analysis["passages"]:
            passages_total += 1
            if passage_analysis["restore_error"]:
                restore_failures.append({
                    "path": passage_analysis["path"],
                    "passage": passage_analysis["passage"],
                    "span": passage_analysis["body_span"],
                    "error": passage_analysis["restore_error"],
                })
            for kind, count in passage_analysis["segment_kinds"].items():
                by_segment_kind[kind] += count
            segment_total += passage_analysis["exposed_segment_count"]
            placeholder_total += passage_analysis["placeholder_count"]
            body_byte_total += passage_analysis["body_bytes"]
            protected_byte_total += passage_analysis["protected_bytes"]
            coverage_entries.append({
                "path": passage_analysis["path"],
                "passage": passage_analysis["passage"],
                "span": passage_analysis["body_span"],
                "body_bytes": passage_analysis["body_bytes"],
                "protected_bytes": passage_analysis["protected_bytes"],
                "coverage": passage_analysis["coverage"],
            })
            for diagnostic in passage_analysis["diagnostics"]:
                diagnostics_total += 1
                code = diagnostic["code"]
                macro = str(diagnostic["macro_name"] or "")
                by_code[code] += 1
                by_code_macro[(code, macro)] += 1
                span = diagnostic["span"]
                entry = _find_allowlist_entry(code, span, passage_analysis["path"], passage_analysis["passage"], allowlist_index)
                if entry is not None:
                    allowlisted[code] += 1
                    matched_entry_ids.add(id(entry))
                    continue
                if code in NON_STRUCTURAL_CODES:
                    continue
                unexpected.append({
                    "path": passage_analysis["path"],
                    "passage": passage_analysis["passage"],
                    "code": code,
                    "macro_name": diagnostic["macro_name"],
                    "span": span,
                    "message": diagnostic["message"],
                })
                unexpected_by_code[code] += 1
            for issue in passage_analysis["invariant_issues"]:
                invariant_issues.append(issue)
                invariant_by_kind[issue["kind"]] += 1

    if workers == 1:
        for path in files:
            relative_path = path.relative_to(root_path).as_posix()
            try:
                consume(relative_path, analyze_file(path, Path(value_kind_path), source_path=relative_path), None)
            except Exception as exc:
                consume(relative_path, None, f"{type(exc).__name__}: {exc}")
    else:
        tasks = [(path, root_path, Path(value_kind_path)) for path in files]
        worker_count = max(1, min(workers or os.cpu_count() or 1, 16))
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            for relative_path, file_analysis, error in executor.map(_analyze_one, tasks):
                consume(relative_path, file_analysis, error)

    stale_entries = [
        entry for entry in allowlist["entries"]
        if isinstance(entry, dict) and id(entry) not in matched_entry_ids
    ]

    restore_failures.sort(key=lambda item: (item["path"], item["passage"], item["span"]["start"]))
    split_failures.sort(key=lambda item: item["path"])
    reassembly_failures.sort(key=lambda item: item["path"])
    invariant_issues.sort(key=_sort_key)
    unexpected.sort(key=_sort_key)
    stale_entries.sort(key=lambda item: (item.get("path", ""), item.get("passage", ""), item.get("code", ""), (item.get("span") or {}).get("start", -1)))
    coverage_entries.sort(key=lambda item: (item["path"], item["span"]["start"]))

    diagnostics_by_code_macro: dict[str, dict[str, int]] = {}
    for (code, macro), count in sorted(by_code_macro.items()):
        diagnostics_by_code_macro.setdefault(code, {})[macro] = count

    report: dict[str, Any] = {
        "version": REPORT_VERSION,
        "corpus": {
            "root": str(root_path),
            "file_count": len(files),
            "files_with_passages": files_with_passages,
            "passage_count": passages_total,
            "twee_byte_count": twee_byte_total,
            "file_hashes": file_hashes,
        },
        "round_trip": {
            "checked_files": len(files),
            "checked_passages": passages_total,
            "split_failures": len(split_failures),
            "reassembly_failures": len(reassembly_failures),
            "restore_failures": len(restore_failures),
            "failures": len(split_failures) + len(reassembly_failures) + len(restore_failures),
            "split_samples": split_failures[:SAMPLE_LIMIT],
            "reassembly_samples": reassembly_failures[:SAMPLE_LIMIT],
            "restore_samples": restore_failures[:SAMPLE_LIMIT],
        },
        "tree_invariants": {
            "checked_passages": passages_total,
            "failures": len(invariant_issues),
            "by_kind": dict(sorted(invariant_by_kind.items())),
            "samples": invariant_issues[:SAMPLE_LIMIT],
        },
        "diagnostics": {
            "total": diagnostics_total,
            "by_code": dict(sorted(by_code.items())),
            "by_code_macro": diagnostics_by_code_macro,
        },
        "allowlist": {
            "path": str(allowlist_path),
            "version": allowlist["version"],
            "matched": sum(allowlisted.values()),
            "matched_by_code": dict(sorted(allowlisted.items())),
            "unexpected": len(unexpected),
            "unexpected_by_code": dict(sorted(unexpected_by_code.items())),
            "stale_entries": stale_entries,
            "samples": unexpected[:SAMPLE_LIMIT],
        },
        "segments": {
            "exposed_segment_count": segment_total,
            "placeholder_count": placeholder_total,
            "by_kind": dict(sorted(by_segment_kind.items())),
        },
        "coverage": {
            "passage_count": len(coverage_entries),
            "body_byte_total": body_byte_total,
            "protected_byte_total": protected_byte_total,
            "mean": (protected_byte_total / body_byte_total) if body_byte_total else 0.0,
            "passages": coverage_entries,
        },
    }
    report["baseline"] = {
        "path": str(baseline_path) if baseline_path else None,
        **compare_baseline(report, baseline),
    }
    report["exit_code"] = compute_exit_code(report)
    return report


def _write_baseline(path: Path, report: dict[str, Any]) -> None:
    baseline = {
        "version": REPORT_VERSION,
        "corpus": {
            "file_count": report["corpus"]["file_count"],
            "passage_count": report["corpus"]["passage_count"],
            "twee_byte_count": report["corpus"]["twee_byte_count"],
        },
        "diagnostics_by_code": report["diagnostics"]["by_code"],
        "segments_by_kind": report["segments"]["by_kind"],
        "regression_rules": {
            "defect_codes": DEFECT_CODES,
            "exposure_kinds": EXPOSURE_KINDS,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _print_summary(report: dict[str, Any]) -> None:
    corpus = report["corpus"]
    round_trip = report["round_trip"]
    invariants = report["tree_invariants"]
    diagnostics = report["diagnostics"]
    allowlist = report["allowlist"]
    segments = report["segments"]
    coverage = report["coverage"]
    baseline = report["baseline"]
    print(f"corpus: {corpus['file_count']} files ({corpus['files_with_passages']} with passages), "
          f"{corpus['passage_count']} passages, {corpus['twee_byte_count']} bytes")
    print(f"round-trip: {round_trip['failures']} failures / {round_trip['checked_files']} files, "
          f"{round_trip['checked_passages']} passages checked "
          f"(split {round_trip['split_failures']}, reassembly {round_trip['reassembly_failures']}, "
          f"restore {round_trip['restore_failures']})")
    print(f"tree invariants: {invariants['failures']} failures / {invariants['checked_passages']} checked")
    print(f"diagnostics: {diagnostics['total']} total")
    for code, count in sorted(diagnostics["by_code"].items()):
        print(f"  {code}: {count}")
    print(f"allowlist: matched {allowlist['matched']}, unexpected {allowlist['unexpected']}")
    kinds = ", ".join(f"{kind} {count}" for kind, count in sorted(segments["by_kind"].items()))
    print(f"segments: {segments['exposed_segment_count']} exposed ({kinds}), "
          f"{segments['placeholder_count']} placeholders")
    print(f"coverage: mean {coverage['mean']:.6f}, "
          f"protected {coverage['protected_byte_total']}/{coverage['body_byte_total']} bytes")
    print(f"baseline: matched={baseline['matched']} deviations={len(baseline['deviations'])} "
          f"regression={baseline['regression']}")
    for deviation in baseline["deviations"]:
        print(f"  delta {deviation['key']}: {deviation['baseline']} -> {deviation['current']} ({deviation['direction']})")
    for reason in baseline["regression_reasons"]:
        print(f"  regression: {reason}")
    print(f"exit code: {report['exit_code']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus verification over game/**/*.twee")
    parser.add_argument("--root", type=Path, default=Path("game"), help="corpus root (default: game)")
    parser.add_argument("--value-kind", type=Path, default=DEFAULT_VALUE_KINDS)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="baseline JSON to compare against")
    parser.add_argument("--report", type=Path, default=Path("corpus-verify-report.json"), help="JSON report output path")
    parser.add_argument("--init-baseline", action="store_true", help="write the current run as the baseline file")
    parser.add_argument("--json", action="store_true", help="also print the full report JSON to stdout")
    parser.add_argument("--workers", type=int, default=None,
                        help="file-level parallelism (default: up to 16 processes; 1 = sequential)")
    args = parser.parse_args(argv)
    report = verify_corpus(
        args.root,
        value_kind_path=args.value_kind,
        allowlist_path=args.allowlist,
        baseline_path=args.baseline,
        workers=args.workers,
    )
    if args.init_baseline:
        _write_baseline(args.baseline, report)
    report_text = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report_text, encoding="utf-8")
    if args.json:
        print(report_text, end="")
    _print_summary(report)
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
