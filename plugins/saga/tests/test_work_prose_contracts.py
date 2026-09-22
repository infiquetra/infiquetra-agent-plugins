"""U3 #930 — maintenance sweep prose contracts.

Pins that Work's post-merge ceremony names all five calls. The /loop claim and the
artifact-pointer path cases retired with the surfaces they guarded: issue #1030 removed the /loop
skill and archived the team-execution plugin that owned the pointer script.

The six stale sentences in #930 were re-resolved at preflight: three were
located and repaired (teardown, first-time move, artifact_pointer path, and
the Phase-4.4 gated/allowlist conflation plus the orphaned skip-silently line)
and three remain unlocated after a repository-wide search — the stale /qa
preamble, the stale certificate comment, and the command stub. The latter are
recorded as explicit non-findings in the work-session and the pull request
description rather than silent non-fixes, per OQ3. This test pins the four
provable prose contracts; the residue is documented as non-findings, not
closed on silent.

Carried from infiquetra-claude-plugins@acc99fe7 (upstream 1.2.0), unchanged apart from
the module bootstrap: this package's tests sit under ``plugins/saga/tests/`` rather than
at a repository root, so ``ROOT`` walks up four levels instead of two.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK_SKILL = ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_phase44_gated_and_allowlist_are_not_conflated() -> None:
    # Phase 4.4 must distinguish gated (certificate) from allowlist (halt).
    text = _read(WORK_SKILL)
    sec_start = text.find("### 4.4")
    sec_end = text.find("## Phase 5", sec_start)
    assert sec_start >= 0 and sec_end >= 0
    sec = text[sec_start:sec_end]
    # Each of these had a dead disjunct: `"halt" in sec.lower()` subsumes both quoted forms and is
    # true of almost any prose about this controller, and `"certificate" in sec.lower()` subsumes
    # the module name beside it. A disjunction is only as strong as its weakest operand, so both
    # assertions were passing on the loosest possible reading of the section.
    assert '"halt"' in sec, 'the halt status must appear as the literal record value "halt"'
    assert "certificate" in sec.lower(), "gated must be described as a certificate verdict"
    # The old conflated sentence "gated.*allowlist returns" with gated for allowlist must be gone.
    assert not re.search(r'"gated".*allowlist returns', sec, flags=re.DOTALL | re.IGNORECASE)


def test_the_gated_and_halt_distinction_is_stated_not_merely_mentioned() -> None:
    """Both words appearing is not the contract; saying they are different decisions is.

    A caller that treats them alike offers a retry for a certificate refusal, which reproduces the
    identical answer."""
    text = _read(WORK_SKILL)
    sec_start = text.find("### 4.4")
    sec = text[sec_start : text.find("## Phase 5", sec_start)]
    collapsed = " ".join(sec.split())
    assert re.search(
        r"`gated`\s+and\s+`halt`\s+are\s+the\s+two\s+withholding\s+outcomes\s+and\s+they\s+"
        r"are\s+\*\*not\s+the\s+same\s+decision\*\*",
        collapsed,
    ), "section 4.4 must state that gated and halt are different decisions"
    assert "neither is cleared by re-running the same call" in collapsed


def test_skip_silently_line_is_not_orphaned() -> None:
    text = _read(WORK_SKILL)
    # The old orphaned "Skip silently when there is no issue" must be replaced.
    assert "Skip silently when there is no issue" not in text
    # New wording is explicit: no board move is submitted when no issue.
    assert (
        "no board move is submitted" in text.lower() or "no lifecycle field to move" in text.lower()
    )
