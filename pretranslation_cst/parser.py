"""Lossless Twee splitter, SugarCube scanner, and small CST builder.

The code deliberately keeps the stages visible: first find passage boundaries,
then find macro boundaries, then assemble the tree.  It is easier to debug a
small state machine than a large expression which tries to do all three jobs.
"""

from __future__ import annotations

import bisect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .grammar import MacroRegistry, MacroSpec, load_macro_registry
from .model import ArgNode, CstNode, Diagnostic, Passage, SourceFile, Span
from .square_markup import DYNAMIC_LABEL_MARKERS, exposed_label, parse_square_markup


MACRO_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
PASSAGE_TAG_RE = re.compile(r"[ \t]+\[([^\]]*)\][ \t]*$")
ASCII_SPACE = " \t\r\n\f\v"
SPECIAL_PASSAGES = {
    "StoryData",
    "StoryTitle",
    "StoryInit",
    "StoryInterface",
    "StoryMenu",
    "StoryShare",
}
class TextSource:
    """One UTF-8 decode and its shared character-to-byte lookup table."""

    def __init__(self, data: bytes) -> None:
        self.data = data
        try:
            self.text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"input is not valid UTF-8: {exc}") from exc
        self.char_to_byte = [0]
        for char in self.text:
            self.char_to_byte.append(self.char_to_byte[-1] + len(char.encode("utf-8")))

    def span(self, start: int, end: int) -> Span:
        return Span(self.char_to_byte[start], self.char_to_byte[end])

    def byte_start(self, char_pos: int) -> int:
        return self.char_to_byte[char_pos]

    def char_start(self, byte_pos: int) -> int:
        index = bisect.bisect_left(self.char_to_byte, byte_pos)
        if index >= len(self.char_to_byte) or self.char_to_byte[index] != byte_pos:
            raise ValueError(f"byte offset is not a UTF-8 boundary: {byte_pos}")
        return index


# Name used by the design documents; TextSource remains as a simple implementation name.
SourceContext = TextSource


@dataclass
class MacroScan:
    node: CstNode | None
    end: int
    diagnostic: Diagnostic | None = None


def _load_value_kinds(path: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if path is None:
        return {}
    if isinstance(path, dict):
        payload = path
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload.get("macros", payload) if isinstance(payload, dict) else {}


def _is_space(char: str) -> bool:
    return char in ASCII_SPACE


def _consume_quoted(
    text: str,
    start: int,
    quote: str,
    limit: int | None = None,
    allow_newline: bool = False,
) -> int | None:
    limit = len(text) if limit is None else limit
    pos = start + 1
    while pos < limit:
        char = text[pos]
        if char == "\\":
            if pos + 1 >= limit or text[pos + 1] == "\n":
                return None
            pos += 2
            continue
        if char == quote:
            return pos + 1
        if char == "\n" and not allow_newline:
            return None
        pos += 1
    return None


def _consume_comment(text: str, start: int, limit: int | None = None) -> int | None:
    limit = len(text) if limit is None else limit
    if text.startswith("<!--", start):
        end = text.find("-->", start + 4, limit)
        return None if end < 0 else end + 3
    if text.startswith("/*", start):
        end = text.find("*/", start + 2, limit)
        return None if end < 0 else end + 2
    return None


def _consume_regex(text: str, start: int, limit: int) -> int | None:
    """Consume a JS-like regex literal when a closing slash is present."""
    if start >= limit or text[start] != "/" or start + 1 >= limit or text[start + 1] in "/* \\t\r\n":
        return None
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


def _can_start_regex(text: str, start: int, body_start: int) -> bool:
    pos = start - 1
    while pos >= body_start and _is_space(text[pos]):
        pos -= 1
    if pos < body_start:
        return True
    return text[pos] in "([{:;,=!?&|+-*%^~<>"


_SQUARE_OPENER_RE = re.compile(r"\[\[|\[[<>]?[Ii][Mm][Gg]\[")


def _consume_square(text: str, start: int, limit: int | None = None) -> int | None:
    """Consume [[...]] or image square markup, including nested [[...]]."""
    limit = len(text) if limit is None else limit
    match = _SQUARE_OPENER_RE.match(text, start, limit)
    if match is None:
        return None
    opener = match.end() - 1  # position of the inner "["
    pos = opener + 1
    depth = 1
    while pos < limit:
        if text[pos] == "\\":
            if pos + 1 >= limit or text[pos + 1] == "\n":
                return None
            pos += 2
            continue
        if text.startswith("[[", pos):
            depth += 1
            pos += 2
            continue
        if text.startswith("]]", pos):
            depth -= 1
            pos += 2
            if depth == 0:
                return pos
            continue
        if text[pos] == "\n":
            return None
        pos += 1
    return None


def _consume_bracket_expression(text: str, start: int, limit: int) -> int | None:
    """Consume a JavaScript-like [ ... ] argument, including nested arrays."""
    if start >= limit or text[start] != "[":
        return None
    depth = 1
    pos = start + 1
    while pos < limit:
        if text[pos] in "\"'`":
            end = _consume_quoted(text, pos, text[pos], limit, allow_newline=text[pos] == "`")
            if end is None:
                return None
            pos = end
            continue
        if text[pos] == "\\":
            pos += 2
            continue
        if text[pos] == "[":
            depth += 1
        elif text[pos] == "]":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return None


def _consume_macro_body(text: str, start: int, limit: int) -> tuple[int | None, str | None]:
    pos = start
    while pos < limit:
        if text.startswith(">>", pos):
            return pos + 2, None
        if text.startswith("/*", pos) or text.startswith("//", pos):
            if text.startswith("//", pos):
                newline = text.find("\n", pos + 2, limit)
                pos = limit if newline < 0 else newline + 1
                continue
            end = _consume_comment(text, pos, limit)
            if end is None:
                return None, "unterminated block comment"
            pos = end
            continue
        if text[pos] in "`\"'":
            end = _consume_quoted(text, pos, text[pos], limit, allow_newline=text[pos] == "`")
            if end is None:
                return None, "unterminated quoted macro argument"
            pos = end
            continue
        if text[pos] == "[":
            end = _consume_square(text, pos, limit)
            if end is not None:
                pos = end
                continue
        if text[pos] == "/" and _can_start_regex(text, pos, start):
            end = _consume_regex(text, pos, limit)
            if end is not None:
                pos = end
                continue
        pos += 1
    return None, "unterminated macro (missing >>)"


def _lex_args(source: TextSource, start: int, end: int) -> tuple[list[ArgNode], str | None]:
    text = source.text
    pos = start
    result: list[ArgNode] = []
    while pos < end:
        while pos < end and _is_space(text[pos]):
            pos += 1
        if pos >= end:
            break
        token_start = pos
        content_start: int | None = None
        if text[pos] in "`\"'":
            token_end = _consume_quoted(text, pos, text[pos], end, allow_newline=text[pos] == "`")
            if token_end is None:
                return result, "unterminated quoted macro argument"
            content_start = pos + 1
            kind = "expression" if text[pos] == "`" else "string"
        elif text[pos] == "[":
            token_end = _consume_square(text, pos, end)
            if token_end is None:
                token_end = _consume_bracket_expression(text, pos, end)
            if token_end is None:
                return result, "malformed or unterminated square-bracket argument"
            kind = "square_bracket"
        else:
            token_end = pos
            while token_end < end and not _is_space(text[token_end]):
                token_end += 1
            kind = "bareword"
        result.append(ArgNode(
            index=len(result),
            raw_span=source.span(token_start, token_end),
            content_span=source.span(content_start, token_end - 1) if content_start is not None else None,
            lexeme_kind=kind,
            raw_text=text[token_start:token_end],
        ))
        pos = token_end
    return result, None


def _parse_macro(source: TextSource, start: int, limit: int) -> MacroScan:
    text = source.text
    pos = start + 2
    closing = False
    if pos < limit and text[pos] == "/":
        closing = True
        pos += 1
    name_start = pos
    if pos < limit and text[pos] in "=-":
        pos += 1
    else:
        match = MACRO_NAME_RE.match(text, pos, limit)
        if match is None:
            return MacroScan(None, min(start + 2, limit), Diagnostic(
                "invalid_macro_name", "invalid macro name", source.span(start, min(start + 2, limit))))
        pos = match.end()
    name_end = pos
    while pos < limit and _is_space(text[pos]):
        pos += 1
    args_start = pos
    body_end, body_error = _consume_macro_body(text, args_start, limit)
    if body_end is None:
        return MacroScan(None, limit, Diagnostic("malformed_macro", body_error or "malformed macro", source.span(start, limit)))
    close_start = body_end - 2
    node = CstNode(
        span=source.span(start, body_end),
        node_type="macro_call",
        name=("/" if closing else "") + text[name_start:name_end],
        role="call",
        name_span=source.span(name_start - (1 if closing else 0), name_end),
        raw_args_span=source.span(args_start, close_start),
    )
    return MacroScan(node, body_end)


def _raw_args_text(source: TextSource, node: CstNode) -> str:
    if node.raw_args_span is None:
        return ""
    start = source.char_start(node.raw_args_span.start)
    end = source.char_start(node.raw_args_span.end)
    return source.text[start:end]


def _decode_macro_args(
    source: TextSource,
    node: CstNode,
    spec: MacroSpec,
    diagnostics: list[Diagnostic],
) -> None:
    node.arg_mode = spec.arg_mode
    node.grammar_source = spec.source
    raw_text = _raw_args_text(source, node)
    if node.name.startswith("/"):
        node.arg_mode = "none"
        if raw_text.strip():
            node.malformed = True
            diagnostics.append(Diagnostic(
                "closing_macro_args", "closing macro must not have arguments",
                node.raw_args_span, node.name,
            ))
        return
    if spec.arg_mode == "raw":
        if node.raw_args_span is not None and raw_text:
            node.expression_span = node.raw_args_span
            node.children.append(CstNode(
                node.raw_args_span, "protected_markup", name="raw_expression", role="expression",
            ))
        return
    if spec.arg_mode == "none":
        if raw_text.strip():
            node.malformed = True
            diagnostics.append(Diagnostic(
                "unexpected_macro_args", "macro does not accept arguments",
                node.raw_args_span, node.name,
            ))
        return
    if node.raw_args_span is None:
        return
    start = source.char_start(node.raw_args_span.start)
    end = source.char_start(node.raw_args_span.end)
    node.args, arg_error = _lex_args(source, start, end)
    if arg_error:
        node.malformed = True
        diagnostics.append(Diagnostic("malformed_args", arg_error, node.span, node.name))


def _next_macro(source: TextSource, start: int, limit: int) -> MacroScan | None:
    text = source.text
    pos = start
    while pos < limit:
        if text.startswith("<!--", pos) or text.startswith("/*", pos):
            end = _consume_comment(text, pos, limit)
            if end is None:
                return MacroScan(None, limit, Diagnostic("unterminated_comment", "unterminated comment", source.span(pos, limit)))
            pos = end
            continue
        if text.startswith("<<", pos):
            return _parse_macro(source, pos, limit)
        pos += 1
    return None


def _parse_header(source: TextSource, start: int, end: int) -> tuple[str, list[str], Span | None]:
    line = source.text[start:end].rstrip("\r\n")
    content_start = start + 2
    content = line[2:]
    tag_match = PASSAGE_TAG_RE.search(content)
    tags: list[str] = []
    if tag_match:
        tags = [tag for tag in tag_match.group(1).split() if tag]
        raw_name = content[:tag_match.start()]
    else:
        raw_name = content
    name = raw_name.strip(" \t")
    left_trim = len(raw_name) - len(raw_name.lstrip(" \t"))
    name_start = content_start + left_trim
    return name, tags, source.span(name_start, name_start + len(name)) if name else None


def _split_source(source: TextSource, source_path: str) -> SourceFile:
    starts: list[tuple[int, int]] = []
    cursor = 0
    for line in source.text.splitlines(keepends=True):
        logical_start = cursor + 1 if cursor == 0 and line.startswith("\ufeff") else cursor
        if source.text.startswith("::", logical_start):
            starts.append((logical_start, cursor + len(line)))
        cursor += len(line)
    if cursor < len(source.text):
        logical_start = 1 if cursor == 0 and source.text.startswith("\ufeff") else cursor
        if source.text.startswith("::", logical_start):
            starts.append((logical_start, len(source.text)))
    passages: list[Passage] = []
    for index, (header_start, header_end) in enumerate(starts):
        next_start = starts[index + 1][0] if index + 1 < len(starts) else len(source.text)
        name, tags, name_span = _parse_header(source, header_start, header_end)
        passages.append(Passage(
            source_path=source_path,
            name=name,
            tags=tags,
            header_span=source.span(header_start, header_end),
            name_span=name_span,
            body_span=source.span(header_end, next_start),
            source_span=source.span(header_start, next_start),
        ))
    prefix_end = source.byte_start(starts[0][0]) if starts else len(source.data)
    return SourceFile(source_path, source.data, passages, Span(0, prefix_end))


def split_twee(data: bytes, source_path: str = "<memory>") -> SourceFile:
    return _split_source(TextSource(data), source_path)


def _opaque_reason(passage: Passage) -> str | None:
    if passage.name in SPECIAL_PASSAGES:
        return "special_passage"
    if "script" in passage.tags:
        return "script_tag"
    if "stylesheet" in passage.tags:
        return "stylesheet_tag"
    return None


def _in_any(span: Span, ranges: Iterable[Span]) -> bool:
    return any(item.contains(span) or span.contains(item) for item in ranges)


def _classify_args(node: CstNode, value_kinds: dict[str, Any], diagnostics: list[Diagnostic]) -> None:
    lookup = value_kinds.get(node.name.lower().lstrip("/"), {})
    schema_args = lookup.get("args", {}) if isinstance(lookup, dict) else {}
    for arg in node.args:
        schema = schema_args.get(str(arg.index), {}) if isinstance(schema_args, dict) else {}
        arg.value_kind = schema.get("kind")
        arg.evidence = list(schema.get("evidence", []))
        arg.confidence = schema.get("confidence")
        arg.note = schema.get("note")
        if node.name.startswith("/"):
            arg.disposition = "protect"
        elif not schema:
            arg.disposition = "unclassified"
            diagnostics.append(Diagnostic(
                "unclassified_argument", "macro argument kind is not classified", arg.raw_span,
                node.name, arg.index))
        # Expose only when the classification is trustworthy: rule-based
        # (call/definition) evidence is trusted, LLM evidence only at
        # confidence=high (value-kind-policy.md).
        elif arg.lexeme_kind == "string" and arg.value_kind == "prose_text" and (
            "llm" not in arg.evidence or arg.confidence == "high"
        ):
            arg.disposition = "expose"
        else:
            arg.disposition = "protect"


def _consume_html_tag(text: str, start: int, limit: int) -> int | None:
    if start >= limit or text[start] != "<" or start + 1 >= limit or text[start + 1] not in "/!?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz":
        return None
    quote: str | None = None
    pos = start + 1
    while pos < limit:
        char = text[pos]
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == ">":
            return pos + 1
        elif char == "\n" and text[start + 1] not in "!?":
            return None
        pos += 1
    return None


def _consume_variable(text: str, start: int, limit: int) -> int:
    pos = start + 1
    if pos >= limit or not (text[pos].isalpha() or text[pos] == "_"):
        return start + 1
    while pos < limit and (text[pos].isalnum() or text[pos] in "_-"):
        pos += 1
    while pos < limit:
        if text[pos] == ".":
            dot = pos
            pos += 1
            if pos >= limit or not (text[pos].isalpha() or text[pos] in "_$"):
                return dot
            while pos < limit and (text[pos].isalnum() or text[pos] in "_-$"):
                pos += 1
        elif text[pos] == "[":
            depth = 1
            pos += 1
            quote: str | None = None
            while pos < limit and depth:
                char = text[pos]
                if quote:
                    if char == "\\":
                        pos += 2
                        continue
                    if char == quote:
                        quote = None
                elif char in "\"'`":
                    quote = char
                elif char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                pos += 1
        else:
            break
    return pos


SQUARE_MARKUP_START_RE = _SQUARE_OPENER_RE


def _is_exposable_link_label(text: str) -> bool:
    """A string-argument display label is translatable when it has no dynamic markers.

    Mirrors ``square_markup.exposed_label`` for string-form link/button arguments:
    ``$``, ``_``, backtick, ``${`` and ``+`` concatenation mark the label as
    dynamic, so the whole argument stays protected.
    """
    return text != "" and not any(marker in text for marker in DYNAMIC_LABEL_MARKERS)


def _attach_argument_nodes(source: TextSource, node: CstNode, spec: MacroSpec) -> None:
    for arg in node.args:
        if arg.disposition == "expose" and arg.content_span is not None:
            node.children.append(CstNode(
                arg.content_span, "prose_text", name="macro_arg", role="argument",
            ))
            continue
        if arg.index in spec.square_label_args and arg.lexeme_kind == "string" and arg.content_span is not None:
            content = source.text[source.char_start(arg.content_span.start):source.char_start(arg.content_span.end)]
            if _is_exposable_link_label(content):
                node.children.append(CstNode(
                    arg.content_span, "prose_text", name="link_label", role="label",
                ))
                continue
        if arg.lexeme_kind != "square_bracket" or SQUARE_MARKUP_START_RE.match(arg.raw_text) is None:
            continue
        start = source.char_start(arg.raw_span.start)
        end = source.char_start(arg.raw_span.end)
        markup = parse_square_markup(source.text, start, end)
        markup_node = CstNode(
            arg.raw_span,
            "protected_markup",
            name="link" if (markup.is_link or markup.error is not None) else "image",
            role="markup",
        )
        if markup.is_link and markup.error is None and arg.index in spec.square_label_args:
            label = exposed_label(markup)
            if label is not None:
                markup_node.children.append(CstNode(
                    source.span(label.start, label.end), "prose_text", name="link_label", role="label",
                ))
        node.children.append(markup_node)


def _collect_tree_exposure(passage: Passage) -> None:
    if passage.root is None:
        return

    def visit(node: CstNode) -> None:
        if node.node_type == "prose_text":
            passage.exposed_candidates.append((node.span, node.name or "prose_text"))
        for child in node.children:
            visit(child)

    visit(passage.root)


def _standalone_markup_nodes(
    source: TextSource,
    start: int,
    end: int,
    ignored: list[Span],
) -> list[CstNode]:
    """Find standalone ``[[...]]`` / image markup outside macros and definitions.

    Each markup element becomes a ``protected_markup`` leaf node so the tree
    builder can place it under ``passage_root`` (or the active container/branch)
    alongside text and macro nodes.  A static link display label is attached as
    a ``link_label`` ``prose_text`` child, mirroring
    ``_attach_argument_nodes``.
    """
    text = source.text
    pos = start
    ignored = sorted(ignored)
    ignored_index = 0
    nodes: list[CstNode] = []
    while pos < end:
        byte_pos = source.byte_start(pos)
        while ignored_index < len(ignored) and ignored[ignored_index].end <= byte_pos:
            ignored_index += 1
        if ignored_index < len(ignored) and ignored[ignored_index].start <= byte_pos < ignored[ignored_index].end:
            pos = source.char_start(ignored[ignored_index].end)
            continue
        if not SQUARE_MARKUP_START_RE.match(text, pos):
            pos += 1
            continue
        markup_end = _consume_square(text, pos, end)
        if markup_end is None:
            pos += 1
            continue
        # A macro span that starts inside the markup would otherwise overlap
        # as a sibling.  Skip the markup entirely when it swallows one of the
        # ignored (macro/definition) spans.
        markup_byte_end = source.byte_start(markup_end)
        if any(item.start < markup_byte_end and item.end > byte_pos for item in ignored):
            pos = markup_end
            continue
        markup = parse_square_markup(text, pos, markup_end)
        markup_node = CstNode(
            source.span(pos, markup_end),
            "protected_markup",
            name="link" if (markup.is_link or markup.error is not None) else "image",
            role="markup",
        )
        if markup.is_link and markup.error is None:
            label = exposed_label(markup)
            if label is not None:
                markup_node.children.append(CstNode(
                    source.span(label.start, label.end), "prose_text", name="link_label", role="label",
                ))
        nodes.append(markup_node)
        pos = markup_end
    return nodes


def _collect_markup(source: TextSource, passage: Passage, start: int, end: int, ignored: list[Span]) -> None:
    text = source.text
    pos = start
    ignored = sorted(ignored)
    ignored_index = 0
    while pos < end:
        byte_pos = source.byte_start(pos)
        while ignored_index < len(ignored) and ignored[ignored_index].end <= byte_pos:
            ignored_index += 1
        if ignored_index < len(ignored) and ignored[ignored_index].start <= byte_pos < ignored[ignored_index].end:
            pos = source.char_start(ignored[ignored_index].end)
            continue
        if text.startswith("<!--", pos) or text.startswith("/*", pos):
            marker_end = _consume_comment(text, pos, end)
            if marker_end is not None:
                passage.protected_spans.append(source.span(pos, marker_end))
                pos = marker_end
                continue
        if text.startswith("<<", pos):
            scan = _parse_macro(source, pos, end)
            pos = max(scan.end, pos + 1)
            continue
        if SQUARE_MARKUP_START_RE.match(text, pos):
            link_end = _consume_square(text, pos, end)
            if link_end is not None:
                pos = link_end
                continue
        if text[pos] == "<":
            html_end = _consume_html_tag(text, pos, end)
            if html_end is not None:
                passage.protected_spans.append(source.span(pos, html_end))
                pos = html_end
                continue
        if text[pos] in "$_" and pos + 1 < end and (text[pos + 1].isalpha() or text[pos + 1] == "_"):
            variable_end = _consume_variable(text, pos, end)
            passage.protected_spans.append(source.span(pos, variable_end))
            pos = variable_end
            continue
        if text[pos] == "`":
            expression_end = _consume_quoted(text, pos, "`", end, allow_newline=True)
            if expression_end is not None:
                passage.protected_spans.append(source.span(pos, expression_end))
                pos = expression_end
                continue
        pos += 1


def _merge_spans(spans: Iterable[Span]) -> list[Span]:
    result: list[Span] = []
    for span in sorted(spans):
        if not result or span.start > result[-1].end:
            result.append(span)
        else:
            result[-1] = Span(result[-1].start, max(result[-1].end, span.end))
    return result


def _assign_tree_metadata(passage: Passage) -> None:
    if passage.root is None:
        return
    passage.node_index.clear()
    ordinal = 0

    def visit(node: CstNode, parent: CstNode | None, depth: int, sibling: int) -> None:
        nonlocal ordinal
        node.parent_id = parent.node_id if parent else None
        node.depth = depth
        node.sibling_order = sibling
        node.node_id = (
            f"{passage.source_path}:{passage.source_span.start}:"
            f"{node.node_type}:{node.span.start}:{node.span.end}:{ordinal}"
        )
        ordinal += 1
        passage.node_index[node.node_id] = node
        for index, child in enumerate(node.children):
            visit(child, node, depth + 1, index)

    visit(passage.root, None, 0, 0)


def _build_tree(
    passage: Passage,
    macros: list[CstNode],
    source: TextSource,
    registry: MacroRegistry,
    markup_nodes: list[CstNode] | None = None,
) -> None:
    root = CstNode(passage.body_span, "passage_root", role="root")
    passage.root = root
    markup_nodes = markup_nodes or []
    all_events = sorted([*macros, *markup_nodes], key=lambda node: (node.span.start, node.span.end))
    stack: list[CstNode] = [root]
    last = passage.body_span.start

    def add_text(start: int, end: int, parent: CstNode) -> None:
        if start < end:
            parent.children.append(CstNode(Span(start, end), "text", role="text"))

    for node in all_events:
        add_text(last, node.span.start, stack[-1])
        if node.node_type == "protected_markup":
            stack[-1].children.append(node)
            passage.protected_spans.append(node.span)
            last = node.span.end
            continue
        if node.name.startswith("/"):
            target = node.name[1:].lower()
            match_index = next(
                (i for i in range(len(stack) - 1, 0, -1)
                 if stack[i].node_type == "macro_container" and stack[i].name.lower() == target),
                None,
            )
            if match_index is None:
                passage.diagnostics.append(Diagnostic("mismatched_close", "closing macro has no matching container", node.span, node.name))
            else:
                if stack[-1].node_type == "macro_branch":
                    stack[-1].span = Span(stack[-1].span.start, node.span.start)
                opening = stack[match_index]
                opening.closing_span = node.span
                opening.span = Span(opening.span.start, node.span.end)
                opening.body_span = Span(opening.raw_args_span.end + 2 if opening.raw_args_span else opening.span.start, node.span.start)
                del stack[match_index:]
            last = node.span.end
            continue
        lower = node.name.lower()
        active_container = (
            stack[-2] if stack[-1].node_type == "macro_branch" and len(stack) > 1
            else stack[-1] if stack[-1].node_type == "macro_container"
            else None
        )
        active_spec = registry.get(active_container.name) if active_container is not None else None
        if active_spec is not None and lower in active_spec.tags:
            if stack[-1].node_type == "macro_branch":
                stack[-1].span = Span(stack[-1].span.start, node.span.start)
                stack.pop()
            node.node_type = "macro_branch"
            node.role = "branch"
            stack[-1].children.append(node)
            stack.append(node)
        else:
            if registry.is_branch_name(lower):
                passage.diagnostics.append(Diagnostic(
                    "unexpected_branch", "branch macro is not valid for the active container",
                    node.span, node.name,
                ))
            spec = registry.get(lower)
            if spec.body_kind != "container":
                stack[-1].children.append(node)
                last = node.span.end
                continue
            node.node_type = "macro_container"
            stack[-1].children.append(node)
            stack.append(node)
            if spec.implicit_branch:
                branch = CstNode(
                    node.span,
                    "macro_branch",
                    name=node.name,
                    role="branch",
                    raw_args_span=node.raw_args_span,
                    args=node.args,
                    arg_mode=node.arg_mode,
                    expression_span=node.expression_span,
                    grammar_source=node.grammar_source,
                    children=node.children,
                )
                node.children = []
                node.children.append(branch)
                stack.append(branch)
        last = node.span.end
    add_text(last, passage.body_span.end, stack[-1])
    for open_node in stack[1:]:
        if open_node.node_type == "macro_branch":
            open_node.span = Span(open_node.span.start, passage.body_span.end)
            continue
        open_node.malformed = True
        open_node.body_span = Span(
            open_node.raw_args_span.end + 2 if open_node.raw_args_span else open_node.span.end,
            passage.body_span.end,
        )
        open_node.span = Span(open_node.span.start, passage.body_span.end)
        passage.protected_spans.append(Span(open_node.span.start, passage.body_span.end))
        passage.diagnostics.append(Diagnostic("unclosed_container", "container has no closing tag", open_node.span, open_node.name))
    _assign_tree_metadata(passage)


def parse_passage(
    passage: Passage,
    data: bytes,
    value_kind_path: str | Path | dict[str, Any] | None = None,
    *,
    grammar_path: str | Path | dict[str, Any] | None = None,
    _source: TextSource | None = None,
    _registry: MacroRegistry | None = None,
) -> Passage:
    source = _source or TextSource(data)
    registry = _registry or load_macro_registry(grammar_path)
    start, end = source.char_start(passage.body_span.start), source.char_start(passage.body_span.end)
    opaque_reason = _opaque_reason(passage)
    if opaque_reason is not None:
        passage.protected_spans.append(passage.body_span)
        passage.root = CstNode(passage.body_span, "passage_root", role="root")
        passage.root.children.append(CstNode(passage.body_span, "passage_opaque", name=opaque_reason, role="opaque"))
        _assign_tree_metadata(passage)
        return passage

    value_kinds = _load_value_kinds(value_kind_path)
    macros: list[CstNode] = []
    pos = start
    while pos < end:
        scan = _next_macro(source, pos, end)
        if scan is None:
            break
        if scan.diagnostic:
            passage.diagnostics.append(scan.diagnostic)
            if scan.diagnostic.span is not None:
                passage.protected_spans.append(scan.diagnostic.span)
        if scan.node is None:
            pos = max(scan.end, pos + 1)
            continue
        node = scan.node
        spec = registry.get(node.name)
        _decode_macro_args(source, node, spec, passage.diagnostics)
        _classify_args(node, value_kinds, passage.diagnostics)
        _attach_argument_nodes(source, node, spec)
        macros.append(node)
        passage.nodes.append(node)
        passage.protected_spans.append(node.span)
        pos = scan.end
    markup_nodes = _standalone_markup_nodes(source, start, end, [*(node.span for node in macros)])
    _collect_markup(source, passage, start, end, [*(node.span for node in macros), *(node.span for node in markup_nodes)])
    _build_tree(passage, macros, source, registry, markup_nodes)
    _collect_tree_exposure(passage)
    passage.protected_spans = _merge_spans(passage.protected_spans)
    passage.nodes.extend(markup_nodes)
    passage.nodes.sort(key=lambda node: (node.span.start, node.span.end))
    return passage


def parse_file(
    data: bytes,
    source_path: str = "<memory>",
    value_kind_path: str | Path | dict[str, Any] | None = None,
    *,
    grammar_path: str | Path | dict[str, Any] | None = None,
) -> SourceFile:
    source = TextSource(data)
    registry = load_macro_registry(grammar_path)
    result = _split_source(source, source_path)
    for passage in result.passages:
        parse_passage(
            passage,
            data,
            value_kind_path,
            grammar_path=grammar_path,
            _source=source,
            _registry=registry,
        )
    return result
