#!/usr/bin/env python3
"""deploy_handoff.py — positive handoff-ack envelope at the saga -> deploy edge (issue #395).

`/work` owns the PR loop through merge and explicitly disclaims deploy. Nothing today requires
deploy to acknowledge picking a merged item up, so a dropped baton is invisible. This sidecar
module owns the acceptance contract that closes that gap (R1/R3/R4/R5):

* ``offer`` mints an ack token (``secrets.token_hex``) and writes a per-saga sidecar
  ``.claude/saga/sagas/<saga_id>/deploy_handoff.json`` with the gate-or-auto payload. The payload
  and ``pr_refs`` are read from the saga record (``state.json["sagas"][saga_id]``, KTD3) — an
  absent posture reads the safe ``gate`` default (R5) and is never overridable from an offer-time
  argument (R2). A repeat ``offer`` (a crashed deploy run, F2 recovery) mints a *fresh*
  token and moves the prior envelope to ``superseded`` so a stale token can never be acked (KTD4).
* ``accept`` is write-once (KTD4): it records ``{token, acknowledged_at, acknowledged_by,
  evidence}`` only on the deploy side. A second accept raises ``AlreadyAcknowledgedError`` (mirrors
  the ship-receipt module's own double-write error, removed in #1027); accept without a prior offer,
  a token mismatch, or an empty
  identity/evidence all fail loud with named errors — ownership is never released silently.
* ``authorize_promotion`` honors the payload mechanically, not by convention (KTD5): ``gate`` ->
  blocked pending explicit confirmation; ``auto`` -> authorized for ``nonprod`` only;
  ``staging``/``production`` always require confirmation regardless of payload.
* ``reconcile`` (U3, read-only) derives status on read, per-saga or via an ``--all`` sweep across
  ``.claude/saga/sagas/*/deploy_handoff.json``: an offer with no ack is
  ``handed-off-unacknowledged`` (R4 — ownership is never released until the ack is on disk; this
  is the dropped-baton case, F2); an offer with an ack is ``accepted``; no sidecar at all is
  ``no-handoff`` (deliberately not an error). Nothing is written back — no committed status field
  anywhere (KTD6).

Storage follows the sidecar discipline the ship-receipt and ship-teardown modules established
(both removed in #1027):
saga-id regex hardening, wrapped ``JSONDecodeError``, atomic tmp-then-``os.replace`` writes, no
``state.json`` contention. Write-once is enforced at the API layer (named errors on double-accept
/ token mismatch), NOT at the filesystem — unlike the ship receipt's ``O_CREAT|O_EXCL``, which was
inapplicable here because ``accept`` mutates an already-existing offer file. The sidecar is
git-ignored, machine-local, single-operator state; a local hand-edit or a same-instant concurrent
accept is outside the trust model, same as every sibling sidecar.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path(".claude/saga")
SAGAS_DIR = STATE_DIR / "sagas"
HANDOFF_NAME = "deploy_handoff.json"

# The gate-or-auto payload vocabulary (KTD5). ``gate`` is the safe default — a missing posture can
# never auto-fire (R5).
PAYLOAD_GATE = "gate"
PAYLOAD_AUTO = "auto"
VALID_PAYLOADS: tuple[str, ...] = (PAYLOAD_GATE, PAYLOAD_AUTO)

# Promotion-authorization decisions returned by ``authorize_promotion`` (KTD5).
DECISION_BLOCKED = "blocked"
DECISION_AUTHORIZED = "authorized"

# Deploy environment vocabulary consulted by ``authorize_promotion``. Only ``nonprod`` is ever
# eligible for an auto authorization; ``staging``/``production`` always require confirmation.
ENV_NONPROD = "nonprod"

# Derived (never committed) reconcile statuses (R4/KTD6, issue #395 U3). ``reconcile`` computes
# these on every read — there is deliberately no status field persisted anywhere on disk.
STATUS_NO_HANDOFF = "no-handoff"
STATUS_UNACKNOWLEDGED = "handed-off-unacknowledged"
STATUS_ACCEPTED = "accepted"
# A sidecar that exists but cannot be parsed/validated. Only the --all sweep emits this: one
# corrupt sidecar must degrade to its own report line, never abort the whole dropped-baton sweep
# and mask every other saga's status (code-review P2, #395 fix round).
STATUS_INVALID_SIDECAR = "invalid-sidecar"

# saga_id becomes a path component under .claude/saga/sagas/ — a traversal value ("../..", an
# absolute path) would read/write outside the sidecar directory. Single path segment, alphanumeric
# first char (also excludes "." / ".." / a leading "-"). Duplicated, not shared, by house
# convention from the sidecar modules removed in #1027 — each sidecar module stays
# dependency-free, which is why the copy outlived its originals.
_SAGA_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


class DeployHandoffError(Exception):
    """Base error for deploy_handoff.py — always caught at the CLI boundary and reported as a
    message, never an uncaught traceback."""


class NoOfferError(DeployHandoffError):
    """``accept`` was called for a saga with no offer envelope on disk — fail-loud (KTD4). Accept
    can never invent an offer; the releasing side must ``offer`` first."""

    def __init__(self, saga_id: str, path: Path) -> None:
        self.saga_id = saga_id
        self.path = path
        super().__init__(
            f"no deploy handoff offered yet for saga {saga_id!r} (looked at {path}); the releasing "
            "side must run `offer` before deploy can `accept`"
        )


class AlreadyAcknowledgedError(DeployHandoffError):
    """The current offer already carries an ack — accept is write-once (KTD4). The existing ack is
    left untouched; a second accept is never a silent overwrite (mirrors ReceiptExistsError)."""

    def __init__(self, saga_id: str, ack: dict[str, Any]) -> None:
        self.saga_id = saga_id
        self.ack = ack
        who = ack.get("acknowledged_by", "?")
        when = ack.get("acknowledged_at", "?")
        super().__init__(
            f"deploy handoff for saga {saga_id!r} was already acknowledged by {who!r} at {when} — "
            "accept is write-once; re-offer to rotate the token if the baton must move again"
        )


class TokenMismatchError(DeployHandoffError):
    """``accept`` supplied a token that does not match the current offer's token (KTD4). A stale
    token — e.g. one belonging to a superseded envelope — can never ack the live offer."""

    def __init__(self, saga_id: str, supplied: str, expected: str) -> None:
        self.saga_id = saga_id
        self.supplied = supplied
        self.expected = expected
        super().__init__(
            f"token mismatch accepting deploy handoff for saga {saga_id!r}: supplied token does not "
            "match the current offer (a superseded/stale token can never ack the live envelope)"
        )


class EmptyAckFieldError(DeployHandoffError):
    """``accept`` was called with an empty ``--by`` or ``--evidence`` (KTD4 requires both
    non-empty) — an anonymous or evidence-free ack would defeat the durable transfer record."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(
            f"deploy handoff accept requires a non-empty {field}; refusing to record an ack with an "
            f"empty {field} (KTD4: acknowledged_by and evidence must both be present)"
        )


class InvalidHandoffError(DeployHandoffError):
    """The on-disk sidecar is not valid JSON or is not a JSON object — always wrapped, never a bare
    ``JSONDecodeError``/``KeyError`` escaping to the CLI boundary."""


def _validate_saga_id(saga_id: str) -> str:
    if not _SAGA_ID_RE.fullmatch(saga_id):
        raise DeployHandoffError(
            f"invalid saga_id {saga_id!r}: must be a single path-safe segment "
            "matching [A-Za-z0-9][A-Za-z0-9._-]* (e.g. issue-395)"
        )
    return saga_id


def handoff_path(repo_root: Path, saga_id: str) -> Path:
    return repo_root / SAGAS_DIR / _validate_saga_id(saga_id) / HANDOFF_NAME


def _read_saga_record(repo_root: Path, saga_id: str) -> dict[str, Any]:
    """Read a saga's summary out of the derived ``state.json`` index (issue #395, U2, KTD3).

    The gate-or-auto posture is authored once at ``/plan`` time and persisted on the saga (the
    ``deploy_autonomy`` field), which ``saga.py`` mirrors into ``state.json["sagas"][saga_id]``.
    ``offer`` reads it here — never re-derives or re-asks it (R2) — via the same
    ``read_state(root)["sagas"][saga_id]`` pattern ``handoff_envelope.read_state`` uses. A missing
    or corrupt index, or an unknown saga, is ``{}``: ``offer`` then falls back to the safe ``gate``
    default and an empty ``pr_refs`` (R5 — a missing posture can never auto-fire). This read never
    writes and never shells out.
    """
    state_path = repo_root / STATE_DIR / "state.json"
    if not state_path.exists():
        return {}
    try:
        loaded = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    sagas = loaded.get("sagas")
    if not isinstance(sagas, dict):
        return {}
    record = sagas.get(saga_id)
    return record if isinstance(record, dict) else {}


def build_envelope(
    saga_id: str,
    *,
    payload: str = PAYLOAD_GATE,
    offered_by: str = "",
    pr_refs: list[str] | None = None,
    token: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Build the offer envelope dict (KTD2 schema) without writing anything to disk.

    In this unit ``payload`` defaults to ``gate`` — the safe direction (R5). U2 derives it from the
    saga record and passes it through; there is deliberately no way to widen it to ``auto`` from an
    offer-time CLI flag (R2). Minting the token here (``secrets.token_hex``) keeps the builder and
    the on-disk offer in lockstep.
    """
    _validate_saga_id(saga_id)
    if payload not in VALID_PAYLOADS:
        raise DeployHandoffError(
            f"invalid deploy-autonomy payload {payload!r}; expected one of {VALID_PAYLOADS}"
        )
    return {
        "token": token or secrets.token_hex(16),
        "payload": payload,
        "offered_at": now or datetime.now(UTC).isoformat(),
        "offered_by": offered_by,
        "saga_id": saga_id,
        "pr_refs": list(pr_refs or []),
    }


def _read_sidecar(repo_root: Path, saga_id: str) -> dict[str, Any] | None:
    """Read the sidecar's ``{envelope, ack, superseded}`` record. Truly-absent (nothing at the
    path at all) is ``None`` — a saga that was never offered has no handoff, deliberately NOT an
    error. EVERYTHING else that prevents a clean read raises ``InvalidHandoffError`` — malformed
    JSON, a non-object body, a dangling symlink, a directory/FIFO/socket in place of the file, or
    an unreadable file (falsification re-review, #395). The regular-file ``stat`` check runs
    BEFORE ``open()`` because a FIFO with no writer makes a blocking ``open()`` hang forever —
    nothing is ever raised, so no except clause downstream could save the reconcile sweep."""
    path = handoff_path(repo_root, saga_id)
    if not os.path.lexists(path):
        return None
    try:
        mode = os.stat(path).st_mode  # follows symlinks
    except FileNotFoundError as exc:
        # lexists but stat fails: a dangling symlink — something IS there (a lost/partial offer),
        # so surface it rather than reading as never-offered.
        raise InvalidHandoffError(f"deploy_handoff.json at {path} is a dangling symlink") from exc
    except OSError as exc:
        raise InvalidHandoffError(f"deploy_handoff.json at {path} is unreadable: {exc}") from exc
    if not stat.S_ISREG(mode):
        raise InvalidHandoffError(
            f"deploy_handoff.json at {path} is not a regular file (directory/FIFO/socket)"
        )
    try:
        with open(path, encoding="utf-8") as handle:
            try:
                data = json.load(handle)
            except json.JSONDecodeError as exc:
                raise InvalidHandoffError(
                    f"deploy_handoff.json at {path} is not valid JSON: {exc}"
                ) from exc
    except OSError as exc:
        raise InvalidHandoffError(f"deploy_handoff.json at {path} is unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise InvalidHandoffError(f"deploy_handoff.json at {path} is not a JSON object")
    return data


def _write_sidecar(repo_root: Path, saga_id: str, record: dict[str, Any]) -> Path:
    path = handoff_path(repo_root, saga_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace (the idiom saga.py's _atomic_write uses, and the removed ship-teardown
    # manifest writer used) — a
    # crash mid-write must never leave a torn sidecar.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def offer(
    repo_root: Path,
    saga_id: str,
    *,
    payload: str | None = None,
    offered_by: str = "",
    pr_refs: list[str] | None = None,
    token: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Mint an offer and write the sidecar (R1). Returns the full ``{envelope, ack, superseded}``
    record.

    The gate-or-auto ``payload`` and the merged ``pr_refs`` are sourced from the operator-authored
    saga record (``state.json["sagas"][saga_id]``, U2/KTD3) when the caller does not pass them
    explicitly: ``payload`` reads ``saga.deploy_autonomy or "gate"`` (absent always reads ``gate``,
    R5) and ``pr_refs`` reads the saga's ``pr_refs`` (absent reads ``[]``). The posture is READ,
    never re-derived or re-asked at offer time, and there is no offer-time CLI flag that can widen
    it to ``auto`` (R2) — the only way to authorize ``auto`` is to have authored it on the saga.

    A repeat offer (F2 recovery) mints a fresh token and moves the prior envelope — with whatever
    ack state it carried — into ``superseded`` (KTD4), so an old token can never ack the new
    envelope. ``ack`` starts ``null``: ownership is not released until the deploy side accepts (R4).
    """
    _validate_saga_id(saga_id)
    if payload is None or pr_refs is None:
        saga_record = _read_saga_record(repo_root, saga_id)
        if payload is None:
            record_payload = saga_record.get("deploy_autonomy")
            payload = record_payload if record_payload else PAYLOAD_GATE
        if pr_refs is None:
            record_refs = saga_record.get("pr_refs")
            pr_refs = [str(ref) for ref in record_refs] if isinstance(record_refs, list) else []
    existing = _read_sidecar(repo_root, saga_id)
    superseded: list[dict[str, Any]] = []
    if existing is not None:
        prior = existing.get("superseded")
        if isinstance(prior, list):
            superseded.extend(prior)
        prior_envelope = existing.get("envelope")
        if isinstance(prior_envelope, dict):
            superseded.append({"envelope": prior_envelope, "ack": existing.get("ack")})

    record: dict[str, Any] = {
        "envelope": build_envelope(
            saga_id,
            payload=payload,
            offered_by=offered_by,
            pr_refs=pr_refs,
            token=token,
            now=now,
        ),
        "ack": None,
        "superseded": superseded,
    }
    _write_sidecar(repo_root, saga_id, record)
    return record


def accept(
    repo_root: Path,
    saga_id: str,
    token: str,
    *,
    acknowledged_by: str,
    evidence: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Record the deploy side's write-once ack (R3, KTD4). Returns the updated record.

    Fails loud with a named error on: no prior offer (``NoOfferError``), an already-acknowledged
    offer (``AlreadyAcknowledgedError``), a token that does not match the live offer
    (``TokenMismatchError``), or an empty identity/evidence (``EmptyAckFieldError``). Only the
    deploy side writes the ack — the releasing side's ``offer`` never does (R3).
    """
    _validate_saga_id(saga_id)
    if not acknowledged_by or not acknowledged_by.strip():
        raise EmptyAckFieldError("acknowledged_by (--by)")
    if not evidence or not evidence.strip():
        raise EmptyAckFieldError("evidence (--evidence)")

    path = handoff_path(repo_root, saga_id)
    record = _read_sidecar(repo_root, saga_id)
    envelope = record.get("envelope") if isinstance(record, dict) else None
    if record is None or not isinstance(envelope, dict):
        raise NoOfferError(saga_id, path)

    existing_ack = record.get("ack")
    if isinstance(existing_ack, dict):
        raise AlreadyAcknowledgedError(saga_id, existing_ack)

    expected = str(envelope.get("token", ""))
    if token != expected:
        raise TokenMismatchError(saga_id, token, expected)

    record["ack"] = {
        "token": expected,
        "acknowledged_at": now or datetime.now(UTC).isoformat(),
        "acknowledged_by": acknowledged_by.strip(),
        "evidence": evidence.strip(),
    }
    _write_sidecar(repo_root, saga_id, record)
    return record


def authorize_promotion(record: dict[str, Any], env: str) -> dict[str, str]:
    """Consult the offer payload to authorize (or block) a promotion (R5, KTD5).

    ``gate`` blocks pending explicit confirmation; ``auto`` authorizes ``nonprod`` promotion only;
    any non-``nonprod`` environment (``staging``/``production``) always blocks regardless of
    payload. A ``gate`` payload is never silently overridden to auto-fire. Deploy's existing
    tag-promotion mechanics are a non-goal and unchanged — this only answers authorized-or-not.
    """
    envelope = record.get("envelope") if isinstance(record, dict) else None
    payload = envelope.get("payload") if isinstance(envelope, dict) else None
    normalized = env.strip().lower()

    if payload == PAYLOAD_AUTO and normalized == ENV_NONPROD:
        return {
            "decision": DECISION_AUTHORIZED,
            "env": normalized,
            "payload": PAYLOAD_AUTO,
            "reason": "auto payload authorizes nonprod promotion",
        }
    if normalized != ENV_NONPROD:
        return {
            "decision": DECISION_BLOCKED,
            "env": normalized,
            "payload": str(payload),
            "reason": f"{normalized} always requires explicit confirmation regardless of payload",
        }
    return {
        "decision": DECISION_BLOCKED,
        "env": normalized,
        "payload": str(payload),
        "reason": "gate payload blocks auto-promotion pending explicit confirmation",
    }


def read(repo_root: Path, saga_id: str) -> dict[str, Any] | None:
    """Read + validate the sidecar (never writes). ``None`` when no handoff has been offered."""
    return _read_sidecar(repo_root, saga_id)


def _offer_age_seconds(offered_at: Any, now: datetime) -> float | None:
    """Best-effort age of an offer in seconds. ``None`` when ``offered_at`` is missing or not a
    parseable ISO timestamp — age is diagnostic, never load-bearing for the derived status."""
    if not isinstance(offered_at, str) or not offered_at:
        return None
    try:
        offered = datetime.fromisoformat(offered_at)
    except ValueError:
        return None
    if offered.tzinfo is None:
        offered = offered.replace(tzinfo=UTC)
    return (now - offered).total_seconds()


def reconcile_one(repo_root: Path, saga_id: str, *, now: str | None = None) -> dict[str, Any]:
    """Derive the read-only status for a single saga's handoff (R4, KTD6, issue #395 U3).

    Ownership is never released until the deploy side's explicit ``accept`` is on disk — this never
    inspects git, merge state, or anything else to guess "done" (derive-on-read discipline). Three
    outcomes, all computed fresh on every call, nothing persisted:

    * no sidecar on disk at all -> ``no-handoff`` (deliberately NOT an error — a saga that was
      never offered toward deploy has nothing to reconcile);
    * an offer with no ack -> ``handed-off-unacknowledged``, naming the saga and the offer's age —
      this is the dropped-baton case (F2): a merge followed by silence surfaces here instead of
      vanishing or silently reading ``deployed``/``done``;
    * an offer with an ack -> ``accepted``.
    """
    _validate_saga_id(saga_id)
    record = _read_sidecar(repo_root, saga_id)
    if record is None:
        return {"saga_id": saga_id, "status": STATUS_NO_HANDOFF}

    envelope = record.get("envelope") if isinstance(record, dict) else None
    ack = record.get("ack") if isinstance(record, dict) else None

    if isinstance(ack, dict):
        return {
            "saga_id": saga_id,
            "status": STATUS_ACCEPTED,
            "acknowledged_at": ack.get("acknowledged_at"),
            "acknowledged_by": ack.get("acknowledged_by"),
        }

    now_dt = datetime.fromisoformat(now) if now else datetime.now(UTC)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=UTC)
    offered_at = envelope.get("offered_at") if isinstance(envelope, dict) else None
    return {
        "saga_id": saga_id,
        "status": STATUS_UNACKNOWLEDGED,
        "offered_at": offered_at,
        "offered_by": envelope.get("offered_by") if isinstance(envelope, dict) else None,
        "offer_age_seconds": _offer_age_seconds(offered_at, now_dt),
    }


def reconcile_all(repo_root: Path, *, now: str | None = None) -> list[dict[str, Any]]:
    """Sweep every ``.claude/saga/sagas/*/deploy_handoff.json`` sidecar and derive each one's
    status (KTD6). Saga directories that never received an offer carry no sidecar and are skipped
    entirely — the sweep's purpose is surfacing dropped batons among sagas that WERE offered, not
    enumerating every saga that exists. A sidecar that exists but cannot be parsed degrades to its
    own ``invalid-sidecar`` entry naming the error — it never aborts the sweep, because one corrupt
    file masking every OTHER saga's dropped baton would defeat the F2 safety net this sweep exists
    to provide. Results are sorted by ``saga_id`` for stable output."""
    sagas_dir = repo_root / SAGAS_DIR
    if not sagas_dir.exists():
        return []
    results: list[dict[str, Any]] = []
    for child in sorted(sagas_dir.iterdir()):
        if not child.is_dir() or not _SAGA_ID_RE.fullmatch(child.name):
            continue
        # lexists, not exists: a DANGLING-symlink sidecar must reach _read_sidecar and surface
        # as invalid-sidecar (something was there — a lost offer), never silently read as
        # never-offered (falsification re-review, #395).
        if not os.path.lexists(child / HANDOFF_NAME):
            continue
        try:
            results.append(reconcile_one(repo_root, child.name, now=now))
        except (InvalidHandoffError, OSError) as exc:
            # OSError covers a sidecar that is a directory (IsADirectoryError) or unreadable
            # (PermissionError) — open() raises these BEFORE the JSON validation that produces
            # InvalidHandoffError, and they must degrade the same way, never abort the sweep
            # (falsification re-review, #395 fix round; the same class as the dirty-worktree
            # OSError degrade from #347, in the ship-teardown module removed in #1027).
            results.append(
                {"saga_id": child.name, "status": STATUS_INVALID_SIDECAR, "note": str(exc)}
            )
    return results


# --------------------------------------------------------------------------- #
# CLI — every error is caught here and reported as a message (exit 1), never a
# traceback (KTD1 house convention).
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-root", type=Path, default=Path.cwd(), help="repo root (default: cwd)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_offer = sub.add_parser("offer", help="mint an offer + write the sidecar (releasing side)")
    p_offer.add_argument("--saga-id", required=True)
    p_offer.add_argument("--offered-by", default="", help="who released the item toward deploy")
    # Deliberately NO --payload and NO --pr-ref flags: the gate-or-auto posture AND the merged PR
    # refs are read from the saga record (state.json["sagas"][saga_id], U2/KTD3), never supplied or
    # widened to `auto` from an offer-time argument (R2). Absent posture reads the safe `gate`
    # default (R5); absent pr_refs reads empty.

    p_accept = sub.add_parser("accept", help="record the write-once ack (deploy side)")
    p_accept.add_argument("--saga-id", required=True)
    p_accept.add_argument("--token", required=True)
    p_accept.add_argument("--by", required=True, dest="by", help="who accepted the handoff")
    p_accept.add_argument("--evidence", required=True, help="durable evidence of acceptance")

    p_read = sub.add_parser("read", help="read + validate the sidecar (never writes)")
    p_read.add_argument("--saga-id", required=True)

    p_reconcile = sub.add_parser(
        "reconcile",
        help="derive handed-off-unacknowledged / accepted / no-handoff status (never writes)",
    )
    reconcile_target = p_reconcile.add_mutually_exclusive_group(required=True)
    reconcile_target.add_argument("--saga-id", help="reconcile a single saga")
    reconcile_target.add_argument(
        "--all", action="store_true", help="sweep every saga with a deploy_handoff.json sidecar"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    repo_root: Path = args.repo_root

    try:
        if args.command == "offer":
            # payload + pr_refs are intentionally NOT passed: offer sources both from the saga
            # record (R2/KTD3), so the CLI cannot override the operator-authored posture.
            record = offer(
                repo_root,
                args.saga_id,
                offered_by=args.offered_by,
            )
            print(json.dumps(record, indent=2, sort_keys=True))
        elif args.command == "accept":
            record = accept(
                repo_root,
                args.saga_id,
                args.token,
                acknowledged_by=args.by,
                evidence=args.evidence,
            )
            print(json.dumps(record, indent=2, sort_keys=True))
        elif args.command == "read":
            found = read(repo_root, args.saga_id)
            if found is None:
                print(f"no deploy handoff for saga {args.saga_id!r}", file=sys.stderr)
                return 1
            print(json.dumps(found, indent=2, sort_keys=True))
        elif args.command == "reconcile":
            if args.all:
                results = reconcile_all(repo_root)
            else:
                results = [reconcile_one(repo_root, args.saga_id)]
            print(json.dumps(results, indent=2, sort_keys=True))
            # Exit-code convention follows the ship receipt's read (KTD6, removed in #1027): 0 for
            # clean or no-handoff,
            # 1 whenever any reconciled saga is handed-off-unacknowledged (dropped baton, F2) or
            # carries an unreadable sidecar (invalid-sidecar is "not clean", never silently 0).
            if any(r["status"] in (STATUS_UNACKNOWLEDGED, STATUS_INVALID_SIDECAR) for r in results):
                return 1
        else:  # pragma: no cover - argparse enforces valid choices
            parser.error(f"unknown command {args.command!r}")
            return 2
    except DeployHandoffError as exc:
        print(f"deploy_handoff: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
