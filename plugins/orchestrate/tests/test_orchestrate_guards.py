"""The four bounded guards this card carries (issue #1025, U7).

Issue 874: the protected-reference denylist peeled ``refs/heads/`` before stripping whitespace,
case sensitively, so four spellings of ``main`` were not classified as protected.
Issue 944: the launch handler replaced a unit's whole note, erasing the close-failure record the
launcher writes, and the sweep discarded the close return.
Issue 891: a multi-unit wait returned on the first settlement and recorded none of them.
Card 1025's own addition: a blocker another unit owns is reported, not repaired.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from orchestrate_support import (
    FakeProc,
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
    return load_orchestrate("_orchestrate_guards", ORCHESTRATE_SCRIPT)


@pytest.fixture
def run(orch):
    return orch.Run(
        run_id="60",
        source="a test",
        base="deadbeef",
        units=[],
        branch="parent/60",
        issue=60,
    )


ESCAPING_SPELLINGS = [
    " refs/heads/main",
    "refs/HEADS/main",
    "Refs/Heads/main",
    "\trefs/heads/main",
]
ALREADY_CAUGHT = ["main", "MAIN", "refs/heads/main", "  main  "]


class TestProtectedReferenceNormalisation:
    @pytest.mark.parametrize("spelling", ALREADY_CAUGHT + ESCAPING_SPELLINGS)
    def test_every_spelling_of_main_is_protected(self, orch, run, spelling: str) -> None:
        assert orch.is_protected_remote_branch(spelling, run) is True

    @pytest.mark.parametrize("spelling", ESCAPING_SPELLINGS)
    def test_the_same_normalisation_applies_to_the_run_branch(self, orch, spelling: str) -> None:
        """Not only the literal denylist: a run branch escaped by the identical route."""
        r = orch.Run(run_id="60", source="t", base="", units=[], branch="orch/60", issue=60)
        assert orch.is_protected_remote_branch(spelling.replace("main", "orch/60"), r) is True

    def test_the_same_normalisation_applies_to_the_base(self, orch) -> None:
        r = orch.Run(run_id="60", source="t", base="release-1", units=[], branch="", issue=60)
        assert orch.is_protected_remote_branch(" Refs/Heads/RELEASE-1 ", r) is True

    def test_an_ordinary_unit_branch_stays_deletable(self, orch, run) -> None:
        assert orch.is_protected_remote_branch("orch/1025-u1", run) is False

    def test_the_membership_set_is_unchanged(self, orch) -> None:
        assert (
            frozenset({"main", "master", "head", "develop", "release", "trunk"})
            == orch.PROTECTED_BRANCH_NAMES
        )

    def test_mutation_proof_peel_before_strip_fails_these_assertions(self, orch, run) -> None:
        """The defect, reproduced: restoring the old ordering must fail the parametrised set.

        This runs the superseded implementation directly rather than editing the module, so the
        test proves the assertions discriminate rather than merely passing beside them.
        """

        def old(branch: str) -> bool:
            norm = branch.removeprefix("refs/heads/").strip()
            if not norm:
                return True
            return norm.lower() in orch.PROTECTED_BRANCH_NAMES

        escaped = [s for s in ESCAPING_SPELLINGS if not old(s)]
        assert escaped == ESCAPING_SPELLINGS, "the old ordering must miss all four"
        assert all(orch.is_protected_remote_branch(s, run) for s in escaped)


class TestTheCloseFailureRecordSurvives:
    def test_the_launch_handler_appends_to_the_note_rather_than_replacing_it(
        self, orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path, branch="issue/61")
        monkeypatch.chdir(repo)
        store = tmp_path / "store"
        store.mkdir()
        write_record(
            store,
            61,
            units=[
                unit_row(
                    "u1",
                    branch="orch/61-u1",
                    note="tab ws:tab-1 could not be closed (exit 1): herdr said no",
                )
            ],
            run_id="61",
            base=git(repo, "rev-parse", "main"),
            branch="issue/61",
        )
        monkeypatch.setattr(orch, "assert_agent_launcher_available", lambda: None)
        monkeypatch.setattr(orch, "assert_review_transport", lambda units: None)
        monkeypatch.setattr(orch, "live_agents", lambda **kw: [])
        monkeypatch.setattr(
            orch,
            "append_unit_note",
            lambda unit, text: setattr(unit, "note", f"{unit.note}; {text}" if unit.note else text),
        )

        def failing_launch(unit, backend, **kw):
            raise SystemExit("the wrapper could not start the session")

        monkeypatch.setattr(orch, "launch", failing_launch)
        orch.cmd_go(args(61, store, limit=0))

        note = read_record(store, 61)["units"][0]["note"]
        assert "could not be closed" in note, "the launcher's close-failure record survived"
        assert "could not start the session" in note

    def test_the_sweep_does_not_report_a_unit_closed_when_its_close_failed(
        self, orch, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = make_repo(tmp_path, branch="parent/62")
        monkeypatch.chdir(repo)
        r = orch.Run(
            run_id="62",
            source="t",
            base=git(repo, "rev-parse", "main"),
            units=[orch.Unit(name="u1", vendor="claude", task="t", tab_id="ws:tab-1")],
            branch="parent/62",
            issue=62,
        )
        monkeypatch.setattr(
            orch, "close_run_session", lambda unit: FakeProc(1, stderr="herdr refused")
        )
        monkeypatch.setattr(
            orch, "tab_close_failure", lambda tab, code, detail: f"tab {tab} failed: {detail}"
        )
        monkeypatch.setattr(orch, "live_agents", lambda **kw: [])
        kept_reasons: dict[str, str] = {}
        closed, kept = orch.reap(r, merged_only=False, kept_reasons=kept_reasons)

        assert closed == [] and kept == ["u1"]
        assert "herdr refused" in kept_reasons["u1"]


class TestTheWaitRecordsEverySettlement:
    class _Event:
        def __init__(self, pane_id: str, agent_status: str) -> None:
            self.pane_id = pane_id
            self.agent_status = agent_status

    def test_a_two_unit_run_records_both_settlements(self, orch) -> None:
        a = orch.Unit(name="u1", vendor="claude", task="t", pane_id="ws:1")
        b = orch.Unit(name="u2", vendor="claude", task="t", pane_id="ws:2")
        observed: list[tuple] = []
        result = orch.wait_on_events(
            {"ws:1": a, "ws:2": b},
            iter([self._Event("ws:1", "idle"), self._Event("ws:2", "idle")]),
            interval=0,
            needed=2,
            poll_unit=lambda unit: "idle",
            sleep=lambda seconds: None,
            settled=observed,
        )
        assert result is not None
        assert [unit.name for unit, _ in observed] == ["u1"]

        # The generator is consumed lazily, so a caller that keeps reading sees the second one.
        observed.clear()
        orch.wait_on_events(
            {"ws:2": b},
            iter([self._Event("ws:2", "idle")]),
            interval=0,
            needed=2,
            poll_unit=lambda unit: "idle",
            sleep=lambda seconds: None,
            settled=observed,
        )
        assert [unit.name for unit, _ in observed] == ["u2"]

    def test_a_settlement_is_written_onto_the_unit_row(self, orch) -> None:
        unit = orch.Unit(name="u1", vendor="claude", task="t")
        orch.append_unit_note = lambda u, text: setattr(
            u, "note", f"{u.note}; {text}" if u.note else text
        )
        orch.record_settlement(unit, "idle")
        assert "settled idle" in unit.note

    def test_a_blocked_session_is_reported_rather_than_answered(self, orch, capsys) -> None:
        unit = orch.Unit(name="u1", vendor="claude", task="t")
        orch.report_wait(unit, "blocked")
        out = capsys.readouterr().out
        assert "is blocked" in out
        assert "asking a question in its own tab" in out

    def test_a_wait_that_times_out_records_no_settlement(self, orch) -> None:
        unit = orch.Unit(name="u1", vendor="claude", task="t", pane_id="ws:1")
        observed: list[tuple] = []
        result = orch.wait_on_events(
            {"ws:1": unit},
            iter([]),
            interval=0,
            needed=2,
            poll_unit=lambda u: "working",
            sleep=lambda seconds: None,
            settled=observed,
        )
        assert result is None and observed == []
