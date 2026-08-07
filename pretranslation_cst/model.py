from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, order=True)
class Span:
    """A file-relative UTF-8 byte span, represented as [start, end)."""

    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span [{self.start}, {self.end})")

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
class MacroNode:
    span: Span
    name: str
    name_span: Span
    raw_args_span: Span
    args: list[ArgNode]
    role: str = "call"
    closing_span: Span | None = None
    body_span: Span | None = None
    malformed: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "span": self.span.to_dict(),
            "name": self.name,
            "name_span": self.name_span.to_dict(),
            "raw_args_span": self.raw_args_span.to_dict(),
            "args": [arg.to_dict() for arg in self.args],
            "role": self.role,
            "malformed": self.malformed,
        }
        if self.closing_span is not None:
            result["closing_span"] = self.closing_span.to_dict()
        if self.body_span is not None:
            result["body_span"] = self.body_span.to_dict()
        return result


@dataclass
class Passage:
    source_path: str
    name: str
    tags: list[str]
    header_span: Span
    name_span: Span | None
    body_span: Span
    source_span: Span
    nodes: list[MacroNode] = field(default_factory=list)
    protected_spans: list[Span] = field(default_factory=list)
    exposed_candidates: list[tuple[Span, str]] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source_path": self.source_path,
            "name": self.name,
            "tags": self.tags,
            "header_span": self.header_span.to_dict(),
            "body_span": self.body_span.to_dict(),
            "source_span": self.source_span.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "diagnostics": [item.to_dict() for item in self.diagnostics],
        }
        if self.name_span is not None:
            result["name_span"] = self.name_span.to_dict()
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "placeholder": self.placeholder,
            "source_span": self.source_span.to_dict(),
            "original_text": self.original_text,
            "reason": self.reason,
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
