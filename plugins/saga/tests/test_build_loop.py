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

import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Sequence
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
        "ruff",
        "ruff",
        "mypy",
        "pytest-coverage",
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
    assert "answers: ruff" in out
    assert "branch preview: none declared" in out
    assert "none prescribed in the run record" in out


def test_the_dry_run_names_every_uncovered_catalogue_check_and_unconfigured_scanner(
    record_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The gap is visible in the loop's own output rather than silently absent."""
    assert build_loop.main(["--record", str(record_file), "--dry-run"], runner=FakeRunner()) == 0
    out = capsys.readouterr().out
    for uncovered in ("mypy", "bandit", "pytest-coverage"):
        assert uncovered in out
    for scanner in build_loop.NAMED_SCANNERS:
        assert scanner in out


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
