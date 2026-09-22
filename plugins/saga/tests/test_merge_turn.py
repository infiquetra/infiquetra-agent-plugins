"""Tests for merge_turn — one worker merges at a time, over the run record (issue 1028).

Every scenario builds its own git repository and its own store root under ``tmp_path``. Nothing
here reads or writes the primary checkout's live ``.claude/saga/`` store, and nothing merges a
branch that exists outside the temporary repository: several card drivers share this machine.

The four properties under test are the four the plan names — only the holder merges, the
destination follows the record, a merge that would revert a newer comparison branch is refused BY
NAME, and both re-integrations happen and are reported separately.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MT = _load("merge_turn")
RR = _load("run_record")


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *argv], capture_output=True, text=True, check=True
    )


def _commit(root: Path, name: str, body: str, message: str) -> str:
    (root / name).write_text(body)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with `main`, a parent branch, and two unit branches off the parent.

    A real ``origin`` remote is wired to a bare clone so the guard's fetch is a real fetch rather
    than a mock: the whole point of the fetch-first rule is that it runs against a live remote.
    """
    origin = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        capture_output=True,
        check=True,
    )
    root = tmp_path / "work"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "shared.txt").write_text("base\n")
    (root / "one.txt").write_text("base\n")
    (root / "two.txt").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-u", "origin", "main")
    _git(root, "branch", "parent/1")
    _git(root, "checkout", "parent/1")
    _git(root, "branch", "unit-a")
    _git(root, "branch", "unit-b")
    _git(root, "checkout", "main")
    return root


def _record(store: Path, *, destination: str = "pr", units: list[dict] | None = None):
    record = RR.RunRecord(
        issue=1028,
        repo="infiquetra/infiquetra-claude-plugins",
        admission={
            **RR.empty_admission(),
            "answers": {"destination": {"value": destination, "source": "operator"}},
        },
        units=units if units is not None else [],
    )
    RR.save(store, record)
    return RR.load(store, 1028, warn=None)


def _unit(name: str, branch: str, **extra) -> dict:
    return {"name": name, "branch": branch, "merge_state": MT.MERGE_READY, **extra}


class TestOnlyTheHolderMerges:
    def test_a_non_holder_is_refused_and_the_holder_is_named(
        self, repo: Path, tmp_path: Path
    ) -> None:
        live = tmp_path / "live-turn"
        live.mkdir()
        # A live turn: a directory that exists AND reports an unfinished merge.
        record = _record(
            tmp_path / "store",
            units=[
                _unit("unit-a", "unit-a", merge_state=MT.MERGE_MERGING, merge_worktree=str(live)),
                _unit("unit-b", "unit-b"),
            ],
        )
        runner = _FakeRunner({("rev-parse", "--verify", "--quiet", "MERGE_HEAD"): 0})
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.take_turn(record, "unit-b", runner=runner)
        assert "unit-a holds the merge turn" in str(caught.value)
        assert str(live) in str(caught.value)

    def test_a_turn_whose_worktree_is_gone_is_released_not_trusted(
        self, repo: Path, tmp_path: Path
    ) -> None:
        record = _record(
            tmp_path / "store",
            units=[
                _unit(
                    "unit-a",
                    "unit-a",
                    merge_state=MT.MERGE_MERGING,
                    merge_worktree=str(tmp_path / "gone"),
                ),
                _unit("unit-b", "unit-b"),
            ],
        )
        result = MT.take_turn(record, "unit-b")
        assert result["released"] == ["unit-a"]
        assert record.units[0]["merge_state"] == MT.MERGE_READY
        assert record.units[1]["merge_state"] == MT.MERGE_MERGING

    def test_a_directory_with_no_unfinished_merge_is_not_a_live_turn(self, tmp_path: Path) -> None:
        here = tmp_path / "stale"
        here.mkdir()
        runner = _FakeRunner({("rev-parse", "--verify", "--quiet", "MERGE_HEAD"): 1})
        assert MT.turn_is_live({"merge_worktree": str(here)}, runner=runner) is False


class _FakeRunner:
    """Answers git by the tail of its argv, so a test can say "MERGE_HEAD resolves" and no more."""

    def __init__(self, answers: dict[tuple[str, ...], int]) -> None:
        self.answers = answers

    def __call__(self, argv, **kwargs):  # type: ignore[no-untyped-def]
        from types import SimpleNamespace

        for suffix, code in self.answers.items():
            if tuple(argv[-len(suffix) :]) == suffix:
                return SimpleNamespace(returncode=code, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="")


class TestTheDestinationFollowsTheRecord:
    def test_a_pr_destination_merges_onto_the_parent_branch(self, tmp_path: Path) -> None:
        record = _record(tmp_path / "store", destination="pr")
        assert (
            MT.destination_branch(record, parent_branch="parent/1", default_branch="main")
            == "parent/1"
        )

    def test_a_run_with_no_parent_branch_merges_onto_the_default_branch(
        self, tmp_path: Path
    ) -> None:
        record = _record(tmp_path / "store", destination="merge")
        assert MT.destination_branch(record, parent_branch="", default_branch="main") == "main"

    def test_plan_only_merges_nothing_and_says_so(self, tmp_path: Path) -> None:
        record = _record(tmp_path / "store", destination="plan-only")
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.destination_branch(record, parent_branch="parent/1", default_branch="main")
        assert "merges nothing" in str(caught.value)

    def test_an_unknown_destination_is_refused_with_the_known_ones(self, tmp_path: Path) -> None:
        record = _record(tmp_path / "store", destination="somewhere-else")
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.destination_branch(record, parent_branch="parent/1", default_branch="main")
        assert "unknown destination 'somewhere-else'" in str(caught.value)
        assert "plan-only" in str(caught.value)


class TestTheMerge:
    def test_a_clean_merge_advances_the_destination_and_records_the_tip(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "checkout", "unit-a")
        _commit(repo, "one.txt", "unit a\n", "unit a works")
        _git(repo, "checkout", "main")
        store = tmp_path / "store"
        record = _record(store, units=[_unit("unit-a", "unit-a"), _unit("unit-b", "unit-b")])
        result = MT.merge_unit(
            record,
            "unit-a",
            repo_root=repo,
            parent_branch="parent/1",
            worktree_root=tmp_path / "turns",
        )
        assert result["destination"] == "parent/1"
        assert record.units[0]["merge_state"] == MT.MERGE_MERGED
        assert record.units[0]["merged_tip"] == result["merged_tip"]
        landed = _git(repo, "rev-parse", "parent/1").stdout.strip()
        assert landed == result["merged_tip"]
        assert "unit a" in _git(repo, "show", "parent/1:one.txt").stdout

    def test_a_conflicting_merge_leaves_the_destination_untouched_and_releases_the_turn(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "checkout", "parent/1")
        _commit(repo, "shared.txt", "parent edit\n", "parent touches shared")
        _git(repo, "checkout", "unit-a")
        _commit(repo, "shared.txt", "unit edit\n", "unit touches shared")
        _git(repo, "checkout", "main")
        before = _git(repo, "rev-parse", "parent/1").stdout.strip()
        record = _record(tmp_path / "store", units=[_unit("unit-a", "unit-a")])
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.merge_unit(
                record,
                "unit-a",
                repo_root=repo,
                parent_branch="parent/1",
                worktree_root=tmp_path / "turns",
            )
        assert "CONFLICT merging unit-a onto parent/1" in str(caught.value)
        assert _git(repo, "rev-parse", "parent/1").stdout.strip() == before
        assert record.units[0]["merge_state"] == MT.MERGE_READY
        assert record.units[0]["merge_worktree"] is None

    def test_a_merge_that_would_revert_a_newer_main_file_is_refused_by_name(
        self, repo: Path, tmp_path: Path
    ) -> None:
        # main moves on, touching shared.txt; the unit branch touched the same file earlier.
        _git(repo, "checkout", "unit-a")
        _commit(repo, "shared.txt", "unit edit\n", "unit touches shared")
        _git(repo, "checkout", "main")
        _commit(repo, "shared.txt", "newer main\n", "main touches shared")
        _git(repo, "push", "origin", "main")
        before = _git(repo, "rev-parse", "parent/1").stdout.strip()
        record = _record(tmp_path / "store", units=[_unit("unit-a", "unit-a")])
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.merge_unit(
                record,
                "unit-a",
                repo_root=repo,
                parent_branch="parent/1",
                worktree_root=tmp_path / "turns",
            )
        message = str(caught.value)
        assert "shared.txt" in message
        assert "backwards relative to origin/main" in message
        assert _git(repo, "rev-parse", "parent/1").stdout.strip() == before
        assert record.units[0]["merge_state"] == MT.MERGE_READY

    def test_a_failed_fetch_refuses_the_turn_before_any_merge(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "remote", "set-url", "origin", str(tmp_path / "does-not-exist.git"))
        record = _record(tmp_path / "store", units=[_unit("unit-a", "unit-a")])
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.merge_unit(
                record,
                "unit-a",
                repo_root=repo,
                parent_branch="parent/1",
                worktree_root=tmp_path / "turns",
            )
        assert "git fetch origin main" in str(caught.value)
        assert "this merge turn is refused" in str(caught.value)
        assert record.units[0]["merge_state"] == MT.MERGE_READY

    def test_a_unit_with_no_branch_is_refused(self, repo: Path, tmp_path: Path) -> None:
        record = _record(tmp_path / "store", units=[_unit("unit-a", "")])
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.merge_unit(record, "unit-a", repo_root=repo, parent_branch="parent/1")
        assert "records no branch" in str(caught.value)

    def test_an_unknown_unit_is_refused_with_the_names_the_record_carries(
        self, repo: Path, tmp_path: Path
    ) -> None:
        record = _record(tmp_path / "store", units=[_unit("unit-a", "unit-a")])
        with pytest.raises(MT.MergeTurnError) as caught:
            MT.find_unit(record, "unit-z")
        assert "no unit named 'unit-z'" in str(caught.value)
        assert "unit-a" in str(caught.value)


class TestBothReintegrations:
    def test_a_surviving_branch_that_can_fast_forward_is_advanced(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "checkout", "unit-a")
        _commit(repo, "one.txt", "unit a\n", "unit a works")
        _git(repo, "checkout", "main")
        record = _record(
            tmp_path / "store", units=[_unit("unit-a", "unit-a"), _unit("unit-b", "unit-b")]
        )
        result = MT.merge_unit(
            record,
            "unit-a",
            repo_root=repo,
            parent_branch="parent/1",
            worktree_root=tmp_path / "turns",
        )
        rows = result["reintegration"]["into_unit_branches"]
        assert [row["branch"] for row in rows] == ["unit-b"]
        assert rows[0]["status"] == "fast-forwarded"
        assert _git(repo, "rev-parse", "unit-b").stdout.strip() == result["merged_tip"]

    def test_a_surviving_branch_with_its_own_commits_is_reported_pending_not_forced(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "checkout", "unit-a")
        _commit(repo, "one.txt", "unit a\n", "unit a works")
        _git(repo, "checkout", "unit-b")
        b_tip = _commit(repo, "two.txt", "unit b\n", "unit b works")
        _git(repo, "checkout", "main")
        record = _record(
            tmp_path / "store", units=[_unit("unit-a", "unit-a"), _unit("unit-b", "unit-b")]
        )
        result = MT.merge_unit(
            record,
            "unit-a",
            repo_root=repo,
            parent_branch="parent/1",
            worktree_root=tmp_path / "turns",
        )
        row = result["reintegration"]["into_unit_branches"][0]
        assert row["status"] == "pending"
        assert "needs a real merge by the worker who owns it" in row["detail"]
        assert _git(repo, "rev-parse", "unit-b").stdout.strip() == b_tip

    def test_the_comparison_branch_reaches_the_parent_branch_and_is_reported_separately(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "checkout", "unit-a")
        _commit(repo, "one.txt", "unit a\n", "unit a works")
        _git(repo, "checkout", "main")
        _commit(repo, "two.txt", "newer main\n", "main moves on")
        _git(repo, "push", "origin", "main")
        record = _record(tmp_path / "store", units=[_unit("unit-a", "unit-a")])
        result = MT.merge_unit(
            record,
            "unit-a",
            repo_root=repo,
            parent_branch="parent/1",
            worktree_root=tmp_path / "turns",
        )
        parent_row = result["reintegration"]["into_parent_branch"]
        assert parent_row["branch"] == "parent/1"
        assert parent_row["status"] == "pending"
        assert "origin/main" in parent_row["from"]

    def test_merging_onto_the_default_branch_skips_the_parent_reintegration_with_a_reason(
        self, repo: Path, tmp_path: Path
    ) -> None:
        _git(repo, "checkout", "unit-a")
        _commit(repo, "one.txt", "unit a\n", "unit a works")
        _git(repo, "checkout", "parent/1")
        record = _record(tmp_path / "store", destination="merge", units=[_unit("unit-a", "unit-a")])
        result = MT.merge_unit(
            record,
            "unit-a",
            repo_root=repo,
            parent_branch="",
            worktree_root=tmp_path / "turns",
        )
        parent_row = result["reintegration"]["into_parent_branch"]
        assert parent_row["status"] == "skipped"
        assert "there is nothing to re-integrate into it" in parent_row["detail"]


class TestNoLock:
    def test_the_module_introduces_no_lock_lease_reservation_or_receipt(self) -> None:
        """Card 1028's stop condition, as a guard rather than a promise in a document."""
        source = (SCRIPTS / "merge_turn.py").read_text(encoding="utf-8")
        body = "\n".join(
            line for line in source.splitlines() if not line.strip().startswith(("#", "*"))
        )
        lowered = body.lower()
        for forbidden in ("flock", "lockfile", "acquire_lock", "lease_id", "reservation_id"):
            assert forbidden not in lowered, f"merge_turn must not grow a {forbidden}"


class TestCommandLine:
    def test_the_dry_run_prints_the_turn_and_changes_nothing(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store = tmp_path / "store"
        _record(store, units=[_unit("unit-a", "unit-a")])
        before = (store / "issue-1028.json").read_text(encoding="utf-8")
        code = MT.main(
            [
                "--record",
                str(store / "issue-1028.json"),
                "--repo-root",
                str(repo),
                "--parent-branch",
                "parent/1",
                "merge",
                "--unit",
                "unit-a",
                "--dry-run",
            ]
        )
        assert code == 0
        printed = json.loads(capsys.readouterr().out)
        assert printed["destination"] == "parent/1"
        assert printed["compare_ref"] == "origin/main"
        assert (store / "issue-1028.json").read_text(encoding="utf-8") == before

    def test_a_refusal_is_one_line_on_stderr_and_exit_2(
        self, repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store = tmp_path / "store"
        _record(store, units=[_unit("unit-a", "unit-a")])
        code = MT.main(
            [
                "--record",
                str(store / "issue-1028.json"),
                "--repo-root",
                str(repo),
                "merge",
                "--unit",
                "unit-z",
                "--dry-run",
            ]
        )
        assert code == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("merge_turn: ")
        assert len(captured.err.strip().splitlines()) == 1
