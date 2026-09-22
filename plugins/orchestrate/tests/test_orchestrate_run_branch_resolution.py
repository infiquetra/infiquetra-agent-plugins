"""Resolve a run branch once, without turning a missing branch into false Git answers.

The tests use real repositories because the contract is about refs, merge bases, and merge
parentage. Only Herdr and agent launch are replaced where a command would otherwise leave Git.
"""

from __future__ import annotations

import argparse
import importlib.util
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
    spec = importlib.util.spec_from_file_location("_orchestrate_run_branch_resolution", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _git_out(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, path: str) -> None:
    (repo / path).write_text(f"{path}\n")
    _git(repo, "add", path)
    _git(repo, "commit", "-m", f"write {path}")


def _repo(tmp_path: Path, names: tuple[str, ...], *, landed: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "base.txt")
    _git(repo, "branch", "orch/r1")
    for name in names:
        branch = f"orch/r1-{name}"
        _git(repo, "checkout", "-b", branch, "orch/r1")
        _commit(repo, f"{name}.txt")
        _git(repo, "checkout", "main")
    if landed:
        _git(repo, "checkout", "orch/r1")
        for name in names:
            _git(repo, "merge", "--no-ff", "--no-edit", f"orch/r1-{name}")
        _git(repo, "checkout", "main")
    return repo


def _unit(name: str, **overrides: Any) -> dict[str, Any]:
    return {
        "name": name,
        "vendor": "claude",
        "task": f"implement {name}",
        "branch": f"orch/r1-{name}",
        "status": "done",
        **overrides,
    }


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


def _rename_run_branch(repo: Path) -> None:
    _git(repo, "branch", "-m", "orch/r1", "orch/r1-renamed")


def test_load_resolves_the_run_branch_once_and_predicates_reuse_it(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path, ("alpha",))
    _write_run(repo, [_unit("alpha")])
    monkeypatch.chdir(repo)
    original = orchestrate.resolve_ref
    resolved: list[str] = []

    def counting_resolve(ref: str) -> str | None:
        if ref == "orch/r1":
            resolved.append(ref)
        return cast(str | None, original(ref))

    monkeypatch.setattr(orchestrate, "resolve_ref", counting_resolve)
    loaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())

    assert loaded.branch_state == orchestrate.RunBranchState(
        "orch/r1", _git_out(repo, "rev-parse", "orch/r1")
    )
    assert orchestrate.branch_produced_anything("orch/r1-alpha", loaded) is True
    assert orchestrate.landed_by_merge("orch/r1-alpha", loaded) is False
    assert resolved == ["orch/r1"]


def test_check_names_a_renamed_run_branch_without_false_no_commit_findings(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    names = ("alpha", "beta", "gamma", "delta")
    repo = _repo(tmp_path, names)
    _write_run(repo, [_unit(name) for name in names])
    _rename_run_branch(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(orchestrate, "live_agents", lambda: [])

    assert orchestrate.cmd_check(NS()) == 1

    output = capsys.readouterr().out
    assert "run branch 'orch/r1' does not resolve" in output
    assert "NO COMMITS" not in output
    for name in names:
        assert f"NO COMMITS {name}" not in output


def test_go_reports_the_missing_branch_before_evaluating_a_dependency(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, ("alpha",))
    _write_run(
        repo,
        [
            _unit("alpha"),
            _unit("beta", branch=None, status="pending", after=["alpha"]),
        ],
    )
    _rename_run_branch(repo)
    monkeypatch.chdir(repo)

    with pytest.raises(SystemExit, match=r"orch/r1.*does not resolve.*cannot go"):
        orchestrate.cmd_go(NS(limit=0))

    assert "committed nothing" not in capsys.readouterr().out


def test_go_refuses_a_missing_run_branch_even_when_no_unit_is_eligible(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, ("alpha",))
    _write_run(repo, [_unit("alpha")])
    _rename_run_branch(repo)
    monkeypatch.chdir(repo)

    with pytest.raises(SystemExit, match=r"orch/r1.*does not resolve.*cannot go"):
        orchestrate.cmd_go(NS(limit=0))

    assert "nothing eligible" not in capsys.readouterr().out


@pytest.mark.parametrize(
    ("command", "args", "expected"),
    [
        ("status", {}, 0),
        ("check", {}, 1),
        ("clean", {"merged": True, "branches": False}, 0),
    ],
)
def test_diagnostic_commands_still_run_and_name_an_unresolvable_branch(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    command: str,
    args: dict[str, object],
    expected: int,
) -> None:
    repo = _repo(tmp_path, ("alpha",))
    _write_run(repo, [_unit("alpha")])
    _rename_run_branch(repo)
    monkeypatch.chdir(repo)
    monkeypatch.setattr(orchestrate, "live_agents", lambda: [])

    result = getattr(orchestrate, f"cmd_{command}")(NS(**args))

    output = capsys.readouterr().out
    assert result == expected
    assert "run branch 'orch/r1' does not resolve" in output
    if command == "clean":
        assert "closed: nothing" in output
        assert "alpha" in output.split("kept", 1)[1]


@pytest.mark.parametrize("command", ["merge", "go"])
def test_land_and_go_refuse_an_unresolvable_run_branch(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    repo = _repo(tmp_path, ("alpha",))
    units = [_unit("alpha", branch=None, status="pending")] if command == "go" else [_unit("alpha")]
    _write_run(repo, units)
    _rename_run_branch(repo)
    monkeypatch.chdir(repo)
    args = NS(clean=False) if command == "merge" else NS(limit=0)

    with pytest.raises(SystemExit, match=rf"orch/r1.*does not resolve.*cannot {command}"):
        getattr(orchestrate, f"cmd_{command}")(args)


def test_resolvable_run_branch_keeps_existing_command_behaviour(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, ("alpha",), landed=True)
    _write_run(repo, [_unit("alpha")])
    monkeypatch.chdir(repo)
    monkeypatch.setattr(orchestrate, "live_agents", lambda: [])

    assert orchestrate.cmd_status(NS()) == 0
    assert "alpha" in capsys.readouterr().out
    assert orchestrate.cmd_check(NS()) == 0
    assert "the record agrees with the repository" in capsys.readouterr().out
    assert orchestrate.cmd_merge(NS(clean=False)) == 0
    assert "already there: alpha" in capsys.readouterr().out
    assert orchestrate.cmd_go(NS(limit=0)) == 0
    assert "nothing eligible" in capsys.readouterr().out
    assert orchestrate.cmd_clean(NS(merged=True, branches=False, all=False)) == 0
    output = capsys.readouterr().out
    assert "closed: alpha" in output
    assert "does not resolve" not in output


def test_legacy_record_without_a_branch_keeps_the_head_based_go_path(
    orchestrate: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = _repo(tmp_path, ("alpha",))
    _write_run(
        repo,
        [
            _unit("alpha"),
            _unit("beta", branch=None, status="pending", after=["alpha"]),
        ],
        branch="",
    )

    monkeypatch.chdir(repo)
    loaded = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
    launched: list[str] = []

    assert loaded.branch == ""
    assert loaded.branch_state is None
    assert orchestrate.produced_anything(loaded.unit("alpha"), loaded) is True

    monkeypatch.setattr(orchestrate, "make_worktree", lambda *_args, **_kwargs: None)

    def fake_launch(unit: Any, backend: str = "inline", *, review_elsewhere: bool = False) -> None:
        launched.append(unit.name)
        unit.status = "running"

    monkeypatch.setattr(orchestrate, "launch", fake_launch)
    assert orchestrate.cmd_go(NS(limit=0)) == 0

    output = capsys.readouterr().out
    assert launched == ["beta"]
    assert "does not resolve" not in output
    assert "committed nothing" not in output
    # The message moved with the command: `land` is `merge`, and a run with no parent
    # branch is told `start` creates one (issue #1025).
    with pytest.raises(SystemExit, match=r"no parent branch"):
        orchestrate.cmd_merge(NS(clean=False))
