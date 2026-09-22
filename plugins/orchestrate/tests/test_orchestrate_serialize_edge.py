"""The second ordering edge: ``serialize`` -- "not at the same time", not "I need your output".

``after`` was the only ordering primitive, and it was overloaded: operators also used it to mean
"do not run at the same time as that unit, because we would both touch the same files" or "wait
until that has landed so I can rebase on it". A run using it the second way looked blocked for a
reason that does not exist, and a reader could not tell the two apart.

``serialize`` gates launch exactly like ``after`` -- a unit is not eligible until every name in
both lists is done -- but it claims nothing about needing the dependency's output, and ``status``
says which kind of wait holds a unit. Eligibility is exercised on the run record directly; ``go``,
``status`` and ``expand`` are driven against a run file on disk the way an operator meets them.
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
    spec = importlib.util.spec_from_file_location("_orchestrate_serialize_edge", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put a launcher where ``agent_argv`` will find one.

    ``expand`` resolves the wrapper for real before it accepts anything, so on a machine without
    it the acceptance tests die on the lookup instead of on the thing under test. A stub script
    that prints no tool list makes the vendor check pass without asserting anything about agents.
    """
    (tmp_path / "agents").write_text("#!/bin/sh\n")
    (tmp_path / "agents").chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=os.pathsep)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _commit(cwd: Path, name: str) -> None:
    (cwd / name).write_text(name + "\n")
    _git(cwd, "add", name)
    _git(cwd, "commit", "-m", f"add {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A run branch to base unit worktrees on; ``go`` creates them with real git."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "branch", "orch/r1")
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


def _read_run(cwd: Path) -> dict[str, Any]:
    """The record in the shape the old run file was read in (issue #1025)."""
    raw = _support.read_record(test_store(), _support.TEST_ISSUE)
    return {**raw["orchestrate"], "units": raw["units"]}


def _unit(name: str, **over: Any) -> dict[str, Any]:
    unit: dict[str, Any] = {"name": name, "vendor": "claude", "task": "x", "status": "pending"}
    unit.update(over)
    return unit


def _run(orchestrate: ModuleType, *units: Any) -> Any:
    return orchestrate.Run(run_id="r1", source="a test", base="0" * 40, units=list(units))


class TestSerializeGatesLaunchLikeAfter:
    """A unit is not eligible until every name in BOTH ``after`` and ``serialize`` is done."""

    def test_a_serialize_only_unit_is_held_while_its_dependency_is_pending(
        self, orchestrate: ModuleType
    ) -> None:
        run = _run(
            orchestrate,
            orchestrate.Unit(name="alpha", vendor="claude", task="x"),
            orchestrate.Unit(name="beta", vendor="claude", task="x", serialize=["alpha"]),
        )
        # alpha carries no edges and is free to go; only the serialized unit is held
        assert [u.name for u in run.eligible()] == ["alpha"]

    def test_a_serialize_only_unit_is_released_once_its_dependency_is_done(
        self, orchestrate: ModuleType
    ) -> None:
        run = _run(
            orchestrate,
            orchestrate.Unit(name="alpha", vendor="claude", task="x", status=orchestrate.DONE),
            orchestrate.Unit(name="beta", vendor="claude", task="x", serialize=["alpha"]),
        )
        assert [u.name for u in run.eligible()] == ["beta"]

    def test_a_running_serialize_dependency_still_holds(self, orchestrate: ModuleType) -> None:
        """Done is the only state that opens the edge -- in flight is still running beside it."""
        run = _run(
            orchestrate,
            orchestrate.Unit(name="alpha", vendor="claude", task="x", status=orchestrate.RUNNING),
            orchestrate.Unit(name="beta", vendor="claude", task="x", serialize=["alpha"]),
        )
        assert run.eligible() == []

    def test_an_unmet_after_edge_holds_even_when_serialize_is_met(
        self, orchestrate: ModuleType
    ) -> None:
        run = _run(
            orchestrate,
            orchestrate.Unit(name="alpha", vendor="claude", task="x"),
            orchestrate.Unit(name="gamma", vendor="claude", task="x", status=orchestrate.DONE),
            orchestrate.Unit(
                name="beta", vendor="claude", task="x", after=["alpha"], serialize=["gamma"]
            ),
        )
        # alpha is edgeless and free to go; beta is held by its unmet after edge
        assert [u.name for u in run.eligible()] == ["alpha"]

    def test_an_unmet_serialize_edge_holds_even_when_after_is_met(
        self, orchestrate: ModuleType
    ) -> None:
        run = _run(
            orchestrate,
            orchestrate.Unit(name="alpha", vendor="claude", task="x", status=orchestrate.DONE),
            orchestrate.Unit(name="gamma", vendor="claude", task="x"),
            orchestrate.Unit(
                name="beta", vendor="claude", task="x", after=["alpha"], serialize=["gamma"]
            ),
        )
        # gamma is edgeless and free to go; beta is held by its unmet serialize edge
        assert [u.name for u in run.eligible()] == ["gamma"]

    def test_both_edges_met_releases_the_unit(self, orchestrate: ModuleType) -> None:
        run = _run(
            orchestrate,
            orchestrate.Unit(name="alpha", vendor="claude", task="x", status=orchestrate.DONE),
            orchestrate.Unit(name="gamma", vendor="claude", task="x", status=orchestrate.DONE),
            orchestrate.Unit(
                name="beta", vendor="claude", task="x", after=["alpha"], serialize=["gamma"]
            ),
        )
        assert [u.name for u in run.eligible()] == ["beta"]


class TestGoHonoursSerializeEdges:
    """The gate is ``eligible``; these prove ``go`` stands on it end to end."""

    def test_a_serialize_only_unit_is_not_launched_while_its_dependency_is_pending(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # alpha running and beta serialized behind it: nothing in the run is eligible
        _write_run(
            repo,
            [_unit("alpha", status="running"), _unit("beta", serialize=["alpha"])],
        )
        monkeypatch.chdir(repo)
        launched: list[str] = []

        def fake_launch(
            unit: Any, backend: str = "inline", *, review_elsewhere: bool = False
        ) -> None:
            launched.append(unit.name)

        monkeypatch.setattr(orchestrate, "launch", fake_launch)
        assert orchestrate.cmd_go(NS(limit=0)) == 0

        assert launched == []
        assert "nothing eligible" in capsys.readouterr().out

    def test_a_serialize_only_unit_is_launched_once_its_dependency_is_done(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _git(repo, "checkout", "-b", "orch/r1-alpha", "orch/r1")
        _commit(repo, "alpha.txt")
        _git(repo, "checkout", "main")
        _write_run(
            repo,
            [
                _unit("alpha", status="done", branch="orch/r1-alpha"),
                _unit("beta", serialize=["alpha"]),
            ],
        )
        monkeypatch.chdir(repo)
        launched: list[str] = []

        def fake_launch(
            unit: Any, backend: str = "inline", *, review_elsewhere: bool = False
        ) -> None:
            launched.append(unit.name)

        monkeypatch.setattr(orchestrate, "launch", fake_launch)
        assert orchestrate.cmd_go(NS(limit=0)) == 0

        assert launched == ["beta"]

    def test_a_serialize_dependency_that_committed_nothing_still_releases(
        self, orchestrate: ModuleType, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``after`` skips a dependency that produced nothing; ``serialize`` claims no output."""
        # the branch exists but sits at the run branch -- the session finished and saved nothing
        _git(repo, "branch", "orch/r1-alpha", "orch/r1")
        _write_run(
            repo,
            [
                _unit("alpha", status="done", branch="orch/r1-alpha"),
                _unit("beta", serialize=["alpha"]),
            ],
        )
        monkeypatch.chdir(repo)
        launched: list[str] = []

        def fake_launch(
            unit: Any, backend: str = "inline", *, review_elsewhere: bool = False
        ) -> None:
            launched.append(unit.name)

        monkeypatch.setattr(orchestrate, "launch", fake_launch)
        assert orchestrate.cmd_go(NS(limit=0)) == 0

        assert launched == ["beta"]


class TestStatusNamesTheKindOfWait:
    """A blocked unit used to read as plain ``pending`` -- now the table says what holds it."""

    def test_a_unit_held_by_after_says_whose_output_it_needs(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(tmp_path, [_unit("alpha"), _unit("beta", after=["alpha"])], base="0" * 40)
        monkeypatch.chdir(tmp_path)
        assert orchestrate.cmd_status(NS()) == 0

        assert "needs output from alpha" in capsys.readouterr().out

    def test_a_unit_held_by_serialize_says_what_it_waits_behind(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(tmp_path, [_unit("alpha"), _unit("beta", serialize=["alpha"])], base="0" * 40)
        monkeypatch.chdir(tmp_path)
        assert orchestrate.cmd_status(NS()) == 0

        out = capsys.readouterr().out
        assert "serialized behind alpha" in out
        assert "needs output from" not in out

    def test_a_unit_held_by_both_edges_shows_both_waits(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(
            tmp_path,
            [
                _unit("alpha"),
                _unit("gamma"),
                _unit("beta", after=["alpha"], serialize=["gamma"]),
            ],
            base="0" * 40,
        )
        monkeypatch.chdir(tmp_path)
        assert orchestrate.cmd_status(NS()) == 0

        line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("beta"))
        assert "needs output from alpha" in line
        assert "serialized behind gamma" in line

    def test_an_eligible_unit_is_not_reported_as_waiting(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A satisfied edge is no wait at all -- the row keeps its task and carries no reason."""
        _write_run(
            tmp_path,
            [_unit("alpha", status="done"), _unit("beta", serialize=["alpha"])],
            base="0" * 40,
        )
        monkeypatch.chdir(tmp_path)
        assert orchestrate.cmd_status(NS()) == 0

        out = capsys.readouterr().out
        assert "serialized behind" not in out
        assert "needs output from" not in out


class TestExpandRejectsUnknownSerializeTargets:
    """The same guarantee ``after`` already has: a name in no run cannot hold a unit."""

    def test_an_unknown_serialize_target_is_rejected(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(tmp_path, [_unit("alpha")], base="0" * 40)
        plan = tmp_path / "phase2.json"
        plan.write_text(json.dumps({"units": [_unit("beta", serialize=["ghost"])]}))
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit, match="serializes behind 'ghost'"):
            orchestrate.cmd_expand(NS(plan=str(plan)))

    def test_an_unknown_after_target_is_still_rejected(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(tmp_path, [_unit("alpha")], base="0" * 40)
        plan = tmp_path / "phase2.json"
        plan.write_text(json.dumps({"units": [_unit("beta", after=["ghost"])]}))
        monkeypatch.chdir(tmp_path)

        with pytest.raises(SystemExit, match="waits on 'ghost'"):
            orchestrate.cmd_expand(NS(plan=str(plan)))

    @pytest.mark.usefixtures("launcher_on_path")
    def test_a_serialize_target_already_in_the_run_is_accepted(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _write_run(tmp_path, [_unit("alpha", status="done")], base="0" * 40)
        plan = tmp_path / "phase2.json"
        plan.write_text(json.dumps({"units": [_unit("beta", serialize=["alpha"])]}))
        monkeypatch.chdir(tmp_path)

        assert orchestrate.cmd_expand(NS(plan=str(plan))) == 0
        units = {u["name"]: u for u in _read_run(tmp_path)["units"]}
        assert units["beta"]["serialize"] == ["alpha"]

    @pytest.mark.usefixtures("launcher_on_path")
    def test_a_serialize_target_among_the_new_units_is_accepted(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """New rows may serialize behind each other, exactly as they may with ``after``."""
        _write_run(tmp_path, [_unit("alpha")], base="0" * 40)
        plan = tmp_path / "phase2.json"
        plan.write_text(json.dumps({"units": [_unit("beta", serialize=["gamma"]), _unit("gamma")]}))
        monkeypatch.chdir(tmp_path)

        assert orchestrate.cmd_expand(NS(plan=str(plan))) == 0
        assert "added 2" in capsys.readouterr().out


class TestRunFilesFromBeforeTheField:
    """``serialize`` saved and loaded alongside ``after`` -- never instead of it."""

    def test_a_run_file_without_the_field_loads_with_empty_edges(
        self, orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A run started before the field existed keeps working, and keeps gating correctly."""
        # A record whose unit rows predate the field: neither row carries `serialize`.
        _support.write_record(
            test_store(),
            _support.TEST_ISSUE,
            units=[
                {"name": "alpha", "vendor": "claude", "task": "x", "status": "done"},
                {"name": "beta", "vendor": "claude", "task": "x", "after": ["alpha"]},
            ],
            run_id="r1",
            source="a test",
            base="0" * 40,
            branch="orch/r1",
        )
        monkeypatch.chdir(tmp_path)

        run = orchestrate.Run.load(_support.TEST_ISSUE, test_store())
        assert run.unit("alpha").serialize == []
        assert run.unit("beta").serialize == []
        assert run.unit("beta").after == ["alpha"]
        assert [u.name for u in run.eligible()] == ["beta"]

    def test_save_writes_serialize_alongside_after(
        self, orchestrate: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        run = orchestrate.Run(
            run_id="r1",
            source="a test",
            base="0" * 40,
            units=[
                orchestrate.Unit(
                    name="beta",
                    vendor="claude",
                    task="x",
                    after=["alpha"],
                    serialize=["gamma"],
                )
            ],
        )
        _support.attach_record(run, test_store())

        run.save()

        raw = _read_run(tmp_path)
        assert raw["units"][0]["after"] == ["alpha"]
        assert raw["units"][0]["serialize"] == ["gamma"]
