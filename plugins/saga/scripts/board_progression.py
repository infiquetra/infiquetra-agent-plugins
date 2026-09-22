#!/usr/bin/env python3
"""board_progression — plugin-agnostic certificate-gated autonomous board writer (#344).

Extracted from ``outcome_board_sync.reconcile_board`` (merged #279/#295): the reusable per-op
*mechanism* — authorize via ``reversibility_certificate`` (default-GATE), idempotency-key into a
separate ledger, drive an injected ``board_writer`` with bounded retry, record fail-loud — with the
``/outcome``-specific *policy* (leaf-state derivation, schema resolution, drift-hold) left in the
caller. Consumers: ``/outcome`` (via ``reconcile_board``), ``/work`` (post-merge), ``/loop``.

Because every op routes through ``reversibility_certificate.authorize_write``, a new consumer
CANNOT widen the autonomously-writable set: merge/deploy op-kinds are absent from the certificate
registry (default-GATE) and ``PARENT_ISSUE_CLOSE`` is ``ALWAYS_OPERATOR``. The allowlist lives in
the certificate, not here (#344 KTD2).

House pattern (mirrors other saga scripts): pure functions over explicit values, lazy imports of
heavy modules, no I/O at import.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _cert():
    """The closed op allowlist. Issue 1030 removed `reversibility_certificate.py` with the ship
    ceremony that consumed its tiering; `op_allowlist.py` is the default-deny half that survives,
    and it keeps the same `authorize_write` / AUTHORIZED / GATE / OpKind surface so every call
    site below is unchanged."""
    import op_allowlist as _m  # noqa: PLC0415

    return _m


def _gated_writer(**_kwargs: Any) -> None:
    """Stand-in board writer for a certificate-gated op — must never actually be invoked.

    A gated verdict short-circuits inside :func:`authorize_and_write` before any writer use, which
    is what lets the CLI skip resolving mission-control on a gated op (#652). Reaching this body
    would mean the CLI's verdict and the library's disagreed; raise rather than return, because a
    writer that silently reports success would record the idempotency key and suppress the real
    write on every future tick. Raising keeps the module's fail-loud contract: the bounded retry
    turns it into ``{"status":"failed"}`` with no ledger key, so the next tick retries.
    """
    raise AssertionError(
        "board writer invoked on a certificate-gated op — CLI and library verdicts diverged"
    )


# ---------------------------------------------------------------------------
# mission-control resolution (#620)
# ---------------------------------------------------------------------------

MISSION_CONTROL_PLUGIN = "mission-control"
MISSION_CONTROL_ENV_VAR = "MISSION_CONTROL_ROOT"
#: BOTH must exist: a root serving only the CLI or only the schema cannot serve board-sync, so a
#: half-usable install is a rung miss rather than a partial success (#620 KTD1).
MISSION_CONTROL_MARKERS = ("scripts/sdlc_manager.py", "config/sdlc-schema.json")


def resolve_mission_control_root() -> tuple[Path, int]:
    """Resolve mission-control's install root; returns ``(root, rung)`` or raises ``RuntimeError``.

    Replaces the pre-#620 ``repo_root / "plugins" / "mission-control"`` arithmetic, which only ever
    resolved inside the plugins monorepo and made every board write fail from a consumer repo.

    Both failure modes surface as ``RuntimeError`` so one ``except`` at the call site covers them
    (#620 KTD6): the ladder exhausting its rungs, and a fleet-core too old to carry
    ``plugin_resolution`` at all — the realistic post-release state while #642 leaves the install
    registry stale.
    """
    import bundled_fleet  # noqa: PLC0415

    try:
        resolution = bundled_fleet.load("plugin_resolution")
    except RuntimeError as exc:
        raise RuntimeError(
            f"board-sync: the resolved fleet-core cannot provide plugin_resolution ({exc}). "
            "Fix: update the fleet-core plugin, or repair the stale install registry at "
            "~/.claude/plugins/installed_plugins.json (see #642)."
        ) from exc
    return resolution.resolve_plugin_root(
        MISSION_CONTROL_PLUGIN,
        markers=MISSION_CONTROL_MARKERS,
        env_var=MISSION_CONTROL_ENV_VAR,
    )


# ---------------------------------------------------------------------------
# Ledger helpers (owned here; re-exported by outcome_board_sync for its readers)
# ---------------------------------------------------------------------------


def _safe_ledger_name(key: str) -> str:
    """Turn an idempotency key into a safe filename.

    Replaces the separators used by ``idempotency_key`` (``:``, ``#``, ``/``) with
    underscores.  Falls back to a SHA-1 hex digest for keys that are too long or
    contain other problematic characters after replacement.
    """
    safe = key.replace(":", "_").replace("#", "_").replace("/", "_")
    # SHA-1 fallback: 200-char limit covers all realistic keys; non-alnum guard is a
    # belt-and-suspenders check for exotic values (e.g. a future label with spaces).
    #
    # `+` is in the safe set because the composite pair identity (#927) joins the halves with it,
    # and it was not: EVERY pair key therefore took the SHA-1 fallback, so the ledger a human is
    # meant to be able to read by filename held an opaque digest for exactly the writes that
    # matter most. `+` is legal in a filename on every filesystem this runs on, and it is the
    # separator `normalize_assignments` refuses inside a field or option value, so it cannot
    # arrive from anywhere else.
    if len(safe) > 200 or not all(c.isalnum() or c in "_-.+" for c in safe):
        safe = hashlib.sha1(key.encode()).hexdigest()
    return safe + ".json"


def _write_once(path: Path, content: str) -> bool:
    """Create ``path`` atomically, refusing to clobber an existing file (write-once).

    Returns True if this call created the file, False if it already existed. Uses temp + ``os.link``
    so a crash mid-write leaves only the temp file, never a torn final file (mirrors
    ``outcome_store._write_once`` but kept local so the module is plugin-agnostic, #344 KTD1).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    try:
        os.link(tmp, path)  # atomic create; raises FileExistsError if path is taken
        return True
    except FileExistsError:
        return False
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


_COMMENT_IDEMPOTENCY_PREFIX = "saga-board-sync-idempotency"
_COMMENT_IDEMPOTENCY_RE = re.compile(
    rf"<!--\s*{re.escape(_COMMENT_IDEMPOTENCY_PREFIX)}:[0-9a-f]{{64}}\s*-->"
)


def _comment_idempotency_marker(key: str) -> str:
    """Return the hidden marker that makes additive progress comments replay-safe."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"<!-- {_COMMENT_IDEMPOTENCY_PREFIX}:{digest} -->"


def _comment_marker_in(body: str) -> str:
    """Return the first saga idempotency marker in ``body``, or ``""`` when absent."""
    match = _COMMENT_IDEMPOTENCY_RE.search(body)
    return match.group(0) if match else ""


def _append_comment_marker(body: str, key: str) -> str:
    """Append the deterministic marker exactly once, preserving visible prose."""
    marker = _comment_idempotency_marker(key)
    if marker in body:
        return body
    return f"{body.rstrip()}\n\n{marker}" if body.strip() else marker


# ---------------------------------------------------------------------------
# The assignment shape a lifecycle-field submission carries (#927)
# ---------------------------------------------------------------------------

# How a multi-assignment submission renders itself inside one idempotency key. It is a separator,
# not a delimiter anyone parses back: the key is an opaque identity string, and this only has to be
# stable and distinct from a single-field key.
ASSIGNMENT_IDENTITY_SEPARATOR = "+"

# The exact fields a lifecycle pair submission carries. Both an upper and a lower bound: a
# submission naming fewer is a half-move, and one naming more is not a lifecycle boundary.
EXPECTED_ASSIGNMENT_FIELDS = ("Stage", "Status")

# Per-assignment budget for one ``flow set-field`` invocation. Each assignment is its own
# cross-board discovery-and-write pass inside mission-control, so the whole-call budget scales with
# the count rather than staying at the single-field figure it was set for.
_TIMEOUT_SECONDS_PER_ASSIGNMENT = 60


def normalize_assignments(
    payload: dict[str, Any] | None, target_state: str
) -> list[tuple[str, str]]:
    """The ordered ``(field, option)`` assignments one ``set-field-status`` op carries (#927).

    ``payload["assignments"]`` — a list of two-element ``[field, option]`` sequences — is the pair
    form the board-submission path gained with #927. It rides the existing ``payload`` dict, so no
    signature on the caller → controller → writer path changed.

    Absent, the result is exactly the single assignment this path built before the pair existed:
    ``payload["field"]`` (defaulting to ``Status``) set to ``target_state``. That fallback is what
    keeps every pre-#927 caller byte-identical, ledger key included.

    A malformed SHAPE raises ``ValueError`` rather than being coerced: a submission that cannot say
    which field it writes must fail at the seam, never reach GitHub as a guess. (The field and
    option values themselves are stringified — a run file round-trips them through JSON anyway.)

    **A one-element ``assignments`` list is refused, deliberately, even though the equivalent
    single-field submission through ``field``/``target_state`` is legal.** The asymmetry is the
    point: ``assignments`` is the pair API a lifecycle boundary opts into, so one element there is a
    boundary that dropped half its move — the "wrong card with a clean record" failure, since
    ``Ready for Active`` is a legal ``Status`` on its own and a Status-only write reports success
    while ``Stage`` stays put. A caller that genuinely wants a one-field write uses the legacy
    keys, which is why refusing this costs no existing caller anything.
    """
    pay = payload or {}
    if "assignments" not in pay or pay["assignments"] is None:
        return [(str(pay.get("field") or "Status"), str(target_state))]
    raw = pay["assignments"]
    if isinstance(raw, (list, tuple)) and not raw:
        # ABSENT is the single-field fallback; EMPTY is a caller that built a pair payload and put
        # nothing in it. Treating them alike sent an empty pair down the Status-only path and
        # reported it as a clean single-field write -- the same "wrong card, clean record" shape
        # the distinct-field guard below refuses, arriving through the one input that skipped it.
        raise ValueError(
            "assignments is present but empty; a submission that opts into the pair API must "
            "carry both halves. Omit the key entirely for a single-field write."
        )
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"assignments must be a list of (field, option) pairs, got {raw!r}")
    assignments: list[tuple[str, str]] = []
    for item in raw:
        if isinstance(item, str) or not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError(f"assignment {item!r} is not a (field, option) pair")
        field_name, option_name = item
        if ASSIGNMENT_IDENTITY_SEPARATOR in str(field_name) or (
            ASSIGNMENT_IDENTITY_SEPARATOR in str(option_name)
        ):
            # The replay identity joins the halves with this separator, so a value containing it
            # could make two different submissions mint one key -- the exact collision the composite
            # identity exists to prevent. Unreachable against today's board (no live Stage or Status
            # option contains it), and refused rather than left to become reachable quietly.
            raise ValueError(
                f"assignment {item!r} contains {ASSIGNMENT_IDENTITY_SEPARATOR!r}, which the replay "
                "identity uses as its separator"
            )
        assignments.append((str(field_name), str(option_name)))
    # DISTINCT fields, not element count. Counting elements accepts
    # ``[["Status", "A"], ["Status", "B"]]`` -- two assignments to one field, which is a half-move
    # wearing a pair's shape and leaves the other field exactly where the single-field write would
    # have.
    names = [field_name for field_name, _ in assignments]
    if len(set(names)) != len(names):
        # A DUPLICATE field, not a missing one: `[["Stage","A"],["Stage","B"],["Status","C"]]`
        # clears the distinct-count check with two distinct names while carrying two conflicting
        # values for Stage. Mission Control applies assignments in order and does not roll back, so
        # the card ends on whichever won the race, and the record names both as landed.
        duplicated = sorted({name for name in names if names.count(name) > 1})
        raise ValueError(
            f"assignments names {', '.join(duplicated)} more than once; one field cannot carry two "
            "options in one submission"
        )
    if len(names) != len(EXPECTED_ASSIGNMENT_FIELDS):
        # An exact count, not a floor. The floor caught the half-move that motivated this guard and
        # left the other end open: a three-field submission is not a lifecycle boundary at all, and
        # authorizing it here would put an unreviewed field on the same certificate as the pair.
        raise ValueError(
            f"assignments carries {len(names)} field(s) ({', '.join(names)}); a lifecycle "
            f"submission that opts into the pair API carries exactly "
            f"{len(EXPECTED_ASSIGNMENT_FIELDS)} "
            f"({', '.join(EXPECTED_ASSIGNMENT_FIELDS)}), or the board is left half-written with a "
            "success-shaped record. Use the field/target_state keys for a single-field write."
        )
    return assignments


def assignment_identity(assignments: list[tuple[str, str]]) -> tuple[str, str]:
    """The ``(field, state)`` an idempotency key names for a WHOLE submission (#927).

    A single assignment renders exactly as it did before the pair existed, so every ledger key a
    pre-#927 tick wrote still resolves and nothing is orphaned.

    A pair renders BOTH halves, and that is the property that matters. Without it a
    ``(Stage, Status)`` pair and a ``Status``-only write to the same option mint the identical key
    — ``set-field-status:{repo}#{n}:Status:{value}`` — so whichever runs second is recorded
    ``skipped`` as already-applied. A pair whose ``Stage`` half never landed would then carry a
    success-shaped record for a move that did not happen, silently: no error, no drift record. Two
    semantically different operations sharing one replay identity is precisely what #812's
    named-field identity exists to prevent.

    Both key-minting sites — :func:`authorize_and_write` and the reconcile controller — call this,
    so a re-announce always meets the key the first write left.
    """
    if len(assignments) == 1:
        return assignments[0]
    # SORTED by field name, so the identity names the move rather than the order it was typed in.
    # Submission order is preserved in the argv and is a real property of the write; it is NOT a
    # property of the logical move, and leaving it in the key would let the same move re-drive
    # itself under a second identity simply because a caller listed Status before Stage.
    ordered = sorted(assignments, key=lambda pair: pair[0])
    return (
        ASSIGNMENT_IDENTITY_SEPARATOR.join(field_name for field_name, _ in ordered),
        ASSIGNMENT_IDENTITY_SEPARATOR.join(option_name for _, option_name in ordered),
    )


# ---------------------------------------------------------------------------
# The lifecycle boundaries (issue 1028)
# ---------------------------------------------------------------------------

#: The ``(Stage, Status)`` pairs a caller may submit, mirroring
#: ``lifecycle_field_mutation.allowed_submissions`` in the vendored
#: ``plugins/mission-control/config/sdlc-schema.json``. The schema is the authority and is read at
#: run time where it resolves; this constant is the offline fallback, and
#: ``tests/test_board_progression.py`` fails if the two drift apart. Having both is deliberate: a
#: dry run must work on a machine with no mission-control install, and a safety list that silently
#: becomes empty because a file was missing is worse than no list at all.
ALLOWED_SUBMISSIONS: tuple[tuple[str, str], ...] = (
    ("Planning", "Designing"),
    ("Planning", "Ready for Active"),
    ("Active", "Implementing"),
    ("Verify", "Awaiting verification"),
    ("Verify", "Ready to close"),
    ("Retro", "Ready to close"),
)

#: The run's lifecycle boundaries, each mapped to the ONE move the lifecycle repository allows
#: there. ``None`` is a real answer, not a gap: ``review-accepted`` has no row in the allowed list,
#: so saga submits nothing at that boundary rather than inventing a move. ``close`` carries two
#: rows because ``retro_trigger.no_trigger_closure`` says a run with no fired trigger closes from
#: Verify and never enters Retro; the caller says which by passing ``retro_trigger_fired``.
BOUNDARIES: dict[str, tuple[str, str] | None] = {
    "admission-exit": ("Planning", "Designing"),
    "plan-review-pass": ("Planning", "Ready for Active"),
    "build-start": ("Active", "Implementing"),
    "review-accepted": None,
    "merge-and-deploy": ("Verify", "Awaiting verification"),
    "close": ("Verify", "Ready to close"),
}

#: The ``close`` boundary's other row, taken when a retro trigger fired.
CLOSE_AFTER_RETRO: tuple[str, str] = ("Retro", "Ready to close")

#: Why ``review-accepted`` prints nothing. Stated once, so the command line and the tests say the
#: same thing and a reader is not left thinking the boundary was forgotten.
NO_SUBMISSION_NOTE = (
    "no allowed submission at this boundary: the lifecycle repository's "
    "lifecycle_field_mutation.allowed_submissions carries no row for review acceptance, so saga "
    "submits nothing here and records the boundary in the run record only"
)


def _vendored_schema_paths() -> list[Path]:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[3] / "mission-control" / "config" / "sdlc-schema.json",
    ]
    with contextlib.suppress(RuntimeError):
        root, _rung = resolve_mission_control_root()
        candidates.append(Path(root) / "config" / "sdlc-schema.json")
    return candidates


def allowed_submissions() -> tuple[tuple[str, str], ...]:
    """The allowed ``(Stage, Status)`` pairs — from the schema where it resolves, else the mirror.

    A schema that resolves but carries no ``allowed_submissions`` block falls back rather than
    returning an empty tuple, because an empty allowed list would refuse every move and read as a
    board outage rather than as the missing block it is.
    """
    for path in _vendored_schema_paths():
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = (raw.get("lifecycle_field_mutation") or {}).get("allowed_submissions")
        if isinstance(rows, list) and rows:
            pairs = [
                (str(row.get("stage")), str(row.get("status")))
                for row in rows
                if isinstance(row, dict) and row.get("stage") and row.get("status")
            ]
            if pairs:
                return tuple(pairs)
    return ALLOWED_SUBMISSIONS


def allowed_submission_refusal(assignments: list[tuple[str, str]]) -> str | None:
    """``None`` when this pair is allowed; otherwise the one-line refusal naming what was asked.

    Only a PAIR is judged. A single-field submission goes through the legacy ``field`` /
    ``target_state`` keys, which the outcome coordinator uses for board states that are not
    lifecycle boundaries at all; issue 1030 removes that caller, and widening this guard to cover
    it today would refuse writes that are currently correct.
    """
    if len(assignments) != len(EXPECTED_ASSIGNMENT_FIELDS):
        return None
    by_field = dict(assignments)
    stage = by_field.get("Stage", "")
    status = by_field.get("Status", "")
    if (stage, status) in allowed_submissions():
        return None
    allowed = "; ".join(f"{a} / {b}" for a, b in allowed_submissions())
    return (
        f"the pair Stage={stage!r}, Status={status!r} is not one the lifecycle repository allows a "
        f"caller to submit. The allowed submissions are: {allowed}"
    )


def resolve_boundary(name: str, *, retro_trigger_fired: bool = False) -> dict[str, Any]:
    """The single move *name* submits, or the honest absence of one.

    Returns ``{"boundary", "stage", "status", "submits"}``. ``submits`` is False only for
    ``review-accepted``; every other boundary submits exactly one pair.
    """
    if name not in BOUNDARIES:
        known = ", ".join(BOUNDARIES)
        raise ValueError(f"unknown boundary {name!r}; the run's boundaries are: {known}")
    pair = BOUNDARIES[name]
    if pair is None:
        return {
            "boundary": name,
            "stage": None,
            "status": None,
            "submits": False,
            "note": NO_SUBMISSION_NOTE,
        }
    if name == "close" and retro_trigger_fired:
        pair = CLOSE_AFTER_RETRO
    return {"boundary": name, "stage": pair[0], "status": pair[1], "submits": True}


def boundary_payload(move: dict[str, Any]) -> dict[str, Any]:
    """The submission payload for a resolved boundary — both halves, never one."""
    return {"assignments": [["Stage", move["stage"]], ["Status", move["status"]]]}


def read_boundary_context(record_path: Path) -> dict[str, Any]:
    """The repository, issue number and retro-trigger flag a boundary move needs.

    Read from the run record rather than passed on the command line, because the record is the one
    file every role reads and a hand-typed issue number is how a move lands on the wrong card.
    """
    raw = json.loads(Path(record_path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{record_path} does not hold a JSON object")
    schema = str(raw.get("schema") or "")
    if schema and schema != "run_record.v1":
        raise ValueError(
            f"run record {record_path} declares schema {schema!r}; this reader knows run_record.v1"
        )
    extra = raw.get("retro") if isinstance(raw.get("retro"), dict) else {}
    return {
        "repo": str(raw.get("repo") or ""),
        "number": int(raw.get("issue") or 0),
        "retro_trigger_fired": bool(extra.get("trigger_fired")),
    }


# ---------------------------------------------------------------------------
# The per-op primitive (the extracted mechanism)
# ---------------------------------------------------------------------------


def authorize_and_write(
    op_kind: str,
    repo: str,
    number: int,
    target_state: str,
    *,
    board_writer: Callable[..., None],
    ledger_dir: Path,
    now: Callable[[], float] = time.time,
    max_attempts: int = 3,
    payload: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    provenance: dict[str, Any] | None = None,
    write_once: Callable[[Path, str], bool] = _write_once,
) -> dict[str, Any]:
    """Authorize, idempotently write, and record ONE candidate board op.

    Routes ``op_kind`` through ``reversibility_certificate.authorize_write`` (R1/R3); a non-AUTHORIZED
    verdict returns ``{status:"gated"}`` with no write and no ledger entry (fail-loud, never silent).
    An AUTHORIZED op is idempotency-keyed into ``ledger_dir``: a present key returns
    ``{status:"skipped"}``; an absent key drives ``board_writer`` with bounded retry, writing the
    ledger key only on success (``{status:"written"}``) so a failed op is retryable next tick
    (``{status:"failed"}``, no key). A ledger fault after a committed write surfaces as
    ``{status:"error", may_reapply:True}`` rather than escaping.

    ``extra`` is merged into every RETURNED record (callers pass e.g. ``{"subplot_id": ...}`` so
    ``/outcome`` records keep their existing shape — zero behavior diff, #344 R2).

    ``provenance`` (#620) is merged into the returned record AND the PERSISTED ledger record on a
    successful write, so a resolution is diagnosable by reading ``board-sync/*.json`` later rather
    than re-derived (R7). Opt-in: only ``reconcile_board`` passes it (the mission-control root+rung it
    resolved for the tick), so every other consumer's persisted record is byte-unchanged. Readers use
    ``.get`` (``outcome_reconcile._read_ledger``), so the additive fields never disturb them.
    """
    cert = _cert()
    prov: dict[str, Any] = dict(provenance or {})
    base: dict[str, Any] = dict(extra or {})
    base.update(prov)
    base.update(op_kind=op_kind, repo=repo, number=number, target_state=target_state)

    # R1: the verdict MUST come from the certificate; never re-derived here (#344 KTD2).
    verdict = cert.authorize_write(op_kind)
    if verdict != cert.AUTHORIZED:
        # R17: surface the gate — no silent write, no silent skip.
        return {"status": "gated", **base, "verdict": "GATE"}

    pay: dict[str, Any] = dict(payload or {})
    if target_state and "target_state" not in pay:
        pay["target_state"] = target_state

    field_kw: str | None = None
    state_kw = target_state
    assignments: list[tuple[str, str]] = []
    if op_kind == str(cert.OpKind.SET_FIELD_STATUS):
        try:
            assignments = normalize_assignments(pay, target_state)
        except ValueError as exc:
            # A submission that cannot say which field it writes is refused here, not guessed at.
            return {"status": "gated", **base, "verdict": "GATE", "error": str(exc)}
        # Field name is part of authorization (#812): Status/Stage only — and EVERY field in the
        # submission, not just the first. A pair whose second half names an unauthorized field
        # must gate as a whole, or the write lands one legal half and leaves the card inconsistent.
        for field_name, _option in assignments:
            if cert.authorize_correction_field(field_name) != cert.AUTHORIZED:
                return {"status": "gated", **base, "field": field_name, "verdict": "GATE"}
        # The VALUE, not just the field (issue 1028). The certificate authorizes ``Stage`` and
        # ``Status`` as names and says nothing about what may be written into them, so before this
        # guard any caller could put a card into any option the board happened to carry. The
        # lifecycle repository calls ``lifecycle_field_mutation.allowed_submissions`` "the single
        # authority" on what a caller may submit, and nothing read it.
        pair_refusal = allowed_submission_refusal(assignments)
        if pair_refusal is not None:
            return {"status": "gated", **base, "verdict": "GATE", "error": pair_refusal}
        # The replay identity names the whole submission (#927): see ``assignment_identity``.
        field_kw, state_kw = assignment_identity(assignments)
        base["field"] = field_kw
        if len(assignments) == 1:
            # Byte-identical to the pre-#927 payload for every single-field caller.
            pay["field"] = assignments[0][0]
        else:
            pay["assignments"] = [[name, option] for name, option in assignments]

    key = cert.idempotency_key(op_kind, repo, number, state_kw, field=field_kw)
    ledger_file = ledger_dir / _safe_ledger_name(key)

    # (i) Key present → idempotent no-op (crash/retry safety, coalescing).
    if ledger_file.exists():
        return {"status": "skipped", **base, "key": key}

    if op_kind == str(cert.OpKind.ISSUE_PROGRESS_COMMENT):
        pay["body"] = _append_comment_marker(str(pay.get("body", "")), key)

    # (ii) Bounded retry.  board_writer raises → retry; key written only on SUCCESS.
    last_exc: Exception | None = None
    attempts_made = 0
    for _ in range(max_attempts):
        attempts_made += 1
        try:
            board_writer(op_kind=op_kind, repo=repo, number=number, payload=pay)
            last_exc = None
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    if last_exc is not None:
        # All attempts exhausted — surface, do NOT write the ledger so the next tick retries.
        return {
            "status": "failed",
            **base,
            "key": key,
            "error": str(last_exc),
            "attempts": max_attempts,
        }

    # (iii) SUCCESS → write the ledger key (sticky, write-once). A fault HERE must NOT escape: the
    #       board write already committed, so propagating would leave a side effect with no recorded
    #       key (recovery would re-apply it). Surface loudly and let the next tick reconcile.
    try:
        record_json = json.dumps(
            {
                "key": key,
                "op_kind": op_kind,
                "repo": repo,
                "number": number,
                "target_state": target_state,
                **({"field": field_kw} if field_kw is not None else {}),
                # Additive (#927), and only for a multi-assignment submission: readers use ``.get``
                # so a single-field record stays byte-identical to every pre-#927 entry, while a
                # pair's record says which fields it actually covered rather than only the
                # composite identity.
                **(
                    {"assignments": [[name, option] for name, option in assignments]}
                    if len(assignments) > 1
                    else {}
                ),
                "ts": now(),
                # #620 R7: persist the tick's mission-control provenance so a stale resolution is
                # diagnosable from the durable ledger. Empty for every consumer that passes none.
                **prov,
            }
        )
        write_once(ledger_file, record_json)
        return {"status": "written", **base, "key": key, "attempts": attempts_made}
    except Exception as ledger_exc:  # noqa: BLE001
        return {
            "status": "error",
            **base,
            "key": key,
            "error": f"board write committed but ledger record failed: {ledger_exc}",
            "may_reapply": True,
        }


# ---------------------------------------------------------------------------
# #449: envelope-authorized merge attribution records (R5 — the board-sync ledger
# schema's `authorizing_envelope_id` extension, merge-class records ONLY)
# ---------------------------------------------------------------------------

# Closed phase vocabulary: `authorized` is written BEFORE the squash (the durable proof
# the merge was pre-authorized, and by which envelope); `merged` is written after GitHub
# confirms the squash landed. Both phases carry the same attribution payload (the #433
# lesson: an in-flight marker must carry its era for every consumer in every phase).
MERGE_RECORD_PHASES = ("authorized", "merged")


def merge_record_key(outcome_id: str, subplot_id: str, pr: str, phase: str, token_id: str) -> str:
    """The deterministic ledger key for one envelope-authorized merge record phase.

    ``token_id`` is the era coordinate: a token is minted per envelope era (content
    fingerprint + intent_revision, exactly one active, ids unreusable after revocation),
    so keying on it means an ``authorized`` record left by an attempt under a dead era
    can never stand as — or write-once-suppress — the pre-attribution of a merge
    performed under a later era. Both phases of one merge share the same token
    coordinate; repeats within one era still dedup write-once.
    """
    return f"merge-under-envelope:{outcome_id}:{subplot_id}:{pr}:{phase}:{token_id}"


def record_envelope_authorized_merge(
    ledger_dir: Path,
    *,
    phase: str,
    outcome_id: str,
    subplot_id: str,
    pr: str,
    authorizing_envelope_id: str,
    token_id: str,
    now: Callable[[], float] = time.time,
    write_once: Callable[[Path, str], bool] = _write_once,
) -> dict[str, Any]:
    """Write ONE envelope-authorized merge attribution record into the board-sync ledger.

    #449 R5: every record written for a merge authorized under the
    ``AUTONOMOUS_UNDER_ENVELOPE`` write class carries ``authorizing_envelope_id`` (and the
    ``token_id`` that presented it) — non-merge ledger records are untouched (the field is
    merge-record-specific, never a schema-wide change). Records are write-once under a
    deterministic key; a repeat call returns ``{status: "skipped"}``. A write fault is
    surfaced as ``{status: "error"}`` — never thrown past the caller, because for the
    ``merged`` phase the side effect (the squash) has already committed.

    Fail closed: an off-vocabulary ``phase`` or an empty attribution field is a caller
    bug and raises — an unattributed merge record must be impossible to write here.
    """
    if phase not in MERGE_RECORD_PHASES:
        raise ValueError(f"phase {phase!r} not in {MERGE_RECORD_PHASES} — closed vocabulary")
    for field_name, value in (
        ("outcome_id", outcome_id),
        ("subplot_id", subplot_id),
        ("pr", pr),
        ("authorizing_envelope_id", authorizing_envelope_id),
        ("token_id", token_id),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"record_envelope_authorized_merge: {field_name} must be a non-empty "
                f"string, got {value!r} — an unattributed merge record is not writable"
            )
    key = merge_record_key(outcome_id, subplot_id, pr, phase, token_id)
    ledger_file = Path(ledger_dir) / _safe_ledger_name(key)
    base: dict[str, Any] = {
        "key": key,
        "op_kind": "merge-under-envelope",
        "outcome_id": outcome_id,
        "subplot_id": subplot_id,
        "pr": pr,
        "phase": phase,
        "authorizing_envelope_id": authorizing_envelope_id,
        "token_id": token_id,
    }
    if ledger_file.exists():
        return {"status": "skipped", **base}
    try:
        created = write_once(ledger_file, json.dumps({**base, "ts": now()}))
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            **base,
            "error": f"merge attribution record failed: {exc}",
        }
    return {"status": "written" if created else "skipped", **base}


# ---------------------------------------------------------------------------
# The production board_writer (moved from outcome.py:_default_board_writer, #344 KTD6)
# ---------------------------------------------------------------------------


def _describe_rows(rows: Any) -> str:
    """Render mission-control's ``updated``/``failed`` rows as ``Field=Option`` pairs."""
    if not isinstance(rows, list):
        return ""
    described = [
        f"{row.get('field')}={row.get('option')}"
        for row in rows
        if isinstance(row, dict) and row.get("field")
    ]
    return ", ".join(described)


def _set_field_landed_detail(stdout: str, assignments: list[tuple[str, str]]) -> str:
    """Name which assignments landed and which did not, from Mission Control's own report (#927).

    ``flow_set_fields_bulk`` prints its ``updated`` / ``failed`` / ``identity`` result to STDOUT and
    only *then* raises on a non-empty ``failed``. So detection of a half-applied pair was never
    missing — the exit code is already non-zero and the caller's ``if returncode != 0: raise``
    already catches it. What was thrown away is the *evidence*: the error carried ``stderr`` while
    the record of which half landed sat on the discarded stdout, leaving the board half-written with
    nothing to say which field to repair.

    A half-applied pair is reachable, not theoretical: ``flow_set_fields_bulk`` calls
    ``_set_lifecycle_field_cross_board`` once per assignment, each all-or-none across boards but
    independent of the others, and only a ``LifecycleMutationHaltError`` propagates — a
    ``RuntimeError`` on the second assignment appends a ``failed`` row and leaves the first written.

    Returns ``""`` when stdout carries no parseable report, so the caller's message degrades to
    exactly what it said before rather than inventing a claim about the board.
    """
    text = stdout or ""
    decoder = json.JSONDecoder()
    # ``_out`` pretty-prints with indent=2, so the report's opening brace is at the start of a line.
    # Scan those positions rather than the whole string: any progress line printed before the report
    # would otherwise defeat a plain ``json.loads``. Later reports win — the result is printed last.
    starts = [0] if text.startswith("{") else []
    starts += [match.end() for match in re.finditer(r"\n(?=\{)", text)]
    report: dict[str, Any] | None = None
    for start in starts:
        try:
            parsed, _end = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if isinstance(parsed, dict) and ("updated" in parsed or "failed" in parsed):
            report = parsed
    if report is None:
        # No report at all, which is NOT the same as nothing having landed. ``_out`` runs before the
        # ``failed`` raise, so an absent report means the run died before it -- a
        # ``LifecycleMutationHaltError`` propagating out of the SECOND assignment is exactly that
        # shape, and it leaves the FIRST one written. Returning "" here reported a total failure for
        # a board that may be half-moved. Say what was submitted and that the outcome is unknown, so
        # the operator checks both fields instead of assuming neither landed.
        submitted = ", ".join(f"{field}={option}" for field, option in assignments)
        if len(assignments) < 2:
            # A single-field write has no halves. `outcome_reconcile.py` still drives
            # `set-field-status` through the legacy `field`/`target_state` form, so this branch is
            # live for real callers, and telling them to "check every field" and that "which halves
            # landed is UNKNOWN" describes a submission they did not make -- it invents a
            # half-written board out of a write that could only ever land or not.
            return (
                f"no outcome report on stdout, so whether the write landed is UNKNOWN; submitted: "
                f"{submitted or 'none'} — check the field on the board before retrying"
            )
        return (
            f"no outcome report on stdout, so which halves landed is UNKNOWN; submitted: "
            f"{submitted or 'none'} — check every field on the board before retrying"
        )
    landed = _describe_rows(report.get("updated"))
    unlanded = _describe_rows(report.get("failed"))
    parts = [f"landed: {landed or 'none'}", f"NOT landed: {unlanded or 'none'}"]
    return "; ".join(parts)


def default_board_writer(
    *,
    mission_control_root: Path,
    project: str = "operations",
    runner: Callable[..., Any] | None = None,
) -> Callable[..., None]:
    """The production board_writer (#279/#344): drive a reversibility-authorized op via mission-control.

    Maps each enumerated ``OpKind`` to its ``sdlc_manager.py`` subcommand. Tests inject a recording
    fake (or the ``--runner`` seam) instead; the nested ``gh`` child runs ONLY under a real
    ``--autonomous`` campaign. A non-zero exit raises so the consumer's bounded-retry / fail-loud
    path engages.

    This is the ONLY place the ``sdlc_manager.py`` argv is built, which is why #927's pair rides
    through here: a ``set-field-status`` op emits one ``--field``/``--option`` per assignment in
    ``payload["assignments"]`` (one assignment, and therefore one flag pair, when it is absent).
    On a non-zero exit the raised error also names which assignments landed and which did not,
    read out of Mission Control's own stdout report — see :func:`_set_field_landed_detail`.

    ``mission_control_root`` is an ALREADY-RESOLVED install root (``resolve_mission_control_root``),
    not a repo root — pre-#620 this derived the path from ``repo_root``, which only held inside the
    plugins monorepo. It is keyword-only on purpose: a caller left on the old positional convention
    fails loudly at the seam instead of silently constructing a path that does not exist.
    """
    import subprocess  # noqa: PLC0415

    sdlc = str(Path(mission_control_root) / "scripts" / "sdlc_manager.py")
    run = runner if runner is not None else subprocess.run

    def _comment_exists(*, owner_repo: str, marker: str, issue_number: int) -> bool:
        path = f"repos/{owner_repo}/issues/{issue_number}/comments"
        result = run(
            ["gh", "api", "--method", "GET", path, "--paginate", "-F", "per_page=100"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if getattr(result, "returncode", 0) != 0:
            raise RuntimeError(
                "board write issue-progress-comment preflight failed: "
                f"{getattr(result, 'stderr', '')!r}"
            )
        try:
            comments = json.loads(getattr(result, "stdout", "") or "[]")
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "board write issue-progress-comment preflight returned invalid JSON"
            ) from exc
        if not isinstance(comments, list):
            raise RuntimeError(
                "board write issue-progress-comment preflight returned non-list JSON"
            )
        for comment in comments:
            if isinstance(comment, dict) and marker in str(comment.get("body", "")):
                return True
        return False

    def _writer(*, op_kind: str, repo: str, number: int, payload: dict[str, Any]) -> None:
        base = ["python3", sdlc]
        n = str(number)
        # The mission-control verbs prepend ORG to build ``repos/{ORG}/{repo}/...``, so they need the
        # BARE repo name. The caller passes an owner-qualified repo ("infiquetra/saga") for the
        # idempotency-key namespace; strip the owner here so the REST path is not doubled.
        repo = repo.rsplit("/", 1)[-1]
        owner_repo = f"infiquetra/{repo}"
        # Empty for every op but the lifecycle write; the timeout and the failure detail below both
        # read it, and both must behave exactly as they did for the other verbs.
        assignments: list[tuple[str, str]] = []
        if op_kind == "set-field-status":
            cert = _cert()
            # One invocation, N assignments (#927). ``flow set-field`` declares --field/--option
            # with action="append" and routes a multi-assignment call through
            # ``flow_set_fields_bulk``. What that saves is one process spawn, one CLI parse and one
            # authorization pass -- NOT one discovery pass: the bulk path calls
            # ``_set_lifecycle_field_cross_board`` once per assignment and each does its own
            # cross-board discovery, which is why the timeout below scales with the assignment
            # count instead of sharing the single-field budget.
            assignments = normalize_assignments(payload, str(payload.get("target_state", "")))
            for field_name, _option in assignments:
                if cert.authorize_correction_field(field_name) != cert.AUTHORIZED:
                    allowed = ", ".join(sorted(cert.CORRECTION_FIELDS))
                    raise ValueError(
                        f"set-field submission rejects field {field_name!r}; allowed: {allowed}"
                    )
            cmd = base + [
                "flow",
                "set-field",
                "--project",
                project,
                "--repo",
                repo,
                "--number",
                n,
            ]
            for field_name, option_name in assignments:
                cmd += ["--field", field_name, "--option", option_name]
            cmd += ["--correction"]
        elif op_kind == "sub-issue-close":
            cmd = base + ["issue", "close", "--repo", repo, "--number", n]
        elif op_kind == "sub-issue-reopen":
            cmd = base + ["issue", "reopen", "--repo", repo, "--number", n]
        elif op_kind == "issue-progress-comment":
            cmd = base + [
                "issue",
                "comment",
                "--repo",
                repo,
                "--number",
                n,
                "--body",
                str(payload.get("body", "")),
            ]
            marker = _comment_marker_in(str(payload.get("body", "")))
            if marker and _comment_exists(
                owner_repo=owner_repo, marker=marker, issue_number=number
            ):
                return
        elif op_kind == "issue-label-add":
            cmd = base + [
                "issue",
                "label-add",
                "--repo",
                repo,
                "--number",
                n,
                "--label",
                str(payload.get("label", "")),
            ]
        elif op_kind == "issue-label-remove":
            cmd = base + [
                "issue",
                "label-remove",
                "--repo",
                repo,
                "--number",
                n,
                "--label",
                str(payload.get("label", "")),
            ]
        else:
            raise ValueError(f"no mission-control verb mapping for op_kind {op_kind!r}")
        # One assignment is one cross-board discovery-and-write pass inside mission-control, so a
        # pair does roughly twice the work of the single-field write this budget was set for.
        # Scaling by the assignment count keeps the per-assignment budget the same rather than
        # halving it silently the moment the pair shipped.
        timeout = _TIMEOUT_SECONDS_PER_ASSIGNMENT * max(1, len(assignments)) if assignments else 60
        result = run(cmd, capture_output=True, text=True, timeout=timeout)
        if getattr(result, "returncode", 0) != 0:
            detail = ""
            if op_kind == "set-field-status":
                landed = _set_field_landed_detail(
                    str(getattr(result, "stdout", "") or ""), assignments
                )
                if landed:
                    detail = f"; {landed}"
            raise RuntimeError(
                f"board write {op_kind} on {repo}#{number} failed: "
                f"{getattr(result, 'stderr', '')!r}{detail}"
            )

    return _writer


def _default_ledger_dir(repo_root: Path) -> Path:
    """Default write-record ledger for skill consumers — git-ignored, machine-local, shared.

    A single dir is safe: ``idempotency_key`` namespaces every entry by op_kind+repo+number+state,
    so entries never collide across issues.
    """
    return repo_root / ".claude" / "saga" / "board-progression"


# ---------------------------------------------------------------------------
# CLI (so markdown skills /work and /loop can invoke the writer, #344 KTD6)
# ---------------------------------------------------------------------------


def _repo_root_default() -> Path:
    # plugins/saga/scripts/board_progression.py → parents[3] == repo root
    return Path(__file__).resolve().parents[3]


def _run_boundary(args: argparse.Namespace) -> int:
    """Resolve one lifecycle boundary and either print its move or submit it.

    One move per boundary and nothing else. A refused move is REPORTED and the command exits
    non-zero; it is never retried here, because a silent retry against a board that just said no is
    how a wrong move becomes a loop.
    """
    if not args.record:
        print(
            json.dumps({"ok": False, "error": "--boundary needs --record <run record path>"}),
            file=sys.stderr,
        )
        return 2
    try:
        context = read_boundary_context(Path(args.record).resolve())
        move = resolve_boundary(
            args.boundary, retro_trigger_fired=bool(context["retro_trigger_fired"])
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2

    if not move["submits"]:
        print(json.dumps({**move, "repo": context["repo"], "number": context["number"]}))
        return 0
    if args.dry_run:
        print(
            json.dumps(
                {
                    **move,
                    "repo": context["repo"],
                    "number": context["number"],
                    "dry_run": True,
                    "payload": boundary_payload(move),
                }
            )
        )
        return 0

    repo_root = Path(args.repo_root).resolve() if args.repo_root else _repo_root_default()
    ledger_dir = (
        Path(args.ledger_dir).resolve() if args.ledger_dir else _default_ledger_dir(repo_root)
    )
    cert = _cert()
    op_kind = str(cert.OpKind.SET_FIELD_STATUS)
    writer: Callable[..., None] = _gated_writer
    if cert.authorize_write(op_kind) == cert.AUTHORIZED:
        try:
            mission_control_root, _rung = resolve_mission_control_root()
        except RuntimeError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 1
        writer = default_board_writer(
            mission_control_root=mission_control_root, project=args.project
        )
    record = authorize_and_write(
        op_kind,
        context["repo"],
        context["number"],
        move["status"],
        board_writer=writer,
        ledger_dir=ledger_dir,
        payload=boundary_payload(move),
        extra={"boundary": args.boundary, "stage": move["stage"]},
    )
    print(json.dumps(record))
    if record.get("status") in ("written", "skipped", "gated"):
        return 0
    # Reported, never retried: the caller decides, with the reason in front of it.
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Certificate-gated autonomous board writer (#344); lifecycle boundaries (1028)."
    )
    # The boundary interface (issue 1028). It sits at the top level rather than under a subcommand
    # because a caller names a lifecycle boundary and nothing else: there is no second verb here,
    # and `write` stays for the op-kind callers issue 1030 removes.
    parser.add_argument("--record", default="", help="path to the run record JSON file")
    parser.add_argument(
        "--boundary",
        default="",
        help="the lifecycle boundary whose one allowed move to submit: " + ", ".join(BOUNDARIES),
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the single move and write nothing"
    )
    # Shared with the `write` subcommand's own copies; the subparser's value wins when a
    # subcommand is used, and these are what the boundary path reads.
    parser.add_argument("--project", default="operations")
    parser.add_argument("--ledger-dir", default="")
    parser.add_argument("--repo-root", default="")
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_write = sub.add_parser("write", help="authorize + idempotently write one board op")
    p_write.add_argument(
        "--op", required=True, help="OpKind, e.g. set-field-status | sub-issue-close"
    )
    p_write.add_argument(
        "--repo", required=True, help="owner/repo (owner used only for the key namespace)"
    )
    p_write.add_argument("--number", required=True, type=int)
    p_write.add_argument("--target-state", default="", help="e.g. Done (for set-field-status)")
    p_write.add_argument("--project", default="operations")
    p_write.add_argument("--payload", default="", help='JSON object, e.g. {"body": "..."}')
    p_write.add_argument(
        "--ledger-dir", default="", help="override the default board-progression ledger dir"
    )
    p_write.add_argument(
        "--repo-root", default="", help="override the repo root (default: derived from __file__)"
    )

    args = parser.parse_args(argv)

    if args.boundary:
        return _run_boundary(args)
    if not args.cmd:
        parser.error("name a --boundary (with --record), or use the `write` subcommand")

    if args.cmd == "write":
        repo_root = Path(args.repo_root).resolve() if args.repo_root else _repo_root_default()
        ledger_dir = (
            Path(args.ledger_dir).resolve() if args.ledger_dir else _default_ledger_dir(repo_root)
        )
        payload = json.loads(args.payload) if args.payload else None
        # #652: the certificate decides BEFORE mission-control is resolved. A gated op needs no
        # writer, so an unresolvable install must not turn an expected GATE verdict (exit 0) into a
        # resolution error (exit 1) for the callers that key on the exit status.
        cert = _cert()
        writer: Callable[..., None] = _gated_writer
        if cert.authorize_write(args.op) == cert.AUTHORIZED:
            try:
                mission_control_root, _rung = resolve_mission_control_root()
            except RuntimeError as exc:
                print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
                return 1
            writer = default_board_writer(
                mission_control_root=mission_control_root, project=args.project
            )
        record = authorize_and_write(
            args.op,
            args.repo,
            args.number,
            args.target_state,
            board_writer=writer,
            ledger_dir=ledger_dir,
            payload=payload,
        )
        print(json.dumps(record))
        # A gate is a normal, expected outcome (exit 0); only a hard write failure is non-zero.
        return 0 if record.get("status") in ("written", "skipped", "gated") else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
