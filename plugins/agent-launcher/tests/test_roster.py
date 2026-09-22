"""Tests for the roster helper (issue #1024, plan U1 through U4).

Every test here drives ``roster.py`` through an **injected fake command runner** and a throwaway
run-record store under ``tmp_path``. Nothing in this file reaches a live herdr server, creates a
pane, closes a pane, or writes into the primary checkout's ``.claude/saga/`` store — several card
drivers share this machine, the operator's herdr server is running beside this suite with live
agent panes that belong to other work, and a test that closed one of those would be the exact
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

IN_PANE = {"HERDR_ENV": "1", "HERDR_PANE_ID": "w99:pTEST"}


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


def _receipt(task: str, *, delivered: bool = True, owned: bool = True) -> dict[str, Any]:
    """A launch receipt with exactly the keys ``launcher.launch_receipt_shape`` produces.

    In particular there is **no** ``workspace_id``: the launcher does not record one, and a fake
    that invented the key would have hidden the bug where every roster row stored a null workspace.
    That is what the live run found and this fixture now prevents.
    """
    return {
        "unit_name": task,
        "vendor": "claude",
        "tab_id": f"w99:t-{task}",
        "pane": f"w99:p-{task}",
        "agent_name": task,
        "reused": True,
        "owned": owned,
        "permission": "auto",
        "verified": True,
        "prompt_delivered": delivered,
    }


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


def test_the_roster_row_names_the_workspace_even_though_the_receipt_does_not(
    roster: ModuleType,
) -> None:
    """herdr identifiers are ``<workspace>:<object>``; the receipt carries no workspace of its own."""
    assert roster.workspace_of(_receipt("planner")) == "w99"
    assert roster.workspace_of({"pane": "w7C:p2Z"}) == "w7C"
    assert roster.workspace_of({}) is None


def _agent_get(status: str) -> subprocess.CompletedProcess[str]:
    """The shape `herdr agent get` really returns, read from herdr 0.9.0 on 2026-09-19."""
    return _ok(
        json.dumps(
            {
                "id": "cli:agent:get",
                "result": {
                    "agent": {
                        "agent": "claude",
                        "agent_status": status,
                        "pane_id": "w99:pX",
                        "tab_id": "w99:tX",
                        "workspace_id": "w99",
                    },
                    "type": "agent_info",
                },
            }
        )
    )


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


def test_every_subcommand_refuses_outside_a_herdr_pane(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R8 and KTD6: one line, exit 4, and no command is built."""
    _record(rr, store)
    runner = FakeRunner()
    for call in (roster.up, roster.wait, roster.down):
        with pytest.raises(roster.NotInHerdrPaneError):
            call(store, 4242, runner=runner, env={})
    assert runner.calls == []


def test_outside_a_pane_the_command_line_exits_four(
    roster: ModuleType, rr: ModuleType, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_path = _record(rr, store)
    monkeypatch.delenv("HERDR_ENV", raising=False)
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
    # ``main`` reads the ambient environment for the herdr-pane precondition, which it checks
    # before the record version — so without these two lines the test exits 4 on a machine
    # outside a pane (CI) and 3 inside one. Pin the pane so the version check is what is tested.
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_PANE_ID", "w99:pTEST")
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
    assert {row["pane_id"] for row in rows} == {
        "w99:p-issue-4242-planner",
        "w99:p-issue-4242-worker",
    }
    assert all(row["created_by"] == "roster.py" for row in rows)
    assert all(row["state"] == "prompted" for row in rows)
    # The row has to name the workspace an operator would look in, even though the launcher's
    # receipt carries no workspace field of its own.
    assert {row["workspace_id"] for row in rows} == {"w99"}


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


def test_every_wait_carries_a_timeout_and_takes_herdrs_settled_state_default(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R6: no ``--until`` (herdr matches idle, done, blocked); never an unbounded wait."""
    _record(rr, store)
    runner = FakeRunner({"agent get": _agent_get("idle")})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    code = roster.wait(store, 4242, runner=runner, timeout_ms=1234, env=IN_PANE, out=lambda _: None)

    assert code == roster.EXIT_OK
    waits = runner.commands("agent", "wait")
    assert len(waits) == 2
    for call in waits:
        assert "--timeout" in call and call[call.index("--timeout") + 1] == "1234"
        assert "--until" not in call
    assert all(row["state"] == "settled" for row in _rows(rr, store))


def test_a_blocked_role_is_reported_with_its_output_and_never_answered(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R7. The helper has no prompt or key-send path at all after a launch."""
    _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner(
        {"agent get": _agent_get("blocked"), "agent read": _ok("Do you want to proceed? (y/n)")}
    )
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    printed: list[str] = []

    with pytest.raises(roster.RoleBlockedError, match="issue-4242-planner"):
        roster.wait(store, 4242, runner=runner, env=IN_PANE, out=printed.append)

    text = "\n".join(printed)
    assert "BLOCKED" in text
    assert "Do you want to proceed?" in text
    assert _rows(rr, store)[0]["state"] == "blocked"
    assert runner.commands("agent", "prompt") == []
    assert runner.commands("agent", "send-keys") == []


def test_a_blocked_role_exits_five_from_the_command_line(
    roster: ModuleType, rr: ModuleType, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_path = _record(
        rr, store, staffing={"planner": {"vendor": "claude", "model": "opus", "effort": "high"}}
    )
    runner = FakeRunner({"agent get": _agent_get("blocked")})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    for key, value in IN_PANE.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(roster, "run", runner)

    assert roster.main(["wait", "--record", str(record_path)]) == 5


def test_a_wait_that_times_out_names_the_role_and_leaves_the_others_alone(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    _record(rr, store)
    runner = FakeRunner(
        {
            "agent wait issue-4242-planner": _ok("timed out", 124),
            "agent get": _agent_get("idle"),
        }
    )
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    with pytest.raises(roster.RoleBlockedError, match="issue-4242-planner"):
        roster.wait(store, 4242, runner=runner, timeout_ms=50, env=IN_PANE, out=lambda _: None)

    states = {row["pane_name"]: row["state"] for row in _rows(rr, store)}
    assert states["issue-4242-planner"] == "prompted"
    assert states["issue-4242-worker"] == "settled"


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
            {
                "result": {
                    "agents": [
                        {"pane_id": f"w7C:p{n}", "name": f"someone-elses-{n}"} for n in range(8)
                    ]
                }
            }
        )
    )
    runner = FakeRunner({"agent list": live_listing})
    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert len(runner.commands("launcher.py", "close")) == 2
    assert runner.commands("agent", "list") == [], "down decides from the record, not the listing"


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
                "pane_id": "w7C:pZZ",
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


def test_down_refuses_to_close_the_pane_it_is_running_in(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan R14: whatever the record says, the coordinator's own pane is never closed."""
    _record(
        rr,
        store,
        roster_rows=[
            {
                "schema": "roster_entry.v1",
                "pane_name": "the-coordinator",
                "pane_id": IN_PANE["HERDR_PANE_ID"],
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
    assert "running in" in "\n".join(printed)


def test_no_test_in_this_module_ever_closes_a_pane_or_tab_directly(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """The negative control: teardown goes through the launcher's ownership proof, never around it.

    Every command this module's helper can build, across a full up/wait/down cycle, is inspected —
    a bare ``herdr pane close`` or ``herdr tab close`` anywhere would mean the ownership receipt had
    been bypassed.
    """
    _record(rr, store)
    runner = FakeRunner({"agent get": _agent_get("idle")})

    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    roster.wait(store, 4242, runner=runner, timeout_ms=10, env=IN_PANE, out=lambda _: None)
    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    assert runner.commands("pane", "close") == [], "a bare pane close was issued"
    assert runner.commands("tab", "close") == [], "a bare tab close was issued"
    assert runner.commands("herdr", "pane") == [], "a raw herdr pane command was issued"
    assert runner.commands("launcher.py", "close"), "teardown must still go through the launcher"


def test_the_helper_never_creates_a_worktree(
    roster: ModuleType, rr: ModuleType, store: Path
) -> None:
    """Plan scope boundary: worktree creation belongs to the orchestrate driver, not here."""
    _record(rr, store)
    runner = FakeRunner({"agent get": _agent_get("idle")})

    roster.up(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)
    roster.wait(store, 4242, runner=runner, timeout_ms=10, env=IN_PANE, out=lambda _: None)
    roster.down(store, 4242, runner=runner, env=IN_PANE, out=lambda _: None)

    for call in runner.calls:
        assert "worktree" not in call, f"a worktree command was issued: {' '.join(call)}"
    assert runner.commands("git", "worktree") == []
    assert runner.commands("herdr", "worktree") == []
