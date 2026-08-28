"""Plain-spoken-text rendering gate (R121, R20; KTD1).

This module is the adapter-facing enforcement boundary for requirement R121:
the agent-facing surface accepts plain spoken text only. Any Markdown
formatting or fenced code block is rejected at submission with a named
reason; text is never silently cleaned, shortened, or reformatted (R20).

The class table, block-indentation rule, and stated non-class list below are
the gate's self-contained normative grammar. Every construct in base Markdown
plus GitHub-flavored pipe tables and strikethrough is disposed of in exactly
one of three ways:
1. A rejecting class in the table below;
2. A structural non-class: blank lines and ordinary paragraph breaks;
3. A prose-collision non-class: HTML entity references (&name;) which collide
   with ordinary prose like 'AT&T;' are accepted as plain.

Precedence for rejection reasons (KTD1):
- Any fence yields 'fenced_code_block';
- Otherwise any other detected class yields 'markdown_formatting', with the
  detected classes and first offending line named in the detail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

__all__ = [
    "REASON_FENCED_CODE_BLOCK",
    "REASON_MARKDOWN_FORMATTING",
    "VERDICT_PLAIN",
    "VERDICT_REJECTED",
    "CLASS_FENCED_CODE_BLOCK",
    "CLASS_INDENTED_CODE_BLOCK",
    "CLASS_ATX_HEADING",
    "CLASS_SETEXT_HEADING",
    "CLASS_LIST_MARKER",
    "CLASS_BLOCKQUOTE",
    "CLASS_HORIZONTAL_RULE",
    "CLASS_TABLE_PIPE_ROW",
    "CLASS_LINK_REFERENCE_DEFINITION",
    "CLASS_HARD_LINE_BREAK",
    "CLASS_RAW_HTML",
    "CLASS_BACKSLASH_ESCAPE",
    "CLASS_EMPHASIS_STRONG",
    "CLASS_STRIKETHROUGH",
    "CLASS_INLINE_CODE_SPAN",
    "CLASS_INLINE_LINK_IMAGE",
    "CLASS_REFERENCE_LINK",
    "CLASS_AUTOLINK",
    "GateVerdict",
    "evaluate",
    "gate",
    "check_rendering",
]

REASON_FENCED_CODE_BLOCK = "fenced_code_block"
REASON_MARKDOWN_FORMATTING = "markdown_formatting"

VERDICT_PLAIN = "plain"
VERDICT_REJECTED = "rejected"

CLASS_FENCED_CODE_BLOCK = "fenced_code_block"
CLASS_INDENTED_CODE_BLOCK = "indented_code_block"
CLASS_ATX_HEADING = "atx_heading"
CLASS_SETEXT_HEADING = "setext_heading"
CLASS_LIST_MARKER = "list_marker"
CLASS_BLOCKQUOTE = "blockquote"
CLASS_HORIZONTAL_RULE = "horizontal_rule"
CLASS_TABLE_PIPE_ROW = "table_pipe_row"
CLASS_LINK_REFERENCE_DEFINITION = "link_reference_definition"
CLASS_HARD_LINE_BREAK = "hard_line_break"
CLASS_RAW_HTML = "raw_html"
CLASS_BACKSLASH_ESCAPE = "backslash_escape"
CLASS_EMPHASIS_STRONG = "emphasis_strong"
CLASS_STRIKETHROUGH = "strikethrough"
CLASS_INLINE_CODE_SPAN = "inline_code_span"
CLASS_INLINE_LINK_IMAGE = "inline_link_image"
CLASS_REFERENCE_LINK = "reference_link"
CLASS_AUTOLINK = "autolink"

# 1. Fenced code block: 0-3 leading spaces, 3+ backticks or 3+ tildes
_FENCE_PATTERN = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")

# 3. ATX heading: 0-3 leading spaces, 1-6 hashes, then space/tab or end of line
_ATX_HEADING_PATTERN = re.compile(r"^[ ]{0,3}#{1,6}([ \t]|$)")

# 4. Setext underline: 0-3 leading spaces, 1+ '=' or 1+ '-', optional spaces/tabs to EOL
_SETEXT_UNDERLINE_PATTERN = re.compile(r"^[ ]{0,3}(?:={1,}|-{1,})[ \t]*$")

# 5. List marker: 0-3 leading spaces, bullet (-+*) or 1-9 digits with . or ), then space/tab/EOL
_LIST_MARKER_PATTERN = re.compile(r"^[ ]{0,3}(?:[-+*]|\d{1,9}[.)])([ \t]|$)")

# 6. Blockquote marker: 0-3 leading spaces, >
_BLOCKQUOTE_PATTERN = re.compile(r"^[ ]{0,3}>")

# 7. Horizontal rule: 0-3 leading spaces, 3+ of -, _, or *, spaces/tabs allowed
_HORIZONTAL_RULE_PATTERN = re.compile(
    r"^[ ]{0,3}(?:(?:-[ \t]*){3,}|(?:_[ \t]*){3,}|(?:\*[ \t]*){3,})$"
)

# 9. Link-reference definition: 0-3 leading spaces, [label]:
_LINK_REF_DEF_PATTERN = re.compile(r"^[ ]{0,3}\[(?:\\\]|[^\]])+\]:")

# 11. Raw HTML: < followed by letter, /letter, !--, !letter, ?, or ![CDATA[
_RAW_HTML_PATTERN = re.compile(r"<(?=[A-Za-z]|/[A-Za-z]|!--|![A-Za-z]|\?|!\[CDATA\[)")

# 12. Backslash escape: backslash before any of the 32 ASCII punctuation characters
# ASCII 33-47, 58-64, 91-96, 123-126
_BACKSLASH_ESCAPE_PATTERN = re.compile(r"\\[!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~]")

# 13. Emphasis / strong: *...* or _..._ (word edge guarded)
_EMPHASIS_STAR_PATTERN = re.compile(r"(?<!\*)\*{1,}(?=\S)(?:.*?\S)?\*{1,}(?!\*)")
_EMPHASIS_UNDERSCORE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])_{1,}(?=\S)(?:.*?\S)?_{1,}(?![A-Za-z0-9_])"
)

# 14. Strikethrough: 1 or 2 tildes
_STRIKETHROUGH_PATTERN = re.compile(
    r"(?<!~)(?P<tilde>~{1,2})(?=\S)(?:.*?\S)?(?P=tilde)(?!~)"
)

# 15. Inline code span: 1+ backticks matched by equal run
_INLINE_CODE_PATTERN = re.compile(r"(?<!`)(?P<ticks>`{1,})(?:.*?(?<!`))(?P=ticks)(?!`)")

# 16. Inline link / image: [text](url) or ![alt](url)
_INLINE_LINK_IMAGE_PATTERN = re.compile(r"!?\[[^\]]*\]\([^)]*\)")

# 17. Reference link: [text][ref] or [text][]
_REFERENCE_LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\[[^\]]*\]")

# 18. Autolink: <scheme:...> or <user@domain>
_AUTOLINK_PATTERN = re.compile(
    r"<(?:[A-Za-z][A-Za-z0-9+.\-]{1,31}:[^<>\s]*|[^<>\s@]+@[^<>\s@]+)>"
)


@dataclass(frozen=True)
class GateVerdict:
    """The outcome of evaluating candidate spoken text against R121."""

    is_plain: bool
    verdict: str
    reason: str | None = None
    detail: dict[str, object] | None = None
    detected_classes: list[str] = field(default_factory=list)
    first_offending_line: int | None = None


@dataclass(frozen=True)
class _Violation:
    class_name: str
    line_number: int


def evaluate(text: str) -> GateVerdict:
    """Evaluate candidate rendering text against the R121 normative grammar.

    Returns a GateVerdict indicating whether the text is plain spoken text or
    rejected, with reason, detected classes, and first offending line number.
    This module exposes no text transformation or cleaning function (R20).
    """
    if not text:
        return GateVerdict(
            is_plain=True,
            verdict=VERDICT_PLAIN,
            reason=None,
            detail=None,
            detected_classes=[],
            first_offending_line=None,
        )

    lines = text.splitlines()
    violations: list[_Violation] = []

    for i, line in enumerate(lines):
        line_no = i + 1

        # 1. Fenced code block
        if _FENCE_PATTERN.match(line):
            violations.append(_Violation(CLASS_FENCED_CODE_BLOCK, line_no))

        # 2. Indented code block: non-blank line with >=4 leading spaces or a tab in leading whitespace
        if line.strip() != "":
            if line.startswith("    ") or bool(re.match(r"^[ ]*\t", line)):
                violations.append(_Violation(CLASS_INDENTED_CODE_BLOCK, line_no))

        # 3. ATX heading
        if _ATX_HEADING_PATTERN.match(line):
            violations.append(_Violation(CLASS_ATX_HEADING, line_no))

        # 4. Setext heading: preceding non-blank line followed by underline line
        if i < len(lines) - 1 and line.strip() != "":
            next_line = lines[i + 1]
            if _SETEXT_UNDERLINE_PATTERN.match(next_line):
                violations.append(_Violation(CLASS_SETEXT_HEADING, line_no))

        # 5. List marker
        if _LIST_MARKER_PATTERN.match(line):
            violations.append(_Violation(CLASS_LIST_MARKER, line_no))

        # 6. Blockquote marker
        if _BLOCKQUOTE_PATTERN.match(line):
            violations.append(_Violation(CLASS_BLOCKQUOTE, line_no))

        # 7. Horizontal rule
        if _HORIZONTAL_RULE_PATTERN.match(line):
            violations.append(_Violation(CLASS_HORIZONTAL_RULE, line_no))

        # 8. Table pipe row
        if "|" in line:
            violations.append(_Violation(CLASS_TABLE_PIPE_ROW, line_no))

        # 9. Link-reference definition
        if _LINK_REF_DEF_PATTERN.match(line):
            violations.append(_Violation(CLASS_LINK_REFERENCE_DEFINITION, line_no))

        # 10. Hard line break: non-final line ending in \ or in 2+ spaces before non-blank line
        if i < len(lines) - 1:
            if line.endswith("\\"):
                violations.append(_Violation(CLASS_HARD_LINE_BREAK, line_no))
            elif line.endswith("  ") and lines[i + 1].strip() != "":
                violations.append(_Violation(CLASS_HARD_LINE_BREAK, line_no))

        # 11. Raw HTML
        if _RAW_HTML_PATTERN.search(line):
            violations.append(_Violation(CLASS_RAW_HTML, line_no))

        # 12. Backslash escape
        if _BACKSLASH_ESCAPE_PATTERN.search(line):
            violations.append(_Violation(CLASS_BACKSLASH_ESCAPE, line_no))

        # 13. Emphasis / strong
        if _EMPHASIS_STAR_PATTERN.search(line) or _EMPHASIS_UNDERSCORE_PATTERN.search(line):
            violations.append(_Violation(CLASS_EMPHASIS_STRONG, line_no))

        # 14. Strikethrough
        if _STRIKETHROUGH_PATTERN.search(line):
            violations.append(_Violation(CLASS_STRIKETHROUGH, line_no))

        # 15. Inline code span
        if _INLINE_CODE_PATTERN.search(line):
            violations.append(_Violation(CLASS_INLINE_CODE_SPAN, line_no))

        # 16. Inline link / image
        if _INLINE_LINK_IMAGE_PATTERN.search(line):
            violations.append(_Violation(CLASS_INLINE_LINK_IMAGE, line_no))

        # 17. Reference link
        if _REFERENCE_LINK_PATTERN.search(line):
            violations.append(_Violation(CLASS_REFERENCE_LINK, line_no))

        # 18. Autolink
        if _AUTOLINK_PATTERN.search(line):
            violations.append(_Violation(CLASS_AUTOLINK, line_no))

    if not violations:
        return GateVerdict(
            is_plain=True,
            verdict=VERDICT_PLAIN,
            reason=None,
            detail=None,
            detected_classes=[],
            first_offending_line=None,
        )

    # Sort violations to determine first offending line
    violations.sort(key=lambda v: v.line_number)
    detected_classes = list(dict.fromkeys(v.class_name for v in violations))
    first_offending_line = violations[0].line_number

    # Precedence: any fence yields 'fenced_code_block'; otherwise 'markdown_formatting'
    if CLASS_FENCED_CODE_BLOCK in detected_classes:
        reason = REASON_FENCED_CODE_BLOCK
    else:
        reason = REASON_MARKDOWN_FORMATTING

    detail: dict[str, object] = {
        "detected_classes": detected_classes,
        "first_offending_line": first_offending_line,
    }

    return GateVerdict(
        is_plain=False,
        verdict=VERDICT_REJECTED,
        reason=reason,
        detail=detail,
        detected_classes=detected_classes,
        first_offending_line=first_offending_line,
    )


gate = evaluate
check_rendering = evaluate
