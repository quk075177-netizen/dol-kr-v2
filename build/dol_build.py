#!/usr/bin/env python3
"""Bootstrap pinned DoL Plus build assets and compile ``game_ko``.

Only the Linux x86_64 Tweego binary, SugarCube story format, head file, and
modules tree are cached. The reference repository is never cloned into this
project and downloaded content is verified against ``build-tools.lock.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOCK = ROOT / "build-tools.lock.json"
DEFAULT_CACHE_ROOT = ROOT / ".cache" / "dol-build-tools"
DEFAULT_SOURCE = ROOT / "game_ko"
DEFAULT_OUTPUT = ROOT / "build" / "dol-plus-ko.html"


class BuildError(RuntimeError):
    """Raised for a local build configuration, download, or compile failure."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_fingerprint(root: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    for path in files:
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return len(files), digest.hexdigest()


def load_lock(path: Path) -> dict[str, Any]:
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BuildError(f"build lock not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BuildError(f"invalid build lock JSON: {path}: {exc}") from exc
    if not isinstance(lock, dict) or lock.get("schemaVersion") != 1:
        raise BuildError(f"unsupported build lock schema: {path}")
    source = lock.get("source")
    if not isinstance(source, dict) or not isinstance(source.get("ref"), str):
        raise BuildError(f"build lock requires source.ref: {path}")
    if len(source["ref"]) != 40 or any(
        ch not in "0123456789abcdef" for ch in source["ref"]
    ):
        raise BuildError(
            f"build lock source.ref must be a full lowercase commit SHA: {path}"
        )
    return lock


def current_platform_key() -> str:
    system = platform.system().casefold()
    machine = platform.machine().casefold()
    if system == "linux" and machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    raise BuildError(
        f"unsupported build host: {platform.system()} {platform.machine()}"
    )


def cache_path(lock: dict[str, Any], cache_root: Path) -> Path:
    return cache_root / lock["source"]["ref"]


def all_locked_files(lock: dict[str, Any], platform_key: str) -> list[dict[str, Any]]:
    platforms = lock.get("platforms")
    if not isinstance(platforms, dict) or platform_key not in platforms:
        raise BuildError(f"build lock has no assets for {platform_key}")
    common = lock.get("commonFiles")
    platform_files = platforms[platform_key].get("files")
    if not isinstance(common, list) or not isinstance(platform_files, list):
        raise BuildError("build lock file lists are malformed")
    result = [*common, *platform_files]
    for item in result:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(field), str)
            for field in ("source", "destination", "sha256")
        ):
            raise BuildError("build lock file entry is malformed")
        destination = PurePosixPath(item["destination"])
        if destination.is_absolute() or ".." in destination.parts:
            raise BuildError(f"unsafe build asset destination: {destination}")
    return result


def download(url: str, output: Path) -> None:
    request = urllib.request.Request(
        url, headers={"User-Agent": "solpjt-build-bootstrap/1"}
    )
    try:
        with (
            urllib.request.urlopen(request, timeout=600) as response,
            output.open("wb") as stream,
        ):
            shutil.copyfileobj(response, stream)
    except (OSError, urllib.error.URLError) as exc:
        raise BuildError(f"download failed: {url}: {exc}") from exc


def extract_modules(archive: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=False)
    found = 0
    try:
        bundle = tarfile.open(archive, "r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise BuildError(f"invalid modules archive: {archive}: {exc}") from exc
    with bundle:
        for member in bundle.getmembers():
            parts = PurePosixPath(member.name).parts
            try:
                marker = parts.index("modules")
            except ValueError:
                continue
            relative = PurePosixPath(*parts[marker + 1 :])
            if not relative.parts:
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise BuildError(f"unsafe path in modules archive: {member.name}")
            if member.isdir():
                continue
            if not member.isfile():
                raise BuildError(
                    f"unsupported non-file in modules archive: {member.name}"
                )
            source = bundle.extractfile(member)
            if source is None:
                raise BuildError(
                    f"could not read modules archive member: {member.name}"
                )
            target = output.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as stream:
                shutil.copyfileobj(source, stream)
            found += 1
    if found == 0:
        raise BuildError("modules archive did not contain a modules tree")


def verify_tools(lock: dict[str, Any], tools: Path, platform_key: str) -> None:
    modules_lock = lock.get("modulesArchive")
    if not isinstance(modules_lock, dict):
        raise BuildError("build lock modulesArchive is malformed")
    modules = tools / "modules"
    if not modules.is_dir():
        raise BuildError(f"cached modules missing: {modules}")
    count, fingerprint = tree_fingerprint(modules)
    if count != modules_lock.get("fileCount") or fingerprint != modules_lock.get(
        "treeSha256"
    ):
        raise BuildError(f"cached modules failed verification: {modules}")
    for item in all_locked_files(lock, platform_key):
        path = tools.joinpath(*PurePosixPath(item["destination"]).parts)
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise BuildError(f"cached build asset failed verification: {path}")


def bootstrap(lock: dict[str, Any], cache_root: Path, platform_key: str) -> Path:
    target = cache_path(lock, cache_root)
    if target.exists():
        verify_tools(lock, target, platform_key)
        print(f"[ok] verified build tools: {target}")
        return target

    cache_root.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".dol-build-tools-", dir=cache_root))
    try:
        modules_lock = lock["modulesArchive"]
        archive = temp / "modules.tar.gz"
        print(f"[download] modules at {lock['source']['ref']}")
        download(str(modules_lock["url"]), archive)
        if sha256_file(archive) != modules_lock["sha256"]:
            raise BuildError("downloaded modules archive failed SHA-256 verification")
        extract_modules(archive, temp / "tools" / "modules")

        raw_base = f"{lock['source']['repository']}/-/raw/{lock['source']['ref']}/"
        for item in all_locked_files(lock, platform_key):
            destination = temp / "tools" / PurePosixPath(item["destination"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            url = raw_base + urllib.parse.quote(item["source"], safe="/")
            print(f"[download] {item['source']}")
            download(url, destination)
            if sha256_file(destination) != item["sha256"]:
                raise BuildError(
                    f"downloaded build asset failed SHA-256: {item['source']}"
                )
            if item.get("executable"):
                destination.chmod(0o755)

        tools = temp / "tools"
        verify_tools(lock, tools, platform_key)
        (tools / "build-tools.lock.json").write_text(
            json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        tools.replace(target)
        print(f"[ok] installed build tools: {target}")
        return target
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def build_report(
    lock: dict[str, Any], source: Path, output: Path, command: Iterable[str]
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "builtAt": datetime.now(UTC).isoformat(),
        "source": str(source),
        "buildToolsRef": lock["source"]["ref"],
        "command": list(command),
        "output": str(output),
        "outputBytes": output.stat().st_size,
        "outputSha256": sha256_file(output),
    }


def write_json_atomic(path: Path, value: Any) -> None:
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def compile_game(
    args: argparse.Namespace, lock: dict[str, Any], platform_key: str
) -> int:
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_dir():
        raise BuildError(f"translated source directory not found: {source}")
    if output.exists() and not args.force:
        raise BuildError(f"output already exists; use --force: {output}")
    tools = cache_path(lock, args.cache_root.resolve())
    if args.offline:
        verify_tools(lock, tools, platform_key)
    else:
        tools = bootstrap(lock, args.cache_root.resolve(), platform_key)

    executable_name = lock["platforms"][platform_key]["executable"]
    executable = tools / executable_name
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_name(f".{output.name}.tmp-{os.getpid()}")
    command = [
        str(executable),
        "-o",
        str(temporary_output),
        "--head",
        str(tools / "head.html"),
        "--module",
        str(tools / "modules"),
        str(source),
    ]
    environment = os.environ.copy()
    environment["TWEEGO_PATH"] = str(tools / "storyFormats")
    try:
        completed = subprocess.run(command, env=environment, check=False)
        if completed.returncode != 0:
            raise BuildError(f"Tweego failed with exit code {completed.returncode}")
        if not temporary_output.is_file():
            raise BuildError("Tweego reported success but did not create an HTML file")
        temporary_output.replace(output)
    finally:
        if temporary_output.exists():
            temporary_output.unlink()

    report_path = output.with_suffix(output.suffix + ".build.json")
    report_command = [*command]
    report_command[2] = str(output)
    write_json_atomic(report_path, build_report(lock, source, output, report_command))
    print(f"[ok] compiled: {output}")
    print(f"[ok] report:   {report_path}")
    return 0


def self_test(lock: dict[str, Any]) -> int:
    platform_key = current_platform_key()
    all_locked_files(lock, platform_key)
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        (root / "nested").mkdir()
        (root / "a.txt").write_bytes(b"alpha")
        (root / "nested" / "b.txt").write_bytes(b"beta")
        count, fingerprint = tree_fingerprint(root)
        if count != 2 or len(fingerprint) != 64:
            raise BuildError("tree fingerprint self-test failed")
    print(f"[ok] build self-test passed: {platform_key}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap pinned DoL Plus tools and compile game_ko"
    )
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap_parser = sub.add_parser(
        "bootstrap", help="download and verify minimal build tools"
    )
    bootstrap_parser.set_defaults(action="bootstrap")

    verify_parser = sub.add_parser("verify", help="verify already cached build tools")
    verify_parser.set_defaults(action="verify")

    compile_parser = sub.add_parser("compile", help="compile a translated source tree")
    compile_parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    compile_parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    compile_parser.add_argument("--offline", action="store_true")
    compile_parser.add_argument("--force", action="store_true")
    compile_parser.set_defaults(action="compile")

    test_parser = sub.add_parser(
        "self-test", help="run provider-free build helper checks"
    )
    test_parser.set_defaults(action="self-test")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        lock = load_lock(args.lock.resolve())
        platform_key = current_platform_key()
        if args.action == "bootstrap":
            bootstrap(lock, args.cache_root.resolve(), platform_key)
            return 0
        if args.action == "verify":
            tools = cache_path(lock, args.cache_root.resolve())
            verify_tools(lock, tools, platform_key)
            print(f"[ok] verified build tools: {tools}")
            return 0
        if args.action == "compile":
            return compile_game(args, lock, platform_key)
        return self_test(lock)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
