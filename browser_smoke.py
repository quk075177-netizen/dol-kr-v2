#!/usr/bin/env python3
"""Bootstrap an ignored Playwright cache and smoke-test the compiled game HTML."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAYWRIGHT_VERSION = "1.59.1"
DEFAULT_CACHE = ROOT / ".cache" / "browser-smoke"
DEFAULT_HTML = ROOT / "build" / "dol-plus-ko.html"
DEFAULT_OUTPUT = ROOT / "build" / "browser-smoke"
RUNNER = ROOT / "browser_smoke.mjs"


class SmokeError(RuntimeError):
    pass


def package_dir(cache: Path) -> Path:
    return cache / "node_modules" / "playwright-core"


def browser_dir(cache: Path) -> Path:
    return cache / "browsers"


def package_is_ready(cache: Path) -> bool:
    manifest = package_dir(cache) / "package.json"
    if not manifest.is_file():
        return False
    try:
        return (
            json.loads(manifest.read_text(encoding="utf-8")).get("version")
            == PLAYWRIGHT_VERSION
        )
    except (OSError, json.JSONDecodeError):
        return False


def browser_is_ready(cache: Path) -> bool:
    root = browser_dir(cache)
    return any(
        root.glob(
            "chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"
        )
    )


def require_commands() -> None:
    for command in ("node", "npm"):
        if shutil.which(command) is None:
            raise SmokeError(f"required command not found: {command}")


def bootstrap(cache: Path) -> None:
    require_commands()
    cache.mkdir(parents=True, exist_ok=True)
    if not package_is_ready(cache):
        completed = subprocess.run(
            [
                "npm",
                "install",
                "--prefix",
                str(cache),
                "--no-save",
                f"playwright-core@{PLAYWRIGHT_VERSION}",
            ],
            check=False,
        )
        if completed.returncode != 0:
            raise SmokeError(
                f"Playwright install failed with exit code {completed.returncode}"
            )
    if not browser_is_ready(cache):
        environment = os.environ.copy()
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir(cache))
        completed = subprocess.run(
            [
                "node",
                str(package_dir(cache) / "cli.js"),
                "install",
                "chromium-headless-shell",
            ],
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            raise SmokeError(
                f"Chromium install failed with exit code {completed.returncode}"
            )
    verify(cache)
    print(f"[ok] browser tools ready: {cache}")


def verify(cache: Path) -> None:
    require_commands()
    if not RUNNER.is_file():
        raise SmokeError(f"browser runner not found: {RUNNER}")
    if not package_is_ready(cache):
        raise SmokeError(f"Playwright {PLAYWRIGHT_VERSION} is not installed in {cache}")
    if not browser_is_ready(cache):
        raise SmokeError(
            f"Chromium headless shell is not installed in {browser_dir(cache)}"
        )


def run_smoke(args: argparse.Namespace) -> int:
    cache = args.cache_root.resolve()
    if args.offline:
        verify(cache)
    else:
        bootstrap(cache)
    html = args.html.resolve()
    if not html.is_file():
        raise SmokeError(f"compiled HTML not found: {html}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_dir(cache))
    command = [
        "node",
        str(RUNNER),
        "--playwright-dir",
        str(package_dir(cache)),
        "--html",
        str(html),
        "--output",
        str(output),
    ]
    if args.passage:
        command.extend(["--passage", args.passage])
    if args.expect_text:
        if not args.passage:
            raise SmokeError("--expect-text requires --passage")
        command.extend(["--expect-text", args.expect_text])
    if args.wikify:
        command.extend(["--wikify", args.wikify])
    if args.expect_wikify_text:
        if not args.wikify:
            raise SmokeError("--expect-wikify-text requires --wikify")
        command.extend(["--expect-wikify-text", args.expect_wikify_text])
    if args.expect_trigger_text:
        if not args.wikify:
            raise SmokeError("--expect-trigger-text requires --wikify")
        command.extend(["--expect-trigger-text", args.expect_trigger_text])
    if args.expect_tooltip_text:
        if not args.wikify:
            raise SmokeError("--expect-tooltip-text requires --wikify")
        command.extend(["--expect-tooltip-text", args.expect_tooltip_text])
    if args.passage_list:
        command.extend(["--passage-list", str(args.passage_list)])
    for text in args.expect_options_text:
        command.extend(["--expect-options-text", text])
    completed = subprocess.run(
        command,
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise SmokeError(
            f"browser smoke test failed with exit code {completed.returncode}"
        )
    return 0


def self_test() -> int:
    require_commands()
    if not RUNNER.is_file():
        raise SmokeError(f"browser runner not found: {RUNNER}")
    print(f"[ok] browser smoke self-test passed: playwright-core {PLAYWRIGHT_VERSION}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test compiled DoL Plus HTML in Chromium"
    )
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="install pinned Playwright and headless Chromium")
    sub.add_parser("verify", help="verify an existing browser cache")
    run = sub.add_parser(
        "run", help="test Start, Options, and Saves in the compiled HTML"
    )
    run.add_argument("--html", type=Path, default=DEFAULT_HTML)
    run.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    run.add_argument("--offline", action="store_true")
    run.add_argument(
        "--passage", help="inspect this compiled passage after the UI checks"
    )
    run.add_argument(
        "--passage-list",
        type=Path,
        help="TSV file of passages to verify: <passage>\\t<expected text> per line",
    )
    run.add_argument(
        "--expect-options-text",
        action="append",
        default=[],
        help="require this text in the options overlay (repeatable; empty skips)",
    )
    run.add_argument(
        "--expect-text", help="require this text in the compiled passage source"
    )
    run.add_argument(
        "--wikify", help="render this SugarCube snippet in an isolated probe"
    )
    run.add_argument(
        "--expect-wikify-text",
        help="require this text in the rendered SugarCube probe",
    )
    run.add_argument(
        "--expect-trigger-text",
        help="require this direct text in the first rendered mouse.tooltip-centertop",
    )
    run.add_argument(
        "--expect-tooltip-text",
        help="require this text in the first rendered mouse.tooltip-centertop tooltip span",
    )
    sub.add_parser(
        "self-test", help="check local runner prerequisites without downloading"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "bootstrap":
            bootstrap(args.cache_root.resolve())
            return 0
        if args.command == "verify":
            verify(args.cache_root.resolve())
            print(f"[ok] verified browser tools: {args.cache_root.resolve()}")
            return 0
        if args.command == "run":
            return run_smoke(args)
        return self_test()
    except SmokeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
