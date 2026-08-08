"""Translate full passages via Gemini and store passage-level records.

Completes the reuse design R2/R4 (docs/translation-reuse-design.md): a
passage is chunked into units, every unit is translated with the existing
retry/preservation logic, the units are restored into a full translated
body, the body is skeleton-verified with our own parser, and a
``level="passage"`` record (source=gemini) is appended to the store the
assembler reads.

Units get two verification layers before joining:

- L1 (``verify_placeholders``): every own placeholder token survives
  exactly once — retried inside ``translate_unit``.
- L2 (``verify_unit_structure``): the own tokens stay in source order
  (``reorder`` — order-insensitive display tokens may move, Option E), and
  no foreign/hallucinated placeholder-like token appears (``foreign_token``
  / ``format_hallucination``) — flagged units are retried with a targeted
  hint, then the passage fails fast with the L2 code instead of wasting a
  full-passage restore/signature failure.

Failure policy (2 tiers, no further auto-escalation):

- tier 1 (``model``, default flash-lite): transient API errors retry on
  the same tier inside the client; unit-level L1/L2 failures escalate to
  ``escalation_model`` (default flash)
- tier 2: a joined-level ``skeleton_mismatch`` re-translates only the unit
  boundary pairs whose prose separation vanished (``boundary_prose_drops``)
  with ``escalation_model``; if L3 still fails it is terminal and only
  logged (the fail log is the data source for a later, deliberate re-run)

``--journal`` streams one JSON line per unit result and per passage
outcome (flushed per write), so progress survives a crash.

Passages already present in the store are skipped unless ``--force``.

Usage:
    python3 -m translation.translate_passages \
        --file game/overworld-town/loc-cafe/main.twee --passage-name "Ocean Breeze"
    python3 -m translation.translate_passages \
        --passages-file /tmp/opencode/passages.jsonl --request-id req_20260808_001
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pretranslation_cst.chunking import chunk_passage
from pretranslation_cst.masking import mask_passage
from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH
from translation.client import (
    TranslatedUnit,
    restore_joined,
    translate_unit,
    translate_units_batch,
    verify_placeholders,
)
from translation.post import post_process, remaining_dynamic_markers
from translation.store import (
    append_record,
    find_passage_reuse,
    find_reuse,
    load_translations,
    load_translations_many,
    passage_placeholder_signature,
    signatures_equal,
    source_hash,
)

DEFAULT_STORE = Path("work/translations/gemini-passages.jsonl")
DEFAULT_LEGACY_STORE = Path("work/translations/ko-reuse.jsonl")


def next_request_id(records: dict[str, list[dict]]) -> str:
    """Auto request id: req_<yyyymmdd>_<seq> (KST)."""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    prefix = f"req_{today}_"
    seq = 0
    for group in records.values():
        for record in group:
            rid = record.get("request_id", "")
            if rid.startswith(prefix):
                try:
                    seq = max(seq, int(rid[len(prefix):]))
                except ValueError:
                    pass
    return f"{prefix}{seq + 1:03d}"


def _skeleton_ok(source_artifact, translated_body: bytes, passage_name: str, source_path: str) -> bool:
    """Mask the translated body and compare protected-span signatures with
    the source.  A mismatch means the translation broke the structure.

    Order-insensitive spans (display-only macros, variables, HTML — see
    pretranslation_cst.order_sensitivity) are compared as multisets, so a
    Korean word-order reorder of those tokens is tolerated; state/control
    spans keep strict sequence equality (Option E, shared with the
    assembler: translation.store.signatures_equal)."""
    try:
        synthetic = f":: {passage_name}\n\n".encode("utf-8") + translated_body
        source = parse_file(synthetic, source_path, DEFAULT_VALUE_KIND_PATH)
        passage = next((p for p in source.passages if p.name == passage_name), None)
        if passage is None:
            return False
        ko_artifact = mask_passage(synthetic, passage)
    except Exception:
        return False
    return signatures_equal(source_artifact, ko_artifact)


# any placeholder-like token the model might emit (including wrong-digit
# hallucinations like <000000> when the masker grew the prefix to <0000000>,
# and underscore-prefixed tokens when the masker's collision loop fired)
_TOKEN_RE = re.compile(r"<0[\d_]+>")

L2_RETRIES = 2


def _token_digit_count(token: str) -> int:
    """Number of characters inside a <0NNNNN> token (format fingerprint)."""
    return len(token) - 2


def _prose_gap_problems(unit, translated: str) -> list[str]:
    """``prose_drop``: two own tokens are adjacent in the translation while
    the source had non-whitespace text between them — the model moved or
    merged the prose across the token boundary (e.g. ``<<He>> points at
    <<him>>`` → ``<<He>><<him>>을 가리키며``).  Whitespace-only source gaps
    are the separator-repair's job and are not flagged here."""
    masked = unit.masked_text
    own = [ph.placeholder for ph in unit.placeholders]
    if len(own) < 2:
        return []
    pos: list[int] = []
    cursor = 0
    for token in own:
        idx = masked.find(token, cursor)
        if idx < 0:
            return []
        pos.append(idx)
        cursor = idx + len(token)
    for i in range(len(own) - 1):
        src_gap = masked[pos[i] + len(own[i]) : pos[i + 1]]
        if not src_gap.strip():
            continue
        t_idx = translated.find(own[i])
        n_idx = (
            translated.find(own[i + 1], t_idx + len(own[i])) if t_idx >= 0 else -1
        )
        if t_idx < 0 or n_idx < 0:
            return []
        if not translated[t_idx + len(own[i]) : n_idx]:
            return ["prose_drop"]
    return []


# prompt scaffolding markers — the model echoing the prompt back (possibly
# with post markers attached) passes L1/L2 (tokens preserved) and only
# explodes at L3, when the echoed "following_context:" gets re-parsed as a
# variable span; catch it early instead
_PROMPT_ECHO_MARKERS = (
    "--- TRANSLATE THIS ---",
    "following_context:",
    "preceding_context:",
    "ancestors:",
    "of passage ",
)


def _prompt_echo_problems(translated: str) -> list[str]:
    """``prompt_echo``: the output contains prompt scaffolding — the model
    returned its own input (with or without edits) instead of a Korean
    translation (observed 2026-08-08: Schism Gold Refuse, where the echoed
    ``following_context:`` text was re-parsed as a variable span and the
    joined skeleton collapsed)."""
    if any(marker in translated for marker in _PROMPT_ECHO_MARKERS):
        return ["prompt_echo"]
    return []


def _content_dropped(unit, translated: str) -> list[str]:
    """``content_drop``: the unit carries real content but the output is
    whitespace-only — the model deleted the text entirely.  Placeholder
    checks cannot see this (the fragment may have no tokens at all, e.g.
    a ``"The "`` fragment unit after the no-merge split), and a silently
    dropped sentence would otherwise assemble as nothing (observed
    2026-08-08: ``" gives you a satisfied smile when "`` -> ``" "``)."""
    if not any(seg.text.strip() for seg in (unit.segments or [])):
        return []
    if not translated.strip():
        return ["content_drop"]
    return []


def verify_unit_structure(unit, translated: str) -> list[str]:
    """L2: unit-level structure checks beyond L1 (each own token exactly once).

    Returns problem codes, empty when OK:

    - ``reorder``: the unit's own tokens appear but not in source order
      (restore would silently substitute them in the wrong places and only
      the joined-signature check would catch it — too late).
    - ``foreign_token``: a placeholder-like token that is not owned by this
      unit (a neighbouring unit's token echoed, or a hallucinated one).
    - ``format_hallucination``: a foreign token whose shape differs from the
      unit's own token format — the model wrote a placeholder in the wrong
      shape (e.g. ``<000000>`` when the masker uses ``<0000000>`` because
      the body text collided with the default prefix).
    - ``prose_drop``: own tokens adjacent in the output although the source
      had prose between them (checked only when the token stream is intact
      and in order).
    - ``content_drop``: the unit has real content but the output is
      whitespace-only — the model deleted the text (invisible to the
      placeholder checks when the unit has no tokens).

    The corpus contains no literal placeholder-like text, so any token-like
    string not owned by the unit is a model artifact.
    """
    own = [ph.placeholder for ph in unit.placeholders]
    own_set = set(own)
    problems: list[str] = _content_dropped(unit, translated)
    problems.extend(_prompt_echo_problems(translated))
    own_digits = {_token_digit_count(t) for t in own}
    for token in _TOKEN_RE.findall(translated):
        if token in own_set:
            continue
        if own_digits and _token_digit_count(token) not in own_digits:
            problems.append("format_hallucination")
        else:
            problems.append("foreign_token")
        break
    own_in_order = [t for t in _TOKEN_RE.findall(translated) if t in own_set]
    # reorder only when every own token is present (a missing token is a
    # drop, which L1 catches) — otherwise a drop would be double-reported
    if len(own_in_order) == len(own) and own_in_order != own:
        # Option E: a reorder of order-insensitive tokens (display-only
        # macros — pronouns, names, variables, HTML) is the model
        # naturalising Korean word order; the restored rendering is
        # unchanged.  Only flag when a state/control token moved.
        if _moved_sensitive_tokens(unit, own, own_in_order):
            problems.append("reorder")
    elif len(own_in_order) == len(own) and not problems:
        problems.extend(_prose_gap_problems(unit, translated))
    return problems


def _moved_sensitive_tokens(unit, own: list[str], own_in_order: list[str]) -> list[str]:
    """Own tokens whose position changed AND that are order-sensitive."""
    sensitive = {ph.placeholder: ph.order_sensitive for ph in unit.placeholders}
    moved = {
        token
        for index, token in enumerate(own)
        if index >= len(own_in_order) or own_in_order[index] != token
    }
    return [token for token in moved if sensitive.get(token, True)]


def _l2_retry_hint(problems: list[str]) -> str:
    hint = (
        "Your previous attempt had a structure problem: "
        + ", ".join(problems)
        + ". Copy the placeholder tokens exactly as written, keep them in"
        " the same order, and do not add any other <...> tokens."
    )
    if "prose_drop" in problems:
        hint += (
            " Keep the text between the placeholder tokens intact — do not"
            " move or merge it."
        )
    if "content_drop" in problems:
        hint += (
            " The unit text is not empty — output a Korean translation of"
            " it; never return only whitespace."
        )
    if "prompt_echo" in problems:
        hint += (
            " Do not echo the prompt or its fields — output only the Korean"
            " translation of the unit text, with nothing else."
        )
    return hint

# malformed {{post:...}} markers: closing brace missing, or closed with a
# single '}' (e.g. "{{post:이가}" — the LLM typo'd the marker)
_MALFORMED_POST_RE = re.compile(r"\{\{post:[^}]*$|" r"\{\{post:[^}]*\}(?!\})")


def verify_malformed_post_markers(text: str) -> list[str]:
    """Detect structurally broken ``{{post:...}}`` markers in translated text
    (unclosed or single-brace closed).  They are not placeholders, so the
    placeholder/skeleton checks never see them."""
    return [match.group(0) for match in _MALFORMED_POST_RE.finditer(text)]


def _separator_gap(text: str, start: int, next_tokens: list[str]) -> str | None:
    """The whitespace-only gap between a placeholder (ending at ``start``)
    and the next placeholder token, or None when the gap contains non-
    whitespace (or there is no next placeholder).

    ``next_tokens`` are the artifact's remaining placeholder tokens in
    order — the look-up is format-agnostic (the masker's prefix can grow,
    which changes the token shape).
    """
    for token in next_tokens:
        idx = text.find(token, start)
        if idx >= 0:
            gap = text[start:idx]
            return gap if not gap.strip() else None
    return None


def _next_tokens(artifact, index: int) -> list[str]:
    """Placeholder tokens after the ``index``-th one, in artifact order."""
    return [ph.placeholder for ph in artifact.placeholders[index + 1 :]]


def _leading_whitespace(text: str, start: int) -> str:
    run = 0
    while start + run < len(text) and text[start + run].isspace():
        run += 1
    return text[start : start + run]


def verify_separator_newlines(artifact, joined: str) -> list[str]:
    """Find placeholders whose whitespace separator (the only thing between
    them and the next protected span) changed in the joined translated text:
    dropped entirely, or shrunk (e.g. ``\\n\\n`` paragraph break → ``\\n``).
    Such changes merge spans in the parser or silently alter rendering.
    Runs on the JOINED text so unit boundaries are covered."""
    problems: list[str] = []
    masked = artifact.masked_text
    for index, placeholder in enumerate(artifact.placeholders):
        token = placeholder.placeholder
        m_idx = masked.find(token)
        t_idx = joined.find(token)
        if m_idx < 0 or t_idx < 0:
            continue  # placeholder drop is handled elsewhere
        m_gap = _separator_gap(masked, m_idx + len(token), _next_tokens(artifact, index))
        if m_gap is None:
            continue
        t_gap = _leading_whitespace(joined, t_idx + len(token))
        if t_gap != m_gap:
            problems.append(token)
    return problems


def repair_separator_newlines(artifact, joined: str) -> str:
    """Deterministically restore the whitespace separator gaps.  The masked
    reference guarantees the gap was whitespace-only, so replacing whatever
    whitespace (or nothing) the translation left with the original gap
    reproduces the original structure and rendering exactly.

    Order-independent: each token is located on its own (``joined.find``),
    so Option E reorders of display-only tokens do not break the repair —
    a monotonic cursor would walk past a moved token and abort the whole
    repair early."""
    masked = artifact.masked_text
    edits: list[tuple[int, str]] = []  # (token end position, source gap)
    for index, placeholder in enumerate(artifact.placeholders):
        token = placeholder.placeholder
        m_idx = masked.find(token)
        m_gap = _separator_gap(masked, m_idx + len(token), _next_tokens(artifact, index))
        if m_gap is None:
            continue
        t_idx = joined.find(token)
        if t_idx < 0:
            continue  # missing placeholder — restore will raise loudly
        after = t_idx + len(token)
        t_gap = _leading_whitespace(joined, after)
        if t_gap != m_gap:
            edits.append((after, m_gap))
    if not edits:
        return joined
    edits.sort()
    out: list[str] = []
    cursor = 0
    for position, gap in edits:
        if position < cursor:
            continue  # inside a whitespace run already replaced
        run_end = position + len(_leading_whitespace(joined, position))
        out.append(joined[cursor:position])
        out.append(gap)
        cursor = run_end
    out.append(joined[cursor:])
    return "".join(out)


DEFAULT_ESCALATION_MODEL = "gemini-2.5-flash"


def boundary_prose_drops(
    artifact, translated_units: list[TranslatedUnit]
) -> list[tuple[int, str, str]]:
    """Unit boundaries where the joined text dropped the prose that
    separated the last token of unit i and the first token of unit i+1 in
    the source — the model moved the boundary text, leaving the two macros
    adjacent so the parser merges them into one span at L3.

    Whitespace-only source gaps are excluded (the separator repair handles
    them).  Returns [(unit_index_of_left_unit, token_a, token_b)].
    """
    masked = artifact.masked_text
    problems: list[tuple[int, str, str]] = []
    for i in range(len(translated_units) - 1):
        unit_a = translated_units[i].unit
        unit_b = translated_units[i + 1].unit
        if not unit_a.placeholders or not unit_b.placeholders:
            continue
        token_a = unit_a.placeholders[-1].placeholder
        token_b = unit_b.placeholders[0].placeholder
        m_a = masked.find(token_a)
        m_b = masked.find(token_b)
        if m_a < 0 or m_b < 0:
            continue
        src_gap = masked[m_a + len(token_a):m_b]
        if not src_gap.strip():
            continue
        text_a = translated_units[i].translated_text
        text_b = translated_units[i + 1].translated_text
        idx_a = text_a.find(token_a)
        idx_b = text_b.find(token_b)
        if idx_a < 0 or idx_b < 0:
            continue
        joined_gap = text_a[idx_a + len(token_a):] + text_b[:idx_b]
        if not joined_gap.strip():
            problems.append((i, token_a, token_b))
    return problems


def _journal_write(journal: Path | None, payload: dict) -> None:
    """Append one JSON line to the journal and flush immediately, so a
    crash never loses the responses already processed."""
    if journal is None:
        return
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
        fh.flush()


def _journal_fail(
    journal: Path | None,
    source_path: str,
    passage_name: str,
    unit_index: int,
    unit_count: int,
    reason: str,
    failed_model: str,
    recovered_by: str | None,
) -> None:
    """One failure event — this is the re-run queue.  A terminal failure
    (``recovered_by`` is None) is a re-run target: extract
    (source_path, passage_name) and feed it back as a new batch."""
    _journal_write(journal, {
        "kind": "fail",
        "source_path": source_path,
        "passage_name": passage_name,
        "unit_index": unit_index,
        "unit_count": unit_count,
        "reason": reason,
        "model": failed_model,
        "recovered_by": recovered_by,
    })


def _journal_passage(
    journal: Path | None,
    source_path: str,
    passage_name: str,
    status: str,
    reason: str | None,
    record_id: str | None,
) -> None:
    _journal_write(journal, {
        "kind": "passage",
        "source_path": source_path,
        "passage_name": passage_name,
        "status": status,
        "reason": reason,
        "record_id": record_id,
    })


def _resolve_unit(
    unit,
    index: int,
    total: int,
    tu: TranslatedUnit,
    *,
    model: str,
    escalation_model: str | None,
    translated_units: list[TranslatedUnit],
    debug_dir: Path | None,
    passage_name: str,
    units,
) -> tuple[str | None, str | None, int, bool, list[dict]]:
    """Run L1/L2 checks on one unit's first output, with hint retries and
    model escalation.  Returns (post-processed text, failure reason, l2
    retries used, escalated, fail events).

    ``fail events`` are per-failure log lines (``kind: fail``) recording
    every unit failure and whether the escalation recovered it — this is
    the fail log the re-run workflow reads.  On failure text is None and
    reason set.

    Escalation is skipped when ``escalation_model`` is None (no further
    auto-escalation)."""
    l2_retries_used = 0
    escalated = False
    fail_events: list[dict] = []

    def fail_event(reason: str, failed_model: str, recovered_by: str | None) -> dict:
        return {
            "kind": "fail",
            "passage_name": passage_name,
            "unit_index": index + 1,
            "unit_count": total,
            "reason": reason,
            "model": failed_model,
            "recovered_by": recovered_by,
        }

    if verify_placeholders(unit, tu.translated_text):
        # placeholder drop: hint retries do not fix drops (observed) —
        # escalate to the stronger model directly
        fail_events.append(fail_event("placeholder_drop", model, escalation_model))
        if escalation_model is None:
            _dump_failure(debug_dir, passage_name, "placeholder_drop", units,
                          _dump_texts(translated_units, tu, index, total))
            return None, "placeholder_drop", l2_retries_used, escalated, fail_events
        tu = translate_unit(unit, index, total, model=escalation_model)
        escalated = True
        if verify_placeholders(unit, tu.translated_text):
            fail_events.append(fail_event("placeholder_drop", escalation_model, None))
            _dump_failure(debug_dir, passage_name, "placeholder_drop", units,
                          _dump_texts(translated_units, tu, index, total))
            return None, "placeholder_drop", l2_retries_used, escalated, fail_events
    problems = verify_unit_structure(unit, tu.translated_text)
    if problems:
        # L2: early unit-level structure check with targeted retries —
        # the same problems would otherwise only surface as a joined
        # restore/signature failure after every unit was translated.
        last_reason = problems[0]
        recovered = False
        for _ in range(L2_RETRIES):
            l2_retries_used += 1
            tu = translate_unit(
                unit, index, total, hint=_l2_retry_hint(problems),
                model=model,
            )
            if verify_placeholders(unit, tu.translated_text):
                last_reason = "placeholder_drop"
                continue
            problems = verify_unit_structure(unit, tu.translated_text)
            if not problems:
                recovered = True
                break
            last_reason = problems[0]
        if not recovered:
            fail_events.append(fail_event(last_reason, model, escalation_model))
            if escalation_model is None:
                _dump_failure(debug_dir, passage_name, last_reason, units,
                              _dump_texts(translated_units, tu, index, total))
                return None, last_reason, l2_retries_used, escalated, fail_events
            # model escalation: the stronger model may avoid the structure
            # problem (or convert it into an L1/L2 checkable one)
            tu = translate_unit(
                unit, index, total, hint=_l2_retry_hint(problems),
                model=escalation_model,
            )
            escalated = True
            if verify_placeholders(unit, tu.translated_text):
                last_reason = "placeholder_drop"
            else:
                problems = verify_unit_structure(unit, tu.translated_text)
                if problems:
                    last_reason = problems[0]
                else:
                    recovered = True
            if not recovered:
                fail_events.append(fail_event(last_reason, escalation_model, None))
                _dump_failure(debug_dir, passage_name, last_reason, units,
                              _dump_texts(translated_units, tu, index, total))
                return None, last_reason, l2_retries_used, escalated, fail_events
    processed = post_process(tu.translated_text)
    if verify_malformed_post_markers(processed):
        # the model typo'd a {{post:...}} marker (missing/dropped brace) —
        # escalate the unit; a malformed marker would otherwise surface only
        # at the joined check after every unit was translated
        fail_events.append(fail_event("malformed_post_marker", model, escalation_model))
        if escalation_model is None:
            _dump_failure(debug_dir, passage_name, "malformed_post_marker", units,
                          _dump_texts(translated_units, tu, index, total))
            return None, "malformed_post_marker", l2_retries_used, escalated, fail_events
        tu = translate_unit(unit, index, total, model=escalation_model)
        escalated = True
        processed = post_process(tu.translated_text)
        if verify_placeholders(unit, tu.translated_text) or verify_malformed_post_markers(processed):
            fail_events.append(fail_event("malformed_post_marker", escalation_model, None))
            _dump_failure(debug_dir, passage_name, "malformed_post_marker", units,
                          _dump_texts(translated_units, tu, index, total))
            return None, "malformed_post_marker", l2_retries_used, escalated, fail_events
    return processed, None, l2_retries_used, escalated, fail_events


def _restore_unit_text(unit) -> str:
    """Restore a unit's masked text (or its translation) to original bytes —
    the per-unit source/translated text for the unit store."""
    text = unit.masked_text
    for placeholder in unit.placeholders:
        occurrences = text.count(placeholder.placeholder)
        if occurrences != 1:
            continue  # should not happen for source text
        text = text.replace(placeholder.placeholder, placeholder.original_text, 1)
    return text


def _restore_translated_text(unit, translated: str) -> str:
    """Restore a unit's translated text the same way (tokens → originals)."""
    for placeholder in unit.placeholders:
        occurrences = translated.count(placeholder.placeholder)
        if occurrences != 1:
            continue
        translated = translated.replace(placeholder.placeholder, placeholder.original_text, 1)
    return translated


def _is_glue_unit(unit) -> bool:
    """True when the unit carries no translatable content — only whitespace
    and protected spans (macros/variables/HTML).  Such units have no prose to
    translate: the identity text (tokens copied verbatim) is the correct and
    only translation, so they skip the API entirely (no-merge chunking
    leaves many of these structural fragments; 2026-08-08)."""
    return not any(seg.text.strip() for seg in unit.segments)


def _retokenize(unit, restored_translated: str) -> str | None:
    """Map a restored translated text back onto this unit's placeholder
    tokens, in order.

    The stored translation carries original bytes — the masker renumbers
    tokens by position, so the token numbers of a stored unit differ after
    any edit (or across passages), and the stored token form would never
    verify against this unit.  Substituting this unit's tokens for the
    originals yields a pipeline-ready token form.  Returns None when an
    original is missing (nothing to reuse safely)."""
    text = restored_translated
    for ph in unit.placeholders:
        idx = text.find(ph.original_text)
        if idx < 0:
            return None
        text = text[:idx] + ph.placeholder + text[idx + len(ph.original_text):]
    return text


def _reuse_unit(unit, units_records: dict | None) -> TranslatedUnit | None:
    """Stored translation for the same restored source text (R2 unit reuse),
    or None on miss / corrupt record.

    The stored ``translated_text`` is restored (original bytes) and already
    post-processed, so a hit is re-tokenised for this unit, re-verified with
    the cheap L1/L2 checks (no API call) and, when clean, feeds the join
    pipeline directly — zero API calls for unchanged units after a game
    update or across passages."""
    if not units_records:
        return None
    record = find_reuse(source_hash(_restore_unit_text(unit)), units_records)
    if record is None or not record.get("translated_text"):
        return None
    tokenized = _retokenize(unit, record["translated_text"])
    if tokenized is None:
        return None
    candidate = TranslatedUnit(unit, tokenized)
    if verify_placeholders(unit, candidate.translated_text):
        return None
    if verify_unit_structure(unit, candidate.translated_text):
        return None
    return candidate


def _append_unit_record(
    units_store: Path | None,
    request_id: str,
    source_path: str,
    passage_name: str,
    unit,
    index: int,
    total: int,
    source_text: str,
    translated_text: str,
    model: str,
    escalated: bool,
) -> None:
    """Stream one record per chunk unit — the unit-level tracking/reuse
    store.  ``source_text`` is the unit's original text (tokens restored)
    and ``translated_text`` the restored translation (original bytes) —
    both token-independent, so ``source_text_hash`` (the R2 reuse key) and
    the stored translation survive edits and across passages.  Appended and
    flushed per unit."""
    if units_store is None:
        return
    record = {
        "record_id": f"un_{source_hash(source_text)[:12]}",
        "source_text_hash": source_hash(source_text),
        "source_text": source_text,
        "translated_text": translated_text,
        "source_path": source_path,
        "passage_name": passage_name,
        "unit_index": index + 1,
        "unit_count": total,
        "request_id": request_id,
        "model": model,
        "escalated": escalated,
        "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "placeholder_ok": True,
        "level": "unit",
        "source": "gemini",
    }
    append_record(record, units_store)


def translate_passage(
    path: Path,
    passage,
    *,
    request_id: str,
    store_records: dict[str, list[dict]],
    force: bool = False,
    game_root: Path | None = None,
    debug_dir: Path | None = None,
    model: str | None = None,
    escalation_model: str | None = DEFAULT_ESCALATION_MODEL,
    batch_size: int = 1,
    journal: Path | None = None,
    units_store: Path | None = None,
    units_records: dict[str, list[dict]] | None = None,
    rejected_hashes: frozenset[str] = frozenset(),
) -> tuple[dict | None, str]:
    """Translate one passage fully.  Returns (record, reason): record is
    None when the passage was skipped (reason="skipped") or failed
    (reason describes the failure step).

    ``batch_size > 1`` translates the units in batched API requests
    (``translate_units_batch``) with per-unit validation and model
    escalation for the failing units.

    Failure policy (2 tiers, no further auto-escalation):
    - tier 1 (``model``, default flash-lite): transient API errors are
      retried on the same tier inside the client; unit-level L1/L2 failures
      escalate to ``escalation_model`` (default flash)
    - tier 2: a joined-level ``skeleton_mismatch`` re-translates only the
      unit boundary pairs whose prose separation vanished
      (``boundary_prose_drops``) with ``escalation_model``; if L3 still
      fails it is terminal and only logged (the fail log is the data
      source for a later, deliberate re-run)

    ``journal`` (optional) streams one JSON line per unit result and per
    passage outcome — flushed after every write so progress survives a
    crash."""
    data = path.read_bytes()
    artifact = mask_passage(data, passage)
    source_path = _rel_source_path(path, game_root)
    body_text = data[passage.body_span.start:passage.body_span.end].decode("utf-8")
    if not force:
        reuse = find_passage_reuse(body_text, store_records)
        if reuse is not None:
            # a record the assembler rejected (assembly re-verification
            # failed) must not count as translated — re-translate it
            if reuse["source_text_hash"] in rejected_hashes:
                print(f"re-translating rejected: {passage.name}", file=sys.stderr)
            else:
                return None, "skipped"  # already translated

    units = chunk_passage(passage, artifact, data)
    base_model = model or "gemini-2.5-flash-lite"
    translated_units: list[TranslatedUnit] = []
    l2_retries = 0
    escalated = 0
    reused_units = 0
    glue_units = 0
    if batch_size <= 1:
        for index, unit in enumerate(units):
            esc = False
            if _is_glue_unit(unit):
                # whitespace/protected-span glue: verbatim is the only
                # correct translation — no API call, no store record
                final_text = unit.masked_text
                glue_units += 1
                translated_units.append(TranslatedUnit(unit, final_text))
                continue
            tu = _reuse_unit(unit, units_records)
            if tu is None:
                tu = translate_unit(unit, index, len(units), model=base_model)
                text, reason, used, esc, fail_events = _resolve_unit(
                    unit, index, len(units), tu,
                    model=base_model, escalation_model=escalation_model,
                    translated_units=translated_units, debug_dir=debug_dir,
                    passage_name=passage.name, units=units,
                )
                l2_retries += used
                escalated += esc
                for event in fail_events:
                    _journal_fail(journal, source_path, passage.name,
                                  event["unit_index"], event["unit_count"],
                                  event["reason"], event["model"], event["recovered_by"])
                if reason is not None:
                    return None, reason
                final_text = text if text is not None else ""
                _append_unit_record(
                    units_store, request_id, source_path, passage.name,
                    unit, index, len(units), _restore_unit_text(unit),
                    _restore_translated_text(unit, final_text),
                    base_model, esc,
                )
            else:
                final_text = tu.translated_text
                reused_units += 1  # record already exists — no re-append
            translated_units.append(TranslatedUnit(unit, final_text))
    else:
        for start in range(0, len(units), batch_size):
            batch = units[start:start + batch_size]
            # R2: units with a stored translation skip the API call — the
            # batch is sent without them and their re-tokenised stored text
            # is spliced back into the per-unit loop below.
            stored = {}
            fresh = []
            for i, unit in enumerate(batch):
                if _is_glue_unit(unit):
                    # verbatim glue: no API call, no store record
                    stored[i] = unit.masked_text
                    glue_units += 1
                    continue
                tu = _reuse_unit(unit, units_records)
                if tu is None:
                    fresh.append((i, unit))
                else:
                    stored[i] = tu.translated_text
                    reused_units += 1
            texts = dict(stored)
            if fresh:
                fresh_units = [unit for _, unit in fresh]
                if len(fresh_units) == 1:
                    # batch protocol needs >=2 items — go straight to a
                    # single per-unit call
                    fresh_texts = [
                        translate_unit(fresh_units[0], start + fresh[0][0],
                                       len(units), model=base_model).translated_text
                    ]
                else:
                    try:
                        fresh_texts = translate_units_batch(fresh_units, model=base_model)
                    except Exception as exc:
                        # protocol failure (bad JSON / schema mismatch) —
                        # fall back to per-unit calls for this batch
                        print(f"[batch fallback] {type(exc).__name__}: {exc}", file=sys.stderr)
                        fresh_texts = [
                            translate_unit(unit, start + i, len(units), model=base_model).translated_text
                            for i, unit in enumerate(fresh_units)
                        ]
                for (i, _), text in zip(fresh, fresh_texts):
                    texts[i] = text
            for i, (unit, text) in enumerate(zip(batch, [texts[j] for j in range(len(batch))])):
                index = start + i
                if i in stored:
                    # reused: already stored and verified by _reuse_unit
                    translated_units.append(TranslatedUnit(unit, text))
                    continue
                tu = TranslatedUnit(unit, text)
                resolved, reason, used, esc, fail_events = _resolve_unit(
                    unit, index, len(units), tu,
                    model=base_model, escalation_model=escalation_model,
                    translated_units=translated_units, debug_dir=debug_dir,
                    passage_name=passage.name, units=units,
                )
                l2_retries += used
                escalated += esc
                for event in fail_events:
                    _journal_fail(journal, source_path, passage.name,
                                  event["unit_index"], event["unit_count"],
                                  event["reason"], event["model"], event["recovered_by"])
                if reason is not None:
                    return None, reason
                final_text = resolved if resolved is not None else ""
                _append_unit_record(
                    units_store, request_id, source_path, passage.name,
                    unit, index, len(units), _restore_unit_text(unit),
                    _restore_translated_text(unit, final_text),
                    base_model, esc,
                )
                translated_units.append(TranslatedUnit(unit, final_text))

    joined = "".join(tu.translated_text for tu in translated_units)
    joined_original = joined
    joined = repair_separator_newlines(artifact, joined)
    repaired = joined != joined_original

    malformed = verify_malformed_post_markers(joined)
    if malformed:
        _dump_failure(debug_dir, passage.name, "malformed_post_marker", units,
                      [tu.translated_text for tu in translated_units])
        return None, "malformed_post_marker"

    try:
        restored = restore_joined(artifact, joined)
    except ValueError:
        _dump_failure(debug_dir, passage.name, "restore_failed", units,
                      [tu.translated_text for tu in translated_units])
        return None, "restore_failed"
    translated_text = restored.decode("utf-8")

    recovered_after_boundary = False
    if not _skeleton_ok(artifact, restored, passage.name, artifact.source_path):
        # joined-level structure failure: escalate only the unit boundary
        # pairs whose prose separation vanished, then let L3 decide.  No
        # whole-passage retry — a second failure is terminal (the fail log
        # is the data source for a later, deliberate re-run).
        if escalation_model and escalation_model != base_model:
            boundary = boundary_prose_drops(artifact, translated_units)
            if boundary:
                affected = sorted({i for pair in boundary for i in (pair[0], pair[0] + 1)})
                print(f"[boundary escalation] {passage.name}: "
                      f"re-translating units {affected} with {escalation_model}")
                for index in affected:
                    if index >= len(translated_units):
                        continue
                    unit = translated_units[index].unit
                    tu = translate_unit(unit, index, len(units), model=escalation_model)
                    if verify_placeholders(unit, tu.translated_text):
                        continue  # escalation dropped too — keep original
                    if verify_unit_structure(unit, tu.translated_text):
                        continue  # escalated output has its own problem
                    translated_units[index] = TranslatedUnit(
                        unit, post_process(tu.translated_text))
                    escalated += 1
                joined = "".join(tu.translated_text for tu in translated_units)
                joined_after = repair_separator_newlines(artifact, joined)
                repaired = repaired or joined_after != joined
                try:
                    restored = restore_joined(artifact, joined_after)
                    if _skeleton_ok(artifact, restored, passage.name, artifact.source_path):
                        translated_text = restored.decode("utf-8")
                        recovered_after_boundary = True
                except ValueError:
                    pass
        if not recovered_after_boundary:
            _dump_failure(debug_dir, passage.name, "skeleton_mismatch", units,
                          [tu.translated_text for tu in translated_units])
            return None, "skeleton_mismatch"

    record = _make_record(
        body_text, source_path, passage, request_id, model, translated_text,
        repaired, l2_retries, escalated, len(units), reused_units, glue_units,
    )
    _journal_passage(journal, source_path, passage.name,
                     "ok", None, record["record_id"])
    return record, "ok"


def _make_record(
    body_text: str,
    source_path: str,
    passage,
    request_id: str,
    model: str | None,
    translated_text: str,
    repaired: bool,
    l2_retries: int,
    escalated: int,
    unit_count: int,
    reused_units: int,
    glue_units: int,
) -> dict:
    markers = remaining_dynamic_markers(translated_text)
    return {
        "record_id": f"tr_{source_hash(body_text)[:12]}_gemini",
        "source_text_hash": source_hash(body_text),
        "source_text": body_text,
        "translated_text": translated_text,
        "source_path": source_path,
        "passage_name": passage.name,
        "unit_id": f"{source_path}:{passage.name}",
        "request_id": request_id,
        "model": model or "gemini-2.5-flash-lite",
        "temperature": 0.7,
        "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "placeholder_ok": True,
        "post_status": "runtime_remaining" if markers else "static_done",
        "source": "gemini",
        "level": "passage",
        "repaired": repaired,
        "l2_retries": l2_retries,
        "api_calls": unit_count + l2_retries,
        "escalated": escalated > 0,
        "escalated_units": escalated,
        "reused_units": reused_units,
        "glue_units": glue_units,
        "tier": "escalated" if escalated > 0 else "base",
    }


def _dump_texts(
    translated_units: list[TranslatedUnit],
    current: TranslatedUnit,
    index: int,
    total: int,
) -> list[str | None]:
    """Translated texts of every unit up to and including the failing one
    (None for the untranslated tail) — a single-unit failure dump keeps the
    context that led to the failure."""
    texts: list[str | None] = [tu.translated_text for tu in translated_units]
    texts.append(current.translated_text)
    texts.extend([None] * (total - index - 1))
    return texts


def _dump_failure(
    debug_dir: Path | None,
    passage_name: str,
    reason: str,
    units,
    translated_texts: list[str | None],
) -> None:
    """Write per-unit masked/translated texts for a failed passage so the
    failure can be analysed without re-translating (LLM output is
    non-deterministic)."""
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "unit_index": index + 1,
            "masked_text": unit.masked_text,
            "translated_text": translated_texts[index] if index < len(translated_texts) else None,
        }
        for index, unit in enumerate(units)
    ]
    payload = {"passage": passage_name, "reason": reason, "units": rows}
    path = debug_dir / f"{passage_name}.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _rel_source_path(path: Path, game_root: Path | None) -> str:
    """Store source_path relative to the game root (like ko_reuse records:
    ``overworld-town/...``, not ``game/overworld-town/...``) so the assembler
    can look the record up by ``game/`` + source_path."""
    if game_root is not None:
        try:
            return path.resolve().relative_to(game_root.resolve()).as_posix()
        except ValueError:
            logging.warning(
                "path %s is outside game root %s; storing as-is",
                path, game_root,
            )
    return path.as_posix()


def _pick_passage(path: Path, passage_name: str):
    data = path.read_bytes()
    source = parse_file(data, path.as_posix(), DEFAULT_VALUE_KIND_PATH)
    for passage in source.passages:
        if passage.is_opaque:
            continue
        if passage.name == passage_name:
            if {"widget", "script", "stylesheet"} & set(passage.tags):
                raise ValueError(
                    f"code passage (tags={passage.tags}) is not translatable: {passage_name}"
                )
            return passage
    raise ValueError(f"passage not found: {passage_name} in {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Translate full passages via Gemini")
    parser.add_argument("--store", type=str, default=str(DEFAULT_STORE))
    parser.add_argument("--file", type=str, default="")
    parser.add_argument("--passage-name", type=str, default="")
    parser.add_argument(
        "--passages-file", type=str, default="",
        help="JSONL of {source_path, passage_name} to translate",
    )
    parser.add_argument("--request-id", type=str, default="")
    parser.add_argument("--game-root", type=str, default="game",
                        help="game tree root for relative source_path")
    parser.add_argument("--force", action="store_true", help="re-translate even if stored")
    parser.add_argument(
        "--debug-dir", type=str, default="",
        help="dump per-unit texts of failed passages here (JSONL per passage)",
    )
    parser.add_argument(
        "--model", type=str, default="",
        help="Gemini model id (default: gemini-2.5-flash-lite)",
    )
    parser.add_argument(
        "--escalation-model", type=str, default=DEFAULT_ESCALATION_MODEL,
        help="model used to retry units that fail L1/L2 with the base model "
             "(default: gemini-2.5-flash)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=16,
        help="units per API request (1 = per-unit calls; default 16)",
    )
    parser.add_argument(
        "--journal", type=str, default="",
        help="stream one JSON line per unit result and passage outcome here "
             "(flushed per write — survives crashes; default: "
             "tmp/journals/<request_id>.jsonl)",
    )
    parser.add_argument(
        "--units-store", type=str, default="",
        help="unit-level record store (one line per chunk unit; default: "
             "work/translations/ko-units.jsonl)",
    )
    args = parser.parse_args(argv)

    if not args.passages_file and not (args.file and args.passage_name):
        parser.error("need --file+--passage-name or --passages-file")

    store_path = Path(args.store)
    game_root = Path(args.game_root)
    debug_dir = Path(args.debug_dir) if args.debug_dir else None
    # passage-level skip checks both stores: legacy ko_reuse (3-match) and
    # previously translated gemini passages (later file wins)
    records = load_translations_many([DEFAULT_LEGACY_STORE, store_path])
    request_id = args.request_id or next_request_id(records)
    if args.journal:
        journal = Path(args.journal)
    else:
        # always stream: per-unit progress survives crashes and is visible
        # in the project tmp/ folder (git-excluded)
        journal = Path("tmp/journals") / f"{request_id}.jsonl"
    units_store = Path(args.units_store) if args.units_store else Path("work/translations/ko-units.jsonl")
    units_records = load_translations(units_store) if units_store.exists() else {}
    rejected_path = Path("work/translations/assembler-rejected.jsonl")
    rejected_hashes: frozenset[str] = frozenset()
    if rejected_path.exists():
        rejected_hashes = frozenset(
            json.loads(line)["source_text_hash"]
            for line in rejected_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    if rejected_hashes:
        print(f"assembler-rejected hashes (re-translate targets): {len(rejected_hashes)}")

    targets: list[tuple[Path, str]] = []
    if args.passages_file:
        for line in Path(args.passages_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            targets.append((Path(row["source_path"]), row["passage_name"]))
    else:
        targets.append((Path(args.file), args.passage_name))

    stats = {"request_id": request_id, "translated": 0, "skipped": 0,
             "reused_units": 0, "glue_units": 0, "failed": []}
    for path, passage_name in targets:
        try:
            passage = _pick_passage(path, passage_name)
        except (ValueError, OSError) as exc:
            stats["failed"].append({"passage": passage_name, "reason": str(exc)})
            continue
        try:
            record, reason = translate_passage(
                path, passage, request_id=request_id, store_records=records,
                force=args.force, game_root=game_root, debug_dir=debug_dir,
                model=args.model or None,
                escalation_model=args.escalation_model,
                batch_size=args.batch_size,
                journal=journal,
                units_store=units_store,
                units_records=units_records,
                rejected_hashes=rejected_hashes,
            )
        except Exception as exc:
            # an unexpected failure (network/quota/... ) must not abort the
            # whole batch — record it and move to the next passage
            stats["failed"].append({"passage": passage_name, "reason": f"exception: {exc}"})
            _journal_passage(journal, path.as_posix(), passage_name,
                             "failed", f"exception: {exc}", None)
            print(f"EXCEPTION: {passage_name} ({type(exc).__name__}: {exc})")
            continue
        if record is None:
            if reason == "skipped":
                stats["skipped"] += 1
                print(f"skip (already stored): {passage_name}")
            else:
                stats["failed"].append({"passage": passage_name, "reason": reason})
                _journal_passage(journal, path.as_posix(), passage_name,
                                 "failed", reason, None)
                print(f"FAILED: {passage_name} ({reason})")
            continue
        append_record(record, store_path)
        records.setdefault(record["source_text_hash"], []).append(record)
        stats["translated"] += 1
        stats["reused_units"] += record.get("reused_units", 0)
        stats["glue_units"] += record.get("glue_units", 0)
        print(f"translated: {passage_name} ({len(record['translated_text'])} chars, "
              f"post_status={record['post_status']}, repaired={record.get('repaired', False)}, "
              f"reused_units={record.get('reused_units', 0)}, "
              f"glue_units={record.get('glue_units', 0)})")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if not stats["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
