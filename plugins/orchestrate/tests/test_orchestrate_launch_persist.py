"""The launch is persisted immediately, and the width number bounds it (issue #1025, U3).

Cards 900 and 990 asked for a durable claim written before launch. This card forbids one: parent
issue 1018 rules out a new lease, reservation, receipt or ledger, and says to stop and report if a
child needs one to pass its own tests. It does not. Writing the row as ``running`` *before* calling
the launcher is enough, because eligibility reads only ``pending`` units.

Card 901 asked for a real concurrency ceiling separate from ``--limit``. The ceiling is the run
record's ``concurrency_allocation``, and it counts open role panes as well as running units,
because a role session is an agent session and the number exists for the account's rate limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orchestrate_support import (
    args,
    git,
    load_orchestrate,
    make_repo,
    read_record,
    unit_row,
    write_record,
)

#: The production driver this module drives. Constructed here, not imported from the shared
#: helper, so the module names on its own face the real file it crosses into.
ORCHESTRATE_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "plugins"
    / "orchestrate"
    / "skills"
    / "orchestrate"
    / "scripts"
    / "orchestrate.py"
)


@pytest.fixture(scope="module")
def orch():
    return load_orchestrate("_orchestrate_launch_persist", ORCHESTRATE_SCRIPT)


@pytest.fixture
def bed(orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A repository, a store, and a driver whose launcher and herdr reads are fakes."""
    repo = make_repo(tmp_path, branch="issue/20")
    monkeypatch.chdir(repo)
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
    monkeypatch.setattr(orch, "assert_review_transport", lambda units: None)
    monkeypatch.setattr(orch, "live_agents", lambda **kw: [])
    monkeypatch.setattr(orch, "append_unit_note", _append_note)
    return repo, store


def _append_note(unit, text: str) -> None:
    unit.note = f"{unit.note}; {text}" if unit.note else text


def _write(store: Path, repo: Path, issue: int, units, **block):
    return write_record(
        store,
        issue,
        units=units,
        base=git(repo, "rev-parse", "main"),
        branch=f"issue/{issue}",
        run_id=str(issue),
        **block,
    )


class TestRepeatedGoLaunchesOnce:
    def test_a_second_go_after_the_first_persisted_does_not_launch_again(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _write(store, repo, 20, [unit_row("u1", branch="orch/20-u1")])
        launches: list[str] = []

        def fake_launch(unit, backend, **kw):
            launches.append(unit.name)
            unit.tab_id = "ws:tab-1"
            unit.pane_id = "ws:pane-1"
            unit.agent_name = unit.name

        monkeypatch.setattr(orch, "launch", fake_launch)

        assert orch.cmd_go(args(20, store, limit=0)) == 0
        assert launches == ["u1"]
        assert read_record(store, 20)["units"][0]["status"] == "running"

        assert orch.cmd_go(args(20, store, limit=0)) == 0
        assert launches == ["u1"], "the second call must not launch the unit again"
        assert "nothing eligible" in capsys.readouterr().out

    def test_the_row_is_written_running_before_the_launcher_is_called(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """This is the whole mechanism: the persist happens first, not after delivery."""
        repo, store = bed
        _write(store, repo, 20, [unit_row("u1", branch="orch/20-u1")])
        seen: list[str] = []

        def fake_launch(unit, backend, **kw):
            seen.append(read_record(store, 20)["units"][0]["status"])
            unit.tab_id = "ws:tab-1"

        monkeypatch.setattr(orch, "launch", fake_launch)
        orch.cmd_go(args(20, store, limit=0))
        assert seen == ["running"]
        assert read_record(store, 20)["units"][0]["launch_started_at"]


class TestTheInterruptWindow:
    def test_a_keyboard_interrupt_after_the_identity_exists_leaves_it_on_disk(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Card 990: a KeyboardInterrupt is a BaseException, which neither except clause caught."""
        repo, store = bed
        _write(store, repo, 20, [unit_row("u1", branch="orch/20-u1")])

        def interrupted_launch(unit, backend, **kw):
            unit.tab_id = "ws:tab-9"
            unit.pane_id = "ws:pane-9"
            unit.agent_name = "u1-2"
            raise KeyboardInterrupt

        monkeypatch.setattr(orch, "launch", interrupted_launch)
        with pytest.raises(KeyboardInterrupt):
            orch.cmd_go(args(20, store, limit=0))

        row = read_record(store, 20)["units"][0]
        assert row["tab_id"] == "ws:tab-9"
        assert row["pane_id"] == "ws:pane-9"
        assert row["agent_name"] == "u1-2"

    def test_a_unit_with_a_recorded_tab_is_never_relaunched(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        _write(
            store,
            repo,
            20,
            [unit_row("u1", branch="orch/20-u1", status="pending", tab_id="ws:tab-9")],
        )
        monkeypatch.setattr(
            orch, "launch", lambda *a, **k: pytest.fail("a unit with a tab was relaunched")
        )
        assert orch.cmd_go(args(20, store, limit=0)) == 0
        assert "already has tab ws:tab-9" in capsys.readouterr().out

    def test_a_launcher_failure_returns_the_unit_to_pending_and_names_it(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        _write(store, repo, 20, [unit_row("u1", branch="orch/20-u1")])

        def failing_launch(unit, backend, **kw):
            raise orch.StagedInputError("the composer holds staged input")

        monkeypatch.setattr(orch, "launch", failing_launch)
        orch.cmd_go(args(20, store, limit=0))
        row = read_record(store, 20)["units"][0]
        assert row["status"] == "pending"
        assert "staged input" in row["note"]


class TestTheWidthNumberBoundsLaunches:
    def _many(self, count: int) -> list[dict]:
        return [unit_row(f"u{i}", branch=f"orch/20-u{i}") for i in range(1, count + 1)]

    def test_three_go_calls_with_width_two_never_exceed_two_live_units(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        _write(store, repo, 20, self._many(5))
        record = read_record(store, 20)
        record["run_configuration"]["concurrency_allocation"]["value"] = 2
        (store / "issue-20.json").write_text(__import__("json").dumps(record))

        def fake_launch(unit, backend, **kw):
            unit.tab_id = f"ws:tab-{unit.name}"

        monkeypatch.setattr(orch, "launch", fake_launch)
        for _ in range(3):
            orch.cmd_go(args(20, store, limit=0))
            live = [u for u in read_record(store, 20)["units"] if u["status"] == "running"]
            assert len(live) <= 2, f"width 2 exceeded: {[u['name'] for u in live]}"

    def test_limit_slices_one_call_and_the_next_call_launches_the_rest(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        _write(store, repo, 20, self._many(2))
        launched: list[str] = []

        def fake_launch(unit, backend, **kw):
            launched.append(unit.name)
            unit.tab_id = f"ws:tab-{unit.name}"

        monkeypatch.setattr(orch, "launch", fake_launch)
        orch.cmd_go(args(20, store, limit=1))
        assert launched == ["u1"]
        orch.cmd_go(args(20, store, limit=1))
        assert launched == ["u1", "u2"]

    def test_open_roster_rows_count_against_the_same_width(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        """One budget: six role panes plus ten units would be sixteen sessions on one account."""
        repo, store = bed
        write_record(
            store,
            20,
            units=self._many(3),
            base=git(repo, "rev-parse", "main"),
            branch="issue/20",
            run_id="20",
            concurrency=3,
            roster=[
                {"pane_name": "planner", "state": "prompted"},
                {"pane_name": "reviewer", "state": "settled"},
            ],
        )
        launched: list[str] = []
        monkeypatch.setattr(orch, "launch", lambda unit, backend, **kw: launched.append(unit.name))
        orch.cmd_go(args(20, store, limit=0))
        assert launched == ["u1"], "two open role panes leave room for exactly one unit"
        out = capsys.readouterr().out
        assert "u1" in out

    def test_a_closed_roster_row_does_not_count(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo, store = bed
        write_record(
            store,
            20,
            units=self._many(3),
            base=git(repo, "rev-parse", "main"),
            branch="issue/20",
            run_id="20",
            concurrency=3,
            roster=[{"pane_name": "planner", "state": "closed"}],
        )
        launched: list[str] = []
        monkeypatch.setattr(orch, "launch", lambda unit, backend, **kw: launched.append(unit.name))
        orch.cmd_go(args(20, store, limit=0))
        assert launched == ["u1", "u2", "u3"]

    def test_at_the_width_already_nothing_launches_and_both_counts_are_named(
        self, orch, bed, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        repo, store = bed
        write_record(
            store,
            20,
            units=[unit_row("u1", branch="orch/20-u1")],
            base=git(repo, "rev-parse", "main"),
            branch="issue/20",
            run_id="20",
            concurrency=2,
            roster=[
                {"pane_name": "planner", "state": "prompted"},
                {"pane_name": "reviewer", "state": "prompted"},
            ],
        )
        monkeypatch.setattr(orch, "launch", lambda *a, **k: pytest.fail("launched past the width"))
        assert orch.cmd_go(args(20, store, limit=0)) == 0
        out = capsys.readouterr().out
        assert "2 open role pane(s)" in out
        assert "concurrency allocation of 2" in out
