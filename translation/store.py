"""Translation reuse store (design: docs/translation-reuse-design.md).

Records are JSONL rows keyed by sha256 of the source text.  One row per
translation event; later rows supersede earlier ones for the same hash
without rewriting history.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Sequence

from pretranslation_cst.model import MaskArtifact

PLACEHOLDER_RE = re.compile(r"<0\d{6}>")


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_translations(path: str | Path) -> dict[str, list[dict]]:
    """Load records grouped by source_text_hash, in append order."""
    records: dict[str, list[dict]] = {}
    p = Path(path)
    if not p.exists():
        return records
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            records.setdefault(record["source_text_hash"], []).append(record)
    return records


def load_translations_many(paths: Sequence[str | Path]) -> dict[str, list[dict]]:
    """Load several store files into one hash-keyed index.

    Files are merged in order, so a record in a later file supersedes an
    earlier one for the same hash (and for the assembler's per-passage
    "latest wins" rule, later files win over earlier ones).
    """
    records: dict[str, list[dict]] = {}
    for path in paths:
        for hash_value, group in load_translations(path).items():
            records.setdefault(hash_value, []).extend(group)
    return records


def find_reuse(hash_value: str, records: dict[str, list[dict]]) -> dict | None:
    """Latest usable record for a hash, or None.

    A record is usable when placeholders verified OK (``placeholder_ok``)
    and the source is not marked superseded.
    """
    candidates = records.get(hash_value) or []
    for record in reversed(candidates):
        if record.get("superseded"):
            continue
        if record.get("placeholder_ok", True):
            return record
    return None


def find_passage_reuse(
    body_text: str,
    records: dict[str, list[dict]],
    *,
    min_level: str = "passage",
) -> dict | None:
    """Passage-level reuse lookup keyed on the full passage body text."""
    record = find_reuse(source_hash(body_text), records)
    if record is None:
        return None
    level = record.get("level", "unit")
    if level != min_level:
        return None
    return record


def append_record(record: dict, path: str | Path) -> None:
    """Append one record (JSONL) to the store, creating the file if needed."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def passage_placeholder_signature(artifact: MaskArtifact) -> list[str]:
    """Ordered original bytes of the protected spans — the skeleton marker
    that must be preserved byte-for-byte by any reuse candidate."""
    return [ph.original_text for ph in artifact.placeholders]


def canonical_signature(signature: list[str], sensitive: list[bool]) -> list[str]:
    """Multiset-normalised signature for order-insensitive tokens (Option E).

    Order-sensitive tokens keep their exact positions; runs of
    order-insensitive tokens between them are sorted, so their internal
    order does not matter.  Two signatures with the same canonical form
    restore to identical rendered structure (see reorder-analysis.md §7).
    """
    out: list[str] = []
    run: list[str] = []
    for text, is_sensitive in zip(signature, sensitive):
        if is_sensitive:
            out.extend(sorted(run))
            run = []
            out.append(text)
        else:
            run.append(text)
    out.extend(sorted(run))
    return out


def signatures_equal(src_artifact: MaskArtifact, ko_artifact: MaskArtifact) -> bool:
    """Canonical protected-span equality between two masked artifacts.

    Order-insensitive spans (display-only macros, variables, HTML) are
    compared as multisets, so a Korean word-order reorder of those tokens
    is tolerated; state/control spans keep strict sequence equality."""
    src_sig = passage_placeholder_signature(src_artifact)
    ko_sig = passage_placeholder_signature(ko_artifact)
    src_sensitive = [ph.order_sensitive for ph in src_artifact.placeholders]
    ko_sensitive = [ph.order_sensitive for ph in ko_artifact.placeholders]
    return canonical_signature(src_sig, src_sensitive) == canonical_signature(ko_sig, ko_sensitive)


def ko_body_preserves_skeleton(ko_body: str, signature: list[str]) -> bool:
    """Check that the KO body contains every protected span byte, in order.

    triple-match guarantees the skeleton (macros/links/formatting) is
    identical between source and KO body; this is a belt-and-braces check
    before registering or reusing a passage.
    """
    cursor = 0
    for token in signature:
        idx = ko_body.find(token, cursor)
        if idx < 0:
            return False
        cursor = idx + len(token)
    return True
