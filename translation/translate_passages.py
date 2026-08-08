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
    verify_placeholders,
)
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

# malformed {{post:...}} markers: closing brace missing, or closed with a
# single '}' (e.g. "{{post:이가}" — the LLM typo'd the marker)
_MALFORMED_POST_RE = re.compile(r"\{\{post:[^}]*$|" r"\{\{post:[^}]*\}(?!\})")


def verify_malformed_post_markers(text: str) -> list[str]:
    """Detect structurally broken ``{{post:...}}`` markers in translated text
    (unclosed or single-brace closed).  They are not placeholders, so the
    placeholder/skeleton checks never see them."""
    return [match.group(0) for match in _MALFORMED_POST_RE.finditer(text)]


def _separator_gap(text: str, start: int) -> str | None:
    """The whitespace-only gap between a placeholder (ending at ``start``)
    and the next placeholder token, or None when the gap contains non-
    whitespace (or there is no next placeholder)."""
    match = _PLACEHOLDER_RE.search(text, start)
    if match is None:
        return None
    gap = text[start : match.start()]
    if not gap.strip():
        return gap
    return None


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
    for placeholder in artifact.placeholders:
        token = placeholder.placeholder
        m_idx = masked.find(token)
        t_idx = joined.find(token)
        if m_idx < 0 or t_idx < 0:
            continue  # placeholder drop is handled elsewhere
        m_gap = _separator_gap(masked, m_idx + len(token))
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
    reproduces the original structure and rendering exactly."""
    masked = artifact.masked_text
    out: list[str] = []
    cursor = 0
    for placeholder in artifact.placeholders:
        token = placeholder.placeholder
        idx = joined.find(token, cursor)
        if idx < 0:
            return joined  # missing placeholder — restore will raise loudly
        after = idx + len(token)
        m_idx = masked.find(token)
        m_gap = _separator_gap(masked, m_idx + len(token))
        if m_gap is not None:
            t_gap = _leading_whitespace(joined, after)
            if t_gap != m_gap:
                out.append(joined[cursor:after])
                out.append(m_gap)
                cursor = after + len(t_gap)
                continue
        out.append(joined[cursor : idx + len(token)])
        cursor = after
    out.append(joined[cursor:])
    return "".join(out)


def translate_passage(
    path: Path,
    passage,
    *,
    request_id: str,
    store_records: dict[str, list[dict]],
    force: bool = False,
    game_root: Path | None = None,
    debug_dir: Path | None = None,
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
            _dump_failure(debug_dir, passage.name, "placeholder_drop", units,
                          [tu.translated_text if i == index else None for i in range(len(units))])
            return None, "placeholder_drop"
        tu.translated_text = post_process(tu.translated_text)
        translated_units.append(tu)

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

    if not _skeleton_ok(artifact, restored, passage.name, artifact.source_path):
        _dump_failure(debug_dir, passage.name, "skeleton_mismatch", units,
                      [tu.translated_text for tu in translated_units])
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
        "repaired": repaired,
    }
    return record, "ok"


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
    args = parser.parse_args(argv)

    if not args.passages_file and not (args.file and args.passage_name):
        parser.error("need --file+--passage-name or --passages-file")

    store_path = Path(args.store)
    game_root = Path(args.game_root)
    debug_dir = Path(args.debug_dir) if args.debug_dir else None
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
        try:
            record, reason = translate_passage(
                path, passage, request_id=request_id, store_records=records,
                force=args.force, game_root=game_root, debug_dir=debug_dir,
            )
        except Exception as exc:
            # an unexpected failure (network/quota/... ) must not abort the
            # whole batch — record it and move to the next passage
            stats["failed"].append({"passage": passage_name, "reason": f"exception: {exc}"})
            print(f"EXCEPTION: {passage_name} ({type(exc).__name__}: {exc})")
            continue
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
              f"post_status={record['post_status']}, repaired={record.get('repaired', False)})")

    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0 if not stats["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
