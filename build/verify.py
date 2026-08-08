#!/usr/bin/env python3
"""One-shot verification pipeline: assemble game_ko/ → compile → smoke.

Runs the whole build chain as a single command so no step can be skipped
and no stale artifact can be mistaken for a fresh one:

    assemble (translation.assemble_game_ko, --emit-passage-list)
        → compile (dol_build.py, tweego)
        → smoke (browser_smoke.py, headless Chromium)
        → summary report

Every step prints its elapsed time, so a slow step is visible immediately
(the smoke step grows with the compiled story size — currently the
dominant cost).

Development loop (cheap, no browser): unit tests + corpus_verify per
change; ``--no-compile --no-smoke`` when only the stores changed and the
tree assembly is the thing to check; the full chain only at milestones.

Exit code 0 = every step passed; 2 = any step failed (step printed first).

Usage:
    python3 build/verify.py
    python3 build/verify.py --no-assemble --no-compile   # smoke only
    python3 build/verify.py --no-compile --no-smoke      # assemble only
    python3 build/verify.py --expect-options-text "일반"  # pass-through
    python3 build/verify.py --min-korean-ratio 0.1
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORES = [
    ROOT / "work" / "translations" / "ko-reuse.jsonl",
    ROOT / "work" / "translations" / "gemini-passages.jsonl",
]
GAME_KO = ROOT / "game_ko"
HTML = ROOT / "build" / "dol-plus-ko.html"
SMOKE_OUT = ROOT / "build" / "browser-smoke"
PASSAGE_LIST = SMOKE_OUT / "passage-list.tsv"


class StepError(RuntimeError):
    pass


def _run(command: list[str], *, label: str) -> None:
    print(f"=== {label} ===")
    print(f"$ {' '.join(command)}")
    started = time.monotonic()
    completed = subprocess.run(command, cwd=ROOT, check=False)
    elapsed = time.monotonic() - started
    if completed.returncode != 0:
        raise StepError(f"{label} failed with exit code {completed.returncode}")
    print(f"--- {label}: {elapsed:.1f}s\n")


def _step_assemble(args: argparse.Namespace) -> None:
    # assemble needs the project venv (parser deps): use `uv run python`.
    command = [
        "uv", "run", "python", "-m", "translation.assemble_game_ko",
    ]
    for store in args.store:
        command.extend(["--store", str(store)])
    command.extend(["--emit-passage-list", str(PASSAGE_LIST)])
    if args.no_verify:
        command.append("--no-verify")
    if args.workers:
        command.extend(["--workers", str(args.workers)])
    _run(command, label="assemble game_ko/")
    print(f"passage-list: {PASSAGE_LIST}")


def _step_compile() -> None:
    _run(
        ["python3", "build/dol_build.py", "compile", "--force"],
        label="compile (tweego)",
    )


def _step_smoke(args: argparse.Namespace) -> dict:
    command = [
        "python3", "browser_smoke.py", "run",
        "--html", str(HTML),
        "--output", str(SMOKE_OUT),
        "--passage-list", str(PASSAGE_LIST),
    ]
    for text in args.expect_options_text:
        command.extend(["--expect-options-text", text])
    if args.min_korean_ratio is not None:
        command.extend(["--min-korean-ratio", str(args.min_korean_ratio)])
    _run(command, label="browser smoke")
    report_path = SMOKE_OUT / "report.json"
    return json.loads(report_path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store", action="append", type=Path, default=[],
        help="passage store path (repeatable; default: ko-reuse.jsonl + "
             "gemini-passages.jsonl)",
    )
    parser.add_argument("--no-assemble", action="store_true", help="use existing game_ko/")
    parser.add_argument("--no-compile", action="store_true", help="use existing build HTML")
    parser.add_argument("--no-smoke", action="store_true",
                        help="skip the browser smoke (dev loop; saves minutes)")
    parser.add_argument("--no-verify", action="store_true", help="assemble without structure verify")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--expect-options-text", action="append", default=[])
    parser.add_argument("--min-korean-ratio", type=float, default=None)
    args = parser.parse_args(argv)
    if not args.store:
        args.store = STORES

    started = time.monotonic()
    try:
        if not args.no_assemble:
            _step_assemble(args)
        if not args.no_compile:
            _step_compile()
        if args.no_smoke:
            print("=== browser smoke skipped (--no-smoke) ===")
            report = {"ok": True, "checks": {"smokeSkipped": True}}
        else:
            report = _step_smoke(args)
    except StepError as exc:
        print(f"verify FAILED: {exc}", file=sys.stderr)
        return 2
    print(f"=== total: {time.monotonic() - started:.1f}s ===")

    print("=== summary ===")
    print(f"ok: {report.get('ok')}")
    print(f"checks: {json.dumps(report.get('checks', {}), ensure_ascii=False)}")
    print(f"warnings: {json.dumps(report.get('warnings', {}), ensure_ascii=False)}")
    ratio = (report.get("runtime") or {}).get("koreanPassageRatio")
    if ratio:
        print(f"korean passage ratio: {ratio['korean']}/{ratio['total']} "
              f"({ratio['ratio']:.1%})")
    fails = [
        item["passage"]
        for item in (report.get("runtime") or {}).get("passageList", [])
        if item.get("exists") and not item.get("textMatch")
    ]
    print(f"passage-list text mismatches: {len(fails)}")
    if fails:
        print("  " + "\n  ".join(fails[:10]))
    print(f"report: {SMOKE_OUT / 'report.json'}")
    return 0 if report.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
