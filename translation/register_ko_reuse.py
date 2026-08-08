"""Register triple-match KO passages as reuse records.

Reads ``research/golden/corpus-triple-match.jsonl`` (Git-excluded), covers
both the no-marker subset and the ``【 】`` marker subset: markers are
normalised to ``{{post:...}}`` and statically resolved where the preceding
value is a fixed string, the KO body is verified with our own parser
pipeline and the skeleton-preservation check, then passage-level records
are appended to the reuse store (``work/translations/ko-reuse.jsonl``,
Git-excluded).

Records whose source_text_hash already exists in the store are skipped, so
re-running is idempotent.

Usage:
    python3 -m translation.register_ko_reuse [--triple-match PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pretranslation_cst.masking import mask_passage
from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH

from translation.assemble_game_ko import macro_sequence

from .post import normalize_markers, resolve_static
from .store import (
    append_record,
    load_translations,
    passage_placeholder_signature,
    source_hash,
)

DEFAULT_TRIPLE_MATCH = Path("research/golden/corpus-triple-match.jsonl")
DEFAULT_OUT = Path("work/translations/ko-reuse.jsonl")


def match_boundaries(source: str, translated: str) -> str:
    """Give the translated body the same leading/trailing newline structure
    as the source body, so consumers (the assembler) never have to guess
    where the passage body ends."""
    leading = source[: len(source) - len(source.lstrip("\n"))]
    trailing = source[len(source.rstrip("\n")) :]
    return leading + translated.strip("\n") + trailing


def make_record(row: dict, ko_normalized: str, *, level: str) -> dict:
    source_body = row["source_body"]
    markers = "{{post:" in ko_normalized
    if markers:
        post_status = "runtime_remaining"
    elif "【" in row["ko_body"]:
        post_status = "static_done"
    else:
        post_status = "none"
    return {
        "record_id": f"tr_{source_hash(source_body)[:12]}_ko",
        "source_text_hash": source_hash(source_body),
        "source_text": source_body,
        "translated_text": ko_normalized,
        "source_path": row["source_path"],
        "passage_name": row["passage_name"],
        "unit_id": f"{row['source_path']}:{row['passage_name']}",
        "request_id": "req_ko_reuse",
        "model": "ko_reuse",
        "temperature": None,
        "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "placeholder_ok": True,
        "post_status": post_status,
        "source": "ko_reuse",
        "level": level,
    }


def register_ko_reuse(
    triple_match_path: str | Path,
    out_path: str | Path,
    *,
    report_path: str | Path | None = None,
) -> dict:
    import re

    marker_re = re.compile(r"【[^】]+】")
    stats = {
        "total": 0,
        "no_marker": 0,
        "with_marker": 0,
        "already_registered": 0,
        "registered": 0,
        "skipped": {},
        "skipped_records": [],
    }
    existing = load_translations(out_path)
    p = Path(triple_match_path)
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            stats["total"] += 1
            if marker_re.search(row["ko_body"]) or "{{post:" in row["ko_body"]:
                stats["with_marker"] += 1
            else:
                stats["no_marker"] += 1
            source_body = row["source_body"]
            if source_hash(source_body) in existing:
                stats["already_registered"] += 1
                continue
            error = _verify_passage(row)
            if error:
                stats["skipped"][error] = stats["skipped"].get(error, 0) + 1
                stats["skipped_records"].append(
                    {"source_path": row["source_path"], "passage_name": row["passage_name"],
                     "reason": error}
                )
                continue
            ko_normalized = resolve_static(normalize_markers(row["ko_body"]))
            ko_normalized = match_boundaries(row["source_body"], ko_normalized)
            record = make_record(row, ko_normalized, level="passage")
            append_record(record, out_path)
            existing.setdefault(record["source_text_hash"], []).append(record)
            stats["registered"] += 1

    if report_path is not None:
        Path(report_path).write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return stats


def _verify_passage(row: dict) -> str | None:
    """Verify the KO body is structurally equivalent to the source body
    under OUR parser: both must produce the same macro-token sequence and
    the same protected-span sequence.

    triple-match already guarantees skeleton equality; this is the
    belt-and-braces check before registering a KO body as a translation.
    Returns an error code string, or None when the KO body is usable.
    """
    try:
        src_synthetic = f":: {row['passage_name']}\n\n{row['source_body']}".encode("utf-8")
        ko_synthetic = f":: {row['passage_name']}\n\n{row['ko_body']}".encode("utf-8")
        src_source = parse_file(src_synthetic, row["source_path"], DEFAULT_VALUE_KIND_PATH)
        ko_source = parse_file(ko_synthetic, row["source_path"], DEFAULT_VALUE_KIND_PATH)
        src_passage = next(
            (p for p in src_source.passages if p.name == row["passage_name"]), None
        )
        ko_passage = next(
            (p for p in ko_source.passages if p.name == row["passage_name"]), None
        )
        if src_passage is None or ko_passage is None:
            return "passage_not_found"
        if macro_sequence(row["source_body"].encode("utf-8")) != macro_sequence(
            row["ko_body"].encode("utf-8")
        ):
            return "macro_sequence_mismatch"
        src_sig = passage_placeholder_signature(mask_passage(src_synthetic, src_passage))
        ko_sig = passage_placeholder_signature(mask_passage(ko_synthetic, ko_passage))
        if src_sig != ko_sig:
            return "skeleton_mismatch"
        return None
    except Exception as exc:  # parser raises ValueError on malformed input
        return f"parse_error:{type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register KO triple-match reuse")
    parser.add_argument("--triple-match", type=str, default=str(DEFAULT_TRIPLE_MATCH))
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT))
    parser.add_argument("--report", type=str, default="")
    args = parser.parse_args(argv)

    stats = register_ko_reuse(
        args.triple_match,
        args.out,
        report_path=args.report or None,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"saved: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
