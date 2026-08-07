"""Post(particle) handling for translated text.

Two jobs:

1. Normalize the ad-hoc particle markers the LLM emits (``이(가)``,
   ``을(를)`` …) and the legacy KO markers (``【은는】`` …) into a standard
   ``{{post:이가}}`` form.
2. Statically resolve markers whose preceding value is a fixed string
   (post known at build time); leave ``{{post:...}}`` for runtime values
   (``$var``, ``<<macro>>``, backtick) for the in-game particle helper.

Post numbers follow dol-kr ``getPostNum``: 0 = 받침O, 1 = 받침X,
2 = ㄹ받침, None = undetermined (latin/digit-unknown/empty).
"""

from __future__ import annotations

import re

# (표준 마커 이름, 받침O, 받침X, ㄹ받침)
POST_TABLE: dict[str, tuple[str, str, str]] = {
    "은는": ("은", "는", "은"),
    "이가": ("이", "가", "이"),
    "을를": ("을", "를", "을"),
    "와과": ("과", "와", "과"),
    "으로로": ("으", "로", "로"),
    "이었였": ("이었", "였", "이었"),
    "이네이구나": ("이네", "이구나", "이네"),
    "이다": ("이다", "다", "이다"),
    "아야": ("아", "야", "아"),
}

# LLM이 생성하는 비정형 표기 → 표준 마커 이름
ADHOC_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"은\(는\)"), "은는"),
    (re.compile(r"이\(가\)"), "이가"),
    (re.compile(r"을\(를\)"), "을를"),
    (re.compile(r"과\(와\)"), "와과"),
    (re.compile(r"으로\(로\)"), "으로로"),
    (re.compile(r"이었\(였\)"), "이었였"),
]

# legacy KO HTML markers 【은는】 → 표준 마커 이름
LEGACY_MARKER_NAMES: dict[str, str] = {
    "은는": "은는",
    "이가": "이가",
    "을를": "을를",
    "와과": "와과",
    "과와": "와과",
    "으로로": "으로로",
    "로로": "으로로",
    "이": "이다",
    "아야": "아야",
    "이었였": "이었였",
    "였": "이었였",
}
LEGACY_MARKER_RE = re.compile(r"【([^】]+)】")

RUNTIME_RE = re.compile(r"[\$_`<]")
STANDARD_MARKER_RE = re.compile(r"\{\{post:([^}]+)\}\}")


def get_post_num(text: str) -> int | None:
    """0=받침O, 1=받침X, 2=ㄹ받침, None=미정."""
    if not text:
        return None
    ch = text[-1]
    code = ord(ch)
    if 0xAC00 <= code <= 0xD7A3:
        jong = (code - 0xAC00) % 28
        if jong == 0:
            return 1
        if jong == 8:
            return 2
        return 0
    if ch.isdigit():
        return [0, 2, 1, 0, 1, 1, 0, 2, 2, 0][int(ch)]
    return None


def normalize_markers(text: str) -> str:
    """Convert ad-hoc LLM markers and legacy KO markers to {{post:...}}."""
    for pattern, name in ADHOC_PATTERNS:
        text = pattern.sub("{{post:%s}}" % name, text)

    def legacy_replace(match: re.Match) -> str:
        name = LEGACY_MARKER_NAMES.get(match.group(1))
        return "{{post:%s}}" % name if name else match.group(0)

    return LEGACY_MARKER_RE.sub(legacy_replace, text)


def _post_particle(name: str, post: int | None) -> str:
    """Pick the particle for a marker name given a post number."""
    forms = POST_TABLE.get(name)
    if forms is None:
        return ""
    # None(미정) → 받침X(1) 기본 (ko-marker 규칙)
    index = post if post is not None else 1
    return forms[index]


def resolve_static(text: str) -> str:
    """Resolve markers whose preceding value is a fixed string.

    A marker is dynamic (kept as {{post:...}}) when the text right before it
    ends with a runtime token ($, _, <, `) or when it starts the string.
    """
    def replace(match: re.Match) -> str:
        name = match.group(1)
        before = text[: match.start()]
        if RUNTIME_RE.search(before) or not before:
            return match.group(0)  # keep for runtime
        # strip trailing whitespace to inspect the value
        value = before.rstrip()
        post = get_post_num(value)
        return _post_particle(name, post)

    return STANDARD_MARKER_RE.sub(replace, text)


def remaining_dynamic_markers(text: str) -> list[str]:
    """Standard markers that still need runtime resolution."""
    return list(dict.fromkeys(STANDARD_MARKER_RE.findall(text)))