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

from .model import ArgNode, CstNode, Diagnostic, Passage, SourceFile, Span


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
CONTAINER_NAMES = {
    "if", "unless", "for", "switch", "capture", "silently", "link", "button",
    "checkbox", "radiobutton", "listbox", "cycle", "dialog", "replace", "append",
    "prepend", "timed", "repeat", "back", "script", "style", "widget",
}
BRANCH_NAMES = {"else", "elseif", "case", "default"}


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


def _consume_square(text: str, start: int, limit: int | None = None) -> int | None:
    """Consume [[...]] or image square markup, including nested [[...]]."""
    limit = len(text) if limit is None else limit
    if not text.startswith("[", start):
        return None
    opener = start + 1
    while opener < limit and text[opener] in "<>IiMmGg":
        opener += 1
    if opener >= limit or text[opener] != "[":
        return None
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
        if text[pos] == "/":
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
    args, arg_error = _lex_args(source, args_start, close_start)
    node = CstNode(
        span=source.span(start, body_end),
        node_type="macro_call",
        name=("/" if closing else "") + text[name_start:name_end],
        role="call",
        name_span=source.span(name_start - (1 if closing else 0), name_end),
        raw_args_span=source.span(args_start, close_start),
        args=args,
        malformed=arg_error is not None,
    )
    diagnostic = Diagnostic("malformed_args", arg_error, node.span, node.name) if arg_error else None
    return MacroScan(node, body_end, diagnostic)


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


def _widget_definitions(source: TextSource, start: int, end: int) -> tuple[list[CstNode], list[Diagnostic]]:
    definitions: list[CstNode] = []
    diagnostics: list[Diagnostic] = []
    open_stack: list[CstNode] = []
    pos = start
    while pos < end:
        scan = _next_macro(source, pos, end)
        if scan is None:
            break
        if scan.diagnostic:
            diagnostics.append(scan.diagnostic)
        if scan.node is None:
            pos = max(scan.end, pos + 1)
            continue
        node = scan.node
        lower = node.name.lower()
        if lower == "widget":
            open_stack.append(node)
        elif lower == "/widget" and open_stack:
            opening = open_stack.pop()
            if not open_stack:
                opening.node_type = "widget_definition_opaque"
                opening.role = "widget_definition"
                opening.closing_span = node.span
                opening.body_span = Span(opening.span.end, node.span.start)
                opening.span = Span(opening.span.start, node.span.end)
                definitions.append(opening)
        pos = scan.end
    if open_stack:
        # Even a malformed nested definition stays buried in the outer opaque span.
        opening = open_stack[0]
        opening.node_type = "widget_definition_opaque"
        opening.role = "widget_definition"
        opening.malformed = True
        opening.body_span = Span(opening.span.end, source.byte_start(end))
        opening.span = Span(opening.span.start, source.byte_start(end))
        definitions.append(opening)
        diagnostics.append(Diagnostic("unclosed_widget", "widget definition has no closing tag", opening.span, "widget"))
    return sorted(definitions, key=lambda node: node.span), diagnostics


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


def _link_label(source: TextSource, start: int, end: int) -> Span | None:
    inner_start, inner_end = start + 2, end - 2
    inner = source.text[inner_start:inner_end]
    delimiter_index = -1
    delimiter = ""
    for candidate in ("|", "->", "<-"):
        index = inner.find(candidate)
        if index >= 0 and (delimiter_index < 0 or index < delimiter_index):
            delimiter_index, delimiter = index, candidate
    if delimiter_index < 0:
        return None
    label_start = inner_start
    label_end = inner_start + delimiter_index
    label = source.text[label_start:label_end]
    if not label or any(marker in label for marker in ("$", "_", "`", "${", "+")):
        return None
    return source.span(label_start, label_end)


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
        if text.startswith("[[", pos):
            link_end = _consume_square(text, pos, end)
            if link_end is not None:
                link_span = source.span(pos, link_end)
                passage.protected_spans.append(link_span)
                label = _link_label(source, pos, link_end)
                if label is not None:
                    passage.exposed_candidates.append((label, "link_label"))
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


def _build_tree(passage: Passage, macros: list[CstNode], definitions: list[CstNode], source: TextSource) -> None:
    root = CstNode(passage.body_span, "passage_root", role="root")
    passage.root = root
    all_events = sorted([*macros, *definitions], key=lambda node: (node.span.start, node.span.end))
    stack: list[CstNode] = [root]
    last = passage.body_span.start

    def add_text(start: int, end: int, parent: CstNode) -> None:
        if start < end:
            parent.children.append(CstNode(Span(start, end), "text", role="text"))

    for node in all_events:
        add_text(last, node.span.start, stack[-1])
        if node.node_type == "widget_definition_opaque":
            root.children.append(node)
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
        if lower in BRANCH_NAMES and len(stack) > 1:
            parent = stack[-2] if stack[-1].node_type == "macro_branch" else stack[-1]
            branch = CstNode(node.span, "macro_branch", name=node.name, role="branch", args=node.args)
            parent.children.append(branch)
            if stack[-1].node_type == "macro_branch":
                stack[-1].span = Span(stack[-1].span.start, node.span.start)
                stack.pop()
            stack.append(branch)
        elif lower in CONTAINER_NAMES:
            node.node_type = "macro_container"
            stack[-1].children.append(node)
            stack.append(node)
            if lower in {"if", "unless"}:
                branch = CstNode(node.span, "macro_branch", name=node.name, role="branch", args=node.args)
                node.children.append(branch)
                stack.append(branch)
        else:
            stack[-1].children.append(node)
        last = node.span.end
    add_text(last, passage.body_span.end, stack[-1])
    for open_node in stack[1:]:
        if open_node.node_type == "macro_branch":
            open_node.span = Span(open_node.span.start, passage.body_span.end)
        open_node.malformed = True
        passage.protected_spans.append(Span(open_node.span.start, passage.body_span.end))
        passage.diagnostics.append(Diagnostic("unclosed_container", "container has no closing tag", open_node.span, open_node.name))
    _assign_tree_metadata(passage)


def parse_passage(
    passage: Passage,
    data: bytes,
    value_kind_path: str | Path | dict[str, Any] | None = None,
    *,
    _source: TextSource | None = None,
) -> Passage:
    source = _source or TextSource(data)
    start, end = source.char_start(passage.body_span.start), source.char_start(passage.body_span.end)
    opaque_reason = _opaque_reason(passage)
    if opaque_reason is not None:
        passage.protected_spans.append(passage.body_span)
        passage.root = CstNode(passage.body_span, "passage_root", role="root")
        passage.root.children.append(CstNode(passage.body_span, "passage_opaque", name=opaque_reason, role="opaque"))
        _assign_tree_metadata(passage)
        return passage

    value_kinds = _load_value_kinds(value_kind_path)
    definitions, definition_diagnostics = _widget_definitions(source, start, end)
    passage.diagnostics.extend(definition_diagnostics)
    passage.protected_spans.extend(node.span for node in definitions)
    definition_spans = [node.span for node in definitions]
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
        if _in_any(scan.node.span, definition_spans):
            pos = scan.end
            continue
        node = scan.node
        _classify_args(node, value_kinds, passage.diagnostics)
        macros.append(node)
        passage.nodes.append(node)
        passage.protected_spans.append(node.span)
        for arg in node.args:
            if arg.disposition == "expose" and arg.content_span is not None:
                passage.exposed_candidates.append((arg.content_span, "macro_arg"))
        pos = scan.end
    passage.nodes.extend(definitions)
    _collect_markup(source, passage, start, end, [*definition_spans, *(node.span for node in macros)])
    _build_tree(passage, macros, definitions, source)
    passage.protected_spans = _merge_spans(passage.protected_spans)
    passage.nodes.sort(key=lambda node: (node.span.start, node.span.end))
    return passage


def parse_file(data: bytes, source_path: str = "<memory>", value_kind_path: str | Path | dict[str, Any] | None = None) -> SourceFile:
    source = TextSource(data)
    result = _split_source(source, source_path)
    for passage in result.passages:
        parse_passage(passage, data, value_kind_path, _source=source)
    return result
