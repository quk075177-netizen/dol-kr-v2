"""Pilot: translate a few sample passages end-to-end with Gemini.

Usage:
    python3 -m translation.pilot [--passage-name NAME] [--max-units N]
"""

from __future__ import annotations

import argparse
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

SAMPLE_FILES = [
    "game/overworld-town/loc-cafe/main.twee",
    "game/overworld-town/loc-flats/main.twee",
    "game/overworld-forest/loc-cabin/main.twee",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pilot translation with Gemini")
    parser.add_argument("--passage-name", type=str, default="")
    parser.add_argument("--max-units", type=int, default=6)
    args = parser.parse_args(argv)

    picked: list[tuple[Path, object]] = []
    for file in SAMPLE_FILES:
        path = Path(file)
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
        return 1

    total_ok = 0
    total_problems = 0
    for path, passage in picked[:1]:
        data = path.read_bytes()
        artifact = mask_passage(data, passage)
        units = chunk_passage(passage, artifact, data)
        print(f"passage: {passage.name} ({len(units)} units, {len(artifact.masked_text)} chars)")
        translated_units: list[TranslatedUnit] = []
        for index, unit in enumerate(units[: args.max_units]):
            print(f"  translating unit {index + 1}/{args.max_units} "
                  f"({unit.char_count} chars, {len(unit.placeholders)} placeholders)...")
            tu = translate_unit(unit, index, len(units))
            problems = verify_placeholders(unit, tu.translated_text)
            if problems:
                total_problems += 1
                print(f"    PLACEHOLDER PROBLEM: {problems}")
                print(f"    original: {unit.masked_text[:200]!r}")
                print(f"    translated: {tu.translated_text[:200]!r}")
            else:
                total_ok += 1
            translated_units.append(tu)

        print("\n--- translated units (first 3) ---")
        for tu in translated_units[:3]:
            print(f"\n[unit {tu.unit.unit_index + 1}] {tu.translated_text[:250]}")
            print(f"  [ok placeholders: {not verify_placeholders(tu.unit, tu.translated_text)}]")

        # restore check on the whole passage (only units we translated)
        if len(translated_units) == len(units):
            try:
                restored = restore_translated(artifact, translated_units)
                remaining = [ph.placeholder for ph in artifact.placeholders
                             if ph.placeholder.encode("utf-8") in restored]
                print(f"\nrestore: {len(restored)} bytes")
                print(f"placeholder tokens remaining: {len(remaining)}")
                print(f"restore clean: {not remaining}")
            except Exception as exc:
                print(f"\nrestore failed: {exc}")

    print(f"\nplaceholder-clean units: {total_ok}, with problems: {total_problems}")
    return 0 if total_problems == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
