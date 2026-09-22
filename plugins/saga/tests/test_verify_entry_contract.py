"""Contract checks for the Verify entry (W8, SDLC issue #89, R69/R71/R70).

Work and QA are Markdown skills, so these tests read the shipped skill text directly (the
house pattern, as in ``test_work_review_contract.py``). They assert the Active/Verify
boundary that the ``verify_entry`` block of ``config/sdlc-schema.json`` in
``infiquetra-sdlc`` encodes: no pre-merge Verify write survives, and the post-merge path
names the real conditions.

Deliberate failure direction: the region assertions anchor on the ``### 5.3`` / ``### 5.4``
phase headings; if a restructure removes those anchors the helper asserts loudly rather
than passing vacuously.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORK_SKILL = ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md"
QA_SKILL = ROOT / "plugins" / "saga" / "skills" / "qa" / "SKILL.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _region(text: str, start_heading: str, end_heading: str, source: Path) -> str:
    """Text between two level-3 phase headings, or an assertion failure naming
    the missing anchor."""
    start = text.find(start_heading)
    end = text.find(end_heading, start + len(start_heading))
    assert start >= 0, f"anchor heading missing in {source}: {start_heading!r}"
    assert end >= 0, f"anchor heading missing in {source}: {end_heading!r}"
    return text[start:end]


def _pr_ready_region() -> str:
    return _region(_read(WORK_SKILL), "### 5.3 ", "### 5.4 ", WORK_SKILL)


def _post_merge_region() -> str:
    return _region(_read(WORK_SKILL), "### 4.4 ", "## Phase 5 ", WORK_SKILL)


def _collapse(text: str) -> str:
    return " ".join(text.split())


# --- R3: the pre-merge Verify write is gone, not renamed ----------------------

# Both titles the pre-merge Verify move shipped under (review cycle 1, F-2):
# the retired <= 0.143.0 form and W7's renamed 0.145.0 form, which carried the
# same PR-ready timing defect as prose. Either reappearing is a regression.
PRE_MERGE_VERIFY_HEADING = re.compile(
    r"^#{2,6}\s.*(?:Move the card to Verify|The card moves to Verify).*$",
    re.MULTILINE,
)


def test_no_pre_merge_verify_move_heading_survives_in_either_form() -> None:
    text = _read(WORK_SKILL)
    assert not PRE_MERGE_VERIFY_HEADING.search(text)


def test_no_target_state_verify_inside_the_pr_ready_region() -> None:
    # Whether the string appears at all is W7/4.4's business; only its PLACE in the
    # PR-ready region is policed here.
    assert "--target-state Verify" not in _pr_ready_region()


# --- R1/R69: the post-merge path states the real condition --------------------


def test_post_merge_region_names_merge_and_succeeded_nonprod_deployment() -> None:
    collapsed = _collapse(_post_merge_region())
    assert "**merged**" in collapsed
    assert "non-production deployment has **succeeded**" in collapsed
    assert "PR-ready" in collapsed and "never move the card to Verify" in collapsed


def test_post_merge_region_names_the_no_deployable_software_route_and_forbids_fabrication() -> None:
    collapsed = _collapse(_post_merge_region())
    assert "no deployable software" in collapsed
    assert "real form and consumption context" in collapsed
    assert "non-applicability" in collapsed and "with a reason" in collapsed
    assert "no environment or deployment record fabricated" in collapsed
    # The schema block is named as the single authority this prose only restates.
    assert "verify_entry" in collapsed
    assert "verify_entry.py" in collapsed


# --- P16/Q6: /qa is the activity Verify holds ---------------------------------


def test_qa_skill_names_the_post_merge_verify_relationship() -> None:
    collapsed = _collapse(_read(QA_SKILL))
    assert "Verify" in collapsed
    assert "merged plus a succeeded non-production deployment" in collapsed
    assert "PR-ready never moves a card to `Verify`" in collapsed
    assert "verify_entry" in collapsed


def test_qa_no_deployable_route_states_the_merge_precondition() -> None:
    """Cycle-2 F-7 regression: /qa's no-deployable route must name merge as a
    precondition (R71 relaxes the DEPLOYMENT requirement, never the MERGE
    requirement), matching the resolver, the schema's require_merge flag, and
    docs/process/verify-entry.md -- and there must be no `or` that introduces a
    second, unmerged entry route."""
    collapsed = _collapse(_read(QA_SKILL))
    assert "no deployable software, the same merge precondition still applies" in collapsed
    assert "relaxes" in collapsed and "deployment" in collapsed and "merge" in collapsed
    assert "merged **and** the delivered artifact exists" in collapsed
    assert "There is no pre-merge entry route" in collapsed
    # The retired unmerged-route wording must not survive anywhere.
    assert "or, for work with no deployable software, once the delivered artifact" not in collapsed


def test_work_post_merge_no_deployable_route_names_the_merge_precondition() -> None:
    """Cycle-2 F-7 (folded sentence): /work 4.4's no-deployable route must also
    state merge, not artifact-in-context alone."""
    collapsed = _collapse(_post_merge_region())
    assert "same merge precondition holds" in collapsed
    assert "relaxes the **deployment** requirement, never the **merge** requirement" in collapsed
    assert "merged **and** the delivered artifact exists in its real form" in collapsed
    assert "never move the card to Verify" in collapsed
    assert "verify_entry" in collapsed
