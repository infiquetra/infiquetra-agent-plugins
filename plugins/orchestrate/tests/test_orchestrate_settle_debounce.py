"""Settle's debounce: idle must persist across two readings before a unit is done.

An agent is also idle *between* turns -- it finishes a tool call, returns to the prompt, thinks,
and continues. One instantaneous sample marked a unit done in that gap, which gated `land` and
every dependent unit's launch; the unit had two commits at the time and finished with ten.

Driven against a real git repository and a real run file, the way the command runs in earnest.
Only herdr itself is canned -- one answer per reading -- because the thing under test is how the
readings are taken and combined, not what a live session reports.
"""

from __future__ import annotations

import argparse
import importlib.util
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
    spec = importlib.util.spec_from_file_location("_orchestrate_settle_debounce", SCRIPT)
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
    """A run branch and three unit branches. Settle reads the run file, not the branches."""
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "test@example.com")
    _git(r, "config", "user.name", "Test")
    _commit(r, "base.txt")
    _git(r, "branch", "orch/r1")
    for unit in ("alpha", "beta", "gamma"):
        _git(r, "checkout", "-b", f"orch/r1-{unit}", "orch/r1")
        _commit(r, f"{unit}.txt")
        _git(r, "checkout", "main")
    for unit in ("delta", "epsilon"):
        _git(r, "branch", f"orch/r1-{unit}", "orch/r1")
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


def _read_units(repo: Path) -> dict[str, dict[str, Any]]:
    raw = _support.read_record(test_store(), _support.TEST_ISSUE)
    units: list[dict[str, Any]] = raw["units"]
    return {u["name"]: u for u in units}


def _unit(name: str, **over: Any) -> dict[str, Any]:
    return {
        "name": name,
        "vendor": "claude",
        "task": "x",
        "branch": f"orch/r1-{name}",
        "status": "running",
        **over,
    }


def _agent(name: str, status: str) -> dict[str, str]:
    return {"name": name, "agent_status": status}


class FakeHerdr:
    """Stands in for ``herdr agent list``: one canned answer per call, and it counts the calls.

    Asking for more readings than were given fails the test loudly -- a settle that polled herdr
    once per unit would burn through one canned reading per row.
    """

    def __init__(self, readings: list[list[dict[str, str]]]) -> None:
        self.readings = list(readings)
        self.calls = 0

    def __call__(self) -> list[dict[str, str]]:
        self.calls += 1
        assert self.readings, (
            f"herdr asked {self.calls} times -- expected one call per reading, not per unit"
        )
        return self.readings.pop(0)


def _patch_settle(
    orchestrate: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    readings: list[list[dict[str, str]]],
) -> tuple[FakeHerdr, list[float]]:
    fake = FakeHerdr(readings)
    monkeypatch.setattr(orchestrate, "live_agents", fake)
    slept: list[float] = []
    monkeypatch.setattr(orchestrate.time, "sleep", slept.append)
    return fake, slept


class TestIdleMustPersistAcrossTwoReadings:
    """An agent is idle between turns too, so one sample is not evidence it finished."""

    def test_idle_in_both_readings_is_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha")])
        fake, slept = _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("alpha", "idle")], [_agent("alpha", "idle")]],
        )
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        assert _read_units(repo)["alpha"]["status"] == "done"
        assert slept == [20], "the two readings must be spaced by the interval"
        assert fake.calls == 2
        assert "alpha" in capsys.readouterr().out

    def test_done_in_the_second_reading_counts_the_same_way(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The settle states are idle *or* done; a reading of either confirms a reading of either."""
        _write_run(repo, [_unit("alpha")])
        _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("alpha", "idle")], [_agent("alpha", "done")]],
        )
        monkeypatch.chdir(repo)

        orchestrate.cmd_settle(NS(interval=20, once=False))
        assert _read_units(repo)["alpha"]["status"] == "done"

    def test_idle_then_working_stays_running(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The observed failure shape: settled-looking in the gap between turns, then back at it."""
        _write_run(repo, [_unit("alpha")])
        _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("alpha", "idle")], [_agent("alpha", "working")]],
        )
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        assert _read_units(repo)["alpha"]["status"] == "running"
        out = capsys.readouterr().out
        assert "alpha" in out
        assert "still moving" in out

    def test_gone_in_both_readings_without_commits_is_orphaned(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Absence in one reading may be a herdr hiccup; absence in both without commits is orphaned."""
        _write_run(repo, [_unit("delta")])
        _patch_settle(orchestrate, monkeypatch, [[], []])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        unit = _read_units(repo)["delta"]
        assert unit["status"] == "orphaned"
        assert unit["note"] == "session disappeared without commits"
        out = capsys.readouterr().out
        assert "session gone -> orphaned" in out

    def test_gone_in_both_readings_with_commits_is_done(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A closed session whose branch carries commits settles done, not failed."""
        _write_run(repo, [_unit("alpha")])
        _patch_settle(orchestrate, monkeypatch, [[], []])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        unit = _read_units(repo)["alpha"]
        assert unit["status"] == "done"
        out = capsys.readouterr().out
        assert "session gone with commits -> done" in out

    def test_gone_in_only_one_reading_is_not_failed(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The flip to orphaned needs both readings to agree, exactly like the flip to done."""
        _write_run(repo, [_unit("delta")])
        _patch_settle(orchestrate, monkeypatch, [[_agent("delta", "idle")], []])
        monkeypatch.chdir(repo)

        orchestrate.cmd_settle(NS(interval=20, once=False))
        assert _read_units(repo)["delta"]["status"] == "running"

    def test_a_mixed_run_gets_one_fate_per_unit(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Three units, one settle pass, all three outcomes decided per unit rather than per run."""
        _write_run(repo, [_unit("alpha"), _unit("beta"), _unit("delta")])
        _patch_settle(
            orchestrate,
            monkeypatch,
            [
                [_agent("alpha", "idle"), _agent("beta", "idle")],  # delta absent -> gone
                [_agent("alpha", "idle"), _agent("beta", "working")],
            ],
        )
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        units = _read_units(repo)
        assert units["alpha"]["status"] == "done"
        assert units["beta"]["status"] == "running"
        assert units["delta"]["status"] == "orphaned"


class TestOnceKeepsTheSingleSample:
    """``--once`` is today's behaviour, kept for a caller that wants it."""

    def test_idle_is_done_on_a_single_reading(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha")])
        fake, slept = _patch_settle(orchestrate, monkeypatch, [[_agent("alpha", "idle")]])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=True)) == 0
        assert _read_units(repo)["alpha"]["status"] == "done"
        assert fake.calls == 1
        assert slept == [], "--once must not wait between readings"

    def test_gone_without_commits_is_orphaned_on_a_single_reading(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("delta")])
        fake, slept = _patch_settle(orchestrate, monkeypatch, [[]])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=True)) == 0
        assert _read_units(repo)["delta"]["status"] == "orphaned"
        assert fake.calls == 1
        assert slept == []


class TestOneHerdrCallPerReading:
    """Polling each unit separately costs one round trip a row -- one shared list per reading."""

    def test_every_unit_is_read_off_one_shared_list(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha"), _unit("beta"), _unit("gamma")])
        agents = [_agent("alpha", "idle"), _agent("beta", "idle"), _agent("gamma", "idle")]
        fake, _ = _patch_settle(orchestrate, monkeypatch, [agents, agents])
        monkeypatch.chdir(repo)

        orchestrate.cmd_settle(NS(interval=20, once=False))
        assert fake.calls == 2, "two readings, two herdr calls -- never one per unit"
        units = _read_units(repo)
        assert all(units[name]["status"] == "done" for name in ("alpha", "beta", "gamma"))

    def test_nothing_running_asks_herdr_nothing(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha", status="done"), _unit("beta", status="pending")])
        fake, slept = _patch_settle(orchestrate, monkeypatch, [])
        monkeypatch.chdir(repo)

        assert orchestrate.cmd_settle(NS(interval=20, once=False)) == 0
        assert fake.calls == 0
        assert slept == []


class TestTheCommandLine:
    """The flags go through the real parser, so their defaults are the ones the CLI installs."""

    def test_the_default_interval_is_twenty_seconds(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha")])
        _, slept = _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("alpha", "idle")], [_agent("alpha", "idle")]],
        )
        monkeypatch.chdir(repo)

        assert (
            orchestrate.main(
                [
                    "settle",
                    "--issue",
                    str(_support.TEST_ISSUE),
                    "--store-root",
                    str(test_store()),
                ]
            )
            == 0
        )
        assert slept == [20]

    def test_the_interval_flag_sets_the_gap(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_run(repo, [_unit("alpha")])
        _, slept = _patch_settle(
            orchestrate,
            monkeypatch,
            [[_agent("alpha", "idle")], [_agent("alpha", "idle")]],
        )
        monkeypatch.chdir(repo)

        assert (
            orchestrate.main(
                [
                    "settle",
                    "--issue",
                    str(_support.TEST_ISSUE),
                    "--store-root",
                    str(test_store()),
                    "--interval",
                    "5",
                ]
            )
            == 0
        )
        assert slept == [5]

    def test_the_once_flag_reaches_the_command(
        self,
        orchestrate: ModuleType,
        repo: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:

        _write_run(repo, [_unit("alpha")])
        fake, slept = _patch_settle(orchestrate, monkeypatch, [[_agent("alpha", "idle")]])
        monkeypatch.chdir(repo)

        assert (
            orchestrate.main(
                [
                    "settle",
                    "--issue",
                    str(_support.TEST_ISSUE),
                    "--store-root",
                    str(test_store()),
                    "--once",
                ]
            )
            == 0
        )
        assert _read_units(repo)["alpha"]["status"] == "done"
        assert fake.calls == 1
        assert slept == []
