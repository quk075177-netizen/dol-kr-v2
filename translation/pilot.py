"""Pilot: translate sample passages end-to-end with Gemini.

Usage:
    python3 -m translation.pilot --passage-name "Ocean Breeze" [--max-units 10]
    python3 -m translation.pilot --batch --out /tmp/opencode/pilot.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pretranslation_cst.chunking import chunk_passage
from pretranslation_cst.masking import mask_passage
from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH

from .client import (
    TranslatedUnit,
    restore_translated,
    translate_unit,
    verify_placeholders,
)
from .post import post_process
from .store import find_passage_reuse, load_translations

SAMPLE_FILES = [
    "game/overworld-town/loc-cafe/main.twee",        # 대화
    "game/overworld-town/loc-flats/main.twee",       # 대화/이벤트
    "game/overworld-forest/loc-cabin/main.twee",     # 이벤트
    "game/base-combat/man-combat.twee",              # 전투
    "game/base-combat/actions-text.twee",            # 전투(성인)
    "game/01-config/versionInfo.twee",               # UI
    "game/base-system/settings.twee",                # 설정
    "game/overworld-forest/loc-forestshop/gwylan-events.twee",  # 성인
]

# 유형별 대표 passage: (파일, passage 이름)
BATCH_PASSAGES = [
    ("game/overworld-town/loc-cafe/main.twee", "Ocean Breeze"),              # 대화
    ("game/base-combat/man-combat.twee", "Widgets Combat Man-Combat"),       # 전투
    ("game/01-config/versionInfo.twee", "Widgets Version Info"),             # UI
    ("game/base-system/settings.twee", "Widgets Settings"),                  # 설정
    ("game/overworld-forest/loc-forestshop/gwylan-events.twee",
     "Gwylan Ocean Breeze Watch"),                                           # 성인
]


def run_passage(
    path: Path,
    passage,
    max_units: int,
    out_handle=None,
    records: dict | None = None,
) -> tuple[int, int, int]:
    """Translate one passage; returns (units_ok, units_with_problems, total_units)."""
    data = path.read_bytes()
    artifact = mask_passage(data, passage)
    if records:
        body_text = data[passage.body_span.start:passage.body_span.end].decode("utf-8")
        reuse = find_passage_reuse(body_text, records)
        if reuse is not None:
            print(
                f"passage: {passage.name} — REUSED ({reuse['source']}, "
                f"{len(reuse['translated_text'])} chars, no API call)"
            )
            return 0, 0, 0
    units = chunk_passage(passage, artifact, data)
    print(f"passage: {passage.name} ({len(units)} units, {len(artifact.masked_text)} chars)")
    ok = 0
    problems = 0
    translated_units: list[TranslatedUnit] = []
    for index, unit in enumerate(units[:max_units]):
        tu = translate_unit(unit, index, len(units))
        raw = tu.translated_text
        probs = verify_placeholders(unit, raw)
        if probs:
            problems += 1
            print(f"  unit {index + 1}: PLACEHOLDER PROBLEM {probs}")
            print(f"    original: {unit.masked_text[:200]!r}")
            print(f"    translated: {raw[:200]!r}")
        else:
            ok += 1
        tu.translated_text = post_process(raw)
        translated_units.append(tu)
        if out_handle is not None:
            row = {
                "source_path": unit.source_path,
                "passage_name": unit.passage_name,
                "unit_index": unit.unit_index,
                "unit_count": unit.unit_count,
                "char_count": unit.char_count,
                "masked_text": unit.masked_text,
                "translated_text": raw,
                "processed_text": tu.translated_text,
                "ancestors": unit.ancestors,
                "placeholder_ok": not probs,
            }
            out_handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    if len(translated_units) == len(units):
        try:
            restored = restore_translated(artifact, translated_units)
            remaining = [ph.placeholder for ph in artifact.placeholders
                         if ph.placeholder.encode("utf-8") in restored]
            print(f"  restore: {len(restored)} bytes, remaining tokens: {len(remaining)}")
        except Exception as exc:
            print(f"  restore failed: {exc}")
    return ok, problems, len(units[:max_units])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pilot translation with Gemini")
    parser.add_argument("--passage-name", type=str, default="")
    parser.add_argument("--file", type=str, default="", help="twee file to scan")
    parser.add_argument("--max-units", type=int, default=6)
    parser.add_argument("--batch", action="store_true", help="run BATCH_PASSAGES")
    parser.add_argument("--out", type=str, default="", help="JSONL output path")
    parser.add_argument(
        "--store",
        type=str,
        default="",
        help="reuse store JSONL path; hit passages skip the API entirely",
    )
    args = parser.parse_args(argv)

    out_handle = None
    if args.out:
        out_handle = open(args.out, "w", encoding="utf-8")

    records = load_translations(args.store) if args.store else None
    reused = 0

    total_ok = 0
    total_problems = 0
    total_units = 0

    def _run(path, passage, max_units):
        nonlocal reused
        ok, problems, n = run_passage(path, passage, max_units, out_handle, records)
        if n == 0:
            reused += 1
        return ok, problems, n

    if args.batch:
        for file, passage_name in BATCH_PASSAGES:
            path = Path(file)
            data = path.read_bytes()
            source = parse_file(data, path.as_posix(), DEFAULT_VALUE_KIND_PATH)
            for passage in source.passages:
                if passage.is_opaque:
                    continue
                if passage.name == passage_name:
                    ok, problems, n = _run(path, passage, args.max_units)
                    total_ok += ok
                    total_problems += problems
                    total_units += n
                    print()
                    break
    else:
        files = [Path(args.file)] if args.file else [Path(f) for f in SAMPLE_FILES]
        picked = []
        for path in files:
            data = path.read_bytes()
            source = parse_file(data, path.as_posix(), DEFAULT_VALUE_KIND_PATH)
            for passage in source.passages:
                if passage.is_opaque:
                    continue
                if args.passage_name and passage.name != args.passage_name:
                    continue
                picked.append((path, passage))
        if not picked:
            print("no passage matched")
            if out_handle:
                out_handle.close()
            return 1
        for path, passage in picked[:1]:
            ok, problems, n = _run(path, passage, args.max_units)
            total_ok += ok
            total_problems += problems
            total_units += n

    if out_handle:
        out_handle.close()
        print(f"saved: {args.out}")

    if records:
        print(f"reused passages (no API call): {reused}")
    print(f"\nplaceholder-clean units: {total_ok}/{total_units}, with problems: {total_problems}")
    return 0 if total_problems == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
