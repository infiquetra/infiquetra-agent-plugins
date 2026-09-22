"""Where the run record and the repository disagree, and how adopt puts the pieces back.

A run's whole state is one JSON file, while the truth lives in git and herdr; the two drift when a
session is started by hand or a run file is lost around live work. ``check`` names the drift and
changes nothing; ``adopt`` rebuilds a unit row from what is still true -- the branch, its worktree,
and the session herdr reports there -- and only writes when told to.

Both are driven against a real git repository. The discovery under test is reading actual branches
and worktrees, so a fake that reports them proves nothing about whether they exist.
"""

from __future__ import annotations

import argparse
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

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
    spec = importlib.util.spec_from_file_location("_orchestrate_drift_adopt", SCRIPT)
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
    """A run branch and two unit branches, each with one commit, both already landed.

    Landed rather than raw so the fixture is a run whose record agrees with the repository -- the
    clean baseline ``check`` reports nothing on. Tests that need drift add branches on top of it.
    """
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "branch", "orch/r1")
    for unit in ("alpha", "beta"):
        _git(r, "checkout", "-b", f"orch/r1-{unit}", "orch/r1")
        _commit(r, f"{unit}.txt")
        _git(r, "checkout", "orch/r1")
        _git(r, "merge", "--no-ff", "--no-edit", f"orch/r1-{unit}")
    _git(r, "checkout", "main")
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


def _read_run(repo: Path) -> dict[str, Any]:
    raw: dict[str, Any] = _support.read_record(test_store(), _support.TEST_ISSUE)
    return raw


def _unit(name: str, **over: Any) -> dict[str, Any]:
    return {
        "name": name,
        "vendor": "claude",
        "task": "x",
        "branch": f"orch/r1-{name}",
        "status": "done",
        **over,
    }


class _NoLiveSessions:
    """The no-live-session baseline, pinned rather than assumed.

    ``check`` and ``adopt`` each take one ``herdr agent list`` reading and match units against
    it. These classes describe a temporary repository with no session at all, but until this
    fixture existed they asked the herdr on PATH -- the operator's live one here, none on a
    runner -- and got the empty answer only by luck of what that herdr was tracking (issue 907,
    U34). ``TestHerdrIsOptional`` deliberately leaves the reading live under a PATH of its own.
    """

    @pytest.fixture(autouse=True)
    def _no_live_sessions(self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(orchestrate, "live_agents", lambda *_a, **_k: [])


class TestCheck(_NoLiveSessions):
    def test_a_clean_run_reports_nothing(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)
        assert orchestrate.cmd_check(NS()) == 0
        assert "the record agrees with the repository" in capsys.readouterr().out

    def test_a_branch_with_no_unit_is_unrecorded(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _git(repo, "branch", "orch/r1-stray", "orch/r1")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 1
        out = capsys.readouterr().out
        assert "UNRECORDED stray -- branch orch/r1-stray is not a unit in this run" in out

    def test_the_run_branch_itself_is_never_unrecorded(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``orch/r1`` exists like any other run branch, but it is no unit and must never appear."""
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)
        orchestrate.cmd_check(NS())

        out = capsys.readouterr().out
        assert "branch orch/r1 is not a unit" not in out

    def test_a_done_unit_with_no_commits_is_reported(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # at base with nothing of its own: the session finished and saved nothing
        _git(repo, "branch", "orch/r1-empty", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta"), _unit("empty")])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 1
        assert "NO COMMITS empty" in capsys.readouterr().out

    def test_a_done_unit_with_unlanded_commits_is_reported(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        _git(repo, "checkout", "orch/r1-alpha")
        _commit(repo, "late.txt")
        _git(repo, "checkout", "main")
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 1
        out = capsys.readouterr().out
        assert "NOT LANDED alpha" in out
        assert "1 commit not on orch/r1" in out

    def test_a_done_unit_with_merge_false_is_not_not_landed(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """merge=false is a hold by request, not drift -- ``land`` names it, ``check`` must not."""
        _write_run(repo, [_unit("alpha"), _unit("beta", merge=False)])
        _git(repo, "checkout", "orch/r1-beta")
        _commit(repo, "late.txt")
        _git(repo, "checkout", "main")
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 0
        out = capsys.readouterr().out
        assert "NOT LANDED" not in out
        assert "the record agrees with the repository" in out


def _fake_agents(
    orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch, states: dict[str, str]
) -> None:
    """Stand in for herdr's session list: one agent per name, at the given ``agent_status``.

    The real herdr may or may not exist on the machine running these tests, and its sessions are
    never these units', so ``check`` is answered from a list built here instead. ``poll`` matches
    on the name, so the real matching still runs.
    """
    agents = [{"name": name, "agent_status": status} for name, status in states.items()]
    monkeypatch.setattr(orchestrate, "live_agents", lambda: agents)


class TestLooksDone:
    """A unit the record calls running whose session went idle with work already committed.

    Neither half is wrong on its own -- the branch has commits, the session is idle -- and that is
    why nothing else in ``check`` notices it. The drift is that the unit finished and the record
    was never told, which stalls the run until an operator asks why.
    """

    def test_running_idle_with_commits_fires_looks_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # cut from main, not orch/r1: its commit is its own, not the landed work of other units
        _git(repo, "checkout", "-b", "orch/r1-fix-52", "main")
        _commit(repo, "fix.txt")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta"), _unit("fix-52", status="running")])
        _fake_agents(orchestrate, monkeypatch, {"fix-52": "idle"})
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 1
        out = capsys.readouterr().out
        assert (
            "  LOOKS DONE fix-52 -- marked running, but its session is idle "
            "and its branch has commits"
        ) in out

    def test_running_reported_done_with_commits_fires_looks_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """``done`` is the other settled state herdr reports, and counts the same as idle."""
        _git(repo, "checkout", "-b", "orch/r1-fix-52", "main")
        _commit(repo, "fix.txt")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta"), _unit("fix-52", status="running")])
        _fake_agents(orchestrate, monkeypatch, {"fix-52": "done"})
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 1
        assert (
            "  LOOKS DONE fix-52 -- marked running, but its session is done "
            "and its branch has commits"
        ) in capsys.readouterr().out

    def test_running_idle_with_no_commits_is_not_reported(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Idle is also what a session is between turns; with nothing saved it may be thinking."""
        # at base with nothing of its own -- a branch cut from orch/r1 would carry the landed
        # commits of the other units and read as produced
        _git(repo, "branch", "orch/r1-slow", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta"), _unit("slow", status="running")])
        _fake_agents(orchestrate, monkeypatch, {"slow": "idle"})
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 0
        out = capsys.readouterr().out
        assert "LOOKS DONE" not in out
        assert "the record agrees with the repository" in out

    def test_running_working_is_not_reported(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A session still working is exactly what ``running`` says, commits or no commits."""
        _git(repo, "checkout", "-b", "orch/r1-fix-52", "main")
        _commit(repo, "fix.txt")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta"), _unit("fix-52", status="running")])
        _fake_agents(orchestrate, monkeypatch, {"fix-52": "working"})
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 0
        assert "LOOKS DONE" not in capsys.readouterr().out

    def test_a_done_unit_is_not_looks_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The finding is for units marked running; a done unit is already settled."""
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        _fake_agents(orchestrate, monkeypatch, {"alpha": "idle", "beta": "idle"})
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_check(NS()) == 0
        assert "LOOKS DONE" not in capsys.readouterr().out


def _hide_herdr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PATH with git on it and no herdr -- what a build runner actually looks like.

    Emptying PATH outright would also hide git, which these commands genuinely need; that tests a
    different machine than the one that broke.
    """
    only_git = tmp_path / "path-without-herdr"
    only_git.mkdir(exist_ok=True)
    (only_git / "git").symlink_to(shutil.which("git") or "/usr/bin/git")
    monkeypatch.setenv("PATH", str(only_git))
    assert shutil.which("herdr") is None


class TestHerdrIsOptional:
    """Both commands decided herdr is optional; the code only half meant it.

    ``check=False`` covers a command that fails, not a command that is not installed --
    ``subprocess.run`` raises there rather than returning. CI has no herdr, and every one of these
    tests died on a traceback out of a read-only command. This machine has herdr, which is exactly
    why the local run was green.
    """

    def test_check_survives_a_machine_without_herdr(
        self,
        orchestrate: ModuleType,
        repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha")])
        _hide_herdr(tmp_path, monkeypatch)
        monkeypatch.chdir(repo)
        orchestrate.cmd_check(NS())

    def test_adopt_survives_a_machine_without_herdr(
        self,
        orchestrate: ModuleType,
        repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [])
        _hide_herdr(tmp_path, monkeypatch)
        monkeypatch.chdir(repo)
        orchestrate.cmd_adopt(NS(yes=False))


class TestAdopt(_NoLiveSessions):
    """No live session exists in a temporary repository: these all exercise the no-matched-agent
    path, which is the one where a branch is all the evidence there is."""

    def test_without_yes_nothing_is_written(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _git(repo, "checkout", "-b", "orch/r1-stray", "orch/r1")
        _commit(repo, "stray.txt")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_adopt(NS(yes=False)) == 0
        out = capsys.readouterr().out
        assert "would adopt: stray" in out
        assert "nothing written -- rerun with --yes" in out
        assert [u["name"] for u in _read_run(repo)["units"]] == ["alpha", "beta"]

    def test_an_unresolvable_run_branch_is_reported_and_degrades_without_a_traceback(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _git(repo, "checkout", "-b", "orch/r1-stray", "orch/r1")
        _commit(repo, "stray.txt")
        _git(repo, "checkout", "main")
        _git(repo, "branch", "-m", "orch/r1", "orch/r1-renamed")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)
        monkeypatch.setattr(orchestrate, "live_agents", lambda: [])

        assert orchestrate.cmd_adopt(NS(yes=False)) == 0

        output = capsys.readouterr().out
        assert "WARNING: run branch 'orch/r1' does not resolve" in output
        assert "would adopt: stray" in output
        assert "status=failed" in output
        assert "nothing written -- rerun with --yes" in output

    def test_with_yes_the_unit_lands_in_the_record(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _git(repo, "checkout", "-b", "orch/r1-stray", "orch/r1")
        _commit(repo, "stray.txt")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_adopt(NS(yes=True)) == 0
        out = capsys.readouterr().out
        assert "adopted: stray" in out
        assert "1 unit(s) written to the run file" in out

        units = {u["name"]: u for u in _read_run(repo)["units"]}
        assert "stray" in units
        assert units["stray"]["branch"] == "orch/r1-stray"
        assert units["stray"]["note"] == "adopted: created outside the run record"

    def test_refs_heads_worktree_listing_recovers_the_adopted_units_live_session(
        self,
        orchestrate: ModuleType,
        repo: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        worktree = tmp_path / "stray-worktree"
        _git(
            repo,
            "worktree",
            "add",
            "-b",
            "orch/r1-stray",
            str(worktree),
            "orch/r1",
        )
        _commit(worktree, "stray.txt")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)
        monkeypatch.setattr(
            orchestrate,
            "live_agents",
            lambda: [
                {
                    "name": "stray-agent",
                    "agent": "codex",
                    "agent_status": "working",
                    "cwd": str(worktree),
                    "tab_id": "tab-1",
                    "pane_id": "pane-1",
                }
            ],
        )

        assert orchestrate.cmd_adopt(NS(yes=True)) == 0

        units = {u["name"]: u for u in _read_run(repo)["units"]}
        assert units["stray"]["worktree"] == str(worktree)
        assert units["stray"]["vendor"] == "codex"
        assert units["stray"]["status"] == "running"
        assert units["stray"]["agent_name"] == "stray-agent"
        assert units["stray"]["tab_id"] == "tab-1"
        assert units["stray"]["pane_id"] == "pane-1"

    def test_a_branch_with_commits_and_no_session_is_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Commits are the evidence the session finished its work, so the row says done."""
        _git(repo, "checkout", "-b", "orch/r1-stray", "orch/r1")
        _commit(repo, "stray.txt")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)

        orchestrate.cmd_adopt(NS(yes=True))
        units = {u["name"]: u for u in _read_run(repo)["units"]}
        assert units["stray"]["status"] == "done"
        assert units["stray"]["vendor"] == "unknown"

    def test_a_branch_with_no_commits_and_no_session_is_failed(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No session and nothing committed: there is no reading of that in which it succeeded."""
        # at base with nothing of its own -- a branch cut from orch/r1 would carry the landed
        # commits of the other units and read as done
        _git(repo, "branch", "orch/r1-hollow", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)

        orchestrate.cmd_adopt(NS(yes=True))
        units = {u["name"]: u for u in _read_run(repo)["units"]}
        assert units["hollow"]["status"] == "failed"

    def test_adopting_twice_does_not_duplicate(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The second pass must see the unit the first pass wrote, not the branch alone."""
        _git(repo, "checkout", "-b", "orch/r1-stray", "orch/r1")
        _commit(repo, "stray.txt")
        _git(repo, "checkout", "main")
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_adopt(NS(yes=True)) == 0
        assert orchestrate.cmd_adopt(NS(yes=True)) == 0
        names = [u["name"] for u in _read_run(repo)["units"]]
        assert names.count("stray") == 1
