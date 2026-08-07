"""Checks that unclassified diagnostics really have no value-kind entry."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


@dataclass
class VerificationReport:
    rows: int = 0
    unclassified: int = 0
    macro_missing: int = 0
    argument_missing: int = 0
    violations: list[dict[str, Any]] = field(default_factory=list)
    malformed_rows: int = 0
    codes: Counter[str] = field(default_factory=Counter)

    @property
    def ok(self) -> bool:
        return not self.violations and self.malformed_rows == 0


def _load_macros(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    macros = payload.get("macros", payload)
    return macros if isinstance(macros, dict) else {}


def verify_unclassified(jsonl_path: str | Path, value_kind_path: str | Path) -> VerificationReport:
    macros = _load_macros(value_kind_path)
    report = VerificationReport()
    with Path(jsonl_path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            report.rows += 1
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                report.malformed_rows += 1
                continue
            cst = row.get("cst", {})
            for diagnostic in cst.get("diagnostics", []):
                code = diagnostic.get("code")
                report.codes[code] += 1
                if code != "unclassified_argument":
                    continue
                report.unclassified += 1
                macro_name = str(diagnostic.get("macro_name", "")).lstrip("/").lower()
                argument_index = diagnostic.get("argument_index")
                macro = macros.get(macro_name)
                args = macro.get("args", {}) if isinstance(macro, dict) else {}
                key = str(argument_index)
                if not isinstance(macro, dict):
                    report.macro_missing += 1
                    continue
                if not isinstance(args, dict) or key not in args:
                    report.argument_missing += 1
                    continue
                report.violations.append({
                    "line": line_number,
                    "source_path": cst.get("source_path"),
                    "passage_name": cst.get("name"),
                    "macro_name": diagnostic.get("macro_name"),
                    "argument_index": argument_index,
                    "reason": "macro-value-kind contains this argument",
                })
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify unclassified CST diagnostics against macro-value-kind")
    parser.add_argument("jsonl", type=Path, help="masked CST JSONL produced by pretranslation_cst.cli")
    parser.add_argument("--value-kind", type=Path, default=Path("research/data/macro-value-kind.yml"))
    args = parser.parse_args()
    report = verify_unclassified(args.jsonl, args.value_kind)
    print(f"rows={report.rows} unclassified={report.unclassified}")
    print(f"macro_missing={report.macro_missing} argument_missing={report.argument_missing}")
    print(f"malformed_rows={report.malformed_rows} violations={len(report.violations)}")
    if report.violations:
        for item in report.violations[:20]:
            print(json.dumps(item, ensure_ascii=False, sort_keys=True))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
