"""Drift guard: `operator-choice.md` must keep telling the truth about the backend enum.

**What this file used to guard, and why it does not any more.** Until issue 1030 it pinned
§3.2's two dynamic-workflow purposes across every offer surface, so a SKILL rebuild could not
quietly resell Claude Code Workflows as fan-out only. Issue 1030 archived the `team-execution`
plugin and removed the `cc-workflows` plugin, so there is no offer left to make and no purpose
list left to under-sell. The sweep that retired those assertions left this module behind with its
constants and its two private helpers and **no test function at all** — a file that looks like a
guard in the tree, collects zero tests, and reports green forever.

So the file keeps its name and its subject and guards the thing that actually can drift now: the
document's claim about the enum must match the engine's enum. A reference document that says
"there are three values" while `saga.py` accepts one is the failure mode this repository keeps
hitting, and it is exactly the kind of claim a reader trusts without checking.

Three assertions, and each names something a sweep could break:

* the document does not tell a reader that `team-execution` or `cc-workflows-ultracode` is
  selectable;
* the document names every value `saga.py` actually accepts;
* the sections that survive only as history say so in their own text, so a reader who lands in
  §3 or §8 from a search result is told before they read a menu that no longer exists.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SAGA_ROOT = REPO_ROOT / "plugins" / "saga"
OPERATOR_CHOICE = SAGA_ROOT / "references" / "operator-choice.md"
SAGA_ENGINE = SAGA_ROOT / "scripts" / "saga.py"

#: The two strings that stay readable at rest and must never be presented as a live choice.
ARCHIVED_MODES = ("team-execution", "cc-workflows-ultracode")

#: The headings whose content is a record of removed machinery rather than current guidance.
HISTORICAL_SECTION_PATTERNS = (
    r"^##\s*3\.\s",
    r"^##\s*4\.\s",
    r"^##\s*8\.\s",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _engine_modes() -> tuple[str, ...]:
    """The enum literal in ``saga.py``, read as text so the guard needs no import."""
    match = re.search(r"^ORCHESTRATION_MODES = \(([^)]*)\)", _read(SAGA_ENGINE), re.MULTILINE)
    assert match is not None, "saga.py no longer declares ORCHESTRATION_MODES as a literal tuple"
    return tuple(re.findall(r'"([^"]+)"', match.group(1)))


def _section(text: str, heading_pattern: str) -> str:
    """Slice one ``##`` section out of the document, anchored on its heading."""
    start = re.search(heading_pattern, text, re.MULTILINE)
    assert start is not None, f"operator-choice.md has no heading matching {heading_pattern!r}"
    after = text[start.end() :]
    nxt = re.search(r"^##\s", after, re.MULTILINE)
    return after[: nxt.start()] if nxt else after


def test_the_engine_still_declares_a_literal_enum() -> None:
    """The guard reads the enum as text; a refactor to a computed value would silence it."""
    modes = _engine_modes()
    assert modes, "ORCHESTRATION_MODES parsed as empty — the guard cannot see the enum"
    assert "inline" in modes


def test_the_document_names_every_mode_the_engine_accepts() -> None:
    """A value the engine accepts and the document omits is an undocumented backend."""
    body = _read(OPERATOR_CHOICE)
    for mode in _engine_modes():
        assert f"`{mode}`" in body, (
            f"saga.py accepts {mode!r} and operator-choice.md never names it"
        )


@pytest.mark.parametrize("mode", ARCHIVED_MODES)
def test_an_archived_mode_is_never_presented_as_selectable(mode: str) -> None:
    """The document may describe an archived value; it may not offer one.

    The check is the availability table in §1, which is where a reader looks to find out what they
    can pick. An archived row has to say so on the row.
    """
    section_one = _section(_read(OPERATOR_CHOICE), r"^##\s*1\.\s")
    rows = [line for line in section_one.splitlines() if line.startswith(f"| `{mode}`")]
    assert rows, f"§1's availability table no longer has a row for {mode!r}"
    for row in rows:
        assert "never selectable" in row, (
            f"§1's row for {mode!r} does not say it is never selectable: {row}"
        )


@pytest.mark.parametrize("pattern", HISTORICAL_SECTION_PATTERNS)
def test_a_historical_section_says_so_in_its_own_text(pattern: str) -> None:
    """A reader landing mid-document from a search must be told before reading a dead menu."""
    section = _section(_read(OPERATOR_CHOICE), pattern).lower()
    assert "historical" in section or "issue 1030" in section, (
        f"the section matching {pattern!r} reads as current guidance but describes removed "
        "machinery; say so in the section itself"
    )
