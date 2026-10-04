"""Tests for the admission questionnaire (issue #1023, plan U3).

Every test passes an explicit ``tmp_path`` store root and an explicit repository root. Nothing here
may create or modify anything under the primary checkout's ``.claude/saga/`` store, and nothing
here reaches the network: the card validator and the staffing component are injected.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
LIVE_PROFILE = REPO_ROOT / ".saga-profile.json"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def adm() -> ModuleType:
    return _load("admission")


@pytest.fixture
def store(tmp_path: Path) -> Path:
    root = tmp_path / "store" / "runs"
    root.mkdir(parents=True)
    return root


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    return root


def _good_card() -> str:
    return "\n".join(
        [
            "### Objective",
            "One JSON run record per issue.",
            "### Intent",
            "Saga keeps state in six stores.",
            "### Out-of-scope / non-goals",
            "- No board write.",
            "### Files expected to change",
            "- `plugins/saga/scripts/run_record.py`",
            "### Tests to add or update",
            "- `tests/test_run_record.py`",
            "### Context library links",
            "- coding_standards: _none_",
            "### Acceptance criteria",
            "- [ ] `uv run pytest tests/test_run_record.py -q` passes.",
            "### Verification",
            "```bash",
            "uv run pytest tests/test_run_record.py -q",
            "```",
            "### Risk",
            "medium",
        ]
    )


def _passing_validator(_body: str) -> tuple[bool, list[str]]:
    return True, []


def _failing_validator(_body: str) -> tuple[bool, list[str]]:
    return False, ["Missing required H3 sections: ['Acceptance criteria']"]


def _fake_staffing() -> SimpleNamespace:
    """A staffing component that records that it was asked."""
    calls: list[str] = []

    def roles() -> dict[str, Any]:
        return {"planner": {}, "lens_reviewer": {}}

    def resolve_role(role: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(role)
        return SimpleNamespace(vendor="claude", model="opus", effort="high")

    def lens_catalogue(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        # The real function returns (mapping keyed by lens identifier, version).
        # This fake used to return the catalogue DOCUMENT, which is the shape the
        # consumer wrongly assumed — so the fake agreed with the bug and the bug
        # survived. See the shape tests at the end of this file.
        return {
            "correctness": {"always_on": True},
            "security": {"always_on": True},
        }, "1.0.0"

    def sdlc_root(*_args: Any, **_kwargs: Any) -> None:
        return None

    return SimpleNamespace(
        roles=roles,
        resolve_role=resolve_role,
        lens_catalogue=lens_catalogue,
        sdlc_root=sdlc_root,
        calls=calls,
    )


def _write_profile(repo_root: Path) -> None:
    (repo_root / ".saga-profile.json").write_text(
        json.dumps(
            {
                "schema": "repository_profile.v1",
                "concurrency_allocation": 10,
                "nonproduction_destination": "none",
                "branch_preview": False,
                "main_consumed_directly": False,
                "mechanical_tool_baseline": ["uv run ruff check ."],
                "preflight_checks": ["the plan cleared /doc-review"],
            }
        ),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# The card validator is a gate (plan R6)
# ---------------------------------------------------------------------------


def test_a_card_that_fails_the_validator_stops_and_names_the_missing_field(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    with pytest.raises(adm.CardNotReadyError) as excinfo:
        adm.admit(
            1023,
            "infiquetra/infiquetra-claude-plugins",
            store_root=store,
            repo_root=repo_root,
            body="### Objective\nx\n",
            validator=_failing_validator,
        )
    assert "Acceptance criteria" in str(excinfo.value)


def test_a_card_that_fails_the_validator_writes_no_record(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    with pytest.raises(adm.CardNotReadyError):
        adm.admit(
            1023,
            "infiquetra/infiquetra-claude-plugins",
            store_root=store,
            repo_root=repo_root,
            body="### Objective\nx\n",
            validator=_failing_validator,
        )
    assert list(store.glob("*.json")) == []


def test_the_real_validator_accepts_a_well_formed_card(adm: ModuleType) -> None:
    """The injected validators above must not be the only thing this is ever run against."""
    passed, errors = adm.load_card_validator()(_good_card())
    assert passed, errors


def test_only_the_first_of_the_six_issue_review_checks_is_performed(adm: ModuleType) -> None:
    block = adm.issue_review_block(card_passed=True)
    assert len(block) == 6
    assert block[adm.ISSUE_REVIEW_CHECKS[0]] == "passed"
    assert [block[check] for check in adm.ISSUE_REVIEW_CHECKS[1:]] == ["not_performed"] * 5


# ---------------------------------------------------------------------------
# Defaults are filled without a question (plan R7)
# ---------------------------------------------------------------------------


def test_every_defaultable_parameter_is_filled_without_a_question(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _write_profile(repo_root)
    record, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        staffing=_fake_staffing(),
    )
    run_record = _load("run_record")
    filled = {
        name
        for name in run_record.RUN_CONFIGURATION_PARAMETERS
        if record.run_configuration[name]["source"] != "unset"
    }
    # Eleven of the thirteen fill themselves here. Two do not: the response to
    # unfinished testing, which the operator must choose from a closed set of two,
    # and the strictness ladder, because this fake resolves no lifecycle checkout
    # for the ladder to be read from.
    #
    # That second exclusion is the repair of issue 1001 showing through. Before it,
    # this assertion passed with `per_lens_score_threshold` filled — but only
    # because the fake returned the catalogue DOCUMENT, the shape the consumer
    # wrongly assumed. Against the real `lens_catalogue`, which returns a mapping
    # keyed by lens identifier, the old consumer filled it for no checkout at all.
    # The fake now returns the real shape, so this line states what actually
    # happens with no checkout. The filled case is covered by
    # `test_resolve_catalogue_reads_the_ladder_from_the_checkout`.
    assert filled == set(run_record.RUN_CONFIGURATION_PARAMETERS) - {
        "unfinished_testing_response",
        "per_lens_score_threshold",
    }
    asked = {question.key for question in outstanding}
    assert "concurrency_allocation" not in asked
    assert "mechanical_tool_baseline" not in asked
    assert "preflight_checks" not in asked


def test_each_filled_value_records_where_it_came_from(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _write_profile(repo_root)
    record, _ = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        staffing=_fake_staffing(),
    )
    assert record.run_configuration["standard_cycle_allowance"] == {
        "value": 3,
        "chosen_by": "delivery_manager",
        "source": "lifecycle-default",
    }
    assert record.run_configuration["concurrency_allocation"]["source"] == "profile"
    assert record.run_configuration["staffing_models_and_efforts"]["source"] == "staffing"


def test_staffing_comes_from_the_component_not_a_local_table(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    staffing = _fake_staffing()
    adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        staffing=staffing,
    )
    assert sorted(staffing.calls) == ["lens_reviewer", "planner"]


def test_an_unreachable_staffing_component_degrades_to_asking_not_refusing(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    record, _ = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        staffing=None,
    )
    assert record.run_configuration["staffing_models_and_efforts"]["source"] == "unset"


def test_a_missing_profile_is_not_an_error(adm: ModuleType, store: Path, repo_root: Path) -> None:
    record, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert record.run_configuration["concurrency_allocation"]["source"] == "unset"
    assert "branch_preview" in {question.key for question in outstanding}


def test_this_repositorys_own_profile_parses_and_fills_what_it_claims(adm: ModuleType) -> None:
    """The tracked `.saga-profile.json` is real configuration, so it is checked like one."""
    if not LIVE_PROFILE.is_file():
        pytest.skip(
            "this catalog does not carry the upstream repository's .saga-profile.json"
        )
    profile = adm.load_profile(REPO_ROOT)
    assert LIVE_PROFILE.is_file()
    assert profile["schema"] == "repository_profile.v1"
    for key in adm.PROFILE_PARAMETERS.values():
        assert key in profile, f"the tracked profile does not supply {key}"
    for key in adm.PROFILE_ADMISSION_ANSWERS:
        assert key in profile, f"the tracked profile does not supply {key}"


# ---------------------------------------------------------------------------
# The one message, asked exactly once (plan R8, R9)
# ---------------------------------------------------------------------------


def test_the_question_set_on_a_fresh_record_with_no_profile_is_the_cards_ten(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert [question.key for question in outstanding] == [
        "risk_tier",
        "approval_scope",
        "destination",
        "staffing_overrides",
        "lens_declaration",
        "repair_allowances",
        "unfinished_testing_response",
        "branch_preview",
        "main_consumed_directly",
        "change_shape",
    ]
    assert len(outstanding) == 10


def test_a_profile_removes_the_two_repository_facts_from_the_question_set(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _write_profile(repo_root)
    _, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    asked = {question.key for question in outstanding}
    assert "branch_preview" not in asked
    assert "main_consumed_directly" not in asked
    assert len(outstanding) == 8


def _all_answers() -> dict[str, Any]:
    run_record = _load("run_record")
    return {
        "risk_tier": "medium",
        "risk_justification": "every other child reads this record",
        "approval_scope": dict.fromkeys(run_record.APPROVAL_CATEGORIES, "none"),
        "destination": "pr",
        "staffing_overrides": "none",
        "lens_declaration": {"always_on": ["correctness"], "conditional": []},
        "repair_allowances": {"standard": 3, "escalated": 2},
        "unfinished_testing_response": "bring the result to the operator",
        "branch_preview": False,
        "main_consumed_directly": False,
        "change_shape": "code",
    }


def test_answers_persist_and_are_not_re_asked(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    run_record = _load("run_record")
    record, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        answers=_all_answers(),
    )
    assert outstanding == []
    run_record.save(store, record)

    _, second_pass = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert second_pass == []


def test_an_operator_answer_is_never_overwritten_by_a_default(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _write_profile(repo_root)
    record, _ = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        answers={"repair_allowances": {"standard": 1, "escalated": 1}},
    )
    assert record.run_configuration["standard_cycle_allowance"] == {
        "value": 1,
        "chosen_by": "delivery_manager",
        "source": "operator",
    }


def test_answers_land_in_the_seven_approval_boundaries(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    run_record = _load("run_record")
    record, _ = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        answers={"approval_scope": dict.fromkeys(run_record.APPROVAL_CATEGORIES, "none")},
    )
    assert set(record.approval_scope) == set(run_record.APPROVAL_CATEGORIES)
    assert all(value == "none" for value in record.approval_scope.values())


def test_an_answer_that_is_not_an_admission_question_is_refused(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    run_record = _load("run_record")
    with pytest.raises(adm.AdmissionError) as excinfo:
        adm.apply_answers(run_record.RunRecord(issue=1023), {"roster_hash": "abc"})
    assert "roster_hash" in str(excinfo.value)


def test_admission_leaves_a_next_step_naming_what_happens_now(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    """A record that says nothing about the next step is a record a cold session cannot resume."""
    record, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert str(len(outstanding)) in record.next_step
    assert "admission question" in record.next_step

    answered, remaining = adm.admit(
        1024,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        answers=_all_answers(),
    )
    assert remaining == []
    assert answered.next_step == "plan"


def test_admission_never_overwrites_a_next_step_a_later_step_set(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    run_record = _load("run_record")
    run_record.set_next_step(store, 1023, "U4 the spore hooks")
    record, _ = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert record.next_step == "U4 the spore hooks"


def test_pending_questions_are_written_onto_the_record(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    record, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert record.admission["pending_questions"] == [q.key for q in outstanding]


# ---------------------------------------------------------------------------
# --dry-run writes nothing (plan R9)
# ---------------------------------------------------------------------------


def test_the_rendered_summary_names_the_defaults_and_the_questions(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _write_profile(repo_root)
    record, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    text = adm.render(record, outstanding, None)
    assert "Filled without asking:" in text
    assert "concurrency_allocation" in text
    assert "not written (--dry-run)" in text
    assert "Questions to answer, once (8)" in text


def test_the_summary_says_so_when_nothing_is_outstanding(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    record, outstanding = adm.admit(
        1023,
        "infiquetra/infiquetra-claude-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        answers=_all_answers(),
    )
    assert "Questions to answer: none" in adm.render(record, outstanding, None)


def test_dry_run_creates_no_file(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adm, "load_card_validator", lambda: _passing_validator)
    monkeypatch.setattr(adm, "load_staffing", lambda: None)
    monkeypatch.setattr(
        adm, "fetch_issue", lambda *_a, **_k: {"number": 1023, "body": _good_card()}
    )
    exit_code = adm.main(
        [
            "--issue",
            "1023",
            "--repo",
            "infiquetra/infiquetra-claude-plugins",
            "--store-root",
            str(store),
            "--repo-root",
            str(repo_root),
            "--dry-run",
        ]
    )
    assert exit_code == 0
    assert list(store.glob("*.json")) == []


def test_a_failing_card_exits_2_from_the_command_line(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(adm, "load_card_validator", lambda: _failing_validator)
    monkeypatch.setattr(adm, "load_staffing", lambda: None)
    monkeypatch.setattr(adm, "fetch_issue", lambda *_a, **_k: {"number": 1023, "body": "x"})
    exit_code = adm.main(
        [
            "--issue",
            "1023",
            "--repo",
            "infiquetra/infiquetra-claude-plugins",
            "--store-root",
            str(store),
            "--repo-root",
            str(repo_root),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Acceptance criteria" in captured.err
    assert "Traceback" not in captured.err


def test_without_dry_run_the_record_is_written_to_the_temporary_store(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_record = _load("run_record")
    monkeypatch.setattr(adm, "load_card_validator", lambda: _passing_validator)
    monkeypatch.setattr(adm, "load_staffing", lambda: None)
    monkeypatch.setattr(
        adm, "fetch_issue", lambda *_a, **_k: {"number": 1023, "body": _good_card()}
    )
    exit_code = adm.main(
        [
            "--issue",
            "1023",
            "--repo",
            "infiquetra/infiquetra-claude-plugins",
            "--store-root",
            str(store),
            "--repo-root",
            str(repo_root),
        ]
    )
    assert exit_code == 0
    assert run_record.load(store, 1023, warn=None) is not None


# ---------------------------------------------------------------------------
# U5: the plan skill names the step it now runs
# ---------------------------------------------------------------------------


def test_the_plan_skill_names_admission_and_the_record_path(adm: ModuleType) -> None:
    """A rename of the script or the store path must not leave the instruction dangling."""
    skill = (REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "plugins/saga/scripts/admission.py" in skill
    assert "--dry-run" in skill
    assert "--answers" in skill
    assert ".claude/saga/runs/issue-<N>.json" in skill
    assert "plugins/saga/references/run-record.md" in skill


def test_the_plan_skill_forbids_inventing_an_approval_boundary_answer(adm: ModuleType) -> None:
    skill = (REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    section = skill.split("### 0.1b")[1].split("### 0.2")[0]
    assert "Never invent an answer" in section


def test_default_repo_reads_the_origin_remote(adm: ModuleType, tmp_path: Path) -> None:
    def _runner(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            returncode=0, stdout="git@github.com:infiquetra/infiquetra-claude-plugins.git\n"
        )

    assert adm.default_repo(tmp_path, runner=_runner) == "infiquetra/infiquetra-claude-plugins"


# ---------------------------------------------------------------------------
# The catalogue read, pinned against the REAL staffing function (issue 1001)
# ---------------------------------------------------------------------------
#
# Until issue 1001 this module's `_resolve_catalogue` read `catalogue["lenses"]`
# and `catalogue["strictness_ladder"]` off the first element of what
# `staffing.lens_catalogue()` returns. That element is a mapping keyed by LENS
# IDENTIFIER, so neither key exists and both reads yielded None for every
# checkout: `per_lens_score_threshold` could not be filled by any path.
#
# The bug survived because the fake above was shaped like the consumer's wrong
# assumption rather than like the real function. These tests fix that: the first
# asserts the real function's shape directly, and the second drives
# `_resolve_catalogue` with a fake built to match it.


def _real_staffing() -> ModuleType | None:
    """fleet-core's staffing component, or None when it cannot be reached."""
    root = Path(__file__).resolve().parents[3]
    path = root / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "staffing.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("real_staffing_for_admission", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules["real_staffing_for_admission"] = module
    spec.loader.exec_module(module)
    return module


def test_real_lens_catalogue_returns_a_pair_keyed_by_lens_identifier() -> None:
    """Pin the sibling's actual return shape, not a fake's.

    One test against the real function is what the old fake could not give. If
    issue 1023 ever changes `lens_catalogue` to return the catalogue document
    instead of a mapping, this fails here rather than silently re-emptying
    `per_lens_score_threshold` in a run nobody is watching.
    """
    staffing = _real_staffing()
    if staffing is None:
        pytest.skip("fleet-core's staffing component is not in this tree")

    returned = staffing.lens_catalogue()
    assert isinstance(returned, tuple), (
        "lens_catalogue returns a pair; a consumer unpacking it as one value reads the "
        "mapping's version string as its catalogue"
    )
    assert len(returned) == 2
    mapping, _version = returned
    assert isinstance(mapping, dict)
    # The mapping is keyed by lens identifier. These two keys are the shape the
    # consumer reads, and neither exists — which is the defect this pins.
    assert "lenses" not in mapping, (
        "the first element is a mapping of lens identifier to entry, not the catalogue "
        "document; reading a 'lenses' key off it always yields None"
    )
    assert "strictness_ladder" not in mapping, (
        "the strictness ladder is not in this return value at all; it is read from the "
        "checkout through staffing.sdlc_root()"
    )


def test_resolve_catalogue_reads_the_real_shape(adm: ModuleType) -> None:
    """`_resolve_catalogue` fills always-on lenses from a mapping keyed by identifier.

    The fake here returns what the real function returns. Against the pre-repair
    consumer this test fails: it read `catalogue["lenses"]`, found nothing, and
    returned an empty result.
    """

    def lens_catalogue(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        return (
            {
                "correctness": {"always_on": True, "name": "Correctness"},
                "security": {"always_on": True, "name": "Security"},
                "performance": {"always_on": False, "name": "Performance"},
            },
            "1.0.0",
        )

    staffing = SimpleNamespace(lens_catalogue=lens_catalogue, sdlc_root=lambda: None)
    resolved = adm._resolve_catalogue(staffing)

    assert resolved["applicable_lenses"]["always_on"] == ["correctness", "security"], (
        "always-on lenses come from the mapping's KEYS, which are lens identifiers; a "
        "conditional lens is never in the list"
    )


def test_resolve_catalogue_reads_the_ladder_from_the_checkout(
    adm: ModuleType, tmp_path: Path
) -> None:
    """The strictness ladder is read from the checkout staffing resolves, not from the pair."""
    checkout = tmp_path / "sdlc"
    (checkout / "config").mkdir(parents=True)
    (checkout / "config" / "lens-catalogue.json").write_text(
        json.dumps(
            {
                "schema": "lens_catalogue.v1",
                "strictness_ladder": {
                    "levels": [
                        {
                            "id": "standard",
                            "derived_overall_minimum": 9.0,
                            "applicable_dimension_minimum": 7,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )

    def lens_catalogue(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        return {"correctness": {"always_on": True}}, "1.0.0"

    staffing = SimpleNamespace(lens_catalogue=lens_catalogue, sdlc_root=lambda: checkout)
    resolved = adm._resolve_catalogue(staffing)

    ladder = resolved["per_lens_score_threshold"]
    assert ladder["levels"][0]["derived_overall_minimum"] == 9.0
    assert ladder["levels"][0]["applicable_dimension_minimum"] == 7


def test_resolve_catalogue_survives_an_absent_checkout(adm: ModuleType) -> None:
    """No checkout is a fact about the machine: the ladder is absent, not an error."""

    def lens_catalogue(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        return {"correctness": {"always_on": True}}, "1.0.0"

    staffing = SimpleNamespace(lens_catalogue=lens_catalogue, sdlc_root=lambda: None)
    resolved = adm._resolve_catalogue(staffing)

    assert resolved["applicable_lenses"]["always_on"] == ["correctness"]
    assert "per_lens_score_threshold" not in resolved


def test_the_catalogue_never_overwrites_an_operator_lens_declaration(
    adm: ModuleType, tmp_path: Path
) -> None:
    """A re-run of admission must not discard the operator's answer.

    `fill_defaults`'s own docstring promises it never overwrites a value carrying an
    `operator` source, and every other fill site honours that. The catalogue loop did
    not — and the omission could not be observed, because `_resolve_catalogue` returned
    an empty mapping for every checkout (see the shape tests above). Repairing that
    read made the clobber reachable: a second `admission.py --issue N` replaced an
    operator's lens declaration, conditional lenses and recorded reasons included, with
    the catalogue's four always-on names.
    """
    checkout = tmp_path / "sdlc"
    (checkout / "config").mkdir(parents=True)
    (checkout / "config" / "lens-catalogue.json").write_text(
        json.dumps({"strictness_ladder": {"levels": []}}), encoding="utf-8"
    )

    def lens_catalogue(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        return {"correctness": {"always_on": True}, "security": {"always_on": True}}, "1.0.0"

    def roles() -> dict[str, Any]:
        return {"planner": {}}

    def resolve_role(_role: str, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(vendor="claude", model="opus", effort="high")

    staffing = SimpleNamespace(
        roles=roles,
        resolve_role=resolve_role,
        lens_catalogue=lens_catalogue,
        sdlc_root=lambda: checkout,
    )

    run_record = _load("run_record")
    record = run_record.RunRecord(
        issue=1001,
        repo="infiquetra/infiquetra-claude-plugins",
        run_configuration=run_record.empty_run_configuration(),
        approval_scope=run_record.empty_approval_scope(),
        admission=run_record.empty_admission(),
    )
    operator_answer = {
        "always_on": ["architecture-maintainability", "correctness", "security", "testing"],
        "conditional_applies": {"adversarial": "the change is a gate"},
        "conditional_does_not_apply": {"privacy": "no personal data is touched"},
    }
    record.run_configuration["applicable_lenses"] = {
        "value": operator_answer,
        "chosen_by": "planner",
        "source": "operator",
    }

    filled = adm.fill_defaults(record, {}, staffing)

    kept = filled.run_configuration["applicable_lenses"]
    assert kept["source"] == "operator"
    assert kept["value"] == operator_answer, (
        "the catalogue proposal overwrote the operator's lens declaration; the "
        "conditional lenses and their recorded reasons would be lost on a re-run"
    )
    # The parameter the operator did NOT answer still fills from the catalogue.
    assert filled.run_configuration["per_lens_score_threshold"]["source"] == "staffing"


# ---------------------------------------------------------------------------
# The staffing and lens tables, in one fixed format (issue #102)
# ---------------------------------------------------------------------------
#
# The golden block below IS the format. A change to it must be deliberate: edit this constant in
# the same commit as the renderer, and the plan skill's instruction to print it verbatim still
# holds.

GOLDEN_TABLES = """\
**Staffing (answer: staffing_overrides)**

| Role | Default | Jev suggestion | Proposed | Why |
|---|---|---|---|---|
| planner | claude opus/high | not configured | claude opus/high | staffing default (work shape judgment) |
| worker | claude sonnet/medium | not configured | claude sonnet/medium | staffing default (work shape mechanical) |

**Lenses (answer: lens_declaration)**

| Lens | Include | Reason | Jev probability |
|---|---|---|---|
| correctness | always on | always-on lens | not configured |
| security | always on | always-on lens | not configured |
| performance | undeclared | undeclared | not configured |
| privacy | undeclared | undeclared | not configured |"""


def _table_staffing(
    *,
    sources: dict[str, str] | None = None,
    failing: tuple[str, ...] = (),
    worker: tuple[str, str] = ("sonnet", "medium"),
) -> SimpleNamespace:
    """A staffing component with two roles and a four-lens catalogue, two of them conditional.

    *sources* sets a role's decision ``source`` (``overlay`` for ``.saga/tier-defaults.json``);
    a role in *failing* raises from ``resolve_role``; *worker* sets the worker's default tier.
    """
    tiers = {"planner": ("opus", "high"), "worker": worker}

    def roles() -> dict[str, Any]:
        return {"planner": {"work_shape": "judgment"}, "worker": {"work_shape": "mechanical"}}

    def resolve_role(role: str, **_kwargs: Any) -> SimpleNamespace:
        if role in failing:
            raise RuntimeError(f"cannot resolve {role}")
        model, effort = tiers[role]
        decision = SimpleNamespace(vendor="claude", model=model, effort=effort)
        if sources and role in sources:
            decision.source = sources[role]
        return decision

    def lens_catalogue(**_kwargs: Any) -> tuple[dict[str, Any], str]:
        return {
            "correctness": {"always_on": True},
            "security": {"always_on": True},
            "performance": {"always_on": False},
            "privacy": {"always_on": False},
        }, "1.0.0"

    def sdlc_root(*_args: Any, **_kwargs: Any) -> None:
        return None

    return SimpleNamespace(
        roles=roles, resolve_role=resolve_role, lens_catalogue=lens_catalogue, sdlc_root=sdlc_root
    )


def _table_record(adm: ModuleType, staffing: Any) -> Any:
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=102, repo="infiquetra/infiquetra-agent-plugins")
    return adm.fill_defaults(record, {}, staffing)


def _tables(adm: ModuleType, record: Any, staffing: Any) -> str:
    data = adm.review_data(record, adm.outstanding_questions(record), staffing, None)
    return adm.render_tables(data)


def _rows(tables: str) -> list[list[str]]:
    """Every data row of both tables, split into cells (an escaped pipe stays in its cell)."""
    rows = []
    for line in tables.splitlines():
        if not line.startswith("| ") or line.startswith(("| Role ", "| Lens ")):
            continue
        rows.append([cell.strip() for cell in re.split(r"(?<!\\)\|", line)[1:-1]])
    return rows


def _assert_no_empty_cell(tables: str) -> None:
    for line in tables.splitlines():
        if line.startswith("|"):
            assert "||" not in line.replace("\\|", ""), line
            assert "| |" not in line, line
    for row in _rows(tables):
        assert all(cell for cell in row), row


def test_the_tables_match_the_golden_format(adm: ModuleType) -> None:
    staffing = _table_staffing()
    tables = _tables(adm, _table_record(adm, staffing), staffing)
    assert tables == GOLDEN_TABLES
    _assert_no_empty_cell(tables)


def test_the_tables_are_titled_in_bold_and_never_with_a_heading(adm: ModuleType) -> None:
    """A heading line pasted into a skill would split its gate-record sections."""
    for line in GOLDEN_TABLES.splitlines():
        assert not line.startswith("#"), line
    assert GOLDEN_TABLES.splitlines()[0] == adm.STAFFING_TITLE


def test_a_recorded_suggestion_renders_with_its_confidence(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    value = record.run_configuration["staffing_models_and_efforts"]["value"]
    value["planner"]["suggestion"] = {
        "suggested": "opus/xhigh",
        "confidence": 0.72,
        "usable": True,
        "low_confidence": False,
    }
    value["worker"]["suggestion"] = {"suggested": None, "usable": False, "problem": "timeout"}
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["planner"][2] == "opus/xhigh (0.72)"
    assert rows["worker"][2] == "no suggestion"
    # A suggestion below the confidence floor, as ``--suggest`` records it, is not shown.
    value["planner"]["suggestion"] = {
        "suggested": "opus/xhigh",
        "confidence": 0.55,
        "usable": True,
        "low_confidence": True,
    }
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["planner"][2] == "no suggestion"


def test_the_tier_judgment_block_is_read_when_present(adm: ModuleType) -> None:
    """The per-role block issue #96 writes, and the raise it applies beside the default."""
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    value = record.run_configuration["staffing_models_and_efforts"]["value"]
    value["planner"]["tier_judgment"] = {
        "band": "auto-raise",
        "confidence": 0.86,
        "default": {"model": "opus", "effort": "high"},
        "proposed": {"model": "opus", "effort": "xhigh"},
        "applied": True,
        "shown": True,
        "reason": "the change is a gate",
    }
    value["planner"]["jev_raise"] = {
        "model": "opus",
        "effort": "xhigh",
        "confidence": 0.86,
        "reason": "the change is a gate",
    }
    value["worker"]["tier_judgment"] = {"band": "log-only", "confidence": 0.41, "shown": False}
    value["_tier_judgment"] = {"status": "ok", "note": ""}
    tables = _tables(adm, record, staffing)
    rows = {row[0]: row for row in _rows(tables)}
    assert rows["planner"][1:] == [
        "claude opus/high",
        "opus/xhigh (0.86, raise applied)",
        "claude opus/xhigh",
        "Jev raise: the change is a gate",
    ]
    assert rows["worker"][2] == "no suggestion"
    assert "_tier_judgment" not in rows
    _assert_no_empty_cell(tables)


def test_a_switched_off_judgment_reads_not_configured(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    value = record.run_configuration["staffing_models_and_efforts"]["value"]
    value["_tier_judgment"] = {"status": "off", "note": "INFIQUETRA_TYPESAFE_TIERING=off"}
    for role in ("planner", "worker"):
        value[role]["tier_judgment"] = {"band": "not-consulted"}
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["planner"][2] == rows["worker"][2] == "not configured"


def test_an_operator_override_keeps_the_fresh_default_and_says_why(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = adm.apply_answers(
        _table_record(adm, staffing),
        {"staffing_overrides": {"worker": {"vendor": "claude", "model": "opus", "effort": "low"}}},
    )
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][1] == "claude sonnet/medium"
    assert rows["worker"][3] == "claude opus/low"
    assert rows["worker"][4] == "operator answer"


def test_an_operator_lens_declaration_renders_with_escaped_reasons(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = adm.apply_answers(
        _table_record(adm, staffing),
        {
            "lens_declaration": {
                "always_on": ["correctness", "security"],
                "conditional_applies": {"performance": "a hot loop | per request"},
                "conditional_does_not_apply": {"privacy": "no personal\ndata is touched"},
            }
        },
    )
    tables = _tables(adm, record, staffing)
    assert "| performance | yes | a hot loop \\| per request | not configured |" in tables
    assert "| privacy | no | no personal data is touched | not configured |" in tables
    _assert_no_empty_cell(tables)


def test_a_lens_proposal_renders_its_probability_bands(adm: ModuleType) -> None:
    """The read contract with issue #110: ``admission.lens_proposal.probabilities``."""
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    record.admission["lens_proposal"] = {
        "ok": True,
        "probabilities": {"performance": 0.85, "privacy": 0.7, "security": 0.4},
    }
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["performance"][3] == "0.85 (pre-checked)"
    assert rows["privacy"][3] == "0.70 (consider)"
    assert rows["security"][3] == "no suggestion"
    assert rows["correctness"][3] == "no suggestion"
    # Below 0.6 a probability is logged, not shown (issue #110); the JSON row keeps it.
    record.admission["lens_proposal"]["probabilities"] = {"performance": 0.4}
    data = adm.review_data(record, [], staffing, None)
    rows = {row[0]: row for row in _rows(adm.render_tables(data))}
    assert rows["performance"][3] == "no suggestion"
    assert rows["privacy"][3] == "no suggestion"
    performance = next(row for row in data["lenses"]["rows"] if row["lens"] == "performance")
    assert performance["jev"] == {
        "cell": "no suggestion",
        "state": "below-threshold",
        "probability": 0.4,
    }


@pytest.mark.parametrize(
    ("probability", "cell"),
    [
        (0.8, "0.80 (pre-checked)"),
        (0.79, "0.79 (consider)"),
        (0.6, "0.60 (consider)"),
        (0.59, "no suggestion"),
    ],
)
def test_the_lens_probability_band_edges(adm: ModuleType, probability: float, cell: str) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    record.admission["lens_proposal"] = {"probabilities": {"performance": probability}}
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["performance"][3] == cell


def test_unreachable_staffing_and_catalogue_render_placeholder_rows(adm: ModuleType) -> None:
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=102, repo="infiquetra/infiquetra-agent-plugins")
    tables = _tables(adm, record, None)
    rows = _rows(tables)
    data = adm.review_data(record, [], None, None)
    # The JSON carries a typed state and no placeholder rows, so a pane never parses prose.
    assert data["staffing"]["status"] == "unreachable"
    assert data["staffing"]["rows"] == []
    assert data["lenses"]["status"] == "catalogue-unreadable"
    assert data["lenses"]["rows"] == []
    assert rows == [
        [
            "(staffing component unreachable)",
            "not configured",
            "not configured",
            "not configured",
            "not configured",
        ],
        [
            "(lens catalogue unreadable)",
            "undeclared",
            "the lens catalogue could not be read",
            "not configured",
        ],
    ]
    _assert_no_empty_cell(tables)


def _run_main(adm: ModuleType, store: Path, repo_root: Path, *extra: str) -> int:
    return adm.main(
        [
            "--issue",
            "102",
            "--repo",
            "infiquetra/infiquetra-agent-plugins",
            "--store-root",
            str(store),
            "--repo-root",
            str(repo_root),
            "--dry-run",
            *extra,
        ]
    )


def _patch_main(adm: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adm, "load_card_validator", lambda: _passing_validator)
    monkeypatch.setattr(adm, "load_staffing", _table_staffing)
    monkeypatch.setattr(adm, "fetch_issue", lambda *_a, **_k: {"number": 102, "body": _good_card()})


def test_render_tables_prints_the_summary_then_the_golden_block(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_main(adm, monkeypatch)
    assert _run_main(adm, store, repo_root, "--render", "tables") == 0
    out = capsys.readouterr().out
    assert out.startswith("Admission for issue 102")
    assert out.rstrip("\n").endswith("\n\n" + GOLDEN_TABLES)
    assert list(store.glob("*.json")) == []


def test_the_default_render_is_the_summary_alone(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_main(adm, monkeypatch)
    assert _run_main(adm, store, repo_root) == 0
    assert adm.STAFFING_TITLE not in capsys.readouterr().out


def test_render_json_carries_the_rows_and_the_palette(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_main(adm, monkeypatch)
    assert _run_main(adm, store, repo_root, "--render", "json") == 0
    data = json.loads(capsys.readouterr().out)
    tier_palette = _load("bundled_fleet").load("tier_palette")
    assert data["schema"] == "admission_review.v1"
    assert data["staffing"]["status"] == "ok"
    assert data["lenses"]["status"] == "ok"
    assert data["tables_markdown"] == GOLDEN_TABLES
    assert "staffing_overrides" in data["pending_questions"]
    assert [row["role"] for row in data["staffing"]["rows"]] == ["planner", "worker"]
    assert data["staffing"]["rows"][0]["jev"]["state"] == "not-configured"
    assert data["lenses"]["catalogue_version"] == "1.0.0"
    assert data["palette"]["models"] == list(tier_palette.MODELS)
    assert {"model": "haiku", "effort": "xhigh"} not in data["palette"]["pairs"]
    assert {"model": "haiku", "effort": "high"} in data["palette"]["pairs"]


def test_the_help_documents_the_render_option(adm: ModuleType) -> None:
    text = adm.build_parser().format_help()
    assert "--render" in text
    for choice in ("summary", "tables", "json"):
        assert choice in text


def test_the_plan_skill_prints_the_tables_exactly_as_rendered(adm: ModuleType) -> None:
    skill = (REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    section = skill.split("### 0.1b")[1].split("### 0.2")[0]
    assert "--render tables" in section
    assert "exactly as rendered" in section
    assert adm.STAFFING_TITLE in section
    # No heading inside the section: it would split the gate-record marker's coverage.
    assert [line for line in section.splitlines()[1:] if line.startswith("#")] == []


def _judgment(band: str, **extra: Any) -> dict[str, Any]:
    return {
        "band": band,
        "confidence": 0.71,
        "default": {"model": "opus", "effort": "high"},
        "proposed": {"model": "opus", "effort": "xhigh"},
        "shown": True,
        **extra,
    }


@pytest.mark.parametrize(
    ("judgment", "cell"),
    [
        # 'agrees' shows the default, not the proposed tier.
        (_judgment("agrees"), "opus/high (0.71, agrees)"),
        (_judgment("auto-raise"), "opus/xhigh (0.71, raise applied)"),
        (_judgment("confirm-raise"), "opus/xhigh (0.71, raise to confirm)"),
        (
            _judgment("advisory-lower", proposed={"model": "opus", "effort": "medium"}),
            "opus/medium (0.71, advisory lower)",
        ),
        # issue #96 records no proposed tier at the ceiling.
        (_judgment("raise-at-ceiling", proposed=None), "at ceiling (0.71)"),
        # A known band the judgment says not to show.
        (_judgment("confirm-raise", shown=False), "no suggestion"),
        (_judgment("raise-at-ceiling", proposed=None, shown=False), "no suggestion"),
        (_judgment("log-only", shown=False), "no suggestion"),
        ({"band": "not-consulted"}, "not configured"),
    ],
)
def test_every_tier_judgment_band_renders_its_cell(
    adm: ModuleType, judgment: dict[str, Any], cell: str
) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    record.run_configuration["staffing_models_and_efforts"]["value"]["planner"]["tier_judgment"] = (
        judgment
    )
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["planner"][2] == cell


@pytest.mark.parametrize(
    ("status", "cell"),
    [("failed", "no suggestion"), ("ok", "no suggestion"), ("off", "not configured")],
)
def test_the_run_wide_consult_status_decides_an_empty_jev_cell(
    adm: ModuleType, status: str, cell: str
) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    value = record.run_configuration["staffing_models_and_efforts"]["value"]
    value["_tier_judgment"] = {"status": status, "note": "timeout"}
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["planner"][2] == rows["worker"][2] == cell


def test_a_repository_overlay_tier_is_named_in_the_why_column(adm: ModuleType) -> None:
    """Coordinator ruling 7: the overlay is its own rung, and it outranks a recorded raise."""
    staffing = _table_staffing(sources={"worker": "overlay", "planner": "policy"})
    record = _table_record(adm, staffing)
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert (
        rows["worker"][4] == "repository overlay (.saga/tier-defaults.json, work shape mechanical)"
    )
    assert rows["planner"][4] == "staffing default (work shape judgment)"
    value = record.run_configuration["staffing_models_and_efforts"]["value"]
    value["worker"]["jev_raise"] = {"model": "sonnet", "effort": "high", "reason": "risky"}
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][3] == "claude sonnet/medium"
    assert rows["worker"][4].endswith("; the overlay outranks the recorded Jev raise")


@pytest.mark.parametrize(
    ("raise_", "reason"),
    [
        ({"model": "fable", "effort": "max"}, "it names fable"),
        ({"model": "opus", "effort": "max"}, "it names max"),
        ({"model": "opus", "effort": "high"}, "it is not exactly one step above the default"),
        ({"model": "sonnet", "effort": "xhigh"}, "it is not exactly one step above the default"),
    ],
)
def test_an_out_of_policy_jev_raise_is_never_shown_as_proposed(
    adm: ModuleType, raise_: dict[str, str], reason: str
) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    record.run_configuration["staffing_models_and_efforts"]["value"]["worker"]["jev_raise"] = {
        **raise_,
        "reason": "bigger is better",
    }
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][3] == "claude sonnet/medium"
    assert rows["worker"][4] == (
        "staffing default (work shape mechanical); recorded Jev raise to "
        f"{raise_['model']}/{raise_['effort']} refused: {reason}"
    )


def test_a_jev_raise_from_a_default_at_the_ceiling_is_refused(adm: ModuleType) -> None:
    """opus/xhigh has no step above it, so any recorded raise is refused."""
    staffing = _table_staffing(worker=("opus", "xhigh"))
    record = _table_record(adm, staffing)
    record.run_configuration["staffing_models_and_efforts"]["value"]["worker"]["jev_raise"] = {
        "model": "opus",
        "effort": "high",
        "reason": "bigger is better",
    }
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][3] == "claude opus/xhigh"
    assert rows["worker"][4] == (
        "staffing default (work shape mechanical); recorded Jev raise to opus/high refused: "
        "it is not exactly one step above the default"
    )


def test_a_one_step_model_raise_is_shown_as_proposed(adm: ModuleType) -> None:
    """At the effort ceiling, the one step is to the next model: sonnet/xhigh to opus/xhigh."""
    staffing = _table_staffing(worker=("sonnet", "xhigh"))
    record = _table_record(adm, staffing)
    record.run_configuration["staffing_models_and_efforts"]["value"]["worker"]["jev_raise"] = {
        "model": "opus",
        "effort": "xhigh",
        "reason": "the change crosses a trust boundary",
    }
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][3] == "claude opus/xhigh"
    assert rows["worker"][4] == "Jev raise: the change crosses a trust boundary"


def test_a_jev_raise_is_refused_when_the_palette_cannot_be_read(
    adm: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    record.run_configuration["staffing_models_and_efforts"]["value"]["worker"]["jev_raise"] = {
        "model": "sonnet",
        "effort": "high",
        "reason": "the change touches a gate",
    }

    def broken_load(_name: str) -> Any:
        raise RuntimeError("palette unreadable")

    monkeypatch.setitem(sys.modules, "bundled_fleet", SimpleNamespace(load=broken_load))
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][3] == "claude sonnet/medium"
    assert rows["worker"][4].endswith("refused: the tier palette could not be read to check it")


def test_a_one_step_jev_raise_is_shown_as_proposed(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    record.run_configuration["staffing_models_and_efforts"]["value"]["worker"]["jev_raise"] = {
        "model": "sonnet",
        "effort": "high",
        "reason": "the change touches a gate",
    }
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][3] == "claude sonnet/high"
    assert rows["worker"][4] == "Jev raise: the change touches a gate"


def test_a_merged_operator_answer_marks_only_the_overridden_rows(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    block = record.run_configuration["staffing_models_and_efforts"]
    block["source"] = "operator"
    block["value"]["worker"].update({"model": "opus", "effort": "low", "operator_override": True})
    block["value"]["planner"]["operator_override"] = False
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][4] == "operator answer"
    assert rows["planner"][4] == "staffing default (work shape judgment)"


@pytest.mark.parametrize("merged", [False, True])
def test_an_operator_answer_outranks_a_repository_overlay(adm: ModuleType, merged: bool) -> None:
    """Coordinator ruling 7: the operator's answer is the top rung, above the overlay."""
    staffing = _table_staffing(sources={"worker": "overlay"})
    record = _table_record(adm, staffing)
    if merged:
        block = record.run_configuration["staffing_models_and_efforts"]
        block["source"] = "operator"
        block["value"]["worker"].update(
            {"model": "opus", "effort": "low", "operator_override": True}
        )
    else:
        record = adm.apply_answers(
            record,
            {
                "staffing_overrides": {
                    "planner": {"vendor": "claude", "model": "opus", "effort": "high"},
                    "worker": {"vendor": "claude", "model": "opus", "effort": "low"},
                }
            },
        )
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    assert rows["worker"][3] == "claude opus/low"
    assert rows["worker"][4] == "operator answer"


def test_a_failed_role_resolve_falls_back_to_the_recorded_default(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    rows = {
        row[0]: row for row in _rows(_tables(adm, record, _table_staffing(failing=("worker",))))
    }
    assert rows["worker"][1] == "claude sonnet/medium"


def test_an_unreadable_catalogue_still_shows_the_operator_declaration(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = adm.apply_answers(
        _table_record(adm, staffing),
        {
            "lens_declaration": {
                "always_on": ["correctness"],
                "conditional_applies": ["performance"],
                "conditional_does_not_apply": {"privacy": "no personal data"},
            }
        },
    )

    def broken_catalogue(**_kwargs: Any) -> Any:
        raise RuntimeError("catalogue unreadable")

    broken = _table_staffing()
    broken.lens_catalogue = broken_catalogue
    data = adm.review_data(record, [], broken, None)
    assert data["lenses"]["status"] == "catalogue-unreadable"
    rows = {row[0]: row for row in _rows(adm.render_tables(data))}
    assert rows["correctness"][1] == "always on"
    assert rows["performance"][1:3] == ["yes", "included"]
    assert rows["privacy"][1:3] == ["no", "no personal data"]


def test_a_lens_in_both_maps_is_listed_once_and_excluded_without_a_catalogue(
    adm: ModuleType,
) -> None:
    staffing = _table_staffing()
    record = adm.apply_answers(
        _table_record(adm, staffing),
        {
            "lens_declaration": {
                "always_on": ["correctness"],
                "conditional_applies": {"performance": "hot path"},
                "conditional_does_not_apply": {"performance": "no hot path"},
            }
        },
    )

    def broken_catalogue(**_kwargs: Any) -> Any:
        raise RuntimeError("catalogue unreadable")

    broken = _table_staffing()
    broken.lens_catalogue = broken_catalogue
    rows = _rows(adm.render_tables(adm.review_data(record, [], broken, None)))
    performance = [row for row in rows if row[0] == "performance"]
    assert len(performance) == 1
    assert performance[0][1:3] == ["no", "no hot path"]


@pytest.mark.parametrize(
    "declaration",
    [
        {"conditional_applies": ["performance"], "conditional_does_not_apply": {"privacy": "x"}},
        {"conditional_applies": {"performance": "hot"}, "conditional_does_not_apply": ["privacy"]},
        {
            "conditional_applies": {"performance": "hot path"},
            "conditional_does_not_apply": {"performance": "no hot path"},
        },
    ],
)
def test_the_table_and_the_review_roster_agree_on_a_declaration(
    adm: ModuleType, declaration: dict[str, Any]
) -> None:
    """A list for ``conditional_does_not_apply`` is ignored by the review, so the table too."""
    roster = _load("review_roster")
    staffing = _table_staffing()
    record = adm.apply_answers(
        _table_record(adm, staffing),
        {"lens_declaration": {"always_on": ["correctness", "security"], **declaration}},
    )
    rows = {row[0]: row for row in _rows(_tables(adm, record, staffing))}
    entries = roster._lens_entries(declaration)
    for lens in ("performance", "privacy"):
        if lens not in entries:
            assert rows[lens][1] == "undeclared"
        else:
            assert rows[lens][1] == ("yes" if entries[lens]["applies"] else "no")
            if entries[lens].get("reason"):
                assert rows[lens][2] == entries[lens]["reason"]


def test_an_override_answered_as_the_skill_documents_keeps_every_role(adm: ModuleType) -> None:
    """The plan skill asks for the complete role map, because apply_answers replaces the map."""
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    data = adm.review_data(record, adm.outstanding_questions(record), staffing, None)
    answer = {
        row["role"]: {key: row["proposed"][key] for key in ("vendor", "model", "effort")}
        for row in data["staffing"]["rows"]
    }
    answer["worker"] = {"vendor": "claude", "model": "opus", "effort": "low"}
    after = adm.apply_answers(record, {"staffing_overrides": answer})
    value = after.run_configuration["staffing_models_and_efforts"]["value"]
    assert sorted(value) == ["planner", "worker"]
    assert value["worker"]["model"] == "opus"
    skill = (REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "the complete role map" in skill
    assert "for each role the operator changes" not in skill
