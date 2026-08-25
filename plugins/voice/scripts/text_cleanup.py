"""Markdown cleanup for the speak path (R6, R7; KTD10).

Strips formatting syntax so it is not spoken aloud (R6) and omits fenced
code blocks contents-and-fences (R7). Fenced blocks go first — backtick
and tilde fences alike — and then a small line-and-regex pass removes
heading markers, emphasis and strong markers, list and blockquote
markers, horizontal rules, link syntax (the link text stays, the URL
goes), inline-code backticks (the span text stays), and table pipes.

This is a line-and-regex pass, not a Markdown parser: fidelity beyond
those tested classes is explicitly not a version-one goal. There is no
length gate of any kind in the pass (R5) — no sentence parsing, no
shortening — so a long input comes back whole.
"""

from __future__ import annotations

import re

__all__ = ["clean"]

#: A fence opener: up to three leading spaces, then three or more backticks
#: or tildes. Fences are removed contents-and-fences before any other pass
#: runs, so formatting syntax inside code never reaches speech (R7).
_FENCE_OPEN = re.compile(r"^\s{0,3}(`{3,}|~{3,})")

#: A line made only of three or more of one horizontal-rule character.
_HORIZONTAL_RULE = re.compile(r"^\s{0,3}(-{3,}|\*{3,}|_{3,})\s*$")

#: Leading blockquote markers, one level or several.
_BLOCKQUOTE = re.compile(r"^\s{0,3}(?:>\s*)+")

#: ATX heading markers, which require a space after the hashes.
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+")

#: Unordered ``-`` / ``+`` / ``*`` and ordered ``1.`` / ``1)`` markers.
_LIST_MARKER = re.compile(r"^\s{0,3}(?:[-+*]|\d{1,9}[.)])\s+")

#: Image and link syntax: keep the text, drop the URL.
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")

#: Inline code spans: keep the span text, drop the backticks.
_INLINE_CODE = re.compile(r"`([^`]*)`")

#: Emphasis and strong markers, paired. The underscore forms are guarded by
#: word edges so identifiers such as ``snake_case`` survive the pass.
_STRONG_STAR = re.compile(r"\*\*([^*]+)\*\*")
_STRONG_UNDERSCORE = re.compile(r"__([^_]+)__")
_EMPHASIS_STAR = re.compile(r"\*([^*]+)\*")
_EMPHASIS_UNDERSCORE = re.compile(r"(?<!\w)_([^_]+)_(?!\w)")

_WHITESPACE_RUN = re.compile(r"[ \t]+")


def clean(text: str) -> str:
    """Return the text with spoken Markdown formatting removed.

    Fenced code blocks are omitted entirely (R7), formatting markers are
    stripped (R6), and the result is returned whole: no length gate, no
    sentence parsing, and no shortening exists anywhere in this pass (R5).
    """
    if not text:
        return ""
    lines = _drop_fenced_blocks(text.splitlines())
    stripped = (_strip_line(line) for line in lines)
    return "\n".join(line for line in stripped if line.strip())


def _drop_fenced_blocks(lines: list[str]) -> list[str]:
    """Omit every fenced code block, contents and fences alike.

    A fence opens on a line starting with three or more backticks or
    tildes and closes on the next line starting with three or more of the
    same character. An unclosed fence omits everything to the end.
    """
    kept: list[str] = []
    fence_char: str | None = None
    for line in lines:
        if fence_char is None:
            match = _FENCE_OPEN.match(line)
            if match is not None:
                fence_char = match.group(1)[0]
                continue
            kept.append(line)
        elif line.strip().startswith(fence_char * 3):
            fence_char = None
    return kept


def _strip_line(line: str) -> str:
    """Strip the formatting markers from one non-fenced line."""
    if _HORIZONTAL_RULE.match(line):
        return ""
    if _is_table_separator(line):
        return ""
    # Blockquote first, so a quoted heading or list keeps its inner strip:
    # ``> # Heading`` is a blockquote, then a heading, then plain text.
    line = _BLOCKQUOTE.sub("", line, count=1)
    line = _HEADING.sub("", line, count=1)
    line = _LIST_MARKER.sub("", line, count=1)
    line = _IMAGE.sub(r"\1", line)
    line = _LINK.sub(r"\1", line)
    line = _INLINE_CODE.sub(r"\1", line)
    line = line.replace("`", "")
    line = _STRONG_STAR.sub(r"\1", line)
    line = _STRONG_UNDERSCORE.sub(r"\1", line)
    line = _EMPHASIS_STAR.sub(r"\1", line)
    line = _EMPHASIS_UNDERSCORE.sub(r"\1", line)
    line = line.replace("|", " ")
    line = _WHITESPACE_RUN.sub(" ", line)
    return line.strip()


def _is_table_separator(line: str) -> bool:
    """True for a table separator row such as ``| --- | --- |``.

    The pipes-only pass would leave the separator's dashes behind, so the
    row is dropped outright: it carries no words to speak.
    """
    stripped = line.strip()
    if not stripped:
        return False
    characters = set(stripped)
    return (
        characters <= set("|-: ")
        and "-" in characters
        and "|" in characters
    )
