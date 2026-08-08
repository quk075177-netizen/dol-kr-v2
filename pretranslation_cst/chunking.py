"""Chunk a masked passage into translation units.

A translate unit is a slice of the passage body that stays within the
CST tree structure so neighbouring prose keeps its context:

* passages at or below ``threshold`` chars become a single unit,
* larger passages are split along container/branch boundaries,
* placeholders never straddle a unit boundary (units are cut on original
  byte spans and their masked text is rebuilt from the placeholder table),
* each unit carries its CST ancestor path plus preceding/following
  context from neighbouring units.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import MaskArtifact, Passage, Placeholder, Segment, Span

DEFAULT_THRESHOLD = 1000
DEFAULT_MAX_CHARS = 2000
DEFAULT_MIN_CHARS = 200


@dataclass
class TranslateUnit:
    """One chunk of a masked passage ready for a translation API."""

    unit_id: str
    source_path: str
    passage_name: str
    unit_index: int
    unit_count: int
    masked_text: str
    segments: list[Segment] = field(default_factory=list)
    placeholders: list[Placeholder] = field(default_factory=list)
    ancestors: list[dict] = field(default_factory=list)
    preceding_context: str = ""
    following_context: str = ""
    char_count: int = 0

    def to_dict(self) -> dict:
        return {
            "unit_id": self.unit_id,
            "source_path": self.source_path,
            "passage_name": self.passage_name,
            "unit_index": self.unit_index,
            "unit_count": self.unit_count,
            "masked_text": self.masked_text,
            "segments": [segment.to_dict() for segment in self.segments],
            "placeholders": [item.to_dict() for item in self.placeholders],
            "ancestors": self.ancestors,
            "preceding_context": self.preceding_context,
            "following_context": self.following_context,
            "char_count": self.char_count,
        }


def _ancestor_path(passage: Passage, node_id: str) -> list[dict]:
    """Ancestor container/branch path for a node, nearest first."""
    path: list[dict] = []
    try:
        for ancestor in passage.get_ancestors(node_id):
            if ancestor.node_type in ("macro_container", "macro_branch"):
                path.append({"node_type": ancestor.node_type, "name": ancestor.name})
    except LookupError:
        pass
    return path


def _body_leaf_nodes(passage: Passage) -> list:
    """Collect body-level text/prose/macro leaf nodes in document order."""
    if passage.root is None:
        return []
    return [node for node in passage.root.children]


def chunk_passage(
    passage: Passage,
    artifact: MaskArtifact,
    data: bytes,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    max_chars: int = DEFAULT_MAX_CHARS,
    min_chars: int = DEFAULT_MIN_CHARS,
) -> list[TranslateUnit]:
    """Split one masked passage into translation units.

    ``data`` is the original file bytes (used for byte offsets).  The split
    honours CST container boundaries so related prose stays together.

    ``threshold`` is the target size below which a unit is left whole;
    ``max_chars`` is a soft ceiling — units are split further only along
    container/branch boundaries, so a single leaf larger than ``max_chars``
    is kept as-is (no hard cap).
    """
    if passage.is_opaque or passage.root is None or not artifact.segments:
        # opaque passage (no exposed text) -> no units
        return []

    body = passage.body_span
    body_text_len = len(artifact.masked_text)
    if body_text_len <= threshold:
        spans = [(body, [])]
    else:
        groups = _collect_groups(passage)
        spans = []
        for group in groups:
            group_text_len = group["span"].end - group["span"].start
            if group_text_len <= threshold:
                spans.append((group["span"], group["ancestors"]))
            else:
                for unit in _split_group(passage, artifact, data, group, threshold, max_chars, min_chars):
                    spans.append((unit["span"], unit["ancestors"]))

    units = _build_units_from_spans(passage, artifact, data, spans)
    merged = _merge_small_units(units, min_chars)
    total = len(merged)
    for index, unit in enumerate(merged):
        unit.unit_index = index
        unit.unit_count = total
        unit.preceding_context = _neighbour_context(merged[index - 1]) if index > 0 else ""
        unit.following_context = _neighbour_context(merged[index + 1]) if index + 1 < total else ""
    return merged


def _build_units_from_spans(
    passage: Passage,
    artifact: MaskArtifact,
    data: bytes,
    spans: list[tuple[Span, list[dict]]],
) -> list[TranslateUnit]:
    """Assign each segment/placeholder to the unit whose span contains its
    start offset, then rebuild masked text per unit.

    The spans are expected to cover the passage body without gaps, so every
    item belongs to exactly one unit regardless of placeholder alignment.
    """
    spans = sorted(spans, key=lambda item: item[0].start)
    # Clamp each span start to the previous span's end so recursive splits
    # can never make sibling spans overlap (which would duplicate items).
    clamped: list[tuple[Span, list[dict]]] = []
    prev_end = 0
    for span, ancestors in spans:
        start = max(span.start, prev_end)
        end = max(start, span.end)
        # A placeholder may cover several adjacent macros merged by masking
        # (_merge merges touching protected spans).  If a split point falls
        # inside such a placeholder, grow the span end to that placeholder's
        # end so no placeholder straddles a unit boundary.
        for ph in artifact.placeholders:
            if start <= ph.source_span.start < end and ph.source_span.end > end:
                end = ph.source_span.end
        clamped.append((Span(start, end), ancestors))
        prev_end = end
    spans = clamped

    items: list[tuple[int, str, object]] = []
    for seg in artifact.segments:
        items.append((seg.source_span.start, "seg", seg))
    for ph in artifact.placeholders:
        items.append((ph.source_span.start, "ph", ph))
    items.sort(key=lambda item: (item[0], item[1]))

    units: list[TranslateUnit] = []
    for span, ancestors in spans:
        start, end = span.start, span.end
        members: list[tuple[str, object]] = []
        for offset, kind, item in items:
            if offset >= end:
                break
            if offset >= start:
                members.append((kind, item))
        masked_parts: list[str] = []
        segs: list[Segment] = []
        phs: list[Placeholder] = []
        for kind, item in members:
            if kind == "seg":
                segs.append(item)
                masked_parts.append(item.text)
            else:
                phs.append(item)
                masked_parts.append(item.placeholder)
        masked = "".join(masked_parts)
        unit = TranslateUnit(
            unit_id=f"{passage.source_path}:{passage.name}:{start}",
            source_path=passage.source_path,
            passage_name=passage.name,
            unit_index=0,
            unit_count=0,
            masked_text=masked,
            segments=segs,
            placeholders=phs,
            ancestors=ancestors,
            char_count=len(masked),
        )
        units.append(unit)
    return units


def _collect_groups(passage: Passage) -> list[dict]:
    """Group body children into contiguous segments split at containers."""
    groups: list[dict] = []
    current: list = []
    for child in passage.root.children:
        if child.node_type in ("text", "prose_text", "macro_call", "protected_markup"):
            current.append(child)
        else:
            if current:
                groups.append(_finalize_group(current, passage))
                current = []
            if child.node_type == "macro_container":
                ancestors = [{"node_type": child.node_type, "name": child.name}]
                ancestors += _ancestor_path(passage, child.node_id)
                groups.append({"span": child.span, "ancestors": ancestors,
                               "node": child, "kind": "container"})
    if current:
        groups.append(_finalize_group(current, passage))
    return groups


def _finalize_group(nodes: list, passage: Passage) -> dict:
    span = Span(nodes[0].span.start, nodes[-1].span.end)
    ancestors = _ancestor_path(passage, nodes[0].node_id)
    return {"span": span, "ancestors": ancestors, "node": None, "kind": "leaf"}


def _split_group(
    passage: Passage,
    artifact: MaskArtifact,
    data: bytes,
    group: dict,
    threshold: int,
    max_chars: int,
    min_chars: int,
    _depth: int = 0,
) -> list[dict]:
    """Recursively split an over-threshold container into span boundaries.

    Returns ``{"span": Span, "ancestors": [...]}`` dicts.
    """
    if _depth > 16 or group["kind"] not in ("container", "branch") or group["node"] is None or not group["node"].children:
        return [{"span": group["span"], "ancestors": group["ancestors"]}]
    node = group["node"]
    children = node.children
    group_start = group.get("start_override", node.span.start)
    group_end = group.get("end_override", node.span.end)
    spans: list[dict] = []
    for index, branch in enumerate(children):
        # Each unit starts at the previous sibling's end (or the container
        # start for the first, which carries the opening macro placeholder)
        # and ends at the next sibling's start (or the container end).
        start = group_start if index == 0 else children[index - 1].span.end
        end = children[index + 1].span.start if index + 1 < len(children) else group_end
        span = Span(start, end)
        if end - start <= threshold:
            spans.append({"span": span, "ancestors": _ancestor_path(passage, branch.node_id)})
        elif branch.node_type in ("macro_container", "macro_branch"):
            child_group = {
                "span": span,
                "ancestors": _ancestor_path(passage, branch.node_id),
                "node": branch,
                "kind": "container" if branch.node_type == "macro_container" else "branch",
                "start_override": start,
                "end_override": end,
            }
            spans.extend(_split_group(passage, artifact, data, child_group,
                                      threshold, max_chars, min_chars, _depth + 1))
        else:
            # leaf macro/text that is itself over the limit: keep as-is
            spans.append({"span": span, "ancestors": _ancestor_path(passage, branch.node_id)})
    return spans


def _merge_small_units(units: list[TranslateUnit], min_chars: int) -> list[TranslateUnit]:
    """Merge units smaller than ``min_chars`` with a neighbour (repeat until
    the merged unit clears the threshold or no neighbour remains)."""
    if len(units) <= 1:
        return units
    merged: list[TranslateUnit] = []
    i = 0
    while i < len(units):
        unit = units[i]
        while unit.char_count < min_chars and i + 1 < len(units):
            nxt = units[i + 1]
            unit = TranslateUnit(
                unit_id=unit.unit_id,
                source_path=unit.source_path,
                passage_name=unit.passage_name,
                unit_index=unit.unit_index,
                unit_count=unit.unit_count,
                masked_text=unit.masked_text + nxt.masked_text,
                segments=unit.segments + nxt.segments,
                placeholders=unit.placeholders + nxt.placeholders,
                ancestors=unit.ancestors or nxt.ancestors,
                char_count=unit.char_count + nxt.char_count,
            )
            i += 1
        merged.append(unit)
        i += 1
    return merged


PLACEHOLDER_PREFIX = "<0"


def _neighbour_context(unit: TranslateUnit) -> str:
    """Short placeholder-safe context slice of a neighbour unit.

    Truncates at a complete placeholder token boundary so the model never
    sees a half token like ``<00000`` in the context hint.
    """
    limit = 120
    text = unit.masked_text
    if len(text) <= limit:
        return text
    cut = text.rfind(PLACEHOLDER_PREFIX, 0, limit)
    if cut >= 0:
        # include the full token that starts at or before the cut
        end = text.find(">", cut + len(PLACEHOLDER_PREFIX))
        if end > 0 and end + 2 <= len(text):
            limit = end + 2
    return text[:limit]