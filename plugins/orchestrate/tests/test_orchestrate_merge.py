"""The merge turn, the parent branch, and the guard against reverting a newer main (U5).

``land`` is gone and ``merge`` takes its place. What went with the name is the bookkeeping around
the merge -- the retained conflict pointer that outlived an invocation, the numbered landing-path
fallback, the retained-merge recovery -- not the merge itself, which still happens in one detached
worktree created and removed inside the turn.

The merge turn is ordinary record state and not a lock: it has no owner token and no expiry, so
the refusal is derived by asking git whether a merge is actually in flight. Card 875's regression
guard survives the removal of ``collect`` as a rule of the turn.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orchestrate_support import (
    FakeProc,
    args,
    commit_file,
    git,
    load_orchestrate,
    make_repo,
    read_record,
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
    return load_orchestrate("_orchestrate_merge", ORCHESTRATE_SCRIPT)


@pytest.fixture
def bed(orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A repository with a parent branch, one unit branch with work on it, and a fake remote."""
    repo = make_repo(tmp_path, branch="parent/40")
    monkeypatch.chdir(repo)
    git(repo, "checkout", "-b", "orch/40-u1", "parent/40")
    commit_file(repo, "unit.txt", "work from u1\n")
    git(repo, "checkout", "main")

    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
    # The two board-writeback stand-ins that used to sit here are gone with the writeback itself
    # (issue 1028): `merge` makes no board write at all now, so there is nothing left to stub.
    monkeypatch.setattr(orch, "live_agents", lambda **kw: [])
    monkeypatch.setattr(orch, "append_unit_note", _append)
    # A real bare remote, so `origin/main` is a real remote-tracking ref and the guard reads
    # something true rather than a stand-in. Nothing here reaches the network.
    remote = tmp_path / "remote.git"
    git(repo, "init", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    git(repo, "fetch", "-q", "origin")
    return repo, store


def advance_remote_main(repo: Path, name: str, body: str) -> None:
    """Put a newer commit on the remote's ``main``, the way another run's merge would."""
    git(repo, "checkout", "-q", "-B", "remote-work", "origin/main")
    commit_file(repo, name, body)
    git(repo, "push", "-q", "origin", "remote-work:main")
    git(repo, "fetch", "-q", "origin")
    git(repo, "checkout", "-q", "main")


def _append(unit, text: str) -> None:
    unit.note = f"{unit.note}; {text}" if unit.note else text


def _record(store: Path, repo: Path, units, **block):
    return write_record(
        store,
        40,
        units=units,
        run_id="40",
        base=git(repo, "rev-parse", "main"),
        branch="parent/40",
        **block,
    )


def _done(name: str, **over):
    return unit_row(name, branch=f"orch/40-{name}", status="done", **over)


def _merge_args(store: Path, **over):
    fields = {"clean": False, "remote": "origin", "compare": "main"}
    fields.update(over)
    return args(40, store, **fields)


def _no_fetch(orch, monkeypatch):
    monkeypatch.setattr(orch, "fetch_default_branch", lambda remote, branch: None)


class TestTheMergeTurn:
    def test_a_unit_merges_onto_the_parent_branch(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        _record(store, repo, [_done("u1")])
        before = git(repo, "rev-parse", "parent/40")

        assert orch.cmd_merge(_merge_args(store)) == 0

        after = git(repo, "rev-parse", "parent/40")
        assert after != before
        parents = git(repo, "rev-list", "--parents", "-n", "1", "parent/40").split()
        assert len(parents) == 3, "the turn makes a real two-parent merge"
        assert parents[2] == git(repo, "rev-parse", "orch/40-u1")
        assert read_record(store, 40)["units"][0]["merge_state"] == "merged"

    def test_the_turns_worktree_is_removed_at_the_end_of_the_turn(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        _record(store, repo, [_done("u1")])
        orch.cmd_merge(_merge_args(store))
        listed = git(repo, "worktree", "list", "--porcelain")
        assert "merge-40" not in listed
        assert not (repo / ".orchestrate").exists() or not list(
            (repo / ".orchestrate").glob("merge-*")
        )

    def test_a_second_turn_is_refused_while_a_merge_is_really_in_flight(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        _record(store, repo, [_done("u1", merge_state="merging", merge_worktree="/somewhere")])
        monkeypatch.setattr(orch, "stale_merge_turn", lambda r, unit, root: False)

        assert orch.cmd_merge(_merge_args(store)) == 1
        assert "u1 holds the merge turn" in capsys.readouterr().out

    def test_a_turn_that_died_is_released_and_the_next_turn_proceeds(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """No expiry and no owner token, so the row MUST be checked against git, never trusted.

        Mutation proof: make ``stale_merge_turn`` always return False -- trusting the row -- and
        this run blocks forever, which is card 992's failure shape in a new place.
        """
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        _record(
            store,
            repo,
            [_done("u1", merge_state="merging", merge_worktree=str(repo / "gone"))],
        )

        assert orch.cmd_merge(_merge_args(store)) == 0
        assert "previous merge turn did not finish" in capsys.readouterr().out
        assert read_record(store, 40)["units"][0]["merge_state"] == "merged"

    def test_a_conflict_leaves_the_unit_ready_and_the_parent_branch_untouched(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        # Make the same file differ on both sides so the merge really conflicts.
        git(repo, "checkout", "parent/40")
        commit_file(repo, "unit.txt", "work from the parent branch\n")
        git(repo, "checkout", "main")
        _record(store, repo, [_done("u1")])
        before = git(repo, "rev-parse", "parent/40")

        code = orch.cmd_merge(_merge_args(store))

        assert code == 1
        assert git(repo, "rev-parse", "parent/40") == before
        assert read_record(store, 40)["units"][0]["merge_state"] == "ready"
        assert "CONFLICT merging" in capsys.readouterr().out


class TestTheMainRegressionGuard:
    def _diverge_main(self, repo: Path, name: str, body: str) -> None:
        advance_remote_main(repo, name, body)

    def test_a_merge_that_would_revert_a_newer_main_file_is_refused_by_name(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        # `origin/main` changes the same file the unit branch changes.
        self._diverge_main(repo, "unit.txt", "the newer main version\n")
        _record(store, repo, [_done("u1")])
        before = git(repo, "rev-parse", "parent/40")

        code = orch.cmd_merge(_merge_args(store))

        out = capsys.readouterr().out
        assert code == 1
        assert "would revert 1 file(s)" in out
        assert "unit.txt" in out
        assert git(repo, "rev-parse", "parent/40") == before

    def test_a_merge_touching_only_other_files_proceeds_though_the_branch_is_behind(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refusing every behind-main merge would make ordinary parallel work unmergeable."""
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        self._diverge_main(repo, "elsewhere.txt", "a file the unit never touches\n")
        _record(store, repo, [_done("u1")])

        assert orch.cmd_merge(_merge_args(store)) == 0
        assert read_record(store, 40)["units"][0]["merge_state"] == "merged"

    def test_a_failed_fetch_refuses_the_turn_rather_than_reading_a_stale_ref(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _record(store, repo, [_done("u1")])
        real = orch.run

        def spy(cmd, **kw):
            if cmd[:2] == ["git", "fetch"]:
                return FakeProc(128, stderr="fatal: could not read from remote repository")
            return real(cmd, **kw)

        monkeypatch.setattr(orch, "run", spy)
        before = git(repo, "rev-parse", "parent/40")

        code = orch.cmd_merge(_merge_args(store))

        out = capsys.readouterr().out
        assert code == 1
        assert "git fetch origin main` failed" in out
        assert "cannot be evaluated against a current ref" in out
        assert git(repo, "rev-parse", "parent/40") == before


class TestWorktreeReleaseAtTheMergeTurn:
    def test_a_merged_units_worktree_is_released_and_its_branch_becomes_deletable(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        worktree = repo.parent / "orch-40-u1"
        git(repo, "worktree", "add", str(worktree), "orch/40-u1")
        _record(store, repo, [_done("u1", worktree=str(worktree))])

        assert orch.cmd_merge(_merge_args(store)) == 0

        assert not worktree.exists()
        assert read_record(store, 40)["units"][0]["worktree"] is None
        git(repo, "branch", "-D", "orch/40-u1")

    def test_release_is_refused_on_a_dirty_worktree_and_names_the_paths(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        worktree = repo.parent / "orch-40-u1"
        git(repo, "worktree", "add", str(worktree), "orch/40-u1")
        (worktree / "scratch.txt").write_text("uncommitted\n")
        _record(store, repo, [_done("u1", worktree=str(worktree))])

        code = orch.cmd_merge(_merge_args(store))

        out = capsys.readouterr().out
        assert "uncommitted changes and would lose them" in out
        assert "scratch.txt" in out
        assert worktree.exists()
        assert code == 3, "cleanup was incomplete, and the exit status says so"

    def test_release_is_refused_when_the_branch_has_unpushed_commits(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        # A remote-tracking ref behind the branch is what "unpushed" means here.
        git(repo, "branch", "origin/orch/40-u1", "parent/40")
        worktree = repo.parent / "orch-40-u1"
        git(repo, "worktree", "add", str(worktree), "orch/40-u1")
        _record(store, repo, [_done("u1", worktree=str(worktree))])

        orch.cmd_merge(_merge_args(store))

        out = capsys.readouterr().out
        assert "not on origin" in out
        assert worktree.exists()


class TestSharedBlockerOwnership:
    def test_a_blocker_owned_by_another_unit_is_reported_not_repaired(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        _record(
            store,
            repo,
            [
                _done(
                    "u1",
                    shared_blockers=[{"blocker_id": "flaky-fixture", "owner_unit": "u2"}],
                )
            ],
        )
        before = git(repo, "rev-parse", "parent/40")

        orch.cmd_merge(_merge_args(store))

        out = capsys.readouterr().out
        assert "'flaky-fixture' is owned by u2" in out
        assert git(repo, "rev-parse", "parent/40") == before

    def test_a_blocker_this_unit_owns_does_not_stop_its_turn(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        _no_fetch(orch, monkeypatch)
        _record(
            store,
            repo,
            [_done("u1", shared_blockers=[{"blocker_id": "b", "owner_unit": "u1"}])],
        )
        assert orch.cmd_merge(_merge_args(store)) == 0
