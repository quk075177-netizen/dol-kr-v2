"""Pretty-print translation store records (JSONL → readable multi-line).

Usage:
    python3 -m translation.store_view --passage "Farm Work"
    python3 -m translation.store_view --last 3
    python3 -m translation.store_view --hash 9d01b2 --full
    python3 -m translation.store_view --journal tmp/journals/req_xxx.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_STORES = [
    Path("work/translations/ko-reuse.jsonl"),
    Path("work/translations/gemini-passages.jsonl"),
]

# 필드 표시 순서/그룹 — 공통 → 유형별
_COMMON = [
    "record_id", "passage_name", "source_path", "source", "level",
    "request_id", "model", "temperature", "created_at", "post_status",
    "placeholder_ok", "source_text_hash",
]
_GEMINI = ["repaired", "l2_retries", "api_calls", "escalated",
           "escalated_units", "reused_units", "tier"]
_BODIES = ["source_text", "translated_text"]
_ORDER = _COMMON + _GEMINI + _BODIES


def _show(record: dict, full: bool) -> str:
    lines: list[str] = []
    shown = set()
    for key in _ORDER:
        if key not in record:
            continue
        value = record[key]
        shown.add(key)
        if key in _BODIES:
            if full:
                lines.append(f"{key}:")
                for body_line in str(value).splitlines():
                    lines.append(f"  | {body_line}")
            else:
                text = str(value)
                preview = text[:200].replace("\n", "⏎")
                lines.append(f"{key} ({len(text)} chars): {preview}{'…' if len(text) > 200 else ''}")
            continue
        lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
    for key in record:
        if key not in shown:
            lines.append(f"{key}: {json.dumps(record[key], ensure_ascii=False)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pretty-print store records")
    parser.add_argument(
        "--store", type=str, default="",
        help="store file to read instead of the defaults (e.g. ko-units.jsonl)",
    )
    parser.add_argument("--passage", type=str, default="",
                        help="show the newest record for this passage name")
    parser.add_argument("--hash", type=str, default="",
                        help="show records whose source_text_hash starts with this")
    parser.add_argument("--last", type=int, default=0,
                        help="show the N newest records")
    parser.add_argument("--journal", type=str, default="",
                        help="pretty-print a journal file instead of the store")
    parser.add_argument("--full", action="store_true",
                        help="print source/translated bodies in full")
    parser.add_argument("--lines", action="store_true",
                        help="show source/translated bodies paired line by line")
    args = parser.parse_args(argv)

    if args.journal:
        records: list[dict] = []
        for line in Path(args.journal).read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        label = f"journal {args.journal}"
    else:
        paths = [Path(args.store)] if args.store else DEFAULT_STORES
        records: list[dict] = []
        for path in paths:
            records.extend(
                json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
        label = ", ".join(str(p) for p in paths)
        if args.passage:
            records = [r for r in records if r.get("passage_name") == args.passage]
        elif args.hash:
            records = [r for r in records if r.get("source_text_hash", "").startswith(args.hash)]
        elif args.last:
            records = records[-args.last:]
        else:
            parser.error("need --passage, --hash, --last or --journal")

    print(f"== {label} — {len(records)} records ==")
    for index, record in enumerate(records, 1):
        print(f"\n--- [{index}] {record.get('kind', 'record')} ---")
        if args.lines and "source_text" in record and "translated_text" in record:
            _show_lines(record)
        else:
            print(_show(record, args.full))
    return 0


def _show_lines(record: dict) -> None:
    """Show source/translated bodies as paired lines (line-count contract)."""
    MAX = 90  # per-side display width
    source = [line[:MAX] + ("…" if len(line) > MAX else "")
              for line in str(record.get("source_text", "")).splitlines()]
    translated = [line[:MAX] + ("…" if len(line) > MAX else "")
                  for line in str(record.get("translated_text", "")).splitlines()]
    print(f"lines: source {len(source)} / translated {len(translated)}"
          f"{'' if len(source) == len(translated) else '  ← MISMATCH'}")
    width = max(1, max((len(line) for line in source), default=1))
    for i, (src, tr) in enumerate(zip(source, translated), 1):
        marker = " " if src == tr else "·"
        print(f"{marker} {i:3d} | {src:<{width}} | {tr}")
    if len(source) != len(translated):
        for extra in source[len(translated):]:
            print(f"    | {extra:<{width}} | (없음)")
        for extra in translated[len(source):]:
            print(f"    | {'':<{width}} | {extra}")


if __name__ == "__main__":
    raise SystemExit(main())
