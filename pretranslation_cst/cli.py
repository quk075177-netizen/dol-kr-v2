from __future__ import annotations

import argparse
import json
from pathlib import Path

from .masking import mask_passage
from .parser import parse_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Lossless Twee CST and prose masker")
    parser.add_argument("root", type=Path, help="directory containing Twee files")
    parser.add_argument("--value-kind", type=Path, default=Path("research/data/macro-value-kind.yml"))
    parser.add_argument("--output", type=Path, required=True, help="JSONL output path")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for path in sorted(args.root.rglob("*.twee")):
            data = path.read_bytes()
            source = parse_file(data, path.as_posix(), args.value_kind)
            for passage in source.passages:
                artifact = mask_passage(data, passage)
                row = {"cst": passage.to_dict(), "mask": artifact.to_dict()}
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
