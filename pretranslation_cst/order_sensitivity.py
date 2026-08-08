"""Order-sensitivity classification for protected spans (Option E).

A protected span whose macro is a pure display value — a pronoun, a name
reference, a body-part display, a variable interpolation, an HTML tag or a
backtick expression — renders the same value no matter where in the
sentence it appears.  The model may therefore move such tokens when it
naturalises Korean word order (clause fronting etc.); the translation stays
functionally identical after restore.

State/control macros (``<<set>>``, ``<<run>>``, ``<<if>>``, ``<<link>>``,
…) are order-sensitive: moving them changes game logic or UI flow.

Conservative whitelist: ONLY the kinds and macros listed here are treated
as order-insensitive; every unlisted macro defaults to sensitive.  A
span is insensitive iff ALL of its kinds are insensitive (a merged span
like ``<<set $x to 1>><<he>>`` must stay sensitive).  Extend the lists
only for reorders of macros verified to be display-only.

See reorder-analysis.md §7 for the design and impact scope.
"""

from __future__ import annotations

# non-macro kinds whose rendering never depends on position
KIND_INSENSITIVE = frozenset({"variable", "expression", "html", "comment"})

# macros verified display-only: SugarCube display builtins plus game
# pronoun/name/body-part references (observed in the reorder cases and
# checked by hand).  Widget-family names (childhe, person1, ...) are the
# game's dynamic pronoun/name refs.
MACRO_INSENSITIVE = frozenset({
    # SugarCube display builtins
    "print",
    "=",
    # game pronoun / name / body-part display macros
    "he", "his", "him", "she", "her", "hers", "their", "they", "them",
    "it", "its", "herself", "himself", "themselves",
    "childhe", "childhim", "childhis", "childname", "childherself",
    "person1", "penis",
})


def is_order_insensitive(kinds: frozenset[str]) -> bool:
    """True when every kind in the span is display-only.

    ``kinds`` is the union of everything a protected span covers, so a
    single state macro anywhere in the span makes it sensitive.
    """
    if not kinds:
        return False
    return all(
        kind in KIND_INSENSITIVE or kind.lower() in MACRO_INSENSITIVE
        for kind in kinds
    )
