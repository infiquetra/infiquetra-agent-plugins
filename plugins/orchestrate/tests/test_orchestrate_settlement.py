"""Evidence-based settlement: settle records done only with branch evidence, never from pane state alone.

Three observed incidents across Team Mimir sessions drove this contract:
1. Stale `done`: Herdr reported `done` predating a supplemental prompt, but the branch had no
   commits. Settle must leave the unit running instead of falsely calling it done.
2. Idle-but-stuck: A unit with a SIGTTIN-suspended background child reported `done` repeatedly while
   stuck. Settle must never mark an idle unit done without commits on its branch.
3. Closed-session-after-commit vs gone-without-commits: When operator cleanup closed a worker session
   after its commits were authored, settle previously called it failed. Settle must mark a closed
   session with commits `done`, while a closed session with no commits produces the distinct
   `orphaned` state.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import orchestrate_support as _support
import pytest

# --- issue #1025: every stateful subcommand takes --issue and --store-root -----------------------

TEST_ISSUE = 1


_STORE: Path | None = None


@pytest.fixture(autouse=True)
def _pin_the_record_store(tmp_path: Path) -> Iterator[None]:
    """Pin this test's record store to its own ``tmp_path``.

    Never the resolved store -- that is the developer's own ``.claude/saga/runs`` -- and never
    derived from the working directory either: a helper called before a test changes directory
    would then write one store and read another.
    """
    global _STORE
    _STORE = tmp_path / "orch-test-store"
    _STORE.mkdir(parents=True, exist_ok=True)
    yield
    _STORE = None


def test_store() -> Path:
    """This test's record store."""
    assert _STORE is not None, "the record store is pinned by an autouse fixture"
    return _STORE


def NS(**fields: object) -> argparse.Namespace:
    """A command Namespace carrying this test's issue and store."""
    # `merge` and `clean` carry optional flags the parser defaults; a Namespace built by
    # hand has to default them too, or the command reads an attribute that is not there.
    defaults = {"remote": "origin", "compare": "main"}
    return argparse.Namespace(
        issue=TEST_ISSUE,
        store_root=str(test_store()),
        **{**defaults, **fields},
    )


SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)


@pytest.fixture(scope="module")
def orchestrate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_orchestrate_settlement", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name + "\n")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", f"add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo with a base commit, run branch, and multiple unit branches."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "branch", "orch/r1")

    # Committed units (have branch completion evidence)
    for unit in ("committed-alpha", "committed-beta"):
        _git(r, "checkout", "-b", f"orch/r1-{unit}", "orch/r1")
        _commit(r, f"{unit}.txt")
        _git(r, "checkout", "main")

    # Uncommitted units (sitting at base, zero commits)
    for unit in ("empty-stale", "empty-stuck", "empty-gone"):
        _git(r, "branch", f"orch/r1-{unit}", "orch/r1")

    return r


def _write_run(repo: Path, units: list[dict[str, Any]] | None = None, **overrides: Any) -> None:
    """Write this test's run into the per-issue run record (issue #1025).

    There is no `.orchestrate/run.json` any more. The store is derived from the repository rather
    than resolved, because the resolved store is the developer's own `.claude/saga/runs`.
    """
    _support.ensure_origin(repo)
    base = subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", "rev-parse", "HEAD"], cwd=repo, check=False, capture_output=True, text=True
    ).stdout.strip()
    block: dict[str, Any] = {"run_id": "r1", "source": "a test", "base": base, "branch": "orch/r1"}
    block.update(overrides)
    _support.write_record(
        test_store(),
        TEST_ISSUE,
        units=[_support.fill_unit_row(u) for u in (units or [])],
        **block,
    )


def _read_units(repo: Path) -> dict[str, dict[str, Any]]:
    raw = _support.read_record(test_store(), _support.TEST_ISSUE)
    units: list[dict[str, Any]] = raw["units"]
    return {u["name"]: u for u in units}


def _unit(name: str, **over: Any) -> dict[str, Any]:
    return {
        "name": name,
        "vendor": "claude",
        "task": "do work",
        "branch": f"orch/r1-{name}",
        "status": "running",
        **over,
    }


def _agent(name: str, status: str) -> dict[str, str]:
    return {"name": name, "agent_status": status}


class FakeHerdr:
    def __init__(self, readings: list[list[dict[str, str]]]) -> None:
        self.readings = list(readings)
        self.calls = 0

    def __call__(self) -> list[dict[str, str]]:
        self.calls += 1
        assert self.readings, f"herdr polled {self.calls} times but no more readings configured"
        return self.readings.pop(0)


def _patch_settle(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    readings: list[list[dict[str, str]]],
) -> tuple[FakeHerdr, list[float]]:
    fake = FakeHerdr(readings)
    monkeypatch.setattr(orchestrate, "live_agents", fake)
    slept: list[float] = []
    monkeypatch.setattr(orchestrate.time, "sleep", slept.append)
    return fake, slept


class TestIncidentShape1StaleDoneWithoutCommits:
    """Incident 1: A stale done reading predating a prompt must not settle done without commits."""

    def test_stale_done_with_no_commits_stays_running(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("empty-stale")])
        _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("empty-stale", "done")], [_agent("empty-stale", "done")]],
        )
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["empty-stale"]
        assert saved["status"] == "running"
        out = capsys.readouterr().out
        assert "empty-stale" in out
        assert "still moving (no commits)" in out

    def test_idle_pane_with_no_commits_stays_running(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("empty-stale")])
        _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("empty-stale", "idle")], [_agent("empty-stale", "idle")]],
        )
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["empty-stale"]
        assert saved["status"] == "running"
        out = capsys.readouterr().out
        assert "still moving (no commits)" in out


class TestIncidentShape2IdleStuckWithoutCommits:
    """Incident 2: A stuck session reporting idle/done (e.g. SIGTTIN suspended child) stays running."""

    def test_stuck_unit_reporting_done_six_times_never_settles_without_evidence(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(repo, [_unit("empty-stuck")])
        monkeypatch.chdir(repo)

        # 3 consecutive settle passes (each with 2 confirming readings = 6 readings total)
        for _ in range(3):
            _patch_settle(
                orchestrate,
                monkeypatch,
                [[_agent("empty-stuck", "done")], [_agent("empty-stuck", "done")]],
            )
            assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
            saved = _read_units(repo)["empty-stuck"]
            assert saved["status"] == "running"


class TestIncidentShape3SessionGoneOutcomes:
    """Incident 3: Session gone with commits settles done; session gone without commits is orphaned."""

    def test_session_closed_after_commit_settles_done_never_failed(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Committed work whose Herdr session was closed settles done, not failed."""
        _write_run(repo, [_unit("committed-alpha")])
        _patch_settle(orchestrate, monkeypatch, [[], []])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["committed-alpha"]
        assert saved["status"] == "done"
        out = capsys.readouterr().out
        assert "committed-alpha: session gone with commits -> done" in out

    def test_session_gone_without_commits_yields_distinct_orphaned_state(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A session that disappeared without commits is marked orphaned with a distinct note."""
        _write_run(repo, [_unit("empty-gone")])
        _patch_settle(orchestrate, monkeypatch, [[], []])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["empty-gone"]
        assert saved["status"] == "orphaned"
        assert saved["status"] == orchestrate.ORPHANED
        assert saved["status"] != orchestrate.FAILED
        assert saved["status"] != orchestrate.DONE
        assert "session disappeared without commits" in saved["note"]
        out = capsys.readouterr().out
        assert "empty-gone: session gone -> orphaned" in out


class TestSettlementUnderOnceFlag:
    """Settlement under --once still requires branch evidence."""

    def test_once_settles_committed_idle_unit_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(repo, [_unit("committed-alpha")])
        _patch_settle(orchestrate, monkeypatch, [[_agent("committed-alpha", "idle")]])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=True)) == 0
        saved = _read_units(repo)["committed-alpha"]
        assert saved["status"] == "done"

    def test_once_leaves_uncommitted_idle_unit_running(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(repo, [_unit("empty-stale")])
        _patch_settle(orchestrate, monkeypatch, [[_agent("empty-stale", "idle")]])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=True)) == 0
        saved = _read_units(repo)["empty-stale"]
        assert saved["status"] == "running"

    def test_once_settles_committed_gone_unit_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(repo, [_unit("committed-alpha")])
        _patch_settle(orchestrate, monkeypatch, [[]])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=True)) == 0
        saved = _read_units(repo)["committed-alpha"]
        assert saved["status"] == "done"

    def test_once_settles_uncommitted_gone_unit_orphaned(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(repo, [_unit("empty-gone")])
        _patch_settle(orchestrate, monkeypatch, [[]])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=True)) == 0
        saved = _read_units(repo)["empty-gone"]
        assert saved["status"] == "orphaned"


class TestLandedWorkSettlement:
    """A unit whose commits were already merged onto the run branch counts as produced work."""

    def test_session_gone_for_already_landed_unit_settles_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Merge committed-beta into the run branch
        _git(repo, "checkout", "orch/r1")
        _git(repo, "merge", "--no-ff", "-m", "merge beta", "orch/r1-committed-beta")
        _git(repo, "checkout", "main")

        _write_run(repo, [_unit("committed-beta")])
        _patch_settle(orchestrate, monkeypatch, [[], []])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["committed-beta"]
        assert saved["status"] == "done"


class TestUnitsWithNoBranchOfTheirOwn:
    """The gate reads a branch, so a unit without one is not commit-gated.

    The review controller is that shape: `merge: False`, no branch, its result delivered through
    `review-result` (see tests/test_review_loop_end_to_end.py, which builds exactly this unit).
    Gating it on commits would wedge the review loop at running forever -- no commit can appear on
    a branch the unit does not have -- and `land` puts the controller back to running on every
    resubmission, so the wedge would recur for the life of the run.
    """

    def test_branchless_controller_settles_done_on_confirmed_idle(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        controller = {
            "name": "code-review-controller",
            "vendor": "grok",
            "task": "/saga:code-review review the run branch",
            "role": "review-controller",
            "merge": False,
            "status": "running",
        }
        _write_run(repo, [controller])
        _patch_settle(
            orchestrate,
            monkeypatch,
            [
                [_agent("code-review-controller", "idle")],
                [_agent("code-review-controller", "idle")],
            ],
        )
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["code-review-controller"]
        assert saved["status"] == "done"
        assert "no branch of its own to check" in capsys.readouterr().out

    def test_branchless_controller_gone_is_orphaned_not_failed(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No branch means no evidence either way, so the honest record is orphaned, not failed."""
        controller = {
            "name": "code-review-controller",
            "vendor": "grok",
            "task": "/saga:code-review review the run branch",
            "role": "review-controller",
            "merge": False,
            "status": "running",
        }
        _write_run(repo, [controller])
        _patch_settle(orchestrate, monkeypatch, [[], []])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["code-review-controller"]
        assert saved["status"] == orchestrate.ORPHANED
        assert saved["status"] != orchestrate.FAILED
        assert "commits could not be checked" in saved["note"]


class TestUnresolvableRunBranchIsUnknownNotZero:
    """A run branch that does not resolve makes the commit count unknown, never zero.

    `go` refuses outright in this state and `adopt`/`clean` warn that branch-dependent checks are
    unavailable. Settle must not turn "could not check" into the claim "committed nothing", which
    is the same false negative that #780 exists to remove.
    """

    def test_idle_unit_stays_running_and_names_the_unresolvable_branch(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("committed-alpha")], branch="orch/deleted")
        _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("committed-alpha", "idle")], [_agent("committed-alpha", "idle")]],
        )
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        assert _read_units(repo)["committed-alpha"]["status"] == "running"
        out = capsys.readouterr().out
        assert "run branch does not resolve" in out
        assert "no commits" not in out

    def test_gone_unit_note_does_not_claim_it_committed_nothing(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """committed-alpha has commits; the note must not assert the opposite when unreadable."""
        _write_run(repo, [_unit("committed-alpha")], branch="orch/deleted")
        _patch_settle(orchestrate, monkeypatch, [[], []])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        saved = _read_units(repo)["committed-alpha"]
        assert saved["status"] == orchestrate.ORPHANED
        assert saved["note"] == "session disappeared; commits could not be checked"
        assert "without commits" not in saved["note"]


@pytest.fixture
def repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    bare = tmp_path / "bare.git"
    _git(tmp_path, "init", "--bare", str(bare))
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "remote", "add", "origin", str(bare))
    _git(r, "push", "origin", "main")
    _git(r, "branch", "orch/r1")
    _git(r, "push", "origin", "orch/r1")

    # Committed and pushed unit
    _git(r, "checkout", "-b", "orch/r1-pushed-unit", "orch/r1")
    _commit(r, "pushed.txt")
    _git(r, "push", "origin", "orch/r1-pushed-unit")
    _git(r, "checkout", "main")

    # Committed but NOT pushed unit
    _git(r, "checkout", "-b", "orch/r1-unpushed-unit", "orch/r1")
    _commit(r, "unpushed.txt")
    _git(r, "checkout", "main")

    return r, bare


class TestIncidentShape4ParkedPushSucceededPRBlocked:
    """Incident 4: Push succeeded but PR creation blocked enters typed parked state."""

    def test_park_records_state_when_pushed_commit_verified_on_remote(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo, _bare = repo_with_remote
        _write_run(repo, [_unit("pushed-unit")])
        monkeypatch.chdir(repo)

        tip = subprocess.run(
            ["git", "rev-parse", "orch/r1-pushed-unit"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        args = NS(
            unit="pushed-unit",
            evidence="GraphQL error: PR creation rate limit",
            remote="origin",
            base="main",
        )
        assert orchestrate.cmd_park(args) == 0

        saved = _read_units(repo)["pushed-unit"]
        assert saved["status"] == "parked"
        assert saved["status"] == orchestrate.PARKED
        assert saved["parked_state"]["unit"] == "pushed-unit"
        assert saved["parked_state"]["remote_head"] == tip
        assert saved["parked_state"]["frozen_revision"] == tip
        assert saved["parked_state"]["base"] == "main"
        assert saved["parked_state"]["failure_evidence"] == "GraphQL error: PR creation rate limit"
        assert saved["parked_state"]["remote_branch"] == "orch/r1-pushed-unit"
        assert saved["parked_state"]["remote"] == "origin"
        assert saved["parked_state"]["resumed"] is False
        assert "PR creation rate limit" in saved["note"]

        out = capsys.readouterr().out
        assert f"parked (remote head {tip[:8]} verified on origin)" in out

    def test_park_records_branch_name_not_commit_sha_as_default_base(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, _bare = repo_with_remote
        _write_run(repo, [_unit("pushed-unit")])
        monkeypatch.chdir(repo)

        # Base is omitted -- should default to run branch "orch/r1", not commit SHA r.base
        args = NS(
            unit="pushed-unit",
            evidence="PR creation rate limit",
            remote="origin",
            base=None,
        )
        assert orchestrate.cmd_park(args) == 0

        saved = _read_units(repo)["pushed-unit"]
        assert saved["parked_state"]["base"] == "orch/r1"
        assert not re.fullmatch(r"[0-9a-fA-F]{40}", saved["parked_state"]["base"])

        # When run branch is empty, should default to "main", not commit SHA r.base
        _write_run(repo, [_unit("pushed-unit")], branch="")
        args = NS(
            unit="pushed-unit",
            evidence="PR creation rate limit",
            remote="origin",
            base=None,
        )
        assert orchestrate.cmd_park(args) == 0
        saved = _read_units(repo)["pushed-unit"]
        assert saved["parked_state"]["base"] == "main"

    def test_park_fails_loudly_when_push_failed_or_remote_branch_missing(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, _bare = repo_with_remote
        _write_run(repo, [_unit("unpushed-unit")])
        monkeypatch.chdir(repo)

        args = NS(
            unit="unpushed-unit",
            evidence="GraphQL error: failed to open PR",
            remote="origin",
            base="main",
        )
        with pytest.raises(SystemExit, match="failed push never enters the parked state"):
            orchestrate.cmd_park(args)

        # Verify run record was NOT mutated
        saved = _read_units(repo)["unpushed-unit"]
        assert saved["status"] == "running"
        assert saved.get("parked_state") in ({}, None)

    def test_park_fails_loudly_when_remote_head_differs_from_frozen_revision(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, _bare = repo_with_remote
        # Advance local branch without pushing to remote
        _git(repo, "checkout", "orch/r1-pushed-unit")
        _commit(repo, "extra.txt")
        _git(repo, "checkout", "main")

        _write_run(repo, [_unit("pushed-unit")])
        monkeypatch.chdir(repo)

        args = NS(
            unit="pushed-unit",
            evidence="blocked PR creation",
            remote="origin",
            base="main",
        )
        with pytest.raises(SystemExit, match="does not match local frozen revision"):
            orchestrate.cmd_park(args)

        saved = _read_units(repo)["pushed-unit"]
        assert saved["status"] == "running"

    def test_park_fails_loudly_when_unit_has_no_branch_or_empty_evidence(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, _bare = repo_with_remote
        _write_run(
            repo, [{"name": "branchless", "vendor": "grok", "task": "t", "status": "running"}]
        )
        monkeypatch.chdir(repo)

        args = NS(
            unit="branchless",
            evidence="some error",
            remote="origin",
            base="main",
        )
        with pytest.raises(SystemExit, match="has no branch recorded"):
            orchestrate.cmd_park(args)

        args_empty = NS(
            unit="pushed-unit",
            evidence="   ",
            remote="origin",
            base="main",
        )
        with pytest.raises(SystemExit, match="failure evidence must not be empty"):
            orchestrate.cmd_park(args_empty)


class TestIncidentShape4ParkedResume:
    """Coordinator-owned resume operation: open or adopt exactly one PR idempotently."""

    def _setup_parked_unit(
        self,
        orchestrate: ModuleType,
        repo: Path,
        unit_name: str = "pushed-unit",
        remote: str = "origin",
    ) -> tuple[dict[str, Any], str]:
        tip = subprocess.run(
            ["git", "rev-parse", f"orch/r1-{unit_name}"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        unit_dict = _unit(
            unit_name,
            status=orchestrate.PARKED,
            note="parked: PR blocked",
            parked_state={
                "unit": unit_name,
                "remote_head": tip,
                "base": "main",
                "frozen_revision": tip,
                "failure_evidence": "rate limit error",
                "remote_branch": f"orch/r1-{unit_name}",
                "remote": remote,
                "pr_url": None,
                "pr_number": None,
                "resumed": False,
            },
        )
        _write_run(repo, [unit_dict])
        return unit_dict, tip

    def test_resume_opens_missing_pr_from_recorded_head_and_base(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo, _bare = repo_with_remote
        self._setup_parked_unit(orchestrate, repo, "pushed-unit")
        monkeypatch.chdir(repo)

        calls: list[list[str]] = []
        real_run = orchestrate._subprocess_run

        def mock_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd[0] == "gh":
                if cmd[1:3] == ["pr", "list"]:
                    return subprocess.CompletedProcess(cmd, returncode=0, stdout="[]", stderr="")
                if cmd[1:3] == ["pr", "create"]:
                    return subprocess.CompletedProcess(
                        cmd,
                        returncode=0,
                        stdout="https://github.com/infiquetra/infiquetra-claude-plugins/pull/834\n",
                        stderr="",
                    )
            return cast(subprocess.CompletedProcess[str], real_run(cmd, *args, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mock_run)

        args = NS(
            unit="pushed-unit",
            title=None,
            body=None,
            base=None,
            remote=None,
        )
        assert orchestrate.cmd_resume(args) == 0

        # Verify PR creation call
        pr_create_calls = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
        assert len(pr_create_calls) == 1
        create_argv = pr_create_calls[0]
        assert "--head" in create_argv
        assert "orch/r1-pushed-unit" in create_argv
        assert "--base" in create_argv
        assert "main" in create_argv

        # Verify run record updated
        saved = _read_units(repo)["pushed-unit"]
        assert saved["status"] == "done"
        assert (
            saved["parked_state"]["pr_url"]
            == "https://github.com/infiquetra/infiquetra-claude-plugins/pull/834"
        )
        assert saved["parked_state"]["pr_number"] == 834
        assert saved["parked_state"]["resumed"] is True
        assert "resumed (opened PR #834)" in saved["note"]

        out = capsys.readouterr().out
        assert (
            "pushed-unit: opened PR https://github.com/infiquetra/infiquetra-claude-plugins/pull/834 -> status=done"
            in out
        )

    def test_resume_uses_recorded_parked_remote_when_cli_remote_omitted(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, bare = repo_with_remote
        # Add an upstream remote
        _git(repo, "remote", "add", "upstream", str(bare))
        self._setup_parked_unit(orchestrate, repo, "pushed-unit", remote="upstream")
        monkeypatch.chdir(repo)

        calls: list[list[str]] = []
        real_run = orchestrate._subprocess_run

        def mock_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd[0] == "gh":
                if cmd[1:3] == ["pr", "list"]:
                    return subprocess.CompletedProcess(cmd, returncode=0, stdout="[]", stderr="")
                if cmd[1:3] == ["pr", "create"]:
                    return subprocess.CompletedProcess(
                        cmd,
                        returncode=0,
                        stdout="https://github.com/infiquetra/infiquetra-claude-plugins/pull/834\n",
                        stderr="",
                    )
            return cast(subprocess.CompletedProcess[str], real_run(cmd, *args, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mock_run)

        # Omit --remote (args.remote is None) -- must use recorded remote "upstream"
        args = NS(
            unit="pushed-unit",
            title=None,
            body=None,
            base=None,
            remote=None,
        )
        assert orchestrate.cmd_resume(args) == 0

        # Verify git ls-remote was invoked against "upstream", not hardcoded "origin"
        ls_remote_calls = [c for c in calls if c[:2] == ["git", "ls-remote"]]
        assert len(ls_remote_calls) >= 1
        assert ls_remote_calls[0][2] == "upstream"

    def test_resume_adopts_existing_matching_pr(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo, _bare = repo_with_remote
        _, tip = self._setup_parked_unit(orchestrate, repo, "pushed-unit")
        monkeypatch.chdir(repo)

        calls: list[list[str]] = []
        real_run = orchestrate._subprocess_run

        def mock_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            if cmd[0] == "gh" and cmd[1:3] == ["pr", "list"]:
                existing = [
                    {
                        "number": 835,
                        "url": "https://github.com/infiquetra/infiquetra-claude-plugins/pull/835",
                        "headRefName": "orch/r1-pushed-unit",
                        "headRefOid": tip,
                        "state": "OPEN",
                    }
                ]
                return subprocess.CompletedProcess(
                    cmd, returncode=0, stdout=json.dumps(existing), stderr=""
                )
            return cast(subprocess.CompletedProcess[str], real_run(cmd, *args, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mock_run)

        args = NS(
            unit="pushed-unit",
            title=None,
            body=None,
            base=None,
            remote=None,
        )
        assert orchestrate.cmd_resume(args) == 0

        # Verify gh pr create was NEVER called
        pr_create_calls = [c for c in calls if c[:3] == ["gh", "pr", "create"]]
        assert len(pr_create_calls) == 0

        saved = _read_units(repo)["pushed-unit"]
        assert saved["status"] == "done"
        assert (
            saved["parked_state"]["pr_url"]
            == "https://github.com/infiquetra/infiquetra-claude-plugins/pull/835"
        )
        assert saved["parked_state"]["pr_number"] == 835
        assert saved["parked_state"]["resumed"] is True
        assert "resumed (adopted PR #835)" in saved["note"]

        out = capsys.readouterr().out
        assert (
            "pushed-unit: adopted PR https://github.com/infiquetra/infiquetra-claude-plugins/pull/835 -> status=done"
            in out
        )

    def test_resume_is_idempotent_when_called_again(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo, _bare = repo_with_remote
        _, tip = self._setup_parked_unit(orchestrate, repo, "pushed-unit")
        monkeypatch.chdir(repo)

        # Mark unit as already resumed
        unit_dict = _unit(
            "pushed-unit",
            status="done",
            parked_state={
                "unit": "pushed-unit",
                "remote_head": tip,
                "base": "main",
                "frozen_revision": tip,
                "failure_evidence": "rate limit",
                "remote_branch": "orch/r1-pushed-unit",
                "remote": "origin",
                "pr_url": "https://github.com/infiquetra/infiquetra-claude-plugins/pull/834",
                "pr_number": 834,
                "resumed": True,
            },
        )
        _write_run(repo, [unit_dict])

        calls: list[list[str]] = []
        real_run = orchestrate._subprocess_run

        def mock_run(cmd: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return cast(subprocess.CompletedProcess[str], real_run(cmd, *args, **kwargs))

        monkeypatch.setattr(orchestrate, "run", mock_run)

        args = NS(
            unit="pushed-unit",
            title=None,
            body=None,
            base=None,
            remote=None,
        )
        assert orchestrate.cmd_resume(args) == 0

        # No gh calls made
        gh_calls = [c for c in calls if c[0] == "gh"]
        assert len(gh_calls) == 0

        out = capsys.readouterr().out
        assert (
            "pushed-unit: already resumed (https://github.com/infiquetra/infiquetra-claude-plugins/pull/834)"
            in out
        )

    def test_resume_fails_loudly_when_remote_branch_missing(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, bare = repo_with_remote
        self._setup_parked_unit(orchestrate, repo, "pushed-unit")
        monkeypatch.chdir(repo)

        # Delete the branch on the bare remote
        subprocess.run(
            ["git", "branch", "-D", "orch/r1-pushed-unit"],
            cwd=bare,
            check=True,
            capture_output=True,
        )

        args = NS(
            unit="pushed-unit",
            title=None,
            body=None,
            base=None,
            remote=None,
        )
        with pytest.raises(SystemExit, match="is missing on remote"):
            orchestrate.cmd_resume(args)

        # Run record unchanged
        saved = _read_units(repo)["pushed-unit"]
        assert saved["status"] == "parked"
        assert saved["parked_state"]["resumed"] is False

    def test_resume_fails_loudly_when_remote_head_changed(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, bare = repo_with_remote
        self._setup_parked_unit(orchestrate, repo, "pushed-unit")
        monkeypatch.chdir(repo)

        # Push a new commit to the branch on bare remote from a temporary clone
        tmp_clone = repo.parent / "tmp_clone"
        _git(repo.parent, "clone", str(bare), str(tmp_clone))
        _git(tmp_clone, "config", "user.email", "test@example.com")
        _git(tmp_clone, "config", "user.name", "Test")
        _git(tmp_clone, "checkout", "orch/r1-pushed-unit")
        _commit(tmp_clone, "diverged.txt")
        _git(tmp_clone, "push", "origin", "orch/r1-pushed-unit")

        args = NS(
            unit="pushed-unit",
            title=None,
            body=None,
            base=None,
            remote=None,
        )
        with pytest.raises(
            SystemExit, match="remote head for 'orch/r1-pushed-unit' on 'origin' has changed"
        ):
            orchestrate.cmd_resume(args)

        # Run record unchanged
        saved = _read_units(repo)["pushed-unit"]
        assert saved["status"] == "parked"
        assert saved["parked_state"]["resumed"] is False

    def test_resume_fails_loudly_when_unit_not_parked(
        self,
        orchestrate: ModuleType,
        repo_with_remote: tuple[Path, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        repo, _bare = repo_with_remote
        _write_run(repo, [_unit("pushed-unit", status="running")])
        monkeypatch.chdir(repo)

        args = NS(
            unit="pushed-unit",
            title=None,
            body=None,
            base=None,
            remote=None,
        )

        with pytest.raises(SystemExit, match="is not in parked state"):
            orchestrate.cmd_resume(args)
