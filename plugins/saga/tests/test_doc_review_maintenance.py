"""The never-written `review` phase, the artifact-matching conventions, and the commit SHA.

Issue 1026 unit U7, card 934 — the maintenance sweep. Every item is a description that no longer
matched the system.

One boundary is asserted as a negative and matters more than the positives: **no write path to the
`review` phase was added.** The tempting repair for "a declared phase nothing writes" is to make
something write it, which would be a behaviour change smuggled in as documentation maintenance.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA = ROOT / "plugins" / "saga"
SAGA_SCRIPTS = SAGA / "scripts"
SAGA_SPEC = SAGA / "references" / "saga-spec.md"
DOC_REVIEW = SAGA / "skills" / "doc-review" / "SKILL.md"
WORK_SKILL = SAGA / "skills" / "work" / "SKILL.md"
PLAN_SKILL = SAGA / "skills" / "plan" / "SKILL.md"

#: The third stale description lived in plugins/saga/skills/loop/SKILL.md, which issue 1030 has
#: now deleted outright. The exclusion and the case that guarded it retired with the file, exactly
#: as that case said it would.

CORRECTED_DESCRIPTIONS = (SAGA_SPEC, WORK_SKILL, PLAN_SKILL)


def test_the_review_phase_is_declared_in_the_enum() -> None:
    """The premise: `review` is a legal value, which is why the descriptions existed."""
    saga_py = (SAGA_SCRIPTS / "saga.py").read_text(encoding="utf-8")
    assert re.search(r'LIFECYCLE_PHASES = \([^)]*"review"', saga_py, re.DOTALL)


def test_the_saga_spec_maturity_row_marks_the_phase_unwritten() -> None:
    """The row itself carries the marker, not a paragraph elsewhere in the file.

    A guard that searched the whole document would pass while the table -- the part a reader
    consults -- still presented `review` as an ordinary recorded phase beside `plan` and `work`.
    """
    for line in SAGA_SPEC.read_text(encoding="utf-8").splitlines():
        if line.startswith("| `review` |"):
            assert "never written" in line, (
                f"the saga-spec maturity row still presents `review` as recorded: {line!r}"
            )
            break
    else:  # pragma: no cover - the row is the subject of this case
        raise AssertionError("the `review` row disappeared from the maturity table")


def test_no_skill_describes_review_as_a_phase_the_capability_enters() -> None:
    """Each corrected skill says, where it names the phase, that nothing writes it."""
    for path in (WORK_SKILL, PLAN_SKILL):
        text = path.read_text(encoding="utf-8")
        for index, line in enumerate(text.splitlines()):
            if "`review`" not in line:
                continue
            window = " ".join(text.splitlines()[index : index + 4])
            assert "no code path writes it" in window or "that no code path writes" in window, (
                f"{path.relative_to(ROOT)}:{index + 1} names the `review` phase without saying "
                f"nothing writes it: {line!r}"
            )


def test_no_write_path_to_the_review_phase_was_added() -> None:
    """Card 934's explicit non-goal, and the one worth guarding: no saga script writes it."""
    offenders: list[str] = []
    for path in SAGA_SCRIPTS.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"lifecycle_phase\s*=\s*[\"']review[\"']", text):
            offenders.append(str(path.relative_to(ROOT)))
        if re.search(r"--lifecycle-phase[\"']?,\s*[\"']review[\"']", text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"a write path to the `review` phase was added: {offenders}"


def test_latest_matching_artifact_is_defined_by_both_conventions() -> None:
    """Card 934: the rule was stated and never defined, while the corpus had converged on two
    filename conventions. Write down what the corpus does; do not invent a third."""
    text = DOC_REVIEW.read_text(encoding="utf-8")
    assert '**File naming, and what "the latest matching artifact" means.**' in text
    flat = " ".join(text.split())
    assert "doc-review-<target>-<YYYY-MM-DD>.md" in flat
    assert "<YYYY-MM-DD>-<topic>.md" in flat
    assert "recorded target path" in flat


def test_both_named_conventions_are_the_ones_the_corpus_actually_uses() -> None:
    """The definition is only worth having if it describes the real corpus."""
    names = [p.name for p in (ROOT / "docs" / "reviews").glob("*.md")]
    target_led = [n for n in names if n.startswith("doc-review-")]
    if not target_led:
        pytest.skip(
            "this catalog's docs/reviews corpus does not use the upstream doc-review-* names"
        )
    date_led = [n for n in names if re.match(r"^\d{4}-\d{2}-\d{2}-", n)]
    assert target_led, "no target-led artifact in docs/reviews/"
    assert date_led, "no date-led artifact in docs/reviews/"
    assert len(target_led) + len(date_led) == len(names), (
        "docs/reviews/ carries a third convention the skill does not name: "
        f"{sorted(set(names) - set(target_led) - set(date_led))}"
    )


def test_an_ambiguity_between_conventions_surfaces_rather_than_being_guessed() -> None:
    flat = " ".join(DOC_REVIEW.read_text(encoding="utf-8").split())
    assert "surface it as a finding rather than picking one" in flat


def test_a_committed_plan_records_a_real_commit_sha() -> None:
    """The surviving repair from a refuted staleness gate: an artifact that records `working
    tree` names no revision anyone can return to."""
    text = DOC_REVIEW.read_text(encoding="utf-8")
    assert "**a real commit SHA whenever the reviewed document is committed.**" in text
    flat = " ".join(text.split())
    assert "Record `working tree` only for a document that is not yet in a commit" in flat


def test_the_refuted_staleness_gate_does_not_appear() -> None:
    """Only the commit-SHA recording survived the refutation; the gate itself must not."""
    flat = " ".join(DOC_REVIEW.read_text(encoding="utf-8").split()).lower()
    assert "staleness gate" not in flat
    assert "stale plan-artifact pair" not in flat


def test_the_undefined_enabled_by_default_wording_is_gone() -> None:
    """A described default the implementation does not have is a promise the reader cannot
    collect on. Card 934 allows either fix; this one drops the word and honours a plain
    request."""
    text = DOC_REVIEW.read_text(encoding="utf-8")
    assert "Safe fixes are enabled by default" not in text
    assert "Safe fixes are applied and edit the reviewed document in place." in text
    assert "report-only" in text


def test_the_duplicated_lifecycle_prose_was_left_alone() -> None:
    """Card 934's settled decision D-D6 rejects consolidating the hand-maintained copies. The
    copies are a documentation-architecture project, not a Document Review concern."""
    copies = [
        p
        for p in (SAGA / "skills").rglob("SKILL.md")
        if "`/plan` answers:" in p.read_text(encoding="utf-8")
    ]
    assert len(copies) >= 4, (
        f"the lifecycle-position copies collapsed to {len(copies)}; D-D6 says leave them"
    )


def test_no_hand_maintained_line_count_was_added_to_the_rubric_engine() -> None:
    """Card 934: a hand-maintained line number is a defect generator, not documentation."""
    docstring = (SAGA_SCRIPTS / "lifecycle_review.py").read_text(encoding="utf-8")[:3000]
    assert not re.search(r"\b\d+\s*-\s*line\b|\blines? \d+-\d+\b", docstring)
