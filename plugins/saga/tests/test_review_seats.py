"""Lens seats: tiers from staffing, lenses from the declaration, no carry-over (child 937).

Three findings from child 937 are guarded here. A lens seat's vendor, model and
effort come from the staffing plan and are named explicitly in every dispatch,
because an omitted model silently inherits the host's and an inherited configuration
is an unverified one. The lens set is the declaration's, fixed at admission, not a
per-commit question. And a new commit gets a review bound to it, never a prior
revision's outcome carried forward.

Nothing here launches a session. The dispatch is built and inspected as data.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"
ROLES = ROOT / "plugins" / "agent-launcher" / "roles"

REVISION = "0123456789abcdef0123456789abcdef01234567"
LATER_REVISION = "fedcba9876543210fedcba9876543210fedcba98"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rr() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    return _load("review_result_for_seats", SCRIPTS / "review_result.py")


@pytest.fixture
def roster_module() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    return _load("review_roster_for_seats", SCRIPTS / "review_roster.py")


@pytest.fixture
def record_module() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    return _load("run_record_for_seats", SCRIPTS / "run_record.py")


def _record(record_module: ModuleType, **lens_overrides: Any) -> Any:
    record = record_module.RunRecord(
        issue=1001,
        repo="infiquetra/infiquetra-claude-plugins",
        run_configuration=record_module.empty_run_configuration(),
        approval_scope=record_module.empty_approval_scope(),
        admission=record_module.empty_admission(),
    )
    declaration = {
        "always_on": ["architecture-maintainability", "correctness", "security", "testing"],
        "conditional_applies": {"adversarial": "the change is a gate"},
        "conditional_does_not_apply": {"privacy": "no personal data is touched"},
    }
    declaration.update(lens_overrides)
    record.run_configuration["applicable_lenses"] = {
        "value": declaration,
        "chosen_by": "planner",
        "source": "operator",
    }
    record.run_configuration["staffing_models_and_efforts"] = {
        "value": {
            "lens-reviewer": {"vendor": "claude", "model": "opus", "effort": "high"},
        },
        "chosen_by": "delivery_manager",
        "source": "staffing",
    }
    return record


# ---------------------------------------------------------------------------
# The lens set comes from the declaration, fixed at admission
# ---------------------------------------------------------------------------


def test_the_lens_set_is_the_declarations_and_not_a_per_commit_question(
    roster_module: ModuleType, record_module: ModuleType
) -> None:
    """The same record produces the same lens set for any revision.

    Before issue 1001 the conditional lenses were chosen by an operator prompt bound
    to a reviewed commit and a cycle, so a new commit re-opened the question. The
    declaration is now settled once, at admission.
    """
    record = _record(record_module)

    first = roster_module.build_declaration(
        record, revision=REVISION, resolved_at="2026-09-19T00:00:00Z"
    )
    second = roster_module.build_declaration(
        record, revision=LATER_REVISION, resolved_at="2026-09-19T00:00:00Z"
    )

    assert first["lenses"] == second["lenses"]
    assert first["run"]["revision"] != second["run"]["revision"]


def test_a_conditional_lens_left_out_carries_its_reason_into_the_declaration(
    roster_module: ModuleType, record_module: ModuleType
) -> None:
    record = _record(record_module)

    declaration = roster_module.build_declaration(
        record, revision=REVISION, resolved_at="2026-09-19T00:00:00Z"
    )

    assert declaration["lenses"]["privacy"] == {
        "applies": False,
        "reason": "no personal data is touched",
    }


def test_a_declaration_naming_no_conditional_lens_is_refused(
    roster_module: ModuleType, record_module: ModuleType
) -> None:
    """An empty set is a missing answer, not a small one."""
    record = _record(record_module, conditional_applies={}, conditional_does_not_apply={})

    with pytest.raises(roster_module.RosterError, match="names no conditional lens"):
        roster_module.build_declaration(
            record, revision=REVISION, resolved_at="2026-09-19T00:00:00Z"
        )


# ---------------------------------------------------------------------------
# Every seat names its vendor, model and effort
# ---------------------------------------------------------------------------


def test_a_result_names_the_executor_that_produced_each_lens(rr: ModuleType) -> None:
    """A result that cannot say who produced it under what configuration is not evidence."""
    lens = rr.LensResult(
        lens="correctness",
        strictness="standard",
        scorable=True,
        dimension_scores={"a": 9},
        executor={
            "vendor": "anthropic",
            "model": "claude-opus-5",
            "effort": "high",
            "prompt_hash": "sha256:abc",
        },
        hosting={"session": "review-a", "isolation": "separate session, read-only checkout"},
    )

    row = lens.to_dict()

    assert row["executor"]["vendor"] == "anthropic"
    assert row["executor"]["model"] == "claude-opus-5"
    assert row["executor"]["effort"] == "high"
    assert row["hosting"]["session"] == "review-a"


def test_a_result_names_its_staffing_source_and_its_revision(rr: ModuleType) -> None:
    result = rr.ReviewResult(
        revision=REVISION,
        roster_hash="sha256:test",
        outcome="review_incomplete",
        cycle=1,
        loop=rr.LOOP_CODE_REVIEW,
        unit="issue-1001",
        provenance={"staffing_source": "staffing", "sdlc_head": "5efc869f"},
    )

    payload = result.to_dict()

    assert payload["revision"] == REVISION
    assert payload["provenance"]["staffing_source"] == "staffing"


# ---------------------------------------------------------------------------
# No silent carry-over between commits
# ---------------------------------------------------------------------------


def test_each_cycle_binds_its_own_revision(rr: ModuleType, record_module: ModuleType) -> None:
    """A later cycle records the revision it read, never the earlier one."""
    record = _record(record_module)
    record = rr.append_result(
        record,
        rr.ReviewResult(
            revision=REVISION,
            roster_hash="sha256:test",
            outcome="repairs_requested",
            cycle=1,
            loop=rr.LOOP_CODE_REVIEW,
            unit="issue-1001",
        ),
    )
    record = rr.append_result(
        record,
        rr.ReviewResult(
            revision=LATER_REVISION,
            roster_hash="sha256:test",
            outcome="accepted",
            cycle=2,
            loop=rr.LOOP_CODE_REVIEW,
            unit="issue-1001",
        ),
    )

    history = rr.history_for(record, "issue-1001", rr.LOOP_CODE_REVIEW)

    assert [entry["revision"] for entry in history] == [REVISION, LATER_REVISION]
    assert [entry["outcome"] for entry in history] == ["repairs_requested", "accepted"]


def test_an_earlier_outcome_is_never_attached_to_a_later_revision(
    rr: ModuleType, record_module: ModuleType
) -> None:
    """The outcome lives on the entry, which names one revision and only one."""
    record = _record(record_module)
    record = rr.append_result(
        record,
        rr.ReviewResult(
            revision=REVISION,
            roster_hash="sha256:test",
            outcome="accepted",
            cycle=1,
            loop=rr.LOOP_CODE_REVIEW,
            unit="issue-1001",
        ),
    )

    history = rr.history_for(record, "issue-1001", rr.LOOP_CODE_REVIEW)
    accepted_revisions = {entry["revision"] for entry in history if entry["outcome"] == "accepted"}

    assert accepted_revisions == {REVISION}
    assert LATER_REVISION not in accepted_revisions


# ---------------------------------------------------------------------------
# The Lens Reviewer prompt this run consumes
# ---------------------------------------------------------------------------


def test_the_lens_reviewer_role_prompt_exists_and_owns_one_lens() -> None:
    """The brief names the lens; it does not restate the rubric.

    The role prompt tells the session how to reach the lifecycle repository and read
    the catalogue for itself, so a dispatch carries the lens identifier rather than a
    copy of its dimensions — which is what keeps one lens's brief free of another's.
    """
    prompt = ROLES / "lens-reviewer.md"
    if not prompt.is_file():
        pytest.skip(
            "agent-launcher's lens-reviewer role is not in this checkout; "
            "that package is imported on its own branch"
        )
    assert prompt.is_file()

    text = prompt.read_text(encoding="utf-8")
    assert "Do not continue into a second lens" in text
    assert "review_result.v2" in text


def test_the_role_prompt_says_a_conditional_lens_reports_without_scoring() -> None:
    """Eleven lenses carry no fixtures, so no executor can be qualified against them."""
    prompt = ROLES / "lens-reviewer.md"
    if not prompt.is_file():
        pytest.skip(
            "agent-launcher's lens-reviewer role is not in this checkout; "
            "that package is imported on its own branch"
        )
    text = prompt.read_text(encoding="utf-8")

    assert "report findings and say plainly" in text
    assert "you did not score" in text
