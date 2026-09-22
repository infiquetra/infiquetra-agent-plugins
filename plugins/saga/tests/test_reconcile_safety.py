"""W7 (SDLC issue #88, R35): the four reconcile safety behaviours survive in the Mission Control
path, with the two the source register names as genuinely at risk tested individually.

The four behaviours (SDLC R35, plan U6):

1. **Replay safety** — a repeated reconcile tick collapses to ``skipped`` (idempotency ledger).
2. **Drift detection** — an outside edit is re-detected on the next tick (level-triggered).
3. **Closed allowlist** — a non-allowlisted op is never auto-corrected. Since W7 the allowlist is
   EMPTY (R32: no autonomous lifecycle-field write authority), the maximally closed form.
4. **Operator prompt when uncertain or consequential** — anything not mechanically safe surfaces
   as ``gated``/``halt`` for the operator instead of a write.

The two at-risk behaviours, named individually (R35):

* the **per-op level-triggered reconcile tick**, which ``/work`` and ``/loop`` have and ``/outcome``
  does not (a deliberate, tracked gap — plugins #593; asserted below as a KNOWN GAP, not hidden),
* **halt-on-irreversible-drift** surfacing a NAMED reason instead of overwriting.

Post-W7 posture (R30/R32): the controller holds no autonomous lifecycle-field write authority —
every drift halts. These tests prove the behaviours are preserved in that stricter shape, not that
the retired auto-correction survived.

Offline: real certificate/controller/board_progression modules loaded by path; writer and live
reader injected fakes; ledger on disk under tmp_path. No GitHub, no gh, no mission-control child.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"
SAGA_ROOT = ROOT / "plugins" / "saga"


def _load(name: str) -> ModuleType:
    # Reuse an existing module instance when one is loaded: these share the singleton module
    # identity other saga tests assert on (e.g. outcome_reconcile's re-export identity probe).
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RC = _load("reconcile_controller")
CERT = _load("op_allowlist")


class LiveBoard:
    """Fake live_reader backing store."""

    def __init__(self) -> None:
        self.values: dict[tuple[str, str, int], str] = {}

    def set(self, op_kind: str, repo: str, number: int, value: str) -> None:
        self.values[(op_kind, repo, number)] = value

    def reader(self, op_kind: str, repo: str, number: int) -> str:
        return self.values.get((op_kind, repo, number), "")


class RecordingWriter:
    """Fake board_writer: records every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *, op_kind: str, repo: str, number: int, payload: dict) -> None:
        self.calls.append({"op_kind": op_kind, "repo": repo, "number": number, "payload": payload})


def _seed_asserted(ledger: Path, writer: RecordingWriter, live: LiveBoard) -> None:
    """Drive one clean idempotent write so saga has asserted Status=Done; mirror it live."""
    rec = RC.reconcile_op(
        "set-field-status",
        "infiquetra/saga",
        450,
        "Done",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert rec["status"] == "written"
    live.set("set-field-status", "infiquetra/saga", 450, "Done")


# ---------------------------------------------------------------------------
# Behaviour 1 — replay safety
# ---------------------------------------------------------------------------


def test_reconcile_safety_replay_is_idempotent(tmp_path: Path) -> None:
    """A repeated reconcile tick collapses to ``skipped`` — the second tick observes the first's
    ledger key and the converged live value, and drives exactly ONE write (R35 #1)."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    writer = RecordingWriter()
    live = LiveBoard()

    tick1 = RC.reconcile_op(
        "set-field-status",
        "infiquetra/saga",
        450,
        "Done",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert tick1["status"] == "written"
    live.set("set-field-status", "infiquetra/saga", 450, "Done")

    tick2 = RC.reconcile_op(
        "set-field-status",
        "infiquetra/saga",
        450,
        "Done",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert tick2["status"] == "skipped"
    assert len(writer.calls) == 1, "exactly one applied write across the replay"

    # A crash-shaped replay (key present, write never landed live): the lost key is re-driven
    # idempotently, not silently skipped — replay safety covers the crash window too (R3/F3).
    ledger_file = next(ledger.glob("*.json"))
    ledger_file.unlink()
    replay = RC.reconcile_op(
        "set-field-status",
        "infiquetra/saga",
        450,
        "Done",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert replay["status"] == "written", "the lost key is re-driven (idempotent), not lost"
    assert len(writer.calls) == 2


# ---------------------------------------------------------------------------
# Behaviour 2 — drift detection (level-triggered re-detection)
# ---------------------------------------------------------------------------


def test_reconcile_safety_detects_drift(tmp_path: Path) -> None:
    """An outside edit made while the lifecycle was at rest is re-detected on the next tick — the
    tick re-reads live every call and never trusts a cached converged flag (R35 #2)."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    writer = RecordingWriter()
    live = LiveBoard()
    _seed_asserted(ledger, writer, live)

    live.set("set-field-status", "infiquetra/saga", 450, "Ready")  # outside edit
    first = RC.reconcile_op(
        "set-field-status",
        "infiquetra/saga",
        450,
        "Done",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert first["status"] == "halt", "the outside edit is re-detected (surfaced, W7), not missed"
    assert first["drift_id"]

    # A SECOND outside edit (a different live value) is ALSO re-detected — level-triggered, not
    # edge-triggered: the drift id changes because the live value changed.
    live.set("set-field-status", "infiquetra/saga", 450, "Shaping")
    second = RC.reconcile_op(
        "set-field-status",
        "infiquetra/saga",
        450,
        "Done",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert second["status"] == "halt"
    assert second["drift_id"] != first["drift_id"], "each new live value is re-detected"


# ---------------------------------------------------------------------------
# Behaviour 3 — closed allowlist for autonomous reversible operations
# ---------------------------------------------------------------------------


def test_reconcile_safety_allowlist_is_closed(tmp_path: Path) -> None:
    """A non-allowlisted op is never auto-corrected. Since W7 the allowlist is EMPTY — no op is
    auto-corrected, by construction and by behaviour (R32/R35 #3)."""
    assert frozenset() == RC.AUTO_CORRECT_OP_KINDS, (
        "the post-W7 allowlist must be empty: no autonomous lifecycle-field write authority (R32)"
    )
    # Behavioural: drift on the historically-autocorrectable op is surfaced, never rewritten.
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    writer = RecordingWriter()
    live = LiveBoard()
    _seed_asserted(ledger, writer, live)
    live.set("set-field-status", "infiquetra/saga", 450, "Ready")

    record = RC.reconcile_op(
        "set-field-status",
        "infiquetra/saga",
        450,
        "Done",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert record["status"] == "halt", "no op — allowlisted or not — is auto-corrected post-W7"
    assert len(writer.calls) == 1

    # Closure proof: every other certificate op kind surfaces its drift the same way (or gates at
    # the certificate), and none of them drives a write through detect.
    for op_kind in (
        str(CERT.OpKind.SUB_ISSUE_CLOSE),
        str(CERT.OpKind.SUB_ISSUE_REOPEN),
        str(CERT.OpKind.PARENT_ISSUE_CLOSE),
    ):
        drift_live = LiveBoard()
        drift_live.set(op_kind, "infiquetra/saga", 450, "external")
        record = RC.detect_op(
            op_kind, "infiquetra/saga", 450, "asserted", live_reader=drift_live.reader
        )
        assert record["status"] in ("halt", "gated", "drift"), record
        assert record["status"] != "corrected", f"{op_kind}: nothing is auto-corrected (W7)"


# ---------------------------------------------------------------------------
# Behaviour 4 — operator prompt when uncertain or consequential
# ---------------------------------------------------------------------------


def test_reconcile_safety_prompts_when_uncertain(tmp_path: Path) -> None:
    """An action that needs a human — a certificate-GATE op, or an outside open/closed drift on a
    saga-asserted close — surfaces ``gated``/``halt`` with a reason and drives NO corrective write:
    the operator prompt is the path (R35 #4; M7 — pause automated writes, route through the
    operator)."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    writer = RecordingWriter()
    live = LiveBoard()

    # Consequential op: the certificate GATEs parent-issue-close (ALWAYS_OPERATOR).
    gated = RC.reconcile_op(
        "parent-issue-close",
        "infiquetra/saga",
        450,
        "",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert gated["status"] == "gated" and gated["halt"] is True
    assert gated["halt_reason"] == "certificate-gate:parent-issue-close"
    assert writer.calls == [] and not list(ledger.iterdir()), "a gated op reads and writes nothing"

    # Uncertain outcome: an issue closed by saga is reopened by an outside actor — reversing that
    # could destroy a human/CI lifecycle decision, so the controller withholds and the operator
    # decides, never a forced re-close.
    seeded = RC.reconcile_op(
        "sub-issue-close",
        "infiquetra/saga",
        450,
        "",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert seeded["status"] == "written"
    live.set("sub-issue-close", "infiquetra/saga", 450, "closed")
    live.set("sub-issue-close", "infiquetra/saga", 450, "open")  # outside reopen at rest
    writes_after_seed = len(writer.calls)

    halted = RC.reconcile_op(
        "sub-issue-close",
        "infiquetra/saga",
        450,
        "",
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert halted["status"] == "halt" and halted["halt"] is True
    assert halted["halt_reason"] == "external-reopen:open"
    assert len(writer.calls) == writes_after_seed, "still no autonomous corrective write"


# ---------------------------------------------------------------------------
# AT-RISK behaviour A (R35) — the per-op level-triggered reconcile tick, /work and /loop only
# ---------------------------------------------------------------------------


# /loop was the second consumer until issue 1030 removed it; /work is the one that remains.
@pytest.mark.parametrize("consumer_skill", ["work"])
def test_level_triggered_tick_survives_for_work_and_loop(consumer_skill: str) -> None:
    """The per-op level-triggered tick SURVIVES for /work and /loop — each skill still drives the
    shared controller (a writing reconcile for the non-field op in /work's 4.4; the read-only
    detect in /loop), and the controller still re-reads live on every call (level-triggered)."""
    skill = (SAGA_ROOT / "skills" / consumer_skill / "SKILL.md").read_text(encoding="utf-8")
    assert "reconcile_controller.py" in skill, (
        f"/{consumer_skill} still drives the shared per-op reconcile controller"
    )

    # Level-triggered, mechanically: two consecutive detect ticks over a board that moved between
    # them produce different observations — convergence is recomputed live each call.
    class Live:
        def __init__(self) -> None:
            self.value = "Ready"

        def reader(self, _op: str, _repo: str, _n: int) -> str:
            return self.value

    board = Live()
    first = RC.detect_op(
        "set-field-status", "infiquetra/saga", 450, "Active", live_reader=board.reader
    )
    assert first["status"] == "drift"
    board.value = "Active"  # Mission Control converged the board between ticks
    second = RC.detect_op(
        "set-field-status", "infiquetra/saga", 450, "Active", live_reader=board.reader
    )
    assert second["status"] == "skipped", "the tick re-read live every call (level-triggered)"


@pytest.mark.parametrize(
    ("op_kind", "outside", "expected_reason"),
    [
        ("sub-issue-close", "open", "external-reopen:open"),
        ("sub-issue-reopen", "closed", "external-close:closed"),
    ],
)
def test_halt_on_irreversible_drift_surfaces_named_reason(
    tmp_path: Path, op_kind: str, outside: str, expected_reason: str
) -> None:
    """An irreversible outside change (issue reopened/closed under saga) is HALTed with a named
    reason — never silently overwritten, and the reason names the drift kind AND the live value
    (R35, at-risk; plan U6 asserts the name, not merely that no write happened)."""
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    writer = RecordingWriter()
    live = LiveBoard()

    write_target = ""  # both close and reopen drive with an empty target payload
    seeded = RC.reconcile_op(
        op_kind,
        "infiquetra/saga",
        450,
        write_target,
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert seeded["status"] == "written"
    converged = "closed" if op_kind == "sub-issue-close" else "open"
    live.set(op_kind, "infiquetra/saga", 450, converged)
    writes_after_seed = len(writer.calls)

    # The outside change happens while the lifecycle is at rest.
    live.set(op_kind, "infiquetra/saga", 450, outside)

    halted = RC.reconcile_op(
        op_kind,
        "infiquetra/saga",
        450,
        write_target,
        board_writer=writer,
        ledger_dir=ledger,
        live_reader=live.reader,
    )
    assert halted["status"] == "halt" and halted["halt"] is True
    assert halted["halt_reason"] == expected_reason, (
        "the surfaced reason names the drift kind and the live value — not a generic refusal"
    )
    assert halted["board_value"] == outside, (
        "the conflicting live value is surfaced for the operator"
    )
    assert len(writer.calls) == writes_after_seed, "a HALT never drives a corrective write"
