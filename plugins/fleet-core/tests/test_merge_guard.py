"""Tests for merge_guard — the one implementation of the never-revert-a-newer-branch refusal.

Two jobs. The first is the guard's own behaviour, driven against real git in a temporary
repository so the merge-base arithmetic is the real thing rather than a mock's opinion of it. The
second is the equivalence check: the orchestrate driver keeps its own copy of these two functions
on purpose — ``orchestrate.py`` documents at its resolver why it must not take a resolution
dependency on another plugin for something it needs when that plugin is absent, and a safety guard
is exactly the thing that must not depend on an install. Two copies of a safety rule is how one of
them stops matching the other, so this drives BOTH through one case table.

Nothing here touches a live repository: every scenario builds its own under ``tmp_path``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FLEET_COMMONS = REPO_ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons"
def _load(path: Path, name: str) -> ModuleType:
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


GUARD = _load(FLEET_COMMONS / "merge_guard.py", "merge_guard")


def _git(cwd: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *argv], capture_output=True, text=True, check=True
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with `main` and a `side` branch that diverged from it."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "shared.txt").write_text("base\n")
    (root / "mine.txt").write_text("base\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "base")
    _git(root, "branch", "side")
    return root


def _commit(root: Path, name: str, body: str, message: str) -> str:
    (root / name).write_text(body)
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


class TestRegressionFiles:
    def test_a_merge_that_contains_the_comparison_reverts_nothing(self, repo: Path) -> None:
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()
        assert GUARD.regression_files(head, "main", cwd=str(repo)) == []

    def test_a_file_the_comparison_changed_and_the_merge_touches_is_named(self, repo: Path) -> None:
        _git(repo, "checkout", "side")
        _commit(repo, "shared.txt", "side edit\n", "side touches shared")
        side = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "main")
        _commit(repo, "shared.txt", "main edit\n", "main touches shared")
        assert GUARD.regression_files(side, "main", cwd=str(repo)) == ["shared.txt"]

    def test_a_branch_merely_behind_the_comparison_is_not_refused(self, repo: Path) -> None:
        _git(repo, "checkout", "side")
        side = _commit(repo, "mine.txt", "side edit\n", "side touches its own file")
        _git(repo, "checkout", "main")
        _commit(repo, "shared.txt", "main edit\n", "main moves on")
        assert GUARD.regression_files(side, "main", cwd=str(repo)) == []

    def test_the_refusal_names_every_file(self) -> None:
        line = GUARD.refusal_for(["a.py", "b.py"], branch="work", compare_ref="origin/main")
        assert "a.py" in line and "b.py" in line
        assert "work" in line and "origin/main" in line
        assert "2 file(s)" in line


class TestFetchComparisonBranch:
    def test_a_successful_fetch_returns_no_refusal(self) -> None:
        runner = lambda argv, **kw: SimpleNamespace(returncode=0, stdout="", stderr="")  # noqa: E731
        assert GUARD.fetch_comparison_branch("origin", "main", runner=runner) is None

    def test_a_failed_fetch_refuses_and_says_which_guard_it_blocks(self) -> None:
        runner = lambda argv, **kw: SimpleNamespace(  # noqa: E731
            returncode=128, stdout="", stderr="fatal: could not read from remote\n"
        )
        refusal = GUARD.fetch_comparison_branch("origin", "main", runner=runner)
        assert refusal is not None
        assert "git fetch origin main" in refusal
        assert "could not read from remote" in refusal
        assert "reverting a newer main" in refusal
        assert "refused" in refusal
