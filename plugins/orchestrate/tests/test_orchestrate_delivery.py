"""Delivery confirmation and bounded retry on task dispatch.

When Orchestrate launches a unit, Herdr may report the session interactive_ready while a startup
dialog (folder trust, account verification) is still displayed. A prompt sent in that window is
silently swallowed. Orchestrate must observe an acceptance signal (took_the_task) before marking
the unit RUNNING. If unaccepted and the session remains continuously idle, it retries delivery up to
2 times. If still unaccepted, it records the named state prompt_undelivered with a loud failure note,
and never records the unit as RUNNING.
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
    spec = importlib.util.spec_from_file_location("_orchestrate_delivery", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def launcher_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    launcher = tmp_path / "agents"
    launcher.write_text("#!/bin/sh\n")
    launcher.chmod(0o755)
    monkeypatch.setenv("ORCHESTRATE_AGENT_LAUNCHER", str(launcher))


def _completed_launch_process(
    tab_id: str = "tab-1", agent_name: str = "worker", pane_id: str = "pane-1"
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        ["agents"],
        returncode=0,
        stdout=f'{{"tab_id":"{tab_id}","agent_name":"{agent_name}","pane_id":"{pane_id}"}}\n',
        stderr="",
    )


def _idle_agent(name: str) -> dict[str, str]:
    """A live session sitting at its prompt -- the reading settle must not mistake for finished."""
    return {"name": name, "agent_status": "idle"}


@pytest.mark.usefixtures("launcher_on_path")
class TestDispatchDeliveryConfirmation:
    def test_ready_pane_that_swallows_prompt_is_marked_prompt_undelivered_after_two_resends(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ready-reporting pane whose startup dialog swallows prompts must not be marked RUNNING.

        It must attempt 2 bounded resends while continuously idle, then transition to the named
        prompt_undelivered state with DELIVERY_WARNING appended.
        """
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #123")
        send_calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            orchestrate, "run", lambda *_args, **_kwargs: _completed_launch_process()
        )
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "send",
            lambda u, p, b="inline", **kw: send_calls.append((u, p, b, kw)),
        )
        monkeypatch.setattr(
            orchestrate,
            "agent_row",
            lambda _unit=None, _agents=None, **_kw: {
                "pane_id": "pane-1",
                "agent_status": "idle",
                "agent": "claude",
                "interactive_ready": True,
            },
        )
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: False)

        orchestrate.launch(unit)

        assert unit.status == orchestrate.PROMPT_UNDELIVERED
        assert unit.status == "prompt_undelivered"
        assert unit.status != orchestrate.RUNNING
        # 1 initial send + 2 resends = 3 sends total
        assert len(send_calls) == 3
        assert orchestrate.DELIVERY_WARNING in unit.note

    def test_resend_is_attempted_only_while_session_has_never_left_idle(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resends are skipped if the session left idle (e.g. status became done or non-idle)."""
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #123")
        send_calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            orchestrate, "run", lambda *_args, **_kwargs: _completed_launch_process()
        )
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "send",
            lambda u, p, b="inline", **kw: send_calls.append((u, p, b, kw)),
        )
        # Session left idle to 'done' before any retry
        monkeypatch.setattr(
            orchestrate,
            "agent_row",
            lambda _unit=None, _agents=None, **_kw: {
                "pane_id": "pane-1",
                "agent_status": "done",
                "agent": "claude",
                "interactive_ready": True,
            },
        )
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: False)

        orchestrate.launch(unit)

        assert unit.status == orchestrate.PROMPT_UNDELIVERED
        # Only the initial send occurred, 0 resends because session is not idle
        assert len(send_calls) == 1

    def test_resend_is_skipped_once_the_session_has_started_working(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The case the guard exists for: a session already working must never be tasked twice.

        ``took_the_task`` samples once a second, so a session that accepted the prompt and began
        work between two samples can still be reported unaccepted. Resending then would hand the
        unit its task a second time, which is the exact harm the idle guard prevents.
        """
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #123")
        send_calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            orchestrate, "run", lambda *_args, **_kwargs: _completed_launch_process()
        )
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "send",
            lambda u, p, b="inline", **kw: send_calls.append((u, p, b, kw)),
        )
        monkeypatch.setattr(
            orchestrate,
            "agent_row",
            lambda _unit=None, _agents=None, **_kw: {
                "pane_id": "pane-1",
                "agent_status": "working",
                "agent": "claude",
                "interactive_ready": True,
            },
        )
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: False)

        orchestrate.launch(unit)

        assert len(send_calls) == 1
        assert unit.status == orchestrate.PROMPT_UNDELIVERED

    def test_resend_is_skipped_when_pane_is_missing(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Resends are skipped if agent_row returns None."""
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #123")
        send_calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            orchestrate, "run", lambda *_args, **_kwargs: _completed_launch_process()
        )
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "send",
            lambda u, p, b="inline", **kw: send_calls.append((u, p, b, kw)),
        )
        rows: list[dict[str, Any] | None] = [
            {"pane_id": "pane-1", "agent": "claude", "interactive_ready": True},
            None,
        ]
        monkeypatch.setattr(
            orchestrate,
            "agent_row",
            lambda _unit, _agents=None: rows.pop(0) if rows else None,
        )
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: False)

        orchestrate.launch(unit)

        assert unit.status == orchestrate.PROMPT_UNDELIVERED
        assert len(send_calls) == 1

    def test_happy_path_prompt_accepted_on_first_send(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the prompt is accepted on first send, unit is RUNNING with no retries or warnings."""
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #123")
        send_calls: list[tuple[Any, ...]] = []

        monkeypatch.setattr(
            orchestrate, "run", lambda *_args, **_kwargs: _completed_launch_process()
        )
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "send",
            lambda u, p, b="inline", **kw: send_calls.append((u, p, b, kw)),
        )
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "agent_row",
            lambda _unit=None, _agents=None, **_kw: {
                "pane_id": "pane-1",
                "agent": "claude",
                "interactive_ready": True,
            },
        )

        orchestrate.launch(unit)

        assert unit.status == orchestrate.RUNNING
        assert unit.status == "running"
        assert len(send_calls) == 1
        assert orchestrate.DELIVERY_WARNING not in unit.note

    def test_happy_path_prompt_accepted_on_resend(
        self, orchestrate: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When initial send fails but 1st resend is accepted, unit is RUNNING with 1 resend."""
        unit = orchestrate.Unit(name="worker", vendor="claude", task="/plan #123")
        send_calls: list[tuple[Any, ...]] = []
        acceptance_results = iter([False, True])

        monkeypatch.setattr(
            orchestrate, "run", lambda *_args, **_kwargs: _completed_launch_process()
        )
        monkeypatch.setattr(orchestrate, "await_ready", lambda _unit: True)
        monkeypatch.setattr(
            orchestrate,
            "send",
            lambda u, p, b="inline", **kw: send_calls.append((u, p, b, kw)),
        )
        monkeypatch.setattr(
            orchestrate,
            "agent_row",
            lambda _unit=None, _agents=None, **_kw: {
                "pane_id": "pane-1",
                "agent_status": "idle",
                "agent": "claude",
                "interactive_ready": True,
            },
        )
        monkeypatch.setattr(orchestrate, "took_the_task", lambda _unit: next(acceptance_results))

        orchestrate.launch(unit)

        assert unit.status == orchestrate.RUNNING
        assert len(send_calls) == 2  # 1 initial + 1 resend
        assert orchestrate.DELIVERY_WARNING not in unit.note


class TestStatusCommandShowsNamedDeliveryFailureState:
    def test_status_renders_prompt_undelivered(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """cmd_status displays prompt_undelivered under the state column for unaccepted units."""
        monkeypatch.chdir(tmp_path)
        unit = orchestrate.Unit(
            name="alpha",
            vendor="claude",
            task="do something",
            status=orchestrate.PROMPT_UNDELIVERED,
            note=orchestrate.DELIVERY_WARNING,
        )
        run_record = orchestrate.Run(
            run_id="test-run",
            source="issue 779",
            base="0" * 40,
            units=[unit],
        )

        # `Run.load` takes the issue and the store now (issue #1025); the stub stands in for
        # the record read, which is not what either of these tests is about.
        monkeypatch.setattr(orchestrate.Run, "load", lambda *_a, **_kw: run_record)
        monkeypatch.setattr(orchestrate, "unit_commit_statuses", lambda _units, _r: [("-", "-")])

        rc = orchestrate.cmd_status(NS())
        assert rc == 0
        captured = capsys.readouterr().out
        assert "prompt_undelivered" in captured
        assert "alpha" in captured
        # Ensure it is not displayed as running
        lines = [line for line in captured.splitlines() if "alpha" in line]
        assert len(lines) == 1
        assert "prompt_undelivered" in lines[0]
        assert "running" not in lines[0].split()


class TestSettleNeverSweepsAnUndeliveredUnit:
    """The silent-success path the named state closes.

    Before the named state, an undelivered unit sat in RUNNING and idle, which ``settle`` read as
    a finished turn and marked done -- so the run reported success and only ``land`` discovered,
    a phase later, that the branch was empty. ``settle`` reads RUNNING units only, and this pins
    that: the next unit in this lane rewrites settlement, and nothing else stops it from taking an
    undelivered unit back into the sweep.
    """

    def test_settle_leaves_a_prompt_undelivered_unit_alone(
        self,
        orchestrate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        unit = orchestrate.Unit(
            name="alpha",
            vendor="claude",
            task="do something",
            status=orchestrate.PROMPT_UNDELIVERED,
            note=orchestrate.DELIVERY_WARNING,
        )
        run_record = _support.attach_record(
            orchestrate.Run(
                run_id="test-run",
                source="issue 779",
                base="0" * 40,
                units=[unit],
            ),
            test_store(),
        )
        # `Run.load` takes the issue and the store now (issue #1025); the stub stands in for
        # the record read, which is not what either of these tests is about.
        monkeypatch.setattr(orchestrate.Run, "load", lambda *_a, **_kw: run_record)
        # An undelivered unit's session is alive and idle -- exactly the reading that used to be
        # taken for a finished turn.
        monkeypatch.setattr(
            orchestrate, "live_agents", lambda *_args, **_kwargs: [_idle_agent("alpha")]
        )

        monkeypatch.setattr(orchestrate.time, "sleep", lambda _seconds: None)

        rc = orchestrate.cmd_settle(NS(once=False, interval=0))

        assert rc == 0
        assert unit.status == orchestrate.PROMPT_UNDELIVERED
        assert unit.status != orchestrate.DONE
        assert orchestrate.DELIVERY_WARNING in unit.note
        assert "alpha" not in capsys.readouterr().out
