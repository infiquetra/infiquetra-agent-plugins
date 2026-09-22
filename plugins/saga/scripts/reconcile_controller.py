#!/usr/bin/env python3
"""reconcile_controller — the ONE level-triggered board-reconcile controller (#450).

Kubernetes-style level-triggered convergence, shared by ``/outcome``, ``/work``, and ``/loop``.
Before #450 the two halves of board consistency lived in two ``/outcome``-only modules and were
unavailable to the other two commands:

* the **idempotency-key write** half — extracted to ``board_progression.authorize_and_write``
  (#344): authorize via ``reversibility_certificate`` (default-GATE), key into a separate ledger,
  drive an injected ``board_writer`` with bounded retry, record fail-loud. This module *composes*
  that primitive; it does not re-derive it.
* the **drift-detect/decide** half — the vocabulary and record shape (:data:`DRIFT_KINDS`,
  :func:`_drift_record`, :func:`_drift_id`, :func:`_close_satisfies_contract`) that ``/outcome``'s
  resume-time detector (``outcome_reconcile``, #295) used to own privately. #450 moves that
  vocabulary HERE and ``outcome_reconcile`` re-exports it, so the drift classification is
  single-sourced (zero behavior change to ``/outcome`` — regression-tested).

On top of those two shared halves this module adds the piece ``/work`` and ``/loop`` were missing: a
per-op **level-triggered reconcile tick** (:func:`reconcile_op`, driven in bulk by :func:`reconcile`)
that, every tick, recomputes the expected board value from durable saga fields and re-reads the live
board, so a rapid double tick converges on one write and an outside edit to a saga-owned field is
re-detected and surfaced as a named HALT — never silently corrected (W7: the controller holds no
autonomous lifecycle-field write authority; see :data:`AUTO_CORRECT_OP_KINDS`).

Threat model / self-attestation (the panel probes exact wording):

* The controller holds **no autonomous lifecycle-field write authority** (W7, SDLC R30/R32):
  :data:`AUTO_CORRECT_OP_KINDS` is empty, so no outside drift is ever silently re-written — every
  drift HALTs with a named reason for the operator, who routes any correction back through the
  mission-control mutation contract (M7: pause automated writes, route through the operator). The
  correcting write, when an operator-ratified change restores it, is **fail-closed and doubly
  gated**: it fires only when the certificate returns ``AUTHORIZED`` *and* the op is in the explicit
  :data:`AUTO_CORRECT_OP_KINDS` allowlist. Any op outside that allowlist, and any GATE verdict,
  HALTs; the controller never widens the autonomously-writable set (that lives in
  ``reversibility_certificate``, #344 KTD2).
* The controller **never reverses an outside issue open/closed change**. A drift whose correction
  would re-drive ``sub-issue-close`` / ``sub-issue-reopen`` is HALTed, not silently overwritten,
  because reversing an external close/reopen would destroy a human/CI lifecycle decision. This is a
  self-attested policy line, not a mathematical property of the certificate (which marks both those
  ops mechanically reversible); the allowlist is the enforcement, this paragraph is the claim.
* Idempotency is only as strong as the injected ``write_once`` (``os.link`` atomic create) and the
  caller serializing ticks (``/outcome`` runs under the coordinator lease). Under true simultaneous
  ticks the ledger dedups to one file; the *board* write is idempotent by nature (re-setting a field
  to the same value is a no-op).

House pattern (mirrors the other saga scripts): pure functions over explicit values, lazy imports of
heavy modules, no I/O at import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _cert():
    """The closed op allowlist. Issue 1030 removed `reversibility_certificate.py` with the ship
    ceremony that consumed its tiering; `op_allowlist.py` is the default-deny half that survives,
    and it keeps the same `authorize_write` / AUTHORIZED / GATE / OpKind surface so every call
    site below is unchanged."""
    import op_allowlist as _m  # noqa: PLC0415

    return _m


def _bp():
    import board_progression as _m  # noqa: PLC0415

    return _m


# ---------------------------------------------------------------------------
# Drift vocabulary (single-sourced here; re-exported by outcome_reconcile, #450)
# ---------------------------------------------------------------------------

# Drift kinds a detection can carry (the caller drift-holds / surfaces these).
DRIFT_KINDS = ("status-drift", "external-close", "external-reopen")

# The ONLY op kinds the controller auto-corrects on outside drift (fail-closed allowlist). Since
# W7 (SDLC run R30/R32) this set is EMPTY: Mission Control is the only routine writer of the board
# lifecycle fields, and a controller that re-wrote a field on its own authority would be a second
# routine writer. Every outside drift — reversible or not — is surfaced as a record with a named
# reason for the operator, who routes any correction through the mission-control mutation contract.
# The allowlist mechanism stays because it is the enforcement seam R35's closed-allowlist behaviour
# is tested against; its emptiness is the post-W7 posture. Widening it back is a deliberate,
# reviewed, operator-ratified change — never an accident of a new op_kind slipping through.
AUTO_CORRECT_OP_KINDS: frozenset[str] = frozenset()

#: The one correction field :func:`default_live_reader` can actually read back — it calls
#: ``outcome_github.board_status``, which has no field parameter, and :func:`_expected_live`
#: likewise takes no field. #812 admits ``Stage`` to the certificate's correction allowlist by
#: name, so the drift half of this controller must refuse to judge a field it cannot read.
#: Widening this needs a field-aware live reader, not a bigger set.
LIVE_READABLE_CORRECTION_FIELD = "Status"


def _drift_id(kind: str, repo: str, number: int, saga_value: str, board_value: str) -> str:
    """Deterministic short id so a CLI can reference a drift across invocations."""
    raw = f"{kind}:{repo}#{number}:{saga_value}->{board_value}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]  # nosec B324 — id, not a secret


def _drift_record(
    kind: str,
    *,
    repo: str,
    number: int,
    subplot_id: str,
    op_kind: str,
    saga_value: str,
    board_value: str,
    author: str = "",
) -> dict[str, Any]:
    return {
        "kind": kind,
        "repo": repo,
        "number": number,
        "subplot_id": subplot_id,
        "op_kind": op_kind,
        "saga_value": saga_value,
        "board_value": board_value,
        "author": author,
        "drift_id": _drift_id(kind, repo, number, saga_value, board_value),
    }


def _close_satisfies_contract(node: Any) -> bool:
    """Whether closing this leaf's issue satisfies its completion contract (mirrors
    ``outcome_orchestrator.barrier_satisfied``).

    A non-code, non-child leaf's contract IS "tracking issue closed", so a close satisfies it. A
    code leaf's contract is "PR merged", so a closed issue does NOT satisfy it — a close there is
    drift regardless of stateReason.
    """
    return (not getattr(node, "is_outcome", False)) and getattr(node, "kind", "") != "code"


# ---------------------------------------------------------------------------
# Level-triggered expected/live helpers
# ---------------------------------------------------------------------------


def _expected_live(
    op_kind: str, target_state: str, assignments: list[tuple[str, str]] | None = None
) -> str:
    """The live value a converged board holds for ``op_kind`` — "" when the op has no readable live
    field (fail-closed: an unknown op never claims a match, so its drift is never auto-corrected).

    ``assignments`` (#927) is a lifecycle submission's ``(field, option)`` list. The expected value
    is the option assigned to the ONE field this controller can read back
    (:data:`LIVE_READABLE_CORRECTION_FIELD`), so a ``(Stage, Status)`` pair is judged on its
    ``Status`` half — exactly as readable as a ``Status``-only write — and a ``Stage``-only
    submission returns "" and is never judged. Absent, the pre-#927 behaviour is unchanged.
    """
    if op_kind == str(_cert().OpKind.SET_FIELD_STATUS):
        if assignments:
            for field_name, option_name in assignments:
                if field_name == LIVE_READABLE_CORRECTION_FIELD:
                    return option_name
            return ""
        return target_state
    if op_kind == str(_cert().OpKind.SUB_ISSUE_CLOSE):
        return "closed"
    if op_kind == str(_cert().OpKind.SUB_ISSUE_REOPEN):
        return "open"
    return ""


def _drift_kind_for(op_kind: str) -> str:
    """Map a drifting op to its :data:`DRIFT_KINDS` label (the human name for the surfaced conflict)."""
    if op_kind == str(_cert().OpKind.SET_FIELD_STATUS):
        return "status-drift"
    if op_kind == str(_cert().OpKind.SUB_ISSUE_CLOSE):
        # saga asserted closed; live shows open → someone reopened it.
        return "external-reopen"
    if op_kind == str(_cert().OpKind.SUB_ISSUE_REOPEN):
        return "external-close"
    return "status-drift"


# ---------------------------------------------------------------------------
# The per-op level-triggered reconcile primitive
# ---------------------------------------------------------------------------


def reconcile_op(
    op_kind: str,
    repo: str,
    number: int,
    target_state: str,
    *,
    board_writer: Callable[..., None],
    ledger_dir: Path,
    live_reader: Callable[[str, str, int], str] | None = None,
    now: Callable[[], float] = time.time,
    max_attempts: int = 3,
    payload: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    write_once: Callable[[Path, str], bool] | None = None,
) -> dict[str, Any]:
    """Reconcile ONE board op against durable saga intent, level-triggered.

    The tick recomputes ``target_state`` fresh from durable fields (the caller's job) and re-reads the
    live board every call — it never trusts a cached "already handled" flag, so a crash between
    compute and ledger write is retried, not skipped (R3/F3).

    Decision order (fail-closed):

    1. Certificate GATE on ``op_kind`` → ``{"status":"gated","halt":True}`` — no read, no write.
    2. **Ledger key absent** (never driven, or the key was lost to a crash) → delegate to
       ``board_progression.authorize_and_write``: it drives the writer if absent and records the key
       on success. A rapid second tick that finds the key present no-ops (R4/F1); a landed-but-
       unrecorded write is safely re-driven (idempotent) then recorded (F3).
    3. **Ledger key present** (saga asserted ``target_state``) → re-read live:
       * no ``live_reader`` / unreadable / live matches expected → ``{"status":"skipped"}`` (converged).
       * live diverges → ``{"status":"halt","halt":True}`` with a named ``halt_reason`` — every
         outside change is surfaced, never overwritten. Since W7 the auto-correct allowlist
         (:data:`AUTO_CORRECT_OP_KINDS`) is empty, so this is the only drift outcome: the outside
         edit — irreversible open/closed change or reversible field edit alike — needs the operator,
         who routes any correction through the mission-control mutation contract (R5; M7).

    Returns one record dict. ``extra`` is merged into every record (e.g. ``{"subplot_id": ...}``).
    """
    cert = _cert()
    bp = _bp()
    wo = write_once if write_once is not None else bp._write_once  # noqa: SLF001
    base: dict[str, Any] = dict(extra or {})
    base.update(op_kind=op_kind, repo=repo, number=number, target_state=target_state)

    # (1) The verdict MUST come from the certificate; never re-derived here. A GATE on the expected
    #     op is a fail-closed HALT — the op needs a human, so no autonomous read or write happens.
    verdict = cert.authorize_write(op_kind)
    if verdict != cert.AUTHORIZED:
        return {
            "status": "gated",
            "halt": True,
            "halt_reason": f"certificate-gate:{op_kind}",
            "verdict": "GATE",
            **base,
        }

    field_kw: str | None = None
    state_kw = target_state
    assignments: list[tuple[str, str]] = []
    if op_kind == "set-field-status":
        # #927: the op may carry a whole ``(Stage, Status)`` pair in its payload. Absent
        # ``assignments`` this normalizes to exactly the single ``field`` (default ``Status``)
        # this controller lifted before, so every pre-#927 caller is byte-unchanged.
        try:
            assignments = bp.normalize_assignments(payload, target_state)
        except ValueError as exc:
            return {
                "status": "gated",
                "halt": True,
                "halt_reason": f"malformed-assignments:{exc}",
                "verdict": "GATE",
                **base,
            }
        # EVERY field in the submission is authorized, not just the first: a pair whose second half
        # names an unauthorized field must gate whole rather than land one legal half.
        for field_name, _option in assignments:
            if cert.authorize_correction_field(field_name) != cert.AUTHORIZED:
                base["field"] = field_name
                return {
                    "status": "gated",
                    "halt": True,
                    "halt_reason": f"certificate-gate:correction-field:{field_name}",
                    "verdict": "GATE",
                    **base,
                }
        # Both key-minting sites (here and ``board_progression.authorize_and_write``) derive the
        # identity from the same helper, so a re-announce meets the key the first write left and a
        # pair can never collide with a Status-only write to the same option.
        field_kw, state_kw = bp.assignment_identity(assignments)
        base["field"] = field_kw

    key = cert.idempotency_key(op_kind, repo, number, state_kw, field=field_kw)
    ledger_file = ledger_dir / bp._safe_ledger_name(key)  # noqa: SLF001

    # (2) Absent key → normal idempotent write / crash-safe resume, via the shared write mechanism.
    if not ledger_file.exists():
        pay: dict[str, Any] = dict(payload or {})
        if len(assignments) > 1:
            # Carry the whole pair, never the composite identity: ``field`` names one field and
            # ``Stage+Status`` is not one. The writer reads ``assignments``.
            pay["assignments"] = [[name, option] for name, option in assignments]
        elif field_kw is not None:
            pay.setdefault("field", field_kw)
        return bp.authorize_and_write(
            op_kind,
            repo,
            number,
            target_state,
            board_writer=board_writer,
            ledger_dir=ledger_dir,
            now=now,
            max_attempts=max_attempts,
            payload=pay or payload,
            extra=extra,
            write_once=wo,
        )

    # (3) Present key → level-triggered drift check against live.
    if live_reader is None:
        return {"status": "skipped", "key": key, **base}
    # Fail closed on a submission this controller cannot read back (#812). Comparing the live
    # Status against another field's value would manufacture a false drift record — a correction
    # request driven by a reading that was never about that field. Skip instead of guessing.
    #
    # The question is whether the submission CONTAINS the readable field, not whether its ledger
    # identity equals it. #927's pair mints the composite identity ``Stage+Status``, which can never
    # equal ``Status``, so an identity comparison sent EVERY pair down this branch: from the second
    # tick onward the controller returned ``skipped`` without calling ``live_reader`` at all, and
    # the level-triggered convergence loop — the one property this module exists to provide — was
    # off for every lifecycle write Plan, Work and Orchestrate make. The ``Status`` half of a pair
    # is exactly as readable as a ``Status``-only write; a ``Stage``-only submission still is not.
    expected_live = _expected_live(op_kind, target_state, assignments or None)
    if op_kind == "set-field-status" and not expected_live:
        return {
            "status": "skipped",
            "key": key,
            "note": (f"live drift-check reads {LIVE_READABLE_CORRECTION_FIELD}, not {field_kw}"),
            **base,
        }
    live = live_reader(op_kind, repo, number)
    if not live:
        return {"status": "skipped", "key": key, "note": "live unreadable", **base}

    if expected_live and live == expected_live:
        return {"status": "skipped", "key": key, **base}

    # OUTSIDE DRIFT: the board moved away from what saga asserted. Since W7 the auto-correct
    # allowlist is empty, so there is no autonomous rewrite branch at all: every drift HALTs with a
    # named reason. Reversing an outside issue open/closed change would destroy a human/CI lifecycle
    # decision; re-writing a drifted field would make this controller a second routine writer of a
    # board lifecycle field (SDLC R30). Both are the operator's to resolve (M7). If
    # AUTO_CORRECT_OP_KINDS is ever deliberately re-widened, restore a bounded-retry auto-correct
    # branch HERE, doubly gated (certificate AUTHORIZED + allowlist membership) — never silently.
    drift_kind = _drift_kind_for(op_kind)
    # The saga-asserted value the drift is measured against is the one the READ was about: for a
    # lifecycle submission that is the readable half, which equals ``target_state`` for every
    # single-field write and is the ``Status`` assignment for a pair.
    saga_value = expected_live if op_kind == "set-field-status" else target_state
    drift_id = _drift_id(drift_kind, repo, number, saga_value, live)
    return {
        "status": "halt",
        "halt": True,
        "halt_reason": f"{drift_kind}:{live}",
        "drift_id": drift_id,
        "board_value": live,
        "key": key,
        **base,
    }


# ---------------------------------------------------------------------------
# Read-only drift detection (the /loop tick's post-W7 shape, SDLC R33)
# ---------------------------------------------------------------------------


def detect_op(
    op_kind: str,
    repo: str,
    number: int,
    target_state: str,
    *,
    live_reader: Callable[[str, str, int], str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read-only level-triggered drift check for an op the lifecycle has already asserted.

    W7 (SDLC R30/R33): ``/loop`` retains drift detection but holds no write authority, so its
    reconcile tick is this pure read: re-read the live board, compare against the saga-asserted
    value, and NEVER write — not on convergence (nothing to do) and not on drift (the correction
    routes through the operator and the mission-control mutation contract, M7). Unlike
    :func:`reconcile_op` there is no ledger dependency: the caller-derived ``target_state`` IS the
    assertion under test, so this never mints a ledger key and can never drive a write.

    Returns one record dict:

    * ``{"status": "skipped", ...}`` — converged: the live board already holds the asserted value.
    * ``{"status": "skipped", "note": "live unreadable", ...}`` — fail-closed: no value was read,
      so nothing is judged and no drift is claimed.
    * ``{"status": "drift", ...}`` — a reversible outside edit to a board lifecycle field. Carries
      ``drift_kind`` / ``drift_id`` / ``board_value`` and the prepared ``target_state`` the operator
      confirms and submits back through the mutation contract.
    * ``{"status": "halt", "halt": True, ...}`` with a named ``halt_reason`` — an irreversible
      outside open/closed change; surface it, never overwrite.
    """
    cert = _cert()
    base: dict[str, Any] = dict(extra or {})
    base.update(op_kind=op_kind, repo=repo, number=number, target_state=target_state)

    # Same fail-closed order as reconcile_op: a GATE on the op means the op needs a human —
    # read nothing, claim nothing.
    verdict = cert.authorize_write(op_kind)
    if verdict != cert.AUTHORIZED:
        return {
            "status": "gated",
            "halt": True,
            "halt_reason": f"certificate-gate:{op_kind}",
            "verdict": "GATE",
            **base,
        }

    live = live_reader(op_kind, repo, number)
    if not live:
        return {"status": "skipped", "note": "live unreadable", **base}

    expected_live = _expected_live(op_kind, target_state)
    if expected_live and live == expected_live:
        return {"status": "skipped", **base}

    # OUTSIDE DRIFT — surfaced, never corrected (W7: no autonomous lifecycle-field writes).
    drift_kind = _drift_kind_for(op_kind)
    drift_id = _drift_id(drift_kind, repo, number, target_state, live)
    if drift_kind in ("external-close", "external-reopen"):
        return {
            "status": "halt",
            "halt": True,
            "halt_reason": f"{drift_kind}:{live}",
            "drift_id": drift_id,
            "board_value": live,
            **base,
        }
    return {
        "status": "drift",
        "drift_kind": drift_kind,
        "drift_id": drift_id,
        "board_value": live,
        "saga_value": target_state,
        **base,
    }


# ---------------------------------------------------------------------------
# The multi-intent driver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReconcileIntent:
    """One board intent the controller should converge — recomputed fresh from durable saga fields.

    ``payload`` carries op-specific extras (e.g. an ``issue-progress-comment`` body); ``extra`` is
    merged into the emitted record (e.g. ``{"subplot_id": ...}``) so consumers keep their own shape.
    """

    op_kind: str
    repo: str
    number: int
    target_state: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


def reconcile(
    intents: list[ReconcileIntent],
    *,
    board_writer: Callable[..., None],
    ledger_dir: Path,
    live_reader: Callable[[str, str, int], str] | None = None,
    now: Callable[[], float] = time.time,
    max_attempts: int = 3,
    write_once: Callable[[Path, str], bool] | None = None,
) -> list[dict[str, Any]]:
    """Reconcile every intent, returning one record per op. Command-agnostic: ``/work``, ``/loop``,
    and ``/outcome`` all pass their own recomputed intents + injected readers/writer."""
    return [
        reconcile_op(
            it.op_kind,
            it.repo,
            it.number,
            it.target_state,
            board_writer=board_writer,
            ledger_dir=ledger_dir,
            live_reader=live_reader,
            now=now,
            max_attempts=max_attempts,
            payload=it.payload or None,
            extra=it.extra or None,
            write_once=write_once,
        )
        for it in intents
    ]


# ---------------------------------------------------------------------------
# Production wiring (composed from the modules that already pass the gh-lane lint)
# ---------------------------------------------------------------------------


def default_live_reader(
    *, project: str = "operations", runner: Callable[..., Any] | None = None
) -> Callable[[str, str, int], str]:
    """The production ``live_reader``: read the live board Status / issue state via ``outcome_github``.

    Returns ``(op_kind, repo, number) -> live_value`` ("" on any unreadable field). No ``gh`` literal
    lives in this module — the reads route through ``outcome_github`` (already lane-linted), so the
    controller stays inside saga's write-ownership lane.
    """

    def _reader(op_kind: str, repo: str, number: int) -> str:
        # The live-state lookups went through `outcome_github`, removed with the outcome
        # coordinator by issue 1030. Returning "" means "could not read", which this controller
        # already treats as a reason not to claim drift -- the safe direction.
        del op_kind, repo, number
        return ""

    return _reader


def _repo_root_default() -> Path:
    # plugins/saga/scripts/reconcile_controller.py → parents[3] == repo root
    return Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# CLI (so the /work and /loop markdown skills can invoke a reconcile tick, #450 R2)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Level-triggered board-reconcile controller (#450)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("reconcile", help="reconcile one board op (idempotent write + drift check)")
    p.add_argument("--op", required=True, help="OpKind, e.g. set-field-status | sub-issue-close")
    p.add_argument(
        "--repo", required=True, help="owner/repo (owner used only for the key namespace)"
    )
    p.add_argument("--number", required=True, type=int)
    p.add_argument("--target-state", default="", help="e.g. Done (for set-field-status)")
    p.add_argument("--project", default="operations")
    p.add_argument("--payload", default="", help='JSON object, e.g. {"body": "..."}')
    p.add_argument(
        "--ledger-dir", default="", help="override the default board-progression ledger dir"
    )
    p.add_argument(
        "--repo-root", default="", help="override the repo root (default: from __file__)"
    )
    p.add_argument(
        "--no-drift-check",
        action="store_true",
        help="skip the live re-read (write-only tick; no outside-drift detection)",
    )

    d = sub.add_parser(
        "detect",
        help="read-only drift check for an already-asserted board op (W7: detects, never writes)",
    )
    d.add_argument("--op", required=True, help="OpKind, e.g. set-field-status")
    d.add_argument("--repo", required=True, help="owner/repo (owner used only for the record)")
    d.add_argument("--number", required=True, type=int)
    d.add_argument("--target-state", required=True, help="the saga-asserted value to verify")
    d.add_argument("--project", default="operations")

    args = parser.parse_args(argv)

    if args.cmd == "reconcile":
        bp = _bp()
        cert = _cert()
        repo_root = Path(args.repo_root).resolve() if args.repo_root else _repo_root_default()
        ledger_dir = (
            Path(args.ledger_dir).resolve()
            if args.ledger_dir
            else bp._default_ledger_dir(repo_root)  # noqa: SLF001
        )
        payload = json.loads(args.payload) if args.payload else None
        # #652: the certificate decides BEFORE mission-control is resolved. A gated op reads
        # nothing and writes nothing, so an unresolvable install must not turn an expected GATE
        # verdict (exit 0) into a resolution error (exit 1) for the callers that key on the exit
        # status. ``bp._gated_writer`` raises if it is ever reached, so a verdict divergence would
        # be a loud failed record rather than a silent no-op write.
        writer: Callable[..., None] = bp._gated_writer  # noqa: SLF001
        reader: Callable[[str, str, int], str] | None = None
        if cert.authorize_write(args.op) == cert.AUTHORIZED:
            try:
                mission_control_root, _rung = bp.resolve_mission_control_root()
            except RuntimeError as exc:
                print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
                return 1
            writer = bp.default_board_writer(
                mission_control_root=mission_control_root, project=args.project
            )
            reader = None if args.no_drift_check else default_live_reader(project=args.project)
        record = reconcile_op(
            args.op,
            args.repo,
            args.number,
            args.target_state,
            board_writer=writer,
            ledger_dir=ledger_dir,
            live_reader=reader,
            payload=payload,
        )
        print(json.dumps(record))
        # written / skipped / corrected are all healthy convergence; a gate/halt needs the operator
        # (exit 0 — expected, not a crash); only a hard write failure is non-zero.
        status = record.get("status")
        if status in ("written", "skipped", "corrected"):
            return 0
        if status in ("gated", "halt"):
            return 0
        return 1

    if args.cmd == "detect":
        # Read-only by construction: no writer is ever built, so mission-control resolution is
        # not needed and no ledger key is minted (SDLC R33: /loop detects, it does not write).
        record = detect_op(
            args.op,
            args.repo,
            args.number,
            args.target_state,
            live_reader=default_live_reader(project=args.project),
        )
        print(json.dumps(record))
        # Every detect outcome is a healthy observation (exit 0): drifted/halted detections need
        # the operator, not a crash.
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
