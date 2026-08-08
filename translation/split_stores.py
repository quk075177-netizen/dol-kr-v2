"""Split the mixed passage store into one file per producer.

The old ``ko-reuse.jsonl`` mixed legacy ``ko_reuse`` records (3-match
registration, passage level) with ``gemini`` passage records — two producers
with different schemas in one file.  After this split:

* ``work/translations/ko-reuse.jsonl`` — ko_reuse only (legacy registry)
* ``work/translations/gemini-passages.jsonl`` — gemini passage records
  (the runner's write target and the assembler's read input)

Idempotent: re-running overwrites the two target files from the source
records, so the split can be replayed after any re-registration.

Usage:
    python3 -m translation.split_stores
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from translation.store import load_translations

DEFAULT_MIXED = Path("work/translations/ko-reuse.jsonl")
DEFAULT_KO_REUSE = Path("work/translations/ko-reuse.jsonl")
DEFAULT_GEMINI = Path("work/translations/gemini-passages.jsonl")


def split_records(mixed_path: str | Path) -> tuple[list[dict], list[dict]]:
    """Partition records by ``source``: (ko_reuse rows, gemini rows)."""
    ko_reuse: list[dict] = []
    gemini: list[dict] = []
    for group in load_translations(mixed_path).values():
        for record in group:
            if record.get("source") == "gemini":
                gemini.append(record)
            elif record.get("source") == "ko_reuse":
                ko_reuse.append(record)
            else:
                raise ValueError(
                    f"unexpected record source {record.get('source')!r}: "
                    f"{record.get('record_id')}"
                )
    return ko_reuse, gemini


def write_rows(rows: list[dict], path: str | Path) -> None:
    """Write records back in append order (original relative order kept)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for record in rows:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mixed", type=str, default=str(DEFAULT_MIXED),
                        help="old combined store (default: ko-reuse.jsonl)")
    parser.add_argument("--ko-reuse", type=str, default=str(DEFAULT_KO_REUSE))
    parser.add_argument("--gemini", type=str, default=str(DEFAULT_GEMINI))
    args = parser.parse_args(argv)

    ko_reuse, gemini = split_records(args.mixed)
    write_rows(ko_reuse, args.ko_reuse)
    write_rows(gemini, args.gemini)
    print(f"ko_reuse: {len(ko_reuse)} -> {args.ko_reuse}")
    print(f"gemini:   {len(gemini)} -> {args.gemini}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
