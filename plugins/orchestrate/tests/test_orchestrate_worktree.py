"""A fresh worktree on every launch, with a declared environment step (issue #1025, U2).

Card 886 reported a relaunch reusing a stale worktree: the session found work it did not do, a
prompt could be stranded, and a second live session could end up in one tree. The answer taken
here is not to fast-forward or refuse the reused directory -- it is to never reuse one. The unit's
*branch* is its identity and is reused; only the working directory is new.

The environment step is the fifth recorded collision: a session in a worktree with no virtual
environment produces confident work that cannot run its own tests.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from orchestrate_support import (
    FakeProc,
    git,
    load_orchestrate,
    make_repo,
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
    return load_orchestrate("_orchestrate_worktree", ORCHESTRATE_SCRIPT)


@pytest.fixture
def run_and_repo(orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = make_repo(tmp_path, branch="issue/3")
    monkeypatch.chdir(repo)
    base = git(repo, "rev-parse", "main")
    r = orch.Run(
        run_id="3",
        source="a test",
        base=base,
        units=[orch.Unit(name="u1", vendor="claude", task="do work")],
        branch="issue/3",
        issue=3,
    )
    return r, repo


class TestFreshWorktreePerLaunch:
    def test_two_launches_get_two_different_paths(self, orch, run_and_repo) -> None:
        r, repo = run_and_repo
        unit = r.units[0]

        assert orch.make_worktree(unit, r, repo) is None
        first = Path(unit.worktree)
        assert first.is_dir()

        assert orch.make_worktree(unit, r, repo) is None
        second = Path(unit.worktree)

        assert second != first, "a relaunch must never reuse the previous worktree path"
        assert second.is_dir()
        # The stale tree is RELEASED rather than left as litter, and the new path is a different
        # name even so, so "never a reused path" stays checkable on disk afterwards.
        assert not first.exists()

    def test_a_relaunch_is_refused_when_the_stale_worktree_is_dirty(
        self, orch, run_and_repo, capsys
    ) -> None:
        """ "Fresh" must never mean "discarded": uncommitted work stops the relaunch by name."""
        r, repo = run_and_repo
        unit = r.units[0]
        orch.make_worktree(unit, r, repo)
        (Path(unit.worktree) / "unsaved.txt").write_text("work nobody committed\n")

        failure = orch.make_worktree(unit, r, repo)

        assert failure is not None
        assert "uncommitted changes" in failure
        assert Path(unit.worktree).is_dir(), "the dirty worktree is left exactly where it was"

    def test_the_second_launch_reuses_the_units_branch(self, orch, run_and_repo) -> None:
        """The branch holds the unit's history; a relaunch continues it, it does not fork it."""
        r, repo = run_and_repo
        unit = r.units[0]
        orch.make_worktree(unit, r, repo)
        branch = unit.branch
        orch.make_worktree(unit, r, repo)
        assert unit.branch == branch
        listed = git(repo, "branch", "--list", "orch/3-*", "--format=%(refname:short)")
        assert listed.splitlines() == [branch]

    def test_a_path_on_disk_that_git_does_not_know_is_still_skipped(
        self, orch, run_and_repo
    ) -> None:
        r, repo = run_and_repo
        canonical = repo.parent / "orch-3-u1"
        canonical.mkdir()
        orch.make_worktree(r.units[0], r, repo)
        assert Path(r.units[0].worktree) != canonical

    def test_a_dangling_symlink_counts_as_taken(self, orch, run_and_repo) -> None:
        """``exists()`` is false for a dangling link and ``git worktree add`` still fails."""
        r, repo = run_and_repo
        canonical = repo.parent / "orch-3-u1"
        canonical.symlink_to(repo.parent / "nowhere")
        assert not canonical.exists() and os.path.lexists(canonical)
        orch.make_worktree(r.units[0], r, repo)
        assert Path(r.units[0].worktree) != canonical


class TestWorktreeEnvironmentStep:
    def test_uv_sync_runs_when_the_repository_has_a_lock_file(
        self, orch, run_and_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r, repo = run_and_repo
        (repo / "uv.lock").write_text("")
        seen: list[list[str]] = []
        real = orch.run

        def spy(cmd, **kw):
            if cmd[:1] == ["uv"]:
                seen.append(list(cmd))
                return FakeProc(0)
            return real(cmd, **kw)

        monkeypatch.setattr(orch, "run", spy)
        assert orch.make_worktree(r.units[0], r, repo) is None
        assert seen == [["uv", "sync", "--locked", "--extra", "dev"]]

    def test_the_environment_variable_overrides_the_default(
        self, orch, run_and_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r, repo = run_and_repo
        (repo / "uv.lock").write_text("")
        monkeypatch.setenv(orch.WORKTREE_SETUP_ENV, "make bootstrap --quiet")
        seen: list[list[str]] = []
        real = orch.run

        def spy(cmd, **kw):
            if cmd[:1] == ["make"]:
                seen.append(list(cmd))
                return FakeProc(0)
            return real(cmd, **kw)

        monkeypatch.setattr(orch, "run", spy)
        assert orch.make_worktree(r.units[0], r, repo) is None
        assert seen == [["make", "bootstrap", "--quiet"]]

    def test_a_failing_setup_step_is_named_and_the_unit_is_not_launched(
        self, orch, run_and_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r, repo = run_and_repo
        (repo / "uv.lock").write_text("")
        real = orch.run

        def spy(cmd, **kw):
            if cmd[:1] == ["uv"]:
                return FakeProc(2, stderr="No solution found for the lock file")
            return real(cmd, **kw)

        monkeypatch.setattr(orch, "run", spy)
        failure = orch.make_worktree(r.units[0], r, repo)
        assert failure is not None
        assert "uv sync --locked --extra dev" in failure
        assert "No solution found" in failure

    def test_no_lock_file_and_no_override_runs_no_step_and_says_so(
        self, orch, run_and_repo, capsys
    ) -> None:
        r, repo = run_and_repo
        assert not (repo / "uv.lock").exists()
        assert orch.make_worktree(r.units[0], r, repo) is None
        assert "no setup step run" in capsys.readouterr().out


class TestWorktreeBeforeBranch:
    def test_a_failed_worktree_removal_keeps_the_branch_and_names_both(
        self, orch, run_and_repo, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """git refuses to delete a branch a worktree holds, so the order is load-bearing."""
        r, repo = run_and_repo
        unit = r.units[0]
        orch.make_worktree(unit, r, repo)
        unit.status = orch.DONE
        unit.tab_id = None
        real = orch.run
        deleted: list[list[str]] = []

        def spy(cmd, **kw):
            if cmd[:3] == ["git", "worktree", "remove"]:
                return FakeProc(128, stderr="fatal: injected removal failure")
            if cmd[:3] == ["git", "branch", "-D"]:
                deleted.append(list(cmd))
            return real(cmd, **kw)

        monkeypatch.setattr(orch, "run", spy)
        monkeypatch.setattr(orch, "live_agents", lambda **kw: [])
        monkeypatch.setattr(orch, "clean_remote_branches", lambda *a, **k: orch.RemoteCleanReport())
        kept_reasons: dict[str, str] = {}
        closed, kept = orch.reap(r, merged_only=False, branches=True, kept_reasons=kept_reasons)

        assert unit.name in kept and unit.name not in closed
        assert "worktree removal failed" in kept_reasons[unit.name]
        assert deleted == [], "the branch must not be deleted while its worktree survives"
        assert git(repo, "rev-parse", "--verify", unit.branch)
