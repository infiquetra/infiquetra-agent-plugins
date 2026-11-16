"""Wait's debounce: idle must persist across consecutive observations before a unit has settled.

An agent is also idle *between* turns -- it finishes a tool call, returns to the prompt, thinks,
and continues. One idle event from old Herdr once returned ``wait`` in that gap; the session was
still working, with uncommitted paths in its worktree. ``settle`` already required two readings;
``wait`` did not.

``wait`` now starts one ``hc wait`` per running unit (herdr core returns from it when a session
stops working, which is a wake, not a settlement). The agreement rule is driven through the real
helpers and through the real child-process boundary with a fake ``hc`` on ``PATH`` -- the
production module is loaded by path, the way the other orchestrate tests do. Only hc is canned.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType
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


def _unit(orchestrate: ModuleType, name: str = "alpha", pane_id: str = "t1") -> Any:
    return orchestrate.Unit(
        name=name,
        vendor="claude",
        task="x",
        pane_id=pane_id,
        agent_name=name,
        status=orchestrate.RUNNING,
    )


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


def _install_fake_hc(root: Path) -> Path:
    fake_bin = root / "bin"
    fake_bin.mkdir()
    fake = fake_bin / "hc"
    fake.write_text(
        "#!" + sys.executable + "\n"
        r"""import json
import os
import sys
import time
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["FAKE_HC_LOG"])
with log.open("a") as stream:
    stream.write(json.dumps({"argv": args, "caller": os.environ.get("HC_TERMINAL_ID")}) + "\n")

state_dir = Path(os.environ["FAKE_HC_STATE"])


def next_value(name: str, default: str) -> str:
    values = os.environ.get(name, default).split(",")
    counter = state_dir / f"{name}.count"
    index = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(index + 1))
    return values[min(index, len(values) - 1)]


if args[:1] == ["wait"]:
    timeout = float(args[args.index("--timeout") + 1])
    delay = float(next_value("FAKE_HC_WAIT_DELAYS", "0"))
    time.sleep(min(delay, timeout))
    code = int(next_value("FAKE_HC_WAIT_EXITS", "0"))
    if code == 0:
        print(json.dumps({"children": [], "ended": True, "reason": "status", "status": "idle",
                          "terminal": args[1], "turn": 1}))
    raise SystemExit(code)

if args[:1] == ["ls"]:
    status = next_value("FAKE_HC_STATUSES", "working")
    rows = [] if status == "gone" else [
        {"address": "t1", "agent": "claude-code", "cwd": "/repo", "state": "live",
         "status": status, "turn": 1, "where": "Run / alpha"}
    ]
    print(json.dumps({"terminals": rows, "machines": [], "hidden_finished": 0}))
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
    pane_id: str = "t1",
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
                "pane_id": pane_id,
                "tab_id": pane_id,
                "status": "running",
                "branch": None,
            }
        ],
        run_id="wait-contract",
        base="HEAD",
        branch="",
    )
    fake_bin = _install_fake_hc(root)
    log = root / "hc.jsonl"
    state = root / "state"
    state.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "FAKE_HC_LOG": str(log),
            "FAKE_HC_STATE": str(state),
            "FAKE_HC_WAIT_EXITS": wait_exits,
            "FAKE_HC_WAIT_DELAYS": wait_delays,
            "FAKE_HC_STATUSES": statuses,
            # The operator's own session: the wait children must not carry it (D5).
            "HC_TERMINAL_ID": "t99",
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
    entries = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
    calls = [entry["argv"] for entry in entries]
    assert all(entry["caller"] is None for entry in entries), "an hc call carried HC_TERMINAL_ID"
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


class TestAWakeRequiresAgreeingObservations:
    """A single idle after ``hc wait`` returns is the think-pause, not a settlement."""

    def test_one_idle_does_not_return(self, orchestrate: ModuleType) -> None:
        slept: list[float] = []
        poll = PollQueue(["working"])
        result = orchestrate.confirmed_stop(
            "idle", lambda: poll(None), interval=20, needed=2, sleep=slept.append
        )
        assert result is None
        assert slept == [20]
        assert poll.calls == 1

    def test_consecutive_agreeing_idles_do_return(self, orchestrate: ModuleType) -> None:
        slept: list[float] = []
        result = orchestrate.confirmed_stop(
            "idle", lambda: PollQueue(["idle"])(None), interval=20, needed=2, sleep=slept.append
        )
        assert result == "idle"
        assert slept == [20]

    @pytest.mark.parametrize("status", ["blocked", "error"])
    def test_a_person_needed_status_returns_promptly_and_is_named(
        self, orchestrate: ModuleType, status: str
    ) -> None:
        """hc returns from a wait on ``error`` as well as ``blocked``; both need a person."""
        slept: list[float] = []
        poll = PollQueue([])
        result = orchestrate.confirmed_stop(
            status, lambda: poll(None), interval=20, needed=2, sleep=slept.append
        )
        assert result == status
        assert slept == []
        assert poll.calls == 0

    def test_error_seen_while_confirming_is_named(self, orchestrate: ModuleType) -> None:
        result = orchestrate.confirmed_stop(
            "idle", lambda: "error", interval=0, needed=2, sleep=lambda _s: None
        )
        assert result == "error"


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

    def test_wait_does_not_return_after_one_idle(self, tmp_path: Path) -> None:
        result, _elapsed, calls = _run_wait(
            tmp_path,
            "--timeout",
            "1",
            "--interval",
            "0",
            wait_exits="0,2",
            statuses="idle,working",
        )
        wait_calls = [call for call in calls if call[:1] == ["wait"]]
        list_calls = [call for call in calls if call[:1] == ["ls"]]
        assert result.returncode == 0
        assert "no unit settled" in result.stdout
        assert len(wait_calls) == 2
        assert len(list_calls) == 2


class TestHcWaitProcessContract:
    """The ``hc wait`` children are exercised through the actual child-process boundary."""

    def test_nonzero_child_is_not_respawned_or_polled(self, tmp_path: Path) -> None:
        result, elapsed, calls = _run_wait(
            tmp_path,
            "--timeout",
            "1",
            "--interval",
            "0",
            wait_exits="2",
        )
        wait_calls = [call for call in calls if call[:1] == ["wait"]]
        list_calls = [call for call in calls if call[:1] == ["ls"]]
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
        wait_calls = [call for call in calls if call[:1] == ["wait"]]
        timeout_values = [float(call[call.index("--timeout") + 1]) for call in wait_calls]
        assert result.returncode == 0
        assert "no unit settled" in result.stdout
        assert 0.8 <= elapsed <= 2.0
        assert wait_calls
        assert all(0.001 <= value <= 1.0 for value in timeout_values)
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
        wait_calls = [call for call in calls if call[:1] == ["wait"]]
        timeout_values = [float(call[call.index("--timeout") + 1]) for call in wait_calls]
        assert result.returncode == 0
        assert "no unit settled" in result.stdout
        assert 0.8 <= elapsed <= 2.0
        assert len(wait_calls) > 10
        assert all(0.001 <= value <= 1.0 for value in timeout_values)
        if len(timeout_values) >= 2:
            assert all(
                earlier > later
                for earlier, later in zip(timeout_values, timeout_values[1:], strict=False)
            )
            assert timeout_values[-1] < timeout_values[0]

    def test_blocked_returns_promptly_with_the_real_wait_argv(self, tmp_path: Path) -> None:
        result, elapsed, calls = _run_wait(tmp_path, "--timeout", "1", statuses="blocked")
        wait_calls = [call for call in calls if call[:1] == ["wait"]]
        assert result.returncode == 0
        assert "alpha is blocked" in result.stdout
        assert elapsed < 0.75
        assert len(wait_calls) == 1
        assert wait_calls[0][:3] == ["wait", "t1", "--timeout"]
        assert wait_calls[0][-1] == "--json"

    def test_error_returns_promptly_and_is_named(self, tmp_path: Path) -> None:
        result, elapsed, calls = _run_wait(tmp_path, "--timeout", "1", statuses="error")
        assert result.returncode == 0
        assert "alpha reports an error" in result.stdout
        assert elapsed < 0.75
        assert len([call for call in calls if call[:1] == ["wait"]]) == 1

    def test_a_unit_hc_no_longer_lists_is_dropped_not_waited_on_again(
        self, tmp_path: Path
    ) -> None:
        """hc returns at once from a wait on an exited terminal; re-waiting would spin."""
        result, elapsed, calls = _run_wait(
            tmp_path, "--timeout", "1", "--interval", "0", statuses="gone"
        )
        assert result.returncode == 0
        assert "no unit settled" in result.stdout
        assert len([call for call in calls if call[:1] == ["wait"]]) == 1
        assert elapsed < 0.75

    def test_an_old_herdr_unit_is_named_and_not_waited_on(self, tmp_path: Path) -> None:
        result, _elapsed, calls = _run_wait(tmp_path, "--timeout", "1", pane_id="w1:p3")
        assert result.returncode == 0
        assert "records no herdr core terminal (w1:p3)" in result.stdout
        assert "no running unit has a herdr core terminal" in result.stdout
        assert calls == []
