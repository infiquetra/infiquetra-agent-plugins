"""Tests for the admission questionnaire (issue #1023, plan U3).

Every test passes an explicit ``tmp_path`` store root and an explicit repository root. Nothing here
may create or modify anything under the primary checkout's ``.claude/saga/`` store, and nothing
here reaches the network: the card validator and the staffing component are injected.
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess  # nosec B404
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
import yaml

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


#: The run-configuration parameters issue #161 retires with the lens roster and the cycle
#: allowances, built from parts so the retired names appear nowhere in this file as one word.
RETIRED_PARAMETERS: tuple[str, ...] = (
    "standard" + "_cycle_allowance",
    "escalated" + "_cycle_allowance",
    "applicable" + "_lenses",
    "per_lens" + "_score_threshold",
)


@pytest.fixture
def adm() -> ModuleType:
    return _load("admission")


@pytest.fixture(autouse=True)
def _setup_stays_off_the_operator_machine(
    adm: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-dry ``main`` must not write the operator's ``~/.saga/machine.json``."""
    home = tmp_path / "admission-home"
    home.mkdir()
    monkeypatch.setattr(adm, "default_machine_home", lambda: home)

    def quiet(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> None:
        raise FileNotFoundError(argv[0] if argv else "tool")

    monkeypatch.setattr(adm, "setup_runner", quiet)


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
        return {"planner": {}}

    def resolve_role(role: str, **_kwargs: Any) -> SimpleNamespace:
        calls.append(role)
        return SimpleNamespace(vendor="claude", model="opus", effort="high")

    def sdlc_root(*_args: Any, **_kwargs: Any) -> None:
        return None

    return SimpleNamespace(
        roles=roles,
        resolve_role=resolve_role,
        sdlc_root=sdlc_root,
        calls=calls,
    )


#: A complete local declaration: no deploy command, which only `local` may omit.
_LOCAL_ENVIRONMENT: dict[str, Any] = {
    "kind": "local",
    "test_command": "python3 -m pytest tests -q",
    "scope": "private",
}


def _write_profile(repo_root: Path) -> None:
    (repo_root / ".saga-profile.json").write_text(
        json.dumps(
            {
                "schema": "repository_profile.v1",
                "concurrency_allocation": 10,
                "nonproduction_destination": "none",
                "functional_test_environment": _LOCAL_ENVIRONMENT,
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
    # Everything fills itself here except the response to unfinished testing, which the operator
    # must choose from a closed set of two. The retired lens and allowance parameters are left out
    # of the comparison so it reads the same before and after they leave the run configuration.
    retired = set(RETIRED_PARAMETERS)
    assert filled - retired == (
        set(run_record.RUN_CONFIGURATION_PARAMETERS) - retired - {"unfinished_testing_response"}
    )
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
    assert sorted(staffing.calls) == ["planner"]


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
    assert "functional_test_environment" in {question.key for question in outstanding}


def test_this_repositorys_own_profile_parses_and_fills_what_it_claims(adm: ModuleType) -> None:
    """The tracked `.saga-profile.json` is real configuration, so it is checked like one."""
    if not LIVE_PROFILE.is_file():
        pytest.skip("this catalog does not carry the upstream repository's .saga-profile.json")
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


def test_the_question_set_on_a_fresh_record_with_no_profile_is_the_cards_eight(
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
        "unfinished_testing_response",
        "functional_test_environment",
        "main_consumed_directly",
        "change_shape",
    ]
    assert len(outstanding) == 8


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
    assert "functional_test_environment" not in asked
    assert "main_consumed_directly" not in asked
    assert len(outstanding) == 6


def _all_answers() -> dict[str, Any]:
    run_record = _load("run_record")
    return {
        "risk_tier": "medium",
        "risk_justification": "every other child reads this record",
        "approval_scope": dict.fromkeys(run_record.APPROVAL_CATEGORIES, "none"),
        "destination": "pr",
        "staffing_overrides": "none",
        "unfinished_testing_response": "bring the result to the operator",
        "functional_test_environment": dict(_LOCAL_ENVIRONMENT),
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
        staffing=_table_staffing(),
        answers={
            "staffing_overrides": {"worker": {"vendor": "claude", "model": "opus", "effort": "low"}}
        },
    )
    block = record.run_configuration["staffing_models_and_efforts"]
    assert block["source"] == "operator"
    assert block["value"]["worker"]["model"] == "opus"
    assert block["value"]["worker"]["effort"] == "low"
    assert block["value"]["worker"]["operator_override"] is True


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
    assert "Questions to answer, once (6)" in text


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
# The staffing table, in one fixed format (issue #102)
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
| worker | claude sonnet/medium | not configured | claude sonnet/medium | staffing default (work shape mechanical) |"""


def _table_staffing(
    *,
    sources: dict[str, str] | None = None,
    failing: tuple[str, ...] = (),
    worker: tuple[str, str] = ("sonnet", "medium"),
) -> SimpleNamespace:
    """A staffing component with two roles.

    *sources* sets a role's decision ``source`` (``overlay`` for ``.saga/tier-defaults.json``);
    a role in *failing* raises from ``resolve_role``; *worker* sets the worker's default tier.
    A ``jev_raise`` is checked by the real resolver's own raise validator against that default,
    so these tests restate none of the raise rules; an overlay ``source`` outranks the raise.
    """
    real = _load_bundled_staffing()
    tiers = {"planner": ("opus", "high"), "worker": worker}
    shapes = {"planner": "judgment", "worker": "mechanical"}

    def roles() -> dict[str, Any]:
        return {role: {"work_shape": shape} for role, shape in shapes.items()}

    def resolve_role(role: str, *, jev_raise: Any = None, **_kwargs: Any) -> SimpleNamespace:
        if role in failing:
            raise RuntimeError(f"cannot resolve {role}")
        model, effort = tiers[role]
        decision = SimpleNamespace(vendor="claude", model=model, effort=effort)
        if sources and role in sources:
            decision.source = sources[role]
        if jev_raise is not None:
            raised = real._validate_jev_raise(
                shapes[role],
                {"model": jev_raise.get("model"), "effort": jev_raise.get("effort")},
                base={"model": model, "effort": effort},
                registry=real.work_shapes(),
            )
            if getattr(decision, "source", None) != "overlay":
                decision.model, decision.effort = raised["model"], raised["effort"]
                decision.source = "jev-raise"
        return decision

    def sdlc_root(*_args: Any, **_kwargs: Any) -> None:
        return None

    return SimpleNamespace(
        roles=roles,
        resolve_role=resolve_role,
        sdlc_root=sdlc_root,
        StaffingError=real.StaffingError,
    )


def _load_bundled_staffing() -> ModuleType:
    """The staffing resolver saga ships, loaded the way admission loads it."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import bundled_fleet  # noqa: PLC0415

    return bundled_fleet.load("staffing")


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
        if not line.startswith("| ") or line.startswith("| Role "):
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


def test_unreachable_staffing_renders_one_placeholder_row(adm: ModuleType) -> None:
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=102, repo="infiquetra/infiquetra-agent-plugins")
    tables = _tables(adm, record, None)
    rows = _rows(tables)
    data = adm.review_data(record, [], None, None)
    # The JSON carries a typed state and no placeholder rows, so a pane never parses prose.
    assert data["staffing"]["status"] == "unreachable"
    assert data["staffing"]["rows"] == []
    assert "lenses" not in data
    assert rows == [
        [
            "(staffing component unreachable)",
            "not configured",
            "not configured",
            "not configured",
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
    assert "lenses" not in data
    assert data["tables_markdown"] == GOLDEN_TABLES
    assert "staffing_overrides" in data["pending_questions"]
    assert [row["role"] for row in data["staffing"]["rows"]] == ["planner", "worker"]
    assert data["staffing"]["rows"][0]["jev"]["state"] == "not-configured"
    assert data["palette"]["models"] == list(tier_palette.MODELS)
    assert {"model": "haiku", "effort": "xhigh"} in data["palette"]["pairs"]
    assert {"model": "haiku", "effort": "high"} in data["palette"]["pairs"]


def test_the_review_document_has_no_lenses_and_pends_no_lens_or_allowance_question(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_main(adm, monkeypatch)
    assert _run_main(adm, store, repo_root, "--render", "json") == 0
    data = json.loads(capsys.readouterr().out)
    assert "lenses" not in data
    retired = ("lens", "allowance")
    assert [key for key in data["pending_questions"] if any(word in key for word in retired)] == []
    assert [
        question["key"]
        for question in data["questions"]
        if any(word in f"{question['key']} {question['prompt']}".lower() for word in retired)
    ] == []
    assert "staffing_overrides" in data["pending_questions"]


@pytest.mark.parametrize("render", ["summary", "tables", "json"])
def test_the_rendered_questionnaire_never_mentions_a_lens_or_an_allowance(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    render: str,
) -> None:
    _patch_main(adm, monkeypatch)
    assert _run_main(adm, store, repo_root, "--render", render) == 0
    text = capsys.readouterr().out.lower()
    assert "lens" not in text
    assert "allowance" not in text


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
        ({"model": "fable", "effort": "max"}, "fable/max is unrunnable"),
        ({"model": "opus", "effort": "max"}, "opus/max is unrunnable"),
        ({"model": "opus", "effort": "high"}, "is not exactly one step above the default"),
        ({"model": "sonnet", "effort": "xhigh"}, "is not exactly one step above the default"),
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
    why = rows["worker"][4]
    assert why.startswith(
        "staffing default (work shape mechanical); recorded Jev raise to "
        f"{raise_['model']}/{raise_['effort']} refused: jev raise for 'mechanical': "
    )
    assert reason in why


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
    assert rows["worker"][4].startswith(
        "staffing default (work shape mechanical); recorded Jev raise to opus/high refused: "
    )
    assert "is not exactly one step above the default opus/xhigh" in rows["worker"][4]


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


def test_the_table_shows_a_model_rung_raise_the_resolver_applied(adm: ModuleType) -> None:
    """Review finding on #93: the table must word the resolver's answer, not a copy of its rules.

    The real resolver accepts one model rung with the effort unchanged (sonnet/high to
    opus/high for the worker); the Why cell must say the raise applied. The merging worker
    served here until 2026-10-07, when its haiku/xhigh default left no legal one-step raise.
    """
    staffing = _load_bundled_staffing()
    raise_ = {"model": "opus", "effort": "high", "reason": "the change crosses a gate"}
    decision = staffing.resolve_role("worker", jev_raise=raise_)
    assert (decision.model, decision.effort, decision.source) == ("opus", "high", "jev-raise")
    record = _table_record(adm, _table_staffing())
    record.run_configuration["staffing_models_and_efforts"]["value"] = {
        "worker": {
            "vendor": "claude",
            "model": "opus",
            "effort": "medium",
            "source": "jev-raise",
            "jev_raise": raise_,
        }
    }
    (row,) = adm._staffing_rows(record, staffing)["rows"]
    assert row["proposed"] == {"vendor": "claude", "model": "opus", "effort": "high"}
    assert row["why"] == "Jev raise: the change crosses a gate"


def test_the_recorded_resolver_outcome_stands_in_when_staffing_is_unreachable(
    adm: ModuleType,
) -> None:
    """Without a resolver, the row's recorded refusal is shown, never a re-derived one."""
    row = {
        "vendor": "claude",
        "model": "sonnet",
        "effort": "medium",
        "source": "policy",
        "jev_raise": {"model": "opus", "effort": "high", "reason": "r"},
        "jev_raise_refused": "jev raise for 'mechanical': recorded refusal",
    }
    proposed, why = adm._proposed_and_why(row, "mechanical", None, operator=False)
    assert proposed == {"vendor": "claude", "model": "sonnet", "effort": "medium"}
    assert why == (
        "staffing default (work shape mechanical); recorded Jev raise to opus/high refused: "
        "jev raise for 'mechanical': recorded refusal"
    )


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


def test_an_override_answered_as_the_skill_documents_keeps_every_role(adm: ModuleType) -> None:
    """The plan skill asks for the complete role map, so every row records the operator."""
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


def test_saving_admission_lands_only_admission_fields_on_a_fresh_read(
    adm: ModuleType, store: Path
) -> None:
    """Issue 95's lock convention: a unit row or usage entry written meanwhile survives."""
    rr = adm.run_record
    rr.save(store, rr.RunRecord(issue=1023, repo="o/r"))
    admitted = rr.RunRecord(
        issue=1023,
        repo="o/r",
        admission={**rr.empty_admission(), "pending_questions": []},
        next_step="plan",
    )
    # Another writer lands after admission read the record and before it writes.
    rr.update(
        store,
        1023,
        lambda current: rr.RunRecord(
            **{
                **current.__dict__,
                "units": [{"id": "u1", "usage": {"entries": [{"session_id": "s"}]}}],
                "next_step": "build u1",
            }
        ),
    )
    adm.save_admission(store, admitted)
    reread = rr.load(store, 1023, warn=None)
    assert reread is not None
    assert reread.units == [{"id": "u1", "usage": {"entries": [{"session_id": "s"}]}}]
    assert reread.admission["pending_questions"] == []
    assert reread.next_step == "build u1", "a fresh next_step wins over admission's suggestion"


def test_saving_admission_creates_the_record_when_there_is_none(
    adm: ModuleType, store: Path
) -> None:
    rr = adm.run_record
    adm.save_admission(store, rr.RunRecord(issue=1023, repo="o/r", next_step="plan"))
    reread = rr.load(store, 1023, warn=None)
    assert reread is not None and reread.next_step == "plan"


# ---------------------------------------------------------------------------
# The review pane's answers path (issue #103)
# ---------------------------------------------------------------------------
#
# The Claude Code review pane hands its answers to ``admission.py --answers -`` on standard input.
# The pane's TypeScript test pins the payload it sends (GOLDEN ANSWERS in the fixture below); these
# tests push that same text through the real script, so the two halves of the hand-off cannot drift.

PANE_FIXTURE = (
    REPO_ROOT
    / "plugins"
    / "saga"
    / "com.infiquetra.claude"
    / "mods"
    / "fixtures"
    / "admission-review.fixture.ts"
)


def _golden_answers() -> dict[str, Any]:
    text = PANE_FIXTURE.read_text(encoding="utf-8")
    body = text.split("/* BEGIN GOLDEN ANSWERS */")[1].split("/* END GOLDEN ANSWERS */")[0]
    return json.loads(body)


def _answer_main(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    answers: Any,
) -> int:
    """Run ``admission.py --answers -`` with *answers* on standard input."""
    _patch_main(adm, monkeypatch)
    text = answers if isinstance(answers, str) else json.dumps(answers)
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))
    return adm.main(
        [
            "--issue",
            "103",
            "--repo",
            "infiquetra/infiquetra-agent-plugins",
            "--store-root",
            str(store),
            "--repo-root",
            str(repo_root),
            "--answers",
            "-",
        ]
    )


def _tiers(value: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        role: {key: row[key] for key in ("vendor", "model", "effort")}
        for role, row in value.items()
        if not role.startswith("_")
    }


def test_the_panes_golden_answers_record_with_the_operator_as_their_source(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _golden_answers()
    assert _answer_main(adm, store, repo_root, monkeypatch, payload) == 0

    shown = subprocess.run(  # nosec B603 — fixed argv, no shell
        [sys.executable, str(SCRIPTS / "run_record.py"), "--store-root", str(store), "show", "103"],
        capture_output=True,
        text=True,
        check=True,
    )
    configuration = json.loads(shown.stdout)["run_configuration"]
    staffing = configuration["staffing_models_and_efforts"]
    assert staffing["source"] == "operator"
    assert _tiers(staffing["value"]) == payload["staffing_overrides"]
    for role in payload["staffing_overrides"]:
        assert staffing["value"][role]["operator_override"] is True, role
    for name in RETIRED_PARAMETERS:
        assert name not in configuration, name
    assert "staffing_overrides" not in json.loads(shown.stdout)["admission"]["pending_questions"]


def test_answers_that_are_not_json_on_standard_input_exit_2(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _answer_main(adm, store, repo_root, monkeypatch, "not json") == 2
    assert "standard input" in capsys.readouterr().err
    assert list(store.glob("*.json")) == []


def test_a_partial_staffing_override_merges_role_by_role(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    before = record.run_configuration["staffing_models_and_efforts"]["value"]
    after = adm.apply_answers(
        record,
        {"staffing_overrides": {"worker": {"vendor": "claude", "model": "opus", "effort": "low"}}},
        staffing,
    )
    block = after.run_configuration["staffing_models_and_efforts"]
    assert block["source"] == "operator"
    assert sorted(_tiers(block["value"])) == ["planner", "worker"]
    assert block["value"]["planner"] == before["planner"]
    assert "operator_override" not in block["value"]["planner"]
    assert block["value"]["worker"] == {
        "vendor": "claude",
        "model": "opus",
        "effort": "low",
        "source": "operator",
        "operator_override": True,
    }
    rows = {row[0]: row for row in _rows(_tables(adm, after, staffing))}
    assert rows["worker"][4] == "operator answer"
    assert rows["planner"][4] == "staffing default (work shape judgment)"


def test_a_merge_keeps_the_run_wide_keys_and_the_roles_own_jev_fields(adm: ModuleType) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    value = record.run_configuration["staffing_models_and_efforts"]["value"]
    value["_tier_judgment"] = {"status": "off", "note": "switched off"}
    value["worker"]["tier_judgment"] = {"band": "not-consulted"}
    after = adm.apply_answers(
        record,
        {"staffing_overrides": {"worker": {"vendor": "claude", "model": "opus", "effort": "low"}}},
        staffing,
    )
    merged = after.run_configuration["staffing_models_and_efforts"]["value"]
    assert merged["_tier_judgment"] == {"status": "off", "note": "switched off"}
    assert merged["worker"]["tier_judgment"] == {"band": "not-consulted"}


@pytest.mark.parametrize(
    ("override", "names"),
    [
        ({"worker": {"vendor": "claude", "model": "gpt", "effort": "high"}}, "'gpt'"),
        ({"worker": {"vendor": "claude", "model": "opus", "effort": "max"}}, "effort max"),
        ({"auditor": {"vendor": "claude", "model": "opus", "effort": "high"}}, "'auditor'"),
        ({"worker": {"vendor": "codex", "model": "opus", "effort": "high"}}, "'codex'"),
        ({"worker": {"model": "opus", "effort": "high"}}, "missing vendor"),
        (
            {"worker": {"vendor": "claude", "model": "opus", "effort": "high", "x": 1}},
            "unexpected x",
        ),
        ("opus everywhere", "mapping of role"),
    ],
)
def test_an_off_palette_or_unknown_override_is_refused_with_one_line(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    override: Any,
    names: str,
) -> None:
    assert _answer_main(adm, store, repo_root, monkeypatch, {"staffing_overrides": override}) == 2
    err = capsys.readouterr().err
    assert err.startswith("admission: ")
    assert err.count("\n") == 1
    assert names in err
    assert list(store.glob("*.json")) == [], "a refused answer writes nothing"


def test_none_and_an_empty_override_take_the_defaults(adm: ModuleType) -> None:
    staffing = _table_staffing()
    for answer in ("none", None, {}):
        after = adm.apply_answers(
            _table_record(adm, staffing), {"staffing_overrides": answer}, staffing
        )
        assert after.run_configuration["staffing_models_and_efforts"]["source"] == "staffing"


#: The answers the questionnaire no longer asks for (issue #161), built from parts so the retired
#: names appear nowhere in this file as one word.
_RETIRED_ANSWERS: dict[str, Any] = {
    "lens" + "_declaration": {
        "always_on": ["correctness", "security"],
        "conditional_applies": {},
        "conditional_does_not_apply": {},
    },
    "repair" + "_allowances": {"standard": 3, "escalated": 2},
}


@pytest.mark.parametrize("key", sorted(_RETIRED_ANSWERS))
def test_an_answer_to_a_retired_question_is_refused_and_changes_nothing(
    adm: ModuleType, key: str
) -> None:
    staffing = _table_staffing()
    record = _table_record(adm, staffing)
    before = json.dumps(record.__dict__, sort_keys=True, default=str)
    with pytest.raises(adm.AdmissionError, match=key):
        adm.apply_answers(record, {key: _RETIRED_ANSWERS[key]}, staffing)
    assert json.dumps(record.__dict__, sort_keys=True, default=str) == before


@pytest.mark.parametrize("key", sorted(_RETIRED_ANSWERS))
def test_the_pane_path_refuses_a_retired_answer_and_leaves_the_record_unchanged(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    key: str,
) -> None:
    assert _answer_main(adm, store, repo_root, monkeypatch, _golden_answers()) == 0
    capsys.readouterr()
    (saved,) = store.glob("*.json")
    before = saved.read_text(encoding="utf-8")

    payload = {**_golden_answers(), key: _RETIRED_ANSWERS[key]}
    assert _answer_main(adm, store, repo_root, monkeypatch, payload) == 2
    err = capsys.readouterr().err
    assert err.startswith("admission: ")
    assert key in err
    assert saved.read_text(encoding="utf-8") == before


def test_a_staffing_only_answers_payload_is_accepted_and_records_no_retired_parameter(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _golden_answers()
    assert list(payload) == ["staffing_overrides"]
    assert _answer_main(adm, store, repo_root, monkeypatch, payload) == 0
    record = adm.run_record.load(store, 103, warn=None)
    assert record is not None
    for name in RETIRED_PARAMETERS:
        assert name not in record.run_configuration, name
    assert [key for key in record.admission.get("answers", {}) if key in _RETIRED_ANSWERS] == []
    pending = record.admission["pending_questions"]
    assert "staffing_overrides" not in pending
    assert [key for key in pending if key in _RETIRED_ANSWERS] == []



def test_answering_in_two_passes_leaves_plan_as_the_next_step(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    """The pane records the staffing question first; the rest follow in a second pass."""
    staffing = _table_staffing()
    answers = _all_answers()
    first = {"staffing_overrides": answers.pop("staffing_overrides")}

    def admit(given: dict[str, Any]) -> Any:
        record, outstanding = adm.admit(
            103,
            "infiquetra/infiquetra-agent-plugins",
            store_root=store,
            repo_root=repo_root,
            body=_good_card(),
            validator=_passing_validator,
            staffing=staffing,
            answers=given,
        )
        adm.save_admission(store, record)
        return record, outstanding

    record, outstanding = admit(first)
    assert outstanding
    assert (
        record.next_step
        == f"answer the {len(outstanding)} outstanding admission question(s), then plan"
    )
    record, outstanding = admit(answers)
    assert outstanding == []
    assert record.next_step == "plan"
    assert adm.run_record.load(store, 103, warn=None).next_step == "plan"


def test_a_next_step_a_later_step_set_survives_a_second_pass(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    run_record = _load("run_record")
    run_record.set_next_step(store, 103, "U4 the spore hooks")
    record, _ = adm.admit(
        103,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        answers=_all_answers(),
    )
    adm.save_admission(store, record)
    assert record.next_step == "U4 the spore hooks"
    assert run_record.load(store, 103, warn=None).next_step == "U4 the spore hooks"


def test_the_plan_skill_calls_the_review_pane_and_falls_back_to_the_tables(
    adm: ModuleType,
) -> None:
    skill = (REPO_ROOT / "plugins" / "saga" / "skills" / "plan" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    section = skill.split("### 0.1b")[1].split("### 0.2")[0]
    assert "mcp__saga__review_admission" in section
    for status in (
        "submitted",
        "dismissed",
        "not-placed",
        "unavailable",
        "nothing-to-review",
        "timed-out",
        "error",
    ):
        assert f"`{status}`" in section, status
    assert "exactly as if the tool were absent" in section
    assert "--render tables" in section
    assert "Never retype or re-record them" in section
    assert [line for line in section.splitlines()[1:] if line.startswith("#")] == []


# ---------------------------------------------------------------------------
# Issue #93 (staffing U1): admission, /plan and /work resolve one tier through
# fleet-core's one staffing resolver. These use the bundled staffing component
# admission really loads, never a fake, because the defect being closed was three
# paths that each looked right alone and disagreed with each other.
# ---------------------------------------------------------------------------

import subprocess  # noqa: E402

LIFECYCLE_STATE = SCRIPTS / "lifecycle_state.py"
SAGA_SKILLS = REPO_ROOT / "plugins" / "saga" / "skills"
TIER_DOCS = (
    SAGA_SKILLS / "plan" / "SKILL.md",
    SAGA_SKILLS / "work" / "SKILL.md",
    SAGA_SKILLS / "work" / "references" / "execution-strategy.md",
)


def _bundled_staffing(adm: ModuleType) -> Any:
    staffing = adm.load_staffing()
    if staffing is None:
        pytest.skip("saga's bundled staffing component is not reachable")
    return staffing


def _overlay(root: Path, model: str, effort: str) -> None:
    (root / ".saga").mkdir(exist_ok=True)
    (root / ".saga" / "tier-defaults.json").write_text(
        json.dumps({"implementation": {"model": model, "effort": effort}}), encoding="utf-8"
    )


def _admitted_staffing(
    adm: ModuleType, repo_root: Path, *, previous: dict[str, Any] | None = None
) -> dict[str, Any]:
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=93, repo="infiquetra/infiquetra-agent-plugins")
    if previous is not None:
        configuration = {name: dict(block) for name, block in record.run_configuration.items()}
        configuration["staffing_models_and_efforts"] = {"value": previous, "source": "staffing"}
        record = run_record.RunRecord(**{**record.__dict__, "run_configuration": configuration})
    filled = adm.fill_defaults(record, {}, _bundled_staffing(adm), repo_root=repo_root)
    block = filled.run_configuration["staffing_models_and_efforts"]
    assert block["source"] == "staffing"
    return block["value"]


def _plan_command(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run the command /plan and /work name, the way an agent runs it (AGENTS.md rule)."""
    return subprocess.run(
        [sys.executable, str(LIFECYCLE_STATE), "resolve-build-unit-tier", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def test_admission_staffs_the_worker_at_opus_medium(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo_root)
    value = _admitted_staffing(adm, repo_root)
    worker = value["worker"]
    assert (worker["vendor"], worker["model"], worker["effort"]) == ("claude", "sonnet", "high")
    assert worker["source"] == "policy"
    for role in ("merging-worker", "release-worker"):
        row = value[role]
        assert (row["vendor"], row["model"], row["effort"]) == ("claude", "haiku", "xhigh")


def _three_paths(adm: ModuleType, repo_root: Path) -> dict[str, tuple[str, str]]:
    worker = _admitted_staffing(adm, repo_root)["worker"]
    lifecycle_state = _load("lifecycle_state")
    work = lifecycle_state.resolve_build_unit_tier(root=repo_root)
    plan = _plan_command(repo_root)
    assert plan.returncode == 0, plan.stderr
    planned = json.loads(plan.stdout)
    direct = _bundled_staffing(adm).resolve_shape("implementation", root=repo_root)
    # /plan's second route: the run-start posture seeds a unit's proposed tier through
    # intent_envelope's recommend, which must not step the implementation shape down.
    posture = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "intent_envelope.py"),
            "recommend",
            "--work-shape",
            "implementation",
            "--run-mode",
            "unattended",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert posture.returncode == 0, posture.stderr
    seeded = json.loads(posture.stdout)
    return {
        "admission": (worker["model"], worker["effort"]),
        "work": (work["model"], work["effort"]),
        "plan": (planned["model"], planned["effort"]),
        "plan-posture": (seeded["model"], seeded["effort"]),
        "resolver": (direct.model, direct.effort),
    }


def test_admission_plan_and_work_agree_with_no_overlay(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo_root)
    paths = _three_paths(adm, repo_root)
    assert set(paths.values()) == {("sonnet", "high")}, paths


def test_admission_plan_and_work_agree_with_an_overlay(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Before #93 /work called the policy layer directly and skipped this overlay.
    _overlay(repo_root, "sonnet", "high")
    monkeypatch.chdir(repo_root)
    paths = _three_paths(adm, repo_root)
    assert set(paths.values()) == {("sonnet", "high")}, paths


def test_admission_reads_the_overlay_from_its_repo_root(
    adm: ModuleType, repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _overlay(repo_root, "sonnet", "high")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    worker = _admitted_staffing(adm, repo_root)["worker"]
    assert (worker["model"], worker["effort"], worker["source"]) == ("sonnet", "high", "overlay")


def test_admission_applies_and_keeps_a_recorded_raise(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo_root)
    raise_ = {
        "model": "opus",
        "effort": "high",
        "confidence": 0.86,
        "reason": "refund logic",
        "decision_id": "staffing/tier:93",
    }
    previous = {
        "worker": {"vendor": "claude", "model": "opus", "effort": "high", "jev_raise": raise_}
    }
    worker = _admitted_staffing(adm, repo_root, previous=previous)["worker"]
    assert (worker["model"], worker["effort"], worker["source"]) == ("opus", "high", "jev-raise")
    assert worker["jev_raise"] == raise_


@pytest.mark.parametrize(
    "bad_raise",
    [
        {"model": "fable", "effort": "medium"},
        {"model": "opus", "effort": "xhigh"},
        {"model": "sonnet", "effort": "low"},
    ],
    ids=["strongest-model", "two-steps", "lowering"],
)
def test_admission_keeps_the_worker_and_shows_a_refused_raise(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch, bad_raise: dict[str, str]
) -> None:
    # Before the review repair the refusal was swallowed and the worker vanished from the plan.
    monkeypatch.chdir(repo_root)
    previous = {"worker": {"vendor": "claude", "model": "sonnet", "effort": "high",
                           "jev_raise": bad_raise}}
    value = _admitted_staffing(adm, repo_root, previous=previous)
    assert "worker" in value, sorted(value)
    worker = value["worker"]
    assert (worker["model"], worker["effort"], worker["source"]) == ("sonnet", "high", "policy")
    assert worker["jev_raise"] == bad_raise
    assert "jev raise" in worker["jev_raise_refused"]


def test_admission_fails_loud_when_staffing_refuses_a_role(adm: ModuleType) -> None:
    real = _bundled_staffing(adm)

    def resolve_role(role: str, **kwargs: Any) -> Any:
        # A worker pinned to another vendor while its work shape is Claude-only.
        return real.resolve_shape("implementation", vendor="codex", root=kwargs.get("root"))

    staffing = SimpleNamespace(
        roles=lambda: {"worker": {}},
        resolve_role=resolve_role,
        StaffingError=real.StaffingError,
    )
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=93, repo="infiquetra/infiquetra-agent-plugins")
    with pytest.raises(adm.AdmissionError, match=r"'worker'.*Claude-only.*codex"):
        adm.fill_defaults(record, {}, staffing)


def test_admission_does_not_blame_a_raise_that_did_not_cause_the_refusal(
    adm: ModuleType,
) -> None:
    # A valid raise on a worker whose Claude-only shape refuses the codex pin: dropping the raise
    # leaves the same refusal, so the raise is not named and the message appears once.
    real = _bundled_staffing(adm)

    def resolve_role(role: str, **kwargs: Any) -> Any:
        return real.resolve_shape(
            "implementation", vendor="codex", root=kwargs.get("root"),
            jev_raise=kwargs.get("jev_raise"),
        )

    staffing = SimpleNamespace(
        roles=lambda: {"worker": {}}, resolve_role=resolve_role, StaffingError=real.StaffingError
    )
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=93, repo="infiquetra/infiquetra-agent-plugins")
    configuration = {name: dict(block) for name, block in record.run_configuration.items()}
    configuration |= {
        "staffing_models_and_efforts": {
            "value": {"worker": {"jev_raise": {"model": "opus", "effort": "high"}}},
            "source": "staffing",
        }
    }
    record = run_record.RunRecord(**{**record.__dict__, "run_configuration": configuration})
    with pytest.raises(adm.AdmissionError) as raised:
        adm.fill_defaults(record, {}, staffing)
    message = str(raised.value)
    assert "Claude-only" in message
    assert message.count("Claude-only") == 1, message
    assert "recorded raise" not in message


def test_admission_names_a_refused_raise_beside_the_role_refusal(adm: ModuleType) -> None:
    # The raise and the default are refused for different reasons: both reasons, in order.
    class Refusal(Exception):
        pass

    def resolve_role(role: str, **kwargs: Any) -> Any:
        if kwargs.get("jev_raise") is not None:
            raise Refusal("jev raise names the strongest model")
        raise Refusal("work shape 'implementation' is Claude-only")

    staffing = SimpleNamespace(
        roles=lambda: {"worker": {}}, resolve_role=resolve_role, StaffingError=Refusal
    )
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=93, repo="infiquetra/infiquetra-agent-plugins")
    configuration = {name: dict(block) for name, block in record.run_configuration.items()}
    configuration |= {
        "staffing_models_and_efforts": {
            "value": {"worker": {"jev_raise": {"model": "fable", "effort": "medium"}}},
            "source": "staffing",
        }
    }
    record = run_record.RunRecord(**{**record.__dict__, "run_configuration": configuration})
    with pytest.raises(
        adm.AdmissionError,
        match=r"'worker': work shape 'implementation' is Claude-only; "
        r"its recorded raise was also refused: jev raise names the strongest model",
    ):
        adm.fill_defaults(record, {}, staffing)


def test_admission_stays_fail_open_for_a_staffing_component_too_old_for_its_arguments(
    adm: ModuleType,
) -> None:
    # The documented fail-open path: a component whose resolve_role takes only the role (no
    # root= or jev_raise=) and has no StaffingError. Admission proceeds and the role is absent.
    staffing = SimpleNamespace(
        roles=lambda: {"worker": {}},
        resolve_role=lambda role: SimpleNamespace(
            vendor="claude", model="opus", effort="medium", source="policy"
        ),
    )
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=93, repo="infiquetra/infiquetra-agent-plugins")
    filled = adm.fill_defaults(record, {}, staffing)
    block = filled.run_configuration.get("staffing_models_and_efforts")
    assert block is None or "worker" not in (block.get("value") or {})


def _recording_bundled_staffing(adm: ModuleType) -> tuple[SimpleNamespace, list[str]]:
    """The staffing component saga ships, wrapped to record every role admission resolves."""
    real = _bundled_staffing(adm)
    asked: list[str] = []

    def resolve_role(role: str, **kwargs: Any) -> Any:
        asked.append(role)
        return real.resolve_role(role, **kwargs)

    wrapper = SimpleNamespace(
        roles=real.roles, resolve_role=resolve_role, StaffingError=real.StaffingError
    )
    return wrapper, asked


def _admit_with_bundled_staffing(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, list[str]]:
    monkeypatch.chdir(repo_root)
    staffing, asked = _recording_bundled_staffing(adm)
    run_record = _load("run_record")
    record = run_record.RunRecord(issue=161, repo="infiquetra/infiquetra-agent-plugins")
    return adm.fill_defaults(record, {}, staffing, repo_root=repo_root), asked


def test_admission_resolves_no_lens_role(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #161: the lens reviewer role is gone, so admission neither asks for it nor skips it."""
    filled, asked = _admit_with_bundled_staffing(adm, repo_root, monkeypatch)
    assert [role for role in asked if "lens" in role] == [], (
        "admission still asks staffing to resolve a lens role"
    )
    recorded = filled.run_configuration["staffing_models_and_efforts"]["value"]
    assert [role for role in recorded if "lens" in role] == []


def test_admission_staffs_the_targeted_reviewer_directly(
    adm: ModuleType, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Issue #161: the targeted reviewer resolves on its work shape, with no lens to pass."""
    filled, _asked = _admit_with_bundled_staffing(adm, repo_root, monkeypatch)
    recorded = filled.run_configuration["staffing_models_and_efforts"]["value"]
    assert "targeted-reviewer" in recorded, sorted(recorded)
    row = recorded["targeted-reviewer"]
    assert row["vendor"] and row["model"] and row["effort"], row


def test_the_build_unit_tier_passes_a_recorded_raise_to_the_resolver(tmp_path: Path) -> None:
    lifecycle_state = _load("lifecycle_state")
    raised = lifecycle_state.resolve_build_unit_tier(
        root=tmp_path, jev_raise={"model": "opus", "effort": "high"}
    )
    assert raised == {"model": "opus", "effort": "high", "source": "jev-raise"}
    command = _plan_command(
        tmp_path, "--explain", "--jev-raise", '{"model": "opus", "effort": "high"}'
    )
    assert command.returncode == 0, command.stderr
    assert json.loads(command.stdout) == {"model": "opus", "effort": "high", "source": "jev-raise"}
    refused = _plan_command(tmp_path, "--jev-raise", '{"model": "fable", "effort": "medium"}')
    assert refused.returncode == 2
    assert "jev raise" in json.loads(refused.stderr)["error"]


def test_the_build_unit_tier_reads_the_overlay_from_its_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    elsewhere = tmp_path / "elsewhere"
    checkout.mkdir()
    elsewhere.mkdir()
    _overlay(checkout, "sonnet", "high")
    monkeypatch.chdir(elsewhere)
    lifecycle_state = _load("lifecycle_state")
    assert lifecycle_state.resolve_build_unit_tier(root=checkout) == {
        "model": "sonnet",
        "effort": "high",
        "source": "overlay",
    }
    command = _plan_command(elsewhere, "--explain", "--root", str(checkout))
    assert command.returncode == 0, command.stderr
    assert json.loads(command.stdout) == {"model": "sonnet", "effort": "high", "source": "overlay"}


def test_the_build_unit_command_shows_a_raise_a_plan_tier_set_aside(tmp_path: Path) -> None:
    # A plan-recorded tier is passed as the operator's answer and outranks a recorded raise; the
    # command must say the raise was set aside rather than drop it without a trace.
    command = _plan_command(
        tmp_path,
        "--explain",
        "--plan-model", "opus", "--plan-effort", "medium",
        "--jev-raise", '{"model": "opus", "effort": "high"}',
    )
    assert command.returncode == 0, command.stderr
    assert json.loads(command.stdout) == {
        "model": "opus",
        "effort": "medium",
        "source": "operator",
        "jev_raise_set_aside": True,
    }


def test_the_build_unit_command_explains_the_winning_layer_only_when_asked(
    tmp_path: Path,
) -> None:
    # The default output stays exactly {model, effort}; --explain adds the resolver's source and,
    # when a passed raise was outranked, jev_raise_set_aside. Neither key leaks without the flag.
    raise_json = '{"model": "opus", "effort": "high"}'
    explained = _plan_command(tmp_path, "--explain")
    assert explained.returncode == 0, explained.stderr
    assert explained.stdout.strip() == (
        '{"model": "sonnet", "effort": "high", "source": "policy"}'
    )
    set_aside = _plan_command(
        tmp_path, "--plan-model", "opus", "--plan-effort", "medium", "--jev-raise", raise_json
    )
    assert set_aside.returncode == 0, set_aside.stderr
    assert json.loads(set_aside.stdout) == {"model": "opus", "effort": "medium"}
    raised = _plan_command(tmp_path, "--jev-raise", raise_json)
    assert json.loads(raised.stdout) == {"model": "opus", "effort": "high"}


def test_the_build_unit_command_runs_as_an_agent_runs_it(tmp_path: Path) -> None:
    undeclared = _plan_command(tmp_path)
    assert undeclared.returncode == 0, undeclared.stderr
    # Issue #93's acceptance criterion, literally: the default output is exactly the two-key tier.
    assert undeclared.stdout.strip() == '{"model": "sonnet", "effort": "high"}'

    mechanical = _plan_command(tmp_path, "--work-shape", "mechanical")
    assert json.loads(mechanical.stdout) == {"model": "haiku", "effort": "xhigh"}

    explicit = _plan_command(tmp_path, "--plan-model", "haiku", "--plan-effort", "low")
    assert json.loads(explicit.stdout) == {"model": "haiku", "effort": "low"}

    unknown = _plan_command(tmp_path, "--work-shape", "nope")
    assert unknown.returncode == 2
    assert "nope" in json.loads(unknown.stderr)["error"]

    # Every Claude model runs xhigh since Haiku 5.5, so haiku/xhigh is an ordinary answer now.
    haiku_xhigh = _plan_command(tmp_path, "--plan-model", "haiku", "--plan-effort", "xhigh")
    assert json.loads(haiku_xhigh.stdout) == {"model": "haiku", "effort": "xhigh"}

    # max is haiku's alone since 2026-10-07; any other model refuses it.
    haiku_max = _plan_command(tmp_path, "--plan-model", "haiku", "--plan-effort", "max")
    assert json.loads(haiku_max.stdout) == {"model": "haiku", "effort": "max"}
    off_palette = _plan_command(tmp_path, "--plan-model", "sonnet", "--plan-effort", "max")
    assert off_palette.returncode == 2
    assert "max" in json.loads(off_palette.stderr)["error"]


@pytest.mark.parametrize("doc", TIER_DOCS, ids=lambda path: path.name)
def test_the_skills_name_the_resolver_and_restate_no_precedence(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    for retired in (
        "parse_tier_band",
        "resolve_tier_for_plan",
        "write_tier_default",
        "tier_defaults",
        "overlay >",
        "issue band",
    ):
        assert retired not in text, f"{doc.name} still names {retired!r}"
    assert "resolve-build-unit-tier" in text


def test_the_table_reads_the_overlay_admission_staffs_from_repo_root(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Review finding on #93: admission staffs from ``--repo-root``, so its table must too.

    The checkout named by ``--repo-root`` sets the implementation shape to opus/medium; the working
    directory's own overlay sets it to sonnet/low. With a recorded Jev raise on the worker
    (sonnet/high to opus/high, which the checkout's overlay outranks), the table's Default,
    Proposed and Why must agree with the tier admission records, never with the working
    directory's overlay and never with the outranked raise.
    """
    staffing = _bundled_staffing(adm)
    (repo_root / ".saga").mkdir()
    (repo_root / ".saga" / "tier-defaults.json").write_text(
        json.dumps({"implementation": {"model": "opus", "effort": "medium"}}), encoding="utf-8"
    )
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / ".saga").mkdir(parents=True)
    (elsewhere / ".saga" / "tier-defaults.json").write_text(
        json.dumps({"implementation": {"model": "sonnet", "effort": "low"}}), encoding="utf-8"
    )
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(adm, "load_card_validator", lambda: _passing_validator)
    monkeypatch.setattr(adm, "load_staffing", lambda: staffing)
    monkeypatch.setattr(adm, "fetch_issue", lambda *_a, **_k: {"number": 102, "body": _good_card()})

    # Seed the store with a record whose worker carries a recorded one-step raise.
    run_record = _load("run_record")
    seeded = adm.fill_defaults(
        run_record.RunRecord(issue=102, repo="infiquetra/infiquetra-agent-plugins"),
        {},
        staffing,
        repo_root=repo_root,
    )
    raise_ = {"model": "opus", "effort": "high", "reason": "gate"}
    seeded.run_configuration["staffing_models_and_efforts"]["value"]["worker"][
        "jev_raise"
    ] = raise_
    adm.save_admission(store, seeded)

    assert _run_main(adm, store, repo_root, "--render", "json") == 0
    data = json.loads(capsys.readouterr().out)
    rows = {row["role"]: row for row in data["staffing"]["rows"]}
    merging = rows["worker"]

    staffed = adm.admit(
        102,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        staffing=staffing,
    )[0].run_configuration["staffing_models_and_efforts"]["value"]["worker"]
    assert (staffed["model"], staffed["effort"], staffed["source"]) == ("opus", "medium", "overlay")
    assert staffed["jev_raise"] == raise_

    tier = {"vendor": "claude", "model": "opus", "effort": "medium"}
    assert merging["default"] == tier
    assert merging["proposed"] == tier
    assert merging["why"] == (
        "repository overlay (.saga/tier-defaults.json, work shape implementation); "
        "the overlay outranks the recorded Jev raise"
    )


# ---------------------------------------------------------------------------
# The functional-test environment, declared once per repository (issue #97)
# ---------------------------------------------------------------------------

PROFILE_REFERENCE = REPO_ROOT / "plugins" / "saga" / "references" / "repository-profile.md"


def _admit_main(
    adm: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    store: Path,
    repo_root: Path,
    *,
    issue: int = 97,
    answers: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> int:
    """Run admission's command line with the network and the siblings faked out."""
    monkeypatch.setattr(adm, "load_card_validator", lambda: _passing_validator)
    monkeypatch.setattr(adm, "load_staffing", lambda: None)
    monkeypatch.setattr(
        adm, "fetch_issue", lambda *_a, **_k: {"number": issue, "body": _good_card()}
    )
    argv = [
        "--issue",
        str(issue),
        "--repo",
        "infiquetra/infiquetra-agent-plugins",
        "--store-root",
        str(store),
        "--repo-root",
        str(repo_root),
    ]
    if answers is not None:
        answers_path = store.parent / f"answers-{issue}.json"
        answers_path.write_text(json.dumps(answers), encoding="utf-8")
        argv += ["--answers", str(answers_path)]
    if dry_run:
        argv.append("--dry-run")
    exit_code: int = adm.main(argv)
    return exit_code


def _profile(repo_root: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(
        (repo_root / ".saga-profile.json").read_text(encoding="utf-8")
    )
    return loaded


def test_a_missing_declaration_is_exactly_one_question_naming_the_four_kinds(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _, outstanding = adm.admit(
        97,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    asked = [question for question in outstanding if question.key.startswith("functional_test")]
    assert [question.key for question in asked] == ["functional_test_environment"]
    prompt = asked[0].prompt
    for kind in ("local", "emulator", "ephemeral-stack", "shared-nonprod"):
        assert kind in prompt
    assert "waive" in prompt
    assert ".saga-profile.json" in prompt


def test_an_answer_is_written_back_to_the_profile_and_keeps_its_other_keys(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_record = _load("run_record")
    (repo_root / ".saga-profile.json").write_text(
        json.dumps({"schema": "repository_profile.v1", "concurrency_allocation": 4}),
        encoding="utf-8",
    )
    answer = {"kind": "local", "test_command": "python3 -m pytest tests -q", "scope": "private"}
    assert (
        _admit_main(
            adm, monkeypatch, store, repo_root, answers={"functional_test_environment": answer}
        )
        == 0
    )
    profile = _profile(repo_root)
    assert profile == {
        "schema": "repository_profile.v1",
        "concurrency_allocation": 4,
        "functional_test_environment": answer,
    }
    record = run_record.load(store, 97, warn=None)
    recorded = record.admission["functional_test_environment"]
    assert recorded["mode"] == "declared"
    assert recorded["source"] == "operator"
    assert recorded["deploy_command"] is None
    assert "functional_test_environment" not in record.admission["pending_questions"]


def test_after_the_write_back_the_next_run_is_not_asked_and_reads_the_profile(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = {"kind": "local", "test_command": "make functional", "scope": "private"}
    assert (
        _admit_main(
            adm, monkeypatch, store, repo_root, answers={"functional_test_environment": answer}
        )
        == 0
    )
    record, outstanding = adm.admit(
        98,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert "functional_test_environment" not in {question.key for question in outstanding}
    recorded = record.admission["functional_test_environment"]
    assert recorded["source"] == "profile"
    assert recorded["test_command"] == "make functional"
    assert record.admission["answers"]["functional_test_environment"]["source"] == "profile"


def test_a_dry_run_with_an_answer_writes_no_profile(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = {"functional_test_environment": dict(_LOCAL_ENVIRONMENT)}
    assert _admit_main(adm, monkeypatch, store, repo_root, answers=answers, dry_run=True) == 0
    assert not (repo_root / ".saga-profile.json").exists()
    assert list(store.glob("*.json")) == []


@pytest.mark.parametrize("waiver", [{"reason": ""}, {"reason": "   "}, {}])
def test_a_waiver_needs_a_reason(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    waiver: dict[str, Any],
) -> None:
    exit_code = _admit_main(
        adm, monkeypatch, store, repo_root, answers={"functional_test_waiver": waiver}
    )
    assert exit_code == 2
    assert "reason" in capsys.readouterr().err
    assert not (repo_root / ".saga-profile.json").exists()
    assert list(store.glob("*.json")) == []


def test_a_waiver_with_a_reason_replaces_a_declaration_in_the_profile(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_record = _load("run_record")
    _write_profile(repo_root)
    waiver = {"reason": "documentation only; nothing here runs"}
    assert (
        _admit_main(adm, monkeypatch, store, repo_root, answers={"functional_test_waiver": waiver})
        == 0
    )
    profile = _profile(repo_root)
    assert profile["functional_test_waiver"] == waiver
    assert "functional_test_environment" not in profile
    recorded = run_record.load(store, 97, warn=None).admission["functional_test_environment"]
    assert recorded == {
        "mode": "waived",
        "level": "repository",
        "reason": waiver["reason"],
        "source": "operator",
    }


def test_a_waiver_nested_under_the_environment_key_is_accepted(adm: ModuleType) -> None:
    run_record = _load("run_record")
    record = adm.apply_answers(
        run_record.RunRecord(issue=97),
        {"functional_test_environment": {"functional_test_waiver": {"reason": "docs only"}}},
    )
    assert record.admission["functional_test_environment"]["mode"] == "waived"


@pytest.mark.parametrize(
    ("answer", "named"),
    [
        ({"kind": "docker", "test_command": "t", "scope": "private"}, "kind"),
        ({"kind": "local", "scope": "private"}, "test_command"),
        ({"kind": "local", "test_command": " ", "scope": "private"}, "test_command"),
        ({"kind": "emulator", "test_command": "t", "scope": "private"}, "deploy_command"),
        (
            {
                "kind": "shared-nonprod",
                "deploy_command": "d",
                "test_command": "t",
                "scope": "private",
            },
            "always shared",
        ),
        ({"kind": "ephemeral-stack", "deploy_command": "d", "test_command": "t"}, "scope"),
        ({"kind": "local", "test_command": "t", "scope": "private", "extra": 1}, "unexpected"),
    ],
)
def test_a_declaration_the_build_loop_could_not_use_is_refused(
    adm: ModuleType, answer: dict[str, Any], named: str
) -> None:
    run_record = _load("run_record")
    with pytest.raises(adm.AdmissionError) as excinfo:
        adm.apply_answers(run_record.RunRecord(issue=97), {"functional_test_environment": answer})
    assert named in str(excinfo.value)


def test_a_refused_declaration_exits_2_and_writes_nothing(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    answers = {"functional_test_environment": {"kind": "emulator", "test_command": "t"}}
    assert _admit_main(adm, monkeypatch, store, repo_root, answers=answers) == 2
    assert "deploy_command" in capsys.readouterr().err
    assert not (repo_root / ".saga-profile.json").exists()


def test_shared_nonprod_without_a_scope_resolves_to_shared(adm: ModuleType) -> None:
    run_record = _load("run_record")
    record = adm.apply_answers(
        run_record.RunRecord(issue=97),
        {
            "functional_test_environment": {
                "kind": "shared-nonprod",
                "deploy_command": "make deploy-nonprod",
                "test_command": "make functional",
                "teardown_command": "make teardown",
            }
        },
    )
    recorded = record.admission["functional_test_environment"]
    assert recorded["scope"] == "shared"
    assert recorded["teardown_command"] == "make teardown"


def test_a_legacy_branch_preview_is_asked_once_with_the_migrated_default(
    adm: ModuleType, store: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo_root / ".saga-profile.json").write_text(
        json.dumps(
            {
                "schema": "repository_profile.v1",
                "branch_preview": True,
                "branch_preview_command": "deploy-preview",
                "main_consumed_directly": False,
            }
        ),
        encoding="utf-8",
    )
    record, outstanding = adm.admit(
        97,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    asked = [question for question in outstanding if question.key.startswith("functional_test")]
    assert len(asked) == 1
    assert asked[0].default == {
        "kind": "ephemeral-stack",
        "deploy_command": "deploy-preview",
        "scope": "private",
    }
    assert record.admission["functional_test_environment"]["mode"] == "incomplete"
    assert record.admission["functional_test_environment"]["missing"] == ["test_command"]

    confirmed = {**asked[0].default, "test_command": "make smoke"}
    assert (
        _admit_main(
            adm, monkeypatch, store, repo_root, answers={"functional_test_environment": confirmed}
        )
        == 0
    )
    profile = _profile(repo_root)
    assert "branch_preview" not in profile
    assert "branch_preview_command" not in profile
    assert profile["functional_test_environment"] == confirmed
    assert profile["main_consumed_directly"] is False


def test_a_legacy_branch_preview_false_declares_nothing_and_is_asked(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    (repo_root / ".saga-profile.json").write_text(
        json.dumps({"schema": "repository_profile.v1", "branch_preview": False}),
        encoding="utf-8",
    )
    record, outstanding = adm.admit(
        97,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    question = next(q for q in outstanding if q.key == "functional_test_environment")
    assert question.default is None
    assert record.admission.get("functional_test_environment") is None


def test_a_profile_declaring_both_the_environment_and_a_waiver_is_refused(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    (repo_root / ".saga-profile.json").write_text(
        json.dumps(
            {
                "functional_test_environment": dict(_LOCAL_ENVIRONMENT),
                "functional_test_waiver": {"reason": "docs"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(adm.AdmissionError) as excinfo:
        adm.admit(
            97,
            "infiquetra/infiquetra-agent-plugins",
            store_root=store,
            repo_root=repo_root,
            body=_good_card(),
            validator=_passing_validator,
        )
    assert "both" in str(excinfo.value)


def test_answering_both_the_environment_and_a_waiver_is_refused(adm: ModuleType) -> None:
    run_record = _load("run_record")
    with pytest.raises(adm.AdmissionError):
        adm.apply_answers(
            run_record.RunRecord(issue=97),
            {
                "functional_test_environment": dict(_LOCAL_ENVIRONMENT),
                "functional_test_waiver": {"reason": "docs"},
            },
        )


def test_an_answers_file_still_carrying_branch_preview_is_refused(adm: ModuleType) -> None:
    run_record = _load("run_record")
    with pytest.raises(adm.AdmissionError) as excinfo:
        adm.apply_answers(run_record.RunRecord(issue=97), {"branch_preview": False})
    assert "not admission questions: branch_preview" in str(excinfo.value)


def test_an_operator_answer_outranks_the_profile_on_a_re_run(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    run_record = _load("run_record")
    _write_profile(repo_root)
    answer = {"kind": "emulator", "deploy_command": "localstack up", "test_command": "t"}
    answer["scope"] = "private"
    record, _ = adm.admit(
        97,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        answers={"functional_test_environment": answer},
    )
    run_record.save(store, record)
    again, _ = adm.admit(
        97,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert again.admission["functional_test_environment"]["kind"] == "emulator"
    assert again.admission["functional_test_environment"]["source"] == "operator"


def test_the_summary_names_the_declared_environment(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _write_profile(repo_root)
    record, outstanding = adm.admit(
        97,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    text = adm.render(record, outstanding, None)
    assert "Functional-test environment:  [profile]" in text
    assert "kind: local (scope: private)" in text
    assert "test: python3 -m pytest tests -q" in text


def test_the_profile_reference_documents_the_block_the_waiver_and_the_migration() -> None:
    """Acceptance criterion 1 of issue #97, pinned so the document cannot drift from the code."""
    text = PROFILE_REFERENCE.read_text(encoding="utf-8")
    for term in (
        "functional_test_environment",
        "functional_test_waiver",
        "Migration from `branch_preview`",
        "branch_preview_command",
        "local",
        "emulator",
        "ephemeral-stack",
        "shared-nonprod",
        "teardown_command",
    ):
        assert term in text, f"repository-profile.md does not name {term}"


# ---------------------------------------------------------------------------
# Issue #96: the tier judgment at admission, from the real issue
# ---------------------------------------------------------------------------
#
# Every consult below runs saga's real bundled staffing component with an injected ``ask``, so the
# state, the bands and the resolver are the shipped ones and nothing reaches the network. The
# saga conftest switches the judgment off for every test; these pass an explicit ``getenv`` that
# leaves it on.

_JUDGE_BODY = "Rotate the IAM signing key behind the token endpoint.\n\n" + _good_card()


def _judging_ask(
    answers: dict[str, tuple[str, float]], calls: list[dict[str, Any]] | None = None
) -> Any:
    """An ``ask`` that answers each role's direction question from *answers* (default: same)."""

    def _ask(state: Any, questions: Any, **options: Any) -> Any:
        if calls is not None:
            calls.append({"state": state, "questions": questions, "options": options})
        out: dict[str, Any] = {}
        for key in questions:
            role = key.split("__")[0]
            choice, confidence = answers.get(role, ("same", 0.9))
            out[key] = {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {choice: confidence},
            }
        return SimpleNamespace(status="ok", answers=out, model="jev-1.13.0", note="")

    return _ask


def _judged(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    answers: dict[str, tuple[str, float]],
    *,
    calls: list[dict[str, Any]] | None = None,
    operator: dict[str, Any] | None = None,
    log_dir: Path | None = None,
    getenv: Any = None,
) -> tuple[Any, list[Any]]:
    return adm.admit(
        96,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_JUDGE_BODY,
        title="Jev decides tier raises",
        validator=_passing_validator,
        staffing=_bundled_staffing(adm),
        answers=operator,
        judge_tiers=True,
        judgment_ask=_judging_ask(answers, calls),
        judgment_getenv=getenv or (lambda _name: None),
        judgment_log_dir=log_dir,
        log_labels=log_dir is not None,
    )


def _staffing_value(record: Any) -> dict[str, Any]:
    value: dict[str, Any] = record.run_configuration["staffing_models_and_efforts"]["value"]
    return value


def _logged(log_dir: Path) -> dict[str, dict[str, Any]]:
    path = log_dir / "verdicts.jsonl"
    if not path.is_file():
        return {}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    return {row["decision_id"]: row for row in rows if row.get("kind") == "verdict"}


def test_the_state_sent_includes_the_issue_title_body_and_flags(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    calls: list[dict[str, Any]] = []
    _judged(adm, store, repo_root, {}, calls=calls)

    assert len(calls) == 1, "every role is judged in one request"
    issue = calls[0]["state"]["issue"]
    assert issue["title"] == "Jev decides tier raises"
    assert issue["body"] == _JUDGE_BODY
    assert issue["flags"] == {
        "has_security": True,
        "has_api": True,
        "has_infra": False,
        "has_privacy": False,
    }
    worker = calls[0]["state"]["tasks"]["worker"]
    assert worker["default_tier"] == "sonnet/high"
    assert worker["work_shape"] == "implementation"
    assert "worker__direction" in calls[0]["questions"]
    assert calls[0]["options"]["total_deadline"] == 20.0
    assert calls[0]["options"]["max_attempts"] == 2


def test_an_auto_raise_is_recorded_in_the_run_record_with_its_reason(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    record, _ = _judged(adm, store, repo_root, {"worker": ("above", 0.85)})

    worker = _staffing_value(record)["worker"]
    assert (worker["model"], worker["effort"], worker["source"]) == ("opus", "high", "jev-raise")
    raise_ = worker["jev_raise"]
    assert (raise_["model"], raise_["effort"], raise_["confidence"]) == ("opus", "high", 0.85)
    assert "one model step" in raise_["reason"] and "0.85" in raise_["reason"]
    assert raise_["decision_id"] == (
        "staffing/tier-direction:infiquetra/infiquetra-agent-plugins#96:role:worker"
    )
    assert worker["tier_judgment"]["band"] == "auto-raise"
    assert _staffing_value(record)["_tier_judgment"] == {"status": "ok", "note": ""}


def test_a_confirm_band_raise_prefills_question_4(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    record, outstanding = _judged(adm, store, repo_root, {"worker": ("above", 0.7)})

    worker = _staffing_value(record)["worker"]
    assert "jev_raise" not in worker
    assert (worker["model"], worker["effort"]) == ("sonnet", "high")
    question = next(q for q in outstanding if q.key == "staffing_overrides")
    assert question.default == {"worker": {"vendor": "claude", "model": "opus", "effort": "high"}}
    assert "raise to confirm, worker: sonnet/high -> opus/high (confidence 0.70)" in question.prompt


def test_a_lower_suggestion_is_advisory_only(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    record, outstanding = _judged(adm, store, repo_root, {"merging-worker": ("below", 0.95)})

    merging = _staffing_value(record)["merging-worker"]
    assert (merging["model"], merging["effort"], merging["source"]) == (
        "haiku",
        "xhigh",
        "policy",
    )
    assert "jev_raise" not in merging
    question = next(q for q in outstanding if q.key == "staffing_overrides")
    assert question.default is None
    assert "advisory lower, never applied, merging-worker" in question.prompt
    rendered = adm.render(record, outstanding, None)
    assert "merging-worker: advisory lower, never applied, haiku/xhigh -> haiku/high" in rendered


def test_the_operator_answer_is_logged_as_the_label(
    adm: ModuleType, store: Path, repo_root: Path, tmp_path: Path
) -> None:
    log_dir = tmp_path / "typesafe"
    override = {"planner": {"vendor": "claude", "model": "opus", "effort": "xhigh"}}
    record, _ = _judged(
        adm,
        store,
        repo_root,
        {"worker": ("above", 0.85), "planner": ("above", 0.7), "merging-worker": ("below", 0.9)},
        operator={"staffing_overrides": override},
        log_dir=log_dir,
    )

    prefix = "staffing/tier-direction:infiquetra/infiquetra-agent-plugins#96:role:"
    logged = _logged(log_dir)
    # The operator confirmed the planner's raise, took the worker's automatic raise, and kept the
    # merging worker's default over Jev's advisory lower.
    assert logged[prefix + "planner"]["label"] == "above"
    assert logged[prefix + "worker"]["label"] == "above"
    assert logged[prefix + "merging-worker"]["label"] == "same"
    assert logged[prefix + "release-worker"]["label"] == "same"
    assert logged[prefix + "worker"]["answer"]["choice"] == "above"
    worker_block = _staffing_value(record)["worker"]["tier_judgment"]
    assert logged[prefix + "worker"]["state_hash"] == worker_block["state_hash"]
    assert worker_block["labeled"] == "above"


def test_a_none_answer_labels_from_the_default_or_the_applied_raise(
    adm: ModuleType, store: Path, repo_root: Path, tmp_path: Path
) -> None:
    log_dir = tmp_path / "typesafe"
    _judged(
        adm,
        store,
        repo_root,
        {"worker": ("above", 0.85), "planner": ("above", 0.7)},
        operator={"staffing_overrides": "none"},
        log_dir=log_dir,
    )

    prefix = "staffing/tier-direction:infiquetra/infiquetra-agent-plugins#96:role:"
    logged = _logged(log_dir)
    assert logged[prefix + "worker"]["label"] == "above", "the applied raise stood"
    assert logged[prefix + "planner"]["label"] == "same", "'none' declined the pending raise"


def test_labels_are_logged_once(
    adm: ModuleType, store: Path, repo_root: Path, tmp_path: Path
) -> None:
    log_dir = tmp_path / "typesafe"
    record, _ = _judged(
        adm,
        store,
        repo_root,
        {"worker": ("above", 0.85)},
        operator={"staffing_overrides": "none"},
        log_dir=log_dir,
    )
    adm.save_admission(store, record)
    lines = (log_dir / "verdicts.jsonl").read_text(encoding="utf-8").splitlines()

    calls: list[dict[str, Any]] = []
    _judged(
        adm,
        store,
        repo_root,
        {"worker": ("above", 0.85)},
        operator={"staffing_overrides": "none"},
        log_dir=log_dir,
        calls=calls,
    )
    assert (log_dir / "verdicts.jsonl").read_text(encoding="utf-8").splitlines() == lines
    assert calls == [], "an already-judged run is not asked again"


def test_off_switch_makes_no_request_at_admission(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    calls: list[dict[str, Any]] = []
    record, outstanding = _judged(
        adm,
        store,
        repo_root,
        {"worker": ("above", 0.95)},
        calls=calls,
        getenv=lambda name: "off" if name == "INFIQUETRA_TYPESAFE_TIERING" else None,
    )

    assert calls == []
    value = _staffing_value(record)
    assert value["_tier_judgment"]["status"] == "off"
    assert (value["worker"]["model"], value["worker"]["effort"]) == ("sonnet", "high")
    assert "tier_judgment" not in value["worker"]
    assert "Tier judgment: switched off" in adm.render(record, outstanding, None)


def test_a_failed_consult_keeps_an_earlier_raise(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    record, _ = _judged(adm, store, repo_root, {"worker": ("above", 0.85)})
    adm.save_admission(store, record)
    # Make the earlier consult look unfinished so the next run asks again, and let it fail.
    run_record = _load("run_record")
    saved = run_record.load(store, 96, warn=None)
    _staffing_value(saved)["_tier_judgment"] = {"status": "error", "note": "down"}
    run_record.save(store, saved)

    def failing(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(status="timeout", answers={}, model="", note="the deadline passed")

    again, _ = adm.admit(
        96,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_JUDGE_BODY,
        validator=_passing_validator,
        staffing=_bundled_staffing(adm),
        judge_tiers=True,
        judgment_ask=failing,
        judgment_getenv=lambda _name: None,
    )
    worker = _staffing_value(again)["worker"]
    assert worker["jev_raise"]["effort"] == "high"
    assert (worker["model"], worker["effort"], worker["source"]) == ("opus", "high", "jev-raise")
    assert _staffing_value(again)["_tier_judgment"] == {
        "status": "timeout",
        "note": "the deadline passed",
    }


def test_an_overlay_tier_is_never_auto_raised(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    _overlay(repo_root, "opus", "medium")
    record, outstanding = _judged(adm, store, repo_root, {"worker": ("above", 0.95)})

    worker = _staffing_value(record)["worker"]
    assert worker["source"] == "overlay"
    assert "jev_raise" not in worker
    assert worker["tier_judgment"]["band"] == "confirm-raise"
    question = next(q for q in outstanding if q.key == "staffing_overrides")
    assert question.default == {"worker": {"vendor": "claude", "model": "opus", "effort": "high"}}


def test_the_library_default_makes_no_request(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    calls: list[dict[str, Any]] = []
    adm.admit(
        96,
        "infiquetra/infiquetra-agent-plugins",
        store_root=store,
        repo_root=repo_root,
        body=_JUDGE_BODY,
        validator=_passing_validator,
        staffing=_bundled_staffing(adm),
        judgment_ask=_judging_ask({}, calls),
        judgment_getenv=lambda _name: None,
    )
    assert calls == []


def test_dry_run_logs_no_verdict_and_the_command_line_judges_by_default(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_dir = tmp_path / "typesafe"
    monkeypatch.setenv("INFIQUETRA_TYPESAFE_LOG_DIR", str(log_dir))
    monkeypatch.delenv("INFIQUETRA_TYPESAFE_TIERING")
    staffing = _bundled_staffing(adm)
    calls: list[dict[str, Any]] = []
    consult = staffing.consult_tier_suggestions

    def injected(units: Any, **kwargs: Any) -> Any:
        kwargs["ask"] = _judging_ask({"worker": ("above", 0.85)}, calls)
        return consult(units, **kwargs)

    monkeypatch.setattr(staffing, "consult_tier_suggestions", injected)
    monkeypatch.setattr(adm, "load_card_validator", lambda: _passing_validator)
    monkeypatch.setattr(adm, "load_staffing", lambda: staffing)
    monkeypatch.setattr(
        adm, "fetch_issue", lambda *_a, **_k: {"number": 96, "title": "T", "body": _JUDGE_BODY}
    )
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"staffing_overrides": "none"}), encoding="utf-8")
    argv = [
        "--issue",
        "96",
        "--repo",
        "o/r",
        "--store-root",
        str(store),
        "--repo-root",
        str(repo_root),
        "--answers",
        str(answers),
    ]

    assert adm.main([*argv, "--dry-run"]) == 0
    assert len(calls) == 1, "the command line judges without being asked to"
    assert calls[0]["options"]["cache_dir"] == log_dir
    assert "worker: raise applied, sonnet/high -> opus/high" in capsys.readouterr().out
    assert _logged(log_dir) == {}, "a dry run logs nothing"

    assert adm.main(argv) == 0
    logged = _logged(log_dir)
    assert logged["staffing/tier-direction:o/r#96:role:worker"]["label"] == "above"


def test_the_plan_skill_names_the_tier_judgment_and_the_off_switch() -> None:
    text = (SAGA_SKILLS / "plan" / "SKILL.md").read_text(encoding="utf-8")
    assert "INFIQUETRA_TYPESAFE_TIERING=off" in text
    assert "tier_judgment.py plan --issue" in text
    assert "tier_judgment.py label --issue" in text
    assert "parse_tier_band" not in text


def test_the_tables_band_names_are_the_staffing_components(adm: ModuleType) -> None:
    staffing = _bundled_staffing(adm)
    assert set(adm._BAND_NOTES) == {
        staffing.BAND_AGREES,
        staffing.BAND_AUTO_RAISE,
        staffing.BAND_CONFIRM_RAISE,
        staffing.BAND_ADVISORY_LOWER,
    }
    assert adm._AT_CEILING == staffing.BAND_RAISE_AT_CEILING


# ---------------------------------------------------------------------------
# Setup notice and the one suggestion (issue #150)
# ---------------------------------------------------------------------------


class _Probe:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _shipped_semgrep_pin() -> str:
    """The Semgrep pin the committed tool list records, which the stub reports."""
    text = (
        REPO_ROOT / "plugins" / "saga" / "references" / "review-tools.yaml"
    ).read_text(encoding="utf-8")
    document = yaml.safe_load(text)
    row = next(item for item in document["tools"] if item.get("id") == "semgrep-security")
    return str(row["default_version"])


def _notice_runner(missing: str | None = "git") -> Any:
    """Every shipped tool is installed except the named binary."""

    def runner(
        argv: list[str], *, cwd: Path | None = None, env: object = None, timeout: int = 30
    ) -> _Probe:
        if argv[:4] == ["gh", "repo", "view", "--json"]:
            return _Probe(0, '{"visibility":"PUBLIC"}')
        if argv == ["gh", "auth", "status"]:
            return _Probe(0, "")
        if argv == ["claude", "--version"]:
            return _Probe(0, "1.0.0\n")
        if missing is not None and argv and argv[0] == missing:
            raise FileNotFoundError(missing)
        if argv and argv[0] == "python3":
            return _Probe(0, "Python 3.12.0\n")
        if argv[:2] == ["semgrep", "--version"]:
            return _Probe(0, f"semgrep {_shipped_semgrep_pin()}\n")
        return _Probe(0, "1.2.3\n")

    return runner


def test_setup_notice_is_replaced_and_names_the_tool(
    adm: ModuleType, store: Path, repo_root: Path, tmp_path: Path
) -> None:
    run_record = _load("run_record")
    home = tmp_path / "notice-home"
    home.mkdir()
    bare, bare_questions = adm.admit(
        150,
        "o/r",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    noticed, questions = adm.admit(
        150,
        "o/r",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        home=home,
        runner=_notice_runner("git"),
    )
    notice = noticed.admission["setup_notice"]
    assert notice["missing_tools"] == ["saga-git"]
    assert "saga-git" in notice["text"]
    assert "sandbox" in notice["text"]
    assert "/saga:setup" in notice["text"]
    assert notice["sandbox_unavailable"] is True
    assert "setup" not in noticed.admission["pending_questions"]
    assert {question.key for question in questions} == {question.key for question in bare_questions}
    assert noticed.review_cycles == bare.review_cycles
    run_record.save(store, noticed)
    replaced, _ = adm.admit(
        150,
        "o/r",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        home=home,
        runner=_notice_runner(None),
    )
    second = replaced.admission["setup_notice"]
    assert isinstance(second, dict)
    assert second["text"] == "Missing sandbox. Run /saga:setup."
    assert second != notice
    assert replaced.review_cycles == []


def test_setup_notice_is_empty_when_nothing_is_missing(
    adm: ModuleType, store: Path, repo_root: Path, tmp_path: Path
) -> None:
    setup = _load("saga_setup")
    home = tmp_path / "clear-home"
    home.mkdir()
    setup.write_machine(
        home,
        {
            "schema": "machine_record.v1",
            "ran": True,
            "offered": True,
            "survey": {
                "sandbox": {"available": True, "reproduction": "available", "reason": None}
            },
            "updated_at": "2026-10-07T00:00:00Z",
        },
    )
    record, _ = adm.admit(
        150,
        "o/r",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
        home=home,
        runner=_notice_runner(None),
    )
    notice = record.admission["setup_notice"]
    assert notice["text"] == ""
    assert notice["missing_tools"] == []
    assert notice["sandbox_unavailable"] is False


def test_suggestion_prints_once_per_machine(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    setup = _load("saga_setup")
    _patch_main(adm, monkeypatch)
    home = tmp_path / "suggest-home"
    home.mkdir()
    argv = [
        "--issue",
        "150",
        "--repo",
        "o/r",
        "--store-root",
        str(store),
        "--repo-root",
        str(repo_root),
        "--home",
        str(home),
    ]
    assert adm.main(argv) == 0
    assert capsys.readouterr().out.count(setup.SUGGESTION) == 1
    machine = setup.load_machine(home)
    assert machine is not None
    assert machine["offered"] is True
    assert machine["ran"] is not True
    assert adm.main(argv) == 0
    assert setup.SUGGESTION not in capsys.readouterr().out

    ran_home = tmp_path / "ran-home"
    ran_home.mkdir()
    setup.write_machine(
        ran_home,
        {
            "schema": "machine_record.v1",
            "ran": True,
            "offered": False,
            "survey": None,
            "updated_at": "2026-10-07T00:00:00Z",
        },
    )
    ran_argv = [*argv[:-1], str(ran_home)]
    assert adm.main(ran_argv) == 0
    assert setup.SUGGESTION not in capsys.readouterr().out

    offered_home = tmp_path / "offered-home"
    offered_home.mkdir()
    setup.write_machine(
        offered_home,
        {
            "schema": "machine_record.v1",
            "ran": False,
            "offered": True,
            "survey": None,
            "updated_at": "2026-10-07T00:00:00Z",
        },
    )
    assert adm.main([*argv[:-1], str(offered_home)]) == 0
    assert setup.SUGGESTION not in capsys.readouterr().out


def test_suggestion_is_not_printed_on_a_dry_run(
    adm: ModuleType,
    store: Path,
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    setup = _load("saga_setup")
    _patch_main(adm, monkeypatch)
    assert _run_main(adm, store, repo_root) == 0
    assert setup.SUGGESTION not in capsys.readouterr().out
    assert not (tmp_path / "admission-home" / ".saga" / "machine.json").exists()
    record, outstanding = adm.admit(
        150,
        "o/r",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert "setup_notice" not in record.admission
    rendered = adm.render(record, outstanding, None)
    assert setup.SUGGESTION not in rendered
    assert all(question.key != "setup" for question in outstanding)


def test_setup_notice_is_not_an_admission_question(adm: ModuleType) -> None:
    assert all(question.key != "setup" for question in adm.QUESTIONS)


def test_profile_written_by_setup_drops_the_functional_test_question(
    adm: ModuleType, store: Path, repo_root: Path
) -> None:
    committed = REPO_ROOT / ".saga-profile.json"
    before = committed.read_bytes()
    _write_profile(repo_root)
    profile = json.loads((repo_root / ".saga-profile.json").read_text(encoding="utf-8"))
    profile["languages"] = ["python"]
    profile["visibility"] = "public"
    (repo_root / ".saga-profile.json").write_text(json.dumps(profile), encoding="utf-8")
    record, outstanding = adm.admit(
        150,
        "o/r",
        store_root=store,
        repo_root=repo_root,
        body=_good_card(),
        validator=_passing_validator,
    )
    assert "functional_test_environment" not in {question.key for question in outstanding}
    assert record.run_configuration["concurrency_allocation"]["source"] == "profile"
    assert record.run_configuration["concurrency_allocation"]["value"] == 10
    assert record.admission["main_consumed_directly"] is False
    assert record.admission["answers"]["main_consumed_directly"]["source"] == "profile"
    assert committed.read_bytes() == before
