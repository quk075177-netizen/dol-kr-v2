"""Versioned SugarCube/game macro grammar used by the CST parser."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


ARG_MODES = {"parsed", "raw", "none"}
BODY_KINDS = {"leaf", "container"}
DEFAULT_GRAMMAR_PATH = Path(__file__).with_name("data") / "macro-grammar.json"


@dataclass(frozen=True)
class MacroSpec:
    name: str
    body_kind: str = "leaf"
    arg_mode: str = "parsed"
    tags: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    square_label_args: tuple[int, ...] = ()
    implicit_branch: bool = False
    source: str = "unknown"

    def __post_init__(self) -> None:
        if self.body_kind not in BODY_KINDS:
            raise ValueError(f"invalid body_kind for {self.name}: {self.body_kind}")
        if self.arg_mode not in ARG_MODES:
            raise ValueError(f"invalid arg_mode for {self.name}: {self.arg_mode}")
        invalid_tags = {name: mode for name, mode in self.tags.items() if mode not in ARG_MODES}
        if invalid_tags:
            raise ValueError(f"invalid tag arg_mode for {self.name}: {invalid_tags}")


class MacroRegistry:
    def __init__(self, specs: Mapping[str, MacroSpec]) -> None:
        self._specs = {name.lower(): spec for name, spec in specs.items()}
        self._branch_names = frozenset(
            tag for spec in self._specs.values() for tag in spec.tags
        )

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "MacroRegistry":
        raw_specs = payload.get("macros", payload)
        if not isinstance(raw_specs, Mapping):
            raise ValueError("macro grammar must contain an object of macros")
        specs: dict[str, MacroSpec] = {}
        for raw_name, raw_spec in raw_specs.items():
            name = str(raw_name).lower()
            data = raw_spec if isinstance(raw_spec, Mapping) else {}
            raw_tags = data.get("tags", {})
            if isinstance(raw_tags, list):
                tags = {str(tag).lower(): "parsed" for tag in raw_tags}
            elif isinstance(raw_tags, Mapping):
                tags = {str(tag).lower(): str(mode) for tag, mode in raw_tags.items()}
            else:
                raise ValueError(f"invalid tags for macro {name}")
            specs[name] = MacroSpec(
                name=name,
                body_kind=str(data.get("body_kind", "leaf")),
                arg_mode=str(data.get("arg_mode", "parsed")),
                tags=MappingProxyType(tags),
                square_label_args=tuple(int(index) for index in data.get("square_label_args", [])),
                implicit_branch=bool(data.get("implicit_branch", False)),
                source=str(data.get("source", "unknown")),
            )
        return cls(specs)

    def get(self, name: str) -> MacroSpec:
        key = name.lower().lstrip("/")
        return self._specs.get(key, MacroSpec(key))

    def is_known(self, name: str) -> bool:
        return name.lower().lstrip("/") in self._specs

    def is_branch_name(self, name: str) -> bool:
        return name.lower() in self._branch_names


def _load_payload(path: str | Path | Mapping[str, Any] | None) -> Mapping[str, Any]:
    if path is None:
        return json.loads(DEFAULT_GRAMMAR_PATH.read_text(encoding="utf-8"))
    if isinstance(path, Mapping):
        return path
    return json.loads(Path(path).read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def default_macro_registry() -> MacroRegistry:
    return MacroRegistry.from_payload(_load_payload(None))


def load_macro_registry(path: str | Path | Mapping[str, Any] | None = None) -> MacroRegistry:
    return default_macro_registry() if path is None else MacroRegistry.from_payload(_load_payload(path))
