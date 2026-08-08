"""Assemble a ``game_ko/`` tree from the English ``game/`` tree and
passage-level translation records (``work/translations/ko-reuse.jsonl``).

The tree is copied verbatim into a staging directory, then every translated
passage body is spliced into its ``.twee`` file at the byte span the parser
recorded for the original body.  Passage headers, tags, file order, and all
other files (JS/CSS/...) stay byte-exact.  Records whose original body no
longer matches the current file (drift) are skipped and reported.  The
staging directory is atomically swapped into place when every file is done,
so a failed run never leaves a half-translated tree.

Usage:
    python3 -m translation.assemble_game_ko --store work/translations/ko-reuse.jsonl
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pretranslation_cst.corpus_verify import collect_known_macro_names
from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH
from translation.store import load_translations, passage_placeholder_signature

GAME_ROOT = Path("game")
GAME_KO_ROOT = Path("game_ko")
DEFAULT_STORE = Path("work/translations/ko-reuse.jsonl")

_SEQ_RE = re.compile(r"<<\s*/?\s*[A-Za-z_]\w*|\[\[|]]|</?[a-z][^>]*>")


def macro_sequence(text: bytes) -> list[str]:
    """Structural fingerprint of a passage body: macro names, link brackets,
    and HTML tags — not their contents (labels are translated)."""
    return _SEQ_RE.findall(text.decode("utf-8", errors="replace"))


_KO_FRAGMENT_RE = re.compile(r"[가-힣]{4,}")


def korean_fragment(text: str) -> str:
    """First Korean run (>=4 hangul chars) of a translated body, or empty —
    the expectation text for the browser smoke passage-list."""
    match = _KO_FRAGMENT_RE.search(text)
    return match.group(0) if match else ""


def pick_passage_records(
    store_path: str | Path,
) -> tuple[dict[tuple[str, str], dict], dict[str, int]]:
    """(source_path, passage_name) -> newest usable passage-level record."""
    records = load_translations(store_path)
    chosen: dict[tuple[str, str], dict] = {}
    skipped = {"non_passage_level": 0, "unusable": 0}
    for group in records.values():
        for record in group:
            if record.get("level") != "passage":
                skipped["non_passage_level"] += 1
                continue
            if not record.get("placeholder_ok", True) or record.get("superseded"):
                skipped["unusable"] += 1
                continue
            chosen[(record["source_path"], record["passage_name"])] = record
    return chosen, skipped


CODE_TAGS = {"widget", "script", "stylesheet"}


def _process_file(
    rel: str,
    items: list[tuple[str, dict]],
    game_root: Path,
    output_root: Path,
    known_names: frozenset[str] | None,
    verify: bool,
) -> dict:
    """Splice one file's translated passages into the staged tree.

    Returns a per-file stats dict.  Runs in worker processes (picklable
    arguments only).
    """
    stats = {
        "files_touched": 0,
        "spliced": 0,
        "spliced_bytes": 0,
        "drift": 0,
        "code_passage_skipped": 0,
        "passage_not_found": 0,
        "parse_error": 0,
        "verify_failed": 0,
        "diagnostics": {},
        "spliced_records": [],
    }
    src = game_root / rel
    dst = output_root / rel
    if not src.is_file():
        stats["file_missing"] += 1
        return stats
    original_data = src.read_bytes()
    data = original_data
    try:
        source = parse_file(data, rel, DEFAULT_VALUE_KIND_PATH)
    except Exception:
        stats["parse_error"] += 1
        return stats
    passages = {passage.name: passage for passage in source.passages}

    edits: list[tuple[int, int, str]] = []
    spliced_names: list[str] = []
    spliced_items: list[tuple[str, dict]] = []
    for name, record in items:
        passage = passages.get(name)
        if passage is None:
            stats["passage_not_found"] += 1
            continue
        if CODE_TAGS & set(passage.tags):
            # widget/script/stylesheet passages are code, not prose —
            # splicing a translation in would break the runtime.
            stats["code_passage_skipped"] += 1
            continue
        start, end = passage.body_span.start, passage.body_span.end
        original = data[start:end].decode("utf-8")
        if original != record["source_text"]:
            stats["drift"] += 1
            continue
        edits.append((start, end, record["translated_text"]))
        spliced_names.append(name)
        spliced_items.append((name, record))
    if not edits:
        return stats

    # splice from the end so earlier offsets stay valid.  The KO body often
    # drops the body's boundary newlines; keep the original leading/trailing
    # whitespace so the next passage header stays a line start (``::`` must
    # begin a line for Tweego/SugarCube).
    for start, end, translated in sorted(edits, reverse=True):
        original_body = data[start:end]
        leading = original_body[: len(original_body) - len(original_body.lstrip(b"\n"))]
        trailing = original_body[len(original_body.rstrip(b"\n")) :]
        new_body = leading + translated.strip("\n").encode("utf-8") + trailing
        data = data[:start] + new_body + data[end:]
    dst.write_bytes(data)
    stats["files_touched"] += 1
    stats["spliced"] += len(edits)
    stats["spliced_bytes"] += sum(len(text.encode("utf-8")) for _, _, text in edits)
    stats["spliced_records"] = [
        (rel, name, record["translated_text"]) for name, record in spliced_items
    ]

    if verify:
        problems = _verify_assembled(
            dst, spliced_names, known_names, original=original_data, original_source=source
        )
        if problems:
            stats["verify_failed"] += len(problems)
            for code in problems:
                stats["diagnostics"][code] = stats["diagnostics"].get(code, 0) + 1
    return stats


def _verify_assembled(
    path: Path,
    spliced_names: list[str],
    known_names: frozenset[str] | None,
    *,
    original: bytes | None = None,
    original_source=None,
) -> list[str]:
    """Reparse a spliced file and validate every spliced passage:

    1. structural diagnostics (unclosed containers, malformed macros, ...)
    2. macro-token sequence equality against the original body
    3. protected-span signature equality (mask both bodies and compare the
       original bytes of the protected spans — the strong skeleton check).

    When ``original``/``original_source`` are given the original parse is
    reused instead of reparsing the original file.
    """
    data = path.read_bytes()
    try:
        source = parse_file(
            data, path.as_posix(), DEFAULT_VALUE_KIND_PATH, _widget_names=known_names
        )
    except Exception:
        return ["parse_error"]
    wanted = set(spliced_names)
    codes: list[str] = []
    if original is not None:
        if original_source is None:
            try:
                original_source = parse_file(
                    original, path.as_posix(), DEFAULT_VALUE_KIND_PATH, _widget_names=known_names
                )
            except Exception:
                return ["parse_error"]
        original_passages = {p.name: p for p in original_source.passages}
        for passage in source.passages:
            if passage.name not in wanted:
                continue
            original_passage = original_passages.get(passage.name)
            if original_passage is None:
                continue
            original_body = original[
                original_passage.body_span.start : original_passage.body_span.end
            ]
            assembled_body = data[passage.body_span.start : passage.body_span.end]
            if macro_sequence(original_body) != macro_sequence(assembled_body):
                codes.append("macro_sequence_mismatch")
            try:
                src_sig = passage_placeholder_signature(
                    _mask_passage(original, original_passage)
                )
                ko_sig = passage_placeholder_signature(_mask_passage(data, passage))
            except Exception:
                codes.append("mask_failed")
                continue
            if src_sig != ko_sig:
                codes.append("skeleton_mismatch")
    for passage in source.passages:
        if passage.name not in wanted:
            continue
        for diagnostic in passage.diagnostics:
            if diagnostic.code in {
                "unclosed_container",
                "malformed_macro",
                "unterminated_comment",
                "invalid_macro_name",
                "unknown_macro",
            }:
                codes.append(diagnostic.code)
    return codes


def _mask_passage(data: bytes, passage):
    from pretranslation_cst.masking import mask_passage

    return mask_passage(data, passage)


def _empty_stats() -> dict:
    return {
        "records": 0,
        "files_touched": 0,
        "spliced": 0,
        "spliced_bytes": 0,
        "drift": 0,
        "code_passage_skipped": 0,
        "passage_not_found": 0,
        "file_missing": 0,
        "parse_error": 0,
        "verify_failed": 0,
        "diagnostics": {},
        "spliced_records": [],
        "copy_seconds": 0.0,
        "splice_seconds": 0.0,
        "verify_seconds": 0.0,
        "total_seconds": 0.0,
    }


def _merge_stats(base: dict, add: dict) -> None:
    for key in ("files_touched", "spliced", "spliced_bytes", "drift",
                "code_passage_skipped", "passage_not_found", "file_missing",
                "parse_error", "verify_failed"):
        base[key] += add.get(key, 0)
    for code, count in add.get("diagnostics", {}).items():
        base["diagnostics"][code] = base["diagnostics"].get(code, 0) + count
    base["spliced_records"].extend(add.get("spliced_records", []))


def _worker(args: tuple) -> tuple[str, dict]:
    rel, items, game_root, output_root, known_names, verify = args
    try:
        return rel, _process_file(
            rel, items, Path(game_root), Path(output_root), known_names, verify
        )
    except Exception as exc:  # worker must never crash the whole pool
        stats = _empty_stats()
        stats["parse_error"] = 1
        return rel, stats


def assemble(
    records: dict[tuple[str, str], dict],
    game_root: Path,
    output_root: Path,
    *,
    verify: bool = True,
    known_names: frozenset[str] | None = None,
    workers: int | None = None,
) -> dict:
    by_file: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for (path, name), record in records.items():
        by_file[path].append((name, record))

    stats = _empty_stats()
    stats["records"] = len(records)
    started = time.monotonic()

    # Stage into a sibling temp dir, then swap atomically at the end so a
    # failed run never leaves a half-translated tree (and stale files from
    # previous runs disappear with the rebuild).
    output_root.parent.mkdir(parents=True, exist_ok=True)
    temp = output_root.parent / f".{output_root.name}.tmp-{os.getpid()}"
    if temp.exists():
        shutil.rmtree(temp)
    shutil.copytree(game_root, temp, symlinks=False)
    stats["copy_seconds"] = round(time.monotonic() - started, 3)

    splice_started = time.monotonic()
    tasks = [
        (rel, items, str(game_root), str(temp), known_names, verify)
        for rel, items in sorted(by_file.items())
    ]
    if workers == 1 or len(tasks) <= 1:
        results = [_worker(task) for task in tasks]
    else:
        pool_size = workers or min(16, os.cpu_count() or 1)
        with ProcessPoolExecutor(max_workers=pool_size) as pool:
            results = list(pool.map(_worker, tasks))
    for rel, file_stats in results:
        _merge_stats(stats, file_stats)
    stats["splice_seconds"] = round(time.monotonic() - splice_started, 3)
    stats["verify_seconds"] = round(stats["verify_seconds"], 3)

    # Atomic swap: move the old tree aside, move the staged tree in, drop
    # the backup.  On failure restore the previous tree if possible.
    backup = output_root.parent / f".{output_root.name}.bak-{os.getpid()}"
    had_existing = output_root.exists()
    if had_existing:
        output_root.replace(backup)
    try:
        temp.replace(output_root)
        if had_existing:
            shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if had_existing and not output_root.exists():
            backup.replace(output_root)
        raise
    finally:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)

    stats["total_seconds"] = round(time.monotonic() - started, 3)
    return stats


def write_passage_list(stats: dict, path: str | Path) -> None:
    """Write the smoke passage-list TSV (passage<TAB>expected Korean fragment)
    from the records that were actually spliced."""
    lines = []
    for rel, name, translated in sorted(stats["spliced_records"]):
        lines.append(f"{name}\t{korean_fragment(translated)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble game_ko/ from game/ + reuse store")
    parser.add_argument("--store", type=str, default=str(DEFAULT_STORE))
    parser.add_argument("--game-root", type=str, default=str(GAME_ROOT))
    parser.add_argument("--output", type=str, default=str(GAME_KO_ROOT))
    parser.add_argument("--no-verify", action="store_true")
    parser.add_argument("--workers", type=int, default=0, help="0 = auto (<=16)")
    parser.add_argument(
        "--emit-passage-list", type=str, default="",
        help="write a smoke passage-list TSV of the spliced passages",
    )
    args = parser.parse_args(argv)

    records, skipped = pick_passage_records(args.store)
    print(f"records picked: {len(records)} (skipped: {skipped})")
    known_names = collect_known_macro_names(Path(args.game_root))
    stats = assemble(
        records,
        Path(args.game_root),
        Path(args.output),
        verify=not args.no_verify,
        known_names=known_names,
        workers=args.workers or None,
    )
    for key, value in stats.items():
        if key == "spliced_records":
            continue
        print(f"  {key}: {value}")
    if args.emit_passage_list:
        write_passage_list(stats, args.emit_passage_list)
        print(f"  passage-list: {args.emit_passage_list} "
              f"({len(stats['spliced_records'])} entries)")
    return 0 if stats["verify_failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
