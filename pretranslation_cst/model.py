"""Small, JSON-friendly data objects used by the Twee CST parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, order=True)
class Span:
    """A file-relative UTF-8 byte span represented as [start, end)."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span [{self.start}, {self.end})")

    def contains(self, other: "Span") -> bool:
        return self.start <= other.start and other.end <= self.end

    def to_dict(self) -> dict[str, int]:
        return {"start": self.start, "end": self.end}


@dataclass
class Diagnostic:
    code: str
    message: str
    span: Span | None = None
    macro_name: str | None = None
    argument_index: int | None = None
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.span is not None:
            result["span"] = self.span.to_dict()
        if self.macro_name is not None:
            result["macro_name"] = self.macro_name
        if self.argument_index is not None:
            result["argument_index"] = self.argument_index
        return result


@dataclass
class ArgNode:
    index: int
    raw_span: Span
    content_span: Span | None
    lexeme_kind: str
    raw_text: str
    value_kind: str | None = None
    evidence: list[str] = field(default_factory=list)
    confidence: str | None = None
    disposition: str = "protect"
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "index": self.index,
            "raw_span": self.raw_span.to_dict(),
            "lexeme_kind": self.lexeme_kind,
            "raw_text": self.raw_text,
            "value_kind": self.value_kind,
            "evidence": self.evidence,
            "confidence": self.confidence,
            "disposition": self.disposition,
        }
        if self.content_span is not None:
            result["content_span"] = self.content_span.to_dict()
        if self.note is not None:
            result["note"] = self.note
        return result


@dataclass
class CstNode:
    span: Span
    node_type: str
    name: str = ""
    role: str = "call"
    name_span: Span | None = None
    raw_args_span: Span | None = None
    args: list[ArgNode] = field(default_factory=list)
    arg_mode: str = "parsed"
    expression_span: Span | None = None
    grammar_source: str | None = None
    closing_span: Span | None = None
    body_span: Span | None = None
    malformed: bool = False
    node_id: str = ""
    parent_id: str | None = None
    sibling_order: int = 0
    depth: int = 0
    children: list["CstNode"] = field(default_factory=list)

    @property
    def byte_span(self) -> Span:
        return self.span

    def to_dict(self, include_children: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "node_id": self.node_id,
            "parent_id": self.parent_id,
            "sibling_order": self.sibling_order,
            "depth": self.depth,
            "byte_span": self.span.to_dict(),
            "node_type": self.node_type,
            "name": self.name,
            "role": self.role,
            "args": [arg.to_dict() for arg in self.args],
            "arg_mode": self.arg_mode,
            "malformed": self.malformed,
            "children": [child.to_dict() for child in self.children] if include_children else [],
        }
        if self.name_span is not None:
            result["name_span"] = self.name_span.to_dict()
        if self.raw_args_span is not None:
            result["raw_args_span"] = self.raw_args_span.to_dict()
        if self.expression_span is not None:
            result["expression_span"] = self.expression_span.to_dict()
        if self.grammar_source is not None:
            result["grammar_source"] = self.grammar_source
        if self.closing_span is not None:
            result["closing_span"] = self.closing_span.to_dict()
        if self.body_span is not None:
            result["body_span"] = self.body_span.to_dict()
        return result


# Kept as a public name for callers of the first draft API.
MacroNode = CstNode


@dataclass(frozen=True)
class ProtectedSpan:
    """A protected byte span plus the kinds of the constructs it covers.

    ``kinds`` holds the macro names (``"he"``, ``"set"``, ...) or the
    generic kind for non-macro spans (``"variable"``, ``"expression"``,
    ``"html"``, ``"comment"``, ``"markup"``, ``"diagnostic"``, ``"body"``).
    Adjacent spans are merged with the union of kinds, so a span can cover
    several macros (e.g. ``<<set $x to 1>><<he>>`` → {"set", "he"}).
    """

    span: Span
    kinds: frozenset[str] = frozenset()

    def to_dict(self) -> dict[str, Any]:
        return {"span": self.span.to_dict(), "kinds": sorted(self.kinds)}


@dataclass
class Passage:
    source_path: str
    name: str
    tags: list[str]
    header_span: Span
    name_span: Span | None
    body_span: Span
    source_span: Span
    nodes: list[CstNode] = field(default_factory=list)
    protected_spans: list[ProtectedSpan] = field(default_factory=list)
    exposed_candidates: list[tuple[Span, str]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    root: CstNode | None = None
    node_index: dict[str, CstNode] = field(default_factory=dict)

    @property
    def is_opaque(self) -> bool:
        return self.root is not None and any(child.node_type == "passage_opaque" for child in self.root.children)

    @property
    def tree(self) -> CstNode | None:
        return self.root

    def get_ancestors(self, node_id: str) -> list[CstNode]:
        node = self.node_index.get(node_id)
        if node is None:
            raise LookupError(f"unknown node_id: {node_id}")
        result: list[CstNode] = []
        while node.parent_id is not None:
            parent = self.node_index.get(node.parent_id)
            if parent is None:
                raise LookupError(f"missing parent for node_id: {node_id}")
            result.append(parent)
            node = parent
        return result

    def get_siblings(self, node_id: str) -> list[CstNode]:
        node = self.node_index.get(node_id)
        if node is None:
            raise LookupError(f"unknown node_id: {node_id}")
        if node.parent_id is None:
            return []
        parent = self.node_index.get(node.parent_id)
        if parent is None:
            raise LookupError(f"missing parent for node_id: {node_id}")
        return [child for child in parent.children if child.node_id != node_id]

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_path": self.source_path,
            "name": self.name,
            "tags": self.tags,
            "header_span": self.header_span.to_dict(),
            "body_span": self.body_span.to_dict(),
            "source_span": self.source_span.to_dict(),
            # The complete hierarchy is in tree. Keep this compatibility list shallow
            # so JSONL output does not repeat every descendant for every macro.
            "nodes": [node.to_dict(include_children=False) for node in self.nodes],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
        if self.name_span is not None:
            result["name_span"] = self.name_span.to_dict()
        if self.root is not None:
            result["tree"] = self.root.to_dict()
        return result


@dataclass
class SourceFile:
    source_path: str
    data: bytes
    passages: list[Passage]
    prefix_span: Span
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        import hashlib

        return {
            "source_path": self.source_path,
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "byte_length": len(self.data),
            "prefix_span": self.prefix_span.to_dict(),
            "passages": [passage.to_dict() for passage in self.passages],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }


@dataclass
class Segment:
    source_span: Span
    text: str
    kind: str

    def to_dict(self) -> dict[str, Any]:
        return {"source_span": self.source_span.to_dict(), "text": self.text, "kind": self.kind}


@dataclass
class Placeholder:
    placeholder: str
    source_span: Span
    original_text: str
    reason: str = "protected"
    order_sensitive: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "placeholder": self.placeholder,
            "source_span": self.source_span.to_dict(),
            "original_text": self.original_text,
            "reason": self.reason,
            "order_sensitive": self.order_sensitive,
        }


@dataclass
class MaskArtifact:
    source_path: str
    passage_name: str
    source_span: Span
    masked_text: str
    segments: list[Segment]
    placeholders: list[Placeholder]
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "passage_name": self.passage_name,
            "source_span": self.source_span.to_dict(),
            "masked_text": self.masked_text,
            "exposed_segments": [segment.to_dict() for segment in self.segments],
            "placeholders": [item.to_dict() for item in self.placeholders],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
