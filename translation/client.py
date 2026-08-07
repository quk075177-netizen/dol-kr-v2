"""Pilot translation of translate units via Vertex AI Gemini.

Uses the Google Cloud Vertex AI SDK with Application Default Credentials.

The pipeline is:

    parse_file -> mask_passage -> chunk_passage -> TranslateUnit
        -> prompt (placeholder rules + structure hints)
        -> Gemini generateContent
        -> translated unit (placeholders preserved verbatim)
        -> restore_mask on the joined translated text

The placeholder tokens (``__DOLKR_P000000__``) are the only contract with the
model: they must survive translation byte-for-byte, since restore relies on
them.  Everything else (prose, link labels, macro arguments) may be
translated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import vertexai
from vertexai.generative_models import Content, GenerativeModel, Part

from pretranslation_cst.chunking import TranslateUnit
from pretranslation_cst.model import MaskArtifact, Placeholder

PLACEHOLDER_RE = re.compile(r"__DOLKR_P\d{6}__")


def _strip_placeholders(text: str) -> str:
    """Remove placeholder tokens from context strings so the model never
    echoes a neighbouring unit's placeholder into its own output."""
    return PLACEHOLDER_RE.sub("", text)

DEFAULT_LOCATION = "us-central1"
DEFAULT_MODEL = "gemini-2.5-flash-lite"
PROJECT_ID = "adept-elevator-503122-h0"

_model: GenerativeModel | None = None


def _get_model(
    *,
    project: str = PROJECT_ID,
    location: str = DEFAULT_LOCATION,
    model: str = DEFAULT_MODEL,
) -> GenerativeModel:
    """Initialise the Vertex AI SDK once and return the Gemini model."""
    global _model
    if _model is None:
        vertexai.init(project=project, location=location)
        _model = GenerativeModel(model)
    return _model


SYSTEM_PROMPT = """You are translating a game's text (English) into natural Korean.

The text contains placeholder tokens like __DOLKR_P000000__. These are NOT
text to translate. They stand for game markup (macros, links, formatting)
that must be reinserted verbatim. Rules:

1. Keep every placeholder token EXACTLY as written: __DOLKR_P000000__ stays
   __DOLKR_P000000__. Never add, remove, reorder, or modify a token.
2. Translate the visible prose around the tokens into natural Korean.
3. Do not translate content that is marked as UI/button text into a long
   sentence; keep it short like a button label.
4. Preserve line breaks and indentation exactly as given.
5. Output ONLY the translated text. No explanations, no quotes around it.
6. If a line contains only placeholders, keep it exactly as-is.
7. If a line contains both placeholders and prose, translate the prose and
   keep every placeholder in the same position and line.
8. Never merge, drop, or reorder lines: the output must have the same line
   count and the same placeholder multiset as the input.

Structure hints (optional context):
- ancestor: the SugarCube container this text lives in (if/elseif/switch...)
- preceding/following context: neighbouring text for tone/tense reference
  (not part of this unit, do NOT translate them)
"""


def _generate(
    contents: list[dict[str, Any]],
    *,
    project: str = PROJECT_ID,
    location: str = DEFAULT_LOCATION,
    model: str = DEFAULT_MODEL,
) -> str:
    model_obj = _get_model(project=project, location=location, model=model)
    request_contents = [
        Content(role=item.get("role", "user"), parts=[Part.from_text(item["parts"][0]["text"])])
        for item in contents
    ]
    response = model_obj.generate_content(request_contents)
    if not response.candidates:
        raise RuntimeError(f"no candidates: {response}")
    return "".join(part.text or "" for part in response.candidates[0].content.parts)


@dataclass
class TranslatedUnit:
    """One translate unit plus its model output."""

    unit: TranslateUnit
    translated_text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit.unit_id,
            "source_path": self.unit.source_path,
            "passage_name": self.unit.passage_name,
            "unit_index": self.unit.unit_index,
            "unit_count": self.unit.unit_count,
            "translated_text": self.translated_text,
            "char_count": len(self.translated_text),
        }


def build_prompt(unit: TranslateUnit, index: int, total: int) -> list[dict[str, Any]]:
    """Build Gemini contents for one translate unit."""
    context_lines: list[str] = []
    if unit.ancestors:
        context_lines.append(f"ancestors: {json.dumps(unit.ancestors, ensure_ascii=False)}")
    if unit.preceding_context:
        context_lines.append(f"preceding_context: {_strip_placeholders(unit.preceding_context)[:120]!r}")
    if unit.following_context:
        context_lines.append(f"following_context: {_strip_placeholders(unit.following_context)[:120]!r}")
    hint = "\n".join(context_lines)
    user_text = (
        f"Unit {index + 1}/{total} of passage \"{unit.passage_name}\" "
        f"({unit.source_path}).\n"
        + (f"\n{hint}\n" if hint else "\n")
        + "\n--- TRANSLATE THIS ---\n"
        + unit.masked_text
    )
    return [
        {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_text}]},
    ]


def translate_unit(unit: TranslateUnit, index: int = 0, total: int = 1, max_retries: int = 3) -> TranslatedUnit:
    """Translate one unit, retrying when the model drops/duplicates placeholders."""
    last_text = ""
    n_placeholders = len(unit.placeholders)
    for attempt in range(max_retries + 1):
        contents = build_prompt(unit, index, total)
        if attempt > 0:
            # Re-emphasise preservation on retries, especially for
            # placeholder-dense units where the model tends to compress.
            extra = (
                f"\nIMPORTANT: this unit has exactly {n_placeholders} placeholder"
                f" tokens. Your previous attempt dropped or duplicated some.\n"
                f"Count them as you go and keep ALL {n_placeholders} tokens exactly once."
            )
            contents[0]["parts"][0]["text"] += extra
        text = _generate(contents)
        last_text = text
        if not verify_placeholders(unit, text):
            return TranslatedUnit(unit=unit, translated_text=text)
    return TranslatedUnit(unit=unit, translated_text=last_text)


def verify_placeholders(unit: TranslateUnit, translated: str) -> list[str]:
    """Check that every placeholder survived the translation exactly once."""
    problems: list[str] = []
    for placeholder in unit.placeholders:
        occurrences = translated.count(placeholder.placeholder)
        if occurrences != 1:
            problems.append(
                f"{placeholder.placeholder}: expected 1 occurrence, got {occurrences}"
            )
    return problems


def restore_translated(artifact: MaskArtifact, translated_units: list[TranslatedUnit]) -> bytes:
    """Reassemble the translated passage and restore placeholders to original
    bytes.  Returns the final translated file passage bytes.

    The joined translated text is a drop-in for the original masked text, so
    ``restore_mask``-style substitution works on the whole passage.
    """
    joined = "".join(tu.translated_text for tu in translated_units)
    # substitute placeholders in order (each must occur exactly once)
    for placeholder in artifact.placeholders:
        occurrences = joined.count(placeholder.placeholder)
        if occurrences != 1:
            raise ValueError(
                f"placeholder {placeholder.placeholder} occurs {occurrences} times in joined text"
            )
        joined = joined.replace(placeholder.placeholder, placeholder.original_text, 1)
    return joined.encode("utf-8")


def find_untranslated_placeholders(artifact: MaskArtifact, translated: str) -> list[Placeholder]:
    """Placeholders that appear in the joined translated text (restore failed
    to consume them, e.g. model dropped a token)."""
    remaining: list[Placeholder] = []
    for placeholder in artifact.placeholders:
        if placeholder.placeholder in translated:
            remaining.append(placeholder)
    return remaining