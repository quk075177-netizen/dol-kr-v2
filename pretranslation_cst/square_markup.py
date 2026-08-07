"""Structural square-bracketed markup parser mirroring SugarCube.

Implements the lexing and parsing rules of SugarCube's
``parseSquareBracketedMarkup`` (src/markup/wikifier-util.js) for ``[[...]]``
link markup and ``[img[...]]`` image markup, instead of the single-delimiter
heuristic of the first parser draft.

The parser preserves the raw character offsets of every component:

* ``text``   -- display label (link) or alternate text (image)
* ``link``   -- link destination/target (links) or image link component
* ``source`` -- image source
* ``setter`` -- the ``][ ... ]`` setter expression

Directional delimiters behave as in SugarCube:

* ``label|target``      label is the text before the pipe
* ``label->target``     label is the text before the right arrow
* ``target<-label``     label is the text after the left arrow

The label exposure policy lives in :func:`exposed_label`: only link markup
with a delimiter exposes a static display label; dynamic labels (``$``,
``_``, backtick, ``${``, string concatenation ``+``), targets, setters and
image markup are protected.
"""

from __future__ import annotations

from dataclasses import dataclass

# Markers that make a display label dynamic and therefore not plain prose.
DYNAMIC_LABEL_MARKERS = ("$", "_", "`", "${", "+")


@dataclass(frozen=True)
class SquarePart:
    """One component of square markup with its char offsets and raw text."""

    start: int
    end: int
    text: str


@dataclass
class SquareMarkup:
    """Structural result of one square-bracketed markup element.

    Character offsets point into the source text; callers convert them to
    byte spans with their own character/byte table.
    """

    raw_start: int
    raw_end: int
    is_link: bool = False
    is_image: bool = False
    align: str | None = None
    force_internal: bool = False
    text: SquarePart | None = None
    link: SquarePart | None = None
    source: SquarePart | None = None
    setter: SquarePart | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _slurp_quote(text: str, pos: int, end: int, quote: str) -> int | None:
    """Consume a quoted string inside square markup.  Returns the position
    just past the closing quote, or None when the quote is unterminated."""
    while pos < end:
        char = text[pos]
        if char == "\\":
            pos += 1
            if pos >= end or text[pos] == "\n":
                return None
            pos += 1
            continue
        if char == "\n":
            return None
        if char == quote:
            return pos + 1
        pos += 1
    return None


class _SquareLexer:
    """State-machine lexer for one square markup element.

    Item kinds follow the SugarCube lexer: ``link_meta``, ``image_meta``,
    ``text``, ``link``, ``source``, ``setter``, ``delim_ltr``,
    ``delim_rtl``, ``inner_meta``, ``right_meta``.
    """

    def __init__(self, text: str, start: int, end: int) -> None:
        self.text = text
        self.pos = start
        self.end = end
        self.depth = 0
        self.item_start = start
        self.items: list[tuple[str, int, int]] = []
        self.delim: str | None = None  # None | "ltr" | "rtl"
        self.is_link = False
        self.is_image = False
        self.align: str | None = None
        self.error: str | None = None

    def next(self) -> str | None:
        if self.pos >= self.end:
            return None
        char = self.text[self.pos]
        self.pos += 1
        return char

    def peek(self) -> str | None:
        if self.pos >= self.end:
            return None
        return self.text[self.pos]

    def backup(self) -> None:
        self.pos -= 1

    def forward(self) -> None:
        self.pos += 1

    def emit(self, kind: str) -> None:
        self.items.append((kind, self.item_start, self.pos))
        self.item_start = self.pos


def _lex_left_meta(lexer: _SquareLexer) -> str | None:
    """Consume ``[[`` or ``[<>]?img[``.  Returns the next lexing state."""
    char = lexer.next()
    if char != "[":
        lexer.error = "malformed square-bracketed markup"
        return None
    if lexer.peek() == "[":
        lexer.forward()
        lexer.is_link = True
        lexer.emit("link_meta")
    else:
        if lexer.peek() in "<>":
            lexer.align = "left" if lexer.peek() == "<" else "right"
            lexer.forward()
        for accepted in ("Ii", "Mm", "Gg"):
            if lexer.peek() not in accepted:
                lexer.error = "malformed square-bracketed markup"
                return None
            lexer.forward()
        if lexer.peek() != "[":
            lexer.error = "malformed square-bracketed markup"
            return None
        lexer.forward()
        lexer.is_image = True
        lexer.emit("image_meta")
    lexer.depth = 2
    return "core"


def _lex_core(lexer: _SquareLexer) -> str | None:
    """Lex the link text / image source section up to ``]]`` or ``][``."""
    what = "link" if lexer.is_link else "image"
    while True:
        char = lexer.next()
        if char is None or char == "\n":
            lexer.error = f"unterminated {what} markup"
            return None
        if char == '"':
            quote_end = _slurp_quote(lexer.text, lexer.pos, lexer.end, '"')
            if quote_end is None:
                lexer.error = f"unterminated double quoted string in {what} markup"
                return None
            lexer.pos = quote_end
            continue
        if char == "|" and lexer.delim is None:
            lexer.delim = "ltr"
            lexer.backup()
            lexer.emit("text")
            lexer.forward()
            lexer.emit("delim_ltr")
            continue
        if char == "-" and lexer.delim is None and lexer.peek() == ">":
            lexer.delim = "ltr"
            lexer.backup()
            lexer.emit("text")
            lexer.forward()
            lexer.forward()
            lexer.emit("delim_ltr")
            continue
        if char == "<" and lexer.delim is None and lexer.peek() == "-":
            lexer.delim = "rtl"
            lexer.backup()
            lexer.emit("link" if lexer.is_link else "source")
            lexer.forward()
            lexer.forward()
            lexer.emit("delim_rtl")
            continue
        if char == "[":
            lexer.depth += 1
            continue
        if char == "]":
            lexer.depth -= 1
            if lexer.depth == 1:
                if lexer.peek() == "[":
                    lexer.depth += 1
                    lexer.backup()
                    if lexer.delim == "rtl":
                        lexer.emit("text")
                    else:
                        lexer.emit("link" if lexer.is_link else "source")
                    lexer.forward()
                    lexer.forward()
                    lexer.emit("inner_meta")
                    return "image_link" if lexer.is_image else "setter"
                if lexer.peek() == "]":
                    lexer.depth -= 1
                    lexer.backup()
                    if lexer.delim == "rtl":
                        lexer.emit("text")
                    else:
                        lexer.emit("link" if lexer.is_link else "source")
                    lexer.forward()
                    lexer.forward()
                    lexer.emit("right_meta")
                    return None
                lexer.error = f"malformed {what} markup"
                return None
    return None


def _lex_image_link(lexer: _SquareLexer) -> str | None:
    """Lex the image link component after ``][``."""
    while True:
        char = lexer.next()
        if char is None or char == "\n":
            lexer.error = "unterminated image markup"
            return None
        if char == '"':
            quote_end = _slurp_quote(lexer.text, lexer.pos, lexer.end, '"')
            if quote_end is None:
                lexer.error = "unterminated double quoted string in image markup link component"
                return None
            lexer.pos = quote_end
            continue
        if char == "[":
            lexer.depth += 1
            continue
        if char == "]":
            lexer.depth -= 1
            if lexer.depth == 1:
                if lexer.peek() == "[":
                    lexer.depth += 1
                    lexer.backup()
                    lexer.emit("link")
                    lexer.forward()
                    lexer.forward()
                    lexer.emit("inner_meta")
                    return "setter"
                if lexer.peek() == "]":
                    lexer.depth -= 1
                    lexer.backup()
                    lexer.emit("link")
                    lexer.forward()
                    lexer.forward()
                    lexer.emit("right_meta")
                    return None
                lexer.error = "malformed image markup"
                return None
    return None


def _lex_setter(lexer: _SquareLexer) -> None:
    """Lex the setter expression after ``][``."""
    what = "link" if lexer.is_link else "image"
    while True:
        char = lexer.next()
        if char is None or char == "\n":
            lexer.error = f"unterminated {what} markup"
            return
        if char in "\"'":
            quote_end = _slurp_quote(lexer.text, lexer.pos, lexer.end, char)
            if quote_end is None:
                lexer.error = f"unterminated {char} quoted string in {what} markup setter component"
                return
            lexer.pos = quote_end
            continue
        if char == "[":
            lexer.depth += 1
            continue
        if char == "]":
            lexer.depth -= 1
            if lexer.depth == 1:
                if lexer.peek() != "]":
                    lexer.error = f"malformed {what} markup"
                    return
                lexer.depth -= 1
                lexer.backup()
                lexer.emit("setter")
                lexer.forward()
                lexer.forward()
                lexer.emit("right_meta")
                return


_STATES = {
    "core": _lex_core,
    "image_link": _lex_image_link,
    "setter": _lex_setter,
}


def parse_square_markup(text: str, start: int, end: int) -> SquareMarkup:
    """Parse one square-bracketed markup element at ``text[start:end]``.

    ``start`` must point at the opening ``[``.  Component spans are returned
    as raw character offsets into ``text``.
    """
    lexer = _SquareLexer(text, start, end)
    state = _lex_left_meta(lexer)
    while state is not None and lexer.error is None:
        state = _STATES[state](lexer)
    markup = SquareMarkup(raw_start=start, raw_end=end, error=lexer.error)
    if lexer.error is not None:
        return markup
    markup.is_link = lexer.is_link
    markup.is_image = lexer.is_image
    markup.align = lexer.align
    for kind, item_start, item_end in lexer.items:
        raw = text[item_start:item_end]
        trimmed = raw.strip()
        if kind == "text":
            markup.text = SquarePart(item_start, item_end, raw)
        elif kind == "link":
            if trimmed.startswith("~"):
                markup.force_internal = True
            markup.link = SquarePart(item_start, item_end, raw)
        elif kind == "source":
            markup.source = SquarePart(item_start, item_end, raw)
        elif kind == "setter":
            markup.setter = SquarePart(item_start, item_end, raw)
    return markup


def exposed_label(markup: SquareMarkup) -> SquarePart | None:
    """Return the display label when it is safe to translate as plain prose.

    The policy mirrors the documented exposure contract: only link markup
    with a delimiter exposes a static display label.  Dynamic labels,
    targets, setters and image markup are protected.
    """
    if markup.error is not None or not markup.is_link or markup.text is None:
        return None
    label = markup.text.text
    if not label or any(marker in label for marker in DYNAMIC_LABEL_MARKERS):
        return None
    return markup.text
