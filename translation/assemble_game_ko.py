"""Assemble a ``game_ko/`` tree from the English ``game/`` tree and
passage-level translation records (``work/translations/ko-reuse.jsonl``).

The tree is copied verbatim, then every translated passage body is spliced
into its ``.twee`` file at the byte span the parser recorded for the
original body.  Passage headers, tags, file order, and all other files
(JS/CSS/...) stay byte-exact.  Records whose original body no longer matches
the current file (drift) are skipped and reported.

Usage:
    python3 -m translation.assemble_game_ko --store work/translations/ko-reuse.jsonl
"""

from __future__ import annotations

import argparse
import shutil
import time
from collections import defaultdict
from pathlib import Path

from pretranslation_cst.corpus_verify import collect_known_macro_names
from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH
from translation.store import load_translations

GAME_ROOT = Path("game")
GAME_KO_ROOT = Path("game_ko")
DEFAULT_STORE = Path("work/translations/ko-reuse.jsonl")

import re

_SEQ_RE = re.compile(r"<<\s*/?\s*[A-Za-z_]\w*|\[\[|]]|</?[a-z][^>]*>")


def macro_sequence(text: bytes) -> list[str]:
    """Structural fingerprint of a passage body: macro names, link brackets,
    and HTML tags — not their contents (labels are translated)."""
    return _SEQ_RE.findall(text.decode("utf-8", errors="replace"))


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


def assemble(
    records: dict[tuple[str, str], dict],
    game_root: Path,
    output_root: Path,
    *,
    verify: bool = True,
    known_names: frozenset[str] | None = None,
) -> dict:
    by_file: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for (path, name), record in records.items():
        by_file[path].append((name, record))

    started = time.monotonic()
    output_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(game_root, output_root, dirs_exist_ok=True, symlinks=False)
    copy_seconds = time.monotonic() - started

    stats = {
        "records": len(records),
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
        "copy_seconds": round(copy_seconds, 3),
        "splice_seconds": 0.0,
        "verify_seconds": 0.0,
    }

    CODE_TAGS = {"widget", "script", "stylesheet"}

    splice_started = time.monotonic()
    for rel in sorted(by_file):
        items = by_file[rel]
        src = game_root / rel
        dst = output_root / rel
        if not src.is_file():
            stats["file_missing"] += 1
            continue
        data = src.read_bytes()
        try:
            source = parse_file(data, rel, DEFAULT_VALUE_KIND_PATH)
        except Exception:
            stats["parse_error"] += 1
            continue
        passages = {passage.name: passage for passage in source.passages}

        edits: list[tuple[int, int, str]] = []
        spliced_names: list[str] = []
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
        if not edits:
            continue

        # splice from the end so earlier offsets stay valid.  The KO body
        # often drops the body's boundary newlines; keep the original
        # leading/trailing whitespace so the next passage header stays
        # a line start (``::`` must begin a line for Tweego/SugarCube).
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

        if verify:
            verify_started = time.monotonic()
            problems = _verify_assembled(dst, spliced_names, known_names, original=src.read_bytes())
            stats["verify_seconds"] += time.monotonic() - verify_started
            if problems:
                stats["verify_failed"] += len(problems)
                for code in problems:
                    stats["diagnostics"][code] = stats["diagnostics"].get(code, 0) + 1

    stats["splice_seconds"] = round(time.monotonic() - splice_started, 3)
    stats["verify_seconds"] = round(stats["verify_seconds"], 3)
    stats["total_seconds"] = round(time.monotonic() - started, 3)
    return stats


def _verify_assembled(
    path: Path,
    spliced_names: list[str],
    known_names: frozenset[str] | None,
    *,
    original: bytes | None = None,
) -> list[str]:
    """Reparse a spliced file and collect structural diagnostics for the
    spliced passages only.  When ``original`` bytes are given, also compare
    the macro sequence of every spliced passage against the original body
    (a sequence change would break the runtime)."""
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
        try:
            original_source = parse_file(
                original, path.as_posix(), DEFAULT_VALUE_KIND_PATH, _widget_names=known_names
            )
        except Exception:
            return ["parse_error"]
        original_bodies = {
            passage.name: original[passage.body_span.start : passage.body_span.end]
            for passage in original_source.passages
        }
        for passage in source.passages:
            if passage.name not in wanted:
                continue
            original_body = original_bodies.get(passage.name)
            if original_body is None:
                continue
            if macro_sequence(original_body) != macro_sequence(data[passage.body_span.start : passage.body_span.end]):
                codes.append("macro_sequence_mismatch")
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble game_ko/ from game/ + reuse store")
    parser.add_argument("--store", type=str, default=str(DEFAULT_STORE))
    parser.add_argument("--game-root", type=str, default=str(GAME_ROOT))
    parser.add_argument("--output", type=str, default=str(GAME_KO_ROOT))
    parser.add_argument("--no-verify", action="store_true")
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
    )
    for key, value in stats.items():
        print(f"  {key}: {value}")
    return 0 if stats["verify_failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
