"""Read-only audit of macro-grammar.json against SugarCube and game JS sources.

The audit extracts macro definitions (Macro.add / Macro.delete / DefineMacro /
DefineMacroS / statDisplay.create, including the alias form Macro.add(name,
'other')) from the pinned SugarCube source and from game/**/*.js, computes the
final effective spec for every macro, and compares it with the versioned
manifest in pretranslation_cst/data/macro-grammar.json.

The manifest is authoritative: this command never writes it.  It only reports
and fails on discrepancies, so a missing or inconsistent entry cannot go
unnoticed.  Handler-derived semantics that static analysis cannot infer (for
example <<default>> rejecting arguments) are resolved through an explicit
allowlist that records the evidence location.

Usage::

    python3 -m pretranslation_cst.macro_audit                 # manifest vs sources
    python3 -m pretranslation_cst.macro_audit --corpus        # + full corpus parse
    python3 -m pretranslation_cst.macro_audit extract-sugarcube --root PATH --out PATH

Output is deterministic: JSON reports use sorted keys and a stable ordering,
so two runs produce byte-identical output.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .paths import DEFAULT_VALUE_KIND_PATH

DEFAULT_GRAMMAR_PATH = Path(__file__).with_name("data") / "macro-grammar.json"
DEFAULT_ALLOWLIST_PATH = Path(__file__).with_name("data") / "macro-grammar-audit-allowlist.json"
DEFAULT_SUGARCUBE_SNAPSHOT = Path(__file__).with_name("data") / "sugarcube-extracted.json"
DEFAULT_GAME_ROOT = Path(__file__).parents[1] / "game"

GAME_SOURCE_KINDS = {"game_js", "game_override"}
SUGARCUBE_SOURCE_KINDS = {"sugarcube", "sugarcube_deprecated"}

_CALL_RE = re.compile(r"\b(?:Macro\.add|Macro\.delete|DefineMacroS?|statDisplay\.create)(?=\s*\()")
_IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_TAGS_KEY_RE = re.compile(r"\btags\s*:")
_SKIP_ARGS_KEY_RE = re.compile(r"\bskipArgs\s*:")
_REGEX_PRECEDING = set("([{:;,=!?&|+-*%^~<>")


# ---------------------------------------------------------------------------
# Minimal JS literal-aware scanning
# ---------------------------------------------------------------------------


def _skip_quoted(text: str, start: int, limit: int) -> int | None:
    quote = text[start]
    pos = start + 1
    while pos < limit:
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == quote:
            return pos + 1
        pos += 1
    return None


def _skip_template(text: str, start: int, limit: int) -> int | None:
    """Skip a backtick template literal, treating ${ ... } as opaque."""
    pos = start + 1
    while pos < limit:
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "`":
            return pos + 1
        pos += 1
    return None


def _skip_line_comment(text: str, start: int, limit: int) -> int:
    newline = text.find("\n", start + 2, limit)
    return limit if newline < 0 else newline + 1


def _skip_block_comment(text: str, start: int, limit: int) -> int | None:
    end = text.find("*/", start + 2, limit)
    return None if end < 0 else end + 2


def _can_start_regex(text: str, start: int, limit: int) -> bool:
    if start >= limit or text[start] != "/" or start + 1 >= limit:
        return False
    if text[start + 1] in "/* \\t\r\n":
        return False
    pos = start - 1
    while pos >= 0 and text[pos] in " \t\r\n":
        pos -= 1
    if pos < 0:
        return True
    return text[pos] in _REGEX_PRECEDING


def _skip_regex(text: str, start: int, limit: int) -> int | None:
    pos = start + 1
    in_class = False
    while pos < limit:
        char = text[pos]
        if char == "\\":
            pos += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            pos += 1
            while pos < limit and text[pos].isalpha():
                pos += 1
            return pos
        elif char == "\n":
            return None
        pos += 1
    return None


def _skip_literal(text: str, start: int, limit: int) -> int | None:
    """Skip a string/template/comment/regex literal starting at start."""
    char = text[start]
    if char in "\"'":
        return _skip_quoted(text, start, limit)
    if char == "`":
        return _skip_template(text, start, limit)
    if text.startswith("//", start):
        return _skip_line_comment(text, start, limit)
    if text.startswith("/*", start):
        return _skip_block_comment(text, start, limit)
    if char == "/" and _can_start_regex(text, start, limit):
        return _skip_regex(text, start, limit)
    return None


def _find_matching(text: str, start: int, limit: int, open_ch: str, close_ch: str) -> int | None:
    """Balanced scan: returns index just past the matching close_ch."""
    depth = 1
    pos = start
    while pos < limit:
        char = text[pos]
        if char in "\"'`":
            end = _skip_literal(text, pos, limit)
            if end is None:
                return None
            pos = end
            continue
        if char == "/":
            end = _skip_literal(text, pos, limit)
            if end is not None:
                pos = end
                continue
        if char == open_ch:
            depth += 1
        elif char == close_ch:
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None


def _read_string_literal(text: str, start: int, limit: int) -> tuple[str, int] | None:
    if start >= limit or text[start] not in "\"'":
        return None
    end = _skip_quoted(text, start, limit)
    if end is None:
        return None
    raw = text[start + 1 : end - 1]
    return raw.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\"), end


def _read_name_list(text: str, start: int, limit: int) -> tuple[list[str], int] | None:
    """Read ['a', 'b'] at start; returns (names, end)."""
    if start >= limit or text[start] != "[":
        return None
    pos = start + 1
    names: list[str] = []
    while pos < limit:
        while pos < limit and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= limit:
            return None
        if text[pos] == "]":
            return names, pos + 1
        parsed = _read_string_literal(text, pos, limit)
        if parsed is None:
            return None
        name, pos = parsed
        names.append(name)
    return None


# ---------------------------------------------------------------------------
# Definition extraction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JsCall:
    function: str
    names: tuple[str, ...] | None = None
    dynamic_name: str | None = None
    alias_of: str | None = None
    tags: tuple[str, ...] | None = None  # None = absent, () = tags: null
    tags_dynamic: bool = False
    skip_args: object = None  # None | bool | tuple[str, ...]
    skip_args_dynamic: bool = False
    source_kind: str = "game_js"
    evidence: str = ""


@dataclass(frozen=True)
class EffectiveSpec:
    name: str
    container: bool
    tags: tuple[str, ...]
    main_raw: bool
    tag_raw: frozenset[str]
    skip_args_all: bool = False
    source_kind: str = "game_js"
    evidence: str = ""
    alias_of: str | None = None

    def tag_mode(self, tag: str) -> str:
        if self.skip_args_all or tag in self.tag_raw:
            return "raw"
        return "parsed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "container": self.container,
            "tags": list(self.tags),
            "main_raw": self.main_raw,
            "tag_raw": sorted(self.tag_raw),
            "skip_args_all": self.skip_args_all,
            "source_kind": self.source_kind,
            "evidence": self.evidence,
            "alias_of": self.alias_of,
        }


def _split_call_args(text: str, call_start: int, limit: int) -> tuple[list[str], int] | None:
    """Split the parenthesised argument list of a call at call_start."""
    open_pos = text.index("(", call_start, limit)
    end = _find_matching(text, open_pos + 1, limit, "(", ")")
    if end is None:
        return None, limit
    body = text[open_pos + 1 : end - 1]
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    pos = 0
    while pos < len(body):
        char = body[pos]
        if char in "\"'`":
            skipped = _skip_literal(body, pos, len(body))
            if skipped is None:
                return None, end
            current.append(body[pos:skipped])
            pos = skipped
            continue
        if char == "/":
            skipped = _skip_literal(body, pos, len(body))
            if skipped is not None:
                current.append(body[pos:skipped])
                pos = skipped
                continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
            if depth < 0:
                return None, end
        elif char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
            pos += 1
            continue
        current.append(char)
        pos += 1
    if depth != 0:
        return None, end
    parts.append("".join(current).strip())
    return parts, end


def _parse_options_object(text: str, obj_start: int, limit: int) -> dict[str, str]:
    """Extract top-level key: value pairs of an object literal."""
    result: dict[str, str] = {}
    depth = 0
    pos = obj_start
    while pos < limit:
        char = text[pos]
        if char in "\"'`":
            end = _skip_literal(text, pos, limit)
            if end is None:
                return result
            pos = end
            continue
        if char == "/":
            end = _skip_literal(text, pos, limit)
            if end is not None:
                pos = end
                continue
        if char == "{":
            depth += 1
            pos += 1
            continue
        if char == "}":
            if depth == 0:
                return result
            depth -= 1
            pos += 1
            continue
        if depth == 1 and (char.isalpha() or char == "_" or char == "$"):
            match = _IDENT_RE.match(text, pos, limit)
            assert match is not None
            key = match.group(0)
            cursor = match.end()
            while cursor < limit and text[cursor] in " \t\r\n":
                cursor += 1
            if cursor < limit and text[cursor] == ":":
                value_start = cursor + 1
                while value_start < limit and text[value_start] in " \t\r\n":
                    value_start += 1
                value_end = _scan_value_end(text, value_start, limit)
                result[key] = text[value_start:value_end].strip()
                pos = value_end
                continue
            pos = cursor
            continue
        pos += 1
    return result


def _scan_value_end(text: str, start: int, limit: int) -> int:
    depth = 0
    pos = start
    while pos < limit:
        char = text[pos]
        if char in "\"'`":
            end = _skip_literal(text, pos, limit)
            if end is None:
                return pos
            pos = end
            continue
        if char == "/":
            end = _skip_literal(text, pos, limit)
            if end is not None:
                pos = end
                continue
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return pos
            depth -= 1
        elif char == "," and depth == 0:
            return pos
        elif char == "\n" and depth == 0:
            return pos
        pos += 1
    return limit


def _interpret_tags(value: str) -> tuple[tuple[str, ...] | None, bool]:
    if value == "null":
        return (), False
    if value == "":
        return None, True
    parsed = _read_name_list(value, 0, len(value))
    if parsed is not None:
        names, end = parsed
        if value[end:].strip() == "":
            return tuple(names), False
    return None, True


def _interpret_skip_args(value: str) -> tuple[object, bool]:
    if value == "true":
        return True, False
    if value == "false":
        return False, False
    if value == "":
        return None, True
    parsed = _read_name_list(value, 0, len(value))
    if parsed is not None:
        names, end = parsed
        if value[end:].strip() == "":
            return tuple(names), False
    return None, True


def _extract_js_call(text: str, call_start: int, limit: int, path: str) -> JsCall | None:
    match = _CALL_RE.match(text, call_start, limit)
    if match is None:
        return None
    function = match.group(0)
    parts, end = _split_call_args(text, match.end(), limit)
    if parts is None or not parts:
        return None
    line = text.count("\n", 0, call_start) + 1
    evidence = f"{path}:{line}"
    arg0 = parts[0]
    names: tuple[str, ...] | None = None
    dynamic_name: str | None = None
    name_parsed = _read_string_literal(arg0, 0, len(arg0))
    if name_parsed is not None:
        names = (name_parsed[0],)
    else:
        name_list = _read_name_list(arg0, 0, len(arg0))
        if name_list is not None:
            names = tuple(name_list[0])
        else:
            ident = _IDENT_RE.match(arg0)
            dynamic_name = ident.group(0) if ident else arg0

    call = JsCall(function=function, names=names, dynamic_name=dynamic_name, evidence=evidence)
    if len(parts) < 2:
        return call
    second = parts[1]
    if function == "Macro.add":
        alias = _read_string_literal(second, 0, len(second))
        if alias is not None:
            return JsCall(function=function, names=names, dynamic_name=dynamic_name,
                          alias_of=alias[0], evidence=evidence)
        options = _parse_options_object(second, second.find("{") if "{" in second else 0, len(second))
        tags, tags_dynamic = _interpret_tags(options.get("tags", ""))
        skip_args, skip_args_dynamic = _interpret_skip_args(options.get("skipArgs", ""))
        return JsCall(function=function, names=names, dynamic_name=dynamic_name,
                      tags=tags, tags_dynamic=tags_dynamic,
                      skip_args=skip_args, skip_args_dynamic=skip_args_dynamic,
                      evidence=evidence)
    if function in ("DefineMacro", "DefineMacroS"):
        tags: tuple[str, ...] | None = None
        tags_dynamic = False
        skip_args: object = None
        skip_args_dynamic = False
        if len(parts) >= 3:
            tags, tags_dynamic = _interpret_tags(parts[2])
        if len(parts) >= 4:
            skip_args, skip_args_dynamic = _interpret_skip_args(parts[3])
        return JsCall(function=function, names=names, dynamic_name=dynamic_name,
                      tags=tags, tags_dynamic=tags_dynamic,
                      skip_args=skip_args, skip_args_dynamic=skip_args_dynamic,
                      evidence=evidence)
    return call


def extract_js_calls(text: str, path: str) -> list[JsCall]:
    """Find macro-definition calls in JS text, skipping string/comment/regex bodies."""
    calls: list[JsCall] = []
    limit = len(text)
    pos = 0
    while pos < limit:
        char = text[pos]
        if char in "\"'`":
            end = _skip_literal(text, pos, limit)
            if end is None:
                pos += 1
                continue
            pos = end
            continue
        if char == "/":
            end = _skip_literal(text, pos, limit)
            if end is not None:
                pos = end
                continue
        if char.isalpha() or char == "_" or char == "$":
            call = _extract_js_call(text, pos, limit, path)
            if call is not None:
                calls.append(call)
                pos = pos + 2
                # Re-scan from just past the call name for nested definitions
                # (e.g. Macro.add inside a handler) without re-matching this one.
                continue
        pos += 1
    return calls


# ---------------------------------------------------------------------------
# Effective spec resolution
# ---------------------------------------------------------------------------


def resolve_effective_specs(calls: Sequence[JsCall]) -> dict[str, EffectiveSpec]:
    """Apply delete/add/alias operations in order; returns final specs."""
    state: dict[str, EffectiveSpec] = {}
    order: list[str] = []
    for call in calls:
        if call.names is None:
            continue
        if call.function == "Macro.delete":
            for name in call.names:
                key = name.lower()
                if key in state:
                    del state[key]
            continue
        if call.function == "Macro.add" and call.alias_of is not None:
            for name in call.names:
                key = name.lower()
                if key in state:
                    del state[key]
                order.append(key)
                state[key] = EffectiveSpec(
                    name=name,
                    container=False,
                    tags=(),
                    main_raw=False,
                    tag_raw=frozenset(),
                    source_kind=call.source_kind,
                    evidence=call.evidence,
                    alias_of=call.alias_of.lower(),
                )
            continue
        source_kind = call.source_kind
        for name in call.names:
            key = name.lower()
            tags = call.tags
            skip_args = call.skip_args
            skip_args_all = skip_args is True
            main_raw = skip_args_all or (
                isinstance(skip_args, tuple) and key in skip_args
            )
            tag_raw = frozenset(
                tag for tag in (tags or ())
                if skip_args_all or (isinstance(skip_args, tuple) and tag in skip_args)
            )
            state[key] = EffectiveSpec(
                name=name,
                container=tags is not None,
                tags=tuple(tags or ()),
                main_raw=main_raw,
                tag_raw=tag_raw,
                skip_args_all=skip_args_all,
                source_kind=source_kind,
                evidence=call.evidence,
            )
    for key in order:
        spec = state.get(key)
        if spec is None or spec.alias_of is None:
            continue
        target = state.get(spec.alias_of)
        if target is None or target.alias_of is not None:
            continue
        state[key] = EffectiveSpec(
            name=spec.name,
            container=target.container,
            tags=target.tags,
            main_raw=target.main_raw,
            tag_raw=target.tag_raw,
            skip_args_all=target.skip_args_all,
            source_kind=spec.source_kind,
            evidence=spec.evidence,
            alias_of=spec.alias_of,
        )
    return state


def extract_sugarcube_specs(root: str | Path) -> dict[str, EffectiveSpec]:
    """Extract final effective specs from a SugarCube source checkout."""
    root = Path(root)
    calls: list[JsCall] = []
    macros_dir = root / "src/macro/macros"
    for path in sorted(macros_dir.glob("*.js")):
        for call in extract_js_calls(path.read_text(encoding="utf-8"), path.as_posix()):
            calls.append(JsCall(
                function=call.function, names=call.names, dynamic_name=call.dynamic_name,
                alias_of=call.alias_of, tags=call.tags, tags_dynamic=call.tags_dynamic,
                skip_args=call.skip_args, skip_args_dynamic=call.skip_args_dynamic,
                source_kind="sugarcube", evidence=call.evidence))
    deprecated_file = root / "src/macro/deprecated-macros.js"
    if deprecated_file.exists():
        for call in extract_js_calls(deprecated_file.read_text(encoding="utf-8"),
                                     deprecated_file.as_posix()):
            calls.append(JsCall(
                function=call.function, names=call.names, dynamic_name=call.dynamic_name,
                alias_of=call.alias_of, tags=call.tags, tags_dynamic=call.tags_dynamic,
                skip_args=call.skip_args, skip_args_dynamic=call.skip_args_dynamic,
                source_kind="sugarcube_deprecated", evidence=call.evidence))
    return resolve_effective_specs(calls)


@functools.lru_cache(maxsize=64)
def _extract_game_js_calls_cached(root: Path) -> list[JsCall]:
    """Collect raw Macro.add/DefineMacro/Macro.delete calls from game/**/*.js.

    Cached by root path so audit, dynamic-detection, and determinism checks in
    one process parse the JS corpus once.  Effective-spec resolution and
    dynamic-name filtering run on the cached call list.
    """
    all_calls: list[JsCall] = []
    for path in sorted(root.rglob("*.js")):
        for call in extract_js_calls(path.read_text(encoding="utf-8"),
                                     path.relative_to(root).as_posix()):
            all_calls.append(call)
    return all_calls


def extract_game_specs(root: str | Path, sugarcube_specs: Mapping[str, EffectiveSpec]) -> dict[str, EffectiveSpec]:
    """Extract final effective specs from game/**/*.js, layered over SC specs."""
    root = Path(root)
    game_specs = resolve_effective_specs(_extract_game_js_calls_cached(root))
    result: dict[str, EffectiveSpec] = {}
    for name, spec in sugarcube_specs.items():
        result[name] = spec
    for name, spec in game_specs.items():
        if name in result and spec.source_kind == "game_js":
            game_specs[name] = EffectiveSpec(
                name=spec.name, container=spec.container, tags=spec.tags,
                main_raw=spec.main_raw, tag_raw=spec.tag_raw,
                skip_args_all=spec.skip_args_all,
                source_kind="game_override", evidence=spec.evidence)
    for name, spec in game_specs.items():
        result[name] = spec
    return result


def extract_game_dynamic(root: str | Path) -> list[dict[str, str]]:
    """Report macro definitions whose name is only resolvable at runtime."""
    root = Path(root)
    result: list[dict[str, str]] = []
    for call in _extract_game_js_calls_cached(root):
        if call.names is None and call.dynamic_name:
            result.append({
                "name": call.dynamic_name,
                "function": call.function,
                "evidence": call.evidence,
            })
    return result


# ---------------------------------------------------------------------------
# Snapshot (pinned SugarCube extraction)
# ---------------------------------------------------------------------------


def sugarcube_specs_to_payload(specs: Mapping[str, EffectiveSpec], root: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for name in sorted(specs):
        spec = specs[name]
        entry = spec.to_dict()
        entry.pop("name", None)
        if spec.evidence.startswith(str(Path(root))):
            entry["evidence"] = spec.evidence[len(str(Path(root))) + 1 :]
        payload[name.lower()] = entry
    return payload


def load_sugarcube_snapshot(path: str | Path | Mapping[str, Any]) -> tuple[dict[str, EffectiveSpec], str]:
    if isinstance(path, Mapping):
        payload = path
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = payload.get("macros", payload)
    specs: dict[str, EffectiveSpec] = {}
    for name, data in entries.items():
        key = str(name).lower()
        tags = tuple(data.get("tags", []))
        container = bool(data.get("container", False))
        tag_raw = frozenset(data.get("tag_raw", []))
        specs[key] = EffectiveSpec(
            name=key,
            container=container,
            tags=tags,
            main_raw=bool(data.get("main_raw", False)),
            tag_raw=tag_raw,
            skip_args_all=bool(data.get("skip_args_all", False)),
            source_kind=str(data.get("source_kind", "sugarcube")),
            evidence=str(data.get("evidence", "")),
            alias_of=data.get("alias_of"),
        )
    return specs, str(payload.get("pinned_source", ""))


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditIssue:
    severity: str  # "error" | "warning" | "info"
    kind: str
    macro: str
    manifest_value: str = ""
    source_value: str = ""
    evidence: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "kind": self.kind,
            "macro": self.macro,
            "manifest": self.manifest_value,
            "source": self.source_value,
            "evidence": self.evidence,
            "detail": self.detail,
        }


@dataclass
class AuditReport:
    issues: list[AuditIssue] = field(default_factory=list)
    trace: dict[str, dict[str, str]] = field(default_factory=dict)
    dynamic_definitions: list[dict[str, str]] = field(default_factory=list)
    manifest_version: str = ""
    pinned_source: str = ""

    @property
    def errors(self) -> list[AuditIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_version": self.manifest_version,
            "pinned_source": self.pinned_source,
            "errors": len(self.errors),
            "issues": [issue.to_dict() for issue in self.issues],
            "trace": self.trace,
            "dynamic_definitions": self.dynamic_definitions,
        }


def _branch_source_name(macro: str, tag: str) -> str:
    return f"{macro}.{tag}"


def _load_allowlist(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("entries", payload)


def _expected_manifest_spec(spec: EffectiveSpec) -> dict[str, str]:
    expected: dict[str, str] = {
        "body_kind": "container" if spec.container else "leaf",
        "arg_mode": "raw" if spec.main_raw else "parsed",
        "source": spec.source_kind,
    }
    for tag in sorted(spec.tags):
        expected[f"tag:{tag}"] = spec.tag_mode(tag)
    return expected


def audit_manifest(
    grammar_path: str | Path,
    game_root: str | Path,
    sugarcube_specs: Mapping[str, EffectiveSpec],
    allowlist_path: str | Path,
    game_specs_override: Mapping[str, EffectiveSpec] | None = None,
) -> AuditReport:
    """Compare macro-grammar.json against the extracted effective specs."""
    report = AuditReport()
    payload = json.loads(Path(grammar_path).read_text(encoding="utf-8"))
    report.manifest_version = str(payload.get("version", ""))
    report.pinned_source = str(payload.get("pinned_sources", {}).get("sugarcube", ""))
    macros_raw = payload.get("macros", payload)
    macros = {str(name).lower(): data for name, data in macros_raw.items()}
    allowlist = _load_allowlist(allowlist_path)

    game_specs = game_specs_override
    if game_specs is None:
        game_specs = extract_game_specs(game_root, sugarcube_specs)
    report.dynamic_definitions.extend(extract_game_dynamic(game_root))

    branch_parents: dict[str, list[EffectiveSpec]] = {}
    for spec in game_specs.values():
        for tag in spec.tags:
            branch_parents.setdefault(tag.lower(), []).append(spec)

    for name in sorted(macros):
        key = str(name).lower()
        entry = macros[name] if isinstance(macros, dict) else {}
        spec = game_specs.get(key)
        manifest_body = str(entry.get("body_kind", "leaf"))
        manifest_arg_mode = str(entry.get("arg_mode", "parsed"))
        manifest_source = str(entry.get("source", "unknown"))
        manifest_tags = entry.get("tags", {}) if isinstance(entry, dict) else {}

        if spec is None:
            parents = branch_parents.get(key)
            if parents:
                branch_sources = {parent.source_kind for parent in parents}
                if manifest_source not in branch_sources:
                    report.issues.append(AuditIssue(
                        "error", "branch_source_kind_mismatch", key,
                        manifest_value=manifest_source,
                        source_value=",".join(sorted(branch_sources)),
                        evidence=parents[0].evidence,
                        detail=f"child tag of {', '.join(sorted(p.name for p in parents))}"))
                expected_modes = {parent.tag_mode(key) for parent in parents}
                if manifest_arg_mode not in expected_modes:
                    allowed = manifest_arg_mode == "none" and any(
                        _branch_source_name(parent.name, key) in allowlist
                        for parent in parents
                    )
                    if not allowed:
                        report.issues.append(AuditIssue(
                            "error", "branch_arg_mode_mismatch", key,
                            manifest_value=manifest_arg_mode,
                            source_value=",".join(sorted(expected_modes)),
                            evidence=parents[0].evidence))
                report.trace[key] = {
                    "source": ",".join(sorted(branch_sources)),
                    "evidence": parents[0].evidence,
                    "body_kind": "leaf",
                    "arg_mode": manifest_arg_mode,
                    "tags": "",
                    "alias_of": "",
                    "branch_of": ",".join(sorted(parent.name for parent in parents)),
                }
                continue
            if key in allowlist and any(
                item.get("kind") == "manifest_entry_without_source"
                for item in allowlist[key] if isinstance(item, dict)
            ):
                report.trace[key] = {
                    "source": "(engine-patch, allowlisted)",
                    "evidence": allowlist[key][0].get("evidence", ""),
                    "body_kind": manifest_body,
                    "arg_mode": manifest_arg_mode,
                    "tags": "",
                    "alias_of": "",
                    "branch_of": "",
                }
                continue
            report.issues.append(AuditIssue(
                "error", "manifest_entry_without_source", key,
                manifest_value=manifest_source, source_value="(none)",
                detail="no Macro.add/DefineMacro/alias definition in SugarCube or game JS"))
            continue
        if manifest_source != spec.source_kind:
            report.issues.append(AuditIssue(
                "error", "source_kind_mismatch", key,
                manifest_value=manifest_source, source_value=spec.source_kind,
                evidence=spec.evidence))
        expected = _expected_manifest_spec(spec)
        if expected["body_kind"] != manifest_body:
            report.issues.append(AuditIssue(
                "error", "body_kind_mismatch", key,
                manifest_value=manifest_body, source_value=expected["body_kind"],
                evidence=spec.evidence))
        if expected["arg_mode"] != manifest_arg_mode:
            allowed = False
            if manifest_arg_mode == "none" and key in allowlist:
                allowed = any(
                    item.get("kind") == "handler_none_args"
                    for item in allowlist[key] if isinstance(item, dict)
                )
            if not allowed:
                report.issues.append(AuditIssue(
                    "error", "arg_mode_mismatch", key,
                    manifest_value=manifest_arg_mode, source_value=expected["arg_mode"],
                    evidence=spec.evidence))
        manifest_tag_keys = {str(tag).lower() for tag in manifest_tags}
        if manifest_tag_keys != set(spec.tags):
            report.issues.append(AuditIssue(
                "error", "tags_mismatch", key,
                manifest_value=",".join(sorted(manifest_tag_keys)),
                source_value=",".join(sorted(spec.tags)),
                evidence=spec.evidence))
        for tag in sorted(spec.tags):
            expected_mode = spec.tag_mode(tag)
            manifest_mode = str(manifest_tags.get(tag, "parsed")).lower()
            if expected_mode != manifest_mode:
                allowed = manifest_mode == "none" and _branch_source_name(key, tag) in allowlist
                if not allowed:
                    report.issues.append(AuditIssue(
                        "error", "tag_arg_mode_mismatch", _branch_source_name(key, tag),
                        manifest_value=manifest_mode, source_value=expected_mode,
                        evidence=spec.evidence))
        report.trace[key] = {
            "source": spec.source_kind,
            "evidence": spec.evidence,
            "body_kind": spec.container and "container" or "leaf",
            "arg_mode": "raw" if spec.main_raw else "parsed",
            "tags": ",".join(sorted(spec.tags)),
            "alias_of": spec.alias_of or "",
        }

    for key in sorted(game_specs):
        spec = game_specs[key]
        if key not in macros:
            if spec.container:
                report.issues.append(AuditIssue(
                    "error", "source_container_missing_from_manifest", key,
                    source_value="container",
                    evidence=spec.evidence,
                    detail="container defined in source but absent from macro-grammar.json"))
                continue
            if spec.main_raw or spec.skip_args_all:
                report.issues.append(AuditIssue(
                    "error", "missing_source_raw_macro", key,
                    source_value="raw",
                    evidence=spec.evidence,
                    detail="skipArgs:true macro defined in source but absent from macro-grammar.json"))
        for tag in sorted(spec.tags):
            if spec.tag_mode(tag) == "raw" and tag not in macros:
                report.issues.append(AuditIssue(
                    "error", "missing_source_raw_tag", f"{key}.{tag}",
                    source_value="raw",
                    evidence=spec.evidence,
                    detail="raw branch tag defined in source but absent from macro-grammar.json"))

    return report


def _drift_compare(
    live_specs: Mapping[str, EffectiveSpec],
    snapshot_specs: Mapping[str, EffectiveSpec],
) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    for key in sorted(set(live_specs) | set(snapshot_specs)):
        live_spec = live_specs.get(key)
        snapshot_spec = snapshot_specs.get(key)
        if live_spec is None or snapshot_spec is None:
            issues.append(AuditIssue(
                "error", "sugarcube_drift", key,
                source_value="(snapshot)" if live_spec is None else "(live)",
                detail="macro present in only one of live SugarCube source / pinned snapshot"))
            continue
        for attr in ("container", "main_raw", "skip_args_all"):
            if getattr(live_spec, attr) != getattr(snapshot_spec, attr):
                issues.append(AuditIssue(
                    "error", "sugarcube_drift", key,
                    source_value=str(getattr(live_spec, attr)),
                    manifest_value=str(getattr(snapshot_spec, attr)),
                    detail=attr,
                    evidence=live_spec.evidence))
        if set(live_spec.tags) != set(snapshot_spec.tags):
            issues.append(AuditIssue(
                "error", "sugarcube_drift", key,
                source_value=",".join(sorted(live_spec.tags)),
                manifest_value=",".join(sorted(snapshot_spec.tags)),
                detail="tags",
                evidence=live_spec.evidence))
        if live_spec.alias_of != snapshot_spec.alias_of:
            issues.append(AuditIssue(
                "error", "sugarcube_drift", key,
                source_value=str(live_spec.alias_of),
                manifest_value=str(snapshot_spec.alias_of),
                detail="alias_of",
                evidence=live_spec.evidence))
    return issues


def audit_sugarcube_drift(
    live_root: str | Path,
    snapshot_specs: Mapping[str, EffectiveSpec],
) -> list[AuditIssue]:
    """Compare a live SugarCube checkout against the pinned snapshot."""
    live = extract_sugarcube_specs(live_root)
    return _drift_compare(live, snapshot_specs)


# ---------------------------------------------------------------------------
# Corpus check
# ---------------------------------------------------------------------------


def audit_corpus(
    corpus_root: str | Path,
    grammar_path: str | Path,
    game_specs: Mapping[str, EffectiveSpec],
    value_kind_path: str | Path | None = None,
) -> tuple[dict[str, int], list[AuditIssue], int, int]:
    """Parse the corpus and attribute close/structure diagnostics."""
    from .parser import parse_file

    corpus_root = Path(corpus_root)
    counts: dict[str, int] = {}
    issues: list[AuditIssue] = []
    files = 0
    passages = 0
    for path in sorted(corpus_root.rglob("*.twee")):
        data = path.read_bytes()
        source = parse_file(data, path.as_posix(), value_kind_path, grammar_path=grammar_path)
        files += 1
        for passage in source.passages:
            passages += 1
            for diagnostic in passage.diagnostics:
                counts[diagnostic.code] = counts.get(diagnostic.code, 0) + 1
                if diagnostic.code == "mismatched_close":
                    closed_name = (diagnostic.macro_name or "").lstrip("/").lower()
                    spec = game_specs.get(closed_name)
                    if spec is not None and spec.container:
                        issues.append(AuditIssue(
                            "error", "registry_gap_mismatched_close", closed_name,
                            source_value="container",
                            evidence=spec.evidence,
                            detail=f"{path.as_posix()}:{diagnostic.span.start if diagnostic.span else '?'}"))
                elif diagnostic.code == "unclosed_container":
                    name = (diagnostic.macro_name or "").lower()
                    spec = game_specs.get(name)
                    if spec is not None and not spec.container:
                        issues.append(AuditIssue(
                            "error", "registry_false_container", name,
                            source_value="leaf",
                            evidence=spec.evidence,
                            detail=f"{path.as_posix()}:{diagnostic.span.start if diagnostic.span else '?'}"))
    return counts, issues, files, passages


def _format_report(report: AuditReport, counts: dict[str, int] | None,
                   corpus_summary: tuple[int, int] | None) -> str:
    lines = [
        f"manifest: {report.manifest_version}",
        f"pinned sugarcube: {report.pinned_source}",
        f"errors: {len(report.errors)}",
    ]
    if corpus_summary is not None:
        files, passages = corpus_summary
        lines.append(f"corpus: {files} files, {passages} passages")
        if counts:
            for code in sorted(counts):
                lines.append(f"  diagnostic {code}: {counts[code]}")
    for issue in report.issues:
        lines.append(
            f"[{issue.severity}] {issue.kind} {issue.macro}: "
            f"manifest={issue.manifest_value!r} source={issue.source_value!r} "
            f"evidence={issue.evidence} {issue.detail}"
        )
    if report.dynamic_definitions:
        lines.append("dynamic definitions (name resolved at runtime, not audited):")
        for item in report.dynamic_definitions:
            lines.append(f"  {item['name']} {item['evidence']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    audit = subparsers.add_parser("audit", help="compare manifest against sources")
    audit.add_argument("--grammar", type=Path, default=DEFAULT_GRAMMAR_PATH)
    audit.add_argument("--game", type=Path, default=None,
                       help="game root containing **/*.js (default: repo game/)")
    audit.add_argument("--sugarcube", type=Path, default=None,
                       help="live SugarCube checkout; checked against the pinned snapshot")
    audit.add_argument("--sugarcube-json", type=Path, default=DEFAULT_SUGARCUBE_SNAPSHOT)
    audit.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST_PATH)
    audit.add_argument("--corpus", type=Path, default=None,
                       help="parse this twee root and attribute structure diagnostics")
    audit.add_argument("--value-kind", type=Path, default=DEFAULT_VALUE_KIND_PATH)
    audit.add_argument("--json-out", type=Path, default=None)
    extract = subparsers.add_parser(
        "extract-sugarcube",
        help="(read-only) print the SugarCube macro extraction as JSON")
    extract.add_argument("--root", type=Path, required=True)
    extract.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    if args.command == "extract-sugarcube":
        specs = extract_sugarcube_specs(args.root)
        payload = {
            "pinned_source": f"sugarcube-2 at {args.root}",
            "macros": sugarcube_specs_to_payload(specs, args.root),
        }
        text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
        if args.out is not None:
            args.out.write_text(text + "\n", encoding="utf-8")
            return 0
        print(text)
        return 0

    if args.command not in ("audit",):
        parser.error("missing command: audit | extract-sugarcube")

    game_root = Path(args.game) if args.game is not None else DEFAULT_GAME_ROOT
    snapshot_specs, pinned_source = load_sugarcube_snapshot(args.sugarcube_json)
    if args.sugarcube is not None:
        drift = audit_sugarcube_drift(args.sugarcube, snapshot_specs)
    else:
        drift = []
    game_specs = extract_game_specs(game_root, snapshot_specs)
    report = audit_manifest(args.grammar, game_root, snapshot_specs, args.allowlist,
                            game_specs_override=game_specs)
    report.issues[0:0] = drift
    report.pinned_source = pinned_source

    corpus_counts: dict[str, int] | None = None
    corpus_summary: tuple[int, int] | None = None
    if args.corpus is not None:
        corpus_counts, corpus_issues, files, passages = audit_corpus(
            args.corpus, args.grammar, game_specs, args.value_kind)
        report.issues.extend(corpus_issues)
        corpus_summary = (files, passages)

    if args.json_out is not None:
        out = {
            "schema_version": 1,
            "report": report.to_dict(),
            "corpus": {
                "files": corpus_summary[0] if corpus_summary else None,
                "passages": corpus_summary[1] if corpus_summary else None,
                "diagnostics": corpus_counts,
            },
        }
        args.json_out.write_text(
            json.dumps(out, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
            encoding="utf-8")

    print(_format_report(report, corpus_counts, corpus_summary))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
