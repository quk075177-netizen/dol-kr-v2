"""Update diff: classify every corpus passage against the translation stores.

After a game update, only the changed passages need translation work.  This
tool walks ``game/**/*.twee``, compares each passage body with the stored
``source_text`` records and reports:

* ``unchanged`` — a usable passage-level record exists for the exact body
  (no work)
* ``changed`` — a record exists for this passage but the body drifted (or
  the record is unusable)
* ``new`` — no record at all

For ``changed``/``new`` passages it also chunks the passage and counts how
many units already have a unit-store translation (R2 reuse) — the expected
API-call savings when re-running the passage.

``--targets`` writes only the changed/new rows in ``--passages-file``
format, so the output feeds the runner directly:

    python3 -m translation.update_diff --targets /tmp/opencode/rerun.jsonl
    python3 -m translation.translate_passages --passages-file /tmp/opencode/rerun.jsonl

Exit code 0 = diff produced (even if nothing changed).
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from pretranslation_cst.chunking import chunk_passage
from pretranslation_cst.masking import mask_passage
from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH

from translation.store import load_translations, load_translations_many, source_hash

DEFAULT_STORES = [
    Path("work/translations/ko-reuse.jsonl"),
    Path("work/translations/gemini-passages.jsonl"),
]
DEFAULT_UNITS = Path("work/translations/ko-units.jsonl")

CODE_TAGS = {"widget", "script", "stylesheet"}


def _classify_one(task: tuple[str, list[str], str, str]) -> list[dict]:
    path, store_files, units_file, root = task
    f = Path(path)
    data = f.read_bytes()
    rows: list[dict] = []
    try:
        source = parse_file(data, path, DEFAULT_VALUE_KIND_PATH)
    except Exception:
        return rows
    stores = load_translations_many(store_files)
    units_records = load_translations(units_file) if Path(units_file).exists() else {}
    for passage in source.passages:
        if passage.is_opaque or CODE_TAGS & set(passage.tags):
            continue
        body = data[passage.body_span.start:passage.body_span.end].decode("utf-8")
        row: dict[str, object] = {
            "source_path": path,
            "passage_name": passage.name,
        }
        records = stores.get(source_hash(body)) or []
        usable = any(
            r.get("placeholder_ok", True) and not r.get("superseded")
            and r.get("level") == "passage"
            for r in records
        )
        if usable:
            row["status"] = "unchanged"
            rows.append(row)
            continue
        known = any(
            r.get("source_path") == path and r.get("passage_name") == passage.name
            for group in stores.values()
            for r in group
        )
        row["status"] = "changed" if known else "new"
        try:
            artifact = mask_passage(data, passage)
            units = chunk_passage(passage, artifact, data)
            row["unit_count"] = len(units)
            row["reusable_units"] = sum(
                1 for unit in units
                if units_records.get(source_hash(_restore_unit_text(unit)))
            )
        except Exception:
            row["unit_count"] = 0
            row["reusable_units"] = 0
        rows.append(row)
    return rows


def _restore_unit_text(unit) -> str:
    """Original bytes of a unit's masked text (placeholder tokens replaced)."""
    text = unit.masked_text
    for placeholder in unit.placeholders:
        occurrences = text.count(placeholder.placeholder)
        if occurrences != 1:
            continue
        text = text.replace(placeholder.placeholder, placeholder.original_text, 1)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=str, default="game")
    parser.add_argument(
        "--store", action="append", type=str, default=[],
        help="passage store path (repeatable; default: ko-reuse.jsonl + "
             "gemini-passages.jsonl)",
    )
    parser.add_argument("--units-store", type=str, default=str(DEFAULT_UNITS))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument(
        "--targets", type=str, default="",
        help="write changed/new rows as a --passages-file JSONL here",
    )
    args = parser.parse_args(argv)

    stores = [Path(s) for s in args.store] or DEFAULT_STORES
    files = sorted(str(f) for f in Path(args.root).rglob("*.twee"))
    tasks = [(path, [str(s) for s in stores], args.units_store, args.root) for path in files]
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for result in ex.map(_classify_one, tasks, chunksize=8):
            rows.extend(result)
    rows.sort(key=lambda r: (r["source_path"], r["passage_name"]))

    counts = {"unchanged": 0, "changed": 0, "new": 0}
    for row in rows:
        counts[row["status"]] += 1
    print(json.dumps(counts, ensure_ascii=False, indent=2))

    if args.targets:
        targets = [
            {"source_path": row["source_path"], "passage_name": row["passage_name"]}
            for row in rows if row["status"] != "unchanged"
        ]
        Path(args.targets).write_text(
            "".join(json.dumps(t, ensure_ascii=False) + "\n" for t in targets),
            encoding="utf-8",
        )
        print(f"targets: {len(targets)} -> {args.targets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
