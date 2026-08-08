"""Translate full passages via Gemini and store passage-level records.

Completes the reuse design R2/R4 (docs/translation-reuse-design.md): a
passage is chunked into units, every unit is translated with the existing
retry/preservation logic, the units are restored into a full translated
body, the body is skeleton-verified with our own parser, and a
``level="passage"`` record (source=gemini) is appended to the store the
assembler reads.

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
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pretranslation_cst.chunking import chunk_passage
from pretranslation_cst.masking import mask_passage
from pretranslation_cst.parser import parse_file
from pretranslation_cst.paths import DEFAULT_VALUE_KIND_PATH
from translation.client import TranslatedUnit, translate_unit, verify_placeholders
from translation.post import post_process, remaining_dynamic_markers
from translation.store import (
    append_record,
    find_passage_reuse,
    load_translations,
    passage_placeholder_signature,
    source_hash,
)

DEFAULT_STORE = Path("work/translations/ko-reuse.jsonl")


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
    the source.  A mismatch means the translation broke the structure."""
    try:
        synthetic = f":: {passage_name}\n\n".encode("utf-8") + translated_body
        source = parse_file(synthetic, source_path, DEFAULT_VALUE_KIND_PATH)
        passage = next((p for p in source.passages if p.name == passage_name), None)
        if passage is None:
            return False
        ko_artifact = mask_passage(synthetic, passage)
    except Exception:
        return False
    return passage_placeholder_signature(source_artifact) == passage_placeholder_signature(ko_artifact)


_PLACEHOLDER_RE = re.compile(r"<0\d{6}>")


def _placeholder_only_gap(text: str, start: int) -> bool:
    """True when the text after ``start`` is whitespace up to the next
    placeholder token (i.e. the two protected spans are line-separated)."""
    match = _PLACEHOLDER_RE.search(text, start)
    if match is None:
        return False
    return not text[start : match.start()].strip()


def verify_separator_newlines(artifact, joined: str) -> list[str]:
    """Find placeholders whose whitespace separator (the only thing between
    them and the next protected span) was dropped in the joined translated
    text.  Such merges break the parser signature even though every
    placeholder survived.  Runs on the JOINED text so unit boundaries are
    covered."""
    problems: list[str] = []
    masked = artifact.masked_text
    for placeholder in artifact.placeholders:
        token = placeholder.placeholder
        m_idx = masked.find(token)
        t_idx = joined.find(token)
        if m_idx < 0 or t_idx < 0:
            continue  # placeholder drop is handled elsewhere
        after = m_idx + len(token)
        m_sep = masked[after] if after < len(masked) else ""
        t_after_pos = t_idx + len(token)
        t_sep = joined[t_after_pos] if t_after_pos < len(joined) else ""
        if m_sep.isspace() and _placeholder_only_gap(masked, after) and not t_sep.isspace():
            problems.append(token)
    return problems


def repair_separator_newlines(artifact, joined: str) -> str:
    """Deterministically restore the dropped whitespace separators.  The
    masked reference guarantees only whitespace sat between the two protected
    spans, so re-inserting the original separator right after the placeholder
    reproduces the original structure exactly."""
    masked = artifact.masked_text
    out: list[str] = []
    cursor = 0
    for placeholder in artifact.placeholders:
        token = placeholder.placeholder
        idx = joined.find(token, cursor)
        if idx < 0:
            return joined  # missing placeholder — restore will raise loudly
        out.append(joined[cursor : idx + len(token)])
        after = idx + len(token)
        m_idx = masked.find(token)
        m_after_pos = m_idx + len(token)
        m_sep = masked[m_after_pos] if m_after_pos < len(masked) else ""
        t_sep = joined[after : after + 1]
        if (
            m_sep.isspace()
            and _placeholder_only_gap(masked, m_after_pos)
            and not t_sep.isspace()
        ):
            out.append(m_sep)
        cursor = after
    out.append(joined[cursor:])
    return "".join(out)


def restore_joined(artifact, joined: str) -> bytes:
    """Substitute placeholders in order in a joined translated text."""
    for placeholder in artifact.placeholders:
        occurrences = joined.count(placeholder.placeholder)
        if occurrences != 1:
            raise ValueError(
                f"placeholder {placeholder.placeholder} occurs {occurrences} times"
            )
        joined = joined.replace(placeholder.placeholder, placeholder.original_text, 1)
    return joined.encode("utf-8")


def translate_passage(
    path: Path,
    passage,
    *,
    request_id: str,
    store_records: dict[str, list[dict]],
    force: bool = False,
    game_root: Path | None = None,
) -> tuple[dict | None, str]:
    """Translate one passage fully.  Returns (record, reason): record is
    None when the passage was skipped (reason="skipped") or failed
    (reason describes the failure step)."""
    data = path.read_bytes()
    artifact = mask_passage(data, passage)
    source_path = _rel_source_path(path, game_root)
    body_text = data[passage.body_span.start:passage.body_span.end].decode("utf-8")
    if not force and find_passage_reuse(body_text, store_records) is not None:
        return None, "skipped"  # already translated

    units = chunk_passage(passage, artifact, data)
    translated_units: list[TranslatedUnit] = []
    for index, unit in enumerate(units):
        tu = translate_unit(unit, index, len(units))
        if verify_placeholders(unit, tu.translated_text):
            return None, "placeholder_drop"
        tu.translated_text = post_process(tu.translated_text)
        translated_units.append(tu)

    joined = "".join(tu.translated_text for tu in translated_units)
    joined = repair_separator_newlines(artifact, joined)
    try:
        restored = restore_joined(artifact, joined)
    except ValueError:
        return None, "restore_failed"
    translated_text = restored.decode("utf-8")

    if not _skeleton_ok(artifact, restored, passage.name, artifact.source_path):
        return None, "skeleton_mismatch"

    markers = remaining_dynamic_markers(translated_text)
    record = {
        "record_id": f"tr_{source_hash(body_text)[:12]}_gemini",
        "source_text_hash": source_hash(body_text),
        "source_text": body_text,
        "translated_text": translated_text,
        "source_path": source_path,
        "passage_name": passage.name,
        "unit_id": f"{source_path}:{passage.name}",
        "request_id": request_id,
        "model": "gemini-2.5-flash-lite",
        "temperature": 0.7,
        "created_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds"),
        "placeholder_ok": True,
        "post_status": "runtime_remaining" if markers else "static_done",
        "source": "gemini",
        "level": "passage",
    }
    return record, "ok"


def _rel_source_path(path: Path, game_root: Path | None) -> str:
    """Store source_path relative to the game root (like ko_reuse records:
    ``overworld-town/...``, not ``game/overworld-town/...``) so the assembler
    can look the record up by ``game/`` + source_path."""
    if game_root is not None:
        try:
            return path.resolve().relative_to(game_root.resolve()).as_posix()
        except ValueError:
            pass
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
    args = parser.parse_args(argv)

    if not args.passages_file and not (args.file and args.passage_name):
        parser.error("need --file+--passage-name or --passages-file")

    store_path = Path(args.store)
    game_root = Path(args.game_root)
    records = load_translations(store_path)
    request_id = args.request_id or next_request_id(records)

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

    stats = {"request_id": request_id, "translated": 0, "skipped": 0, "failed": []}
    for path, passage_name in targets:
        try:
            passage = _pick_passage(path, passage_name)
        except (ValueError, OSError) as exc:
            stats["failed"].append({"passage": passage_name, "reason": str(exc)})
            continue
        record, reason = translate_passage(
            path, passage, request_id=request_id, store_records=records,
            force=args.force, game_root=game_root,
        )
        if record is None:
            if reason == "skipped":
                stats["skipped"] += 1
                print(f"skip (already stored): {passage_name}")
            else:
                stats["failed"].append({"passage": passage_name, "reason": reason})
                print(f"FAILED: {passage_name} ({reason})")
            continue
        append_record(record, store_path)
        records.setdefault(record["source_text_hash"], []).append(record)
        stats["translated"] += 1
        print(f"translated: {passage_name} ({len(record['translated_text'])} chars, "
              f"post_status={record['post_status']})")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if not stats["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
