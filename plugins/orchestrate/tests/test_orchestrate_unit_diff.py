"""What a unit actually changed, measured from the merge base rather than the run branch.

``run-branch..unit-branch`` is the obvious comparison and the wrong one for this question: every
unit in a phase branches from the same base, so the moment a sibling lands, that diff reports the
sibling's additions as this unit's deletions. In the run this was written for it showed a
391-line test file as deleted by a unit that had never touched it. ``diff`` measures from the
merge base -- the newest commit common to the run branch and the unit branch -- so a unit's
change is its own, whoever else has landed since.

The repository is built as the scenario this command exists for: two units off one base, one of
them landed first. The file also carries, from the same unit of work, the regressions for
``start`` rejecting an ordering edge that names a unit in no run -- the check ``expand`` already
had, lifted so both commands share it.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
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
    spec = importlib.util.spec_from_file_location("_orchestrate_unit_diff", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _git_out(cwd: Path, *args: str) -> str:
    got = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return got.stdout.strip()


def _commit(cwd: Path, name: str, body: str | None = None) -> None:
    (cwd / name).write_text(body if body is not None else name + "\n")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", f"add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The scenario this command exists for: two units off one base, one landed first.

    alpha and beta both branch from the run branch at the base commit. alpha lands first; beta
    is still out on its branch. The naive ``orch/r1..orch/r1-beta`` now reports alpha's fifty
    lines as beta's deletions; ``diff`` must report beta's change only.
    """
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "branch", "orch/r1")
    _git(r, "checkout", "-b", "orch/r1-alpha", "orch/r1")
    _commit(r, "alpha.txt", "alpha line\n" * 50)
    _git(r, "checkout", "-b", "orch/r1-beta", "orch/r1")
    _commit(r, "beta.txt")
    _git(r, "checkout", "orch/r1")
    _git(r, "merge", "--no-ff", "--no-edit", "orch/r1-alpha")
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


def _run_diff(
    orchestrate: ModuleType,
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *argv: str,
) -> tuple[int, str]:
    monkeypatch.chdir(repo)
    code: int = orchestrate.main(
        [
            "diff",
            "--issue",
            str(_support.TEST_ISSUE),
            "--store-root",
            str(test_store()),
            *argv,
        ]
    )
    return code, capsys.readouterr().out


def _deletion_lines(out: str) -> list[str]:
    """Patch lines that remove something; ``---`` headers are not among them."""
    return [
        line for line in out.splitlines() if line.startswith("-") and not line.startswith("---")
    ]


class TestTheScenarioThisExistsFor:
    """Two units off one base; alpha landed first. The naive comparison is now poisonous."""

    def test_the_naive_comparison_reports_the_sibling_as_deletions(self, repo: Path) -> None:
        """Ground the defect this command replaces, against the real repository."""
        out = _git_out(repo, "diff", "orch/r1..orch/r1-beta")
        assert "alpha.txt" in out
        assert "deleted file mode" in out

    def test_diff_shows_only_the_units_own_change(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        code, out = _run_diff(orchestrate, repo, monkeypatch, capsys, "beta")
        assert code == 0
        assert "beta.txt" in out
        assert "+beta" in out
        assert "alpha.txt" not in out
        assert "deleted file mode" not in out
        assert _deletion_lines(out) == []

    def test_stat_summarises_instead_of_patching(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        code, out = _run_diff(orchestrate, repo, monkeypatch, capsys, "beta", "--stat")
        assert code == 0
        assert "beta.txt |" in out
        assert "1 file changed" in out
        assert "@@" not in out
        assert "alpha.txt" not in out

    def test_the_merge_base_is_named_in_the_output(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The reader must know WHICH comparison they are looking at -- that ambiguity is the
        entire defect."""
        _write_run(repo, [_unit("alpha"), _unit("beta")])
        code, out = _run_diff(orchestrate, repo, monkeypatch, capsys, "beta")
        assert code == 0
        base = _git_out(repo, "merge-base", "orch/r1", "orch/r1-beta")
        assert "merge base" in out
        assert base[:8] in out


class TestTheWholeRunSummary:
    def test_no_unit_summarises_every_unit_with_a_branch(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _git(repo, "branch", "orch/r1-empty", "orch/r1")
        _write_run(
            repo,
            [
                _unit("alpha"),
                _unit("beta"),
                _unit("empty"),
                _unit("pending", branch=None, status="pending"),
            ],
        )
        code, out = _run_diff(orchestrate, repo, monkeypatch, capsys)
        assert code == 0
        assert "alpha" in out
        assert "beta" in out
        assert "empty" in out
        assert "pending" not in out
        assert "alpha.txt |" in out  # a landed unit still gets its summary
        assert "beta.txt |" in out
        assert "no commits of its own" in out
        assert "@@" not in out  # the summary is stat-only, never a full patch


class TestEmptyShapesSaySoInWords:
    """An empty diff reads as 'this unit changed nothing'; both ways a branch measures empty
    are something else, and each gets words."""

    def test_a_unit_with_no_branch_says_so(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("ghost", branch=None, status="pending")])
        code, out = _run_diff(orchestrate, repo, monkeypatch, capsys, "ghost")
        assert code == 0
        assert "has no branch" in out
        assert "@@" not in out

    def test_a_branch_with_no_commits_of_its_own_says_so(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _git(repo, "branch", "orch/r1-empty", "orch/r1")
        _write_run(repo, [_unit("empty")])
        code, out = _run_diff(orchestrate, repo, monkeypatch, capsys, "empty")
        assert code == 0
        assert "no commits of its own" in out
        assert "@@" not in out

    def test_a_landed_unit_still_shows_its_change(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Its work is on the run branch now; 'no commits of its own' would be a lie."""
        _write_run(repo, [_unit("alpha")])
        code, out = _run_diff(orchestrate, repo, monkeypatch, capsys, "alpha")
        assert code == 0
        assert "landed on orch/r1" in out
        assert "alpha.txt" in out
        assert "+alpha line" in out
        base = _git_out(repo, "rev-parse", "main")
        assert base[:8] in out  # the branch point is still the named comparison
        assert _deletion_lines(out) == []


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a launcher where ``launcher`` will find one.

    ``assert_vendors_available`` resolves the wrapper for real; on a machine without it, start
    fails on the lookup instead of on the check under test. An empty script reads as a wrapper
    with no tools, which the check passes on -- keeping the resolution in the test rather than
    stubbing it out.
    """
    (tmp_path / "agents").write_text("#!/bin/sh\n")
    (tmp_path / "agents").chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)


def _write_plan(repo: Path, units: list[dict[str, Any]], run_id: str = "r2") -> Path:
    path = repo / "plan.json"
    path.write_text(json.dumps({"run_id": run_id, "source": "a test", "units": units}))
    return path


@pytest.mark.usefixtures("launcher_on_path")
class TestStartRejectsUnknownDependencies:
    """A typo in an ordering edge is a unit that is never eligible, forever. ``expand`` always
    caught it; ``start`` -- where the first plan is the most likely place to typo -- did not."""

    def test_an_unknown_after_name_is_rejected_at_start(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(repo)
        plan = _write_plan(
            repo,
            [
                {"name": "alpha", "vendor": "claude", "task": "x"},
                {"name": "beta", "vendor": "claude", "task": "x", "after": ["ghost"]},
            ],
        )
        with pytest.raises(SystemExit, match="waits on 'ghost', which is in no run"):
            orchestrate.cmd_start(NS(plan=str(plan), base=None))
        # nothing written, no branch created -- the refusal happens before any of it
        assert not (test_store() / f"issue-{_support.TEST_ISSUE}.json").exists()
        assert (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", "orch/r2"],
                cwd=repo,
                capture_output=True,
            ).returncode
            != 0
        )

    def test_an_unknown_serialize_name_is_rejected_at_start(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.chdir(repo)
        plan = _write_plan(
            repo,
            [
                {"name": "alpha", "vendor": "claude", "task": "x"},
                {"name": "beta", "vendor": "claude", "task": "x", "serialize": ["ghost"]},
            ],
        )
        with pytest.raises(SystemExit, match="serializes behind 'ghost', which is in no run"):
            orchestrate.cmd_start(NS(plan=str(plan), base=None))
        assert not (test_store() / f"issue-{_support.TEST_ISSUE}.json").exists()

    def test_a_sibling_dependency_is_accepted(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A name pointing at a unit in the same incoming plan is valid -- units routinely
        depend on their siblings."""
        monkeypatch.chdir(repo)
        plan = _write_plan(
            repo,
            [
                {"name": "alpha", "vendor": "claude", "task": "x"},
                {"name": "beta", "vendor": "claude", "task": "x", "after": ["alpha"]},
            ],
        )
        # `start` requires the record and never creates one (issue #1025).
        _support.write_record(test_store(), _support.TEST_ISSUE, units=None)
        assert orchestrate.cmd_start(NS(plan=str(plan), base=None, branch=None)) == 0
        assert [u["name"] for u in _read_run(repo)["units"]] == ["alpha", "beta"]

    def test_a_valid_plan_still_starts(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(repo)
        plan = _write_plan(
            repo,
            [
                {"name": "alpha", "vendor": "claude", "task": "x"},
                {"name": "beta", "vendor": "claude", "task": "x"},
            ],
        )
        # `start` requires the record and never creates one (issue #1025).
        _support.write_record(test_store(), _support.TEST_ISSUE, units=None)
        # `--branch` names the run branch; without it `start` derives `parent/<N>` or
        # `issue/<N>` from the issue's sub-issues (issue #1025), which is not this test's
        # subject -- that a valid plan starts and its branch is created.
        assert orchestrate.cmd_start(NS(plan=str(plan), base=None, branch="orch/r2")) == 0
        assert (test_store() / f"issue-{_support.TEST_ISSUE}.json").exists()
        assert (
            subprocess.run(
                ["git", "rev-parse", "--verify", "--quiet", "orch/r2"],
                cwd=repo,
                capture_output=True,
            ).returncode
            == 0
        )

    def test_expand_still_rejects_an_unknown_name(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The check moved into a shared helper; expand must keep refusing exactly as before."""
        _write_run(repo, [_unit("alpha")])
        plan = _write_plan(
            repo, [{"name": "beta", "vendor": "claude", "task": "x", "after": ["ghost"]}]
        )

        monkeypatch.chdir(repo)
        with pytest.raises(SystemExit, match="waits on 'ghost', which is in no run"):
            orchestrate.cmd_expand(NS(plan=str(plan)))
        assert [u["name"] for u in _read_run(repo)["units"]] == ["alpha"]
