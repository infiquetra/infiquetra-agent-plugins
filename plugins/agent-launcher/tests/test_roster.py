"""Tests for the roster helper (issue #1024, plan U1 through U4).

Every test here drives ``roster.py`` through an **injected fake command runner** and a throwaway
run-record store under ``tmp_path``. Nothing in this file reaches a live herdr core, creates a
session, closes a session, or writes into the primary checkout's ``.claude/saga/`` store — several
card drivers share this machine, the operator's herdr core is running beside this suite with live
sessions that belong to other work, and a test that closed one of those would be the exact
failure the helper exists to prevent (plan R10).

The fake runner records every argument vector it is handed, so the assertions are about the
commands the helper *built* — which is where every guard in the plan actually lives.
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
CATALOG = Path(__file__).resolve().parents[3]
ROSTER_PATH = PACKAGE / "skills" / "agent-launcher" / "scripts" / "roster.py"
SAGA_SCRIPTS = CATALOG / "plugins" / "saga" / "scripts"
ROLES_DIR = PACKAGE / "roles"
STAFFING_REGISTRY = (
    CATALOG / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "staffing.json"
)

#: The caller's own terminal address, as herdr core sets it inside every Herdr terminal.
IN_PANE = {"HC_TERMINAL_ID": "t99"}

#: The terminal address the fake launcher gives each seat. Addresses are unique on the whole core.
ADDRESSES = {
    "issue-4242-planner": "t11",
    "issue-4242-worker": "t12",
    "issue-4343-planner": "t13",
    "issue-4343-worker": "t14",
}


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def roster() -> ModuleType:
    return _load("roster", ROSTER_PATH)


@pytest.fixture
def rr() -> ModuleType:
    path = SAGA_SCRIPTS / "run_record.py"
    if not path.is_file():
        pytest.skip(
            "plugins/saga/scripts/run_record.py is not in this checkout; "
            "roster records are saga's and that package is imported on its own branch"
        )
    return _load("run_record", path)


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A throwaway store root, never the primary checkout's."""
    root = tmp_path / "store" / "runs"
    root.mkdir(parents=True)
    return root


# --------------------------------------------------------------------------- the fake runner


class FakeRunner:
    """Stands in for ``roster.run``: records each argv, returns a canned result.

    ``replies`` maps a substring of the joined argv to the ``CompletedProcess`` to return, so a
    test names only the calls it cares about.
    """

    def __init__(self, replies: dict[str, subprocess.CompletedProcess[str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.replies = replies or {}

    def __call__(
        self,
        cmd: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(cmd))
        joined = " ".join(cmd)
        for needle, reply in self.replies.items():
            if needle in joined:
                return reply
        if "launcher.py" in joined and "launch" in cmd:
            return _ok(json.dumps(_receipt(cmd[cmd.index("--task") + 1])))
        if cmd[:2] == ["hc", "wait"]:
            return _ok(json.dumps(_wait_result(cmd[2])))
        return _ok("")

    def commands(self, *needles: str) -> list[list[str]]:
        """Calls whose argv carries *needles* as consecutive tokens.

        Token-exact on purpose. A substring search over the joined argv is not a guard: every
        launch carries this repository's own path, which contains both ``agent`` (in
        ``agent-launcher``) and ``worktrees``, so a loose matcher reports commands that were never
        issued and, worse, could hide one that was.
        """

        def matches(token: str, needle: str) -> bool:
            return token == needle or token.endswith(f"/{needle}")

        width = len(needles)
        found = []
        for call in self.calls:
            for start in range(len(call) - width + 1):
                if all(matches(call[start + i], needles[i]) for i in range(width)):
                    found.append(call)
                    break
        return found


def _ok(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["fake"], returncode, stdout, "")


def _receipt(
    task: str, *, delivered: bool = True, owned: bool = True, space: str | None = None
) -> dict[str, Any]:
    """A launch receipt with exactly the keys ``launcher.launch_receipt_shape`` produces.

    ``tab_id`` and ``pane`` are both the hc terminal address (``t11``). There is no ``workspace_id``
    key: a fake that invented one would have hidden the bug where every roster row stored a null
    workspace. The launcher adds ``space`` to a receipt only after the launch result names one, so
    it appears here only when a test asks for it.
    """
    address = ADDRESSES.get(task, "t90")
    receipt: dict[str, Any] = {
        "unit_name": task,
        "vendor": "claude",
        "tab_id": address,
        "pane": address,
        "agent_name": task,
        "reused": True,
        "owned": owned,
        "permission": "auto",
        "verified": True,
        "prompt_delivered": delivered,
    }
    if space is not None:
        receipt["space"] = space
    return receipt


def test_the_fake_receipt_carries_exactly_the_launchers_own_keys() -> None:
    """The fake must not be more generous than the launcher, or every test above it is a guess."""
    source = (PACKAGE / "skills" / "agent-launcher" / "scripts" / "launcher.py").read_text(
        encoding="utf-8"
    )
    body = source.split("def launch_receipt_shape(", 1)[1].split("\ndef ", 1)[0]
    real_keys = set(re.findall(r'^\s+"([a-z_]+)":', body, re.MULTILINE))
    assert set(_receipt("x")) == real_keys, (
        "the fake launch receipt has drifted from launcher.launch_receipt_shape"
    )


def test_the_roster_row_names_the_workspace_the_receipt_names_in_space(
    roster: ModuleType,
) -> None:
    """The launcher's receipt names the Herdr app workspace id as ``space``; that is read first."""
    assert roster.workspace_of(_receipt("planner", space="w4")) == "w4"
    assert roster.workspace_of({"space": "w4", "workspace_id": "w9", "tab_id": "w7:t1"}) == "w4"
    assert roster.workspace_of({"workspace_id": "w9", "tab_id": "w7:t1"}) == "w9"
    assert roster.workspace_of({}) is None


def test_a_bare_hc_address_names_no_workspace(roster: ModuleType) -> None:
    """``t11`` is unique on the whole core and says nothing about where a window shows it."""
    assert roster.workspace_of(_receipt("issue-4242-planner")) is None
    assert roster.workspace_of({"tab_id": "t5", "pane": "t5"}) is None


def test_an_old_herdr_receipt_still_names_its_workspace_in_its_ids(roster: ModuleType) -> None:
    """Receipts written before the move carry ``<workspace>:<object>`` ids; they are still read."""
    assert roster.workspace_of({"tab_id": "w99:t-planner", "pane": "w99:p-planner"}) == "w99"
    assert roster.workspace_of({"pane": "w7C:p2Z"}) == "w7C"


def _wait_result(
    target: str, *, reason: str = "status", ended: bool = True, status: str = "idle"
) -> dict[str, Any]:
    """The WaitResult JSON ``hc wait --json`` prints."""
    return {
        "children": [],
        "ended": ended,
        "exit_code": None,
        "reason": reason,
        "signal": None,
        "status": status,
        "terminal": target,
        "turn": 4,
    }


def _hc_wait(target: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return _ok(json.dumps(_wait_result(target, **kwargs)))


def _agent_get(status: str, address: str = "t5") -> subprocess.CompletedProcess[str]:
    """The shape ``hc get --json`` returns for a live terminal whose program reported *status*."""
    return _ok(
        json.dumps(
            {
                "address": address,
                "state": "live",
                "status": {"app": "claude-code", "state": status},
            }
        )
    )


def _finished_get(address: str = "t5") -> subprocess.CompletedProcess[str]:
    """``hc get --json`` for a terminal whose program has finished."""
    return _ok(json.dumps({"address": address, "state": "finished", "status": None}))


# --------------------------------------------------------------------------- records


def _record(
    rr: ModuleType,
    store: Path,
    *,
    staffing: dict[str, Any] | None = None,
    lenses: list[str] | None = None,
    concurrency: int | None = None,
    roster_rows: list[dict[str, Any]] | None = None,
    issue: int = 4242,
) -> Path:
    configuration = rr.empty_run_configuration()
    configuration["staffing_models_and_efforts"]["value"] = (
        staffing
        if staffing is not None
        else {
            "planner": {"vendor": "claude", "model": "opus", "effort": "high"},
            "worker": {"vendor": "codex", "model": "gpt-5.6-sol", "effort": "medium"},
        }
    )
    if lenses is not None:
        configuration["applicable_lenses"]["value"] = lenses
    if concurrency is not None:
        configuration["concurrency_allocation"]["value"] = concurrency
    record = rr.RunRecord(
        issue=issue,
        repo="infiquetra/infiquetra-claude-plugins",
        run_configuration=configuration,
        roster=roster_rows or [],
    )
    return Path(rr.save(store, record))


def _rows(rr: ModuleType, store: Path, issue: int = 4242) -> list[dict[str, Any]]:
    record = rr.load(store, issue, warn=None)
    assert record is not None
    return list(record.roster)


# --------------------------------------------------------------------------- U1: the skeleton


def test_dry_run_prints_every_pane_kind_model_and_prompt_and_creates_nothing(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """The card's first acceptance criterion, and the proof the dry run touches no runner."""
    _record(rr, store)
    runner = FakeRunner()
    printed: list[str] = []

    code = roster.up(store, 4242, runner=runner, dry_run=True, env=IN_PANE, out=printed.append)

    assert code == roster.EXIT_OK
    text = "\n".join(printed)
    assert "issue-4242-planner" in text
    assert "issue-4242-worker" in text
    assert "claude" in text and "opus" in text and "high" in text
    assert "codex" in text and "gpt-5.6-sol" in text and "medium" in text
    assert "planner.md" in text and "implementer.md" in text
    assert runner.calls == [], "a dry run must create nothing"


def test_every_subcommand_refuses_outside_a_herdr_terminal(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R8 and KTD6: one line, exit 4, and no command is built."""
    _record(rr, store)
    runner = FakeRunner()
    for call in (roster.up, roster.wait, roster.down):
        with pytest.raises(roster.NotInHerdrPaneError):
            call(store, 4242, runner=runner, env={})
    assert runner.calls == []


def test_require_herdr_pane_returns_the_callers_own_terminal_address(roster: ModuleType) -> None:
    assert roster.require_herdr_pane({"HC_TERMINAL_ID": "t21"}) == "t21"


def test_require_herdr_pane_refuses_without_a_terminal_address_even_in_old_herdr(
    roster: ModuleType,
) -> None:
    """``HERDR_ENV`` and ``HERDR_PANE_ID`` mean nothing now; only ``HC_TERMINAL_ID`` does."""
    old = {"HERDR_ENV": "1", "HERDR_PANE_ID": "w99:pTEST"}
    for env in ({}, old, {**old, "HC_TERMINAL_ID": ""}):
        with pytest.raises(roster.NotInHerdrPaneError, match="Herdr terminal"):
            roster.require_herdr_pane(env)


def test_outside_a_terminal_the_command_line_exits_four(
    roster: ModuleType, rr: ModuleType, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_path = _record(rr, store)
    monkeypatch.delenv("HC_TERMINAL_ID", raising=False)
    monkeypatch.setenv("HERDR_ENV", "1")
    assert roster.main(["down", "--record", str(record_path)]) == 4


def test_a_role_with_no_prompt_in_the_library_is_a_named_refusal(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan KTD3: ``merging-worker`` is staffed by the registry and has no lifecycle prompt."""
    _record(
        rr,
        store,
        staffing={"merging-worker": {"vendor": "claude", "model": "sonnet", "effort": "low"}},
    )
    with pytest.raises(roster.RosterError, match="merging-worker"):
        roster.up(store, 4242, runner=FakeRunner(), dry_run=True, env=IN_PANE)


def test_an_unknown_record_version_exits_three_with_one_line(
    roster: ModuleType,
    rr: ModuleType,
    store: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ``main`` reads the ambient environment for the Herdr terminal precondition, which it checks
    # before the record version — so without this line the test exits 4 on a machine outside a
    # terminal (CI) and 3 inside one. Pin the terminal so the version check is what is tested.
    monkeypatch.setenv("HC_TERMINAL_ID", "t99")
    record_path = _record(rr, store)
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    payload["schema"] = "run_record.v2"
    record_path.write_text(json.dumps(payload), encoding="utf-8")

    assert roster.main(["down", "--record", str(record_path)]) == 3
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "run_record.v2" in err[0]


def test_record_and_issue_resolve_to_the_same_place_and_both_or_neither_refuses(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan KTD10."""
    record_path = _record(rr, store)
    assert roster.resolve_record_location(record=str(record_path)) == (store, 4242)
    assert roster.resolve_record_location(issue=4242, store_root=str(store)) == (store, 4242)
    with pytest.raises(roster.RosterError, match="not both"):
        roster.resolve_record_location(record=str(record_path), issue=4242)
    with pytest.raises(roster.RosterError, match="--record"):
        roster.resolve_record_location()


def test_the_staffing_to_roles_mapping_resolves_on_both_sides(roster: ModuleType) -> None:
    """Plan KTD2's drift guard: a change to either vocabulary fails here, not in production."""
    if not STAFFING_REGISTRY.is_file():
        pytest.skip(
            "plugins/fleet-core/scripts/fleet_commons/staffing.json is not in this checkout; "
            "the full Fleet Core import carries it"
        )
    registry = json.loads(STAFFING_REGISTRY.read_text(encoding="utf-8"))
    index = json.loads((ROLES_DIR / "index.json").read_text(encoding="utf-8"))
    known_role_ids = {row["role_id"] for row in index["roles"]}

    for staffing_role, role_id in roster.STAFFING_ROLE_TO_ROLE_ID.items():
        assert staffing_role in registry["roles"], (
            f"{staffing_role!r} is mapped but the staffing registry no longer names it"
        )
        assert role_id in known_role_ids, (
            f"{role_id!r} is mapped but the roles library no longer carries that role"
        )

    unmapped = set(registry["roles"]) - set(roster.STAFFING_ROLE_TO_ROLE_ID)
    assert unmapped == {"merging-worker"}, (
        "a staffing role gained or lost a prompt; map it, or state why it is a refusal"
    )


def test_a_lens_reviewer_gets_one_seat_per_lens_sliced_by_the_published_rule(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R5: the slicing rule is read from ``index.json``, never restated here."""
    _record(
        rr,
        store,
        staffing={"lens-reviewer": {"vendor": "claude", "model": "opus", "effort": "high"}},
        lenses=["security", "correctness", "testing"],
    )
    record = rr.load(store, 4242, warn=None)
    seats = roster.plan_seats(record)

    assert [seat.pane_name for seat in seats] == [
        "issue-4242-lens-security",
        "issue-4242-lens-correctness",
        "issue-4242-lens-testing",
    ]
    assert all(seat.role_id == "lens_reviewer" for seat in seats)

    index = roster.load_roles_index()
    text = (ROLES_DIR / "lens-reviewer.md").read_text(encoding="utf-8")
    sliced = roster.lens_section(text, index, "security")
    assert "#### security" in sliced
    assert "#### correctness" not in sliced
    assert len(sliced) < len(text)


def test_a_lens_reviewer_with_no_declared_lens_is_refused(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(
        rr,
        store,
        staffing={"lens-reviewer": {"vendor": "claude", "model": "opus", "effort": "high"}},
    )
    record = rr.load(store, 4242, warn=None)
    with pytest.raises(roster.RosterError, match="no applicable lenses"):
        roster.plan_seats(record)


def test_seats_that_would_share_a_pane_name_are_refused_before_any_launch(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """The launcher splits a pane inside an existing tab rather than failing on a duplicate label."""
    _record(
        rr,
        store,
        staffing={"lens-reviewer": {"vendor": "claude", "model": "opus", "effort": "high"}},
        lenses=["security", "security"],
    )
    record = rr.load(store, 4242, warn=None)
    with pytest.raises(roster.RosterError, match="same pane name"):
        roster.plan_seats(record)


def test_the_dispatch_brief_names_the_role_file_by_absolute_path(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan KTD4: the briefing arrives by path, never as a composer paste."""
    record_path = _record(rr, store)
    record = rr.load(store, 4242, warn=None)
    seat = next(s for s in roster.plan_seats(record) if s.role == "planner")
    brief = roster.dispatch_brief(seat, record, record_path)

    assert str(ROLES_DIR / "planner.md") in brief
    assert str(record_path) in brief
    assert len(brief) < 1000, "the brief points at the prompt; it does not inline it"
    assert (ROLES_DIR / "planner.md").read_text(encoding="utf-8")[:200] not in brief


# --------------------------------------------------------------------------- U2: up


def test_up_launches_one_session_per_role_with_the_staffing_plan_vendor_model_and_effort(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store)
    runner = FakeRunner()

    code = roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert code == roster.EXIT_OK
    launches = runner.commands("launcher.py", "launch")
    assert len(launches) == 2
    planner = next(c for c in launches if "issue-4242-planner" in " ".join(c))
    assert planner[planner.index("--vendor") + 1] == "claude"
    assert planner[planner.index("--model") + 1] == "opus"
    assert planner[planner.index("--effort") + 1] == "high"
    worker = next(c for c in launches if "issue-4242-worker" in " ".join(c))
    assert worker[worker.index("--vendor") + 1] == "codex"
    assert worker[worker.index("--model") + 1] == "gpt-5.6-sol"


def test_up_records_each_pane_before_it_launches_the_next_one(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R3: an interrupted ``up`` still leaves ``down`` able to clean up what was created."""
    _record(rr, store)
    seen: list[int] = []

    class RecordingRunner(FakeRunner):
        def __call__(self, cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            if "launch" in cmd:
                seen.append(len(_rows(rr, store)))
            return super().__call__(cmd, **kwargs)

    roster.up(store, 4242, runner=RecordingRunner(), env=IN_PANE, out=lambda _: None)

    assert seen == [0, 1], "the first pane must be on the record before the second launch"
    rows = _rows(rr, store)
    assert [row["schema"] for row in rows] == ["roster_entry.v1"] * 2
    assert {row["pane_id"] for row in rows} == {"t11", "t12"}
    assert all(row["created_by"] == "roster.py" for row in rows)
    assert all(row["state"] == "prompted" for row in rows)
    # A bare hc address names no workspace, and the fake receipt carries no ``space``: the row
    # records none rather than a guess.
    assert {row["workspace_id"] for row in rows} == {None}


def test_up_records_the_space_the_receipt_names_as_the_rows_workspace(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner(
        {"--task issue-4242-planner": _ok(json.dumps(_receipt("issue-4242-planner", space="w4")))}
    )

    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    row = _rows(rr, store)[0]
    assert (row["pane_id"], row["workspace_id"]) == ("t11", "w4")


def test_up_writes_only_the_roster_block(roster: ModuleType, rr: ModuleType, store: Path) -> None:
    """Plan R11: no other run-record block is this helper's to write."""
    record_path = _record(rr, store)
    before = json.loads(record_path.read_text(encoding="utf-8"))

    roster.up(store, 4242, runner=FakeRunner(), env=IN_PANE, out=lambda _: None)

    after = json.loads(record_path.read_text(encoding="utf-8"))
    changed = {k for k in after if before.get(k) != after.get(k)}
    assert changed == {"roster", "updated_at"}


def test_up_is_idempotent_per_role(roster: ModuleType, rr: ModuleType, store: Path) -> None:
    """Plan R12: re-running after an interruption repairs the roster, never doubles it."""
    _record(rr, store)
    runner = FakeRunner()

    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert len(runner.commands("launcher.py", "launch")) == 2, "the second run must launch nothing"
    assert len(_rows(rr, store)) == 2


def test_an_undelivered_prompt_is_recorded_reported_and_never_retried(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R13: the launcher's staged-input stop. Redelivery is an operator action."""
    _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner(
        {
            "--task issue-4242-planner": _ok(
                json.dumps(_receipt("issue-4242-planner", delivered=False)), 1
            )
        }
    )
    printed: list[str] = []

    code = roster.up(store, 4242, runner=runner, env=IN_PANE, out=printed.append)

    assert code == roster.EXIT_REFUSED
    assert _rows(rr, store)[0]["state"] == "created"
    assert "not delivered" in "\n".join(printed)
    assert runner.commands("redeliver") == []
    assert len(runner.commands("launcher.py", "launch")) == 1, "no second launch after a stop"


def test_a_plan_needing_more_panes_than_the_concurrency_allocation_is_refused(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store, concurrency=1)
    runner = FakeRunner()
    with pytest.raises(roster.RosterError, match="concurrency allocation"):
        roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    assert runner.calls == []


def test_the_named_account_reaches_every_launch_and_absence_names_nothing(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """The launcher appends no account flag when none is named, and its own default is the
    personal account — so a roster meant to run on the company account has to say so, once, and
    have it reach every seat."""
    _record(rr, store)
    runner = FakeRunner()

    roster.up(store, 4242, runner=runner, account="company", env=IN_PANE, out=lambda _: None)

    launches = runner.commands("launcher.py", "launch")
    assert len(launches) == 2
    for call in launches:
        assert call[call.index("--account") + 1] == "company"

    plain = FakeRunner()
    _record(rr, store, issue=4343)
    roster.up(store, 4343, runner=plain, env=IN_PANE, out=lambda _: None)
    for call in plain.commands("launcher.py", "launch"):
        assert "--account" not in call, "no account named must mean no account flag invented"


def test_a_staffing_row_may_pin_its_own_account(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(
        rr,
        store,
        staffing={
            "planner": {
                "vendor": "claude",
                "model": "opus",
                "effort": "high",
                "account": "personal",
            }
        },
    )
    runner = FakeRunner()

    roster.up(store, 4242, runner=runner, account="company", env=IN_PANE, out=lambda _: None)

    call = runner.commands("launcher.py", "launch")[0]
    assert call[call.index("--account") + 1] == "personal"


def test_the_receipt_is_written_outside_every_worktree_beside_the_record(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan KTD9: a receipt inside a worktree dies with the worktree, and the panes then leak."""
    roster_record = _record(rr, store)
    roster.up(store, 4242, runner=FakeRunner(), env=IN_PANE, out=lambda _: None)

    for row in _rows(rr, store):
        receipt_path = Path(row["receipt_path"])
        assert receipt_path.is_file()
        assert receipt_path.parent == store / "receipts" / "issue-4242"
        assert roster_record.parent in receipt_path.parents


# --------------------------------------------------------------------------- U3: wait


def test_every_wait_is_an_hc_wait_on_the_recorded_address_with_a_timeout_in_seconds(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R6: never an unbounded wait; hc takes whole seconds and is asked for JSON."""
    _record(rr, store)
    runner = FakeRunner({"hc get": _agent_get("idle")})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    code = roster.wait(
        store, 4242, runner=runner, timeout_ms=12_345, env=IN_PANE, out=lambda _: None
    )

    assert code == roster.EXIT_OK
    waits = runner.commands("hc", "wait")
    assert sorted(waits) == [
        ["hc", "wait", "t11", "--timeout", "12", "--json"],
        ["hc", "wait", "t12", "--timeout", "12", "--json"],
    ]
    assert all(row["state"] == "settled" for row in _rows(rr, store))


def test_a_sub_second_wait_is_sent_as_one_second(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """hc takes whole seconds and zero would not be a timeout at all."""
    _record(rr, store)
    runner = FakeRunner({"hc get": _agent_get("idle")})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    roster.wait(store, 4242, runner=runner, timeout_ms=50, env=IN_PANE, out=lambda _: None)

    for call in runner.commands("hc", "wait"):
        assert call[call.index("--timeout") + 1] == "1"


def test_a_row_with_no_terminal_address_is_not_waited_on(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Rows from the old Herdr roster named the session; with no address there is no target."""
    _record(
        rr,
        store,
        roster_rows=[
            {
                "schema": "roster_entry.v1",
                "pane_name": "issue-4242-planner",
                "agent_name": "issue-4242-planner",
                "pane_id": None,
                "created_by": "roster.py",
                "state": "prompted",
            }
        ],
    )
    runner = FakeRunner()

    code = roster.wait(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert code == roster.EXIT_OK
    assert runner.calls == []


def test_a_blocked_role_is_reported_with_its_output_and_never_answered(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R7. The helper has no prompt or key-send path at all after a launch."""
    _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner(
        {"hc get": _agent_get("blocked"), "hc read": _ok("Do you want to proceed? (y/n)")}
    )
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    printed: list[str] = []

    with pytest.raises(roster.RoleBlockedError, match="issue-4242-planner"):
        roster.wait(store, 4242, runner=runner, env=IN_PANE, out=printed.append)

    text = "\n".join(printed)
    assert "BLOCKED on terminal t11" in text
    assert "Do you want to proceed?" in text
    assert _rows(rr, store)[0]["state"] == "blocked"
    assert runner.commands("hc", "read") == [["hc", "read", "t11", "--lines", "40"]]
    assert runner.commands("hc", "send") == []
    assert runner.commands("hc", "type") == []
    assert runner.commands("hc", "key") == []


def test_a_blocked_role_exits_five_from_the_command_line(
    roster: ModuleType, rr: ModuleType, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_path = _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner({"hc get": _agent_get("blocked")})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    for key, value in IN_PANE.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(roster, "run", runner)

    assert roster.main(["wait", "--record", str(record_path)]) == 5


def test_a_wait_that_fails_names_the_role_and_leaves_the_others_alone(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store)
    runner = FakeRunner(
        {
            "hc wait t11": _ok("timed out", 124),
            "hc get": _agent_get("idle"),
        }
    )
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    with pytest.raises(roster.RoleBlockedError, match="issue-4242-planner"):
        roster.wait(store, 4242, runner=runner, timeout_ms=50, env=IN_PANE, out=lambda _: None)

    states = {row["pane_name"]: row["state"] for row in _rows(rr, store)}
    assert states["issue-4242-planner"] == "prompted"
    assert states["issue-4242-worker"] == "settled"


def test_a_wait_that_hc_itself_times_out_is_unsettled_even_though_hc_exits_zero(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """``reason: timeout`` with ``ended: false`` is a clean exit that settled nothing."""
    _record(rr, store)
    runner = FakeRunner(
        {
            "hc wait t11": _hc_wait("t11", reason="timeout", ended=False, status="working"),
            "hc get": _agent_get("idle"),
        }
    )
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    printed: list[str] = []

    with pytest.raises(roster.RoleBlockedError, match="issue-4242-planner"):
        roster.wait(store, 4242, runner=runner, timeout_ms=5000, env=IN_PANE, out=printed.append)

    assert "did not settle" in "\n".join(printed)
    assert ["hc", "get", "t11", "--json"] not in runner.calls, "a timed out wait is not read"
    states = {row["pane_name"]: row["state"] for row in _rows(rr, store)}
    assert states["issue-4242-planner"] == "prompted"
    assert states["issue-4242-worker"] == "settled"


def test_a_wait_that_prints_no_json_is_unsettled(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner({"hc wait t11": _ok("terminal t11 is idle"), "hc get": _agent_get("idle")})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    with pytest.raises(roster.RoleBlockedError, match="did not settle"):
        roster.wait(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)


def test_a_finished_terminal_reads_as_exited_and_is_not_settled(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """A program that has finished is not an agent that reported idle."""
    _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner({"hc get": _finished_get("t11")})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    printed: list[str] = []

    with pytest.raises(roster.RoleBlockedError, match="status exited"):
        roster.wait(store, 4242, runner=runner, env=IN_PANE, out=printed.append)

    assert "reports status exited" in "\n".join(printed)
    assert _rows(rr, store)[0]["state"] == "prompted"


def test_agent_status_reads_hc_get(roster: ModuleType) -> None:
    def status_of(reply: subprocess.CompletedProcess[str]) -> str:
        runner = FakeRunner({"hc get": reply})
        result = roster._agent_status(runner, "t5")
        assert runner.calls == [["hc", "get", "t5", "--json"]]
        return result

    assert status_of(_agent_get("blocked")) == "blocked"
    assert status_of(_agent_get("working")) == "working"
    assert status_of(_finished_get()) == "exited"
    no_status = _ok(json.dumps({"address": "t5", "state": "live", "status": None}))
    assert status_of(no_status) == "unknown"
    assert status_of(_ok("", 1)) == "unknown"
    assert status_of(_ok("not json")) == "unknown"


# --------------------------------------------------------------------------- U4: down


def test_down_closes_exactly_the_recorded_panes_through_their_own_receipts(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store)
    runner = FakeRunner()
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    receipts = {row["receipt_path"] for row in _rows(rr, store)}

    code = roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    closes = runner.commands("launcher.py", "close")
    assert code == roster.EXIT_OK
    assert len(closes) == 2
    assert {c[c.index("--receipt-json") + 1] for c in closes} == receipts
    assert all(row["state"] == "closed" for row in _rows(rr, store))
    assert all(row["closed_at"] for row in _rows(rr, store))


def test_down_ignores_live_panes_it_did_not_record(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """The operator's other agent panes are live beside this run; the record is the only input."""
    _record(rr, store)
    live_listing = _ok(
        json.dumps(
            [
                {"address": f"t{40 + n}", "state": "live", "name": f"someone-elses-{n}"}
                for n in range(8)
            ]
        )
    )
    runner = FakeRunner({"hc ls": live_listing})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert len(runner.commands("launcher.py", "close")) == 2
    assert runner.commands("hc", "ls") == [], "down decides from the record, not the listing"


def test_down_skips_a_row_whose_ownership_receipt_is_gone(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store)
    runner = FakeRunner()
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    rows = _rows(rr, store)
    Path(rows[0]["receipt_path"]).unlink()
    printed: list[str] = []

    roster.down(store, 4242, runner=runner, env=IN_PANE, out=printed.append)

    assert len(runner.commands("launcher.py", "close")) == 1
    assert "receipt" in "\n".join(printed)


def test_down_skips_a_row_this_helper_did_not_create(
    roster: ModuleType, rr: ModuleType, store: Path, tmp_path: Path
) -> None:
    """The row is otherwise perfectly closeable — a real, readable receipt on disk, a live state,
    a pane that is not this one. Only ``created_by`` stands between it and a close, so this test
    isolates that guard instead of being caught by the missing-receipt one."""
    receipt = tmp_path / "foreign-receipt.json"
    receipt.write_text(json.dumps(_receipt("someone-elses-session")), encoding="utf-8")
    _record(
        rr,
        store,
        roster_rows=[
            {
                "schema": "roster_entry.v1",
                "pane_name": "someone-elses-session",
                "pane_id": "t77",
                "receipt_path": str(receipt),
                "created_by": "a-different-tool",
                "state": "prompted",
            }
        ],
    )
    runner = FakeRunner()
    printed: list[str] = []

    roster.down(store, 4242, runner=runner, env=IN_PANE, out=printed.append)

    assert runner.calls == []
    assert "created_by" in "\n".join(printed)


def test_down_does_not_close_a_row_twice(roster: ModuleType, rr: ModuleType, store: Path) -> None:
    _record(rr, store)
    runner = FakeRunner()
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert len(runner.commands("launcher.py", "close")) == 2


def test_down_on_an_empty_roster_closes_nothing_and_succeeds(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store)
    runner = FakeRunner()
    assert roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None) == 0
    assert runner.calls == []


def test_down_refuses_to_close_the_terminal_it_is_running_in(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R14: whatever the record says, the coordinator's own terminal is never closed."""
    _record(
        rr,
        store,
        roster_rows=[
            {
                "schema": "roster_entry.v1",
                "pane_name": "the-coordinator",
                "pane_id": IN_PANE["HC_TERMINAL_ID"],
                "receipt_path": "/nonexistent",
                "created_by": "roster.py",
                "state": "prompted",
            }
        ],
    )
    runner = FakeRunner()
    printed: list[str] = []

    roster.down(store, 4242, runner=runner, env=IN_PANE, out=printed.append)

    assert runner.calls == []
    assert "terminal this command is running in" in "\n".join(printed)


def test_no_test_in_this_module_ever_closes_a_terminal_directly(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """The negative control: teardown goes through the launcher's ownership proof, never around it.

    Every command this module's helper can build, across a full up/wait/down cycle, is inspected —
    a bare ``hc close`` anywhere would mean the ownership receipt had been bypassed, and an old
    Herdr call would mean the move was not finished.
    """
    _record(rr, store)
    runner = FakeRunner({"hc get": _agent_get("idle")})

    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    roster.wait(store, 4242, runner=runner, timeout_ms=10, env=IN_PANE, out=lambda _: None)
    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert runner.commands("hc", "close") == [], "a bare hc close was issued"
    assert runner.commands("hc", "kill") == [], "a bare hc kill was issued"
    assert all(call[0] != "herdr" for call in runner.calls), "an old Herdr call was issued"
    assert runner.commands("launcher.py", "close"), "teardown must still go through the launcher"


def test_the_helper_never_creates_a_worktree(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan scope boundary: worktree creation belongs to the orchestrate driver, not here."""
    _record(rr, store)
    runner = FakeRunner({"hc get": _agent_get("idle")})

    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    roster.wait(store, 4242, runner=runner, timeout_ms=10, env=IN_PANE, out=lambda _: None)
    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    for call in runner.calls:
        assert "worktree" not in call, f"a worktree command was issued: {' '.join(call)}"
    assert runner.commands("git", "worktree") == []
    assert runner.commands("hc", "worktree") == []


def test_saving_the_roster_lands_on_a_fresh_read_under_the_record_lock(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Saga's run-record lock convention (issue 95): only ``roster`` is replaced on a fresh copy."""
    rr.save(store, rr.RunRecord(issue=95, units=[{"id": "u1"}]))
    stale = rr.load(store, 95, warn=None)
    rr.update(
        store,
        95,
        lambda current: rr.RunRecord(
            **{**current.__dict__, "units": [{"id": "u1", "usage": {"entries": [{"x": 1}]}}]}
        ),
    )
    roster.save_record(store, stale, [{"role": "worker"}])
    reread = rr.load(store, 95, warn=None)
    assert reread.roster == [{"role": "worker"}]
    assert reread.units == [{"id": "u1", "usage": {"entries": [{"x": 1}]}}]
    assert rr.lock_path(store, 95).is_file()


# --------------------------------------------------------------------------- issue #158: headless


TARGETED = {
    "planner": {"vendor": "claude", "model": "opus", "effort": "high"},
    "targeted-reviewer": {"vendor": "claude", "model": "opus", "effort": "high"},
}


def test_the_targeted_reviewer_gets_one_seat_never_one_per_lens(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store, staffing=TARGETED, lenses=["correctness", "security", "testing"])
    record = roster.load_record(store, 4242)
    seats = [s for s in roster.plan_seats(record) if s.role == "targeted-reviewer"]
    assert len(seats) == 1
    seat = seats[0]
    assert (seat.pane_name, seat.lens, seat.headless) == (
        "issue-4242-targeted-reviewer", None, True,
    )
    assert (seat.role_id, seat.prompt_file) == ("targeted_reviewer", "targeted-reviewer.md")


def test_up_opens_no_pane_and_records_no_row_for_the_headless_seat(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store, staffing=TARGETED, lenses=["correctness"])
    runner = FakeRunner()
    said: list[str] = []

    code = roster.up(store, 4242, runner=runner, env=IN_PANE, out=said.append)

    assert code == roster.EXIT_OK
    launches = runner.commands("launcher.py", "launch")
    assert len(launches) == 1
    assert not any("targeted-reviewer" in " ".join(c) for c in launches)
    assert [row["role"] for row in _rows(rr, store)] == ["planner"]
    assert any("targeted-reviewer is headless" in line for line in said)


def test_a_headless_seat_counts_against_no_pane_allocation(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store, staffing=TARGETED, lenses=["correctness"], concurrency=1)
    runner = FakeRunner()

    code = roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert code == roster.EXIT_OK
    assert len(runner.commands("launcher.py", "launch")) == 1


def test_the_dry_run_says_how_the_headless_seat_starts(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store, staffing=TARGETED, lenses=["correctness"])
    said: list[str] = []
    roster.up(store, 4242, dry_run=True, env=IN_PANE, out=said.append)
    assert "start  started by `launcher.py review`" in "\n".join(said)
    assert "would create 1 pane(s)" in said[0]


# --------------------------------------------------------------------------- run(): hc env


def _capture_subprocess_env(
    roster: ModuleType, monkeypatch: pytest.MonkeyPatch, cmd: list[str]
) -> dict[str, str] | None:
    """Run ``roster.run(cmd)`` against a patched ``subprocess.run`` and return the env it got."""
    seen: dict[str, Any] = {}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setenv("HC_TERMINAL_ID", "t99")
    monkeypatch.setenv("HC_SCOPE", "somewhere")
    monkeypatch.setenv("ROSTER_TEST_KEEP", "yes")
    monkeypatch.setattr(roster.subprocess, "run", fake_run)
    roster.run(cmd, check=False)
    return seen["env"]


def test_run_strips_the_callers_terminal_variables_for_hc_and_keeps_the_rest(
    roster: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sends then arrive untagged, and a wait is not ended by a message to this session (D5)."""
    env = _capture_subprocess_env(roster, monkeypatch, ["hc", "wait", "t5", "--json"])

    assert env is not None
    assert "HC_TERMINAL_ID" not in env and "HC_SCOPE" not in env
    assert env["ROSTER_TEST_KEEP"] == "yes"


def test_run_leaves_the_environment_alone_for_any_other_program(
    roster: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The launcher needs the caller's variables to know which workspace it is being run from."""
    env = _capture_subprocess_env(roster, monkeypatch, ["python3", "launcher.py", "launch"])
    assert env is None
