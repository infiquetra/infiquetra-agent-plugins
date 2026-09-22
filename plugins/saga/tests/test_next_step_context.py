"""The suppression rule and the issue resolver behind the continuation hooks (issue #1029).

Every case uses a temporary git repository and a temporary record store. Nothing here touches the
primary checkout's live `.claude/saga/runs` directory.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SAGA_SCRIPTS = ROOT / "plugins" / "saga" / "scripts"

sys.path.insert(0, str(SAGA_SCRIPTS))

import next_step_context  # noqa: E402
import run_record  # noqa: E402


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on branch `issue/1029` with nothing in it."""
    path = tmp_path / "repo"
    path.mkdir()
    _git("init", "-q", "-b", "issue/1029", cwd=path)
    return path


@pytest.fixture
def store(tmp_path: Path) -> Path:
    path = tmp_path / "runs"
    path.mkdir()
    return path


# --------------------------------------------------------------------------------------------
# The suppression rule itself (plan KTD1): an empty `next_step` is the whole signal.
# --------------------------------------------------------------------------------------------


def test_a_live_record_is_announced(repo: Path, store: Path) -> None:
    run_record.set_next_step(store, 1029, "run /work on the plan")
    announcement = next_step_context.next_step_for(repo, store_root=store)
    assert announcement is not None
    assert announcement["issue"] == 1029
    assert announcement["next_step"] == "run /work on the plan"


def test_an_empty_next_step_announces_nothing(repo: Path, store: Path) -> None:
    """The card's motivating case: the step is done, so nothing is said about it."""
    run_record.set_next_step(store, 1029, "run /work on the plan")
    run_record.set_next_step(store, 1029, "")
    assert next_step_context.next_step_for(repo, store_root=store) is None


def test_a_whitespace_next_step_announces_nothing(repo: Path, store: Path) -> None:
    run_record.set_next_step(store, 1029, "   \n ")
    assert next_step_context.next_step_for(repo, store_root=store) is None


def test_no_record_at_all_announces_nothing(repo: Path, store: Path) -> None:
    assert next_step_context.next_step_for(repo, store_root=store) is None


def test_an_unreadable_record_announces_nothing(repo: Path, store: Path) -> None:
    run_record.record_path(store, 1029).write_text("{ not json", encoding="utf-8")
    assert next_step_context.next_step_for(repo, store_root=store) is None


def test_a_record_for_a_different_issue_announces_nothing(repo: Path, store: Path) -> None:
    run_record.set_next_step(store, 4242, "run /work on some other plan")
    assert next_step_context.next_step_for(repo, store_root=store) is None


# --------------------------------------------------------------------------------------------
# Issue resolution (plan KTD2): the active saga first, then the branch name.
# --------------------------------------------------------------------------------------------


def test_the_branch_name_resolves_the_issue(repo: Path) -> None:
    assert next_step_context.issue_from_branch(repo) == 1029


def test_a_slugged_issue_branch_resolves_the_issue(tmp_path: Path) -> None:
    path = tmp_path / "slugged"
    path.mkdir()
    _git("init", "-q", "-b", "issue/1029-continuation-mechanics", cwd=path)
    assert next_step_context.issue_from_branch(path) == 1029


@pytest.mark.parametrize("branch", ["main", "work/cp908-review-integrity", "parent/1018"])
def test_a_branch_that_is_not_issue_shaped_resolves_nothing(tmp_path: Path, branch: str) -> None:
    path = tmp_path / branch.replace("/", "-")
    path.mkdir()
    _git("init", "-q", "-b", branch, cwd=path)
    assert next_step_context.issue_from_branch(path) is None


def test_outside_a_repository_nothing_resolves(tmp_path: Path) -> None:
    assert next_step_context.resolve_issue(tmp_path) is None


def test_the_active_saga_wins_over_the_branch(repo: Path, store: Path, tmp_path: Path) -> None:
    """A saga naming issue 4242 beats a branch named `issue/1029` (the documented order)."""
    import saga

    saga.save(repo, saga.Saga(saga_id="issue-4242", kind="issue", id="4242", next_step="a step"))
    assert next_step_context.resolve_issue(repo) == 4242


# --------------------------------------------------------------------------------------------
# The layering guard (plan KTD2a): `run_record` must not reach for `saga_spore`.
# --------------------------------------------------------------------------------------------


def test_run_record_does_not_import_saga_spore() -> None:
    """The resolver lives in its own module precisely so this cycle cannot close.

    `saga_spore` imports `saga`, and `saga` imports `run_record`. A `run_record` that imported
    `saga_spore` would close the loop `run_record` -> `saga_spore` -> `saga` -> `run_record`, and
    the lazy import in `saga` would hide it at runtime rather than crashing.
    """
    source = (SAGA_SCRIPTS / "run_record.py").read_text(encoding="utf-8")
    assert "saga_spore" not in source


def test_the_rendered_announcement_names_the_step_and_its_record(repo: Path, store: Path) -> None:
    run_record.set_next_step(store, 1029, "run /work on the plan")
    announcement = next_step_context.next_step_for(repo, store_root=store)
    assert announcement is not None
    rendered = next_step_context.render(announcement)
    assert "run /work on the plan" in rendered
    assert str(run_record.record_path(store, 1029)) in rendered
