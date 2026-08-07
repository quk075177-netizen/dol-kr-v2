from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .model import ArgNode, Diagnostic, MacroNode, Passage, SourceFile, Span


MACRO_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")
PASSAGE_TAG_RE = re.compile(r"[ \t]+\[([^\]]*)\][ \t]*$")
ASCII_SPACE = " \t\r\n\f\v"


class TextSource:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.text = data.decode("utf-8")
        self.char_to_byte = [0]
        for char in self.text:
            self.char_to_byte.append(self.char_to_byte[-1] + len(char.encode("utf-8")))

    def span(self, start: int, end: int) -> Span:
        return Span(self.char_to_byte[start], self.char_to_byte[end])

    def byte_start(self, char_pos: int) -> int:
        return self.char_to_byte[char_pos]


@dataclass
class MacroScan:
    node: MacroNode | None
    end: int
    diagnostic: Diagnostic | None = None


def _load_value_kinds(path: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if path is None:
        return {}
    if isinstance(path, dict):
        return path
    raw = Path(path).read_text(encoding="utf-8")
    payload = json.loads(raw)
    return payload.get("macros", {})


def _is_space(char: str) -> bool:
    return char in ASCII_SPACE


def _consume_quoted(text: str, start: int, quote: str) -> int | None:
    pos = start + 1
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            if pos + 1 >= len(text) or text[pos + 1] == "\n":
                return None
            pos += 2
            continue
        if char == quote:
            return pos + 1
        if char == "\n":
            return None
        pos += 1
    return None


def _consume_comment(text: str, start: int) -> int | None:
    if text.startswith("<!--", start):
        end = text.find("-->", start + 4)
        return None if end < 0 else end + 3
    if text.startswith("/*", start):
        end = text.find("*/", start + 2)
        return None if end < 0 else end + 2
    return None


def _consume_square(text: str, start: int) -> int | None:
    """Consume SugarCube [[...]]/[img[...]] markup with nested bracket depth."""
    pos = start
    if pos >= len(text) or text[pos] != "[":
        return None
    pos += 1
    if pos < len(text) and text[pos] in "<>IiMmGg":
        while pos < len(text) and text[pos] in "<>IiMmGg":
            pos += 1
    if pos >= len(text) or text[pos] != "[":
        return None
    pos += 1
    depth = 2
    while pos < len(text):
        char = text[pos]
        if char == "\\":
            if pos + 1 >= len(text) or text[pos + 1] == "\n":
                return None
            pos += 2
            continue
        if char == "\n":
            return None
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 1 and pos + 1 < len(text) and text[pos + 1] == "]":
                return pos + 2
            if depth < 1:
                return None
        pos += 1
    return None


def _consume_macro_body(text: str, start: int) -> tuple[int | None, str | None]:
    """Return the index after >>, following parserlib's lookahead alternatives."""
    pos = start
    while pos < len(text):
        if text.startswith(">>", pos):
            return pos + 2, None
        if text.startswith("/*", pos):
            end = _consume_comment(text, pos)
            if end is not None:
                pos = end
                continue
        if text.startswith("//", pos):
            newline = text.find("\n", pos + 2)
            pos = len(text) if newline < 0 else newline + 1
            continue
        if text[pos] in "`\"'":
            end = _consume_quoted(text, pos, text[pos])
            if end is None:
                return None, "unterminated quoted macro argument"
            pos = end
            continue
        if text[pos] == "/":
            end = _consume_quoted(text, pos, "/")
            if end is not None:
                pos = end
                continue
        if text[pos] == "[":
            end = _consume_square(text, pos)
            if end is not None:
                pos = end
                continue
        pos += 1
    return None, "unterminated macro (missing >>)"


def _lex_args(source: TextSource, start: int, end: int) -> tuple[list[tuple[int, int, int | None, str]], str | None]:
    text = source.text
    pos = start
    result: list[tuple[int, int, int | None, str]] = []
    while pos < end:
        while pos < end and _is_space(text[pos]):
            pos += 1
        if pos >= end:
            break
        token_start = pos
        content_start: int | None = None
        if text[pos] in "`\"'":
            quote = text[pos]
            token_end = _consume_quoted(text, pos, quote)
            if token_end is None or token_end > end:
                return result, "unterminated quoted macro argument"
            content_start = pos + 1
            content_end = token_end - 1
            kind = "expression" if quote == "`" else "string"
        elif text[pos] == "[":
            token_end = _consume_square(text, pos)
            if token_end is None or token_end > end:
                return result, "malformed or unterminated square-bracket argument"
            content_end = token_end
            kind = "square_bracket"
        else:
            token_end = pos
            while token_end < end and not _is_space(text[token_end]):
                token_end += 1
            content_end = token_end
            kind = "bareword"
        result.append((token_start, token_end, content_start if content_start is not None else token_start, kind))
        pos = token_end
    return result, None


def _parse_macro(source: TextSource, start: int, value_kinds: dict[str, Any]) -> MacroScan:
    text = source.text
    if not text.startswith("<<", start):
        return MacroScan(None, start + 1)
    pos = start + 2
    closing = False
    if pos < len(text) and text[pos] == "/":
        closing = True
        pos += 1
    name_start = pos
    if pos < len(text) and text[pos] in "=-":
        pos += 1
    else:
        match = MACRO_NAME_RE.match(text, pos)
        if match is None:
            return MacroScan(None, start + 2, Diagnostic("invalid_macro_name", "invalid macro name", source.span(start, min(start + 2, len(text)))))
        pos = match.end()
    name_end = pos
    while pos < len(text) and _is_space(text[pos]):
        pos += 1
    args_start = pos
    body_end, error = _consume_macro_body(text, pos)
    if body_end is None:
        diagnostic = Diagnostic("malformed_macro", error or "malformed macro", source.span(start, len(text)))
        return MacroScan(None, len(text), diagnostic)
    close_start = body_end - 2
    arg_items, arg_error = _lex_args(source, args_start, close_start)
    malformed = arg_error is not None
    args: list[ArgNode] = []
    lookup = value_kinds.get(text[name_start:name_end].lower())
    schema_args = lookup.get("args", {}) if lookup else {}
    for index, (arg_start, arg_end, content_start, lexeme_kind) in enumerate(arg_items):
        schema = schema_args.get(str(index), {}) if isinstance(schema_args, dict) else {}
        content_span = None
        if lexeme_kind in {"string", "expression"}:
            content_span = source.span(content_start, arg_end - 1)
        arg = ArgNode(
            index=index,
            raw_span=source.span(arg_start, arg_end),
            content_span=content_span,
            lexeme_kind=lexeme_kind,
            raw_text=text[arg_start:arg_end],
            value_kind=schema.get("kind"),
            evidence=list(schema.get("evidence", [])),
            confidence=schema.get("confidence"),
            disposition="protect",
            note=schema.get("note"),
        )
        if (
            not closing
            and arg.lexeme_kind == "string"
            and arg.value_kind == "prose_text"
            and ("llm" not in arg.evidence or arg.confidence == "high")
        ):
            arg.disposition = "expose"
        elif lookup is None or not schema:
            arg.disposition = "unclassified"
        args.append(arg)
    node = MacroNode(
        span=source.span(start, body_end),
        name=("/" if closing else "") + text[name_start:name_end],
        name_span=source.span(name_start - (1 if closing else 0), name_end),
        raw_args_span=source.span(args_start, close_start),
        args=args,
        malformed=malformed,
    )
    diagnostic = Diagnostic("malformed_args", arg_error, node.span) if arg_error else None
    return MacroScan(node, body_end, diagnostic)


def _next_macro(source: TextSource, start: int, end: int) -> MacroScan | None:
    text = source.text
    pos = start
    while pos < end:
        if text.startswith("<!--", pos) or text.startswith("/*", pos):
            comment_end = _consume_comment(text, pos)
            if comment_end is None:
                return MacroScan(None, end, Diagnostic("unterminated_comment", "unterminated comment", source.span(pos, end)))
            pos = min(comment_end, end)
            continue
        if text.startswith("<<", pos):
            return _parse_macro(source, pos, {})
        pos += 1
    return None


def _find_widget_definitions(source: TextSource, body_start: int, body_end: int, value_kinds: dict[str, Any]) -> tuple[list[MacroNode], list[Diagnostic]]:
    definitions: list[MacroNode] = []
    diagnostics: list[Diagnostic] = []
    pos = body_start
    while pos < body_end:
        scan = _next_macro(source, pos, body_end)
        if scan is None:
            break
        if scan.diagnostic is not None:
            diagnostics.append(scan.diagnostic)
        if scan.node is None:
            pos = max(scan.end, pos + 1)
            continue
        node = scan.node
        if node.name.lower() != "widget":
            pos = scan.end
            continue
        depth = 1
        search = scan.end
        close_node: MacroNode | None = None
        while search < body_end:
            inner = _next_macro(source, search, body_end)
            if inner is None:
                break
            if inner.diagnostic is not None:
                diagnostics.append(inner.diagnostic)
            if inner.node is None:
                search = max(inner.end, search + 1)
                continue
            name = inner.node.name.lower()
            if name == "widget":
                depth += 1
            elif name == "/widget":
                depth -= 1
                if depth == 0:
                    close_node = inner.node
                    break
            search = inner.end
        if close_node is None:
            open_end = node.span.end
            node.role = "widget_definition"
            node.malformed = True
            node.span = Span(node.span.start, source.byte_start(body_end))
            node.body_span = Span(open_end, source.byte_start(body_end))
            diagnostics.append(Diagnostic("unclosed_widget", "widget definition has no closing tag", source.span(pos, body_end), "widget"))
            definitions.append(node)
            break
        node.role = "widget_definition"
        node.closing_span = close_node.span
        node.body_span = Span(node.span.end, close_node.span.start)
        node.span = Span(node.span.start, close_node.span.end)
        definitions.append(node)
        pos = _char_from_byte(source, close_node.span.end)
    return definitions, diagnostics


def _parse_header(source: TextSource, line_start: int, line_end: int) -> tuple[str, list[str], Span | None]:
    line = source.text[line_start:line_end].rstrip("\r\n")
    content_start = line_start + 2
    content = line[2:]
    tags: list[str] = []
    tag_match = PASSAGE_TAG_RE.search(content)
    if tag_match:
        tags = [tag for tag in tag_match.group(1).split() if tag]
        raw_name = content[:tag_match.start()]
        left_trim = len(raw_name) - len(raw_name.lstrip(" \t"))
        name_text = raw_name.strip(" \t")
        name_start = content_start + left_trim
        name_end = name_start + len(name_text)
    else:
        name_text = content.strip(" \t")
        left_trim = len(content) - len(content.lstrip(" \t"))
        name_start = content_start + left_trim
        name_end = name_start + len(name_text)
    return name_text, tags, source.span(name_start, name_end) if name_text else None


def split_twee(data: bytes, source_path: str = "<memory>") -> SourceFile:
    source = TextSource(data)
    starts: list[tuple[int, int]] = []
    cursor = 0
    for line in source.text.splitlines(keepends=True):
        if line.startswith("::"):
            starts.append((cursor, cursor + len(line)))
        cursor += len(line)
    if cursor < len(source.text) and source.text[cursor:].startswith("::"):
        starts.append((cursor, len(source.text)))
    passages: list[Passage] = []
    for index, (header_start, header_end) in enumerate(starts):
        next_start = starts[index + 1][0] if index + 1 < len(starts) else len(source.text)
        name, tags, name_span = _parse_header(source, header_start, header_end)
        body_start = header_end
        header_span = source.span(header_start, header_end)
        passage = Passage(
            source_path=source_path,
            name=name,
            tags=tags,
            header_span=header_span,
            name_span=name_span,
            body_span=source.span(body_start, next_start),
            source_span=source.span(header_start, next_start),
        )
        passages.append(passage)
    prefix_end = source.byte_start(starts[0][0]) if starts else len(data)
    return SourceFile(source_path, data, passages, Span(0, prefix_end))


def parse_passage(passage: Passage, data: bytes, value_kind_path: str | Path | dict[str, Any] | None = None) -> Passage:
    source = TextSource(data)
    body_start = _char_from_byte(source, passage.body_span.start)
    body_end = _char_from_byte(source, passage.body_span.end)
    value_kinds = _load_value_kinds(value_kind_path)
    definitions, definition_diagnostics = _find_widget_definitions(source, body_start, body_end, value_kinds)
    passage.nodes.extend(definitions)
    passage.diagnostics.extend(definition_diagnostics)
    definition_ranges = [node.span for node in definitions]
    passage.protected_spans.extend(definition_ranges)
    pos = body_start
    definition_index = 0
    while pos < body_end:
        byte_pos = source.byte_start(pos)
        while definition_index < len(definition_ranges) and definition_ranges[definition_index].end <= byte_pos:
            definition_index += 1
        if definition_index < len(definition_ranges) and definition_ranges[definition_index].start <= byte_pos < definition_ranges[definition_index].end:
            pos = _char_from_byte(source, definition_ranges[definition_index].end)
            continue
        scan = _next_macro(source, pos, body_end)
        if scan is None:
            break
        if scan.diagnostic is not None:
            passage.diagnostics.append(scan.diagnostic)
        if scan.node is not None:
            node = scan.node
            lookup = value_kinds.get(node.name.lower().lstrip("/"), {})
            schema_args = lookup.get("args", {}) if isinstance(lookup, dict) else {}
            # Re-run argument classification with the real schema.
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
                elif arg.lexeme_kind == "string" and arg.value_kind == "prose_text" and ("llm" not in arg.evidence or arg.confidence == "high"):
                    arg.disposition = "expose"
                else:
                    arg.disposition = "protect"
                if arg.disposition == "unclassified":
                    passage.diagnostics.append(Diagnostic("unclassified_argument", "macro argument kind is not classified", arg.raw_span, node.name, arg.index))
            passage.nodes.append(node)
            passage.protected_spans.append(node.span)
            for arg in node.args:
                if arg.disposition == "expose" and arg.content_span is not None:
                    passage.exposed_candidates.append((arg.content_span, "macro_arg"))
            pos = scan.end
        else:
            pos = max(scan.end, pos + 1)
    _collect_text_protection(source, passage, body_start, body_end, definition_ranges)
    passage.nodes.sort(key=lambda node: (node.span.start, node.span.end))
    passage.protected_spans = _merge_spans(passage.protected_spans)
    return passage


def _char_from_byte(source: TextSource, byte_pos: int) -> int:
    import bisect

    index = bisect.bisect_left(source.char_to_byte, byte_pos)
    if index >= len(source.char_to_byte) or source.char_to_byte[index] != byte_pos:
        raise ValueError(f"byte offset {byte_pos} is not a UTF-8 character boundary")
    return index


def _merge_spans(spans: Iterable[Span]) -> list[Span]:
    ordered = sorted(spans)
    merged: list[Span] = []
    for span in ordered:
        if not merged or span.start > merged[-1].end:
            merged.append(span)
        else:
            merged[-1] = Span(merged[-1].start, max(merged[-1].end, span.end))
    return merged


def _consume_html_tag(text: str, start: int) -> int | None:
    if start >= len(text) or text[start] != "<" or start + 1 >= len(text) or text[start + 1] not in "/!?A-Za-z":
        return None
    quote: str | None = None
    pos = start + 1
    while pos < len(text):
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


def _consume_variable(text: str, start: int) -> int:
    pos = start + 1
    if pos >= len(text) or not (text[pos].isalpha() or text[pos] == "_"):
        return start + 1
    while pos < len(text) and (text[pos].isalnum() or text[pos] in "_-"):
        pos += 1
    while pos < len(text):
        if text[pos] == ".":
            dot = pos
            pos += 1
            if pos >= len(text) or not (text[pos].isalpha() or text[pos] in "_$"):
                return dot
            while pos < len(text) and (text[pos].isalnum() or text[pos] in "_-$"):
                pos += 1
        elif text[pos] == "[":
            depth = 1
            pos += 1
            quote: str | None = None
            while pos < len(text) and depth:
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


def _find_link(text: str, start: int) -> int | None:
    return _consume_square(text, start) if text.startswith("[[", start) else None


def _link_label_span(source: TextSource, start: int, end: int) -> Span | None:
    text = source.text
    inner_start = start + 2
    inner_end = end - 2
    inner = text[inner_start:inner_end]
    for delimiter in ("|", "->", "<-"):
        index = inner.find(delimiter)
        if index < 0:
            continue
        if delimiter == "<-":
            label_start, label_end = inner_start, inner_start + index
        else:
            label_start, label_end = inner_start, inner_start + index
        label = text[label_start:label_end]
        if not label or any(marker in label for marker in ("$", "_", "`", "${")):
            return None
        return source.span(label_start, label_end)
    return None


def _collect_text_protection(source: TextSource, passage: Passage, body_start: int, body_end: int, definitions: list[Span]) -> None:
    text = source.text
    pos = body_start
    definition_index = 0
    while pos < body_end:
        byte_pos = source.byte_start(pos)
        while definition_index < len(definitions) and definitions[definition_index].end <= byte_pos:
            definition_index += 1
        if definition_index < len(definitions) and definitions[definition_index].start <= byte_pos < definitions[definition_index].end:
            pos = _char_from_byte(source, definitions[definition_index].end)
            continue
        comment_end = _consume_comment(text, pos) if text.startswith("<!--", pos) or text.startswith("/*", pos) else None
        if comment_end is not None:
            passage.protected_spans.append(source.span(pos, min(comment_end, body_end)))
            pos = comment_end
            continue
        if text.startswith("<<", pos):
            scan = _parse_macro(source, pos, {})
            if scan.node is not None:
                pos = scan.end
                continue
            pos = max(scan.end, pos + 1)
            continue
        html_end = _consume_html_tag(text, pos) if text[pos] == "<" else None
        if html_end is not None:
            passage.protected_spans.append(source.span(pos, min(html_end, body_end)))
            pos = html_end
            continue
        link_end = _find_link(text, pos)
        if link_end is not None:
            link_span = source.span(pos, min(link_end, body_end))
            passage.protected_spans.append(link_span)
            label_span = _link_label_span(source, pos, link_end)
            if label_span is not None:
                passage.exposed_candidates.append((label_span, "link_label"))
            pos = link_end
            continue
        if text[pos] in "$_" and pos + 1 < body_end and (text[pos + 1].isalpha() or text[pos + 1] == "_"):
            variable_end = _consume_variable(text, pos)
            passage.protected_spans.append(source.span(pos, variable_end))
            pos = variable_end
            continue
        if text[pos] == "`":
            expression_end = _consume_quoted(text, pos, "`")
            if expression_end is not None:
                passage.protected_spans.append(source.span(pos, expression_end))
                pos = expression_end
                continue
        pos += 1


def parse_file(data: bytes, source_path: str = "<memory>", value_kind_path: str | Path | dict[str, Any] | None = None) -> SourceFile:
    result = split_twee(data, source_path)
    value_kinds = _load_value_kinds(value_kind_path)
    for passage in result.passages:
        parse_passage(passage, data, value_kinds)
    return result
