from __future__ import annotations

from dataclasses import dataclass

from .model import Diagnostic, MaskArtifact, Passage, Placeholder, Segment, Span


def _contains(outer: Span, inner: Span) -> bool:
    return outer.start <= inner.start and inner.end <= outer.end


def _candidate_map(candidates: list[tuple[Span, str]]) -> list[tuple[Span, str]]:
    result: list[tuple[Span, str]] = []
    for span, kind in sorted(candidates, key=lambda item: (item[0].start, item[0].end)):
        if span.start == span.end:
            continue
        if result and span.start < result[-1][0].end:
            # A nested candidate is not independently translatable.
            if _contains(result[-1][0], span):
                continue
            raise ValueError(f"overlapping exposed spans: {result[-1][0]} and {span}")
        result.append((span, kind))
    return result


def mask_passage(data: bytes, passage: Passage, placeholder_prefix: str = "__DOLKR_P") -> MaskArtifact:
    body = passage.body_span
    candidates = _candidate_map([
        (span, kind) for span, kind in passage.exposed_candidates
        if _contains(body, span)
    ])
    protected = [span for span in passage.protected_spans if _contains(body, span)]
    blocked = _subtract_candidates(protected, [span for span, _ in candidates])
    segments = _make_segments(data, body, blocked, candidates)
    placeholder_values: list[Placeholder] = []
    parts: list[str] = []
    seg_index = 0
    block_index = 0
    while seg_index < len(segments) or block_index < len(blocked):
        next_segment = segments[seg_index] if seg_index < len(segments) else None
        next_block = blocked[block_index] if block_index < len(blocked) else None
        if next_block is not None and (next_segment is None or next_block.start < next_segment.source_span.start):
            token = f"{placeholder_prefix}{len(placeholder_values):06d}__"
            original = data[next_block.start:next_block.end].decode("utf-8")
            placeholder_values.append(Placeholder(token, next_block, original))
            parts.append(token)
            block_index += 1
        elif next_segment is not None:
            parts.append(next_segment.text)
            seg_index += 1
        else:
            break
    return MaskArtifact(
        source_path=passage.source_path,
        passage_name=passage.name,
        source_span=body,
        masked_text="".join(parts),
        segments=segments,
        placeholders=placeholder_values,
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


def _merge(spans: list[Span]) -> list[Span]:
    result: list[Span] = []
    for span in sorted(spans):
        if not result or span.start > result[-1].end:
            result.append(span)
        else:
            result[-1] = Span(result[-1].start, max(result[-1].end, span.end))
    return result


def _subtract_candidates(protected: list[Span], candidates: list[Span]) -> list[Span]:
    result: list[Span] = []
    candidate_index = 0
    for protected_span in protected:
        cursor = protected_span.start
        while candidate_index < len(candidates) and candidates[candidate_index].end <= cursor:
            candidate_index += 1
        scan_index = candidate_index
        while scan_index < len(candidates) and candidates[scan_index].start < protected_span.end:
            candidate = candidates[scan_index]
            if candidate.start > cursor:
                result.append(Span(cursor, min(candidate.start, protected_span.end)))
            cursor = max(cursor, min(candidate.end, protected_span.end))
            if cursor >= protected_span.end:
                break
            scan_index += 1
        if cursor < protected_span.end:
            result.append(Span(cursor, protected_span.end))
    return _merge(result)


def _make_segments(data: bytes, body: Span, blocked: list[Span], candidates: list[tuple[Span, str]]) -> list[Segment]:
    open_ranges: list[Span] = []
    cursor = body.start
    for span in blocked:
        if cursor < span.start:
            open_ranges.append(Span(cursor, span.start))
        cursor = max(cursor, span.end)
    if cursor < body.end:
        open_ranges.append(Span(cursor, body.end))

    result: list[Segment] = []
    candidate_index = 0
    for open_span in open_ranges:
        while candidate_index < len(candidates) and candidates[candidate_index][0].end <= open_span.start:
            candidate_index += 1
        position = open_span.start
        scan_index = candidate_index
        while scan_index < len(candidates) and candidates[scan_index][0].start < open_span.end:
            candidate, kind = candidates[scan_index]
            if position < candidate.start:
                plain = Span(position, candidate.start)
                result.append(Segment(plain, data[plain.start:plain.end].decode("utf-8"), "plain_text"))
            exposed = Span(max(position, candidate.start), min(open_span.end, candidate.end))
            if exposed.start < exposed.end:
                result.append(Segment(exposed, data[exposed.start:exposed.end].decode("utf-8"), kind))
            position = max(position, candidate.end)
            scan_index += 1
        if position < open_span.end:
            plain = Span(position, open_span.end)
            result.append(Segment(plain, data[plain.start:plain.end].decode("utf-8"), "plain_text"))
    return result
