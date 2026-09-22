"""Cleanup runs for every unit, names every leftover, and retires this run's workspaces (U6).

Three defects meet here. Issue 960: ``land --clean`` skipped the reap entirely when one landing
path could not be cleaned, and said nothing about the skip. Issue 979: a removal failure recorded
while an exception was unwinding was appended to a list whose only reader that path skipped.
Issue 991: the cleanup-failure test chose one of three host mechanisms, so which failure shape ran
differed per machine and every run left an undeletable directory behind.

**Every failure in this module is injected at the command runner.** The same code path therefore
runs on every machine, a defect appearing under only one platform cannot pass, and nothing
undeletable is left on disk. That is issue 991's repair, and it is why this module replaces the
cleanup assertions that lived in ``test_orchestrate_land_clean.py`` and
``test_orchestrate_land_worktree.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orchestrate_support import (
    FakeProc,
    args,
    git,
    load_orchestrate,
    make_repo,
    unit_row,
    write_record,
)

#: The production driver this module drives. Constructed here, not imported from the shared
#: helper, so the module names on its own face the real file it crosses into.
ORCHESTRATE_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)


@pytest.fixture(scope="module")
def orch():
    return load_orchestrate("_orchestrate_clean", ORCHESTRATE_SCRIPT)


@pytest.fixture
def bed(orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = make_repo(tmp_path, branch="parent/50")
    monkeypatch.chdir(repo)
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
    monkeypatch.setattr(orch, "live_agents", lambda **kw: [])
    monkeypatch.setattr(orch, "clean_remote_branches", lambda *a, **k: orch.RemoteCleanReport())
    monkeypatch.setattr(orch, "close_run_session", lambda unit: FakeProc(0))
    return repo, store


def make_unit_worktree(repo: Path, name: str) -> Path:
    git(repo, "branch", f"orch/50-{name}", "parent/50")
    path = repo.parent / f"orch-50-{name}"
    git(repo, "worktree", "add", str(path), f"orch/50-{name}")
    return path


def record(store: Path, repo: Path, units):
    return write_record(
        store,
        50,
        units=units,
        run_id="50",
        base=git(repo, "rev-parse", "main"),
        branch="parent/50",
    )


def clean_args(store: Path, **over):
    fields = {"merged": False, "branches": False, "remote": "origin"}
    fields.update(over)
    return args(50, store, **fields)


def fails_removing(orch, monkeypatch, path: Path):
    """Make exactly one ``git worktree remove`` fail, identically on every machine."""
    real = orch.run

    def spy(cmd, **kw):
        if cmd[:3] == ["git", "worktree", "remove"] and str(path) in cmd:
            return FakeProc(128, stderr="fatal: injected removal failure")
        return real(cmd, **kw)

    monkeypatch.setattr(orch, "run", spy)


class TestTheSweepIsTotal:
    def test_one_unremovable_path_does_not_stop_the_sweep(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Issue 960: the whole reap used to be skipped when one path could not be cleaned."""
        repo, store = bed
        stuck = make_unit_worktree(repo, "u1")
        fine = make_unit_worktree(repo, "u2")
        record(
            store,
            repo,
            [
                unit_row("u1", branch="orch/50-u1", status="done", worktree=str(stuck)),
                unit_row("u2", branch="orch/50-u2", status="done", worktree=str(fine)),
            ],
        )
        fails_removing(orch, monkeypatch, stuck)

        code = orch.cmd_clean(clean_args(store))

        out = capsys.readouterr().out
        assert code == 3, "the exit status says cleanup was incomplete"
        assert "closed: u2" in out
        assert "injected removal failure" in out
        assert str(stuck) in out or "u1" in out
        assert not fine.exists(), "every other unit is still cleaned"

    def test_the_leftover_is_named_with_gits_own_message(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        stuck = make_unit_worktree(repo, "u1")
        record(
            store, repo, [unit_row("u1", branch="orch/50-u1", status="done", worktree=str(stuck))]
        )
        fails_removing(orch, monkeypatch, stuck)
        orch.cmd_clean(clean_args(store))
        assert "injected removal failure" in capsys.readouterr().out

    def test_the_report_runs_even_while_an_exception_is_unwinding(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Issue 979: the only reader of the failure list was skipped by an in-flight exception."""
        repo, store = bed
        stuck = make_unit_worktree(repo, "u1")
        record(
            store, repo, [unit_row("u1", branch="orch/50-u1", status="done", worktree=str(stuck))]
        )
        real_reap = orch.reap

        def reap_then_raise(r, **kw):
            kw["kept_reasons"]["u1"] = "worktree removal failed (128): injected"
            raise RuntimeError("something else went wrong mid-sweep")

        monkeypatch.setattr(orch, "reap", reap_then_raise)
        with pytest.raises(RuntimeError):
            orch.cmd_clean(clean_args(store))
        assert "kept u1: worktree removal failed" in capsys.readouterr().out
        assert real_reap is not None

    def test_repeated_cleanup_is_idempotent_on_an_already_absent_worktree(
        self, orch, bed, capsys
    ) -> None:
        repo, store = bed
        path = make_unit_worktree(repo, "u1")
        record(
            store, repo, [unit_row("u1", branch="orch/50-u1", status="done", worktree=str(path))]
        )
        assert orch.cmd_clean(clean_args(store)) == 0
        assert orch.cmd_clean(clean_args(store)) == 0
        assert "closed: u1" in capsys.readouterr().out

    def test_merge_clean_reaps_the_other_unit_when_one_path_is_stuck(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """Issue 960 named this flag exactly: the reap must not be skipped wholesale."""
        repo, store = bed
        stuck = make_unit_worktree(repo, "u1")
        fine = make_unit_worktree(repo, "u2")
        record(
            store,
            repo,
            [
                unit_row("u1", branch="orch/50-u1", status="done", worktree=str(stuck)),
                unit_row("u2", branch="orch/50-u2", status="done", worktree=str(fine)),
            ],
        )
        fails_removing(orch, monkeypatch, stuck)
        r = orch.Run.load(50, store)
        kept_reasons: dict[str, str] = {}
        closed, _ = orch.reap(r, merged_only=False, only=["u1", "u2"], kept_reasons=kept_reasons)
        assert closed == ["u2"]
        assert "u1" in kept_reasons


class TestWorkspaceRetirement:
    def test_a_workspace_this_run_created_is_retired_once_its_tabs_are_gone(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        write_record(
            store,
            50,
            units=[],
            run_id="50",
            base=git(repo, "rev-parse", "main"),
            branch="parent/50",
            workspaces_created=["50-lane-a"],
        )
        closed: list[list[str]] = []
        real = orch.run

        def spy(cmd, **kw):
            if cmd[:2] == ["herdr", "workspace"]:
                closed.append(list(cmd))
                return FakeProc(0)
            return real(cmd, **kw)

        monkeypatch.setattr(orch, "run", spy)
        orch.cmd_clean(clean_args(store))
        assert closed == [["herdr", "workspace", "close", "50-lane-a"]]

    def test_a_workspace_still_holding_a_live_agent_is_refused_and_the_agent_named(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        write_record(
            store,
            50,
            units=[],
            run_id="50",
            base=git(repo, "rev-parse", "main"),
            branch="parent/50",
            workspaces_created=["50-lane-a"],
        )
        monkeypatch.setattr(
            orch,
            "live_agents",
            lambda **kw: [{"name": "someone-else", "pane_id": "50-lane-a:pane-3"}],
        )
        monkeypatch.setattr(
            orch,
            "run",
            lambda cmd, **kw: (
                pytest.fail(f"a live workspace was touched: {cmd}")
                if cmd[:2] == ["herdr", "workspace"]
                else FakeProc(0)
            ),
        )
        orch.cmd_clean(clean_args(store))
        assert "it still holds someone-else" in capsys.readouterr().out

    def test_a_workspace_this_run_did_not_create_is_never_retired(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Ownership comes from the record; a prefix match would retire someone else's lane."""
        repo, store = bed
        write_record(
            store,
            50,
            units=[],
            run_id="50",
            base=git(repo, "rev-parse", "main"),
            branch="parent/50",
            workspaces_created=[],
        )
        monkeypatch.setattr(
            orch,
            "run",
            lambda cmd, **kw: (
                pytest.fail(f"an unowned workspace was touched: {cmd}")
                if cmd[:2] == ["herdr", "workspace"]
                else FakeProc(0)
            ),
        )
        assert orch.cmd_clean(clean_args(store)) == 0


class TestTheFleetDoctorCheck:
    def test_a_managed_worktree_with_no_live_session_is_reported_by_path(
        self, orch, bed, capsys
    ) -> None:
        """The one check worth keeping from the retired fleet-doctor command."""
        repo, store = bed
        path = make_unit_worktree(repo, "u1")
        record(
            store,
            repo,
            [unit_row("u1", branch="orch/50-u1", status="running", worktree=str(path))],
        )
        # `--merged` keeps a running unit, which is the state the check is about: its worktree is
        # managed by this run and nothing is standing in it.
        orch.cmd_clean(clean_args(store, merged=True))
        out = capsys.readouterr().out
        assert f"managed worktree at {path}" in out
        assert "no live session is standing in it" in out

    def test_a_worktree_with_a_live_session_is_not_reported(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        path = make_unit_worktree(repo, "u1")
        record(
            store,
            repo,
            [unit_row("u1", branch="orch/50-u1", status="running", worktree=str(path))],
        )
        monkeypatch.setattr(orch, "live_agents", lambda **kw: [{"name": "u1", "cwd": str(path)}])
        orch.cmd_clean(clean_args(store, merged=True))
        assert "managed worktree at" not in capsys.readouterr().out


class TestMutationProof:
    def test_removing_the_ownership_check_would_retire_an_unowned_workspace(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The guard is the record's list; with it emptied, nothing may be closed."""
        repo, store = bed
        write_record(
            store,
            50,
            units=[],
            run_id="50",
            base=git(repo, "rev-parse", "main"),
            branch="parent/50",
            workspaces_created=[],
        )
        r = orch.Run.load(50, store)
        assert orch.retire_run_workspaces(r) == []

    def test_continuing_past_a_failure_is_what_makes_the_sweep_total(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the loop returned on the first failure, u2 would be kept instead of closed."""
        repo, store = bed
        stuck = make_unit_worktree(repo, "u1")
        fine = make_unit_worktree(repo, "u2")
        record(
            store,
            repo,
            [
                unit_row("u1", branch="orch/50-u1", status="done", worktree=str(stuck)),
                unit_row("u2", branch="orch/50-u2", status="done", worktree=str(fine)),
            ],
        )
        fails_removing(orch, monkeypatch, stuck)
        r = orch.Run.load(50, store)
        closed, kept = orch.reap(r, merged_only=False, kept_reasons={})
        assert "u2" in closed and "u1" in kept
