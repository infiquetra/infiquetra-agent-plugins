"""Pure terminal-composer inspection for the agent-launcher reuse guard.

The launcher owns the Herdr read and the decision to prompt.  This module owns only the
presentation problem: find the input box in one ANSI viewport and classify its contents without
persisting those contents.  Keeping that parser separate prevents terminal heuristics from growing
inside the session lifecycle code.  The accepted ambiguity is recorded in
``docs/engineering-journal/DECISIONS.md#907-styled-composer-trade``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

# The OSC branch's body excludes ESC as well as BEL. An OSC body may not contain either, and
# without the exclusion an unterminated OSC start scanned to the end of the viewport and back
# once per start -- a clean quadratic, 18.9 seconds at 8000 repeats -- while the herdr read
# timeout bounded nothing in-process (issue 907 terminal review F12).
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))")
SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")

# This is a complete roster, not a fallback table.  A vendor whose input box has not been
# characterised is present with ``None`` and receives an explicit unsupported-vendor result.
# The launcher asserts these keys against its own vendor roster at import time.  Checked-in
# pane captures exist only for Claude and Codex (tests/fixtures/composer-panes.json, which
# also carries two live idle Claude captures); Grok, Agy and Qwen have characterised markers
# but no checked-in capture.
COMPOSER_GLYPH_BY_VENDOR: dict[str, str | None] = {
    "claude": "❯",
    "codex": "›",
    "grok": "❯",
    "agy": ">",
    "qwen": ">",
    # No stable composer marker was present in the 2026-08-30 live captures.  Muse could not be
    # launched through the wrapper on that host, and OpenCode presented no composer marker.
    "muse": None,
    "opencode": None,
}

COMPOSER_MARKERS = frozenset(glyph for glyph in COMPOSER_GLYPH_BY_VENDOR.values() if glyph)

# A border may precede the prompt glyph.  These are structural terminal characters, not content.
_LEADING_BORDER_GLYPHS = frozenset("│┃┆┇┊┋╎╏▏▎▍▌▋▊▉█╭╰┌└")
_TRAILING_BORDER_GLYPHS = frozenset("│┃┆┇┊┋╎╏▏▎▍▌▋▊▉█╮╯┐┘")
_HORIZONTAL_RULE_GLYPHS = frozenset("─━═▄▀ ")


class ComposerState(StrEnum):
    """Mutually exclusive outcomes from a successful or unsupported composer parse."""

    EMPTY = "empty"
    STAGED = "staged"
    UNCLASSIFIABLE = "unclassifiable"
    NOT_FOUND = "not_found"
    UNSUPPORTED_VENDOR = "unsupported_vendor"
    READ_FAILED = "read_failed"
    READ_TIMEOUT = "read_timeout"


class _RowClass(StrEnum):
    """One class per physical row; the whole row rule lives in ``_classify_row``."""

    MARKER = "marker"
    BLANK = "blank"
    RULE = "rule"
    BORDERED = "bordered"
    INDENTED = "indented"
    TERMINATOR = "terminator"


@dataclass(frozen=True)
class ComposerInspection:
    """A composer outcome and withheld text only when the outcome is staged."""

    state: ComposerState
    text: str | None = None


@dataclass
class _StyleState:
    """The Select Graphic Rendition attributes that make a run client-drawn."""

    intensity: bool = False
    italic: bool = False
    underline: bool = False
    blink: bool = False
    inverse: bool = False
    conceal: bool = False
    strike: bool = False
    foreground: bool = False
    background: bool = False

    @property
    def active(self) -> bool:
        return any(vars(self).values())

    def reset(self) -> None:
        for name in vars(self):
            setattr(self, name, False)

    def apply(self, params: str) -> None:
        codes = [int(code) for code in params.split(";") if code] if params else [0]
        index = 0
        while index < len(codes):
            code = codes[index]
            if code == 0:
                self.reset()
            elif code in (1, 2):
                self.intensity = True
            elif code == 3:
                self.italic = True
            elif code == 4:
                self.underline = True
            elif code in (5, 6):
                self.blink = True
            elif code == 7:
                self.inverse = True
            elif code == 8:
                self.conceal = True
            elif code == 9:
                self.strike = True
            elif code == 22:
                self.intensity = False
            elif code == 23:
                self.italic = False
            elif code == 24:
                self.underline = False
            elif code == 25:
                self.blink = False
            elif code == 27:
                self.inverse = False
            elif code == 28:
                self.conceal = False
            elif code == 29:
                self.strike = False
            elif code == 39:
                self.foreground = False
            elif code == 49:
                self.background = False
            elif 30 <= code <= 38 or 90 <= code <= 97:
                self.foreground = True
                if code == 38 and index + 1 < len(codes):
                    index += 4 if codes[index + 1] == 2 else 2
            elif 40 <= code <= 48 or 100 <= code <= 107:
                self.background = True
                if code == 48 and index + 1 < len(codes):
                    index += 4 if codes[index + 1] == 2 else 2
            index += 1


@dataclass
class _ComposerBlock:
    """One contiguous composer region beginning at a vendor marker."""

    lines: list[str]
    marker_column: int
    start_row: int = 0
    ambiguous_empty: bool = False
    adjacent_to_previous: bool = False


def strip_ansi(text: str) -> str:
    """Remove terminal control sequences without changing printable content."""
    return ANSI_RE.sub("", text)


def _row_without_sgr(line: str) -> str:
    """Printable row text after SGR/OSC and non-breaking space, before class."""
    return strip_ansi(line).replace("\xa0", " ")


def _without_border(text: str) -> tuple[str, int]:
    """Return row content without a paired box border and its original content column.

    At most one trailing glyph is stripped, and only after a leading border was consumed: a
    draft may itself end in a border-shaped character, and the closing border is the only
    structural one.
    """
    leading = len(text) - len(text.lstrip())
    candidate = text.lstrip()
    bordered = False
    while candidate and candidate[0] in _LEADING_BORDER_GLYPHS:
        bordered = True
        candidate = candidate[1:].lstrip()
    consumed = len(text) - len(candidate)
    if bordered:
        candidate = candidate.rstrip()
        if candidate and candidate[-1] in _TRAILING_BORDER_GLYPHS:
            candidate = candidate[:-1].rstrip()
    return candidate, max(leading, consumed)


def _has_leading_border(text: str) -> bool:
    candidate = text.lstrip()
    return bool(candidate and candidate[0] in _LEADING_BORDER_GLYPHS)


def _is_horizontal_rule(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and set(stripped) <= _HORIZONTAL_RULE_GLYPHS


def _classify_row(line: str, *, glyph: str, marker_column: int | None) -> tuple[_RowClass, int]:
    """Classify one physical row of the viewport: the row rule, stated in one place.

    Successor of ``_is_continuation``. The contract is
    ``docs/engineering-journal/DECISIONS.md`` ``{#907-composer-structural-continuations}``.
    The shape is read after ANSI stripping, with ``\\xa0`` read as space. Every non-blank
    class is decided on the row's content after border pairing, so a bordered row whose
    content is only rule glyphs is a rule row, not a bordered one. ``marker_column`` is the
    marker column of the block in play -- open, or awaiting settlement after a blank row --
    or ``None`` when no block is in play; it decides only the indented/terminator split.
    """
    clean = _row_without_sgr(line)
    if not clean.strip():
        return _RowClass.BLANK, 0
    candidate, column = _without_border(clean)
    if candidate.startswith(glyph):
        return _RowClass.MARKER, column
    if _is_horizontal_rule(candidate):
        return _RowClass.RULE, column
    if _has_leading_border(clean):
        return _RowClass.BORDERED, column
    if (
        marker_column is not None
        and column > marker_column
        and candidate[:1] not in COMPOSER_MARKERS
    ):
        return _RowClass.INDENTED, column
    return _RowClass.TERMINATOR, column


def _composer_blocks(ansi_text: str, *, glyph: str) -> list[_ComposerBlock]:
    """Return structurally bounded marker blocks in pane order.

    See ``docs/engineering-journal/DECISIONS.md``
    ``{#907-composer-structural-continuations}``. One class per physical row decides
    everything. A row directly below an open block
    continues it when it is bordered, or when it is unbordered and indented past the marker
    column; a blank, rule, marker or terminator row ends the block and separates it from the
    next. An empty block closed by a blank row is not settled until the next non-blank row
    arrives: indented content makes it ``ambiguous_empty`` -- that shape is either a status
    footer after a spacer or a draft with a leading blank line -- and anything else settles
    it as empty.
    """
    blocks: list[_ComposerBlock] = []
    current: _ComposerBlock | None = None
    unsettled_blank: _ComposerBlock | None = None
    separated = True
    rows = ansi_text.splitlines()
    for row_index, line in enumerate(rows):
        marker_column = (
            current.marker_column
            if current is not None
            else unsettled_blank.marker_column
            if unsettled_blank is not None
            else None
        )
        row_class, column = _classify_row(line, glyph=glyph, marker_column=marker_column)
        if row_class is _RowClass.MARKER:
            # A marker row settles any blank-closed empty block as plain empty before the
            # next block starts; adjacency records whether a separator came between them.
            unsettled_blank = None
            current = _ComposerBlock(
                lines=[line],
                marker_column=column,
                start_row=row_index,
                adjacent_to_previous=bool(blocks and not separated),
            )
            blocks.append(current)
            separated = False
        elif current is not None:
            if row_class in (_RowClass.BORDERED, _RowClass.INDENTED):
                # Containment (bordered) or indentation past the marker column (unbordered)
                # proves continuation. No capture shows chrome between the marker and its
                # draft rows, so that asymmetry is accepted and recorded.
                current.lines.append(line)
                separated = False
            elif row_class is _RowClass.TERMINATOR and not _visible_after_marker(
                current.lines, glyph
            ):
                # Issue 1002 F102: a still-empty Claude/Codex box whose next row begins with
                # another vendor's glyph (`> quoted draft`) is that draft, not an empty box
                # that authorises a write. Stop absorbing once the block has visible text so
                # menu rows under a filled box stay content (F13).
                candidate, _ = _without_border(_row_without_sgr(line))
                if candidate[:1] in COMPOSER_MARKERS and not candidate.startswith(glyph):
                    current.lines.append(line)
                    separated = False
                else:
                    current = None
                    separated = True
            else:
                if row_class is _RowClass.BLANK and not _visible_after_marker(current.lines, glyph):
                    unsettled_blank = current
                current = None
                separated = True
        else:
            if unsettled_blank is not None:
                if row_class is _RowClass.INDENTED:
                    unsettled_blank.ambiguous_empty = True
                    unsettled_blank = None
                elif row_class is not _RowClass.BLANK:
                    unsettled_blank = None
            if row_class is not _RowClass.BORDERED and row_class is not _RowClass.INDENTED:
                separated = True
    return blocks


def _visible_after_marker(lines: list[str], glyph: str) -> str:
    clean_lines = [_without_border(_row_without_sgr(line))[0] for line in lines]
    first = clean_lines[0]
    if first.startswith(glyph):
        clean_lines[0] = first[len(glyph) :]
    # Terminal wraps do not add a character to the draft; joining with a newline over-counts it.
    return "".join(line.strip() for line in clean_lines).strip()


def _unstyled_text(lines: list[str], glyph: str) -> str:
    """Printable characters emitted while no Select Graphic Rendition attribute was active."""
    state = _StyleState()
    output: list[str] = []
    for line in lines:
        cursor = 0
        row: list[str] = []
        for sgr in SGR_RE.finditer(line):
            if not state.active:
                row.append(ANSI_RE.sub("", line[cursor : sgr.start()]))
            state.apply(sgr.group(1))
            cursor = sgr.end()
        if not state.active:
            row.append(ANSI_RE.sub("", line[cursor:]))
        joined = "".join(row).replace("\xa0", " ")
        candidate, _ = _without_border(joined)
        if not _has_leading_border(joined) and _has_leading_border(strip_ansi(line)) and candidate:
            # The row's border glyphs were styled and never entered the unstyled content,
            # but an unstyled closing border can still trail it. Exactly one glyph, so a
            # draft ending in a border-shaped character keeps that character.
            candidate = candidate.rstrip()
            if candidate and candidate[-1] in _TRAILING_BORDER_GLYPHS:
                candidate = candidate[:-1].rstrip()
        output.append(candidate)
    if output and output[0].startswith(glyph):
        output[0] = output[0][len(glyph) :]
    return "".join(output).strip()


def _classify_block(block: _ComposerBlock, *, glyph: str) -> ComposerInspection:
    visible = _visible_after_marker(block.lines, glyph)
    if not visible:
        if block.ambiguous_empty or block.adjacent_to_previous:
            return ComposerInspection(ComposerState.UNCLASSIFIABLE)
        # An empty box is empty regardless of how the client coloured its marker or background.
        return ComposerInspection(ComposerState.EMPTY, "")
    staged = _unstyled_text(block.lines, glyph)
    if staged:
        # Once any unstyled character proves operator input, the whole visible block is the
        # withheld draft. Styled wrapped rows belong to that same contiguous composer and count.
        # Receipt length is that visible length:
        # ``docs/engineering-journal/DECISIONS.md`` ``{#907-input-box-visible-length}``.
        return ComposerInspection(ComposerState.STAGED, visible)
    # A fully client-styled non-empty row is byte-indistinguishable from a styled operator draft.
    return ComposerInspection(ComposerState.UNCLASSIFIABLE)


def _only_blanks_between(
    rows: list[str],
    earlier: _ComposerBlock,
    later: _ComposerBlock,
    *,
    ignore: tuple[_ComposerBlock, ...] = (),
) -> bool:
    """True when nothing but blank rows sit between two marker blocks.

    Adjacent blocks have an empty interval. Rows that belong to ignored empty-decoy
    blocks in between are not content. A leftover content row is scrollback above a
    live empty box (CORR-05). Blank-only (or decoy-only) separation is a painted
    empty marker under a still-staged draft (issue 1002 F110 / R5).
    """
    start = earlier.start_row + len(earlier.lines)
    end = later.start_row
    if end < start:
        return False
    decoy_rows: set[int] = set()
    for block in ignore:
        decoy_rows.update(range(block.start_row, block.start_row + len(block.lines)))
    return all(i in decoy_rows or not _row_without_sgr(rows[i]).strip() for i in range(start, end))


def _is_empty_decoy(inspection: ComposerInspection, block: _ComposerBlock, *, glyph: str) -> bool:
    """An empty or unclassifiable-empty marker that can stand in for a painted decoy."""
    return not _visible_after_marker(block.lines, glyph) and inspection.state in (
        ComposerState.EMPTY,
        ComposerState.UNCLASSIFIABLE,
    )


def inspect_composer(ansi_text: str, *, vendor: str) -> ComposerInspection:
    """Inspect the live composer block and let that block decide the outcome.

    The last block is the live box when a content row sits above it, so a submitted
    echo never stands in for a lower empty box. Empty markers with only blank rows
    (or nothing) between them and an earlier staged block are painted chrome, and
    the staged inspection wins so the write stops (issue 1002 F110).
    """
    if vendor not in COMPOSER_GLYPH_BY_VENDOR:
        return ComposerInspection(ComposerState.UNSUPPORTED_VENDOR)
    glyph = COMPOSER_GLYPH_BY_VENDOR[vendor]
    if glyph is None:
        return ComposerInspection(ComposerState.UNSUPPORTED_VENDOR)
    blocks = _composer_blocks(ansi_text, glyph=glyph)
    if not blocks:
        return ComposerInspection(ComposerState.NOT_FOUND)
    classified = [_classify_block(block, glyph=glyph) for block in blocks]
    last = classified[-1]
    rows = ansi_text.splitlines()
    if _is_empty_decoy(last, blocks[-1], glyph=glyph):
        intermediates: list[_ComposerBlock] = []
        for index in range(len(blocks) - 2, -1, -1):
            if classified[index].state is ComposerState.STAGED:
                ignored = tuple(intermediates) + (blocks[-1],)
                if _only_blanks_between(rows, blocks[index], blocks[-1], ignore=ignored):
                    return classified[index]
                break
            if _is_empty_decoy(classified[index], blocks[index], glyph=glyph):
                intermediates.append(blocks[index])
                continue
            break
    return last


def composer_staged_text(ansi_text: str, *, vendor: str) -> str | None:
    """Compatibility view: staged text, empty string, or None for every other outcome."""
    result = inspect_composer(ansi_text, vendor=vendor)
    if result.state is ComposerState.STAGED:
        return result.text
    if result.state is ComposerState.EMPTY:
        return ""
    return None
