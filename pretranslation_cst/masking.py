"""Convert a passage into exposed text plus reversible placeholders."""

from __future__ import annotations

from .model import MaskArtifact, Passage, Placeholder, Segment, Span


def _merge(spans: list[Span]) -> list[Span]:
    result: list[Span] = []
    for span in sorted(spans):
        if not result or span.start > result[-1].end:
            result.append(span)
        else:
            result[-1] = Span(result[-1].start, max(result[-1].end, span.end))
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


def _subtract_candidates(protected: list[Span], candidates: list[Span]) -> list[Span]:
    result: list[Span] = []
    for protected_span in sorted(protected):
        cursor = protected_span.start
        for candidate in candidates:
            if candidate.end <= cursor:
                continue
            if candidate.start >= protected_span.end:
                break
            if candidate.start > cursor:
                result.append(Span(cursor, min(candidate.start, protected_span.end)))
            cursor = max(cursor, min(candidate.end, protected_span.end))
            if cursor >= protected_span.end:
                break
        if cursor < protected_span.end:
            result.append(Span(cursor, protected_span.end))
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
    blocked = _subtract_candidates(
        [span for span in passage.protected_spans if body.contains(span)],
        [span for span, _ in candidates],
    )
    segments = _make_segments(data, body, blocked, candidates)
    parts: list[str] = []
    placeholders: list[Placeholder] = []
    segment_index = 0
    block_index = 0
    body_text = data[body.start:body.end].decode("utf-8")
    prefix = placeholder_prefix

    while segment_index < len(segments) or block_index < len(blocked):
        segment = segments[segment_index] if segment_index < len(segments) else None
        blocked_span = blocked[block_index] if block_index < len(blocked) else None
        if blocked_span is not None and (segment is None or blocked_span.start < segment.source_span.start):
            token_number = len(placeholders)
            token = f"{prefix}{token_number:06d}__"
            while token in body_text or token in "".join(parts):
                prefix = prefix + "_"
            token = f"{prefix}{token_number:06d}>"
            original = data[blocked_span.start:blocked_span.end].decode("utf-8")
            placeholders.append(Placeholder(token, blocked_span, original))
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
