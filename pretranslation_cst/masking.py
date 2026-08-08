"""Convert a passage into exposed text plus reversible placeholders."""

from __future__ import annotations

import re

from .model import MaskArtifact, Passage, Placeholder, ProtectedSpan, Segment, Span
from .order_sensitivity import is_order_insensitive

# opening of a macro inside an exposed span: <<name or << /name
_MACRO_OPEN_RE = re.compile(r"<<\s*/?\s*[A-Za-z_][A-Za-z0-9_]*")


def _nested_macro_spans(text: str) -> list[tuple[int, int, str]]:
    """Nested ``<<...>>`` macro spans inside exposed text, as local
    (start, end, name) tuples.

    Macro arguments and link labels are exposed for translation, but a
    macro that appears *inside* them (``<<hypnosisText "<<He>> snaps
    <<his>> fingers, ...">>``) is still runtime-processed by the game and
    must survive translation as a protected span.  Without this the model
    may translate the macro content itself (observed: ``<<He>>`` became
    ``<그가>``) and no check catches it — the L1/L2/skeleton checks only
    guard placeholder tokens and protected spans.

    The closing ``>>`` search skips quoted strings, so a nested macro with
    quoted arguments (``<<npc "a>>b">>``) closes correctly.  Unclosed or
    malformed ``<<`` are left exposed."""
    spans: list[tuple[int, int, str]] = []
    pos = 0
    end = len(text)
    while pos < end:
        match = _MACRO_OPEN_RE.search(text, pos, end)
        if match is None:
            break
        raw_name = match.group(0)[2:].strip().lstrip("/").strip()
        if not raw_name:
            pos = match.end()
            continue
        cursor = match.end()
        quote: str | None = None
        close = -1
        while cursor + 1 < end:
            char = text[cursor]
            if quote is not None:
                if char == "\\":
                    cursor += 2
                    continue
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
            elif char == ">" and text[cursor + 1] == ">":
                close = cursor + 2
                break
            cursor += 1
        if close < 0:
            pos = match.end()
            continue
        spans.append((match.start(), close, raw_name))
        pos = close
    return spans


def _merge(spans: list[ProtectedSpan]) -> list[ProtectedSpan]:
    result: list[ProtectedSpan] = []
    for protected in sorted(spans, key=lambda item: (item.span.start, item.span.end)):
        if not result or protected.span.start > result[-1].span.end:
            result.append(protected)
        else:
            merged = result[-1]
            result[-1] = ProtectedSpan(
                Span(merged.span.start, max(merged.span.end, protected.span.end)),
                merged.kinds | protected.kinds,
            )
    return result


def _candidate_map(candidates: list[tuple[Span, str]]) -> list[tuple[Span, str]]:
    result: list[tuple[Span, str]] = []
    for span, kind in sorted(candidates, key=lambda item: (item[0].start, item[0].end)):
        if span.start == span.end:
            continue
        if result and span.start < result[-1][0].end:
            # A nested candidate is not independently translatable.
            if result[-1][0].contains(span):
                continue
            raise ValueError(f"overlapping exposed spans: {result[-1][0]} and {span}")
        result.append((span, kind))
    return result


def _subtract_candidates(
    protected: list[ProtectedSpan], candidates: list[Span]
) -> list[ProtectedSpan]:
    result: list[ProtectedSpan] = []
    for protected_span in sorted(protected, key=lambda item: item.span.start):
        span = protected_span.span
        cursor = span.start
        for candidate in candidates:
            if candidate.end <= cursor:
                continue
            if candidate.start >= span.end:
                break
            if candidate.start > cursor:
                result.append(ProtectedSpan(Span(cursor, min(candidate.start, span.end)), protected_span.kinds))
            cursor = max(cursor, min(candidate.end, span.end))
            if cursor >= span.end:
                break
        if cursor < span.end:
            result.append(ProtectedSpan(Span(cursor, span.end), protected_span.kinds))
    return _merge(result)


def _make_segments(data: bytes, body: Span, blocked: list[Span], candidates: list[tuple[Span, str]]) -> list[Segment]:
    open_ranges: list[Span] = []
    cursor = body.start
    for blocked_span in blocked:
        if cursor < blocked_span.start:
            open_ranges.append(Span(cursor, blocked_span.start))
        cursor = max(cursor, blocked_span.end)
    if cursor < body.end:
        open_ranges.append(Span(cursor, body.end))

    result: list[Segment] = []
    for open_span in open_ranges:
        position = open_span.start
        for candidate, kind in candidates:
            if candidate.end <= open_span.start:
                continue
            if candidate.start >= open_span.end:
                break
            if position < candidate.start:
                plain = Span(position, min(candidate.start, open_span.end))
                result.append(Segment(plain, data[plain.start:plain.end].decode("utf-8"), "plain_text"))
            exposed = Span(max(position, candidate.start), min(open_span.end, candidate.end))
            if exposed.start < exposed.end:
                result.append(Segment(exposed, data[exposed.start:exposed.end].decode("utf-8"), kind))
            position = max(position, candidate.end)
        if position < open_span.end:
            plain = Span(position, open_span.end)
            result.append(Segment(plain, data[plain.start:plain.end].decode("utf-8"), "plain_text"))
    return result


def mask_passage(data: bytes, passage: Passage, placeholder_prefix: str = "<0") -> MaskArtifact:
    body = passage.body_span
    candidates = _candidate_map([
        (span, kind) for span, kind in passage.exposed_candidates if body.contains(span)
    ])
    # nested macros inside exposed spans are still runtime macros — split
    # them out of the exposure and keep them protected
    split_candidates: list[tuple[Span, str]] = []
    nested_protected: list[ProtectedSpan] = []
    for span, kind in candidates:
        text = data[span.start:span.end].decode("utf-8", errors="replace")
        macros = _nested_macro_spans(text)
        if not macros:
            split_candidates.append((span, kind))
            continue
        cursor = span.start
        for start, end, name in macros:
            # local char offsets -> absolute byte offsets (multi-byte text)
            byte_start = span.start + len(text[:start].encode("utf-8"))
            byte_end = span.start + len(text[:end].encode("utf-8"))
            if cursor < byte_start:
                split_candidates.append((Span(cursor, byte_start), kind))
            nested_protected.append(ProtectedSpan(
                Span(byte_start, byte_end), frozenset({name})))
            cursor = byte_end
        if cursor < span.end:
            split_candidates.append((Span(cursor, span.end), kind))
    candidates = _candidate_map(split_candidates)
    blocked = _subtract_candidates(
        [protected for protected in passage.protected_spans if body.contains(protected.span)],
        [span for span, _ in candidates],
    )
    blocked = _merge(blocked + nested_protected)
    segments = _make_segments(data, body, [protected.span for protected in blocked], candidates)
    parts: list[str] = []
    placeholders: list[Placeholder] = []
    segment_index = 0
    block_index = 0
    body_text = data[body.start:body.end].decode("utf-8")
    prefix = placeholder_prefix

    while segment_index < len(segments) or block_index < len(blocked):
        segment = segments[segment_index] if segment_index < len(segments) else None
        blocked_span = blocked[block_index] if block_index < len(blocked) else None
        if blocked_span is not None and (segment is None or blocked_span.span.start < segment.source_span.start):
            token_number = len(placeholders)
            token = f"{prefix}{token_number:06d}__"
            while token in body_text or token in "".join(parts):
                prefix = prefix + "_"
            token = f"{prefix}{token_number:06d}>"
            original = data[blocked_span.span.start:blocked_span.span.end].decode("utf-8")
            placeholders.append(Placeholder(
                token,
                blocked_span.span,
                original,
                order_sensitive=not is_order_insensitive(blocked_span.kinds),
            ))
            parts.append(token)
            block_index += 1
        elif segment is not None:
            parts.append(segment.text)
            segment_index += 1
        else:
            break

    return MaskArtifact(
        source_path=passage.source_path,
        passage_name=passage.name,
        source_span=body,
        masked_text="".join(parts),
        segments=segments,
        placeholders=placeholders,
        diagnostics=list(passage.diagnostics),
    )


def restore_mask(artifact: MaskArtifact) -> bytes:
    result = artifact.masked_text
    for placeholder in artifact.placeholders:
        occurrences = result.count(placeholder.placeholder)
        if occurrences != 1:
            raise ValueError(f"placeholder {placeholder.placeholder!r} occurs {occurrences} times")
        result = result.replace(placeholder.placeholder, placeholder.original_text, 1)
    return result.encode("utf-8")
