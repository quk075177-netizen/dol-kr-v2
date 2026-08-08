"""Extract re-run targets from a fail journal.

Fail events with ``recovered_by`` = null are terminal failures — the
passage is a re-run candidate.  This tool emits the ``--passages-file``
JSONL to feed straight back into the runner:

    uv run python -m translation.journal_rerun \\
        --journal tmp/journals/req_20260808_007.jsonl --out /tmp/opencode/rerun.jsonl
    uv run python -m translation.translate_passages \\
        --passages-file /tmp/opencode/rerun.jsonl

``--passages-file`` rows carry only the passage identity — the re-run gets
a fresh request_id and the current pipeline (batch + escalation).
"""

from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract re-run targets from a fail journal")
    parser.add_argument("--journal", required=True, help="journal JSONL path")
    parser.add_argument("--out", required=True, help="passages-file JSONL to write")
    parser.add_argument("--include-recovered", action="store_true",
                        help="also include failures that the escalation recovered")
    args = parser.parse_args(argv)

    targets: OrderedDict[tuple[str, str], dict] = OrderedDict()
    for line in Path(args.journal).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("kind") != "fail":
            continue
        if not args.include_recovered and record.get("recovered_by") is not None:
            continue
        key = (record["source_path"], record["passage_name"])
        targets.setdefault(key, {
            "source_path": record["source_path"],
            "passage_name": record["passage_name"],
            "terminal_failures": 0,
        })
        targets[key]["terminal_failures"] += 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for target in targets.values():
            fh.write(json.dumps(
                {"source_path": target["source_path"],
                 "passage_name": target["passage_name"]},
                ensure_ascii=False,
            ) + "\n")
    print(f"re-run targets: {len(targets)} passage(s) → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
