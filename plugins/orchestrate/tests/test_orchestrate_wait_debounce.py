"""Wait's debounce: idle must persist across consecutive observations before a unit has settled.

An agent is also idle *between* turns -- it finishes a tool call, returns to the prompt, thinks,
and continues. One idle event from herdr once returned ``wait`` in that gap; the session was still
working, with uncommitted paths in its worktree. ``settle`` already required two readings; ``wait``
did not.

The agreement rule is driven through the real wait helpers with a fake event source and a fake
``herdr agent wait`` -- the production module is loaded by path, the way the other orchestrate
tests do. Only herdr itself is canned.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import orchestrate_support as _support
import pytest

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
    spec = importlib.util.spec_from_file_location("_orchestrate_wait_debounce", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _unit(orchestrate: ModuleType, name: str = "alpha", pane_id: str = "p1") -> Any:
    return orchestrate.Unit(
        name=name,
        vendor="claude",
        task="x",
        pane_id=pane_id,
        agent_name=name,
        status=orchestrate.RUNNING,
    )


def _event(pane_id: str, status: str) -> SimpleNamespace:
    return SimpleNamespace(pane_id=pane_id, agent_status=status)


def _write_run(repo: Path, units: list[dict[str, Any]] | None = None, **overrides: Any) -> None:
    """Write this test's run into the per-issue run record (issue #1025).

    There is no `.orchestrate/run.json` any more. The store is derived from the repository rather
    than resolved, because the resolved store is the developer's own `.claude/saga/runs`.
    """
    base = subprocess.run(  # nosec B603 B607 - fixed argv, temporary repository
        ["git", "rev-parse", "HEAD"], cwd=repo, check=False, capture_output=True, text=True
    ).stdout.strip()
    block: dict[str, Any] = {"run_id": "r1", "source": "a test", "base": base, "branch": "orch/r1"}
    block.update(overrides)
    _support.write_record(
        repo.parent / "orch-test-store",
        _support.TEST_ISSUE,
        units=[_support.fill_unit_row(u) for u in (units or [])],
        **block,
    )


def _install_fake_herdr(root: Path) -> Path:
    fake_bin = root / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "herdr"
    fake.write_text(
        "#!" + sys.executable + "\n"
        r"""import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["FAKE_HERDR_LOG"])
with log.open("a") as stream:
    stream.write(json.dumps(args) + "\n")

state_dir = Path(os.environ["FAKE_HERDR_STATE"])


def next_value(name: str, default: str) -> str:
    values = os.environ.get(name, default).split(",")
    counter = state_dir / f"{name}.count"
    index = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(index + 1))
    return values[min(index, len(values) - 1)]


if args[:2] == ["agent", "wait"]:
    timeout_ms = int(args[args.index("--timeout") + 1])
    required = os.environ.get("FAKE_HERDR_REQUIRED_UNTIL", "")
    untils = [args[index + 1] for index, arg in enumerate(args) if arg == "--until"]
    if required and required not in untils:
        time.sleep(timeout_ms / 1000)
        raise SystemExit(2)
    delay = float(next_value("FAKE_HERDR_WAIT_DELAYS", "0"))
    time.sleep(min(delay, timeout_ms / 1000))
    raise SystemExit(int(next_value("FAKE_HERDR_WAIT_EXITS", "0")))

if args[:2] == ["agent", "list"]:
    status = next_value("FAKE_HERDR_STATUSES", "working")
    print(json.dumps({"result": {"agents": [{"name": "alpha", "agent_status": status}]}}))
    raise SystemExit(0)

raise SystemExit(2)
"""
    )
    fake.chmod(0o755)
    return fake_bin


def _run_wait(
    tmp_path: Path,
    *args: str,
    wait_exits: str = "0",
    wait_delays: str = "0",
    statuses: str = "working",
    required_until: str = "",
) -> tuple[subprocess.CompletedProcess[str], float, list[list[str]]]:
    root = tmp_path / "repo"
    root.mkdir()
    _write_run(
        root,
        [
            {
                "name": "alpha",
                "vendor": "claude",
                "task": "test wait",
                "agent_name": "alpha",
                "status": "running",
                "branch": None,
            }
        ],
        run_id="wait-contract",
        base="HEAD",
        branch="",
    )
    fake_bin = _install_fake_herdr(root)
    log = root / "herdr.jsonl"
    state = root / "state"
    state.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "FAKE_HERDR_LOG": str(log),
            "FAKE_HERDR_STATE": str(state),
            "FAKE_HERDR_WAIT_EXITS": wait_exits,
            "FAKE_HERDR_WAIT_DELAYS": wait_delays,
            "FAKE_HERDR_STATUSES": statuses,
            "FAKE_HERDR_REQUIRED_UNTIL": required_until,
        }
    )
    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "wait",
            "--issue",
            str(_support.TEST_ISSUE),
            "--store-root",
            str(root.parent / "orch-test-store"),
            *args,
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=3,
    )
    elapsed = time.monotonic() - started
    calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    return result, elapsed, calls


class PollQueue:
    """One canned status per call, failing loudly if wait looks more often than the test prepared."""

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, _unit: Any) -> str:
        self.calls += 1
        assert self.answers, f"poll asked {self.calls} times -- more than the test queued"
        return self.answers.pop(0)


class TestEventPathRequiresAgreeingObservations:
    """A single idle from the socket is the think-pause, not a settlement."""

    def test_one_idle_does_not_return(self, orchestrate: ModuleType) -> None:
        unit = _unit(orchestrate)
        slept: list[float] = []
        poll = PollQueue(["working"])
        result = orchestrate.wait_on_events(
            {unit.pane_id: unit},
            iter([_event(unit.pane_id, "idle")]),
            interval=20,
            needed=2,
            poll_unit=poll,
            sleep=slept.append,
        )
        assert result is None
        assert slept == [20]
        assert poll.calls == 1

    def test_idle_then_working_does_not_return(self, orchestrate: ModuleType) -> None:
        unit = _unit(orchestrate)
        slept: list[float] = []
        result = orchestrate.wait_on_events(
            {unit.pane_id: unit},
            iter([_event(unit.pane_id, "idle"), _event(unit.pane_id, "working")]),
            interval=20,
            needed=2,
            poll_unit=PollQueue(["working"]),
            sleep=slept.append,
        )
        assert result is None
        assert slept == [20]

    def test_consecutive_agreeing_idles_do_return(self, orchestrate: ModuleType) -> None:
        unit = _unit(orchestrate)
        slept: list[float] = []
        result = orchestrate.wait_on_events(
            {unit.pane_id: unit},
            iter([_event(unit.pane_id, "idle")]),
            interval=20,
            needed=2,
            poll_unit=PollQueue(["idle"]),
            sleep=slept.append,
        )
        assert result is not None
        assert result[0] is unit
        assert result[1] == "idle"
        assert slept == [20]

    def test_blocked_returns_promptly_and_is_named(self, orchestrate: ModuleType) -> None:
        unit = _unit(orchestrate)
        slept: list[float] = []
        poll = PollQueue([])
        result = orchestrate.wait_on_events(
            {unit.pane_id: unit},
            iter([_event(unit.pane_id, "blocked")]),
            interval=20,
            needed=2,
            poll_unit=poll,
            sleep=slept.append,
        )
        assert result is not None
        assert result[1] == "blocked"
        assert slept == []
        assert poll.calls == 0


class TestWaitRejectsSingleObservation:
    """No command or helper path can opt back into the defect."""

    def test_once_is_not_a_wait_flag(self, tmp_path: Path) -> None:
        result, _elapsed, calls = _run_wait(tmp_path, "--once")
        assert result.returncode == 2
        assert "unrecognized arguments: --once" in result.stderr
        assert calls == []

    @pytest.mark.parametrize("value", ["1", "0", "-1"])
    def test_confirmations_below_two_are_rejected(self, tmp_path: Path, value: str) -> None:
        result, _elapsed, calls = _run_wait(tmp_path, "--confirmations", value)
        assert result.returncode == 2
        assert "confirmations must be at least 2" in result.stderr
        assert calls == []

    def test_helper_rejects_one_observation(self, orchestrate: ModuleType) -> None:
        with pytest.raises(ValueError, match="at least two"):
            orchestrate.confirmed_stop(
                "idle",
                lambda: "idle",
                interval=0,
                needed=1,
            )

    def test_fallback_does_not_return_after_one_idle(self, tmp_path: Path) -> None:
        result, _elapsed, calls = _run_wait(
            tmp_path,
            "--timeout",
            "1",
            "--interval",
            "0",
            wait_exits="0,2",
            statuses="idle,working",
        )
        wait_calls = [call for call in calls if call[:2] == ["agent", "wait"]]
        list_calls = [call for call in calls if call[:2] == ["agent", "list"]]
        assert result.returncode == 0
        assert "no unit settled" in result.stdout
        assert len(wait_calls) == 2
        assert len(list_calls) == 2


class TestFallbackProcessContract:
    """The fallback is exercised through the actual child-process boundary."""

    def test_nonzero_child_is_not_respawned_or_polled(self, tmp_path: Path) -> None:
        result, elapsed, calls = _run_wait(
            tmp_path,
            "--timeout",
            "1",
            "--interval",
            "0",
            wait_exits="2",
        )
        wait_calls = [call for call in calls if call[:2] == ["agent", "wait"]]
        list_calls = [call for call in calls if call[:2] == ["agent", "list"]]
        assert result.returncode == 0
        assert len(wait_calls) == 1
        assert list_calls == []
        assert elapsed < 0.75

    def test_restarts_share_one_monotonic_deadline(self, tmp_path: Path) -> None:
        result, elapsed, calls = _run_wait(
            tmp_path,
            "--timeout",
            "1",
            "--interval",
            "0",
            wait_exits="0",
            wait_delays="0.05",
            statuses="working",
        )
        wait_calls = [call for call in calls if call[:2] == ["agent", "wait"]]
        timeout_values = [int(call[call.index("--timeout") + 1]) for call in wait_calls]
        assert result.returncode == 0
        assert "no unit settled" in result.stdout
        assert 0.8 <= elapsed <= 2.0
        assert wait_calls
        assert all(1 <= value <= 1000 for value in timeout_values)
        if len(timeout_values) >= 2:
            assert all(
                earlier > later
                for earlier, later in zip(timeout_values, timeout_values[1:], strict=False)
            )
            assert timeout_values[-1] < timeout_values[0]

    def test_restarts_share_one_monotonic_deadline_under_scheduling_skew(
        self, tmp_path: Path
    ) -> None:
        """Rapid child wakeups / scheduling skew produce >10 wait calls while sharing the deadline."""
        result, elapsed, calls = _run_wait(
            tmp_path,
            "--timeout",
            "1",
            "--interval",
            "0",
            wait_exits="0",
            wait_delays="0",
            statuses="working",
        )
        wait_calls = [call for call in calls if call[:2] == ["agent", "wait"]]
        timeout_values = [int(call[call.index("--timeout") + 1]) for call in wait_calls]
        assert result.returncode == 0
        assert "no unit settled" in result.stdout
        assert 0.8 <= elapsed <= 2.0
        assert len(wait_calls) > 10
        assert all(1 <= value <= 1000 for value in timeout_values)
        if len(timeout_values) >= 2:
            assert all(
                earlier > later
                for earlier, later in zip(timeout_values, timeout_values[1:], strict=False)
            )
            assert timeout_values[-1] < timeout_values[0]

    def test_blocked_is_in_real_wait_argv_and_returns_promptly(self, tmp_path: Path) -> None:
        result, elapsed, calls = _run_wait(
            tmp_path,
            "--timeout",
            "1",
            required_until="blocked",
            statuses="blocked",
        )
        wait_calls = [call for call in calls if call[:2] == ["agent", "wait"]]
        assert result.returncode == 0
        assert "alpha is blocked" in result.stdout
        assert elapsed < 0.75
        assert len(wait_calls) == 1
        assert wait_calls[0][:-1] == [
            "agent",
            "wait",
            "alpha",
            "--until",
            "idle",
            "--until",
            "done",
            "--until",
            "blocked",
            "--timeout",
        ]
