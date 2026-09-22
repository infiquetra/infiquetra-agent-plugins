"""Every lifecycle skill ends by doing the next step, not by recommending it (issue #1029).

A structural test over the skill files, because the behaviour lives in instruction text and there
is no runtime to assert against. The first test below is the card's own acceptance criterion,
written with the same phrase and the same case-insensitivity as the command it mirrors:

    grep -n -i "recommended next" plugins/saga/skills/*/SKILL.md
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SKILLS = ROOT / "plugins" / "saga" / "skills"

#: The exact phrase the card's acceptance grep hunts for, matched case-insensitively as `-i` does.
RECOMMENDED_NEXT_RE = re.compile(r"recommended next", re.IGNORECASE)

#: The five lifecycle skills and, for each, the command its ending must now run. The final section
#: is the last ATX heading's body, which is where a routing section sits in every one of them.
LIFECYCLE_CONTINUATIONS: dict[str, tuple[str, ...]] = {
    "plan": ("/work",),
    "doc-review": ("/work",),
    "work": ("/qa",),
    "code-review": ("/work", "next_step"),
    "qa": ("/retro",),
}

#: Wording that means the skill is handing the operator a decision rather than taking the step.
RECOMMENDATION_WORDING = (
    "recommended next",
    "recommend the next command",
    "present continuation routing",
)


def _skill(name: str) -> str:
    return (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")


def test_no_skill_recommends_a_next_step() -> None:
    """The card's acceptance criterion, as a test: the grep must print nothing.

    Scoped to every skill in the plugin, not only the five lifecycle ones, because that is what
    the criterion's glob covers.
    """
    offenders = [
        f"{path.parent.name}:{n}"
        for path in sorted(SKILLS.glob("*/SKILL.md"))
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if RECOMMENDED_NEXT_RE.search(line)
    ]
    assert not offenders, f"skills still recommending a next step: {offenders}"


@pytest.mark.parametrize("name", sorted(LIFECYCLE_CONTINUATIONS))
def test_the_lifecycle_skill_names_the_step_it_continues_into(name: str) -> None:
    text = _skill(name)
    expected = LIFECYCLE_CONTINUATIONS[name]
    assert any(token in text for token in expected), (
        f"/{name}'s instructions never name its continuation ({' or '.join(expected)})"
    )


@pytest.mark.parametrize("name", sorted(LIFECYCLE_CONTINUATIONS))
def test_the_lifecycle_skill_carries_no_recommendation_wording(name: str) -> None:
    text = _skill(name).lower()
    found = [phrase for phrase in RECOMMENDATION_WORDING if phrase in text]
    assert not found, f"/{name} still hands the operator the step: {found}"


@pytest.mark.parametrize("name", sorted(LIFECYCLE_CONTINUATIONS))
def test_the_lifecycle_skill_states_the_continuation_in_its_ending(name: str) -> None:
    """The continuation belongs at the END, which is where a reader stops reading.

    "The ending" is the last quarter of the file, which in each of these five covers the final
    routing section and its hard boundary.
    """
    text = _skill(name)
    ending = text[int(len(text) * 0.75) :]
    expected = LIFECYCLE_CONTINUATIONS[name]
    assert any(token in ending for token in expected), (
        f"/{name} names its continuation, but not in its ending"
    )


def test_the_preservation_contract_survives_in_work() -> None:
    """Continuation moved what runs automatically; it moved nothing about what is confirmed.

    `/work`'s pull-request open, review request, and merge are confirmed actions, and a card that
    made the chain automatic is exactly the change that could have quietly swallowed one.
    """
    text = _skill("work")
    assert "never auto-fired" in text
    assert "under confirmation" in text
    assert "explicitly confirmed" in text


def test_doc_review_bounds_its_continuation() -> None:
    """A strategy or requirements document must not continue into `/work` (plan U4)."""
    text = _skill("doc-review")
    assert "classified as a **plan**" in text
    assert "standalone rather than dispatched" in text
    assert "no `P0` and no `P1` remains" in text


def test_plan_reads_the_destination_before_continuing() -> None:
    """`plan-only` stops after the review; the other destinations continue (plan KTD4)."""
    text = _skill("plan")
    assert "plan-only" in text
    assert "admission.destination" in text


def test_the_three_skills_issue_1030_owns_are_gone() -> None:
    """`/loop`, `/resume` and `/handoff` were issue #1030's to remove, and it removed them.

    This case was written by the continuation card as a boundary guard -- "not mine to delete" --
    and it inverts here rather than retiring, because the boundary it protects still matters in the
    other direction: the run record's `next_step` is what replaced these three, so a re-added skill
    would mean the continuation mechanism had been abandoned rather than merely reverted.
    """
    for name in ("loop", "resume", "handoff"):
        assert not (SKILLS / name).exists(), (
            f"/{name} is removed by issue 1030; the run record's next_step replaced it"
        )
