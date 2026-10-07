"""Tests for the build loop's check runner (issue #1027).

Every test that touches a store passes an explicit ``tmp_path`` store root or an explicit record
path under ``tmp_path``. Nothing here may create or modify anything under the primary checkout's
``.claude/saga/`` store — several card drivers share this machine and that store is live state.

Nothing here runs a real check. ``build_loop.run_check`` takes an injectable ``runner``, so ruff,
mypy, pytest and any deployment are faked at that seam; the module under test is the real one,
loaded at module scope, because ``scripts/lint_test_shape.py`` rejects a suite whose production
module is a fake.
"""

from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
REFERENCE = REPO_ROOT / "plugins" / "saga" / "references" / "mechanical-baseline.md"
RUN_RECORD_REFERENCE = REPO_ROOT / "plugins" / "saga" / "references" / "run-record.md"
PROFILE_REFERENCE = REPO_ROOT / "plugins" / "saga" / "references" / "repository-profile.md"
WORK_SKILL = REPO_ROOT / "plugins" / "saga" / "skills" / "work" / "SKILL.md"
CODE_REVIEW_SKILL = REPO_ROOT / "plugins" / "saga" / "skills" / "code-review" / "SKILL.md"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: The real module, at module scope. A suite that only ever exercised a fake would pass while the
#: shipped module was broken, which is the shape `scripts/lint_test_shape.py` exists to reject.
build_loop = _load("build_loop")
run_record = _load("run_record")
#: The lease module exactly as ``build_loop`` imported it, so a fake backend's holders are the
#: classes ``build_loop`` checks against rather than a second copy of them.
environment_lease = build_loop.environment_lease


# ---------------------------------------------------------------------------
# Fakes: the check runner, and a record on disk.
# ---------------------------------------------------------------------------


class FakeRunner:
    """A check runner whose verdict per command is scripted, and which records what it was asked.

    It honours the real runner's contract exactly, because the module's behaviour depends on it:
    ``FileNotFoundError`` for an absent program and ``subprocess.TimeoutExpired`` for a timeout are
    what the real ``subprocess.run`` raises, so a fake that returned a code instead would let a
    ``could-not-execute`` path pass untested.
    """

    def __init__(self, verdicts: dict[str, Any] | None = None, default: int = 0) -> None:
        self.verdicts = verdicts or {}
        self.default = default
        self.calls: list[list[str]] = []
        self.cwds: list[Path | None] = []

    def __call__(
        self, argv: Sequence[str], timeout: int, cwd: Path | None = None
    ) -> tuple[int, str]:
        self.calls.append(list(argv))
        if list(argv[:1]) != ["git"]:
            self.cwds.append(cwd)
        key = " ".join(argv)
        for pattern, verdict in self.verdicts.items():
            if pattern in key:
                if isinstance(verdict, BaseException):
                    raise verdict
                if callable(verdict):
                    result: tuple[int, str] = verdict(argv, timeout)
                    return result
                return int(verdict), f"scripted verdict for {pattern}"
        if argv[:1] == ["git"]:
            return 0, "a" * 40
        return self.default, ""


def _record_dict(
    *,
    baseline: list[str] | None = None,
    units: list[dict[str, Any]] | None = None,
    branch_preview: bool = False,
    schema: str = "run_record.v1",
) -> dict[str, Any]:
    return {
        "schema": schema,
        "issue": 1027,
        "repo": "infiquetra/infiquetra-claude-plugins",
        "created_at": "2026-09-20T00:00:00Z",
        "updated_at": "2026-09-20T00:00:00Z",
        "admission": {"branch_preview": branch_preview},
        "run_configuration": {
            "mechanical_tool_baseline": {
                "value": baseline if baseline is not None else ["uv run ruff check ."],
                "chosen_by": "planner",
                "source": "profile",
            }
        },
        "approval_scope": {},
        "roster": [],
        "units": units if units is not None else [{"id": "U1"}],
        "review_cycles": [],
        "next_step": "build loop",
    }


@pytest.fixture
def record_file(tmp_path: Path) -> Path:
    path = tmp_path / "issue-1027.json"
    path.write_text(json.dumps(_record_dict()), encoding="utf-8")
    return path


def _write(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _block(path: Path, unit_index: int = 0) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    block: dict[str, Any] = raw["units"][unit_index]["build_loop"]
    return block


# ---------------------------------------------------------------------------
# The baseline runs and every result is recorded.
# ---------------------------------------------------------------------------


def test_the_python_baseline_runs_and_records_each_result_with_its_catalogue_check(
    tmp_path: Path,
) -> None:
    """The card's first named test: four tools run, four results recorded, each mapped."""
    path = _write(
        tmp_path / "issue-1027.json",
        _record_dict(
            baseline=[
                "uv run ruff check .",
                "uv run ruff format --check .",
                "uv run mypy plugins/ --ignore-missing-imports",
                "uv run pytest tests/ -q",
            ]
        ),
    )
    runner = FakeRunner()
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 0

    baseline = _block(path)["iterations"][0]["baseline"]
    assert [entry["catalogue_check"] for entry in baseline] == [
        "ruff-format,ruff-lint",
        "ruff-format,ruff-lint",
        "mypy",
        None,
    ]
    assert {entry["status"] for entry in baseline} == {"pass"}
    # Every command reached the runner, not merely the first.
    assert sum(1 for call in runner.calls if call[:1] != ["git"]) == 4


def test_a_command_no_catalogue_check_claims_is_recorded_as_repository_specific(
    tmp_path: Path,
) -> None:
    """A repository may run more than the catalogue names; that is data, not an error."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["make house-check"]))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0
    entry = _block(path)["iterations"][0]["baseline"][0]
    assert entry["catalogue_check"] is None
    assert entry["status"] == "pass"


def test_a_failing_check_is_an_iteration_and_not_a_refusal(tmp_path: Path) -> None:
    """Exit 4 is its own code so that no caller can read 'not green yet' as 'stop'."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["uv run ruff check ."]))
    runner = FakeRunner(verdicts={"ruff": 1})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 4

    block = _block(path)
    assert block["iterations"][0]["green"] is False
    assert block["iterations"][0]["baseline"][0]["status"] == "fail"
    # The refusal codes must stay distinguishable from this one.
    assert build_loop.EXIT_NOT_GREEN not in (
        build_loop.EXIT_GREEN,
        build_loop.EXIT_REFUSED,
        build_loop.EXIT_UNKNOWN_VERSION,
    )
    # A non-green iteration hands nothing to code review.
    assert "handed_to_code_review" not in block


def test_a_missing_program_is_could_not_execute_and_never_a_fail(tmp_path: Path) -> None:
    """The lens catalogue's rule: an unexecutable check is never a pass and never a fail.

    Collapsing this into ``fail`` would make an environment problem look like a defect in the code;
    collapsing it into ``pass`` would let a missing tool report green.
    """
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["ruff check ."]))
    runner = FakeRunner(verdicts={"ruff": FileNotFoundError("ruff")})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 4
    entry = _block(path)["iterations"][0]["baseline"][0]
    assert entry["status"] == "could-not-execute"
    assert entry["exit_code"] is None
    assert "not installed" in entry["detail"]


def test_a_timeout_is_could_not_execute(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["uv run pytest -q"]))
    runner = FakeRunner(verdicts={"pytest": subprocess.TimeoutExpired("pytest", 1)})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 4
    entry = _block(path)["iterations"][0]["baseline"][0]
    assert entry["status"] == "could-not-execute"
    assert "did not finish" in entry["detail"]


def test_a_command_that_does_not_parse_never_reaches_a_shell(tmp_path: Path) -> None:
    """An unsplittable profile entry is recorded, not handed to a shell to interpret."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=['uv run ruff "unclosed']))
    runner = FakeRunner()
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 4
    entry = _block(path)["iterations"][0]["baseline"][0]
    assert entry["status"] == "could-not-execute"
    assert "argument vector" in entry["detail"]
    assert all(call[:1] == ["git"] for call in runner.calls), "the bad command must not have run"


# ---------------------------------------------------------------------------
# The preview, in all three of its cases.
# ---------------------------------------------------------------------------


def test_a_declared_preview_is_invoked_and_its_result_recorded(tmp_path: Path) -> None:
    """The card's second named test, first half."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(branch_preview=True))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".saga-profile.json").write_text(
        json.dumps({"schema": "repository_profile.v1", "branch_preview_command": "deploy-preview"}),
        encoding="utf-8",
    )
    runner = FakeRunner()
    code = build_loop.main(
        ["--record", str(path), "--unit", "U1", "--repo-root", str(repo_root)], runner=runner
    )
    assert code == 0
    preview = _block(path)["iterations"][0]["preview"]
    assert preview == {
        "declared": True,
        "status": "pass",
        "command": "deploy-preview",
        "exit_code": 0,
        "duration_seconds": preview["duration_seconds"],
        "detail": "",
    }
    assert ["deploy-preview"] in runner.calls


def test_an_undeclared_preview_is_skipped_with_a_record_entry_and_never_an_error(
    tmp_path: Path,
) -> None:
    """The card's second named test, second half: skipped with an entry, never an error."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(branch_preview=False))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0
    preview = _block(path)["iterations"][0]["preview"]
    assert preview["declared"] is False
    assert preview["status"] == "no-preview-declared"
    assert _block(path)["iterations"][0]["green"] is True


def test_a_declared_preview_with_no_command_is_could_not_execute_never_a_guess(
    tmp_path: Path,
) -> None:
    """Guessing a deployment command is the one guess that can do real damage."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(branch_preview=True))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    runner = FakeRunner()
    assert (
        build_loop.main(
            ["--record", str(path), "--unit", "U1", "--repo-root", str(repo_root)], runner=runner
        )
        == 4
    )
    preview = _block(path)["iterations"][0]["preview"]
    assert preview["status"] == "could-not-execute"
    assert preview["detail"] == "the profile declares a preview but names no command"
    # The baseline still runs; what must NOT happen is a deployment invented to fill the gap.
    assert [call for call in runner.calls if call[:1] not in (["git"], ["uv"])] == []


# ---------------------------------------------------------------------------
# Green, and the hand-off.
# ---------------------------------------------------------------------------


def test_the_loop_exits_green_only_when_every_check_and_the_smoke_are_green(
    tmp_path: Path,
) -> None:
    """The card's third named test, first half."""
    unit = {
        "id": "U1",
        "functional_checks": [{"name": "cli", "command": "check-cli"}],
        "scenario_smoke": [{"name": "smoke", "command": "smoke-it"}],
    }
    path = _write(
        tmp_path / "issue-1027.json", _record_dict(baseline=["uv run ruff check ."], units=[unit])
    )
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0

    path_red = _write(
        tmp_path / "issue-red.json", _record_dict(baseline=["uv run ruff check ."], units=[unit])
    )
    runner = FakeRunner(verdicts={"smoke-it": 1})
    assert build_loop.main(["--record", str(path_red), "--unit", "U1"], runner=runner) == 4
    assert _block(path_red)["iterations"][0]["scenario_smoke"][0]["status"] == "fail"


def test_the_green_iteration_hands_over_a_forty_character_revision(tmp_path: Path) -> None:
    """The card's third named test, second half: code review gets the exact revision.

    ``/code-review`` Phase 0.2 refuses an abbreviation or a symbolic reference, so the shape is
    part of the contract and not a detail of presentation.
    """
    path = _write(tmp_path / "issue-1027.json", _record_dict())
    revision = "c0ffee" + "0" * 34
    runner = FakeRunner(verdicts={"rev-parse": lambda argv, timeout: (0, revision)})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 0

    handed = _block(path)["handed_to_code_review"]
    assert handed["revision"] == revision
    assert len(handed["revision"]) == 40
    assert _block(path)["iterations"][0]["revision"] == revision


def test_an_abbreviated_revision_is_refused_rather_than_recorded(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict())
    runner = FakeRunner(verdicts={"rev-parse": lambda argv, timeout: (0, "c0ffee0")})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 2


# ---------------------------------------------------------------------------
# Absence, recorded rather than shown as nothing.
# ---------------------------------------------------------------------------


def test_absent_functional_checks_and_smoke_read_empty_with_a_none_prescribed_reason(
    tmp_path: Path,
) -> None:
    """Plan KTD9: a reader must tell 'none prescribed' from 'three prescribed and lost'."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[{"id": "U1"}]))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0

    iteration = _block(path)["iterations"][0]
    assert iteration["functional_checks"] == []
    assert iteration["functional_checks_reason"] == build_loop.REASON_NONE_PRESCRIBED
    assert iteration["scenario_smoke"] == []
    assert iteration["scenario_smoke_reason"] == build_loop.REASON_NONE_PRESCRIBED
    assert iteration["green"] is True


def test_a_prescribed_check_list_carries_no_none_prescribed_reason(tmp_path: Path) -> None:
    """The control: the reason must DISCRIMINATE, or 'always present' would pass the test above."""
    unit = {"id": "U1", "functional_checks": [{"name": "cli", "command": "check-cli"}]}
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[unit]))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0
    iteration = _block(path)["iterations"][0]
    assert "functional_checks_reason" not in iteration
    assert iteration["scenario_smoke_reason"] == build_loop.REASON_NONE_PRESCRIBED


# ---------------------------------------------------------------------------
# The plan's checks, as functional_checks.py writes them (issue #98).
# ---------------------------------------------------------------------------

#: One unit row exactly as ``functional_checks.py write`` leaves it.
PLANNED_UNIT: dict[str, Any] = {
    "id": "U1",
    "functional_checks": [
        {"name": "cli", "command": "check-cli", "proves": ["AC-1"], "runs": "local"},
        {"name": "stack", "command": "check-stack", "proves": ["AC-2"], "runs": "environment"},
    ],
    "scenario_smoke": [
        {"name": "smoke", "command": "smoke-it", "proves": ["AC-3"], "runs": "environment"}
    ],
}


def test_the_recorded_criterion_keeps_what_each_check_proves_and_where_it_runs(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[PLANNED_UNIT]))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0
    criterion = _block(path)["exit_criterion"]
    assert criterion["functional_checks"] == PLANNED_UNIT["functional_checks"]
    assert criterion["scenario_smoke"] == PLANNED_UNIT["scenario_smoke"]


def test_an_environment_check_is_recorded_but_not_run_in_a_unit_iteration(
    tmp_path: Path,
) -> None:
    """Pre-review testing ruling 3: the declared environment only ever gets the combined branch."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[PLANNED_UNIT]))
    runner = FakeRunner()
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 0

    ran = {call[0] for call in runner.calls}
    assert "check-cli" in ran
    assert "check-stack" not in ran and "smoke-it" not in ran
    iteration = _block(path)["iterations"][0]
    assert [entry["name"] for entry in iteration["functional_checks"]] == ["cli"]
    assert "functional_checks_reason" not in iteration
    assert iteration["scenario_smoke"] == []
    assert iteration["scenario_smoke_reason"] == build_loop.REASON_DEFERRED == (
        "deferred-to-combined-branch"
    )


def test_a_list_of_only_environment_checks_is_deferred_not_none_prescribed(
    tmp_path: Path,
) -> None:
    unit = {"id": "U1", "functional_checks": [PLANNED_UNIT["functional_checks"][1]]}
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[unit]))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0
    iteration = _block(path)["iterations"][0]
    assert iteration["functional_checks_reason"] == build_loop.REASON_DEFERRED
    assert iteration["scenario_smoke_reason"] == build_loop.REASON_NONE_PRESCRIBED


def test_a_check_with_no_runs_key_still_runs_locally(tmp_path: Path) -> None:
    """Back-compatibility: every entry written before issue #98 carries no ``runs``."""
    unit = {"id": "U1", "functional_checks": [{"name": "old", "command": "old-check"}]}
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[unit]))
    runner = FakeRunner(verdicts={"old-check": 1})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 4
    assert _block(path)["iterations"][0]["functional_checks"][0]["status"] == "fail"


def test_the_dry_run_of_a_record_with_several_units_lists_each_unit_s_checks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Before issue #98 a dry run with no --unit on two rows printed 'none prescribed'."""
    second = {
        "id": "U2",
        "functional_checks": [
            {"name": "api", "command": "check-api", "proves": ["AC-4"], "runs": "local"}
        ],
        "scenario_smoke": PLANNED_UNIT["scenario_smoke"],
    }
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[PLANNED_UNIT, second]))
    argv = ["--record", str(path), "--repo-root", str(tmp_path), "--dry-run"]
    assert build_loop.main(argv, runner=FakeRunner()) == 0
    out = capsys.readouterr().out
    assert "none prescribed in the run record" not in out
    assert "  Unit U1:\n    cli: check-cli  (proves AC-1; runs locally)" in out
    assert (
        "    stack: check-stack  (proves AC-2; runs against the declared environment, on the "
        "combined branch)"
    ) in out
    assert "  Unit U2:\n    api: check-api  (proves AC-4; runs locally)" in out
    assert out.count("smoke: smoke-it") == 1


def test_the_dry_run_lists_the_smoke_per_unit_when_the_units_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    second = {"id": "U2", "scenario_smoke": [{"name": "other", "command": "other-smoke"}]}
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[PLANNED_UNIT, second]))
    argv = ["--record", str(path), "--repo-root", str(tmp_path), "--dry-run"]
    assert build_loop.main(argv, runner=FakeRunner()) == 0
    smoke = capsys.readouterr().out.split("Scenario smoke, from the plan:")[1]
    assert "  Unit U1:\n    smoke: smoke-it" in smoke
    assert "  Unit U2:\n    other: other-smoke" in smoke


def test_the_reference_no_longer_says_no_step_writes_the_checks() -> None:
    """Issue #98, third criterion: the writer exists, so the sentence denying it is gone."""
    text = REFERENCE.read_text(encoding="utf-8")
    assert "No step in saga writes these onto a unit's row yet" not in text
    assert "functional_checks.py write" in text
    assert build_loop.REASON_DEFERRED in text


# ---------------------------------------------------------------------------
# The record: iterations accumulate, unknown keys survive, versions are refused.
# ---------------------------------------------------------------------------


def test_iterations_accumulate_and_are_numbered_from_one(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["uv run ruff check ."]))
    assert (
        build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner({"ruff": 1}))
        == 4
    )
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0

    iterations = _block(path)["iterations"]
    assert [entry["iteration"] for entry in iterations] == [1, 2]
    assert [entry["green"] for entry in iterations] == [False, True]


def test_an_unknown_key_on_the_unit_row_survives_an_iteration_write(tmp_path: Path) -> None:
    """``run-record.md``'s rule for a unit row: a key another consumer does not know is left alone."""
    unit = {"id": "U1", "merge_state": "ready", "a_newer_key": {"kept": True}}
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[unit]))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0

    raw = json.loads(path.read_text(encoding="utf-8"))["units"][0]
    assert raw["merge_state"] == "ready"
    assert raw["a_newer_key"] == {"kept": True}


def test_an_unknown_top_level_field_survives_an_iteration_write(tmp_path: Path) -> None:
    payload = _record_dict()
    payload["orchestrate"] = {"run_branch": "parent/1018"}
    path = _write(tmp_path / "issue-1027.json", payload)
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0
    assert json.loads(path.read_text(encoding="utf-8"))["orchestrate"] == {
        "run_branch": "parent/1018"
    }


def test_an_unknown_record_version_is_one_line_and_exit_three(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict(schema="run_record.v2"))
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 3
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1, "a known refusal is one line, never a traceback"
    assert "run_record.v2" in err[0]


def test_a_missing_record_is_a_refusal_naming_the_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "nowhere.json"
    assert build_loop.main(["--record", str(missing), "--unit", "U1"], runner=FakeRunner()) == 2
    assert str(missing) in capsys.readouterr().err


def test_an_ambiguous_unit_refuses_rather_than_picking(tmp_path: Path) -> None:
    """Writing an iteration onto the wrong unit is worse than stopping."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[{"id": "U1"}, {"id": "U2"}]))
    assert build_loop.main(["--record", str(path)], runner=FakeRunner()) == 2


def test_a_named_unit_that_does_not_exist_refuses_and_lists_the_ones_that_do(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict(units=[{"id": "U1"}, {"id": "U2"}]))
    assert build_loop.main(["--record", str(path), "--unit", "U9"], runner=FakeRunner()) == 2
    err = capsys.readouterr().err
    assert "U1" in err and "U2" in err


# ---------------------------------------------------------------------------
# The dry run.
# ---------------------------------------------------------------------------


def test_the_dry_run_prints_the_checks_and_whether_a_preview_is_declared(
    record_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The card's first acceptance criterion, as a test."""
    assert build_loop.main(["--record", str(record_file), "--dry-run"], runner=FakeRunner()) == 0
    out = capsys.readouterr().out
    assert "uv run ruff check ." in out
    assert "answers: ruff-format,ruff-lint" in out
    assert "branch preview: none declared" in out
    assert "none prescribed in the run record" in out


def test_the_dry_run_names_every_uncovered_review_tool(
    record_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gap is the review-tool list. This baseline does not run bandit."""
    assert build_loop.main(["--record", str(record_file), "--dry-run"], runner=FakeRunner()) == 0
    out = capsys.readouterr().out
    for uncovered in (
        "semgrep-saga",
        "semgrep-security",
        "gitleaks",
        "osv-scanner",
        "jscpd",
        "lizard",
        "bandit",
    ):
        assert uncovered in out
    assert "Named scanners" not in out
    section = out.split("Review tools this baseline does not name:", 1)[1]
    section = section.split("Child-scoped functional checks", 1)[0]
    assert "\n  coverage " not in section
    assert "relocated-test" not in section


def test_the_check_map_comes_from_the_default_tool_list() -> None:
    """``semgrep scan`` answers both semgrep rows. ``gitleaks detect`` answers gitleaks."""
    mapping = build_loop.check_map(["semgrep scan", "gitleaks detect", "make house-check"])
    assert [entry["catalogue_check"] for entry in mapping["commands"]] == [
        "semgrep-saga,semgrep-security",
        "gitleaks",
        None,
    ]
    uncovered = {entry["catalogue_check"] for entry in mapping["uncovered"]}
    assert "semgrep-saga" not in uncovered
    assert "gitleaks" not in uncovered
    assert "osv-scanner" in uncovered
    assert "jscpd" in uncovered
    assert "lizard" in uncovered
    assert "coverage" not in uncovered
    assert "relocated-test" not in uncovered
    assert "saga-git" not in uncovered
    unnamed = build_loop.check_map(["make house-check"])
    unnamed_ids = {entry["catalogue_check"] for entry in unnamed["uncovered"]}
    assert "semgrep-security" in unnamed_ids
    assert "saga-git" not in unnamed_ids
    # The ruff rows answer the ruff token. catalogue: false keeps saga-uv out of that answer.
    assert build_loop.catalogue_check_for("uv run ruff check .") == "ruff-format,ruff-lint"
    assert build_loop.catalogue_check_for("git diff --check") is None
    assert build_loop.catalogue_check_for("python3 scripts/check_repo.py") is None
    assert "unconfigured_scanners" not in mapping


def test_saga_scripts_do_not_read_mechanical_checks() -> None:
    """The lifecycle map is not a source this package reads."""
    roots = (REPO_ROOT / "plugins" / "saga" / "scripts", REPO_ROOT / "plugins" / "saga" / "skills")
    offenders = []
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix not in {".py", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "mechanical_checks" in text:
                offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


def test_importing_build_loop_does_not_import_the_adapters() -> None:
    """The tool list is a yaml read. Importing the loop does not import the adapters."""
    probe = (
        "import sys\n"
        f"sys.path.insert(0, {str(SCRIPTS)!r})\n"
        "import build_loop\n"
        "raise SystemExit('review_adapters_all_languages' in sys.modules)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_the_dry_run_says_a_preview_is_declared_when_it_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control: 'none declared' must discriminate, not be printed unconditionally."""
    path = _write(tmp_path / "issue-1027.json", _record_dict(branch_preview=True))
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".saga-profile.json").write_text(
        json.dumps({"branch_preview_command": "deploy-preview"}), encoding="utf-8"
    )
    assert (
        build_loop.main(
            ["--record", str(path), "--dry-run", "--repo-root", str(repo_root)], runner=FakeRunner()
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "branch preview: declared, command: deploy-preview" in out
    assert "none declared" not in out


def test_the_dry_run_writes_nothing_and_runs_nothing(record_file: Path) -> None:
    before = record_file.read_text(encoding="utf-8")
    runner = FakeRunner()
    assert build_loop.main(["--record", str(record_file), "--dry-run"], runner=runner) == 0
    assert record_file.read_text(encoding="utf-8") == before
    assert runner.calls == []


def test_the_dry_run_needs_no_unit(record_file: Path) -> None:
    """The card's criterion names no --unit, so the dry run must work without one."""
    assert build_loop.main(["--record", str(record_file), "--dry-run"], runner=FakeRunner()) == 0


def test_naming_neither_a_record_nor_an_issue_is_a_refusal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert build_loop.main(["--dry-run"], runner=FakeRunner()) == 2
    assert "--record" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The declared functional-test environment, printed and recorded (issue #97).
# ---------------------------------------------------------------------------

_DECLARED = {
    "mode": "declared",
    "kind": "ephemeral-stack",
    "deploy_command": "make stack-up",
    "test_command": "make functional",
    "teardown_command": "make stack-down",
    "scope": "private",
    "source": "operator",
}


def _with_environment(environment: dict[str, Any] | None) -> dict[str, Any]:
    payload = _record_dict()
    if environment is not None:
        payload["admission"]["functional_test_environment"] = environment
    return payload


def test_the_dry_run_prints_the_declared_environment_from_the_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _with_environment(_DECLARED))
    assert build_loop.main(["--record", str(path), "--dry-run"], runner=FakeRunner()) == 0
    out = capsys.readouterr().out
    assert "Functional-test environment, from operator:" in out
    assert "kind: ephemeral-stack (scope: private)" in out
    assert "deploy or start: make stack-up" in out
    assert "test: make functional" in out
    assert "teardown: make stack-down" in out


def test_the_dry_run_prints_the_waiver_and_its_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waiver = {
        "mode": "waived",
        "level": "repository",
        "reason": "documentation only",
        "source": "profile",
    }
    path = _write(tmp_path / "issue-1027.json", _with_environment(waiver))
    assert build_loop.main(["--record", str(path), "--dry-run"], runner=FakeRunner()) == 0
    out = capsys.readouterr().out
    assert "Functional-test waiver, from profile: documentation only" in out
    assert "run on the combined branch" not in out


def test_the_dry_run_says_when_no_environment_is_declared(
    record_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "empty-repo"
    empty.mkdir()
    assert (
        build_loop.main(
            ["--record", str(record_file), "--dry-run", "--repo-root", str(empty)],
            runner=FakeRunner(),
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Functional-test environment:\n  not declared — admission asks for it" in out


def test_a_record_admitted_before_the_block_falls_back_to_the_profile(
    record_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps(
            {
                "functional_test_environment": {
                    "kind": "local",
                    "test_command": "python3 -m pytest tests -q",
                    "scope": "private",
                }
            }
        ),
        encoding="utf-8",
    )
    assert (
        build_loop.main(
            ["--record", str(record_file), "--dry-run", "--profile", str(profile)],
            runner=FakeRunner(),
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Functional-test environment, from profile:" in out
    assert "deploy or start: none — local" in out
    assert "test: python3 -m pytest tests -q" in out


def test_a_legacy_preview_reads_as_an_incomplete_declaration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict(branch_preview=True))
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"branch_preview_command": "deploy-preview"}), encoding="utf-8")
    assert (
        build_loop.main(
            ["--record", str(path), "--dry-run", "--profile", str(profile)], runner=FakeRunner()
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "Functional-test environment, from legacy-branch-preview:" in out
    assert "deploy or start: deploy-preview" in out
    assert "missing test_command" in out


def test_an_invalid_profile_declaration_is_a_refusal(
    record_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile = tmp_path / "profile.json"
    profile.write_text(
        json.dumps({"functional_test_environment": {"kind": "local", "scope": "private"}}),
        encoding="utf-8",
    )
    assert (
        build_loop.main(
            ["--record", str(record_file), "--dry-run", "--profile", str(profile)],
            runner=FakeRunner(),
        )
        == 2
    )
    assert "test_command" in capsys.readouterr().err


def test_an_iteration_records_the_environment_and_runs_none_of_its_commands(
    tmp_path: Path,
) -> None:
    """U2 declares and records; running the commands on the combined branch is U4."""
    path = _write(tmp_path / "issue-1027.json", _with_environment(_DECLARED))
    runner = FakeRunner()
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 0
    criterion = _block(path)["exit_criterion"]
    assert criterion["environment"] == _DECLARED
    ran = [" ".join(call) for call in runner.calls]
    assert not any("make" in call for call in ran), ran


# ---------------------------------------------------------------------------
# The drift guards: the document and the code say the same thing.
# ---------------------------------------------------------------------------


def _marked_table(text: str, marker: str) -> list[str]:
    body = text.split(f"<!-- BEGIN {marker} -->")[1].split(f"<!-- END {marker} -->")[0]
    return [
        row.split("|")[1].strip().strip("`")
        for row in body.strip().splitlines()
        if row.startswith("|") and not set(row) <= set("|- ")
    ][1:]


def test_the_record_block_key_set_matches_the_reference_document(tmp_path: Path) -> None:
    """U2's drift guard: the shape `tests/test_run_record.py` uses for `run-record.md`."""
    path = _write(tmp_path / "issue-1027.json", _record_dict())
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0

    documented = set(_marked_table(REFERENCE.read_text(encoding="utf-8"), "BUILD-LOOP BLOCK"))
    assert set(_block(path)) == documented


def test_the_iteration_key_set_matches_the_reference_document(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict())
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0

    documented = set(_marked_table(REFERENCE.read_text(encoding="utf-8"), "ITERATION KEYS"))
    written = set(_block(path)["iterations"][0])
    # The two `*_reason` keys are conditional and documented in prose, not in the key table.
    assert written - {"functional_checks_reason", "scenario_smoke_reason"} == documented


def test_the_three_statuses_match_the_reference_document() -> None:
    documented = set(_marked_table(REFERENCE.read_text(encoding="utf-8"), "STATUSES"))
    assert documented == {
        build_loop.STATUS_PASS,
        build_loop.STATUS_FAIL,
        build_loop.STATUS_COULD_NOT_EXECUTE,
    }


def test_the_exit_codes_match_the_reference_document() -> None:
    """A table a reader trusts must be the table the code returns."""
    documented = {
        int(code) for code in _marked_table(REFERENCE.read_text(encoding="utf-8"), "EXIT CODES")
    }
    assert documented == {
        build_loop.EXIT_GREEN,
        build_loop.EXIT_INTERNAL,
        build_loop.EXIT_REFUSED,
        build_loop.EXIT_UNKNOWN_VERSION,
        build_loop.EXIT_NOT_GREEN,
        build_loop.EXIT_ENVIRONMENT_STOP,
    }


def test_the_unit_key_is_named_in_the_run_record_reference() -> None:
    """A key one consumer writes and the record's own document never mentions is the drift."""
    assert build_loop.UNIT_KEY in RUN_RECORD_REFERENCE.read_text(encoding="utf-8")


def test_the_optional_preview_command_key_is_named_in_the_profile_reference() -> None:
    """The same rule for the profile: a key read in code is written down where a writer looks."""
    assert "branch_preview_command" in PROFILE_REFERENCE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The skill says what the module does.
# ---------------------------------------------------------------------------


def test_the_work_skill_runs_the_build_loop_and_calls_exit_four_an_iteration() -> None:
    """The prose and the code must agree that 4 is not a refusal.

    A skill that told a worker to stop on exit 4 would reintroduce the gate this card removed,
    while every test above still passed.
    """
    text = WORK_SKILL.read_text(encoding="utf-8")
    assert "build_loop.py" in text
    collapsed = " ".join(text.split())
    assert re.search(r"4 — not green yet", collapsed), "the skill must name exit 4 by number"
    assert "loop iteration, not a refusal" in collapsed


def test_the_work_skill_no_longer_carries_the_removed_gate_or_ceremony() -> None:
    text = WORK_SKILL.read_text(encoding="utf-8")
    assert "requires_hard_test_gate" not in text
    assert "ship_ceremony" not in text


def test_the_preservation_contract_survives_in_the_work_skill() -> None:
    """Issue #1029's contract: pull-request open, review request and merge stay confirmed."""
    collapsed = " ".join(WORK_SKILL.read_text(encoding="utf-8").split())
    assert "explicitly confirmed" in collapsed


# ---------------------------------------------------------------------------
# Globs: a profile entry is a command line, and a command line may carry one.
# ---------------------------------------------------------------------------


def test_a_glob_in_a_baseline_command_is_expanded_without_a_shell(tmp_path: Path) -> None:
    """This repository's own profile carries ``plugins/*/tests/``, and the loop found it.

    The loop never uses a shell, on purpose: a profile entry is tracked configuration and
    tracked configuration does not reach ``sh -c``. But a command line written by a human
    legitimately carries a glob, and passing ``plugins/*/tests/`` through verbatim hands pytest a
    literal path that does not exist -- which the loop then records as a ``fail``, indistinguishable
    from a real test failure. So the loop expands globs itself, the way a shell would, and keeps
    ``shell=False``.
    """
    repo = tmp_path / "repo"
    (repo / "plugins" / "alpha" / "tests").mkdir(parents=True)
    (repo / "plugins" / "beta" / "tests").mkdir(parents=True)

    path = _write(
        tmp_path / "issue-1027.json", _record_dict(baseline=["pytest plugins/*/tests/ -q"])
    )
    runner = FakeRunner()
    assert (
        build_loop.main(
            ["--record", str(path), "--unit", "U1", "--repo-root", str(repo)], runner=runner
        )
        == 0
    )
    call = next(c for c in runner.calls if c[:1] != ["git"])
    assert "plugins/*/tests/" not in call, "the glob must not reach the program verbatim"
    # The trailing slash survives, exactly as it does through a shell.
    assert sorted(part for part in call if "alpha" in part or "beta" in part) == [
        "plugins/alpha/tests/",
        "plugins/beta/tests/",
    ]


def test_a_glob_that_matches_nothing_is_passed_through_verbatim(tmp_path: Path) -> None:
    """A shell does this too, and the program's own error is clearer than a silent drop."""
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _write(
        tmp_path / "issue-1027.json", _record_dict(baseline=["pytest nowhere/*/tests -q"])
    )
    runner = FakeRunner()
    assert (
        build_loop.main(
            ["--record", str(path), "--unit", "U1", "--repo-root", str(repo)], runner=runner
        )
        == 0
    )
    call = next(c for c in runner.calls if c[:1] != ["git"])
    assert "nowhere/*/tests" in call


def test_a_check_runs_from_the_repository_root_not_the_caller_s_directory(tmp_path: Path) -> None:
    """Which directory a check runs in decides what it checks, so it is named, not inherited."""
    repo = tmp_path / "repo"
    repo.mkdir()
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["uv run ruff check ."]))
    runner = FakeRunner()
    assert (
        build_loop.main(
            ["--record", str(path), "--unit", "U1", "--repo-root", str(repo)], runner=runner
        )
        == 0
    )
    assert runner.cwds and all(cwd == repo for cwd in runner.cwds)


# ---------------------------------------------------------------------------
# The run-record lock convention (issue 95)
# ---------------------------------------------------------------------------


def test_a_usage_entry_added_while_the_checks_run_survives_the_iteration_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The checks run with no lock held; the iteration lands on a record re-read under the lock.

    Before issue 95 the build loop saved the copy it read before the checks, so a unit session's
    ``usage add`` that landed while they ran was silently erased.
    """
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["uv run ruff check ."]))

    def usage_lands_mid_check(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        run_record.update(
            tmp_path,
            1027,
            lambda record: run_record.add_usage(
                record,
                "U1",
                session_id="reviewer-1",
                role="lens-reviewer",
                vendor="claude",
                model="claude-opus-5-5",
                effort="high",
                counts={"output": 10},
            ),
        )
        return 0, ""

    held: list[bool] = []
    real_save = build_loop.save_record_file

    def save_record_file(record_path: Path, record: run_record.RunRecord) -> Path:
        # A non-blocking probe: it fails to take the lock only if build_loop holds it now.
        fd = os.open(record_path.with_name(record_path.name + ".lock"), os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held.append(False)
            fcntl.flock(fd, fcntl.LOCK_UN)
        except BlockingIOError:
            held.append(True)
        finally:
            os.close(fd)
        return real_save(record_path, record)

    monkeypatch.setattr(build_loop, "save_record_file", save_record_file)
    runner = FakeRunner(verdicts={"ruff": usage_lands_mid_check})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 0

    assert held == [True], "the re-read and the write happen under the record's lock"
    row = json.loads(path.read_text(encoding="utf-8"))["units"][0]
    assert [entry["session_id"] for entry in row["usage"]["entries"]] == ["reviewer-1"]
    assert row["build_loop"]["iterations"][0]["green"] is True
    assert row["build_loop"]["handed_to_code_review"]["revision"] == "a" * 40


def test_an_iteration_is_numbered_against_the_record_read_under_the_lock(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _record_dict(baseline=["uv run ruff check ."]))

    def another_iteration_lands(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw["units"][0]["build_loop"] = {"iterations": [{"iteration": 1, "green": False}]}
        path.write_text(json.dumps(raw), encoding="utf-8")
        return 0, ""

    runner = FakeRunner(verdicts={"ruff": another_iteration_lands})
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=runner) == 0
    iterations = _block(path)["iterations"]
    assert [entry["iteration"] for entry in iterations] == [1, 2]


# ---------------------------------------------------------------------------
# The combined-branch pass (issue #99, pre-review testing U4).
# ---------------------------------------------------------------------------

_SHARED = {
    "mode": "declared",
    "kind": "shared-nonprod",
    "deploy_command": "deploy-stack --env nonprod",
    "test_command": "run-functional",
    "teardown_command": "teardown-stack",
    "scope": "shared",
    "source": "profile",
}

_PRIVATE = {**_DECLARED, "deploy_command": "deploy-stack", "test_command": "run-functional",
            "teardown_command": "teardown-stack"}


class FakeLeaseBackend:
    """An in-memory lease store with the git backend's semantics: one holder per name, never
    replaced, and a compare-and-swap release. Shared between two runs, it stands in for the one
    remote both hosts see."""

    def __init__(self) -> None:
        self.refs: dict[str, tuple[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self._next = 0

    def _token(self) -> str:
        self._next += 1
        return f"{self._next:040x}"

    def hold(self, name: str, holder: Any) -> str:
        token = self._token()
        self.refs[name] = (token, holder)
        return token

    def acquire(self, name: str, holder: Any) -> Any:
        self.calls.append(("acquire", name))
        current = self.refs.get(name)
        if current is not None:
            return environment_lease.AcquireResult(
                environment_lease.HELD, token=current[0], holder=current[1]
            )
        token = self.hold(name, holder)
        return environment_lease.AcquireResult(environment_lease.ACQUIRED, token=token, holder=holder)

    def read(self, name: str) -> Any:
        current = self.refs.get(name)
        if current is None:
            return environment_lease.LeaseState(name=name, held=False)
        return environment_lease.LeaseState(
            name=name, held=True, token=current[0], holder=current[1]
        )

    def release(self, name: str, token: str) -> Any:
        self.calls.append(("release", name))
        current = self.refs.get(name)
        if current is None or current[0] != token:
            return environment_lease.ReleaseResult(environment_lease.NOT_HELD)
        del self.refs[name]
        return environment_lease.ReleaseResult(environment_lease.RELEASED)


def _combined_record(
    environment: dict[str, Any] | None = _SHARED,
    *,
    issue: int = 1027,
    units: list[dict[str, Any]] | None = None,
    baseline: list[str] | None = None,
) -> dict[str, Any]:
    payload = _record_dict(baseline=baseline, units=units)
    payload["issue"] = issue
    if environment is not None:
        payload["admission"]["functional_test_environment"] = dict(environment)
    return payload


def _combined(
    path: Path,
    runner: FakeRunner,
    backend: Any = None,
    *extra: str,
    repo_root: Path | None = None,
) -> int:
    argv = ["--record", str(path), "--combined", "--lease-wait", "0", *extra]
    if repo_root is not None:
        argv += ["--repo-root", str(repo_root)]
    code: int = build_loop.main(argv, runner=runner, lease_backend=backend, sleep=lambda _: None)
    return code


def _combined_block(path: Path) -> dict[str, Any]:
    block: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))["combined_branch"]
    return block


def _commands(runner: FakeRunner) -> list[str]:
    return [" ".join(call) for call in runner.calls if call[:1] != ["git"]]


def test_a_combined_pass_runs_baseline_deploy_test_teardown_in_order_and_records_each(
    tmp_path: Path,
) -> None:
    """Acceptance criteria 1 and 2: the order, and every step's result on the run record."""
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner, backend = FakeRunner(), FakeLeaseBackend()
    assert _combined(path, runner, backend) == build_loop.EXIT_GREEN

    assert _commands(runner) == [
        "uv run ruff check .",
        "deploy-stack --env nonprod",
        "run-functional",
        "teardown-stack",
    ]
    assert [call[0] for call in backend.calls] == ["acquire", "release"]
    block = _combined_block(path)
    entry = block["passes"][-1]
    assert entry["pass"] == 1 and entry["status"] == "pass" and entry["green"] is True
    for step, command in (
        ("deploy", "deploy-stack --env nonprod"),
        ("test", "run-functional"),
        ("teardown", "teardown-stack"),
    ):
        assert entry[step]["command"] == command
        assert entry[step]["status"] == "pass"
        assert entry[step]["exit_code"] == 0
        assert {"duration_seconds", "detail"} <= set(entry[step])
    assert entry["lease"]["status"] == "acquired"
    assert entry["lease"]["release_status"] == "released"
    assert entry["lease"]["ref"] == "refs/saga/leases/shared-nonprod"
    assert block["environment"]["kind"] == "shared-nonprod"
    handed = block["handed_to_code_review"]
    assert len(handed["revision"]) == 40 and handed["pass"] == 1 and handed["waived"] is False
    assert backend.refs == {}, "the lease is released after teardown"


def test_teardown_runs_after_a_failing_test_and_the_pass_is_a_loop_pass(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner, backend = FakeRunner(verdicts={"run-functional": 1}), FakeLeaseBackend()
    assert _combined(path, runner, backend) == build_loop.EXIT_NOT_GREEN

    assert _commands(runner)[-1] == "teardown-stack"
    entry = _combined_block(path)["passes"][-1]
    assert entry["status"] == "fail"
    assert entry["test"]["status"] == "fail"
    assert entry["teardown"]["status"] == "pass"
    assert entry["lease"]["release_status"] == "released"
    assert "handed_to_code_review" not in _combined_block(path)


def test_a_failed_deploy_is_could_not_execute_skips_the_test_and_still_tears_down(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner, backend = FakeRunner(verdicts={"deploy-stack": 1}), FakeLeaseBackend()
    assert _combined(path, runner, backend) == build_loop.EXIT_NOT_GREEN

    assert "run-functional" not in _commands(runner)
    assert _commands(runner)[-1] == "teardown-stack"
    entry = _combined_block(path)["passes"][-1]
    assert entry["deploy"]["status"] == "could-not-execute"
    assert entry["deploy"]["exit_code"] == 1
    assert entry["test"] is None
    assert entry["status"] == "could-not-execute"
    assert entry["environment_problems"][0].startswith("deploy:")
    assert entry["lease"]["release_status"] == "released"


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired(cmd="deploy-stack", timeout=1),
        FileNotFoundError("deploy-stack"),
    ],
    ids=["timeout", "missing-program"],
)
def test_teardown_runs_after_a_deploy_timeout_or_a_missing_deploy_program(
    tmp_path: Path, failure: BaseException
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner, backend = FakeRunner(verdicts={"deploy-stack": failure}), FakeLeaseBackend()
    assert _combined(path, runner, backend) == build_loop.EXIT_NOT_GREEN

    entry = _combined_block(path)["passes"][-1]
    assert entry["deploy"]["status"] == "could-not-execute"
    assert entry["teardown"]["status"] == "pass"
    assert _commands(runner)[-1] == "teardown-stack"
    assert backend.refs == {}


def test_an_interrupt_mid_test_still_tears_down_releases_and_records_the_pass(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner = FakeRunner(verdicts={"run-functional": KeyboardInterrupt()})
    backend = FakeLeaseBackend()
    with pytest.raises(KeyboardInterrupt):
        _combined(path, runner, backend)

    assert _commands(runner)[-1] == "teardown-stack"
    assert backend.refs == {}
    entry = _combined_block(path)["passes"][-1]
    assert entry["interrupted"] is True
    assert entry["status"] == "could-not-execute"
    assert entry["teardown"]["status"] == "pass"


def test_no_declared_teardown_is_recorded_not_declared_and_the_pass_can_be_green(
    tmp_path: Path,
) -> None:
    environment = {**_SHARED, "teardown_command": None}
    path = _write(tmp_path / "issue-1027.json", _combined_record(environment))
    runner = FakeRunner()
    assert _combined(path, runner, FakeLeaseBackend()) == build_loop.EXIT_GREEN
    entry = _combined_block(path)["passes"][-1]
    assert entry["teardown"]["status"] == "not-declared"


def test_a_failing_teardown_is_an_environment_problem_and_the_lease_is_still_released(
    tmp_path: Path,
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner, backend = FakeRunner(verdicts={"teardown-stack": 2}), FakeLeaseBackend()
    assert _combined(path, runner, backend) == build_loop.EXIT_NOT_GREEN
    entry = _combined_block(path)["passes"][-1]
    assert entry["status"] == "could-not-execute"
    assert entry["teardown"]["exit_code"] == 2
    assert any(problem.startswith("teardown:") for problem in entry["environment_problems"])
    assert backend.refs == {}


def test_three_consecutive_could_not_execute_passes_stop_the_loop_with_exit_five(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The environment stop names the problem; it is an exit code, not a refusal to run again."""
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    backend = FakeLeaseBackend()
    broken = FakeRunner(verdicts={"deploy-stack": FileNotFoundError("deploy-stack")})
    assert _combined(path, broken, backend) == build_loop.EXIT_NOT_GREEN
    assert _combined(path, broken, backend) == build_loop.EXIT_NOT_GREEN
    capsys.readouterr()
    assert _combined(path, broken, backend) == build_loop.EXIT_ENVIRONMENT_STOP
    out = capsys.readouterr().out
    assert "Environment stop: 3 consecutive combined passes could not execute" in out
    assert "the program is not installed" in out

    # A fourth invocation still runs: the stop is reported, never a refusal.
    again = FakeRunner(verdicts={"deploy-stack": FileNotFoundError("deploy-stack")})
    assert _combined(path, again, backend) == build_loop.EXIT_ENVIRONMENT_STOP
    assert "uv run ruff check ." in _commands(again)
    # And a fixed environment resets the streak.
    assert _combined(path, FakeRunner(), backend) == build_loop.EXIT_GREEN


def test_a_failing_pass_resets_the_could_not_execute_streak(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    backend = FakeLeaseBackend()
    broken = FakeRunner(verdicts={"deploy-stack": 1})
    assert _combined(path, broken, backend) == build_loop.EXIT_NOT_GREEN
    assert _combined(path, broken, backend) == build_loop.EXIT_NOT_GREEN
    failing = FakeRunner(verdicts={"run-functional": 1})
    assert _combined(path, failing, backend) == build_loop.EXIT_NOT_GREEN
    assert _combined(path, broken, backend) == build_loop.EXIT_NOT_GREEN
    statuses = [entry["status"] for entry in _combined_block(path)["passes"]]
    assert statuses == ["could-not-execute", "could-not-execute", "fail", "could-not-execute"]


def _other_holder(**overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "repo": "infiquetra/other-repo",
        "issue": 77,
        "revision": "b" * 40,
        "host": "builder-2",
        "started_at": environment_lease.iso_utc(environment_lease.utc_now()),
        "bound_seconds": 5400,
    }
    fields.update(overrides)
    return environment_lease.LeaseHolder(**fields)


def test_a_second_run_cannot_take_a_held_shared_lease(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance criterion 1, lease exclusion: nothing deploys while another run holds it."""
    backend = FakeLeaseBackend()
    token = backend.hold("shared-nonprod", _other_holder())
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner = FakeRunner()
    assert _combined(path, runner, backend) == build_loop.EXIT_NOT_GREEN

    assert "deploy-stack --env nonprod" not in _commands(runner)
    assert "teardown-stack" not in _commands(runner)
    assert backend.refs["shared-nonprod"][0] == token, "another run's lease is never touched"
    assert ("release", "shared-nonprod") not in backend.calls
    entry = _combined_block(path)["passes"][-1]
    assert entry["status"] == "could-not-execute"
    assert entry["lease"]["status"] == "held"
    assert entry["lease"]["holder"]["issue"] == 77
    assert "infiquetra/other-repo#77" in entry["lease"]["detail"]
    assert "Waiting on the shared environment" in capsys.readouterr().out


def test_a_waiting_run_polls_and_says_what_it_waits_on(tmp_path: Path) -> None:
    backend = FakeLeaseBackend()
    backend.hold("shared-nonprod", _other_holder())
    record = run_record.from_dict(_combined_record(), warn=None)
    elapsed = [0.0]
    sleeps: list[float] = []
    reports: list[str] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        elapsed[0] += seconds
    entry, green = build_loop.run_combined_pass(
        record,
        _SHARED,
        [],
        "c" * 40,
        runner=FakeRunner(),
        lease_backend=backend,
        lease_wait=90,
        clock=lambda: elapsed[0],
        sleep=sleep,
        report=reports.append,
        host="builder-1",
    )
    assert green is False
    assert sleeps == [30.0, 30.0, 30.0]
    assert len(reports) == 4
    assert all("infiquetra/other-repo#77" in line and "builder-2" in line for line in reports)
    assert entry["lease"]["waited_seconds"] == 90


def test_a_released_lease_admits_the_next_run(tmp_path: Path) -> None:
    """Run A holds, passes and releases; run B on the same remote then deploys."""
    backend = FakeLeaseBackend()
    first = _write(tmp_path / "issue-1027.json", _combined_record(issue=1027))
    second = _write(tmp_path / "issue-2000.json", _combined_record(issue=2000))
    order: list[str] = []

    def deploy_while_held(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        # While run A deploys, run B is refused.
        blocked = FakeRunner()
        assert _combined(second, blocked, backend) == build_loop.EXIT_NOT_GREEN
        assert "deploy-stack --env nonprod" not in _commands(blocked)
        order.append("A deployed")
        return 0, ""

    assert _combined(first, FakeRunner(verdicts={"deploy-stack": deploy_while_held}), backend) == 0
    runner_b = FakeRunner()
    assert _combined(second, runner_b, backend) == build_loop.EXIT_GREEN
    assert "deploy-stack --env nonprod" in _commands(runner_b)
    assert order == ["A deployed"]
    passes_b = _combined_block(second)["passes"]
    assert [entry["lease"]["status"] for entry in passes_b] == ["held", "acquired"]


def test_the_lease_is_released_on_every_exit_path(tmp_path: Path) -> None:
    for verdicts in ({"run-functional": 1}, {"deploy-stack": 1}, {"teardown-stack": 1}):
        path = _write(tmp_path / "issue-1027.json", _combined_record())
        backend = FakeLeaseBackend()
        _combined(path, FakeRunner(verdicts=verdicts), backend)
        assert backend.refs == {}, verdicts
        assert backend.calls[-1] == ("release", "shared-nonprod"), verdicts


def test_a_private_environment_never_takes_a_lease(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record(_PRIVATE))
    backend = FakeLeaseBackend()
    assert _combined(path, FakeRunner(), backend) == build_loop.EXIT_GREEN
    assert backend.calls == []
    lease = _combined_block(path)["passes"][-1]["lease"]
    assert lease == {"required": False, "status": "not-required"}


def _record_after_an_interrupted_pass() -> dict[str, Any]:
    payload = _combined_record()
    payload["combined_branch"] = {
        "environment": dict(_SHARED),
        "passes": [
            {
                "pass": 1,
                "status": "could-not-execute",
                "interrupted": True,
                "environment_problems": ["the pass was interrupted: KeyboardInterrupt"],
            }
        ],
    }
    return payload


def test_a_lease_left_by_an_interrupted_invocation_of_this_run_waits_for_the_operator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issues #139 and #140: no same-run take-over, even on this host with a lower pass number.

    The earlier invocation's lease is held until the operator releases it with the exact command.
    """
    backend = FakeLeaseBackend()
    left = _other_holder(
        repo="infiquetra/infiquetra-claude-plugins",
        issue=1027,
        host=environment_lease.host_label(),
        pass_number=1,
        invocation="deadbeefdeadbeef",
        started_at="2026-10-01T00:00:00Z",
        bound_seconds=600,
    )
    token = backend.hold("shared-nonprod", left)
    path = _write(tmp_path / "issue-1027.json", _record_after_an_interrupted_pass())
    runner = FakeRunner()
    assert _combined(path, runner, backend) == build_loop.EXIT_NOT_GREEN
    assert "deploy-stack --env nonprod" not in _commands(runner)
    assert backend.refs["shared-nonprod"] == (token, left)
    lease = _combined_block(path)["passes"][-1]["lease"]
    assert lease["status"] == "held"
    assert lease["holder"]["invocation"] == "deadbeefdeadbeef"
    assert lease["invocation"] and lease["invocation"] != "deadbeefdeadbeef"
    assert f"release --name shared-nonprod --expect {token}" in lease["detail"]
    assert "STALE" in capsys.readouterr().out


def test_a_second_invocation_of_the_same_run_waits_on_a_lease_still_deploying(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Acceptance criterion 1 of #139/#140, through the real command line on one record.

    While invocation A deploys, invocation B of the same run waits and gives up, landing a
    could-not-execute pass. That moves the record's pass count past A's, which is exactly what let
    invocation C take A's lease before; C waits too. Only A ever deploys. The lease is the real
    git backend against a bare repository under ``tmp_path``, so the backend's own rule is what
    is tested; nothing touches a real remote.
    """
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    remote, clone = tmp_path / "remote.git", tmp_path / "host"
    for argv in (
        ["init", "-q", "--bare", str(remote)],
        ["init", "-q", str(clone)],
        ["-C", str(clone), "remote", "add", "origin", str(remote)],
    ):
        subprocess.run(["git", *argv], check=True, capture_output=True)
    backend = environment_lease.GitRefLeaseBackend(clone)
    deploys: list[str] = []
    waits: list[float] = []

    def short_sleep(seconds: float) -> None:
        waits.append(seconds)
        time.sleep(min(seconds, 0.05))

    def deploy_a(argv: Sequence[str], timeout: int) -> tuple[int, str]:
        deploys.append("A")
        holder_a = backend.read("shared-nonprod").token
        for name in ("B", "C"):
            runner = FakeRunner()
            code = build_loop.main(
                ["--record", str(path), "--combined", "--lease-wait", "1"],
                runner=runner,
                lease_backend=backend,
                sleep=short_sleep,
            )
            assert code == build_loop.EXIT_NOT_GREEN, name
            assert "deploy-stack --env nonprod" not in _commands(runner), name
            assert backend.read("shared-nonprod").token == holder_a, name
        return 0, ""

    runner_a = FakeRunner(verdicts={"deploy-stack": deploy_a})
    assert _combined(path, runner_a, backend) == build_loop.EXIT_GREEN
    assert deploys == ["A"]
    assert waits, "the waiting invocations slept between polls"
    assert "Waiting on the shared environment" in capsys.readouterr().out
    passes = _combined_block(path)["passes"]
    assert [entry["lease"]["status"] for entry in passes] == ["held", "held", "acquired"]
    assert [entry["pass"] for entry in passes] == [1, 2, 3]
    invocations = {entry["lease"]["invocation"] for entry in passes}
    assert len(invocations) == 3, "each invocation carries its own nonce"
    a_invocation = passes[-1]["lease"]["invocation"]
    assert all(entry["lease"]["holder"]["invocation"] == a_invocation for entry in passes)
    assert not backend.read("shared-nonprod").held


def test_a_waiting_invocation_that_wins_the_lease_takes_a_fresh_pass_number(
    tmp_path: Path,
) -> None:
    """Acceptance criterion 3: the number is read when the lease is won, not before the wait."""
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    backend = FakeLeaseBackend()
    backend.hold("shared-nonprod", _other_holder())
    pushed: list[Any] = []
    original = backend.acquire

    def acquire(name: str, holder: Any) -> Any:
        pushed.append(holder)
        return original(name, holder)

    backend.acquire = acquire  # type: ignore[method-assign]

    def sleep(_: float) -> None:
        # While this invocation waits, two other passes of the run land and the holder leaves.
        with run_record.file_lock(path):
            raw = json.loads(path.read_text(encoding="utf-8"))
            block = raw.setdefault("combined_branch", {"environment": dict(_SHARED)})
            block.setdefault("passes", []).extend(
                [{"pass": 1, "status": "fail"}, {"pass": 2, "status": "fail"}]
            )
            path.write_text(json.dumps(raw), encoding="utf-8")
        backend.refs.clear()

    code = build_loop.main(
        ["--record", str(path), "--combined", "--lease-wait", "60"],
        runner=FakeRunner(),
        lease_backend=backend,
        sleep=sleep,
    )
    assert code == build_loop.EXIT_GREEN
    assert [holder.pass_number for holder in pushed] == [1, 3]
    landed = _combined_block(path)["passes"][-1]
    assert landed["pass"] == 3
    assert landed["lease"]["holder"]["pass_number"] == 3


def test_a_pass_records_the_lease_at_the_time_it_was_won_with_its_fresh_pass_number() -> None:
    """Acceptance criteria 2 and 3 on the pass's own lease block, with the clocks injected."""
    start = datetime(2026, 10, 4, tzinfo=UTC)
    elapsed = [0.0]
    backend = FakeLeaseBackend()
    backend.hold("shared-nonprod", _other_holder())
    numbers = iter([1, 1, 4])

    def sleep(seconds: float) -> None:
        elapsed[0] += seconds
        if elapsed[0] >= 60:
            backend.refs.clear()

    def wall_now() -> datetime:
        return start + timedelta(seconds=elapsed[0])

    entry, green = build_loop.run_combined_pass(
        run_record.from_dict(_combined_record(), warn=None),
        _SHARED,
        [],
        "c" * 40,
        runner=FakeRunner(),
        lease_backend=backend,
        pass_number=1,
        next_pass=lambda: next(numbers),
        lease_wait=1800,
        clock=lambda: elapsed[0],
        wall_now=wall_now,
        sleep=sleep,
        report=lambda _: None,
        host="builder-1",
        invocation="feedfacefeedface",
    )
    assert green is True
    holder = entry["lease"]["holder"]
    assert holder["started_at"] == environment_lease.iso_utc(start + timedelta(seconds=60))
    assert holder["started_at"] != environment_lease.iso_utc(start)
    assert not environment_lease.is_stale(environment_lease.LeaseHolder(**holder), wall_now())
    assert holder["pass_number"] == 4 and entry["pass"] == 4
    assert holder["invocation"] == entry["lease"]["invocation"] == "feedfacefeedface"


def test_a_lease_won_after_waiting_is_stamped_when_taken_and_is_not_stale() -> None:
    """The wait is not counted as time held: the pushed start time is the moment of the win."""
    start = datetime(2026, 10, 4, tzinfo=UTC)
    elapsed = [0.0]
    backend = FakeLeaseBackend()
    backend.hold("shared-nonprod", _other_holder())
    pushed: list[Any] = []
    original = backend.acquire

    def acquire(name: str, holder: Any) -> Any:
        pushed.append(holder)
        if elapsed[0] >= 1470:
            backend.refs.pop(name, None)
        return original(name, holder)

    backend.acquire = acquire  # type: ignore[method-assign]

    def sleep(seconds: float) -> None:
        elapsed[0] += seconds

    def wall_now() -> datetime:
        return start + timedelta(seconds=elapsed[0])

    ours = environment_lease.LeaseHolder(
        repo="infiquetra/example",
        issue=1,
        revision="c" * 40,
        host="builder-1",
        started_at=environment_lease.iso_utc(start),
        bound_seconds=600,
        pass_number=1,
        invocation="feedfacefeedface",
    )
    result, waited = build_loop.acquire_lease(
        backend,
        "shared-nonprod",
        ours,
        lease_wait=1800,
        remote="origin",
        repo_root=Path("."),
        clock=lambda: elapsed[0],
        sleep=sleep,
        wall_now=wall_now,
        report=lambda _: None,
    )
    assert result.status == environment_lease.ACQUIRED
    assert waited >= 1470
    won = result.holder
    assert won.started_at == environment_lease.iso_utc(wall_now())
    assert won.started_at == pushed[-1].started_at
    assert not environment_lease.is_stale(won, wall_now())
    state = backend.read("shared-nonprod")
    assert "STALE" not in environment_lease.describe(state, wall_now())


def test_a_stale_holder_is_reported_with_the_release_command_and_is_never_released(
    tmp_path: Path,
) -> None:
    backend = FakeLeaseBackend()
    token = backend.hold(
        "shared-nonprod",
        _other_holder(started_at="2026-10-01T00:00:00Z", bound_seconds=600),
    )
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), backend) == build_loop.EXIT_NOT_GREEN
    detail = _combined_block(path)["passes"][-1]["lease"]["detail"]
    assert "STALE" in detail
    assert f"environment_lease.py --repo-root" in detail
    assert f"release --name shared-nonprod --expect {token}" in detail
    assert backend.refs["shared-nonprod"][0] == token


def test_a_multi_lane_run_with_an_unmerged_unit_is_refused_by_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        {"name": "U1", "branch": "issue/1-u1", "merge_state": "merged", "merged_tip": "d" * 40},
        {"name": "U2", "branch": "issue/1-u2", "merge_state": "ready"},
    ]
    path = _write(tmp_path / "issue-1027.json", _combined_record(units=units))
    runner = FakeRunner()
    assert _combined(path, runner, FakeLeaseBackend()) == build_loop.EXIT_REFUSED
    assert "still to merge: U2" in capsys.readouterr().err
    assert _commands(runner) == []


def test_a_revision_missing_a_recorded_merge_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        {"name": "U1", "branch": "issue/1-u1", "merge_state": "merged", "merged_tip": "d" * 40},
        {"name": "U2", "branch": "issue/1-u2", "merge_state": "merged", "merged_tip": "e" * 40},
    ]
    path = _write(tmp_path / "issue-1027.json", _combined_record(units=units))
    runner = FakeRunner(verdicts={"merge-base --is-ancestor " + "e" * 40: 1})
    assert _combined(path, runner, FakeLeaseBackend()) == build_loop.EXIT_REFUSED
    assert "does not contain unit U2's merge" in capsys.readouterr().err

    merged = FakeRunner()
    assert _combined(path, merged, FakeLeaseBackend()) == build_loop.EXIT_GREEN


def test_a_one_unit_run_runs_the_pass_on_its_own_branch(tmp_path: Path) -> None:
    units = [{"name": "U1", "branch": "issue/1-u1", "merge_state": "ready"}]
    path = _write(tmp_path / "issue-1027.json", _combined_record(units=units))
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == build_loop.EXIT_GREEN


def test_a_waived_repository_runs_the_baseline_only_and_records_the_waiver(
    tmp_path: Path,
) -> None:
    waiver = {"mode": "waived", "level": "repository", "reason": "docs only", "source": "profile"}
    path = _write(tmp_path / "issue-1027.json", _combined_record(waiver))
    runner, backend = FakeRunner(), FakeLeaseBackend()
    assert _combined(path, runner, backend) == build_loop.EXIT_GREEN
    assert _commands(runner) == ["uv run ruff check ."]
    assert backend.calls == []
    block = _combined_block(path)
    assert block["passes"][-1]["waiver"] == {"level": "repository", "reason": "docs only"}
    assert block["handed_to_code_review"]["waived"] is True


def test_no_declaration_and_no_waiver_is_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = tmp_path / "repo"
    empty.mkdir()
    path = _write(tmp_path / "issue-1027.json", _combined_record(None))
    runner = FakeRunner()
    assert _combined(path, runner, FakeLeaseBackend(), repo_root=empty) == build_loop.EXIT_REFUSED
    assert "no functional-test environment and no waiver" in capsys.readouterr().err
    assert runner.calls == []


def test_a_declaration_that_names_production_is_refused_before_anything_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    environment = {**_SHARED, "deploy_command": "deploy-stack --env production"}
    path = _write(tmp_path / "issue-1027.json", _combined_record(environment))
    runner = FakeRunner()
    assert _combined(path, runner, FakeLeaseBackend()) == build_loop.EXIT_REFUSED
    assert "names production" in capsys.readouterr().err
    assert runner.calls == []


@pytest.mark.parametrize(
    ("command", "trips"),
    [
        ("deploy --env prod", True),
        ("./deploy-prod.sh", True),
        ("deploy --env=PRODUCTION", True),
        ("deploy --env nonprod", False),
        ("deploy --env non-prod", False),
        ("deploy --env pre-prod", False),
        ("deploy --env preprod", False),
        ("make product-demo", False),
    ],
)
def test_the_production_tripwire_reads_words_not_substrings(command: str, trips: bool) -> None:
    environment = {**_PRIVATE, "deploy_command": command}
    assert (build_loop.production_tripwire(environment) is not None) is trips


def test_environment_bound_plan_checks_run_once_after_the_test_command(tmp_path: Path) -> None:
    smoke = [{"name": "smoke", "command": "smoke-run", "runs": "environment"}]
    units = [
        {
            "id": "U1",
            "functional_checks": [
                {"name": "local", "command": "local-check", "runs": "local"},
                {"name": "api", "command": "api-check", "runs": "environment"},
            ],
            "scenario_smoke": smoke,
        },
        {"id": "U2", "scenario_smoke": smoke},
    ]
    path = _write(tmp_path / "issue-1027.json", _combined_record(_PRIVATE, units=units))
    runner = FakeRunner(verdicts={"smoke-run": 1})
    assert _combined(path, runner, FakeLeaseBackend()) == build_loop.EXIT_NOT_GREEN
    assert _commands(runner) == [
        "uv run ruff check .",
        "deploy-stack",
        "run-functional",
        "api-check",
        "smoke-run",
        "teardown-stack",
    ]
    entry = _combined_block(path)["passes"][-1]
    assert [result["status"] for result in entry["environment_checks"]] == ["pass", "fail"]
    assert entry["status"] == "fail"


def test_a_red_baseline_deploys_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner, backend = FakeRunner(verdicts={"ruff": 1}), FakeLeaseBackend()
    assert _combined(path, runner, backend) == build_loop.EXIT_NOT_GREEN
    assert _commands(runner) == ["uv run ruff check ."]
    assert backend.calls == []
    entry = _combined_block(path)["passes"][-1]
    assert entry["status"] == "fail" and entry["deploy"] is None
    assert "baseline is not green" in entry["skipped_reason"]


def test_a_shared_lease_on_a_remote_the_checkout_lacks_is_a_refusal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The card's stop condition: no lease location every deploying host can see, no pass."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    runner = FakeRunner()
    assert _combined(path, runner, None, repo_root=repo) == build_loop.EXIT_REFUSED
    assert "is not configured" in capsys.readouterr().err
    assert _commands(runner) == []


def test_the_combined_dry_run_prints_the_environment_lease_and_integration(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        {"name": "U1", "branch": "issue/1-u1", "merge_state": "merged", "merged_tip": "d" * 40},
        {"name": "U2", "branch": "issue/1-u2", "merge_state": "ready"},
    ]
    path = _write(tmp_path / "issue-1027.json", _combined_record(units=units))
    before = path.read_text(encoding="utf-8")
    runner = FakeRunner()
    assert _combined(path, runner, None, "--dry-run") == build_loop.EXIT_GREEN
    out = capsys.readouterr().out
    assert "kind: shared-nonprod (scope: shared)" in out
    assert "Lease: refs/saga/leases/shared-nonprod on remote origin" in out
    assert "still to merge: U2" in out
    assert runner.calls == []
    assert path.read_text(encoding="utf-8") == before


def test_unit_and_combined_are_alternatives(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    with pytest.raises(SystemExit):
        build_loop.main(["--record", str(path), "--unit", "U1", "--combined"])


def test_loading_a_record_with_a_combined_block_warns_about_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == build_loop.EXIT_GREEN
    capsys.readouterr()
    build_loop.load_record_file(path)
    assert "unknown top-level field" not in capsys.readouterr().err


# ---------------------------------------------------------------------------
# The evidence code review reads (the parent's second criterion).
# ---------------------------------------------------------------------------


def test_a_run_cannot_reach_code_review_without_a_passing_combined_run_at_that_revision(
    tmp_path: Path,
) -> None:
    """Issue #91's criterion: a green unit loop alone admits nothing; the combined pass does."""
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert build_loop.main(["--record", str(path), "--unit", "U1"], runner=FakeRunner()) == 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["units"][0]["build_loop"]["handed_to_code_review"]
    evidence = build_loop.functional_evidence(raw, "a" * 40)
    assert evidence["admits"] is False and evidence["status"] == "missing"

    assert _combined(path, FakeRunner(verdicts={"run-functional": 1}), FakeLeaseBackend()) == 4
    failed = build_loop.functional_evidence(build_loop.load_record_file(path), "a" * 40)
    assert failed["admits"] is False and failed["status"] == "failed"
    assert failed["test"] == "fail"

    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    for record in (json.loads(path.read_text(encoding="utf-8")), build_loop.load_record_file(path)):
        passed = build_loop.functional_evidence(record, "a" * 40)
        assert passed["admits"] is True and passed["status"] == "passed"
        assert passed["environment"] == {"kind": "shared-nonprod", "scope": "shared"}
        assert (passed["deploy"], passed["test"], passed["teardown"]) == ("pass", "pass", "pass")
        stale = build_loop.functional_evidence(record, "f" * 40)
        assert stale["admits"] is False and stale["status"] == "missing"


def test_a_waived_combined_pass_is_admitted_as_waived(tmp_path: Path) -> None:
    waiver = {"mode": "waived", "level": "repository", "reason": "docs only", "source": "profile"}
    path = _write(tmp_path / "issue-1027.json", _combined_record(waiver))
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    evidence = build_loop.functional_evidence(build_loop.load_record_file(path), "a" * 40)
    assert evidence["admits"] is True
    assert evidence["status"] == "waived" and evidence["waiver_reason"] == "docs only"


# ---------------------------------------------------------------------------
# The review gate: `--handoff` (issue #100, pre-review testing U5).
# ---------------------------------------------------------------------------


def _gate(
    path: Path, capsys: pytest.CaptureFixture[str], *extra: str, runner: FakeRunner | None = None
) -> tuple[int, str, str]:
    capsys.readouterr()
    code: int = build_loop.main(
        ["--record", str(path), "--handoff", *extra], runner=runner or FakeRunner()
    )
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_with_no_combined_run_and_no_waiver_work_does_not_hand_the_revision_to_review(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #100's first criterion: the gate prints no revision, so `/work` §5.1 has none."""
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    before = path.read_bytes()
    code, out, err = _gate(path, capsys)
    assert code == build_loop.EXIT_REFUSED
    assert out == ""
    assert err.startswith("build_loop: no passing combined-branch functional run and no waiver")
    assert "a" * 40 in err
    assert len(err.strip().splitlines()) == 1
    assert path.read_bytes() == before, "the gate writes nothing"


def test_a_failing_or_unexecutable_latest_pass_does_not_hand_off(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(verdicts={"run-functional": 1}), FakeLeaseBackend()) == 4
    code, out, err = _gate(path, capsys)
    assert code == build_loop.EXIT_REFUSED and out == ""
    assert f"the latest combined pass at {'a' * 40} is fail" in err

    assert _combined(path, FakeRunner(verdicts={"deploy-stack": 1}), FakeLeaseBackend()) == 4
    code, out, err = _gate(path, capsys)
    assert code == build_loop.EXIT_REFUSED and out == ""
    assert "is could-not-execute" in err


def test_a_later_failing_pass_at_the_same_revision_withdraws_the_green_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    assert _combined(path, FakeRunner(verdicts={"run-functional": 1}), FakeLeaseBackend()) == 4
    code, out, _ = _gate(path, capsys)
    assert code == build_loop.EXIT_REFUSED and out == ""


def test_a_green_pass_at_head_hands_off_its_full_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    code, out, err = _gate(path, capsys)
    assert code == build_loop.EXIT_GREEN, err
    admitted = json.loads(out)
    assert admitted["revision"] == "a" * 40
    assert admitted["pass"] == 1 and admitted["status"] == "passed"
    assert admitted["waived"] is False and admitted["waiver_reason"] is None
    assert admitted["environment"] == {"kind": "shared-nonprod", "scope": "shared"}
    assert (admitted["deploy"], admitted["test"], admitted["teardown"]) == ("pass",) * 3


def test_head_moved_since_the_green_pass_is_refused_naming_the_commit_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    moved = FakeRunner(
        verdicts={"rev-parse": lambda *_: (0, "c" * 40), "rev-list": lambda *_: (0, "2")}
    )
    code, out, err = _gate(path, capsys, runner=moved)
    assert code == build_loop.EXIT_REFUSED and out == ""
    assert f"HEAD moved 2 commits since the green pass at {'a' * 40}" in err
    assert "run the combined-branch loop again" in err
    assert ["git", "-C", str(Path.cwd()), "rev-list", f"{'a' * 40}..{'c' * 40}", "--count"] in (
        moved.calls
    )


def test_a_waived_pass_hands_off_with_its_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    waiver = {"mode": "waived", "level": "repository", "reason": "docs only", "source": "profile"}
    path = _write(tmp_path / "issue-1027.json", _combined_record(waiver))
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    code, out, err = _gate(path, capsys)
    assert code == build_loop.EXIT_GREEN, err
    admitted = json.loads(out)
    assert admitted["waived"] is True and admitted["status"] == "waived"
    assert admitted["waiver_reason"] == "docs only"


def test_handoff_revision_checks_the_named_revision_instead_of_head(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    never_head = FakeRunner(verdicts={"rev-parse": lambda *_: (0, "c" * 40)})
    code, out, _ = _gate(path, capsys, "--revision", "a" * 40, runner=never_head)
    assert code == build_loop.EXIT_GREEN
    assert json.loads(out)["revision"] == "a" * 40
    assert not any("rev-parse" in call for call in never_head.calls)

    code, out, err = _gate(path, capsys, "--revision", "f" * 40)
    assert code == build_loop.EXIT_REFUSED and out == ""
    assert f"no passing combined-branch functional run and no waiver at {'f' * 40}" in err

    code, _, err = _gate(path, capsys, "--revision", "HEAD")
    assert code == build_loop.EXIT_REFUSED
    assert "not a full forty-character commit identifier" in err


def test_revision_without_handoff_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert build_loop.main(["--record", str(path), "--revision", "a" * 40, "--dry-run"]) == 2
    assert "--revision belongs to --handoff" in capsys.readouterr().err


def test_handoff_is_an_alternative_to_unit_and_combined(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    for other in (["--unit", "U1"], ["--combined"]):
        with pytest.raises(SystemExit):
            build_loop.main(["--record", str(path), "--handoff", *other])


def test_a_declared_shared_environment_with_only_unit_green_cannot_obtain_a_handoff(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Parent #91's second criterion, at the command `/work` §5.1 runs."""
    units = [{"id": "U1"}, {"id": "U2"}]
    path = _write(tmp_path / "issue-1027.json", _combined_record(units=units))
    for unit in ("U1", "U2"):
        assert build_loop.main(["--record", str(path), "--unit", unit], runner=FakeRunner()) == 0
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert all(row["build_loop"]["handed_to_code_review"] for row in raw["units"])
    code, out, _ = _gate(path, capsys)
    assert code == build_loop.EXIT_REFUSED and out == ""


def test_the_work_skill_takes_the_reviewed_revision_only_from_the_handoff_gate() -> None:
    text = WORK_SKILL.read_text(encoding="utf-8")
    section = text[text.index("### 5.1 ") : text.index("### 5.2 ")]
    assert "build_loop.py" in section and "--handoff" in section
    assert 'units"][0]' not in section and "units[0]" not in section
    collapsed = " ".join(section.split()).lower()
    assert "review does not start without a passing combined-branch functional run" in collapsed
    assert "--review-gate-override" in collapsed and "does not apply to this gate" in collapsed


def test_the_code_review_skill_reads_the_functional_evidence_and_stops_without_it() -> None:
    text = CODE_REVIEW_SKILL.read_text(encoding="utf-8")
    assert "show --issue" not in text
    phase_0 = text[text.index("## Phase 0") : text.index("## Phase 1")]
    assert "--handoff" in phase_0 and '--revision "$REVIEWED_SHA"' in phase_0
    collapsed = " ".join(phase_0.split())
    assert "no passing combined-branch functional run and no waiver" in collapsed
    assert "stop" in collapsed.lower()


# ---------------------------------------------------------------------------
# The combined-branch drift guards.
# ---------------------------------------------------------------------------


def test_the_combined_block_key_set_matches_the_reference_document(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    documented = set(_marked_table(REFERENCE.read_text(encoding="utf-8"), "COMBINED-BRANCH BLOCK"))
    assert set(_combined_block(path)) == documented


def test_the_combined_pass_key_set_matches_the_reference_document(tmp_path: Path) -> None:
    path = _write(tmp_path / "issue-1027.json", _combined_record())
    assert _combined(path, FakeRunner(), FakeLeaseBackend()) == 0
    documented = set(_marked_table(REFERENCE.read_text(encoding="utf-8"), "COMBINED PASS KEYS"))
    written = set(_combined_block(path)["passes"][0])
    # `waiver`, `skipped_reason` and `interrupted` are conditional and documented in prose.
    assert written - {"waiver", "skipped_reason", "interrupted"} == documented


def test_the_combined_key_is_named_in_the_run_record_reference() -> None:
    text = RUN_RECORD_REFERENCE.read_text(encoding="utf-8")
    assert build_loop.COMBINED_KEY in text
    top_level = text.split("<!-- BEGIN TOP-LEVEL KEYS -->")[1].split("<!-- END TOP-LEVEL KEYS -->")[0]
    assert build_loop.COMBINED_KEY not in top_level, "it is an extension key, not a v1 key"


def test_the_lease_block_is_named_in_the_profile_reference() -> None:
    text = PROFILE_REFERENCE.read_text(encoding="utf-8")
    assert '"lease"' in text and "refs/saga/leases/" in text


def test_the_work_skill_integrates_then_runs_the_combined_pass_before_review() -> None:
    """Acceptance criterion 3: after integration, before review, and exit 5 named."""
    text = WORK_SKILL.read_text(encoding="utf-8")
    phase_3 = text.index("## Phase 3")
    merge = text.index("merge_turn.py", phase_3)
    combined = text.index("--combined", phase_3)
    review = text.index("### 5.1 ")
    assert phase_3 < merge < combined < review
    collapsed = " ".join(text.split())
    assert "5 — environment stop" in collapsed
    assert "single-lane run" in collapsed
