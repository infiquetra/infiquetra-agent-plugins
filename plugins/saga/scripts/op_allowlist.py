#!/usr/bin/env python3
"""The closed allowlist of mission-control operations saga may submit without an operator.

This is the surviving half of `reversibility_certificate.py`, which issue 1030 removed with the
ship-ceremony family. That module carried two things: a **reversibility tiering** -- which
operations were reversible, what their inverse was, what aborting one cost -- and, underneath it, a
**default-deny allowlist** of the operations saga is allowed to submit at all.

The tiering went with the ceremony that consumed it: nothing computes an inverse or an abort cost
any more. The allowlist stays, because it answers a question the lifecycle still asks on every
board write -- *may saga do this one without a human?* -- and because its failure direction is the
one worth keeping: an operation nobody enumerated is refused, not attempted.

Two ops are enumerated and still refused, which is the point of naming them rather than omitting
them. Closing a **parent** issue is always the operator's, because it declares a whole tree of work
finished. Merging was reachable only through the envelope machinery this release removes, so it has
no autonomous path left at all.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "AUTHORIZED",
    "CORRECTION_FIELDS",
    "GATE",
    "OpKind",
    "Verdict",
    "authorize_correction_field",
    "authorize_write",
    "idempotency_key",
]


class Verdict(StrEnum):
    """What the allowlist says about one operation."""

    AUTHORIZED = "AUTHORIZED"
    GATE = "GATE"


AUTHORIZED = Verdict.AUTHORIZED
GATE = Verdict.GATE


class OpKind(StrEnum):
    """Canonical names for mission-control operations, mirroring mission-control's verbs.

    A closed allowlist: anything not named here is refused by default-deny. Repository-level
    mutations are deliberately absent -- saga never submits one.
    """

    SET_FIELD_STATUS = "set-field-status"
    ISSUE_LABEL_ADD = "issue-label-add"
    ISSUE_LABEL_REMOVE = "issue-label-remove"
    SUB_ISSUE_CLOSE = "sub-issue-close"
    SUB_ISSUE_REOPEN = "sub-issue-reopen"
    ISSUE_PROGRESS_COMMENT = "issue-progress-comment"
    WORKTREE_RECLAIM_MERGED = "worktree-reclaim-merged"
    PARENT_ISSUE_CLOSE = "parent-issue-close"


#: The operations saga may submit on its own. Every one is undoable by a later submission of a
#: member of this same set, which is why it needs no operator and no recorded inverse.
_AUTONOMOUS: frozenset[OpKind] = frozenset(
    {
        OpKind.SET_FIELD_STATUS,
        OpKind.ISSUE_LABEL_ADD,
        OpKind.ISSUE_LABEL_REMOVE,
        OpKind.SUB_ISSUE_CLOSE,
        OpKind.SUB_ISSUE_REOPEN,
        OpKind.ISSUE_PROGRESS_COMMENT,
        OpKind.WORKTREE_RECLAIM_MERGED,
    }
)

#: Enumerated and still the operator's. Named rather than omitted so the refusal reads as a
#: decision: an omitted op is refused by accident, a listed one is refused on purpose.
_OPERATOR_ONLY: frozenset[OpKind] = frozenset({OpKind.PARENT_ISSUE_CLOSE})


def authorize_write(op_kind: str | OpKind) -> Verdict:
    """Return ``AUTHORIZED`` or ``GATE`` for *op_kind*, defaulting to ``GATE``.

    A string that matches no member returns ``GATE`` without raising, so a caller passing a typo or
    a verb from a newer mission-control never writes by accident.
    """
    if not isinstance(op_kind, OpKind):
        try:
            op_kind = OpKind(op_kind)
        except ValueError:
            return GATE
    if op_kind in _OPERATOR_ONLY:
        return GATE
    return AUTHORIZED if op_kind in _AUTONOMOUS else GATE


#: The only project fields a `set-field-status` op may name. Naming any other field -- Initiative,
#: Objective, anything else -- is gated, never a silent write (#812). `Stage` is allowed as a name
#: only; there is no `set-field-stage` op kind.
CORRECTION_FIELDS: frozenset[str] = frozenset({"Status", "Stage"})


def authorize_correction_field(field_name: str) -> Verdict:
    """Authorize `Status` and `Stage` by name; gate every other project field (#812).

    The field name is part of the authorization, not a parameter to it: an op that names a field
    outside this set is refused rather than written.
    """
    return AUTHORIZED if field_name in CORRECTION_FIELDS else GATE


def idempotency_key(
    op_kind: str | OpKind,
    repo: str,
    issue_number: int,
    target_state: str,
    *,
    field: str | None = None,
) -> str:
    """Return the deterministic idempotency key for one autonomous board write.

    Key form:
      `set-field-status`   ``"{op_kind}:{repo}#{issue_number}:{field}:{target_state}"``
                           (``field`` defaults to ``Status``)
      every other op       ``"{op_kind}:{repo}#{issue_number}:{target_state}"``
      progress comment     ``target_state`` carries the leaf transition id as the coalescing
                           discriminator, so one comment is posted per meaningful transition.

    The ``repo`` qualifier is load-bearing: two issues sharing a number in different repositories
    must get distinct keys, or one silently skips the other's board write off a colliding ledger
    entry.

    A pure string recipe -- it writes no ledger. Recording executed keys belongs to the caller.
    """
    op_str = op_kind.value if isinstance(op_kind, OpKind) else str(op_kind)
    if op_str == OpKind.SET_FIELD_STATUS.value:
        field_name = field if field else "Status"
        return f"{op_str}:{repo}#{issue_number}:{field_name}:{target_state}"
    return f"{op_str}:{repo}#{issue_number}:{target_state}"
