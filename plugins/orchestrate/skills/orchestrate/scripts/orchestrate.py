#!/usr/bin/env python3
"""Run a plan of units across herdr agent sessions, one git worktree each.

The plan is authored by the operator and Claude together; this script is the mechanical half.
It creates a FRESH worktree and a branch per unit, launches the requested agent there, sends the
unit's saga command, waits, takes a merge turn onto the run's parent branch, and cleans up.

State is saga's per-issue run record, `run_record.v1`, under the primary checkout's
`.claude/saga/runs/issue-<N>.json`. One record per issue, so two issues can be driven in one
repository at once, and the store root is resolved from the git COMMON directory, so a unit's own
worktree reads the same file the coordinator writes.

There is no lock, lease, reservation or receipt anywhere in here, and adding one is out of bounds
(issue #1018). What makes a repeated `go` launch a unit once is that the launch is persisted
before the launcher is called; what makes a relaunch safe is that every launch gets its own fresh
worktree; what serialises merges is a `merge_state` field checked against git rather than trusted.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import functools
import glob
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ships beside this file. Kept optional so a partial install degrades to per-unit waits rather
# than refusing to run at all.
try:
    import herdr_events
except ImportError:  # pragma: no cover - only when the sibling module is missing
    herdr_events = None  # type: ignore[assignment]

# The top-level key orchestrate keeps its own run-level state under, inside saga's per-issue run
# record. The record's twelve documented keys have no place for a run branch, a base commit or a
# unit-name-to-issue mapping, and ``run_record`` preserves an unknown top-level key unchanged
# across a read and a write by design -- so this is a first-class extension point rather than a
# smuggled field. The record's own documented keys (``admission``, ``approval_scope``,
# ``run_configuration``, ``review_cycles``, ``roster``) are NEVER written from here.
ORCHESTRATE_BLOCK = "orchestrate"

# Where a landing worktree used to live, and where a run file used to be written. Only the
# directory name survives, as the parent of a merge turn's detached worktree; there is no run
# file, no task spill and no recovery pointer under it any more (issue #1025).
WORKTREE_STATE_DIR = Path(".orchestrate")

# The note matches the task column's existing human-facing bound. It used to be the only unbounded
# status field: one delivery warning stretched a two-unit table to 268 characters per row.
STATUS_TEXT_WIDTH = 44

# Vendor flag tables, wrapper resolution, argv assembly, launch, preflight, delivery,
# and owned cleanup live in the agent-launcher plugin and are ingested below
# (``_ingest_agent_launcher``). Orchestrate keeps run-scheduling, landing, review
# policy, and the run ledger.


# Where each vendor keeps its saga install, so "does this vendor have saga" is resolved rather than
# believed. Checked by `saga --check`. A vendor absent here, or whose globs match nothing, cannot
# run a saga capability at all -- agy and muse are in that position today, and a saga task sent to
# them does nothing no matter what prefix it carries.
SAGA_INSTALL: dict[str, list[str]] = {
    "claude": ["~/.claude/plugins/cache/*/saga/*/commands"],
    "codex": ["~/.codex/plugins/cache/*/saga/*/skills"],
    "grok": ["~/.grok/marketplace-cache/*/plugins/saga/commands"],
    "qwen": ["~/.qwen/extensions/saga/commands"],
    "opencode": ["~/.config/opencode/commands"],
    # agy is Antigravity, and its home is the Gemini config directory. The plugin there is a
    # *symlink* into the operator's own antigravity-plugins checkout rather than a fetched cache,
    # which is why a search for directories named `saga` finds only `~/.gemini/saga` -- the saga
    # state, not the commands. `glob` resolves the link, so one concrete path is enough.
    "agy": ["~/.gemini/config/plugins/saga/commands"],
}

# How each vendor names a saga capability. Saga is installed for most of them, but the invocation
# differs -- and a bare "/plan" is a command nowhere, so it arrives as prose the agent may or may
# not act on. That is how a "/plan" unit once produced claude's own built-in plan mode instead.
# `normalize_task` applies this at send time, so the interview writes one form for everybody.
#
# claude and grok/qwen/opencode were read off their installed command files; codex's saga ships
# skills under the `saga` namespace with no command directory at all (its PORTABILITY.md says so),
# and codex prefixes with `$`.
# Saga stages that stop and ask the operator which execution backend to use. `/work` offers it
# unconditionally -- there is no skip-if-already-decided path in its contract -- and an
# `AskUserQuestion` in a background tab waits forever. Unlike saga's engine offer there is no stored
# preference to pre-seed, so the decision is carried in the task text, which is the only lever saga
# exposes. Orchestrate is always inline by design: a dispatched unit is already one of several
# parallel sessions, and nesting a workflow inside one is the orchestration-of-orchestration this
# plugin exists to avoid.
# Saga stages that stop and ask the operator which execution backend to use, and what each one
# needs to be told instead. Both `/plan` and `/work` offer it, so under orchestration the planner
# hangs before the builder is ever reached -- an `AskUserQuestion` in a background tab waits
# forever.
#
# The two messages differ because the stages have different jobs. `/plan` is where the decision is
# recorded, and it records it into the plan document's `backend:` frontmatter, which is the only
# carrier that survives a worktree boundary: the saga tick is untracked local state. `/work` then
# reads that field rather than asking, so the note there is a belt to the document's braces.
BACKEND_NOTES: dict[str, str] = {
    "plan": (
        " The execution backend for this run is already decided: {backend}. "
        "Do not offer or ask about it -- set `backend: {backend}` in the plan's frontmatter "
        "and continue."
    ),
    "work": (
        " The execution backend for this run is already decided: {backend}, and the plan's "
        "`backend:` frontmatter says so. Do not offer or ask about it -- record {backend} "
        "and continue."
    ),
}

# What a builder is told when this run reviews the build in its own phase.
#
# `/work` Phase 5 calls `/code-review` programmatically as its own pre-PR gate. In one session that
# is right. Under orchestration it is a self-review -- the reviewer is the builder's own vendor,
# which is the one thing the operator's roster rule forbids -- and it has a worse failure than the
# wasted pass: §5.3 blocks on any P0 or P1 and the only documented exit is an operator override with
# a recorded rationale. That is a question, in a background tab, waiting forever. The observed run
# came back clean and so survived; a run that does not would hang after an hour of work.
#
# Sent only when the run actually has a code-review phase of its own. Without one the in-loop gate
# is the only review there is, and suppressing it would remove the review rather than move it.
REVIEW_ELSEWHERE_NOTE = (
    " This run reviews the build in its own separate phase, with a different vendor than yours, "
    "after your work is landed. Skip the Phase 5 code-review gate entirely -- do not call "
    "/code-review, do not write a code-review evidence record, and do not ask for an override. "
    "Commit your work, say what you did, and stop."
)

# Sent with every dispatched saga task, whatever the capability.
#
# `BACKEND_NOTES` pre-answers one question. Saga's `/plan` names the whole family in its own
# SKILL.md: "Use AskUserQuestion for choices from a known set (destination, execution backend,
# scope class, resume-vs-mint)". Shipping a note for the backend fixed one member of four, and the
# next live run stopped on the destination within minutes of starting -- a planner sitting blocked
# in a tab nobody was watching, with the rest of the run queued behind it.
#
# One rule rather than four more pre-decided answers. Pre-deciding each would make this plugin model
# saga's entire question vocabulary, which goes stale the moment saga adds a fifth -- the same closed
# vocabulary that sent a whole review phase around the plugin (see `launch_args`).
#
# The second half is the load-bearing half. A unit must not silently invent an answer to a real
# question about the work: "should this refactor also cover X" is the operator's, and guessing it
# produces confident work on the wrong thing. Stopping is safe, because an idle unit is exactly what
# `settle` and the orchestrator are watching for.
UNATTENDED_NOTE = (
    " You are running unattended in a tab nobody is watching, so a question waits forever and takes "
    "the run down with it. For a choice from a known set -- destination, execution backend, scope "
    "class, resume-vs-mint -- do not ask: take the most defensible option, say in one line which "
    "you took and why, and continue. For a real question about the work itself, do not guess and "
    "do not prompt either: write the question into your output and stop, and the orchestrator will "
    "bring it to the operator."
)

SAGA_SYNTAX: dict[str, str] = {
    "claude": "/saga:{cap}",
    "codex": "$saga:{cap}",
    "grok": "/{cap}",
    "agy": "/saga:{cap}",
    "qwen": "/{cap}",
    "opencode": "/{cap}",
}

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"
ACCOUNT_MISMATCH = "account_mismatch"
ORPHANED = "orphaned"

# The three merge-turn states a unit row can carry. ``merging`` is never trusted on its own: see
# ``stale_merge_turn``.
MERGE_READY, MERGE_MERGING, MERGE_MERGED = "ready", "merging", "merged"
PARKED = "parked"
TERMINAL_UNIT_STATUSES = frozenset({FAILED, ORPHANED, ACCOUNT_MISMATCH, PARKED})

REVIEW_CONTROLLER_ROLE = "review-controller"
RUN_SLOT = "__run__"
"""Key under which an unscoped run's single-controller review state lives in ``review_states``."""
REVIEWER_SEAT_ROLE = "external-reviewer"
WORK_FIX_ROLES = frozenset({"review-fixer", "downstream-resolver"})
_REVIEW_SHAPED = re.compile(r"(?i)\breview\b")
_RETIRED_TRANSPORT = re.compile(r"engine_session_runner|engine_offer|external_only")
OPERATOR_FIX_ROLES = frozenset({"human", "release"})
#: The code-review result Orchestrate consumes. Moved to v2 by issue 1001, when the
#: review began taking its lenses and thresholds from the lifecycle repository's
#: catalogue instead of a policy file inside the Saga plugin. The pair of schema
#: identifiers is the only persistent compatibility contract between the two
#: repositories, so a consumer that does not recognise one must refuse rather than
#: guess — which is why this is a named constant and not an inline string.
REVIEW_RESULT_SCHEMA = "review_result.v2"
REVIEW_OUTCOMES = frozenset(
    {"accepted", "repairs_requested", "cycle_cap_best_available", "review_incomplete"}
)
_NON_CODE_REVIEW_CAPABILITIES = frozenset(
    {
        "brainstorm",
        "ceo-review",
        "delegation-audit",
        "doc-review",
        "engines",
        "fleet-doctor",
        "founder-review",
        "handoff",
        "ideate",
        "investigate",
        "loop",
        "office-hours",
        "optimize",
        "outcome",
        "plan",
        "promote",
        "pulse",
        "qa",
        "resume",
        "retro",
        "spec",
        "strategy",
        "tier",
        "work",
    }
)


# AccountMismatchError is defined by the ingested agent-launcher module.


@dataclass
class Unit:
    name: str
    vendor: str
    task: str
    """What the session is told to do -- a saga command like "/plan #456", or free prose.

    Always the full text in memory, even when the record on disk keeps only a pointer: ``save``
    spills a task longer than ``TASK_SPILL_THRESHOLD`` into its own file, and ``load`` reads it
    back, so no caller of ``task`` knows the difference."""
    model: str | None = None
    effort: str | None = None
    account: str | None = None
    """Account selection for this unit (e.g. "company" or "personal").

    When set to "company", claude units emit ``--company-account`` in their launch arguments.
    Absent, the run's default account is used if present; absent both, no account flag is emitted,
    defaulting to the environment.
    """
    permission: str = "auto"
    """How freely this unit may act: ``auto`` (get on with it) or ``bypass`` (ask nothing).

    ``auto`` is the default because it is enough for a unit to do its own work in its own worktree.
    ``bypass`` is there because it is what the operator runs all day, and a unit that keeps stopping
    to ask in a tab nobody is watching has failed. The containment is the worktree either way."""
    permission_declared: bool = False
    """Whether the plan row that produced this unit named ``permission`` explicitly.

    False means the unit inherited the default, and false is the default here too, so a unit row
    that lacks the key -- a legacy run file, or one written by hand -- reads as not declared
    rather than as a posture somebody chose (cycle 2, F67). The plan parser is the only producer
    that sets it true. Recorded because a run that declared a posture and a plan that omitted the
    field produce a worker in ``auto`` with nothing on screen to say so."""
    setup: list[str] = field(default_factory=list)
    """Lines sent into the session before its task, for tier control the command line lacks.

    ``["/effort high"]`` for an agent whose CLI has no effort flag. Sent in order, each as its own
    prompt, so the session has settled into the requested tier before it is given work. Anything a
    slash command can do to a fresh session belongs here."""
    launch_args: list[str] = field(default_factory=list)
    """Extra arguments appended after the vendor token, passed through verbatim and never inspected.

    Arguments after the vendor token reach the vendor, except for the few the wrapper intercepts
    from that position (``--company-account`` is one: it swaps the configuration directory before
    the tool starts). A launcher flag that must precede the vendor token cannot be expressed here
    -- ``--workspace`` is the case that forced the ``workspace`` field: after the vendor token the
    wrapper treats it as the vendor's argument and the session lands in the caller's workspace.

    ``model`` and ``effort`` cover what every vendor has in common; this covers everything else the
    wrapper knows and this plugin does not. Deliberately not validated here. The wrapper is a
    separate program on its own release schedule, so any list of acceptable flags kept in this file
    would go stale silently -- which is the same closed vocabulary one level up. It already rejects
    what it does not accept, by name. Carry it, do not police it."""
    workspace: str | None = None
    """Herdr workspace NAME this unit launches into.

    Emitted as ``--workspace <name>`` in the launcher position, before the vendor token, alongside
    ``--task`` and ``--cwd``. Absent, the run's default is used if it has one; absent both, the
    session lands in the caller's workspace -- today's behaviour. The wrapper's ``--workspace``
    takes a name, not an ID: handed an ID it creates a new workspace called that rather than
    joining the one you meant.

    A field rather than a ``launch_args`` entry because the two argv positions are mutually
    exclusive, and this plugin should not have to know which of the wrapper's flags belong where."""
    merge: bool = True
    """Should this unit's branch be merged onto the run branch by ``land``?

    True for almost everything: a phase becomes real to the next one by landing. False is for a unit
    whose branch is meant to be *read* rather than merged -- several planners each writing their own
    version of the same document, where merging them by git produces a conflict at best and a
    silently interleaved plan at worst.

    Whether a unit is that kind is a judgement about what the phase was for, so it is authored here
    rather than guessed. This plugin does not compare branches for overlapping paths to work it out:
    that is real work, wrong in both directions, and it decides something the person who wrote the
    phase already knows."""
    role: str | None = None
    """The unit's review-loop role, when it participates in that loop.

    ``review-controller`` identifies the one top-level Code Review invocation. Additional
    reviewer seats requested by that controller use ``external-reviewer`` and launch through
    the same expand/go path as every other unit. Work workers use ``review-fixer`` or
    ``downstream-resolver`` so an opaque result can be routed without treating a unit name as
    policy. Older run records carry no role and continue to load unchanged."""
    lifecycle: str | None = None
    """Which child lifecycle this unit belongs to, when a run carries more than one.

    A run reviewing several independent frozen targets needs one Code Review controller per target,
    each with its own typed state.  Declaring a lifecycle is what makes those controllers legible as
    *deliberately separate* rather than as the accidental second controller the single-controller
    guard exists to catch (#877).  Runs with a single review phase leave this unset and behave
    exactly as before, including the error when a second unscoped controller appears."""
    paths: list[str] = field(default_factory=list)
    """Repository paths this Work worker owns for review-fix routing.

    A directory path owns its descendants. Routing requires both path overlap and the matching
    ``role``; neither a familiar unit name nor a vendor choice substitutes for ownership."""
    fix_requests: list[dict[str, Any]] = field(default_factory=list)
    """Outstanding routing-only fix requests assigned to this Work worker.

    The complete typed result remains an opaque string on ``Run``. These are only the request fields
    Orchestrate is allowed to act on, retained until the worker's repair lands."""
    after: list[str] = field(default_factory=list)
    serialize: list[str] = field(default_factory=list)
    """Wait for these units to finish, without claiming anything about needing their output.

    ``after`` means "I build on what you produce", and it was also being used to mean "do not run
    at the same time as you -- we would both touch the same files" or "wait until that has landed
    so I can rebase on it". A run using it the second way looked blocked for a reason that does
    not exist, and a reader could not tell the two apart. This edge gates launch exactly like
    ``after`` -- a unit is not eligible until every name in both lists is done -- and the
    difference is carried downstream, not in the gate: ``go`` does not ask whether a serialize
    dependency committed anything, and ``status`` names which kind of edge holds a unit."""
    worktree: str | None = None
    branch: str | None = None
    branched_from: str | None = None
    """The commit the unit branch started from, recorded when its worktree is created.

    Kept as creation provenance and for compatibility with existing run records. It cannot prove
    that the unit authored later commits: an empty unit can move its pointer by merging an advanced
    run branch. Landing therefore still requires the second-parent merge shape described by
    ``landed_by_merge``."""
    tab_id: str | None = None
    pane_id: str | None = None
    """The pane this session occupies. Recorded because herdr's event subscriptions are keyed by
    pane, not by agent name -- ``events.subscribe`` rejects a request without one."""
    agent_name: str | None = None
    """What herdr calls this session. The wrapper uniquifies names, so it can differ from
    ``name`` -- which is the plan's identity and the dependency key, and never changes."""
    status: str = PENDING
    note: str = ""
    variant: str | None = None
    """Effective model variant (e.g. for OpenCode), verified before task submission."""
    launch_receipt: dict[str, Any] = field(default_factory=dict)
    """Verified launch state the launcher fills in memory: provider, model, cwd, worktree, pane.

    **Never persisted** (issue #1025). The receipt was a record that outlived its invocation, and
    the card removes the receipt records; what a later invocation actually needs from a launch --
    the tab, the pane and the agent name -- are their own unit fields, written the moment the
    session exists (``record_launch_identity``)."""
    parked_state: dict[str, Any] = field(default_factory=dict)
    """Typed parked state for push-succeeded / PR-creation-blocked recovery."""
    merge_state: str = MERGE_READY
    """Where this unit stands in the merge-turn sequence: ``ready``, ``merging`` or ``merged``.

    Ordinary execution state, not a lock: it carries no owner token and no expiry, and a row left
    at ``merging`` by a turn that died is reset by the next turn once git confirms no merge is in
    flight (see ``stale_merge_turn``). The software-development-lifecycle repository's
    parent-branch chapter describes merge turns exactly this way and explicitly rejects a lock
    service for them."""
    owned: bool = False
    """Did this run's launcher create the tab this unit records?

    The launcher proves ownership from its launch receipt and refuses to close a tab it did not
    create. The receipt itself is no longer persisted (issue #1025 removes the receipt records),
    so the one FACT the close needs is kept as its own field -- an identity fact like ``tab_id``,
    not a record of the launch. Without it a reload left orchestrate unable to close a tab it had
    made, and every later sweep reported a borrowed tab it should have closed.
    ``session_owned`` reads this whenever the receipt is absent."""
    merge_worktree: str | None = None
    """The detached worktree this unit's merge turn is running in, while a turn is in flight.

    Cleared at the end of every turn, in a ``finally``. It is how a ``merging`` row is checked
    against reality rather than trusted: no worktree, or a worktree with no merge in flight, means
    the turn died and the row is released."""
    launch_started_at: str | None = None
    """When ``go`` persisted this unit's launch, written BEFORE the launcher is called.

    This is what makes a repeated ``go`` in the launch window launch the unit once: the row is
    already ``running`` when the second call reads it, so eligibility does not return it. There is
    no claim, no owner and no expiry -- see DECISIONS ``{#1025-immediate-persist-not-a-reservation}``
    for the residual this deliberately leaves."""
    shared_blockers: list[dict[str, Any]] = field(default_factory=list)
    """Blockers this unit meets, each naming the ONE unit that owns its repair.

    Orchestrate does not diagnose blockers and never writes a row here; it only reads them, so two
    units never both repair the same thing. The producer is whoever notices the blocker -- the
    coordinator, or a role session writing through the record."""


@dataclass
class ReviewRouting:
    """Routing actions extracted from an otherwise opaque typed review result."""

    outcome: str
    run_branch: str = ""
    work_requests: int = 0
    dispatches: list[tuple[Unit, dict[str, Any]]] = field(default_factory=list)
    replacements: list[Unit] = field(default_factory=list)
    assignments: list[tuple[Unit, dict[str, Any]]] = field(default_factory=list)
    operator_requests: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class RunBranchState:
    """The recorded run branch and the commit it resolved to when the run was loaded."""

    name: str
    commit: str | None


class RunBranchResolutionError(RuntimeError):
    """A branch-dependent predicate was asked about an unresolvable run branch."""


# Unit-row keys that are in-memory only and never reach the record (issue #1025).
UNPERSISTED_UNIT_FIELDS = frozenset({"launch_receipt"})


class RecordError(RuntimeError):
    """The per-issue run record could not be used. The command line maps it to exit 2."""


class UnknownRecordVersionError(RecordError):
    """The record carries a version this Orchestrate does not know. Exit 3."""


@dataclass
class Run:
    run_id: str
    source: str
    base: str
    units: list[Unit]
    backend: str = "inline"
    """The execution backend every saga unit in this run uses.

    Decided once, up front, because it is a property of the run rather than of a unit -- and because
    `/work` otherwise stops to ask in a background tab nobody is watching. Always ``inline`` today:
    a dispatched unit is already one of several parallel sessions, so nesting a workflow inside one
    is the orchestration-of-orchestration this plugin exists to avoid."""
    branch: str = ""
    """The run's shared branch -- what a team would call the feature branch.

    Every unit branches from here and lands back here when it finishes, so the next phase opens on
    everything the earlier phases actually produced rather than on one predecessor's branch. At the
    end this is the single branch that merges into the operator's tree."""
    branch_state: RunBranchState | None = field(default=None, init=False, repr=False)
    """One load-time resolution of ``branch``; absent only for a legacy branchless run."""
    issue: int = 0
    """The issue this run belongs to. The run's identity, and the record's file name."""
    store_root: Path | None = field(default=None, repr=False)
    """Where this run's record lives. Absolute, and the same from every linked worktree."""
    record: Any = field(default=None, repr=False)
    """The loaded ``run_record.v1`` document this run is a view over."""
    workspaces_created: list[str] = field(default_factory=list)
    """Herdr workspaces this run created, so ``clean`` can retire exactly those and no others."""
    workspace: str | None = None
    """Default herdr workspace NAME every unit inherits unless it sets its own.

    Absent means today's behaviour: sessions land in the caller's workspace. A unit with its own
    ``workspace`` wins; there is no other precedence."""
    account: str | None = None
    """Default account selection every unit inherits unless it sets its own (e.g. "company")."""
    issues: dict[str, str] = field(default_factory=dict)
    """Unit name -> issue reference (``owner/repo#N``) whose board card this run reports to.

    This driver no longer writes to a board at all (issue 1028): saga submits each of the run's
    lifecycle boundaries itself, through its own boundary interface and mission-control's
    constrained mutation. The mapping is kept because it is still how a unit is tied to the card
    its work belongs to, which readers other than a board write use."""
    status_map: dict[str, Any] = field(default_factory=dict)
    """Unit-name prefix -> board rung overrides, replacing the default one key at a time.

    A rung is a ``(Stage, Status)`` pair, stored in a run file as a two-element JSON array.
    Nothing in this file submits one any more, and there is no default map left to override
    (issue 1028): saga owns the board moves and checks each pair against the lifecycle
    repository's allowed list. The field is retained, loaded and saved unchanged so a run file
    written before that change still round-trips."""
    review_result: str | None = None
    """The latest typed Code Review result, stored verbatim and never normalized."""
    review_outcome: str | None = None
    """The result's routing outcome, copied without deriving a review-policy decision."""
    review_resubmit_pending: bool = False
    """Whether landed Work repairs must be resubmitted to the one review controller."""
    operator_fix_requests: list[dict[str, Any]] = field(default_factory=list)
    """Outstanding human or release requests this run is waiting on."""
    review_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    """Typed review state per Code Review controller, keyed by controller unit name.

    ``review_result``, ``review_outcome``, ``review_resubmit_pending`` and ``operator_fix_requests``
    above are the single-controller view and stay authoritative for runs with one review phase.  A
    run carrying several scoped controllers keeps each controller's typed state here instead, so one
    controller's outcome, resubmit flag, or unresolved fix requests can never be read as another's
    (#877)."""
    review_controller_ceiling: int | None = None
    """Most Code Review controllers this run may have running at once, when declared."""

    @classmethod
    def load(cls, issue: int, store_root: Path | None = None) -> Run:
        """Read *issue*'s run from saga's per-issue run record (issue #1025).

        There is no run file any more. One record per issue is what lets two issues be driven in
        one repository at once, and the store root comes from the git COMMON directory, so a
        unit's own worktree reads the same file the coordinator writes -- issue 886's fifth
        finding was that a repository-relative, git-ignored directory resolves to an empty one
        inside a worktree.
        """
        root = Path(store_root) if store_root is not None else resolve_record_store_root()
        record = load_record(root, issue)
        block = record.extra.get(ORCHESTRATE_BLOCK)
        if not isinstance(block, dict):
            raise RecordError(
                f"the run record for issue {issue} carries no {ORCHESTRATE_BLOCK!r} block, so this "
                "issue has no orchestrate run; `orchestrate.py start --issue "
                f"{issue} --plan <plan>` creates one"
            )
        loaded = cls(
            run_id=str(block.get("run_id") or f"issue-{issue}"),
            source=str(block.get("source", "")),
            base=str(block.get("base", "")),
            units=[read_unit(u) for u in record.units],
            backend=str(block.get("backend", "inline")),
            branch=str(block.get("branch", "")),
            issue=int(issue),
            store_root=root,
            record=record,
            workspaces_created=list(block.get("workspaces_created") or []),
            issues=dict(block.get("issues") or {}),
            status_map=dict(block.get("status_map") or {}),
            workspace=block.get("workspace") or None,
            account=block.get("account") or None,
            review_result=block.get("review_result"),
            review_outcome=block.get("review_outcome"),
            review_resubmit_pending=bool(block.get("review_resubmit_pending", False)),
            operator_fix_requests=list(block.get("operator_fix_requests") or []),
            review_states=dict(block.get("review_states") or {}),
            review_controller_ceiling=review_ceiling_from_plan(block),
        )
        loaded.resolve_branch_once()
        return loaded

    def parameter(self, name: str) -> Any:
        """One run-configuration parameter's value, or ``None`` when the record has no record."""
        if self.record is None:
            return None
        entry = self.record.run_configuration.get(name)
        if isinstance(entry, dict):
            return entry.get("value")
        return entry

    def open_roster_rows(self) -> int:
        """How many role sessions this issue still has open.

        Counted against the same width number this run's units are counted against: the number
        exists for the account's rate limit, and a role pane is an agent session like any other.
        """
        if self.record is None:
            return 0
        return sum(1 for row in self.record.roster if str(row.get("state")) != "closed")

    def resolve_branch_once(self) -> None:
        """Resolve the named run branch once and retain both success and failure as state."""
        if not self.branch:
            self.branch_state = None
            return
        if self.branch_state is None or self.branch_state.name != self.branch:
            self.branch_state = RunBranchState(self.branch, resolve_ref(self.branch))

    @property
    def resolved_branch(self) -> str | None:
        """The cached run-branch commit, or None for a legacy or unresolvable branch."""
        self.resolve_branch_once()
        return self.branch_state.commit if self.branch_state is not None else None

    @property
    def unresolvable_branch(self) -> str | None:
        """The recorded branch name when its one load-time resolution failed."""
        self.resolve_branch_once()
        if self.branch_state is not None and self.branch_state.commit is None:
            return self.branch_state.name
        return None

    def resolved_run_ref(self) -> str:
        """The cached run commit, or the historical HEAD fallback for a branchless run."""
        if not self.branch:
            return "HEAD"
        commit = self.resolved_branch
        if commit is None:
            raise RunBranchResolutionError(f"run branch {self.branch!r} does not resolve")
        return commit

    def record_branch_advance(self, commit: str) -> None:
        """Keep the cached resolution current after this process advances the run branch."""
        if self.branch:
            self.branch_state = RunBranchState(self.branch, commit)

    def block(self) -> dict[str, Any]:
        """This run's own state, as it is stored under the record's ``orchestrate`` key."""
        return {
            "run_id": self.run_id,
            "source": self.source,
            "base": self.base,
            "backend": self.backend,
            "branch": self.branch,
            "workspaces_created": self.workspaces_created,
            "issues": self.issues,
            "status_map": self.status_map,
            "workspace": self.workspace,
            "account": self.account,
            "review_result": self.review_result,
            "review_outcome": self.review_outcome,
            "review_resubmit_pending": self.review_resubmit_pending,
            "operator_fix_requests": self.operator_fix_requests,
            "review_states": self.review_states,
            "review_controller_ceiling": self.review_controller_ceiling,
        }

    def save(self) -> Path:
        """Write the unit rows and this run's own block back to the record, and nothing else.

        ``admission``, ``approval_scope``, ``run_configuration``, ``review_cycles`` and ``roster``
        pass through untouched, and so does every OTHER unknown top-level key a newer writer put
        there -- the record module preserves them and this only replaces its own.
        """
        if self.record is None or self.store_root is None:
            raise RecordError("this run is not attached to a record; nothing was written")
        module = _run_record_module()
        extra = dict(self.record.extra)
        extra[ORCHESTRATE_BLOCK] = self.block()
        updated = module.RunRecord(
            **{
                **self.record.__dict__,
                "units": [unit_row(u) for u in self.units],
                "extra": extra,
            }
        )
        self.record = updated
        return Path(module.save(self.store_root, updated))

    def unit(self, name: str) -> Unit:
        for u in self.units:
            if u.name == name:
                return u
        raise SystemExit(f"no unit named {name!r}")

    def reviews_separately(self) -> bool:
        """Does this run have a code-review phase of its own?

        Read off the unit table rather than asked, because the interview already wrote the answer
        there: a review phase is one top-level Code Review controller. An explicit role is
        authoritative. Role-less legacy units retain task-text inference in any vendor's spelling,
        since ``normalize_task`` has not run yet at this point.
        """
        return any(is_review_controller(unit) for unit in self.units)

    def review_controllers(self) -> list[Unit]:
        """Every Code Review controller in this run, in table order."""
        return [unit for unit in self.units if is_review_controller(unit)]

    def review_controller(self) -> Unit | None:
        """Return the single Code Review controller, refusing an ambiguous legacy panel.

        Several controllers are permitted only when each one declares its own child lifecycle; that
        is the deliberate multi-target shape, and callers that need it ask for a controller by name
        through ``review_controller_for``.  An unscoped second controller is still the accidental
        panel this has always refused, and still refuses with the same message (#877).
        """
        controllers = self.review_controllers()
        if len(controllers) > 1:
            if all(unit.lifecycle for unit in controllers):
                raise SystemExit(
                    f"this run has {len(controllers)} scoped Code Review controllers "
                    f"({', '.join(unit.name for unit in controllers)}); name one with "
                    "`--controller` so its typed state cannot be read as another's"
                )
            raise SystemExit(
                "this run has more than one Code Review controller; one review phase is one "
                "top-level controller invocation"
            )
        return controllers[0] if controllers else None

    def review_slot(self, controller: Unit | None) -> dict[str, Any]:
        """Read the typed review state belonging to ``controller``.

        This store is the only authority.  An unscoped run keeps its state under ``RUN_SLOT``; a
        scoped controller keeps its own, which is the whole point -- one controller's outcome,
        resubmit flag and unresolved fix requests must never be legible as another's (#877).
        ``write_review_slot`` mirrors the unscoped slot back onto the run-level fields purely so a
        record written here still loads in an older Orchestrate.  Read through this method, never
        from the run-level fields directly: reading them directly is exactly the miss that left the
        multi-target repair loop unwired.
        """
        key = controller.name if (controller is not None and controller.lifecycle) else RUN_SLOT
        slot = self.review_states.setdefault(key, {})
        if key == RUN_SLOT:
            # Fill from the run-level fields on every read, not once. Adopting only when empty left
            # two live authorities that could disagree the moment either side was written (#877).
            slot.setdefault("review_result", self.review_result)
            slot.setdefault("review_outcome", self.review_outcome)
            slot.setdefault("review_resubmit_pending", self.review_resubmit_pending)
            # Copy, never alias: an aliased list makes the slot and the run-level field the same
            # object, so "two live authorities" becomes true again the moment either is mutated.
            slot.setdefault("operator_fix_requests", list(self.operator_fix_requests))
        slot.setdefault("review_result", None)
        slot.setdefault("review_outcome", None)
        slot.setdefault("review_resubmit_pending", False)
        slot.setdefault("operator_fix_requests", [])
        slot.setdefault("dispatched_fix_ids", [])
        if key != RUN_SLOT:
            self._migrate_run_global_review_state(key, slot)
        return slot

    def _migrate_run_global_review_state(self, key: str, slot: dict[str, Any]) -> None:
        """Copy run-global review state into a newly scoped named slot (#898).

        Named-slot contents are the authority once present. A different result already in
        that slot is a named stop, not an overwrite. Two empty named slots must not both
        inherit the same run-global result.
        """
        run_slot = self.review_states.get(RUN_SLOT, {})
        source_result = run_slot.get("review_result")
        if source_result is None:
            source_result = self.review_result
        if source_result is None:
            return
        if slot.get("run_global_linked"):
            return
        source_outcome = run_slot.get("review_outcome", self.review_outcome)
        source_pending = run_slot.get("review_resubmit_pending", self.review_resubmit_pending)
        source_requests = list(
            run_slot.get("operator_fix_requests") or self.operator_fix_requests or []
        )
        named_empty = (
            slot.get("review_result") is None
            and slot.get("review_outcome") is None
            and not slot.get("review_resubmit_pending")
            and not slot.get("operator_fix_requests")
        )
        if not named_empty:
            if slot.get("review_result") != source_result:
                raise SystemExit(
                    f"controller {key!r} already has a typed review result that conflicts "
                    "with run-global review state; refusing to overwrite either slot"
                )
            slot["run_global_linked"] = True
            return
        empty_named = 0
        for unit in self.review_controllers():
            if not unit.lifecycle:
                continue
            other = slot if unit.name == key else self.review_states.get(unit.name, {})
            if (
                other.get("review_result") is None
                and other.get("review_outcome") is None
                and not other.get("review_resubmit_pending")
                and not other.get("operator_fix_requests")
            ):
                empty_named += 1
        if empty_named > 1:
            raise SystemExit(
                "run-global review state cannot be copied into more than one empty named "
                "slot; name which controller owns it"
            )
        slot["review_result"] = source_result
        slot["review_outcome"] = source_outcome
        slot["review_resubmit_pending"] = bool(source_pending)
        slot["operator_fix_requests"] = list(source_requests)
        slot["run_global_linked"] = True

    def write_review_slot(self, controller: Unit | None, **changes: Any) -> None:
        """Write typed review state back to whichever slot ``controller`` owns."""
        slot = self.review_slot(controller)
        slot.update(changes)
        if controller is not None and controller.lifecycle:
            slot["run_global_linked"] = True
        if controller is None or not controller.lifecycle:
            # Mirror to the run-level fields so a record written here still loads in an older
            # Orchestrate, and so the single-controller view stays true for anything reading it.
            for key, value in changes.items():
                setattr(self, key, value)

    def review_controller_for(self, selector: str) -> Unit:
        """Return the controller named by ``selector``, refusing anything that is not one.

        ``selector`` is a unit name or a declared lifecycle.  A result aimed at a unit that is not a
        Code Review controller, or at a name this run does not carry, is refused rather than routed
        somewhere plausible -- misrouting typed state is the failure this scoping exists to prevent.
        """
        controllers = self.review_controllers()
        matched = [
            unit
            for unit in controllers
            if unit.name == selector
            or (unit.lifecycle and str(unit.lifecycle).strip() == str(selector).strip())
        ]
        if len(matched) > 1:
            # Storing the wrong target's verdict is the exact failure this scoping prevents, so an
            # ambiguous selector is refused rather than resolved by table order.
            raise SystemExit(
                f"selector {selector!r} matches {len(matched)} Code Review controllers "
                f"({', '.join(unit.name for unit in matched)}); name one unambiguously"
            )
        if matched:
            return matched[0]
        named = [unit for unit in self.units if unit.name == selector]
        if named:
            raise SystemExit(
                f"unit {selector!r} is not a Code Review controller; refusing to record a typed "
                "review result against it"
            )
        known = ", ".join(
            f"{unit.name}" + (f" (lifecycle {unit.lifecycle})" if unit.lifecycle else "")
            for unit in controllers
        )
        raise SystemExit(
            f"this run has no Code Review controller {selector!r}"
            + (f"; it has {known}" if known else "; it has none")
        )

    def eligible(self) -> list[Unit]:
        """Pending units whose every ordering edge is satisfied.

        ``after`` and ``serialize`` gate identically -- a unit is not eligible until every name in
        both lists is done. What the edge *means* is carried elsewhere: see ``wait_reason``."""
        done = {u.name for u in self.units if u.status == DONE}
        ready = [
            u
            for u in self.units
            if u.status == PENDING and all(dep in done for dep in u.after + u.serialize)
        ]
        return self._within_review_ceiling(ready)

    def _within_review_ceiling(self, ready: list[Unit]) -> list[Unit]:
        """Hold back Code Review controllers that would exceed the run's declared ceiling.

        A ceiling is a launch limit, not a plan limit: the run may legitimately carry more scoped
        controllers than it is allowed to run at once, and the surplus simply waits for a live one
        to finish rather than being refused at load (#877).  Non-controller units are never held.
        """
        ceiling = self.review_controller_ceiling
        if ceiling is None:
            return ready
        live = sum(1 for u in self.units if is_review_controller(u) and u.status == RUNNING)
        room = ceiling - live
        held: list[Unit] = []
        for unit in ready:
            if not is_review_controller(unit):
                held.append(unit)
                continue
            if room > 0:
                held.append(unit)
                room -= 1
        return held

    def wait_reason(self, unit: Unit) -> str:
        """Why a pending unit is still pending, naming the kind of each edge that holds it.

        ``after`` and ``serialize`` gate launch identically but mean different things -- one
        needs the dependency's output, the other only asks not to run beside it -- and while both
        lived in ``after``, a reader could not tell them apart. Empty means nothing holds the
        unit: it is eligible and simply has not been launched yet."""
        done = {u.name for u in self.units if u.status == DONE}
        parts: list[str] = []
        if (
            unit.status == PENDING
            and is_review_controller(unit)
            and all(dep in done for dep in unit.after + unit.serialize)
            and unit not in self.eligible()
        ):
            live = sum(1 for u in self.units if is_review_controller(u) and u.status == RUNNING)
            parts.append(
                f"review controller ceiling {self.review_controller_ceiling} reached "
                f"({live} running)"
            )
        needs = [dep for dep in unit.after if dep not in done]
        if needs:
            parts.append(f"needs output from {', '.join(needs)}")
        behind = [dep for dep in unit.serialize if dep not in done]
        if behind:
            parts.append(f"serialized behind {', '.join(behind)}")
        return "; ".join(parts)


def _atomic_write_text(target: Path, content: str, encoding: str = "utf-8") -> None:
    """Write content to target atomically via a temporary file in the same directory."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(f".tmp.{os.getpid()}_{uuid.uuid4().hex[:8]}")
    try:
        temp_path.write_text(content, encoding=encoding)
        temp_path.replace(target)
    finally:
        if temp_path.exists():
            with contextlib.suppress(OSError):
                temp_path.unlink()


# ------------------------------------------------------- saga's per-issue run record (issue #1025)

#: Points straight at saga's ``run_record.py``, for a layout the resolver below does not know.
RUN_RECORD_ENV = "ORCHESTRATE_RUN_RECORD"

_RUN_RECORD_MODULE: Any = None


def _run_record_candidates() -> list[Path]:
    """Where saga's ``run_record.py`` can live, in order of trust.

    The repository layout first, because this file ships beside the saga plugin in one checkout,
    then each vendor's install cache, newest version first. A bare ``<plugin>/../saga/`` guess is not
    enough on its own -- in an install cache the sibling of ``orchestrate/<version>/`` is
    ``orchestrate/``, not ``saga/``.
    """
    here = Path(__file__).resolve()
    root = _plugin_root(here)
    # 1. The repository layout: this file ships beside the saga plugin in one checkout.
    paths = [root.parent / "saga" / "scripts" / "run_record.py"]
    # 2. The SIBLING CACHE layout, which the repository probe cannot reach: an install cache holds
    #    `<marketplace>/orchestrate/<version>/` and `<marketplace>/saga/<version>/`, so the sibling
    #    of this plugin's root is `orchestrate/`, not `saga/`, and the version directory sits
    #    between them. Newest version first, the same ordering `_install_candidates` uses and for
    #    the same reason: a stale saga resolved here would read the record with an older contract.
    marketplace = root.parent.parent
    paths.extend(
        sorted(
            (
                Path(hit)
                for hit in glob.glob(str(marketplace / "saga" / "*" / "scripts" / "run_record.py"))
            ),
            key=lambda path: (_version_rank(path, "saga"), str(path)),
            reverse=True,
        )
    )
    # 3. Every vendor's own install cache, newest version first.
    paths.extend(_install_candidates("saga", "scripts/run_record.py"))
    return paths


def _run_record_module() -> Any:
    """Import saga's ``run_record`` by path, once per process.

    Neither plugin is importable as a package, so the module is loaded from its file. A missing
    saga is a refusal naming every path that was tried, never a traceback out of an import.
    """
    global _RUN_RECORD_MODULE
    if _RUN_RECORD_MODULE is not None:
        return _RUN_RECORD_MODULE
    override = os.environ.get(RUN_RECORD_ENV, "")
    candidates = [Path(override).expanduser()] if override else _run_record_candidates()
    for path in candidates:
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("run_record", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules.setdefault("run_record", module)
        spec.loader.exec_module(module)
        _RUN_RECORD_MODULE = module
        return module
    tried = ", ".join(str(path) for path in candidates) or "<nothing>"
    raise RecordError(
        "saga's run_record module could not be found, so this issue's run record cannot be read; "
        f"install the saga plugin beside orchestrate, or point {RUN_RECORD_ENV} at run_record.py. "
        f"Tried: {tried}"
    )


def resolve_record_store_root(start: Path | None = None) -> Path:
    """The absolute run-record store, resolved through saga's own resolver.

    Never re-derived here. The resolution reads the git COMMON directory rather than the
    worktree's own, which is the whole reason a unit's worktree and the coordinator see one file;
    a second copy of that rule in this plugin is the drift this repository keeps paying for.
    """
    module = _run_record_module()
    try:
        return Path(module.resolve_store_root(start))
    except Exception as exc:  # the module raises its own StoreRootError
        raise RecordError(f"the run record store could not be resolved: {exc}") from None


def _record_warn(message: str) -> None:
    """Report an unknown top-level record field, except this plugin's own block.

    ``orchestrate`` is an unknown key from ``run_record``'s point of view and a known one from
    here, so warning about it on every read would train the operator to ignore the warning that
    matters -- a field a NEWER writer added, which is the case issue 989 is about.
    """
    if f"{ORCHESTRATE_BLOCK!r}" in message:
        return
    print(message, file=sys.stderr)


def load_record(store_root: Path, issue: int) -> Any:
    """Read *issue*'s record, mapping saga's errors onto this module's own."""
    module = _run_record_module()
    try:
        record = module.load(store_root, issue, warn=_record_warn)
    except module.UnknownRecordVersionError as exc:
        raise UnknownRecordVersionError(str(exc)) from None
    except module.RunRecordError as exc:
        raise RecordError(str(exc)) from None
    if record is None:
        raise RecordError(
            f"there is no run record for issue {issue} in {store_root}; run the admission step "
            f"first: `python3 plugins/saga/scripts/admission.py --issue {issue}`"
        )
    return record


def unit_row(unit: Unit) -> dict[str, Any]:
    """One unit's row for the record, with the in-memory-only fields left out."""
    return {key: value for key, value in asdict(unit).items() if key not in UNPERSISTED_UNIT_FIELDS}


def _orchestrate_version() -> str:
    """This Orchestrate's version, from the root Claude manifest.

    That file carries the version and paths. The companion dependency floor is
    read from whichever manifest states ``dependencies``; both files carry the
    same version.
    """
    manifest = _plugin_root(Path(__file__).resolve()) / ".claude-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return "unknown"


def read_unit(raw: dict[str, Any]) -> Unit:
    """One unit from its row in the record's ``units`` array.

    The task is the row's own text: there is no spill file any more (issue #1025). The spill
    existed because the old fixed-path run file was rewritten whole on every save and 83% of a
    75-unit record was task text; one issue's record is not that file.

    A key this Unit does not know is dropped with a one-line notice naming the unit, the key
    and this Orchestrate's version. That is a safety net for a hand-edited row, or one a newer
    Orchestrate added a field to; the record's own ``schema`` token is what refuses a document
    this version cannot read at all, before any unit row is reached.
    """
    known = set(Unit.__dataclass_fields__)
    unknown = [key for key in raw if key not in known]
    if unknown:
        for key in unknown:
            print(
                f"WARNING: unit {raw.get('name', '?')} carries unknown key {key!r}; this "
                f"Orchestrate {_orchestrate_version()} ignores it (written by a newer "
                "Orchestrate)",
                file=sys.stderr,
            )
        raw = {key: value for key, value in raw.items() if key in known}
    unit = Unit(**raw)
    if unit.lifecycle is not None:
        # Normalise here rather than in the plan guard alone: review-result, merge, status and reap
        # all load the run without passing through that guard, and "c2" versus "c2 " being two
        # lifecycles for routing is exactly the bypass the one-per-lifecycle rule forbids (#877).
        unit.lifecycle = unit.lifecycle.strip() or None
    return unit


def is_code_review_task(task: str) -> bool:
    """Whether task text *invokes* Saga's Code Review controller in any supported spelling.

    Anchored to a command position -- start of text or after whitespace -- because the sigil is
    otherwise indistinguishable from an ordinary path separator.  Without the anchor a Work or
    Document Review unit is classified as a Code Review controller merely for naming the directory
    where committed typed results live, and the operator then cannot tell a real second controller
    from a false positive (#877).
    """
    return bool(re.search(r"(?:^|(?<=\s))[/$](?:saga:)?code-review(?=$|\s|[.,:;!?](?:\s|$))", task))


def is_review_controller(unit: Unit) -> bool:
    """Identify a controller without letting generated Work prose override an explicit role."""
    return unit.role == REVIEW_CONTROLLER_ROLE or (
        unit.role is None and is_code_review_task(unit.task)
    )


def plan_units(plan: Mapping[str, Any]) -> list[Unit]:
    """Load unit rows and enforce one top-level Code Review controller per plan.

    Older plans identified Code Review only through their task text. Preserve that authoring shape,
    but assign the explicit controller role while loading it and refuse the former N-reviewer panel.
    Work routing roles require path ownership because a role alone cannot identify the responsible
    worker for a finding.
    """
    raw_units = plan.get("units")
    if not isinstance(raw_units, list):
        raise SystemExit("plan `units` must be a list")
    units: list[Unit] = []
    for raw in raw_units:
        if not isinstance(raw, dict):
            raise SystemExit("every plan unit must be an object")
        try:
            unit = Unit(**raw)
        except TypeError as exc:
            raise SystemExit(f"invalid plan unit: {exc}") from None
        unit.permission_declared = "permission" in raw
        if unit.role == REVIEW_CONTROLLER_ROLE:
            if not is_code_review_task(unit.task):
                raise SystemExit(
                    f"unit {unit.name!r} declares {REVIEW_CONTROLLER_ROLE!r} but does not invoke "
                    "Code Review"
                )
        elif unit.role is None and is_code_review_task(unit.task):
            unit.role = REVIEW_CONTROLLER_ROLE
        if unit.role in WORK_FIX_ROLES and not unit.paths:
            raise SystemExit(
                f"Work worker {unit.name!r} declares role {unit.role!r} without owned paths"
            )
        if unit.paths:
            unit.paths = [
                _route_path(path, label=f"unit {unit.name!r} owned path") for path in unit.paths
            ]
        units.append(unit)
    assert_review_transport(units)
    omitted = [unit.name for unit in units if not unit.permission_declared]
    if omitted:
        print(f"permission not declared, inheriting {Unit.permission}: {', '.join(omitted)}")
    return units


def review_ceiling_from_plan(plan: Mapping[str, Any]) -> int | None:
    """Read and validate ``review_controller_ceiling`` from a plan.

    A ceiling that silently fails to load is worse than none: the operator believes launches are
    capped and they are not.  So a present-but-unusable value is refused rather than dropped (#877).
    """
    if "review_controller_ceiling" not in plan:
        return None
    raw = plan["review_controller_ceiling"]
    if raw is None:
        return None
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
        raise SystemExit(f"review_controller_ceiling must be a positive whole number, got {raw!r}")
    return raw


def assert_single_review_controller(units: Sequence[Unit]) -> None:
    """Refuse the superseded one-full-review-per-reviewer plan shape.

    One review phase is still one controller.  What is now also expressible is a run carrying
    several *independent child lifecycles*, each with its own frozen target and its own typed
    result: that shape declares a distinct ``lifecycle`` on every controller, which is what
    separates it from the accidental panel this refuses (#877).  Anything less than fully scoped --
    a missing lifecycle, or two controllers claiming the same one -- is still the old error.
    """
    controllers = [unit for unit in units if is_review_controller(unit)]
    if len(controllers) <= 1:
        return

    for unit in controllers:
        if unit.lifecycle is not None:
            unit.lifecycle = unit.lifecycle.strip() or None
    unscoped = [unit for unit in controllers if not unit.lifecycle]
    if unscoped:
        names = ", ".join(unit.name for unit in controllers)
        raise SystemExit(
            f"review phase has {len(controllers)} controller units ({names}); create exactly one "
            "top-level Code Review controller, or give each one its own `lifecycle`"
        )

    seen: dict[str, str] = {}
    for unit in controllers:
        lifecycle = str(unit.lifecycle).strip()
        if lifecycle in seen:
            raise SystemExit(
                f"Code Review controllers {seen[lifecycle]!r} and {unit.name!r} both claim "
                f"lifecycle {lifecycle!r}; each controller owns exactly one"
            )
        seen[lifecycle] = unit.name

    # A name that equals another controller's lifecycle would make `--controller` ambiguous at the
    # moment a typed result arrives, which is far too late to discover it.
    names = {unit.name for unit in controllers}
    collide = names & set(seen)
    for value in sorted(collide):
        if seen[value] != value:
            raise SystemExit(
                f"controller name {value!r} also names another controller's lifecycle; "
                "`--controller` could not tell them apart"
            )


def is_explicit_non_code_review_capability(task: str) -> bool:
    """Whether task text begins with an explicit non-Code-Review Saga capability invocation.

    Matches either namespaced capability invocations (e.g. ``/saga:plan``, ``$saga:doc-review``)
    or bare capability commands for known non-Code-Review Saga capabilities (e.g. ``/doc-review``,
    ``/founder-review``, ``/plan``). Does not match Code Review invocations, unknown capabilities,
    or untyped prompts.
    """
    match = re.match(r"^\s*[/$](?:saga:)?([a-z0-9_-]+)\b", task, re.IGNORECASE)
    if not match:
        return False
    cap = match.group(1).lower()
    return cap in _NON_CODE_REVIEW_CAPABILITIES


def is_standalone_review_prompt(unit: Unit) -> bool:
    """A review-shaped unit that declares no role, i.e. a bespoke review.

    Wording cannot carry this decision. "review this PR" and "do a code review of the
    branch" are the same request, and no regex that admits the first while refusing the
    second is worth trusting. The role field this run record already carries is the
    signal: a reviewer seat, a work-fix worker, and an operator row each say what they
    are, so anything left over that talks about reviewing is the bespoke review the
    leaf refuses.

    Explicit non-Code-Review Saga capabilities (such as leading ``/saga:plan`` or
    ``/doc-review``) are not bespoke reviews even if they contain the word "review".
    """
    if is_code_review_task(unit.task):
        return False
    if unit.role is not None:
        return False
    if is_explicit_non_code_review_capability(unit.task):
        return False
    return bool(_REVIEW_SHAPED.search(unit.task))


def is_reviewer_seat(unit: Unit) -> bool:
    return unit.role == REVIEWER_SEAT_ROLE


def assert_no_engine_prefs(plan: Mapping[str, Any]) -> None:
    """The engine-prefs seam is retired; reviewer seats live in the run unit table."""
    if plan.get("engine_prefs"):
        raise SystemExit(
            "plan carries engine_prefs; that seam is retired (#776). Represent reviewer "
            "seats as named units with role 'review-controller' or 'external-reviewer' "
            "in the Orchestrate run record, not .saga/engine-prefs.json"
        )


def assert_review_transport(units: Sequence[Unit]) -> None:
    """Refuse bespoke reviews and unrecorded reviewer launches when Code Review is present.

    Halt. Never fall back to the retired saga external-engine runner.
    """
    if not any(is_review_controller(unit) for unit in units):
        return
    assert_single_review_controller(units)
    for unit in units:
        if is_review_controller(unit):
            continue
        if _RETIRED_TRANSPORT.search(unit.task):
            raise SystemExit(
                f"unit {unit.name!r} names the retired saga external-engine runner; halt and "
                f"dispatch reviewer seats through expand/go with role {REVIEWER_SEAT_ROLE!r}"
            )
        if is_code_review_task(unit.task) and unit.role not in {
            *WORK_FIX_ROLES,
            *OPERATOR_FIX_ROLES,
        }:
            raise SystemExit(
                f"unit {unit.name!r} is a duplicate Code Review; create exactly one "
                "top-level review-controller and dispatch extra reviewer seats through "
                f"expand/go with role {REVIEWER_SEAT_ROLE!r}"
            )
        if is_reviewer_seat(unit):
            # The sanctioned transport. A seat's task reads like a review instruction
            # because reviewing is what the seat is for; refusing it here would leave
            # the run record with no way to express the reviewer the leaf requires.
            continue
        if is_standalone_review_prompt(unit):
            raise SystemExit(
                f"unit {unit.name!r} is a plain review prompt; when a Saga Code Review "
                "phase is present, Orchestrate refuses bespoke reviews. Add a named "
                f"{REVIEWER_SEAT_ROLE!r} seat through expand/go, or halt"
            )


def _route_path(value: object, *, label: str) -> str:
    """Normalize one repository-relative path used only for ownership overlap."""
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{label} must be non-empty text")
    if "\n" in value or "\r" in value:
        raise SystemExit(f"{label} must not contain a newline")
    path = value.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    path = path.rstrip("/")
    if not path or path.startswith("/") or ".." in path.split("/"):
        raise SystemExit(f"{label} must be a repository-relative path: {value!r}")
    return path


def route_paths_overlap(left: Sequence[str], right: Sequence[str]) -> bool:
    """Whether two exact-or-directory-prefix repository path sets overlap."""
    left_paths = [_route_path(path, label="worker path") for path in left]
    right_paths = [_route_path(path, label="fix request touched path") for path in right]
    return any(
        a == b or a.startswith(f"{b}/") or b.startswith(f"{a}/")
        for a in left_paths
        for b in right_paths
    )


def _review_routing_fields(raw_result: str) -> tuple[str, list[dict[str, Any]]]:
    """Read only the result fields Orchestrate is authorized to route.

    Scores, dimensions, cycles, priorities, confidence, and all other Code Review policy stay
    untouched. The original string is persisted separately on ``Run`` before this function is
    called by the command surface.
    """
    try:
        payload = json.loads(raw_result)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"review result is not JSON: {exc}") from None
    if not isinstance(payload, dict):
        raise SystemExit("review result must be a JSON object")
    schema = payload.get("schema")
    if schema != REVIEW_RESULT_SCHEMA:
        raise SystemExit(
            f"review result has unsupported schema {schema!r}; expected {REVIEW_RESULT_SCHEMA!r}"
        )
    outcome = payload.get("outcome")
    if not isinstance(outcome, str) or outcome not in REVIEW_OUTCOMES:
        raise SystemExit(f"review result has unsupported routing outcome {outcome!r}")
    if outcome != "repairs_requested":
        return str(outcome), []

    raw_requests = payload.get("fix_requests")
    if not isinstance(raw_requests, list):
        raise SystemExit("repairs_requested result requires a fix_requests list")
    requests: list[dict[str, Any]] = []
    for index, item in enumerate(raw_requests):
        if not isinstance(item, dict):
            raise SystemExit(f"fix request {index} must be an object")
        owner = item.get("owner")
        if not isinstance(owner, str) or owner not in WORK_FIX_ROLES | OPERATOR_FIX_ROLES:
            raise SystemExit(f"fix request {index} has unsupported owner role {owner!r}")
        fix_id = item.get("fix_id")
        if not isinstance(fix_id, str) or not fix_id.strip():
            raise SystemExit(f"fix request {index} requires a non-empty fix_id")
        if "\n" in fix_id or "\r" in fix_id:
            raise SystemExit(f"fix request {index} fix_id must not contain a newline")
        touched = item.get("touched_paths")
        if not isinstance(touched, list) or not touched:
            raise SystemExit(f"fix request {fix_id!r} requires touched_paths")
        normalized = [
            _route_path(path, label=f"fix request {fix_id!r} touched path") for path in touched
        ]
        request = json.loads(json.dumps(item, ensure_ascii=False))
        request["owner"] = owner
        request["fix_id"] = fix_id.strip()
        request["touched_paths"] = normalized
        requests.append(request)
    return str(outcome), requests


def _unit_is_terminal(unit: Unit) -> bool:
    """Whether the run has already retired this unit; routing must not revive it."""
    return unit.status in TERMINAL_UNIT_STATUSES


def _unit_is_live(unit: Unit, agents: Sequence[Mapping[str, Any]]) -> bool:
    """Whether Herdr still reports the worker's recorded pane or agent identity."""
    return any(
        (unit.pane_id and row.get("pane_id") == unit.pane_id)
        or ((unit.agent_name or unit.name) == row.get("name"))
        for row in agents
    )


def _fix_request_id(request: Mapping[str, Any]) -> str:
    """Return the already-validated request identity."""
    return str(request["fix_id"])


def _unit_has_fix_request(unit: Unit, fix_id: str) -> bool:
    """Whether a unit already carries the identified review repair."""
    return any(_fix_request_id(request) == fix_id for request in unit.fix_requests)


def _park_fix_request(
    r: Run, holder: Unit, request: dict[str, Any], controller: Unit | None = None
) -> None:
    """Keep one outstanding copy of a review repair on its actionable holder.

    The strip is confined to the controller's own lifecycle: clearing a same-identifier request from
    another lifecycle's worker would silently discharge that target's outstanding repair (#877).
    """
    fix_id = _fix_request_id(request)
    for unit in _lifecycle_units(r, controller):
        unit.fix_requests = [
            existing for existing in unit.fix_requests if _fix_request_id(existing) != fix_id
        ]
    holder.fix_requests.append(request)


def _request_prompt(request: Mapping[str, Any], *, run_branch: str = "") -> str:
    """A Work instruction carrying the structured request without the surrounding result."""
    refresh = (
        f"Before editing, merge the current run branch `{run_branch}` into this unit branch so the "
        "repair is based on the reviewed revision. "
        if run_branch
        else ""
    )
    return (
        refresh
        + "Apply only this Code Review fix request as Work. Keep the request's owner role and path "
        "scope, commit the repair on this unit's branch, run the relevant checks, and stop. The "
        "complete review result remains opaque to Orchestrate; this is its routing request:\n\n"
        + json.dumps(request, ensure_ascii=False, sort_keys=True)
    )


def _replacement_name(
    template: Unit,
    request: Mapping[str, Any],
    existing: set[str],
    controller: Unit | None = None,
) -> str:
    """Create a stable safe unit name without treating the request identity as a path."""
    slug = re.sub(r"[^a-z0-9]+", "-", _fix_request_id(request).lower()).strip("-") or "repair"
    if controller is not None and controller.lifecycle:
        stem_base = str(controller.lifecycle).strip()
    elif controller is not None:
        stem_base = controller.name
    else:
        stem_base = template.name
    stem_base = re.split(r"-fix(?:-|$)", stem_base, maxsplit=1)[0].rstrip("-") or stem_base
    stem = f"{stem_base}-repair-{slug}"[:80].rstrip("-")
    candidate = stem
    suffix = 2
    while candidate in existing:
        candidate = f"{stem}-{suffix}"
        suffix += 1
    return candidate


def _replacement_worker(
    template: Unit, request: dict[str, Any], controller: Unit | None, existing: set[str]
) -> Unit:
    """Create a fresh Work unit from an approved worker's execution configuration."""
    name = _replacement_name(template, request, existing, controller)
    task = f"/saga:work {_request_prompt(request)}"
    scoped_lifecycle = controller.lifecycle if controller is not None else None
    workspace = (
        f"{str(scoped_lifecycle).strip()}-repair" if scoped_lifecycle else template.workspace
    )
    replacement = Unit(
        name=name,
        vendor=template.vendor,
        task=task,
        model=template.model,
        effort=template.effort,
        permission=template.permission,
        setup=list(template.setup),
        launch_args=list(template.launch_args),
        workspace=workspace,
        account=template.account,
        merge=True,
        role=str(request["owner"]),
        paths=list(request["touched_paths"]),
        fix_requests=[request],
        serialize=[controller.name] if controller is not None else [],
        note=f"minted from {template.name}",
        # A replacement minted without its controller's lifecycle leaves that child lifecycle:
        # _lifecycle_units cannot see it, so resubmit stops waiting on its outstanding repair and
        # land resubmits the frozen target before the repair exists (#877).
        lifecycle=template.lifecycle or scoped_lifecycle,
    )
    existing.add(name)
    return replacement


def route_review_result(
    r: Run,
    raw_result: str,
    *,
    agents: Sequence[Mapping[str, Any]] | None = None,
    controller: Unit | None = None,
) -> ReviewRouting:
    """Route one persisted result without making or recomputing a review decision.

    ``controller`` is the already-selected owner of this result.  It is passed in rather than
    resolved here because resolution is the caller's decision once a run may carry several scoped
    controllers, and re-deriving it would reintroduce the ambiguity (#877).
    """
    outcome, requests = _review_routing_fields(raw_result)
    if controller is None:
        controller = r.review_controller()
    r.write_review_slot(controller, review_outcome=outcome, operator_fix_requests=[])
    operator_requests: list[dict[str, Any]] = r.review_slot(controller)["operator_fix_requests"]
    routing = ReviewRouting(outcome=outcome, run_branch=r.branch)
    if outcome != "repairs_requested":
        r.write_review_slot(controller, review_resubmit_pending=False)
        return routing

    live = list(live_agents() if agents is None else agents)
    names = {unit.name for unit in r.units}
    for request in requests:
        owner = str(request["owner"])
        if owner in OPERATOR_FIX_ROLES:
            operator_requests.append(request)
            routing.operator_requests.append(request)
            continue

        routing.work_requests += 1
        fix_id = _fix_request_id(request)
        touched_paths = list(request["touched_paths"])
        # A lifecycle-less worker may serve as a mint TEMPLATE, but a scoped controller in a
        # multi-controller run must not reuse it as a live holder: that shares one session between
        # two frozen targets, and landing it discharges both repairs (#877).
        role_workers = [
            unit for unit in _lifecycle_units(r, controller, shared_ok=True) if unit.role == owner
        ]
        matching = [unit for unit in role_workers if route_paths_overlap(unit.paths, touched_paths)]
        # No carve-out for a single scoped controller. The count is read at route time, so a run
        # that parks while it has one controller and later gains a second through `expand` would
        # strand the first controller's repairs on a worker its own resubmit gate cannot see. And
        # even with one controller the gate reads `shared_ok=False`, so a bag parked on an unscoped
        # worker is invisible and land resubmits before the repair exists. A scoped controller
        # therefore never reuses a live lifecycle-less holder -- it always mints a stamped copy.
        scoped = bool(controller is not None and controller.lifecycle)
        reusable = [
            unit
            for unit in matching
            if _unit_is_live(unit, live)
            and not _unit_is_terminal(unit)
            and not (scoped and not unit.lifecycle)
        ]
        if reusable:
            worker = reusable[0]
            _park_fix_request(r, worker, request, controller)
            routing.dispatches.append((worker, request))
            continue

        eligible_names = {unit.name for unit in r.eligible()}
        assigned = next(
            (
                unit
                for unit in _lifecycle_units(r, controller)
                if _unit_has_fix_request(unit, fix_id)
                and not _unit_is_terminal(unit)
                and (_unit_is_live(unit, live) or unit.name in eligible_names)
            ),
            None,
        )
        if assigned is not None:
            _park_fix_request(r, assigned, request, controller)
            routing.assignments.append((assigned, request))
            continue

        templates = matching or role_workers
        if not templates:
            raise SystemExit(
                f"no Work worker declares owner role {owner!r}; cannot choose a replacement "
                "vendor or execution tier"
            )
        replacement = _replacement_worker(templates[0], request, controller, names)
        r.units.append(replacement)
        _park_fix_request(r, replacement, request, controller)
        if templates[0].name in r.issues:
            r.issues[replacement.name] = r.issues[templates[0].name]
        routing.replacements.append(replacement)

    r.write_review_slot(controller, review_resubmit_pending=routing.work_requests > 0)
    return routing


def _send_with_pane_guard(unit: Unit, text: str) -> None:
    """Put one line into a live unit's session through the launcher's only door.

    ``PaneWriter`` is the launcher's single pane-write choke point; Orchestrate does not own
    a door of its own, so it cannot write unguarded. The writer is seeded ``wrote_before``
    true: every unit this sender reaches -- a live worker taking a routed repair, a controller
    taking a resubmission -- was prompted by its launch, so the launcher has already written
    into the session and a person may have typed since. The launcher's owned exemption covers
    only the first write into a pane created seconds earlier; these writes land hours or days
    later into a session the operator has been watching, so ownership alone exempts nothing
    here (terminal review F06). A unit with no pane cannot be inspected and is prompted through
    its agent handle. An inconclusive inspection still sends -- the documented trade in
    ``guard_pane_before_write``.
    """
    writer = PaneWriter(unit, unit.pane_id, wrote_before=True)
    writer.write(text)


def dispatch_review_routing(
    routing: ReviewRouting,
    *,
    sender: Callable[[Unit, str], None] | None = None,
    slot: dict[str, Any] | None = None,
) -> list[str]:
    """Send routed requests to live workers; replacement units launch through ordinary ``go``."""
    send_one = sender or _send_with_pane_guard
    dispatched: list[str] = []
    already = list((slot or {}).get("dispatched_fix_ids") or [])
    for unit, request in routing.dispatches:
        if _unit_is_terminal(unit):
            continue
        fix_id = _fix_request_id(request)
        if fix_id in already:
            dispatched.append(unit.name)
            continue
        try:
            send_one(unit, _request_prompt(request, run_branch=routing.run_branch))
        except StagedInputError as exc:
            if str(exc) not in unit.note:
                append_unit_note(unit, str(exc))
            print(exc)
            continue
        unit.status = RUNNING
        append_unit_note(unit, f"outstanding review fix {fix_id}")
        dispatched.append(unit.name)
        already.append(fix_id)
        if slot is not None:
            slot["dispatched_fix_ids"] = list(already)
    return dispatched


def complete_landed_fix_requests(r: Run, landed_names: Sequence[str]) -> list[str]:
    """Clear only requests whose assigned worker was merged by this land invocation."""
    completed: list[str] = []
    for name in landed_names:
        unit = r.unit(name)
        if not unit.fix_requests:
            continue
        completed.extend(_fix_request_id(request) for request in unit.fix_requests)
        unit.fix_requests.clear()
        append_unit_note(unit, "review fix landed")
    return completed


def _lifecycle_units(r: Run, controller: Unit | None, *, shared_ok: bool = False) -> list[Unit]:
    """Units this controller owns: its own lifecycle, or the whole run when unscoped.

    Routing a repair across this boundary hands one frozen target's fix to another target's worker,
    and landing one controller then clears the other's outstanding requests (#877).
    """
    if controller is None or not controller.lifecycle:
        scoped = {u.lifecycle for u in r.units if u.lifecycle}
        if not scoped:
            return list(r.units)
        return [u for u in r.units if not u.lifecycle]

    want = str(controller.lifecycle).strip()
    owned = [u for u in r.units if u.lifecycle and str(u.lifecycle).strip() == want]
    if not shared_ok:
        # Reusing one lifecycle-less worker from several scoped controllers couples the very targets
        # this scoping isolates: both park on one session, landing it discharges both repairs, and
        # until then each child's parked bag blocks the other's resubmit (#877).  Such a worker is a
        # mint TEMPLATE only -- `_replacement_worker` stamps the controller's lifecycle onto the
        # copy, so the repair that actually runs belongs to exactly one target.
        return owned
    return owned + [u for u in r.units if not u.lifecycle and not is_review_controller(u)]


def resubmit_review_if_ready(
    r: Run,
    revision: str,
    *,
    sender: Callable[[Unit, str], None] | None = None,
    landed_names: Sequence[str] = (),
    landed_revisions: Mapping[str, str] | None = None,
) -> bool:
    """Resubmit the landed revision through the same controller when every Work repair landed.

    "The same controller" is load-bearing once a run may carry several: a landed repair belongs to
    the controller whose result requested it, and resubmitting it anywhere else would hand one
    frozen target's repair to another target's review (#877).
    """
    pending = [
        unit
        for unit in r.review_controllers()
        if unit.lifecycle and r.review_slot(unit)["review_resubmit_pending"]
    ]
    if pending:
        # Each scoped controller recovers independently. One controller still holding an operator
        # request or a live worker must not block another whose repairs are clear -- that would make
        # two independent targets unable to recover at all (#877). A controller withheld on staged
        # input does not block the others either, but it is still a resubmission this land did
        # not make: once every controller has had its turn, the withheld ones are raised together
        # so `land` exits 4 exactly as it does for any other resubmission failure (cycle 2, F42).
        sent = False
        withheld: list[str] = []
        failed: list[str] = []
        landed = set(landed_names)
        tips = dict(landed_revisions or {})
        for candidate in pending:
            if candidate.status == RUNNING:
                continue
            if landed:
                owned = {
                    unit.name for unit in _lifecycle_units(r, candidate) if unit.name in landed
                }
                if not owned:
                    continue
                owned_tips = [tips[name] for name in landed_names if name in owned and name in tips]
                candidate_revision = owned_tips[-1] if owned_tips else revision
            else:
                candidate_revision = revision
            try:
                if _resubmit_one(r, candidate, candidate_revision, sender=sender):
                    sent = True
                    print(
                        f"resubmitted landed revision {candidate_revision} through {candidate.name}"
                    )
            except StagedInputError:
                withheld.append(candidate.name)
            except SystemExit as exc:
                failed.append(f"{candidate.name}: {exc}")
                print(f"  {candidate.name} resubmission skipped: {exc}")
        if withheld:
            raise StagedInputError(
                f"resubmission withheld for {', '.join(withheld)}: the composer holds staged "
                "input; clear it and land again"
            )
        if failed:
            raise SystemExit(
                "resubmission write failed for "
                + "; ".join(failed)
                + "; later controllers were still attempted"
            )
        return sent

    controller = r.review_controller()
    if not r.review_slot(controller)["review_resubmit_pending"]:
        return False
    if controller is None:
        raise SystemExit("review repairs landed, but this run has no Code Review controller")
    return _resubmit_one(r, controller, revision, sender=sender)


def _resubmit_one(
    r: Run,
    controller: Unit,
    revision: str,
    *,
    sender: Callable[[Unit, str], None] | None = None,
) -> bool:
    """Resubmit ``revision`` through one controller, if that controller's own work is clear.

    "Its own" is the whole point: a worker belonging to another lifecycle is not this controller's
    business, and treating it as blocking is what deadlocks two independent targets.
    """
    slot = r.review_slot(controller)
    if slot["operator_fix_requests"]:
        return False
    if any(unit.fix_requests for unit in _lifecycle_units(r, controller)):
        return False
    task = normalize_task(controller.vendor, controller.task, r.backend)
    task += (
        f" The routed Work repairs are now landed on the run branch at revision {revision}. "
        "Resubmit that exact revision through this same Code Review controller and emit the next "
        "complete typed result for `review-result` collection."
    )
    send_one = sender or _send_with_pane_guard
    try:
        send_one(controller, task)
    except StagedInputError as exc:
        # Record, report, and raise. The multi-controller loop in resubmit_review_if_ready
        # catches this per controller so one staged composer never blocks the others (cycle 1,
        # F23); the single-controller path lets it reach `land`'s failure handler, so a
        # resubmission that was withheld exits 4 like every other resubmission failure instead
        # of falling through to exit 0 (cycle 2, F42). The pending flag stays set either way, so
        # the next land retries once the composer is clear.
        if str(exc) not in controller.note:
            append_unit_note(controller, str(exc))
        print(f"  {controller.name} resubmission withheld: {exc}")
        raise
    controller.status = RUNNING
    append_unit_note(controller, f"resubmitted landed revision {revision}")
    r.write_review_slot(controller, review_resubmit_pending=False)
    return True


def _plugin_root(script: Path) -> Path:
    """The plugin root above a script, in both layouts this plugin ships in.

    The relative depth is the same in the repository and the installed cache:
    <plugin-root>/<skills>/<plugin-name>/scripts/<file>, so three parents above a script is
    always the plugin root -- the cache's version directory plays the same role. Every
    other place that needs a sibling plugin or a plugin manifest goes through here, so the
    layout is named once.
    """
    return script.parents[3]


def _version_tuple(value: str) -> tuple[int, int, int]:
    """Parse the numeric three-part plugin versions used by this repository."""
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if match is None:
        raise SystemExit(f"agent-launcher has unsupported version {value!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _manifest_with_dependencies(root: Path) -> Path:
    """The manifest that states Orchestrate's companion dependency floor.

    The root ``.claude-plugin/plugin.json`` carries paths and the version. The
    dependency array rides on the Claude adapter manifest under
    ``com.infiquetra.claude/``, which is the upstream manifest after import. A
    root manifest that still states ``dependencies`` stays the one that is read.
    """
    root_manifest = root / ".claude-plugin" / "plugin.json"
    adapter = root / "com.infiquetra.claude" / "plugin.json"
    for candidate in (root_manifest, adapter):
        if not candidate.is_file():
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("dependencies"):
            return candidate
    return adapter if adapter.is_file() else root_manifest


def _declared_agent_launcher_floor(manifest: Path | None = None) -> tuple[int, int, int]:
    """Read the one authoritative companion floor from Orchestrate's own manifest."""
    if manifest is None:
        manifest = _manifest_with_dependencies(_plugin_root(Path(__file__).resolve()))
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        dependencies = payload["dependencies"]
        requirement = next(
            entry["version"]
            for entry in dependencies
            if isinstance(entry, dict) and entry.get("name") == "agent-launcher"
        )
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise SystemExit(
            f"cannot read Orchestrate's agent-launcher dependency from {manifest}: {exc}"
        ) from None
    match = re.fullmatch(r">=(\d+\.\d+\.\d+)", str(requirement))
    if match is None:
        raise SystemExit(
            f"Orchestrate's agent-launcher dependency must be a numeric >= floor, got "
            f"{requirement!r} in {manifest}"
        )
    return _version_tuple(match.group(1))


class _LauncherFloorFailure(SystemExit):
    """A launcher that loads but sits below the floor Orchestrate declares for it.

    Still a ``SystemExit`` so every existing caller reads it the same way; ``remedy`` names
    this fault's own remedy, which differs by cause (update for a stale install).
    """

    def __init__(self, message: str, remedy: str) -> None:
        super().__init__(f"{message.rstrip('.')}. {remedy}")


def _companion_version_manifest(package_root: Path) -> Path:
    """Where a companion package states its version.

    An authored package in this catalog states it on the portable ``plugin.json``.
    A Claude install states it on ``.claude-plugin/plugin.json``. The adapter
    manifest is the middle candidate.
    """
    for relative in (
        "plugin.json",
        "com.infiquetra.claude/plugin.json",
        ".claude-plugin/plugin.json",
    ):
        candidate = package_root / relative
        if candidate.is_file():
            return candidate
    return package_root / ".claude-plugin" / "plugin.json"


def _validated_agent_launcher(path: Path) -> Path:
    """Enforce Orchestrate's declared companion-plugin version floor at runtime."""
    manifest = _companion_version_manifest(_plugin_root(path))
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        version = _version_tuple(str(payload["version"]))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"cannot verify agent-launcher manifest {manifest}: {exc}") from None
    minimum = _declared_agent_launcher_floor()
    if version < minimum:
        required = ".".join(str(part) for part in minimum)
        actual = ".".join(str(part) for part in version)
        raise _LauncherFloorFailure(
            f"agent-launcher {actual} is installed; Orchestrate requires >={required}",
            _UPDATE_REMEDIATION,
        )
    return path


def _agent_launcher_script() -> Path | None:
    """Locate the sibling ``plugins/agent-launcher`` package.

    ``AGENT_LAUNCHER_ROOT``, when set, is that package's root and replaces the
    default. The default is the sibling package next to this one in the catalog.
    There is no search of a Claude plugin cache.
    """
    override = os.environ.get("AGENT_LAUNCHER_ROOT")
    if override:
        candidate = Path(override) / "skills" / "agent-launcher" / "scripts" / "launcher.py"
        if not candidate.is_file():
            raise SystemExit(
                f"AGENT_LAUNCHER_ROOT={override!r} does not contain "
                "skills/agent-launcher/scripts/launcher.py"
            )
        return candidate
    here = Path(__file__).resolve()
    repo_candidate = (
        _plugin_root(here).parent
        / "agent-launcher"
        / "skills"
        / "agent-launcher"
        / "scripts"
        / "launcher.py"
    )
    if repo_candidate.is_file():
        return repo_candidate
    return None


def _subprocess_run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Fallback command runner used when the agent-launcher plugin is absent."""
    try:
        proc = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if check:
            raise SystemExit(f"timed out after {timeout}s: {' '.join(cmd)}") from None
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timed out")
    except OSError as exc:
        if check:
            raise SystemExit(f"cannot run {cmd[0]!r}: {exc}") from None
        return subprocess.CompletedProcess(cmd, returncode=127, stdout="", stderr=str(exc))
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{err}")
    return proc


_INSTALL_REMEDIATION = "claude plugin install agent-launcher@infiquetra-plugins"
_UPDATE_REMEDIATION = "claude plugin update agent-launcher@infiquetra-plugins"
_REMEDIATION_MESSAGE = (
    f"agent-launcher plugin not found. Install the companion plugin: {_INSTALL_REMEDIATION}"
)
# The companion fault, composed per cause: a stale install carries the update remedy, a
# missing or unusable one carries the install remedy, and each names its own cause.
_AGENT_LAUNCHER_ERROR: str | None = None
_COMPANION_FAULT_PRINTED = False


def _agent_launcher_error(detail: str) -> str:
    """One failure contract for a companion that cannot be used at all."""
    return f"{detail.rstrip('.')}. Install the companion plugin: {_INSTALL_REMEDIATION}"


def _agent_launcher_required(*_args: Any, **_kwargs: Any) -> Any:
    raise SystemExit(_AGENT_LAUNCHER_ERROR or _REMEDIATION_MESSAGE)


def _print_companion_fault_once() -> None:
    """Print the companion fault once per process, for a read-only degraded command."""
    global _COMPANION_FAULT_PRINTED
    if _COMPANION_FAULT_PRINTED:
        return
    _COMPANION_FAULT_PRINTED = True
    print(_AGENT_LAUNCHER_ERROR or _REMEDIATION_MESSAGE, file=sys.stderr)


def assert_agent_launcher_ingested() -> None:
    """Refuse a read-only command only when no companion was ingested at all.

    The KTD7 matrix's read side for the two informational commands, ``roster`` and ``saga``:
    they list vendors and saga capabilities and never write a pane, create a session or
    worktree, or close a tab, so a companion that is merely below the floor still serves
    them -- exactly as it serves ``wait``, ``settle`` and ``adopt``. A missing or unusable
    companion has nothing to read with and refuses with the install remedy. Gating these
    two on the floor was a smaller instance of the fail-closed regression this plugin
    already shipped once (terminal review F24), and it contradicted the decision record.
    """
    if not _AGENT_LAUNCHER_AVAILABLE:
        raise SystemExit(_AGENT_LAUNCHER_ERROR or _REMEDIATION_MESSAGE)


def assert_agent_launcher_available() -> None:
    """Refuse before any pane write, session or worktree creation, or tab close.

    The five commands that call this: ``start``, ``expand``, ``go``, ``review-result``,
    ``merge`` and ``clean``.

    **A companion below the declared floor WARNS and the command continues** (issue #1025). The
    distinction that survives is between stale and absent: a below-floor launcher still defines
    every name orchestrate calls, so the call can be made and the operator is told the install is
    behind; a launcher that was never ingested, or that is missing a required name, has nothing to
    call and still refuses with the install remedy. Refusing on the floor made an out-of-date
    install indistinguishable from a broken one, and stopped work that would have succeeded.
    """
    if not _AGENT_LAUNCHER_AVAILABLE:
        raise SystemExit(_AGENT_LAUNCHER_ERROR or _REMEDIATION_MESSAGE)
    if _AGENT_LAUNCHER_ERROR:
        _print_companion_fault_once()


def _ingest_agent_launcher() -> bool:
    """Load the shared launcher into this module's globals.

    Tests monkeypatch ``run``, ``live_agents``, ``launch``, and friends on this
    module. ``exec`` into ``globals()`` makes those names the ones the extracted
    functions look up, so the patches still apply. Importing a second module
    would hide them. A missing plugin must not kill every subcommand at import.
    The exec is atomic: a launcher that fails partway through its own import binds
    nothing (the namespace is restored), and a successful ingest restores this
    module's own ``__doc__``, so ``--help`` keeps describing Orchestrate. Floor
    policy after a successful ingest is
    ``docs/engineering-journal/DECISIONS.md`` ``{#907-agent-launcher-floor-owner}``.
    """
    global _AGENT_LAUNCHER_ERROR
    try:
        script = _agent_launcher_script()
    except SystemExit as exc:
        _AGENT_LAUNCHER_ERROR = _agent_launcher_error(str(exc))
        return False
    if script is None:
        _AGENT_LAUNCHER_ERROR = _REMEDIATION_MESSAGE
        return False
    try:
        source = script.read_text(encoding="utf-8")
    except OSError as exc:
        _AGENT_LAUNCHER_ERROR = _agent_launcher_error(
            f"cannot read agent-launcher at {script}: {exc}"
        )
        return False
    missing, unusable = _companion_source_faults(source)
    if missing:
        _AGENT_LAUNCHER_ERROR = (
            f"agent-launcher at {script} does not define {', '.join(missing)}; Orchestrate "
            f"requires a release that does. {_UPDATE_REMEDIATION}"
        )
        return False
    if unusable:
        _AGENT_LAUNCHER_ERROR = (
            f"agent-launcher at {script} is unusable: {unusable}. {_UPDATE_REMEDIATION}"
        )
        return False
    try:
        _validated_agent_launcher(script)
    except _LauncherFloorFailure as exc:
        # A stale launcher is still ingested, so read-only commands -- status, check, wait,
        # settle, adopt, roster, saga -- keep their Herdr reads through it; the floor gates
        # only the six commands that would write a pane, create a session or worktree, or
        # close a tab, and this fault carries the update remedy.
        _AGENT_LAUNCHER_ERROR = str(exc)
    except SystemExit as exc:
        # Orchestrate's own manifest could not name a floor. The launcher is still ingested
        # for reads; writes are gated behind this cause and the install remedy.
        _AGENT_LAUNCHER_ERROR = _agent_launcher_error(str(exc))
    # launcher.py has a ``__main__`` CLI. When orchestrate.py is the entry point,
    # ingest would otherwise run that CLI against orchestrate's argv (``wait``,
    # ``clean``, …) and exit. The flag is this module's globals, not the environment.
    globals()["_AGENT_LAUNCHER_INGESTING"] = True
    # Caller obligation: this compile filename is the ingested launcher's only authority for
    # where its sibling composer.py lives -- the loader resolves the parser from this frame's
    # co_filename -- so it must stay the launcher's real path. A placeholder makes every
    # ingested launch stop with the named wrong-directory message.
    snapshot = dict(globals())
    own_doc = globals()["__doc__"]
    try:
        exec(compile(source, str(script), "exec"), globals())
    except (SystemExit, Exception) as exc:
        # The exec is atomic: a launcher that fails partway through its own import binds
        # nothing, not a subset of its names over this module's own definitions.
        globals().clear()
        globals().update(snapshot)
        _AGENT_LAUNCHER_ERROR = _agent_launcher_error(
            f"agent-launcher at {script} is unusable: {type(exc).__name__}: {exc}"
        )
        return False
    # The exec binds the launcher's module docstring into this namespace, so --help would
    # describe the launcher; Orchestrate keeps describing Orchestrate.
    globals()["__doc__"] = own_doc
    _bind_missing_launcher_names(script)
    return True


# Every launcher name Orchestrate calls. The degraded block below binds each to the
# required-companion stub when nothing was ingested; ``_bind_missing_launcher_names`` binds the
# same stub for any of them a launcher that WAS ingested does not define -- a companion whose
# manifest satisfies the floor but whose source predates it, or a launcher root pointed at an
# older tree (cycle 2, F54/F69/F72). Without that check a missing name surfaced as a NameError
# at the first pane write instead of the named companion fault with the update remedy.
REQUIRED_LAUNCHER_NAMES = (
    "launch",
    "redeliver",
    "agent_argv",
    "launcher",
    "launchable",
    "roster",
    "live_agents",
    "close_run_session",
    "tab_close_failure",
    "verify_unit_preflight",
    "agent_row",
    "session_has_started",
    "append_unit_note",
    "PaneWriter",
    "session_owned",
    "should_guard_pane_write",
    "guard_pane_before_write",
    "models",
    "favourites",
    "has_delivery_warning",
    "clear_delivery_warning",
    "VENDOR_FLAGS",
    "VENDOR_PERMISSION",
    "VENDOR_NOTES",
    "AccountMismatchError",
    "StagedInputError",
    "ComposerState",
)


def _top_level_defined_names(tree: ast.AST) -> set[str]:
    """Names a companion module binds at top level: defs, classes, and assignment targets."""
    names: set[str] = set()
    body = getattr(tree, "body", ())
    for node in body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                names.update(_assignment_target_names(target))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _assignment_target_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for elt in target.elts:
            names.update(_assignment_target_names(elt))
        return names
    return set()


def _guard_calls_pane_input_inspection(tree: ast.AST) -> bool:
    """True when ``guard_pane_before_write`` in this tree calls ``pane_input_inspection``."""
    body = getattr(tree, "body", ())
    for node in body:
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "guard_pane_before_write"
        ):
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Name)
                    and child.func.id == "pane_input_inspection"
                ):
                    return True
            return False
    return False


def _companion_source_faults(source: str) -> tuple[list[str], str | None]:
    """AST-validate companion source before exec.

    Returns (missing required names, unusable reason). A name-only stub whose
    ``guard_pane_before_write`` does not call ``pane_input_inspection`` is unusable
    even when every required name is defined. Floor checking is separate.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [], f"invalid Python: {exc}"
    defined = _top_level_defined_names(tree)
    missing = [name for name in REQUIRED_LAUNCHER_NAMES if name not in defined]
    if not _guard_calls_pane_input_inspection(tree):
        return missing, "guard_pane_before_write does not call pane_input_inspection"
    return missing, None


def _companion_names_are_live() -> bool:
    """True when no required name is still the refuse stub after ingest."""
    for name in REQUIRED_LAUNCHER_NAMES:
        if name in ("AccountMismatchError", "StagedInputError"):
            obj = globals().get(name)
            if not (isinstance(obj, type) and issubclass(obj, BaseException)):
                return False
            continue
        if name not in globals() or globals()[name] is _agent_launcher_required:
            return False
    return True


def _bind_missing_launcher_names(script: Path) -> None:
    """After a successful exec, refuse the write side by name for any required name absent.

    The stub raises the companion fault; the two stop classes are bound to local exception
    types so ``except`` clauses keep working. The fault carries the update remedy, because a
    launcher that loads but lacks these names is an older release, whatever its manifest says.
    An error already recorded (a floor failure) is kept: it names the same remedy.
    """
    global _AGENT_LAUNCHER_ERROR
    missing = [name for name in REQUIRED_LAUNCHER_NAMES if name not in globals()]
    if not missing:
        return
    for name in missing:
        if name in ("AccountMismatchError", "StagedInputError"):
            globals()[name] = type(name, (Exception,), {})
        else:
            globals()[name] = _agent_launcher_required
    if not _AGENT_LAUNCHER_ERROR:
        _AGENT_LAUNCHER_ERROR = (
            f"agent-launcher at {script} does not define {', '.join(missing)}; Orchestrate "
            f"requires a release that does. {_UPDATE_REMEDIATION}"
        )


run = _subprocess_run
if not _ingest_agent_launcher():
    _AGENT_LAUNCHER_AVAILABLE = False
    launch = _agent_launcher_required
    redeliver = _agent_launcher_required
    agent_argv = _agent_launcher_required
    launcher = _agent_launcher_required
    launchable = _agent_launcher_required
    roster = _agent_launcher_required
    live_agents = _agent_launcher_required
    close_run_session = _agent_launcher_required
    tab_close_failure = _agent_launcher_required
    verify_unit_preflight = _agent_launcher_required
    agent_row = _agent_launcher_required
    session_has_started = _agent_launcher_required
    append_unit_note = _agent_launcher_required
    PaneWriter = _agent_launcher_required
    session_owned = _agent_launcher_required
    should_guard_pane_write = _agent_launcher_required
    guard_pane_before_write = _agent_launcher_required
    models = _agent_launcher_required
    favourites = _agent_launcher_required
    has_delivery_warning = _agent_launcher_required
    clear_delivery_warning = _agent_launcher_required
    VENDOR_FLAGS = {}
    VENDOR_PERMISSION = {}
    VENDOR_NOTES = {}
    ComposerState = _agent_launcher_required

    class AccountMismatchError(Exception):
        pass

    class StagedInputError(Exception):
        pass
else:
    # Exec succeeded. Missing names were stubbed by ``_bind_missing_launcher_names``;
    # those companions are ingested-but-unusable and must not take the live-read path
    # (F107). A below-floor companion with live names stays available for reads.
    _AGENT_LAUNCHER_AVAILABLE = _companion_names_are_live()


def repo_root() -> Path:
    return Path(run(["git", "rev-parse", "--show-toplevel"]).stdout.strip())


# ----------------------------------------------------------------- launching


def produced_anything(dep: Unit, r: Run) -> bool:
    """Did this unit actually commit something to its branch?

    A dependent unit opens on its dependency's branch, so if that branch is still sitting at the
    base commit there is nothing there to work on. Launching anyway does not fail loudly -- the
    session finds no plan, no diff, no artifact, and writes something plausible about nothing. That
    happened: a doc-review unit reviewed a plan document that was never written.

    "Commit something" means what THIS unit did, and it is read two ways. First, its own commits
    still on its branch: counted from the merge base of the run branch and the unit's branch --
    the point the unit was cut from -- so inherited work does not count. Counting from the run's
    original base did exactly that: a unit created after the first land is cut from a run branch
    that already carries the landed commits, so it counted as productive the moment it existed.
    Measured live on one run: four units with zero commits of their own each reported six. The
    consequences were all live: `check` could never say NO COMMITS after the first land, its
    LOOKS DONE fired on any post-land unit merely idle between turns, and `go`'s dependency gate
    -- which exists because a doc-review once reviewed a plan that was never written -- could
    never catch an empty dependency again. Second, a unit whose commits already landed still
    produced: see ``landed_by_merge``.
    """
    if not dep.branch:
        return False
    return branch_produced_anything(dep.branch, r)


def branch_produced_anything(branch: str, r: Run) -> bool:
    """The branch-level reading behind ``produced_anything`` -- see its docstring for the why."""
    base = r.resolved_run_ref()
    mb = run(["git", "merge-base", base, branch], check=False)
    if mb.returncode != 0:
        return False
    got = run(["git", "rev-list", "--count", f"{mb.stdout.strip()}..{branch}"], check=False)
    if got.returncode == 0 and got.stdout.strip() not in ("", "0"):
        return True
    return landed_by_merge(branch, r)


def landed_by_merge(branch: str, r: Run) -> bool:
    """Is this branch's tip the second parent of a merge on the branch this run lands onto?

    That shape, and only that shape, records work that ``land`` brought home. Git cannot distinguish
    a genuinely fast-forwarded unit from an empty unit whose branch pointer moved by merging the
    advanced run branch: both tips are on the run branch's first-parent history. Inferring either
    from ancestry would let the empty unit launch dependents and be reaped as if it saved work.

    The ref measured is the run branch commit cached at load. A run with no stored run branch
    predates the run-branch design and falls back to ``HEAD`` -- those units landed straight onto
    the operator's tree, where this shape is just as readable. Refusing that case left a legacy
    unit whose work WAS merged reading as produced nothing: ``check`` shouted NO COMMITS at landed
    work, and ``clean --merged`` would not reap it. When ``r.base`` is absent too there is no
    earlier bound to name, so the range is the ref's whole history.
    """
    ref = r.resolved_run_ref()
    tip = run(["git", "rev-parse", "--verify", "--quiet", branch], check=False)
    if tip.returncode != 0 or not tip.stdout.strip():
        return False
    revs = f"{r.base}..{ref}" if r.base else ref
    merges = run(["git", "log", "--first-parent", "--merges", "--format=%P", revs], check=False)
    if merges.returncode != 0:
        return False
    sha = tip.stdout.strip()
    for parents in merges.stdout.splitlines():
        pair = parents.split()
        if len(pair) >= 2 and pair[1] == sha:
            return True
    return False


#: Points at the command that prepares a fresh worktree's environment, for a repository whose
#: setup is not ``uv``.
WORKTREE_SETUP_ENV = "ORCHESTRATE_WORKTREE_SETUP"

#: What a ``uv`` repository's fresh worktree needs before a session can run its own tests.
DEFAULT_WORKTREE_SETUP = ("uv", "sync", "--locked", "--extra", "dev")


def fresh_unit_worktree_path(canonical: Path, *, avoid: Path | None = None) -> Path:
    """The canonical path, or the lowest unused numbered sibling when that is taken.

    "Unused" is THREE tests: nothing at the path on disk (``lexists``, so a dangling symlink
    counts), no git worktree registered there, and not *avoid*. A directory git has forgotten and
    a registration whose directory is gone are both real states, and either one makes
    ``git worktree add`` fail.

    *avoid* is the path this unit used last time, and it counts as taken even after it has been
    removed. That is what makes "a fresh worktree on every launch, never a reused path" a property
    a reader can check on disk rather than a claim about what happened in between: releasing a
    stale tree and recreating a directory of the same name would leave the two launches
    indistinguishable afterwards.
    """
    registered = set(registered_worktree_paths())
    blocked = {Path(os.path.abspath(avoid))} if avoid is not None else set()

    def taken(candidate: Path) -> bool:
        return (
            os.path.lexists(candidate)
            or Path(os.path.abspath(candidate)) in registered
            or Path(os.path.abspath(candidate)) in blocked
        )

    if not taken(canonical):
        return canonical
    number = 1
    while True:
        candidate = canonical.with_name(f"{canonical.name}-{number}")
        if not taken(candidate):
            return candidate
        number += 1


def worktree_setup_command() -> list[str] | None:
    """What to run in a fresh worktree before a session is launched into it, or ``None``.

    Declared, never guessed: the environment variable when it is set, otherwise ``uv sync`` when
    the repository has a ``uv.lock``, otherwise nothing. Copying or linking the primary
    checkout's ``.venv`` is not an option -- a virtual environment records absolute paths, so the
    copy points back at the directory it came from.
    """
    override = os.environ.get(WORKTREE_SETUP_ENV, "").strip()
    if override:
        return shlex.split(override)
    return None


def prepare_worktree_environment(path: Path, root: Path) -> str | None:
    """Run the setup command in *path*; return a failure description, or ``None`` on success.

    A unit whose worktree has no virtual environment produces confident work that cannot run its
    own tests, and the failure surfaces much later as a test result nobody can reproduce. So a
    failing setup is named on the unit and the unit is not launched.
    """
    command = worktree_setup_command()
    if command is None:
        if not (root / "uv.lock").is_file():
            print(f"  {path.name}: no uv.lock and no {WORKTREE_SETUP_ENV}; no setup step run")
            return None
        command = list(DEFAULT_WORKTREE_SETUP)
    print(f"  {path.name}: {' '.join(command)}")
    proc = run(command, check=False, timeout=900)
    if proc.returncode == 0:
        return None
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return f"worktree setup `{' '.join(command)}` failed ({proc.returncode})" + (
        f": {detail[-1]}" if detail else ""
    )


def make_worktree(unit: Unit, r: Run, root: Path) -> str | None:
    """A FRESH worktree on every launch, on the unit's own branch (issue #1025, card 886).

    The branch is the unit's identity and holds its history, so a relaunch reuses it; only the
    working directory is new. A reused directory is what made "fast-forward it, adopt or close the
    prior session, preserve the unknown fields" a question at all -- a fresh one removes the
    question rather than answering it, and it is also why a second ``go`` racing the first can
    never put two sessions in one tree.

    A new branch opens on the parent branch as it stands, with everything merged so far already on
    it. Returns a setup-failure description, or ``None`` when the worktree is ready.
    """
    # dash, not a second slash: git cannot hold `orch/<run>` as a branch and `orch/<run>/<unit>`
    # as another, because one ref would have to be both a file and a directory
    branch = unit.branch or f"orch/{r.run_id}-{unit.name}"
    base = r.branch or r.base
    # The stale directory is RELEASED, not reused and not left behind. git will not check a branch
    # out into a second worktree while the first still holds it, so a relaunch has to let the old
    # one go -- and letting it go is the point: card 886's hazards all begin with a session
    # standing in a tree some earlier session left. The release refuses on uncommitted or unpushed
    # work and names what is at risk, so "fresh" never means "discarded".
    previous = Path(unit.worktree) if unit.worktree else None
    if previous is not None and os.path.lexists(previous):
        released, why = release_unit_worktree(unit, root)
        print(f"  {unit.name}: {why}")
        if not released:
            return (
                "the previous worktree could not be released, so this unit is not relaunched: "
                f"{why}"
            )
    path = fresh_unit_worktree_path(root.parent / f"orch-{r.run_id}-{unit.name}", avoid=previous)
    if resolve_ref(branch) is None:
        run(["git", "worktree", "add", str(path), "-b", branch, base or r.base])
        unit.branched_from = resolve_ref(branch)
    else:
        run(["git", "worktree", "add", str(path), branch])
    unit.worktree = str(path)
    unit.branch = branch
    print(f"  {unit.name}: {path.name} on {branch} from {base}")
    return prepare_worktree_environment(path, root)


def poll(
    unit: Unit,
    agents: list[dict[str, Any]] | None = None,
    *,
    timeout: float = 20,
) -> str:
    """Ask herdr what this session is doing. Absence means the session is gone.

    A caller looking at several units at once passes one already-fetched list rather than paying a
    herdr round trip per unit: an unresponsive herdr costs the timeout once instead of once a row.
    """
    handle = unit.agent_name or unit.name
    for a in live_agents(timeout=timeout) if agents is None else agents:
        if a.get("name") == handle:
            return str(a.get("agent_status", "unknown"))
    return "gone"


def run_branches(run_id: str) -> list[str]:
    """Every local unit branch of this run, exactly as git records them.

    The list is the discovery source for ``check``, ``adopt`` and ``status``: a unit branch that
    exists without a row in the table is work the record lost track of. The run branch itself is
    excluded by the pattern -- it carries no unit-name suffix, so it can never be mistaken for one.

    ``check=False`` because ``status`` is a display command and reads this on every poll: a run
    record left behind in a directory that is no longer a repository made a read-only command exit
    non-zero on a git error it has no way to act on. ``check`` reaches ``repo_root`` first, so it
    still fails loudly when git itself cannot answer.
    """
    proc = run(
        ["git", "branch", "--list", f"orch/{run_id}-*", "--format=%(refname:short)"], check=False
    )
    if proc.returncode != 0:
        return []
    return [b.strip() for b in proc.stdout.splitlines() if b.strip()]


def worktree_on_branch(branch: str) -> str | None:
    """The path of the worktree checked out on this branch, if any."""
    proc = run(["git", "worktree", "list", "--porcelain"])
    wanted = branch if branch.startswith("refs/") else f"refs/heads/{branch}"
    path: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree ") :]
        elif line.startswith("branch ") and line[len("branch ") :] == wanted:
            return path
    return None


def agent_for_worktree(path: str | None, agents: list[dict]) -> dict | None:
    """The live session sitting in this worktree, matched by its cwd.

    A session's cwd is the one thing about it that cannot drift: it was handed to the launcher and
    never changes, while names can be uniquified and statuses come and go. No worktree, no match --
    a branch without its tree cannot be tied to a session.
    """
    if not path:
        return None
    for a in agents:
        if a.get("cwd") == path:
            return a
    return None


def rebuild_unit(name: str, branch: str, r: Run, agents: list[dict]) -> Unit:
    """Reconstruct a unit from what is still true about it: its branch, tree, and session.

    ``task``, ``after``, ``serialize``, ``model``, ``effort`` and ``permission`` are left at their
    defaults: they cannot be recovered, and an invented value is worse than an empty one -- the
    session has already been given its task, so nothing here is ever sent to it again.
    """
    worktree = worktree_on_branch(branch)
    agent = agent_for_worktree(worktree, agents)
    vendor = str(agent.get("agent", "unknown")) if agent else "unknown"
    if agent is not None and agent.get("agent_status") == "working":
        status = RUNNING
    elif agent is not None:
        status = DONE
    elif r.unresolvable_branch:
        status = FAILED
    elif produced_anything(Unit(name=name, vendor=vendor, task="", branch=branch), r):
        status = DONE
    else:
        status = FAILED
    return Unit(
        name=name,
        vendor=vendor,
        task="",
        worktree=worktree,
        branch=branch,
        tab_id=agent.get("tab_id") if agent else None,
        pane_id=agent.get("pane_id") if agent else None,
        agent_name=(agent.get("name") or name) if agent else name,
        status=status,
        note="adopted: created outside the run record",
    )


def discover_unrecorded(r: Run) -> list[tuple[str, str]]:
    """``(unit name, branch)`` for every unit branch the table has no row for, in git's order."""
    prefix = f"orch/{r.run_id}-"
    known = {u.name for u in r.units}
    return [
        (branch[len(prefix) :], branch)
        for branch in run_branches(r.run_id)
        if branch.startswith(prefix) and branch[len(prefix) :] not in known
    ]


# ------------------------------------------------- installed-plugin resolution

# The board writeback that used to live here is GONE (issue 1028): saga now submits each of the
# run's lifecycle boundaries itself, through `board_progression.py`'s boundary interface and
# mission-control's constrained lifecycle-field mutation, so this driver has no board write to make
# and no schema vocabulary to resolve. What survives is the narrow resolver the run-record lookup
# below still needs: find one file inside one plugin's install tree, newest version first.

_VERSION_SEGMENT_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


def _version_rank(path: Path, plugin: str) -> tuple[int, ...]:
    """The parsed version of the install directory ``plugin`` sits in, or ``()`` when there is none.

    An install cache keeps one directory per version, and `sorted()` over the raw glob hits is
    lexicographic: it puts `0.10.0` before `0.9.0` and `0.136.0` before every later release. With
    sixty saga copies installed across two plugin roots on this machine, that made the resolver
    select 0.136.0 -- a saga that predates every contract this file depends on.

    Only the segment DIRECTLY AFTER the plugin's own name is read. An earlier form took the highest
    dotted-numeric segment anywhere in the path, so a marketplace checkout at
    ``cache/infiquetra-9.9.9/saga/0.1.0/`` outranked every real release: the version it sorted on
    belonged to a different thing entirely. A path carrying no version directory ranks lowest, so a
    hand-placed checkout never outranks a real install."""
    parts = path.parts
    for index, part in enumerate(parts[:-1]):
        if part == plugin:
            match = _VERSION_SEGMENT_RE.match(parts[index + 1])
            if not match:
                return ()
            return tuple(int(number) for number in match.group(1).split("."))
    return ()


# ---------------------------------------------------------------------------------------------
# WHY THIS RESOLVER IS HAND-ROLLED, AND WHAT IT DUPLICATES
#
# saga carries `fleet_commons_shim`, a five-rung resolution ladder (env override, repo walk-up,
# installed registry, cache sibling, loud miss) that does this job better than the loop below. This
# file cannot use it, and the reason is structural rather than incidental: the thing being resolved
# IS saga. Importing saga's ladder to find saga is circular, and an Orchestrate on a machine with no
# saga installed -- an ordinary state, which the missing-controller branch below is written for --
# would fail at import rather than degrade.
#
# So this is a deliberate duplicate with a narrower job: find one file inside one plugin's install
# tree, newest version first, with no registry read and no repo walk. What must be kept in step with
# the fleet ladder is the ROOT LIST -- `~/.claude-company` was missing here for exactly as long as
# nobody was comparing the two. If a sixth root is added to the shim, add it here too.
# ---------------------------------------------------------------------------------------------

# The vendor install roots, as `{plugin}` templates. `~/.claude-company` is a SECOND, separate
# plugin tree beside `~/.claude` -- not a symlink to it -- and omitting it made every company-account
# install invisible to this resolver.
_INSTALL_PATTERNS = (
    "~/.claude/plugins/cache/*/{plugin}/*/{tail}",
    "~/.claude-company/plugins/cache/*/{plugin}/*/{tail}",
    "~/.codex/plugins/cache/*/{plugin}/*/{tail}",
    "~/.grok/marketplace-cache/*/plugins/{plugin}/{tail}",
    "~/.qwen/extensions/{plugin}/{tail}",
    "~/.gemini/config/plugins/{plugin}/{tail}",
)


def _install_candidates(plugin: str, tail: str) -> list[Path]:
    """Installed copies of ``plugin``'s ``tail`` file, newest version first ACROSS every root.

    The ranking is global, not per-root. Ranking inside each pattern and then concatenating meant
    root order decided the winner before version did: every copy under ``~/.claude`` outranked
    every copy under ``~/.claude-company``, so a stale saga in the first root beat a newer one in
    the second -- which is the same "an old saga executed the write" failure the version ordering
    exists to prevent, reached by a different door. Ties (equal versions, or none) fall back to
    path order, which keeps root precedence as the tiebreak it should have been all along."""
    found: list[Path] = []
    for pattern in _INSTALL_PATTERNS:
        expanded = str(Path(pattern.format(plugin=plugin, tail=tail)).expanduser())
        found.extend(Path(hit) for hit in glob.glob(expanded))
    return sorted(found, key=lambda path: (_version_rank(path, plugin), str(path)), reverse=True)


def report_cleanup_failures(failures: Sequence[tuple[Path, str]]) -> None:
    """Name every path cleanup could not remove, with git's own message (issue #1025).

    Called from a ``finally`` block, so it must contain nothing that can itself raise: issue 979
    reported a removal failure appended to a list whose only reader was skipped whenever an
    exception was unwinding, which is exactly when a leftover most needs naming.
    """
    for path, detail in failures:
        print(f"  CLEANUP FAILED at {path}: {detail}")


# ----------------------------------------------------------------- commands


def load_plan(path: str) -> dict[str, Any]:
    """Read a plan file, refusing by name rather than by traceback.

    Since the companion floor warns instead of refusing (issue #1025), a plan read is now
    reachable in states that used to stop earlier -- so "this file is not a plan" has to be a
    sentence the operator can act on rather than a JSONDecodeError six frames deep.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"cannot read the plan at {path}: {exc}") from None
    try:
        loaded = json.loads(raw)
    except ValueError as exc:
        raise SystemExit(f"the plan at {path} is not JSON: {exc}") from None
    if not isinstance(loaded, dict):
        raise SystemExit(f"the plan at {path} is not a JSON object")
    return loaded


def validate_plan(plan: Mapping[str, Any]) -> list[Unit]:
    """Every check ``start`` runs before it creates anything, and NOTHING else (issue 879).

    This is the first half of ``start``, not a copy of it: ``plan-check`` calls this and stops,
    ``start`` calls it and goes on to create resources. One code path stays the source of truth,
    so a validator cannot quietly stop agreeing with the ``start`` it claims to match.

    Nothing here writes: no worktree, no branch, no tab, no session, no record. ``plan_units``
    runs ``assert_review_transport`` on its way through, so that check is reached here for the
    same reason ``start`` reaches it -- by the plan parser, with nothing added. (Issue 879 warns
    against *adding* it, having read a ``main`` on which ``plan_units`` did not yet call it.)
    """
    assert_no_engine_prefs(plan)
    assert_safe_path_component(str(plan.get("run_id", "")), "run id")
    units = plan_units(plan)
    assert_safe_unit_names(units)
    assert_dependencies_reachable(units)
    assert_vendors_available(units)
    assert_saga_reachable(units)
    return units


def cmd_plan_check(args: argparse.Namespace) -> int:
    """Validate a plan completely, and create nothing (issue 879).

    Exit 0 means the plan is startable; exit 2 means it is not, with the same message ``start``
    would print. Usable as a gate step, and safe to run while another run is active -- it does not
    read or write any run record at all.
    """
    assert_agent_launcher_ingested()
    plan = load_plan(args.plan)
    units = validate_plan(plan)
    order = " -> ".join(u.name for u in units)
    print(f"plan {plan.get('run_id', '?')}: {len(units)} units validate clean  ({order})")
    print("nothing was created: no worktree, no branch, no tab, no session, no run record.")
    return 0


def parent_branch_name(issue: int, *, runner: Callable[..., Any] | None = None) -> tuple[str, str]:
    """The run's shared branch name for *issue*, and the one line explaining the choice.

    A parent issue with children gets a parent branch, per the software-development-lifecycle
    repository's parent-branch chapter; an issue with no children gets its own. The sub-issue
    count is read ONCE here and then recorded, so a later network failure can never change the
    branch a run is already using. When GitHub cannot answer, the name falls back to the
    standalone form and the printed line says so rather than pretending it knew.
    """
    call = runner or run
    query = (
        '{repository(owner:"infiquetra",name:"infiquetra-claude-plugins")'
        f"{{issue(number:{int(issue)}){{subIssues(first:1){{totalCount}}}}}}}}"
    )
    proc = call(["gh", "api", "graphql", "-f", f"query={query}"], check=False, timeout=60)
    if getattr(proc, "returncode", 1) != 0:
        return f"issue/{issue}", "GitHub could not be asked for sub-issues, so the standalone name"
    try:
        payload = json.loads(proc.stdout)
        count = int(payload["data"]["repository"]["issue"]["subIssues"]["totalCount"])
    except (ValueError, KeyError, TypeError):
        return f"issue/{issue}", "GitHub's answer could not be read, so the standalone name"
    if count > 0:
        return f"parent/{issue}", f"issue {issue} has {count} sub-issue(s), so the parent name"
    return f"issue/{issue}", f"issue {issue} has no sub-issues, so the standalone name"


def cmd_start(args: argparse.Namespace) -> int:
    """Create the branch and the unit rows for one issue's run.

    ``start`` REQUIRES the record and never creates one: the record is written by saga's
    admission step, which is what fills the thirteen run-configuration parameters and the seven
    approval boundaries. Minting one here would produce a record whose admission block is empty,
    which every later reader would have to treat as "not asked yet".
    """
    assert_agent_launcher_available()
    plan = load_plan(args.plan)
    units = validate_plan(plan)
    store_root = Path(args.store_root) if args.store_root else resolve_record_store_root()
    record = load_record(store_root, args.issue)
    base = args.base or run(["git", "rev-parse", "HEAD"]).stdout.strip()
    if args.branch:
        branch, why = args.branch, "named on the command line, so"
    else:
        branch, why = parent_branch_name(args.issue)
    r = Run(
        run_id=plan["run_id"],
        source=plan.get("source", ""),
        base=base,
        units=units,
        backend=plan.get("backend", "inline"),
        branch=branch,
        issue=int(args.issue),
        store_root=store_root,
        record=record,
        issues=plan.get("issues", {}),
        status_map=plan.get("status_map", {}),
        workspace=plan.get("workspace") or None,
        account=plan.get("account") or None,
        review_controller_ceiling=review_ceiling_from_plan(plan),
    )
    exists = run(["git", "rev-parse", "--verify", "--quiet", r.branch], check=False)
    if exists.returncode != 0:
        run(["git", "branch", r.branch, base])
    path = r.save()
    print(f"{why} the run branch is {r.branch}, from {base[:8]}")
    order = " -> ".join(u.name for u in r.units)
    print(f"run {r.run_id}: {len(r.units)} units on base {base[:8]}  ({order})")
    print(f"record {path}")
    print(f"`orchestrate.py go --issue {args.issue}` to launch what is eligible.")
    return 0


def probe(name: str) -> tuple[str, dict[str, bool]]:
    """Ask one tool's own help what tier control it offers, and whether ours still works.

    Only run against agents ``VENDOR_FLAGS`` claims to know -- those are the entries that can rot,
    and running ``--help`` on an arbitrary tool could start something.

    Returns the help text plus, per key, whether the tool advertises *any* flag for it. The check
    for whether *our* flag still exists is done against the token orchestrate actually passes, not
    against a guessed name: codex sets effort through ``-c key=value``, which no search for
    ``--effort`` would ever find.
    """
    got = run([name, "--help"], check=False, timeout=20)
    out = (got.stdout or "") + (got.stderr or "")
    return out, {
        "model": bool(re.search(r"--model\b", out)),
        "effort": bool(re.search(r"--effort\b|--reasoning-effort\b", out)),
    }


def normalize_task(
    vendor: str, task: str, backend: str = "inline", *, review_elsewhere: bool = False
) -> str:
    """Rewrite a leading namespaced saga command into the form this vendor understands.

    The interview writes the task, and it writes ``/saga:plan`` -- claude's form -- for every
    vendor. Codex needs ``$saga:plan`` and grok, qwen and opencode need a bare ``/plan``. A wrong
    prefix does not error: the agent reads it as prose and does something of its own, which is the
    quiet failure this plugin keeps having to fix. So the translation happens here, at the moment of
    sending, rather than depending on the interview to remember.

    Only an explicitly namespaced command is rewritten (``/saga:x`` or ``$saga:x``). A task that
    opens with anything else -- a path, a bare slash command, plain prose -- is left exactly alone,
    because guessing at what is and is not a command is how this goes wrong in the other direction.
    """
    match = re.match(r"^\s*[/$]saga:([a-z][a-z0-9-]*)", task)
    if not match:
        return task
    cap = match.group(1)
    rewritten = saga_command(vendor, cap) + task[match.end() :]
    note = BACKEND_NOTES.get(cap)
    if note and backend not in ("", None):
        rewritten += note.format(backend=backend)
    if cap == "work" and review_elsewhere:
        rewritten += REVIEW_ELSEWHERE_NOTE
    # Last, and for every capability: the specific notes above answer the questions this plugin
    # knows about, and this one covers the rest -- including whatever saga asks next.
    rewritten += UNATTENDED_NOTE
    return rewritten


def saga_command(vendor: str, cap: str) -> str:
    """Render a saga capability the way this vendor actually invokes it.

    ``cap`` is the bare name -- ``plan``, ``doc-review``, ``code-review``. A vendor with no entry
    gets the plain name back, which reads as prose rather than pretending to be a command.
    """
    return SAGA_SYNTAX.get(vendor, "{cap}").format(cap=cap.lstrip("/$").replace("saga:", ""))


def saga_capabilities(vendor: str) -> list[str]:
    """Which saga capabilities are actually installed for this vendor, read off disk."""
    found: set[str] = set()
    for pattern in SAGA_INSTALL.get(vendor, []):
        for directory in glob.glob(str(Path(pattern).expanduser())):
            base = Path(directory)
            found.update(f.stem for f in base.glob("*.md") if f.stem != "README")
            found.update(d.name for d in base.iterdir() if d.is_dir() and (d / "SKILL.md").exists())
    return sorted(found)


def cmd_saga(args: argparse.Namespace) -> int:
    """Show how each vendor invokes a saga capability, and whether it has saga at all."""
    assert_agent_launcher_ingested()
    for name, _ in roster():
        caps = saga_capabilities(name)
        if not caps:
            print(f"{name:12s} NO SAGA INSTALLED — a saga task here does nothing, whatever prefix")
            continue
        has = args.cap in caps
        mark = "" if has else f"  (no `{args.cap}` among its {len(caps)} capabilities)"
        print(f"{name:12s} {saga_command(name, args.cap)}{mark}")
    missing = [n for n, _ in roster() if not saga_capabilities(n)]
    if missing:
        print(f"\nwithout saga: {', '.join(missing)} — give those units plain prose, not a command")
    return 0


def cmd_roster(args: argparse.Namespace) -> int:
    """Print the agents this machine can run, asked now rather than remembered."""
    assert_agent_launcher_ingested()
    rows = roster()
    if not rows:
        print("could not read the wrapper's tool list; check that it runs and prints `Tools:`")
        return 1
    print(f"{'vendor':12s} tier control")
    for name, flags in rows:
        print(f"{name:12s} {flags}")
    print(f"\n{len(rows)} usable here. A vendor showing 'none' still takes a tier — set it with a")
    print("slash command in the unit's `setup`, which is sent before the task.")

    print("\nhow each of these behaves -- read this rather than recalling it:")
    for name, _ in rows:
        caps = saga_capabilities(name)
        modes = VENDOR_PERMISSION.get(name, {})
        print(f"\n  {name}")
        print(f"    permission   auto={' '.join(modes.get('auto', [])) or '(vendor default)'}")
        print(f"                 bypass={' '.join(modes.get('bypass', [])) or '(no escalation)'}")
        if caps:
            print(
                f"    saga         {len(caps)} capabilities, invoked as {saga_command(name, 'plan')}"
            )
        else:
            print("    saga         not installed -- a saga task here arrives as prose")
        note = VENDOR_NOTES.get(name)
        if note:
            for i, line in enumerate(textwrap.wrap(note, 92)):
                label = "note" if i == 0 else ""
                print(f"    {label:12s} {line}")

    missing = [n for n in VENDOR_FLAGS if n not in {x for x, _ in rows}]
    if missing:
        print(f"known but not available on this machine: {', '.join(missing)}")
    unknown = [n for n in launchable() if n not in VENDOR_FLAGS]
    if unknown:
        print(f"launchable but not vendors orchestrate drives: {', '.join(unknown)}")

    if args.models:
        print("\nmodels, asked of each vendor that can answer:")
        for name, _ in rows:
            liked = favourites(name)
            found = models(name)
            if liked:
                print(f"  {name}: {', '.join(liked)}   <- your favourites, offer these first")
            elif not found:
                print(f"  {name}: no favourites and it cannot list its own — ask for the name")
            if found:
                head = "     also available:" if liked else f"  {name}:"
                print(head)
                for m in found[: args.limit]:
                    print(f"    {m}")
                if len(found) > args.limit:
                    print(f"    ... and {len(found) - args.limit} more (`{name} models`)")

    if not args.probe:
        if not args.models:
            print("\n`roster --models` asks each vendor what it has; `--probe` checks flag drift.")
        return 0

    print("\nprobing each tool's help for drift:")
    drift = 0
    for name, _ in rows:
        try:
            out, says = probe(name)
        except SystemExit:
            print(f"  {name:12s} could not run --help; skipped")
            continue
        for what in ("model", "effort"):
            template = VENDOR_FLAGS[name].get(what)
            if template:
                # check the token we actually pass, so a `-c key=value` override is not called a lie
                token = template.split()[0].split("=")[0]
                if token not in out:
                    print(
                        f"  {name:12s} DRIFT: passes {token} for {what}; its help no longer shows it"
                    )
                    drift += 1
            elif says[what]:
                print(f"  {name:12s} DRIFT: advertises a {what} flag orchestrate does not pass")
                drift += 1
    print("  no drift" if not drift else f"\n{drift} mismatch(es) — update VENDOR_FLAGS")
    return 0


def assert_safe_path_component(value: str, label: str) -> None:
    """Refuse a value that is not one safe path component."""
    if not value:
        raise SystemExit(f"{label} must not be empty")
    if Path(value).is_absolute():
        raise SystemExit(f"{label} {value!r} must not be an absolute path")
    if "/" in value or "\\" in value:
        raise SystemExit(f"{label} {value!r} must not contain a path separator")
    if value in (".", ".."):
        raise SystemExit(f"{label} {value!r} is a path traversal")


def assert_safe_unit_names(units: list[Unit]) -> None:
    """Refuse any unit name that is not one safe path component.

    A unit name becomes a worktree directory name, and in Python an absolute right-hand operand
    discards the left when joined, while ``..`` traverses -- unchecked, a name is a directory
    created anywhere on disk. Names are refused here, where they enter a run, so a bad plan fails
    before anything is
    written and before any worktree exists. A name reaches the filesystem as a worktree
    directory name, so the check still earns its place with the task spill gone.
    """
    for unit in units:
        assert_safe_path_component(unit.name, "unit name")


def assert_saga_reachable(units: list[Unit]) -> None:
    """Refuse a saga task aimed at a vendor with no saga installed.

    The prefix is not the only way this goes wrong. agy and muse have no saga install at all, so a
    ``/saga:plan`` sent to either is prose whatever it is prefixed with -- the session reads it,
    does something of its own, and reports itself done. Catch it before a tab opens.
    """
    bad = []
    for unit in units:
        if not re.match(r"^\s*[/$]saga:", unit.task):
            continue
        if not saga_capabilities(unit.vendor):
            bad.append(f"{unit.name} ({unit.vendor})")
    if bad:
        raise SystemExit(
            f"saga is not installed for: {', '.join(bad)}. "
            "Write those tasks as plain prose, or move them to a vendor that has it "
            "(`orchestrate.py saga <cap>`)."
        )


def assert_vendors_available(units: list[Unit]) -> None:
    """Refuse a plan naming an agent the wrapper cannot launch.

    A typo otherwise surfaces as a launch failure per unit, after worktrees exist and tabs have
    opened. Cheaper to fail before anything is created.
    """
    available = {n for n, _ in roster()}
    if not available:
        return  # the wrapper could not be read; do not block on a check that itself failed
    unknown = sorted({u.vendor for u in units if u.vendor not in available})
    if unknown:
        raise SystemExit(
            f"the wrapper cannot launch: {', '.join(unknown)}. "
            f"available: {', '.join(sorted(available))} (`orchestrate.py roster`)"
        )


def assert_dependencies_reachable(incoming: list[Unit], existing: set[str] | None = None) -> None:
    """Reject an ``after`` or ``serialize`` name that is in no run.

    A typo in an ordering edge otherwise produces a unit that is never eligible, forever --
    ``eligible`` waits on a name that does not exist, and ``status`` reports the wait -- and the
    failure is silent at the only moment it could have been caught cheaply. A name may point at a
    sibling in ``incoming`` itself: units routinely depend on the units they were planned with.
    """
    reachable = {u.name for u in incoming} | (existing or set())
    for unit in incoming:
        for dep in unit.after:
            if dep not in reachable:
                raise SystemExit(f"unit {unit.name!r} waits on {dep!r}, which is in no run")
        for dep in unit.serialize:
            if dep not in reachable:
                raise SystemExit(
                    f"unit {unit.name!r} serializes behind {dep!r}, which is in no run"
                )


def cmd_expand(args: argparse.Namespace) -> int:
    """Add units to a run already in flight.

    The up-front table can only name the later phases, never their units: what ``/work`` splits into
    is decided by the plan, which does not exist yet when the operator approves. So a phase that
    produces the next phase's units is read when it finishes, the operator approves the new rows,
    and they are appended to the same run -- not started as a second one. That keeps ``after``
    reaching back to the units they depend on, and keeps one ``collect`` for the whole thing.
    """
    assert_agent_launcher_available()
    r = Run.load(args.issue, args.store_root)
    added = load_plan(args.plan)
    assert_no_engine_prefs(added)
    incoming = plan_units(added)
    assert_safe_unit_names(incoming)

    existing = {u.name for u in r.units}
    seen: set[str] = set()
    for unit in incoming:
        if unit.name in existing or unit.name in seen:
            raise SystemExit(f"unit {unit.name!r} is already in this run; give the new one a name")
        seen.add(unit.name)
    assert_dependencies_reachable(incoming, existing)
    assert_review_transport([*r.units, *incoming])

    assert_vendors_available(incoming)
    assert_saga_reachable(incoming)
    r.units.extend(incoming)
    r.issues.update(added.get("issues", {}))
    r.status_map.update(added.get("status_map", {}))
    expanded_ceiling = review_ceiling_from_plan(added)
    if expanded_ceiling is not None:
        r.review_controller_ceiling = expanded_ceiling
    if "workspace" in added:
        r.workspace = added["workspace"] or None
    if "account" in added:
        r.account = added["account"] or None
    r.save()
    print(f"added {len(incoming)}: {', '.join(u.name for u in incoming)}")
    print("`orchestrate.py go` to launch whatever is now eligible.")
    return 0


def _review_json_object(raw: str | None) -> dict[str, Any] | None:
    """Parse a stored or incoming review artifact when it is a JSON object."""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, TypeError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _review_ingest_refusal(slot: Mapping[str, Any], incoming_raw: str) -> str | None:
    """Named stop for a cycle-regressed or terminal overwrite; None means ingest may proceed."""
    stored_raw = slot.get("review_result")
    if not stored_raw or stored_raw == incoming_raw:
        return None
    stored = _review_json_object(str(stored_raw))
    incoming = _review_json_object(incoming_raw)
    stored_outcome = None
    if stored is not None and isinstance(stored.get("outcome"), str):
        stored_outcome = stored["outcome"]
    elif isinstance(slot.get("review_outcome"), str):
        stored_outcome = slot["review_outcome"]
    if stored_outcome in {"accepted", "cycle_cap_best_available"}:
        return (
            f"refusing to overwrite terminal review outcome {stored_outcome!r} with a "
            "different artifact; byte-identical replay is the only admitted exception"
        )
    if stored is None or incoming is None:
        return None
    stored_history = stored.get("cycle_history")
    incoming_history = incoming.get("cycle_history")
    if (
        isinstance(stored_history, list)
        and isinstance(incoming_history, list)
        and len(incoming_history) < len(stored_history)
    ):
        return (
            f"refusing cycle-regressed review result: incoming cycle_history length "
            f"{len(incoming_history)} is shorter than stored {len(stored_history)}"
        )
    return None


def cmd_review_result(args: argparse.Namespace) -> int:
    """Persist one typed result verbatim, then act only on its routing fields."""
    assert_agent_launcher_available()  # routing resubmits reach PaneWriter: gate before any write
    try:
        raw_result = Path(args.file).read_bytes().decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"cannot read review result {args.file!r}: {exc}") from None

    r = Run.load(args.issue, args.store_root)
    selector = getattr(args, "controller", None)
    controllers = r.review_controllers()
    controller: Unit | None
    if selector is not None:
        controller = r.review_controller_for(selector)
    elif len(controllers) > 1:
        # Refuse rather than guess. Picking one would write this target's typed state into another
        # target's slot, which is precisely the mixing this scoping exists to prevent (#877).
        known = ", ".join(
            unit.name + (f" (lifecycle {unit.lifecycle})" if unit.lifecycle else "")
            for unit in controllers
        )
        raise SystemExit(
            f"this run has {len(controllers)} Code Review controllers ({known}); pass "
            "`--controller` to say which one produced this result"
        )
    else:
        controller = controllers[0] if controllers else None

    slot = r.review_slot(controller)
    if slot["review_result"] == raw_result and slot["review_outcome"] is not None:
        print("review result is already recorded byte-for-byte; nothing dispatched twice")
        return 0
    refusal = _review_ingest_refusal(slot, raw_result)
    if refusal is not None:
        raise SystemExit(refusal)

    # Persist before interpreting even the routing envelope. A bad or unsupported route must not
    # discard the controller's evidence; the operator can inspect the exact string that failed.
    r.write_review_slot(controller, review_result=raw_result, review_outcome=None)
    r.save()
    routing = route_review_result(r, raw_result, controller=controller)
    # ``review_outcome`` is the completion marker used by the byte-identical replay guard. Keep it
    # unset until every live-worker prompt succeeds, while saving the routed fix requests first so
    # cleanup cannot reap their workers across this process boundary.
    r.write_review_slot(controller, review_outcome=None)
    r.save()  # outstanding requests protect workers before any prompt crosses a process boundary

    try:
        dispatched = dispatch_review_routing(routing, slot=r.review_slot(controller))
    except SystemExit as exc:
        r.save()
        print(f"REVIEW FIX DISPATCH FAILED: {exc}")
        return 1
    routed_work = len(dispatched) + len(routing.replacements) + len(routing.assignments)
    if routed_work != routing.work_requests:
        r.save()
        print(
            f"REVIEW FIX ROUTING FAILED: routed {routed_work} of "
            f"{routing.work_requests} Work fix requests; the result remains retryable"
        )
        return 1
    r.write_review_slot(controller, review_outcome=routing.outcome)
    r.save()

    scope = f" for {controller.name}" if controller is not None and controller.lifecycle else ""
    print(f"recorded Code Review routing outcome{scope}: {routing.outcome}")
    for name in dispatched:
        print(f"  dispatched Work repair to live worker {name}")
    for unit in routing.replacements:
        print(f"  created replacement Work worker {unit.name}; `orchestrate.py go` launches it")
    for unit, request in routing.assignments:
        print(f"  kept Work repair {_fix_request_id(request)} on actionable worker {unit.name}")
    for request in routing.operator_requests:
        print(
            f"  OPERATOR ACTION: {request['owner']} owns fix {_fix_request_id(request)} "
            f"for {', '.join(request['touched_paths'])}; it was not dispatched as Work"
        )
    return 0


def launch_room(r: Run) -> tuple[int, int, int]:
    """How many more sessions this run may start: ``(room, live units, open role panes)``.

    The width number is the record's ``concurrency_allocation``, and it is ONE budget. A role
    session is an agent session like any other and the number exists for the account's rate
    limit, so counting units alone would let six role panes and ten units put sixteen sessions on
    one account against a cap of ten. ``roster.py`` already refuses to exceed the same number on
    its side; this is the other half of that agreement.
    """
    width = r.parameter("concurrency_allocation")
    live_units = sum(1 for unit in r.units if unit.status == RUNNING)
    open_roles = r.open_roster_rows()
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        return (len(r.units), live_units, open_roles)
    return (max(width - live_units - open_roles, 0), live_units, open_roles)


def record_launch_identity(unit: Unit, r: Run) -> None:
    """Persist the wrapper identity the moment the session exists (issue 990).

    Handed to the launcher as its post-create callback. Before this, ``tab_id``, ``pane_id`` and
    ``agent_name`` were written onto the in-memory unit and nothing persisted them until a second
    save after delivery returned -- a window of up to two minutes plus settle plus the delivery
    check, in which an interrupt left the record claiming the unit was never launched while a real
    tab existed, and the next ``go`` made a second session.
    """
    receipt = unit.launch_receipt if isinstance(unit.launch_receipt, dict) else {}
    if "owned" in receipt:
        unit.owned = receipt["owned"] is True
    with contextlib.suppress(RecordError):
        r.save()


def cmd_go(args: argparse.Namespace) -> int:
    assert_agent_launcher_available()
    r = Run.load(args.issue, args.store_root)
    if r.unresolvable_branch:
        raise SystemExit(f"run branch {r.unresolvable_branch!r} does not resolve; cannot go")
    assert_review_transport(r.units)
    ready = r.eligible()
    if not ready:
        print("nothing eligible -- either everything is running or dependencies are unmet.")
        return 0
    room, live_units, open_roles = launch_room(r)
    if room <= 0:
        print(
            f"at the run's width already: {live_units} unit(s) running and {open_roles} open role "
            f"pane(s) against a concurrency allocation of {r.parameter('concurrency_allocation')}"
        )
        return 0
    slice_size = min(room, args.limit) if args.limit else room
    root = repo_root()
    for unit in ready[:slice_size]:
        if unit.tab_id:
            print(f"  {unit.name}: already has tab {unit.tab_id}; not launching twice")
            continue
        empty = [d for d in unit.after if not produced_anything(r.unit(d), r)]
        if empty:
            print(f"  {unit.name}: skipped — {', '.join(empty)} committed nothing to build on")
            continue
        setup_failure = make_worktree(unit, r, root)
        if setup_failure is not None:
            unit.status = PENDING
            append_unit_note(unit, setup_failure)
            print(f"  {unit.name} NOT LAUNCHED: {setup_failure}")
            r.save()
            continue
        if not unit.workspace and r.workspace:
            unit.workspace = r.workspace
        if not unit.account and r.account:
            unit.account = r.account
        # THE IMMEDIATE PERSIST (issue #1025, cards 900 and 990). The row goes to `running` and
        # is written BEFORE the launcher is called, so a second `go` in the launch window finds
        # the unit already running and eligibility does not return it. No claim, no owner token,
        # no expiry -- see DECISIONS {#1025-immediate-persist-not-a-reservation}.
        unit.status = RUNNING
        unit.launch_started_at = datetime.now(UTC).isoformat()
        r.save()
        print(f"launching {unit.name} ({unit.vendor}) -> {unit.task}")
        try:
            launch(unit, r.backend, review_elsewhere=r.reviews_separately())
        except StagedInputError as exc:
            # The stop returns the unit to PENDING and says why; it does NOT retry through the
            # recorded pane. The automatic redelivery route that DECISIONS
            # {#907-staged-input-redeliver} described went with the persisted launch receipt this
            # card removed -- see DECISIONS {#1025-staged-stop-does-not-auto-redeliver}, which
            # supersedes it in part. `launcher.py redeliver` is still the right repair; an
            # operator runs it, and orchestrate says so below rather than guessing.
            unit.status = PENDING
            # Append, never overwrite: the guard's withheld line and an earlier stop message
            # are facts a repeated stop must not erase. The membership test is a substring,
            # not a split on the separator: the stop message itself contains the separator.
            if str(exc) not in unit.note:
                append_unit_note(unit, str(exc))
            print(f"  {unit.name} PENDING: {exc}")
            print(
                f"  the composer for {unit.name} holds staged input: clear it and redeliver by "
                "hand with `launcher.py redeliver`, never a second launch"
            )
        except AccountMismatchError as exc:
            unit.status = ACCOUNT_MISMATCH
            # APPEND, never replace (issue 944). Replacing the note erased the launcher's own
            # close-failure record, so the fix agent-launcher 1.1.0 made observable never reached
            # an operator working through orchestrate.
            append_unit_note(unit, str(exc))
            print(f"  {unit.name} FAILED: {exc}")
        except SystemExit as exc:
            unit.status = FAILED
            append_unit_note(unit, str(exc))
            print(f"  {unit.name} FAILED: {exc}")
        except BaseException:
            # A keyboard interrupt is a BaseException and neither clause above catches it. The
            # identity the launcher already wrote onto the unit is persisted here before the
            # interrupt continues, so an interrupted launch is never relaunched blind (issue 990).
            r.save()
            raise
        finally:
            record_launch_identity(unit, r)
    return 0


def unit_commit_statuses(units: Sequence[Unit], r: Run) -> list[tuple[str, str]]:
    """Return every unit's commit count and landed state from one landing-history walk.

    Once a unit is merged, its branch tip is also in the run branch and their ordinary merge base
    is the unit tip. Counting from that point would report zero for work that plainly exists, so
    the landing merge's first parent recovers the branch point used for the honest count. Resolving
    the branch tips first lets one first-parent walk classify every unit instead of repeating the
    same run-branch history query once per row.
    """
    if r.unresolvable_branch:
        return [("?", "unknown") if unit.branch else ("-", "-") for unit in units]

    comparison = r.resolved_run_ref()
    branch_tips: dict[str, str | None] = {}
    for unit in units:
        if unit.branch and unit.branch not in branch_tips:
            branch_tips[unit.branch] = resolve_ref(unit.branch)
    resolved_tips = {branch: tip for branch, tip in branch_tips.items() if tip is not None}
    merged_by_branch = landing_merges(resolved_tips, comparison)

    statuses: list[tuple[str, str]] = []
    for unit in units:
        if not unit.branch:
            statuses.append(("-", "-"))
            continue
        tip = branch_tips[unit.branch]
        if tip is None:
            statuses.append(("?", "missing"))
            continue
        merged = merged_by_branch.get(unit.branch)
        base = merge_base(f"{merged}^1", tip) if merged else merge_base(comparison, tip)
        if base is None:
            statuses.append(("?", "yes" if merged else "unknown"))
            continue
        count = run(["git", "rev-list", "--count", f"{base}..{tip}"], check=False)
        if count.returncode != 0 or not count.stdout.strip():
            statuses.append(("?", "yes" if merged else "unknown"))
            continue
        statuses.append((count.stdout.strip(), "yes" if merged else "no"))
    return statuses


def one_line(text: str) -> str:
    """Collapse arbitrary task and note whitespace so one unit always occupies one table row."""
    return " ".join(text.split())


def status_cell(text: str) -> str:
    """Collapse and visibly bound a prose status cell."""
    collapsed = one_line(text)
    if len(collapsed) <= STATUS_TEXT_WIDTH:
        return collapsed
    return f"{collapsed[: STATUS_TEXT_WIDTH - 1]}…"


def cmd_status(args: argparse.Namespace) -> int:
    r = Run.load(args.issue, args.store_root)
    if _AGENT_LAUNCHER_AVAILABLE:
        live = {u.name: poll(u) for u in r.units if u.status == RUNNING}
    else:
        # The companion was not ingested, so Herdr cannot be asked: print the fault once and
        # read liveness as unknown -- absence must not read as gone (the API-04 trade).
        _print_companion_fault_once()
        live = {u.name: "unknown" for u in r.units if u.status == RUNNING}
    print(f"run {r.run_id}   base {r.base[:8]}   {r.source}\n")
    if r.unresolvable_branch:
        print(f"WARNING: run branch {r.unresolvable_branch!r} does not resolve\n")
    headers = (
        "unit",
        "vendor",
        "model",
        "effort",
        "state",
        "herdr",
        "commits",
        "landed",
        "task",
        "note",
    )
    rows: list[tuple[str, ...]] = []
    commit_statuses = unit_commit_statuses(r.units, r)
    for unit, (commits, is_landed) in zip(r.units, commit_statuses, strict=True):
        tail = one_line(unit.task)[:STATUS_TEXT_WIDTH]
        if unit.status == PENDING:
            why = r.wait_reason(unit)
            if why:
                # The wait is the interesting thing about a blocked unit -- its task is in the
                # plan. Naming the kind of edge is the fix for a run that looked blocked for a
                # reason that does not exist.
                tail = f"[{why}]"
        rows.append(
            (
                unit.name,
                unit.vendor,
                unit.model or "-",
                unit.effort or "-",
                unit.status,
                live.get(unit.name, "-"),
                commits,
                is_landed,
                tail,
                status_cell(unit.note),
            )
        )
    widths = [
        max([len(headers[index]), *(len(row[index]) for row in rows)])
        for index in range(len(headers))
    ]

    def format_row(values: Sequence[str]) -> str:
        return " ".join(value.ljust(widths[index]) for index, value in enumerate(values)).rstrip()

    head = format_row(headers)
    print(head)
    print("-" * (sum(widths) + len(widths) - 1))
    for row in rows:
        print(format_row(row))
    for name, branch in discover_unrecorded(r):
        print(f"UNRECORDED {name} -- branch {branch} is not a unit in this run")
    # Read every controller's own slot. Consulting only the run-level fields would show a scoped
    # run as having no Code Review result at all, which is exactly when the operator needs one (#877).
    scoped_controllers = [unit for unit in r.review_controllers() if unit.lifecycle]
    # Carry the Unit itself. Matching a label back to its controller by name prefix attributes one
    # controller's Work to another whenever one name prefixes the other (#877).
    slots: list[tuple[Unit | None, str, dict[str, Any]]] = [
        (unit, f"{unit.name} (lifecycle {unit.lifecycle})", r.review_slot(unit))
        for unit in scoped_controllers
    ]
    if not slots:
        only = r.review_controllers()[0] if r.review_controllers() else None
        slots = [(only, "", r.review_slot(only))]

    operator_requests: list[dict[str, Any]] = []
    for owner, label, slot in slots:
        operator_requests.extend(slot["operator_fix_requests"])
        scope = f" [{label}]" if label else ""
        if not slot["review_outcome"]:
            if slot.get("review_result"):
                print(f"\nCode Review result{scope}: recorded-but-unrouted")
            continue
        outstanding_work = any(unit.fix_requests for unit in _lifecycle_units(r, owner))
        pending = slot["review_resubmit_pending"]
        operator_held = bool(slot["operator_fix_requests"])
        if pending and outstanding_work and operator_held:
            state = "awaiting landed Work repairs and operator-owned fix requests"
        elif pending and outstanding_work:
            state = "awaiting landed Work repairs"
        elif pending and operator_held:
            state = "resubmission held by operator-owned fix requests"
        elif pending:
            state = "awaiting Code Review resubmission"
        elif operator_held:
            state = "operator-owned fix requests outstanding"
        else:
            state = "recorded"
        typed_outcome = str(slot["review_outcome"])
        print(f"\nCode Review result{scope}: {one_line(typed_outcome)} ({state})")
        if owner is not None and owner.note:
            for token in sorted(REVIEW_OUTCOMES, key=len, reverse=True):
                if re.search(rf"\b{re.escape(token)}\b", owner.note, flags=re.IGNORECASE):
                    if token != typed_outcome:
                        print(
                            f"note contradicts typed outcome: note has {token}, "
                            f"slot has {typed_outcome}"
                        )
                    break

    for request in operator_requests:
        request_owner = one_line(str(request.get("owner", "?")))
        fix_id = one_line(str(request.get("fix_id", "?")))
        touched_paths = one_line(", ".join(str(path) for path in request.get("touched_paths", [])))
        print(f"OPERATOR ACTION: {request_owner} owns fix {fix_id} for {touched_paths}")
    return 0


def settle_reading(units: list[Unit]) -> dict[str, str]:
    """One poll of every unit, against one herdr round trip in total.

    ``live_agents`` is fetched once and passed to ``poll`` -- polling each unit separately costs one
    round trip a row, and an unresponsive herdr costs its timeout once a row instead of once.
    """
    agents = live_agents()
    return {unit.name: poll(unit, agents) for unit in units}


def cmd_settle(args: argparse.Namespace) -> int:
    """Mark running units done when their session has completed and produced evidence.

    Idle is read twice, ``interval`` seconds apart, and only counts when both readings agree: an
    agent is also idle *between* turns -- it finishes a tool call, returns to the prompt, thinks,
    and continues. One instantaneous sample once marked a unit done in that gap; it had two commits
    at the time and finished with ten. ``--once`` restores the single sample for a caller that
    wants it.

    Settlement mirrors the evidence model in ``cmd_check``, gating completion on the existing
    ``produced_anything`` helper:
    - A session that is idle or done settles ``done`` only when its branch has commits. An idle
      session without commits stays ``running``.
    - A session that is gone settles ``done`` if its branch has commits (e.g. session closed after
      finishing work), or ``orphaned`` if it disappeared without committing anything.

    The gate is a *branch* reading, so it is applied only where a branch can be read. A unit with
    no branch of its own -- the review controller, which carries ``merge: False`` and delivers its
    result through ``review-result`` -- is not commit-gated and settles on the confirmed reading
    alone; gating it would leave the review loop unable to finish, because it has no branch on
    which a commit could ever appear. An unresolvable run branch makes the count unknown rather
    than zero: such a unit stays ``running`` and is told so, and a gone session is recorded
    ``orphaned`` with a note that says the commits could not be checked rather than one asserting
    there were none.
    """
    r = Run.load(args.issue, args.store_root)
    running = [u for u in r.units if u.status == RUNNING]
    first = settle_reading(running) if running else {}
    second = first
    if running and not args.once:
        time.sleep(args.interval)
        second = settle_reading(running)
    for unit in running:
        # The gate reads branch truth, so it applies only where there is a branch to read and a
        # resolvable run branch to count from. A unit with no branch of its own was never
        # commit-gated -- the review controller is that shape, declared `merge: False` with its
        # output delivered through `review-result` -- and an unresolvable run branch makes the
        # count unknown rather than zero. `reapable` refuses a branchless unit and `adopt` warns
        # that an unresolvable branch makes commit checks unavailable; neither reads as evidence
        # of nothing, and settling on either would put the record back to guessing.
        commit_gated = bool(unit.branch)
        countable = commit_gated and r.unresolvable_branch is None
        has_evidence = countable and produced_anything(unit, r)
        if has_delivery_warning(unit) and has_evidence:
            clear_delivery_warning(unit)
        a, b = first[unit.name], second[unit.name]
        if a in {"idle", "done"} and b in {"idle", "done"}:
            shown = a if args.once else f"{a} then {b}"
            if has_evidence:
                unit.status = DONE
                print(f"  {unit.name}: {shown} -> done")
            elif not commit_gated:
                unit.status = DONE
                print(f"  {unit.name}: {shown} -> done (no branch of its own to check)")
            elif not countable:
                print(f"  {unit.name}: {shown} -> unsettled (run branch does not resolve)")
            else:
                print(f"  {unit.name}: {shown} -> still moving (no commits)")
        elif a == "gone" and b == "gone":
            if has_evidence:
                unit.status = DONE
                print(f"  {unit.name}: session gone with commits -> done")
            else:
                unit.status = ORPHANED
                append_unit_note(
                    unit,
                    "session disappeared without commits"
                    if countable
                    else "session disappeared; commits could not be checked",
                )
                print(f"  {unit.name}: session gone -> orphaned")
        elif a in {"idle", "done"}:
            print(f"  {unit.name}: {a} then {b} -> still moving")
    r.save()
    return 0


SETTLED_STATES = frozenset({"idle", "done"})


def confirmation_count(value: str) -> int:
    """Parse a wait confirmation count, rejecting the single-observation defect."""
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("confirmations must be an integer") from exc
    if count < 2:
        raise argparse.ArgumentTypeError("confirmations must be at least 2")
    return count


def confirmed_stop(
    first: str,
    further: Callable[[], str],
    *,
    interval: int,
    needed: int,
    sleep: Callable[[float], None] = time.sleep,
    deadline: float | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> str | None:
    """Return the status if consecutive observations agree the unit has stopped, else None.

    ``blocked`` is a real stop and returns on the first sighting. ``idle`` and ``done`` need
    ``needed`` agreeing samples ``interval`` seconds apart -- an agent is also idle between
    turns, and one sample once returned ``wait`` in that gap. Any other status is not a stop.
    """
    if needed < 2:
        raise ValueError("wait requires at least two confirming observations")
    if first == "blocked":
        return "blocked"
    if first not in SETTLED_STATES:
        return None
    last = first
    for _ in range(needed - 1):
        if deadline is not None:
            remaining = deadline - monotonic()
            if remaining <= interval:
                if remaining > 0:
                    sleep(remaining)
                return None
        sleep(interval)
        last = further()
        if last == "blocked":
            return "blocked"
        if last not in SETTLED_STATES:
            return None
    return last


def report_wait(unit: Unit, status: str) -> None:
    if status == "blocked":
        print(f"{unit.name} is blocked -- it is asking a question in its own tab")
        return
    print(f"{unit.name} is {status} -- `settle`, `merge`, then `go`")


def record_settlement(unit: Unit, status: str) -> None:
    """Write one observed settlement onto the unit's row (issue 891).

    The wait used to return on the FIRST unit to settle and record nothing, so an unattended run
    over several units had no durable answer to "which of them finished". Every settlement this
    wait observes is written, and a blocked session is recorded as blocked rather than answered.
    """
    append_unit_note(unit, f"settled {status}")


def wait_on_events(
    by_pane: dict[str, Unit],
    events: Iterator[Any],
    *,
    interval: int,
    needed: int,
    poll_unit: Callable[[Unit], str],
    sleep: Callable[[float], None] = time.sleep,
    settled: list[tuple[Unit, str]] | None = None,
) -> tuple[Unit, str] | None:
    """Drive the event-socket path: a wake is one observation, not a settlement.

    The stream is edge-triggered, so a single ``idle`` is the think-pause this function exists
    to ignore. Confirmation is level-triggered, through ``poll_unit``, matching ``settle``.

    Every confirmed settlement is appended to *settled* before the first one returns, so a
    multi-unit wait has a record of all of them rather than only of the one it returned.
    """
    for event in events:
        unit = by_pane.get(event.pane_id)
        if unit is None:
            continue

        status = confirmed_stop(
            event.agent_status,
            functools.partial(poll_unit, unit),
            interval=interval,
            needed=needed,
            sleep=sleep,
        )
        if status is not None and settled is not None:
            settled.append((unit, status))
        if status is not None:
            return unit, status
    return None


def wait_on_agent_waits(
    running: list[Unit],
    *,
    timeout: int,
    interval: int,
    needed: int,
) -> tuple[Unit, str] | None:
    """Drive the ``herdr agent wait`` fallback with the same confirmation rule as the socket.

    A successful wait-process exit is a wake, not a settlement: the first observation is a poll,
    then further polls ``interval`` apart until they agree -- or the unit is still moving and its
    wait is restarted. A failed child is not a wake and is not restarted. Every child and poll gets
    only the time left before one shared monotonic deadline.
    """
    deadline = time.monotonic() + max(timeout, 0)
    procs: dict[int, tuple[Unit, subprocess.Popen[bytes]]] = {}

    def remaining() -> float:
        return max(deadline - time.monotonic(), 0.0)

    def start_unit(unit: Unit) -> bool:
        budget = remaining()
        if budget <= 0:
            return False
        proc = _popen_herdr_wait(unit, budget)
        procs[proc.pid] = (unit, proc)
        return True

    def stop_children() -> None:
        children = [proc for _, proc in procs.values()]
        for proc in children:
            if proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
        for proc in children:
            with contextlib.suppress(ChildProcessError):
                proc.wait()

    try:
        for unit in running:
            start_unit(unit)
        while procs:
            budget = remaining()
            if budget <= 0:
                return None
            finished = next(
                (
                    (pid, unit, proc, returncode)
                    for pid, (unit, proc) in procs.items()
                    if (returncode := proc.poll()) is not None
                ),
                None,
            )
            if finished is None:
                time.sleep(min(0.01, budget))
                continue
            pid, unit, _proc, returncode = finished
            procs.pop(pid)
            if returncode != 0:
                continue

            budget = remaining()
            if budget <= 0:
                return None

            def poll_before_deadline(current_unit: Unit = unit) -> str:
                budget = remaining()
                if budget <= 0:
                    return "timeout"
                return poll(current_unit, timeout=budget)

            status = confirmed_stop(
                poll_before_deadline(),
                poll_before_deadline,
                interval=interval,
                needed=needed,
                deadline=deadline,
            )
            if status is not None:
                return unit, status
            start_unit(unit)
    finally:
        stop_children()
    return None


def _popen_herdr_wait(unit: Unit, timeout: float) -> subprocess.Popen[bytes]:
    handle = unit.agent_name or unit.name
    return subprocess.Popen(
        [
            "herdr",
            "agent",
            "wait",
            handle,
            "--until",
            "idle",
            "--until",
            "done",
            "--until",
            "blocked",
            "--timeout",
            str(max(1, int(timeout * 1000))),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def cmd_wait(args: argparse.Namespace) -> int:
    """Block until a running unit settles, told by herdr rather than asking it.

    Subscribes to ``pane.agent_status_changed`` on each running unit's pane over herdr's event
    socket and blocks in the kernel until a line arrives. Subscriptions are keyed by pane, which is
    why a unit records its ``pane_id`` at launch -- a request without one is rejected outright.

    An agent goes idle between turns -- it finishes a tool call, returns to the prompt, thinks,
    and continues -- so a single ``idle`` is not a settlement. Idle is read ``confirmations``
    times, ``interval`` seconds apart, and only counts when consecutive readings agree, the same
    shape as ``settle``. At least two observations are mandatory. ``blocked`` is a real stop and
    returns on the first sighting, naming that state.

    Falls back to ``herdr agent wait`` when the socket is unreachable: an older herdr, a stopped
    server, or a unit launched before pane ids were recorded. That path obeys the same
    confirmation rule; a degraded path that still fired on one sample would leave the defect in
    place on exactly the machines that hit the fallback.
    """
    r = Run.load(args.issue, args.store_root)
    running = [u for u in r.units if u.status == RUNNING]
    if not running:
        print("nothing running -- `go` to launch what is eligible")
        return 0

    needed = args.confirmations
    by_pane = {u.pane_id: u for u in running if u.pane_id}
    print(f"waiting on {', '.join(u.name for u in running)} (up to {args.timeout}s)")
    observed: list[tuple[Unit, str]] = []

    if by_pane and herdr_events is not None:
        try:
            settled = wait_on_events(
                by_pane,
                herdr_events.agent_status_events(list(by_pane), timeout=float(args.timeout)),
                interval=args.interval,
                needed=needed,
                poll_unit=poll,
                settled=observed,
            )
            for unit, status in observed:
                record_settlement(unit, status)
            r.save()
            if settled is None:
                print("no unit changed state before the timeout")
                return 0
            report_wait(*settled)
            return 0
        except herdr_events.HerdrEventError as exc:
            print(f"event socket unavailable ({exc}); falling back to per-unit waits")

    settled = wait_on_agent_waits(
        running,
        timeout=args.timeout,
        interval=args.interval,
        needed=needed,
    )
    if settled is not None:
        record_settlement(*settled)
    r.save()
    if settled is None:
        print("no unit settled before the timeout")
        return 0
    report_wait(*settled)
    return 0


def registered_worktree_paths() -> list[Path]:
    """Return every path Git records, including missing prunable worktrees."""
    listed = run(["git", "worktree", "list", "--porcelain", "-z"], check=False)
    if listed.returncode != 0:
        detail = (listed.stderr or listed.stdout or "unknown git error").strip()
        raise SystemExit(f"cannot inspect registered worktrees before land: {detail}")
    return [
        Path(field.removeprefix("worktree ")).resolve()
        for field in listed.stdout.split("\0")
        if field.startswith("worktree ")
    ]


def worktree_registration_exists(path: Path) -> bool:
    """Whether Git still records ``path``, including a missing prunable worktree."""
    wanted = path.resolve()
    return wanted in registered_worktree_paths()


def live_linked_worktree_at(path: Path, *, operator_worktree: Path) -> bool:
    """Whether ``path`` is an exact, separate linked worktree safe for housekeeping.

    This proof deliberately does not invoke ``git -C path``. An untrusted path may be a plain
    directory inside the operator's checkout, a symlink, or a worktree whose gitfile was rewritten
    to the primary gitdir. Read the registration and linked-worktree metadata from the repository
    side instead; only callers holding a true result may issue path-scoped Git commands.
    """
    lexical = Path(os.path.abspath(path))
    try:
        wanted = path.resolve(strict=True)
    except OSError:
        return False
    if lexical != wanted:
        return False

    registered = registered_worktree_paths()
    # Git lists its primary worktree first. The operator can also invoke Orchestrate from another
    # linked worktree, so both checkouts are distinct exclusions from a housekeeping candidate.
    if (
        not registered
        or wanted == registered[0]
        or wanted == operator_worktree.resolve()
        or wanted not in registered
    ):
        return False

    gitfile = wanted / ".git"
    if gitfile.is_symlink() or not gitfile.is_file():
        return False
    try:
        marker, separator, raw_gitdir = gitfile.read_text().strip().partition(":")
    except OSError:
        return False
    if marker != "gitdir" or not separator or not raw_gitdir.strip():
        return False
    admin = Path(raw_gitdir.strip())
    if not admin.is_absolute():
        admin = gitfile.parent / admin
    try:
        admin = admin.resolve(strict=True)
    except OSError:
        return False

    common_result = run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], check=False
    )
    reported_common = common_result.stdout.strip()
    if common_result.returncode != 0 or not reported_common:
        return False
    common = Path(reported_common).resolve()
    try:
        relative_admin = admin.relative_to(common / "worktrees")
    except ValueError:
        return False
    if len(relative_admin.parts) != 1:
        return False

    try:
        back_pointer = Path((admin / "gitdir").read_text().strip())
    except OSError:
        return False
    if not back_pointer.is_absolute():
        back_pointer = admin / back_pointer
    return back_pointer.resolve() == gitfile.resolve()


def stale_merge_turn(r: Run, unit: Unit, root: Path) -> bool:
    """Is this unit's recorded ``merging`` state left over from a turn that never finished?

    A merge turn is ordinary execution state, not a lock: there is no owner token and no expiry.
    That means a row left at ``merging`` by a process that died would block every later turn
    forever unless the state is checked against reality -- which is card 992's failure shape, a
    failed attempt demoting a unit out of the one state its own door can act on, reappearing in a
    new place. So the refusal is DERIVED, never trusted: a turn is live only while its own
    worktree is still registered and still holds an unfinished merge.
    """
    path = unit.merge_worktree or ""
    if not path:
        return True
    candidate = Path(path)
    if not os.path.lexists(candidate) or not worktree_registration_exists(candidate):
        return True
    if not live_linked_worktree_at(candidate, operator_worktree=root):
        return True
    head = run(
        ["git", "-C", str(candidate), "rev-parse", "--verify", "--quiet", "MERGE_HEAD"], check=False
    )
    return head.returncode != 0


def merge_turn_holder(r: Run, root: Path) -> Unit | None:
    """The unit whose merge turn is genuinely in flight, or ``None`` -- clearing stale rows.

    Every row this finds stale is reset to ``ready`` with a line saying its turn did not finish.
    That is the "inspect the actual Git and worker state first" step the lifecycle repository's
    own merge-turn flowchart prescribes for an attempt whose outcome is unknown.
    """
    holder: Unit | None = None
    for unit in r.units:
        if unit.merge_state != MERGE_MERGING:
            continue
        if stale_merge_turn(r, unit, root):
            unit.merge_state = MERGE_READY
            unit.merge_worktree = None
            print(
                f"  {unit.name}: its previous merge turn did not finish and no merge is in "
                "flight; the turn is released"
            )
            continue
        holder = unit
    return holder


def fetch_default_branch(remote: str, branch: str) -> str | None:
    """Refresh ``<remote>/<branch>``; return a refusal reason, or ``None`` when it is current.

    A regression guard that reads an out-of-date remote-tracking ref passes silently, which is
    the quiet failure card 875 reported one level up. So the turn refuses rather than comparing
    against whatever the operator last pulled.
    """
    fetched = run(["git", "fetch", remote, branch], check=False, timeout=180)
    if fetched.returncode != 0:
        detail = (fetched.stderr or fetched.stdout or "unknown error").strip().splitlines()
        return (
            f"`git fetch {remote} {branch}` failed"
            + (f": {detail[-1]}" if detail else "")
            + f"; the guard against reverting a newer {branch} cannot be evaluated against a "
            "current ref, so this merge turn is refused"
        )
    return None


def main_regression_files(merged_tip: str, compare_ref: str) -> list[str]:
    """Files this merge would take BACKWARDS relative to *compare_ref* (card 875).

    Empty means the merge reverts nothing. The reading is deliberately narrow: only a file the
    comparison ref has changed since the two diverged, AND that this merge result also touches,
    can be reverted by publishing this merge. Refusing every merge whose branch is merely behind
    the comparison ref would make ordinary parallel work unmergeable.
    """
    ancestor = run(["git", "merge-base", "--is-ancestor", compare_ref, merged_tip], check=False)
    if ancestor.returncode == 0:
        return []
    base = merge_base(compare_ref, merged_tip)
    if base is None:
        return []
    theirs = run(["git", "diff", "--name-only", f"{base}..{compare_ref}"], check=False)
    ours = run(["git", "diff", "--name-only", f"{base}..{merged_tip}"], check=False)
    if theirs.returncode != 0 or ours.returncode != 0:
        return []
    theirs_files = {line.strip() for line in theirs.stdout.splitlines() if line.strip()}
    ours_files = {line.strip() for line in ours.stdout.splitlines() if line.strip()}
    return sorted(theirs_files & ours_files)


def release_unit_worktree(unit: Unit, root: Path) -> tuple[bool, str]:
    """Remove a merged unit's worktree so its branch becomes deletable (issue 876).

    GitHub cannot delete a branch a local worktree still holds, and `gh pr merge --delete-branch`
    failed for exactly this reason on pull requests 867, 869 and 872 during one campaign. The
    moment the branch becomes deletable is the merge turn, so the release happens here rather
    than only at the end of the run.

    Refuses on dirty or unpushed state, naming what is at risk: the worktree is the last copy of
    anything not committed, and the branch is the last copy of anything not pushed.

    **It also refuses while the unit still records a tab.** A recorded tab is a session this run
    has not closed, and a session's working directory is this worktree -- pulling the floor out
    from under a live session is worse than a branch that stays undeletable for one more step.
    `clean` closes the tab first and then removes the worktree, which is the order that already
    worked; this is the same order, brought forward to the merge turn only where it is safe. The
    reading is the record's rather than herdr's on purpose: it is deterministic, it needs no
    round trip in the middle of a merge, and a machine that cannot answer about its sessions must
    not silently become a machine that removes them.
    """
    path = Path(unit.worktree) if unit.worktree else None
    if path is None or not os.path.lexists(path):
        return True, "no worktree to release"
    if unit.tab_id:
        return False, (
            f"the worktree at {path} still hosts tab {unit.tab_id}; `clean` closes the tab and "
            "then removes it"
        )
    if not live_linked_worktree_at(path, operator_worktree=root):
        return False, f"{path} is not a proven separate linked worktree; it was left untouched"
    status = run(["git", "-C", str(path), "status", "--porcelain"], check=False)
    if status.returncode != 0:
        detail = (status.stderr or status.stdout or "unknown error").strip()
        return False, f"git could not inspect {path}: {detail}"
    dirty = [line.strip() for line in status.stdout.splitlines() if line.strip()]
    if dirty:
        shown = ", ".join(dirty[:5]) + (" ..." if len(dirty) > 5 else "")
        return False, f"the worktree at {path} has uncommitted changes and would lose them: {shown}"
    if unit.branch:
        unpushed = run(
            ["git", "rev-list", "--count", f"origin/{unit.branch}..{unit.branch}"], check=False
        )
        count = unpushed.stdout.strip() if unpushed.returncode == 0 else ""
        if count and count not in ("", "0"):
            return False, (
                f"{unit.branch} has {count} commit(s) not on origin, and removing the worktree "
                "makes the branch deletable; push first"
            )
    removed = run(["git", "worktree", "remove", "--force", str(path)], check=False)
    if removed.returncode != 0 and os.path.lexists(path):
        detail = (removed.stderr or removed.stdout or "unknown error").strip()
        return False, f"removing {path} failed ({removed.returncode}): {detail}"
    unit.worktree = None
    return True, f"released the worktree at {path}"


def cmd_merge(args: argparse.Namespace) -> int:
    """Take one merge turn per ready unit, merging its branch onto the run's parent branch.

    This replaces `land` (issue #1025). What is gone with the name is the machinery around the
    merge, not the merge: the retained conflict pointer that outlived an invocation, the numbered
    landing-path fallback and its preserved-path bookkeeping, and the retained-merge recovery that
    inspected an earlier run's worktree and decided whether to publish it. What remains is one
    detached worktree per turn, created and removed inside the turn.

    Merges are serialised: exactly one unit holds the turn at a time, tracked in the record as
    ordinary state. A conflicting merge aborts in the turn's own worktree, leaves the unit at
    ``ready`` with the conflict named, and leaves the parent branch untouched -- the merging
    worker re-merges on its next turn, which is whose job the lifecycle repository says it is.

    Exit status: 0 everything merged; 1 the merge itself could not finish; 3 every merge landed but
    cleanup left something behind, named above; 4 repairs landed but could not be resubmitted.
    Exit 2 is retired with the board writeback this command used to make (issue 1028).
    """
    assert_agent_launcher_available()  # reaching PaneWriter and close_run_session: gate first
    r = Run.load(args.issue, args.store_root)
    if not r.branch:
        raise SystemExit("this run has no parent branch; `start` creates one")
    branch_tip = r.resolved_branch
    if branch_tip is None:
        raise SystemExit(f"parent branch {r.branch!r} does not resolve; cannot merge")

    root = repo_root()
    branch_ref = r.branch if r.branch.startswith("refs/") else f"refs/heads/{r.branch}"
    landed: list[str] = []
    empty: list[str] = []
    already: list[str] = []
    held: list[str] = []
    landed_names: list[str] = []
    landed_tips: dict[str, str] = {}
    completed_fix_ids: list[str] = []
    cleanup_failures: list[tuple[Path, str]] = []
    refusals: list[str] = []

    held_at = worktree_on_branch(r.branch)
    if held_at:
        print(
            f"WARNING: {r.branch} is checked out at {held_at}; advancing the ref leaves files "
            "brought in by a merge staged for deletion in that checkout. Do not commit that "
            f"index; run `git -C {held_at} reset` first, then reconcile it with the new tip."
        )

    holder = merge_turn_holder(r, root)
    r.save()
    if holder is not None:
        print(
            f"  {holder.name} holds the merge turn and its merge is still in flight at "
            f"{holder.merge_worktree}; one worker merges at a time"
        )
        return 1

    fetch_refusal = fetch_default_branch(args.remote, args.compare)
    compare_ref = f"{args.remote}/{args.compare}"
    if fetch_refusal is not None:
        print(f"  MERGE TURN REFUSED: {fetch_refusal}")
        return 1

    try:
        for unit in r.units:
            if unit.status != DONE or not unit.branch:
                continue
            if not unit.merge:
                held.append(unit.name)
                continue
            blocker = next(
                (
                    row
                    for row in unit.shared_blockers
                    if str(row.get("owner_unit") or "") not in ("", unit.name)
                ),
                None,
            )
            if blocker is not None:
                refusals.append(
                    f"{unit.name}: blocker {blocker.get('blocker_id', '?')!r} is owned by "
                    f"{blocker.get('owner_unit')}, so this unit does not repair it"
                )
                continue
            ahead = run(
                ["git", "rev-list", "--count", f"{branch_tip}..{unit.branch}"], check=False
            ).stdout.strip()
            if ahead in ("", "0"):
                if unit.name not in landed_names:
                    (already if produced_anything(unit, r) else empty).append(unit.name)
                continue

            turn_worktree = fresh_unit_worktree_path(
                root / WORKTREE_STATE_DIR / f"merge-{r.run_id}"
            )
            added = run(
                ["git", "worktree", "add", "--detach", str(turn_worktree), branch_tip], check=False
            )
            if added.returncode != 0:
                detail = (added.stderr or added.stdout or "unknown error").strip()
                raise SystemExit(
                    f"cannot create the merge turn's worktree at {turn_worktree}: {detail}"
                )
            unit.merge_state = MERGE_MERGING
            unit.merge_worktree = str(turn_worktree)
            r.save()

            expected_tip = branch_tip
            merged_tip = ""
            try:
                merge = run(
                    ["git", "-C", str(turn_worktree), "merge", "--no-ff", "--no-edit", unit.branch],
                    check=False,
                )
                if merge.returncode != 0:
                    run(["git", "-C", str(turn_worktree), "merge", "--abort"], check=False)
                    unit.merge_state = MERGE_READY
                    refusals.append(
                        f"{unit.name}: CONFLICT merging {unit.branch} onto {r.branch}; the turn "
                        "is released and the parent branch is untouched. Merge the parent branch "
                        "into the unit branch, resolve it there, then take the turn again"
                    )
                    continue
                head = run(["git", "-C", str(turn_worktree), "rev-parse", "HEAD"], check=False)
                if head.returncode != 0 or not head.stdout.strip():
                    unit.merge_state = MERGE_READY
                    refusals.append(f"{unit.name}: the merge result could not be read")
                    continue
                merged_tip = head.stdout.strip()
                reverted = main_regression_files(merged_tip, compare_ref)
                if reverted:
                    unit.merge_state = MERGE_READY
                    shown = ", ".join(reverted[:20]) + (" ..." if len(reverted) > 20 else "")
                    refusals.append(
                        f"{unit.name}: this merge would revert {len(reverted)} file(s) that "
                        f"{compare_ref} carries more recently: {shown}. Merge {compare_ref} into "
                        "the unit branch first, then take the turn again"
                    )
                    continue
                advanced = run(
                    ["git", "update-ref", branch_ref, merged_tip, expected_tip], check=False
                )
                if advanced.returncode != 0:
                    unit.merge_state = MERGE_READY
                    detail = (advanced.stderr or advanced.stdout or "unknown error").strip()
                    refusals.append(
                        f"{unit.name}: advancing {r.branch} failed: {detail}; the parent branch "
                        "is unchanged and the turn is released"
                    )
                    continue
            finally:
                unit.merge_worktree = None
                removed = run(
                    ["git", "worktree", "remove", "--force", str(turn_worktree)], check=False
                )
                if removed.returncode != 0 and os.path.lexists(turn_worktree):
                    detail = (removed.stderr or removed.stdout or "unknown error").strip()
                    cleanup_failures.append((turn_worktree, detail))
                r.save()

            branch_tip = merged_tip
            r.record_branch_advance(merged_tip)
            unit.merge_state = MERGE_MERGED
            landed.append(f"{unit.name} (+{ahead})")
            landed_names.append(unit.name)
            landed_tips[unit.name] = branch_tip
            completed_fix_ids.extend(complete_landed_fix_requests(r, [unit.name]))
            r.save()
            released, why = release_unit_worktree(unit, root)
            print(f"  {unit.name}: {why}")
            # A release DEFERRED because the unit still records a tab is the correct order, not a
            # cleanup failure: `clean` closes the tab and then removes the worktree. Only a
            # release that was attempted and could not be made records a failure, so the exit
            # status keeps meaning "something was left behind that should not have been".
            if not released and unit.worktree and not unit.tab_id:
                cleanup_failures.append((Path(unit.worktree), why))
            r.save()
    finally:
        report_cleanup_failures(cleanup_failures)

    resubmit_failed = False
    resubmit_owed_unmade = False
    any_pending = r.review_resubmit_pending or any(
        r.review_slot(unit)["review_resubmit_pending"] for unit in r.review_controllers()
    )
    if any_pending:
        try:
            if resubmit_review_if_ready(
                r, branch_tip, landed_names=landed_names, landed_revisions=landed_tips
            ):
                print(f"resubmitted landed revision {branch_tip} to the Code Review controller")
        except StagedInputError as exc:
            resubmit_failed = True
            resubmit_owed_unmade = True
            print(f"REVIEW RESUBMIT FAILED: {exc}")
        except SystemExit as exc:
            resubmit_failed = True
            resubmit_owed_unmade = True
            print(f"REVIEW RESUBMIT FAILED: {exc}")
        r.save()

    for held_controller in r.review_controllers():
        held_slot = r.review_slot(held_controller)
        if (
            held_controller.lifecycle
            and held_slot["review_resubmit_pending"]
            and held_slot["operator_fix_requests"]
        ):
            resubmit_owed_unmade = True
            print(
                f"REVIEW RESUBMISSION HELD for {held_controller.name} "
                f"(lifecycle {held_controller.lifecycle}): "
                f"{len(held_slot['operator_fix_requests'])} operator-owned fix request(s) "
                "outstanding"
            )

    outstanding_work = any(unit.fix_requests for unit in r.units)
    unscoped_slot = r.review_slot(
        None if any(u.lifecycle for u in r.review_controllers()) else r.review_controller()
    )
    if (
        unscoped_slot["review_resubmit_pending"]
        and unscoped_slot["operator_fix_requests"]
        and not outstanding_work
    ):
        resubmit_owed_unmade = True
        fix_ids = ", ".join(
            one_line(str(request.get("fix_id", "?"))) for request in r.operator_fix_requests
        )
        request_label = "request" if len(r.operator_fix_requests) == 1 else "requests"
        print(f"Code Review resubmission held by operator-owned fix {request_label}: {fix_ids}")

    print(f"merged onto {r.branch}: {', '.join(landed) or 'nothing new'}")
    if completed_fix_ids:
        print(f"review fixes landed: {', '.join(completed_fix_ids)}")
    if already:
        print(f"already there: {', '.join(already)}")
    if held:
        print(
            f"NOT MERGED BY REQUEST: {', '.join(held)} -- "
            f"their branches hold work that is not on {r.branch}; read them yourself"
        )
    if empty:
        print(f"COMMITTED NOTHING: {', '.join(empty)} -- those sessions finished without saving")
    for refusal in refusals:
        print(f"  MERGE TURN REFUSED: {refusal}")

    # The sweep names only the units THIS invocation merged. It runs even when a
    # cleanup failure has already been recorded -- issue 960 reported the opposite, a reap skipped
    # entirely because one path could not be cleaned, with nothing said about the skip.
    if getattr(args, "clean", False):
        kept_reasons: dict[str, str] = {}
        closed, _ = reap(r, merged_only=True, only=landed_names, kept_reasons=kept_reasons)
        r.save()
        if closed:
            print(f"reaped: {', '.join(closed)}")
        elif not landed_names:
            print("nothing to reap: this invocation merged nothing")
        else:
            print("nothing reaped: every unit this invocation merged was kept, reasons below")
        for name, reason in kept_reasons.items():
            print(f"kept {name}: {reason}")

    if refusals and not landed_names:
        return 1
    if resubmit_owed_unmade or resubmit_failed:
        return 4
    if cleanup_failures:
        return 3
    # Exit status 2 used to mean "every merge landed but a board writeback did not". There is no
    # writeback here any more (issue 1028), so there is no state that produces it, and inventing a
    # new meaning for a status callers already read would be worse than retiring it.
    return 0


def landed(branch: str, r: Run) -> bool | None:
    """Where this branch's work stands relative to the branch this run lands onto.

    Three answers, and the third is the one that used to be missing:

    ``True`` -- the branch has commits, and every one of them is on the run branch: landed.
    ``False`` -- the branch has commits the run branch does not have, or git cannot answer.
    ``None`` -- the branch has no commits of its own at all: nothing to land.

    ``None`` is NOT ``True``. A session that has not committed yet sits at exactly the commit it
    was cut from, and "zero commits ahead of the run branch" describes it perfectly -- which is
    also exactly what a merged branch looks like. Answering both with one yes is how
    `clean --merged` once closed the tabs and removed the worktrees of units that were still
    working, and destroyed their work. "Commits of its own" is the same question
    ``produced_anything`` answers, and gets the same reading: the unit's own commits from the
    merge base, or the merge that landed them.

    Measured against the run branch, not the operator's tree. Units land on the run branch as each
    phase finishes, and the operator's tree sees none of it until `collect`, once, at the very end.

    A run with no run branch predates `land`. There is nothing else to measure against, so the
    operator's tree it is.
    """
    base = r.resolved_run_ref()
    ahead = run(["git", "rev-list", "--count", f"{base}..{branch}"], check=False)
    if ahead.returncode != 0 or ahead.stdout.strip() not in ("", "0"):
        return False
    if branch_produced_anything(branch, r):
        return True
    return None


def reapable(unit: Unit, r: Run) -> bool:
    """May ``--merged`` reap this unit: its DONE work is landed and no review needs its controller.

    ``reap`` keeps a worker carrying a routed fix before this predicate is reached. Here, pending
    resubmission or operator-owned work keeps the controller available. The status gate keeps
    reaping away from anything still working:
    zero commits ahead of the run branch is also exactly what a unit that has not committed yet
    looks like, and that reading once cost four live units their worktrees. The commit gate keeps
    reaping away from a DONE unit that saved nothing: its worktree is the evidence the session
    failed, and this plugin keeps no other record.
    """
    if is_review_controller(unit):
        slot = r.review_slot(unit)
        if slot["review_resubmit_pending"] or bool(slot["operator_fix_requests"]):
            # Reaping here closes the session the controller still needs to resubmit through.
            return False
    if unit.status != DONE or not unit.branch:
        return False
    if r.unresolvable_branch:
        return False
    return landed(unit.branch, r) is True


@dataclass
class RemoteCleanReport:
    deleted: list[str] = field(default_factory=list)
    already_absent: list[str] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)


#: The reference names no run may ever delete from a remote. Membership is unchanged by #1025.
PROTECTED_BRANCH_NAMES = frozenset({"main", "master", "head", "develop", "release", "trunk"})

_REFS_HEADS_PREFIX = re.compile(r"^refs/heads/", re.IGNORECASE)


def normalize_branch_name(branch: str) -> str:
    """Strip, casefold, and only THEN peel any ``refs/heads/`` prefix (issue 874).

    The old ordering peeled first, case-sensitively, so four spellings of ``main`` escaped the
    denylist entirely: a leading space or tab meant the prefix did not match and the peel was a
    no-op, and ``refs/HEADS/`` or ``Refs/Heads/`` failed the same way. That is hygiene rather than
    a live exploit -- the current push encoding does not turn those spellings into a real deletion
    -- but the denylist is the last guard on the only destructive thing this plugin does, and it
    should hold on its own terms rather than by depending on how a caller normalises a name today.
    """
    return _REFS_HEADS_PREFIX.sub("", branch.strip().casefold()).strip()


def is_protected_remote_branch(branch: str, r: Run) -> bool:
    """Check if a branch is protected from remote deletion."""
    norm = normalize_branch_name(branch)
    if not norm:
        return True
    if norm in PROTECTED_BRANCH_NAMES:
        return True
    # The run branch, the resolved branch and the base get the SAME normalisation, not only the
    # literal denylist: a run branch spelled with a stray prefix escaped by the identical route.
    if r.branch and norm == normalize_branch_name(r.branch):
        return True
    if r.resolved_branch and norm == normalize_branch_name(r.resolved_branch):
        return True
    return bool(r.base and norm == normalize_branch_name(r.base))


def prove_remote_branch_merged(
    branch: str,
    remote_sha: str,
    r: Run,
    *,
    remote: str = "origin",
) -> tuple[bool, str]:
    """Check if the remote branch head is proven merged via GitHub PR or Git ancestry.

    Returns (is_merged, evidence_or_refusal_reason).
    """
    if is_protected_remote_branch(branch, r):
        return False, f"protected: branch {branch!r} is protected from remote deletion"

    remote_ref = branch if branch.startswith("refs/") else f"refs/heads/{branch}"
    # 1. GitHub PR verification if gh is available
    pr_res = run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "all",
            "--json",
            "number,url,state,mergedAt,headRefName,headRefOid",
        ],
        check=False,
    )
    if pr_res.returncode == 0 and pr_res.stdout.strip():
        try:
            prs = json.loads(pr_res.stdout)
            if isinstance(prs, list) and prs:
                for p in prs:
                    if p.get("headRefName") == branch:
                        state = (p.get("state") or "").upper()
                        if state == "OPEN":
                            return False, f"open (PR #{p.get('number')} is OPEN)"
                        if (state == "MERGED" or p.get("mergedAt")) and p.get(
                            "headRefOid"
                        ) == remote_sha:
                            return True, f"merged PR #{p.get('number')}"
                        if state == "CLOSED":
                            return (
                                False,
                                f"refused: PR #{p.get('number')} was closed without merge",
                            )
        except (ValueError, KeyError):
            pass

    # 2. Git committed ancestry proof
    if resolve_ref(remote_sha) is None:
        run(["git", "fetch", remote, remote_ref], check=False)

    if resolve_ref(remote_sha) is None:
        return False, f"unknown: remote head {remote_sha[:8]} not found locally or on remote"

    auth_targets: list[str] = []
    if r.resolved_branch:
        auth_targets.append(r.resolved_branch)
    if r.branch:
        rb = resolve_ref(r.branch)
        if rb and rb not in auth_targets:
            auth_targets.append(rb)
        rr = resolve_ref(f"refs/remotes/{remote}/{r.branch}") or resolve_ref(f"{remote}/{r.branch}")
        if rr and rr not in auth_targets:
            auth_targets.append(rr)
    main_ref = (
        resolve_ref("main")
        or resolve_ref(f"refs/remotes/{remote}/main")
        or resolve_ref(f"{remote}/main")
    )
    if main_ref and main_ref not in auth_targets:
        auth_targets.append(main_ref)
    if r.base:
        base_ref = resolve_ref(r.base)
        if base_ref and base_ref not in auth_targets:
            auth_targets.append(base_ref)

    # Also check remote heads of run branch and main if present on remote
    for ref_name in [r.branch, "main"]:
        if not ref_name:
            continue
        t_ref = ref_name if ref_name.startswith("refs/") else f"refs/heads/{ref_name}"
        ls_target = run(["git", "ls-remote", remote, t_ref], check=False)
        if ls_target.returncode == 0 and ls_target.stdout.strip():
            t_sha = ls_target.stdout.strip().splitlines()[0].split()[0]
            if resolve_ref(t_sha) is None:
                run(["git", "fetch", remote, t_ref], check=False)
            if resolve_ref(t_sha) and t_sha not in auth_targets:
                auth_targets.append(t_sha)

    for target in auth_targets:
        anc = run(["git", "merge-base", "--is-ancestor", remote_sha, target], check=False)
        if anc.returncode == 0:
            if (
                r.base
                and resolve_ref(r.base) == remote_sha
                and not branch_produced_anything(branch, r)
            ):
                return False, f"not merged (branch {branch} committed no work)"
            return True, f"ancestry proven: contained in {target[:8]}"

    return (
        False,
        f"diverged / unmerged: remote head {remote_sha[:8]} is not contained in authoritative branch",
    )


def clean_remote_branches(
    r: Run,
    *,
    remote: str = "origin",
    only: Sequence[str] | None = None,
) -> RemoteCleanReport:
    """Delete eligible run-owned remote branches.

    Considers only exact branch names recorded by the current run. Deletes only after merged-PR
    proof or committed ancestry proof that the head is contained in the authoritative branch.
    Refuses open, diverged, unknown, or retained branches with a clear reason and retains evidence.
    Reads back every deletion; repeated sweeps report already-absent branches cleanly.
    """
    report = RemoteCleanReport()
    scope = set(only) if only is not None else None

    unit_by_branch: dict[str, list[Unit]] = {}
    for u in r.units:
        if u.branch:
            unit_by_branch.setdefault(u.branch, []).append(u)

    for branch, units in unit_by_branch.items():
        if is_protected_remote_branch(branch, r):
            report.refused.append(
                (branch, f"protected: branch {branch!r} is protected from remote deletion")
            )
            continue
        if scope is not None and not any(u.name in scope for u in units):
            report.refused.append((branch, "retained (unit not in clean scope)"))
            continue
        if any(u.fix_requests for u in units):
            report.refused.append((branch, "retained (unit has outstanding review fixes)"))
            continue
        if any(u.status in (RUNNING, PENDING) for u in units):
            open_units = [u.name for u in units if u.status in (RUNNING, PENDING)]
            report.refused.append((branch, f"open (unit(s) {', '.join(open_units)} in progress)"))
            continue

        remote_ref = branch if branch.startswith("refs/") else f"refs/heads/{branch}"
        ls_res = run(["git", "ls-remote", remote, remote_ref], check=False)
        if ls_res.returncode != 0:
            err = (ls_res.stderr or ls_res.stdout or "").strip()
            report.refused.append((branch, f"unknown / remote query failed on {remote!r}: {err}"))
            continue

        output = ls_res.stdout.strip()
        if not output:
            report.already_absent.append(branch)
            continue

        remote_sha = output.splitlines()[0].split()[0]
        is_merged, evidence = prove_remote_branch_merged(branch, remote_sha, r, remote=remote)
        if not is_merged:
            report.refused.append((branch, evidence))
            continue

        del_ref = branch if branch.startswith("refs/heads/") else f"refs/heads/{branch}"
        del_res = run(["git", "push", remote, "--delete", "--", del_ref], check=False)
        if del_res.returncode != 0:
            err = (del_res.stderr or del_res.stdout or "").strip()
            report.refused.append((branch, f"deletion failed on {remote!r}: {err}"))
            continue

        rb_res = run(["git", "ls-remote", remote, remote_ref], check=False)
        if rb_res.returncode == 0 and not rb_res.stdout.strip():
            report.deleted.append(branch)
        else:
            report.refused.append(
                (branch, f"read-back failed: branch {branch} still present on {remote!r}")
            )

    return report


def _reap_keep_reason(unit: Unit, r: Run) -> str:
    """The true reason a ``--merged`` sweep kept this unit.

    Mirrors ``reapable``'s gate order -- a change there must be reflected here, or the
    printed reason silently stops being the truth. The routed-fix gate is reap's own, one
    line above the call.
    """
    if is_review_controller(unit):
        slot = r.review_slot(unit)
        if slot["review_resubmit_pending"] or bool(slot["operator_fix_requests"]):
            return "review controller still owed a resubmission"
    if unit.status != DONE:
        return "not done"
    if not unit.branch:
        # cmd_settle records the review controller in exactly this shape: done, with no branch
        # of its own. It is not "not done" (terminal review F26); it has nothing to reap.
        return "done, with no branch of its own to measure"
    if r.unresolvable_branch:
        return "run branch unresolved"
    if landed(unit.branch, r) is None:
        return "committed nothing to land"
    # landed()'s single False covers two causes: the branch carries commits the run branch does
    # not, and git could not answer at all. Ask the same question once more here so the printed
    # reason names the true one (terminal review F37).
    comparison = run(
        ["git", "rev-list", "--count", f"{r.resolved_run_ref()}..{unit.branch}"], check=False
    )
    if comparison.returncode != 0:
        detail = (comparison.stderr or comparison.stdout or "").strip().splitlines()
        return f"git could not compare branch {unit.branch} against the run branch" + (
            f": {detail[0]}" if detail else ""
        )
    return "not on the run branch"


def reap(
    r: Run,
    *,
    merged_only: bool,
    branches: bool = False,
    only: Sequence[str] | None = None,
    remote: str = "origin",
    kept_reasons: dict[str, str] | None = None,
    failures: dict[str, str] | None = None,
) -> tuple[list[str], list[str]]:
    """Close tabs and remove worktrees; return ``(closed, kept)`` by unit name.

    A worker carrying an outstanding review fix is always kept. Otherwise, ``merged_only`` applies
    the ``--merged`` rule -- see ``reapable`` -- and keeps everything else. Without it, every other
    unit is closed regardless of its state: a last resort, run with the table in front of you,
    because it also discards the worktree that is the evidence a unit failed.

    ``only`` narrows the sweep to those unit names; every other unit is kept, whatever its
    state. ``merge --clean`` passes the units that turn just merged, so reaping there is a
    consequence of what that invocation did -- not a licence to close work an earlier one
    deliberately kept. ``clean`` never passes it: the operator's own sweep still sees the whole
    run, and its behaviour is unchanged.

    ``branches`` deletes the branches of the units it closes, and ONLY after that unit's worktree
    is gone: git refuses to delete a branch a worktree still holds, so the other order fails on
    every unit that still has one. A removal that failed keeps the unit, so the branch stays too
    -- it is the last copy of a failed unit's work.

    **The sweep never stops early.** One unit whose path cannot be removed keeps that unit, names
    it, and the loop continues: issue 960 reported the opposite, a whole reap skipped because one
    path could not be cleaned, with nothing in the output saying the reap did not happen.
    """
    kept, closed = [], []
    root = repo_root()
    scope = set(only) if only is not None else None
    for unit in r.units:
        if scope is not None and unit.name not in scope:
            kept.append(unit.name)
            continue
        if unit.fix_requests:
            kept.append(unit.name)
            if kept_reasons is not None:
                kept_reasons[unit.name] = "fix request outstanding"
            continue
        if merged_only and not reapable(unit, r):
            kept.append(unit.name)
            if kept_reasons is not None:
                kept_reasons[unit.name] = _reap_keep_reason(unit, r)
            continue
        tab_closed = False
        if unit.tab_id:
            close_result = close_run_session(unit)
            if close_result is None:
                # The launcher did not create this tab, so it is never closed here. Report it
                # as left open -- never as closed -- and keep the unit: the run record is
                # what names the tab the operator must close by hand, and the session in it
                # may still be standing in this unit's worktree.
                if kept_reasons is not None:
                    # Reported, but NOT a failure of this run's cleanup: the run never owned
                    # this tab, so there is nothing here it failed to clean. Exit 3 means
                    # "something this run owns was left behind", and widening it to include a
                    # borrowed tab would make the honest signal fire on a healthy sweep.
                    kept_reasons[unit.name] = f"tab left open (not owned): tab {unit.tab_id}"
                kept.append(unit.name)
                continue
            if close_result.returncode != 0:
                detail = (close_result.stderr or close_result.stdout or "").strip()
                failure = tab_close_failure(unit.tab_id, close_result.returncode, detail)
                # The note was already recorded by close_run_session, the single owner; a
                # repeated failure must not stack a second copy on it.
                if kept_reasons is not None:
                    kept_reasons[unit.name] = failure
                if failures is not None:
                    failures[unit.name] = failure
                kept.append(unit.name)
                continue
            tab_closed = True
        if unit.worktree and Path(unit.worktree).exists():
            removed = run(["git", "worktree", "remove", "--force", unit.worktree], check=False)
            if removed.returncode != 0 and os.path.lexists(unit.worktree):
                # Mirror the landing-worktree treatment: a removal that failed and left the
                # directory behind keeps the unit, so the run record still names the worktree
                # and `clean --all` does not delete the only record of it (terminal review F27).
                # The tab, if this pass closed it, is named too, so the report matches the side
                # effects performed (cycle 2, F71); a rerun closes an absent tab idempotently.
                detail = (removed.stderr or removed.stdout or "").strip()
                if kept_reasons is not None:
                    closed_tab = f"tab {unit.tab_id} closed; " if tab_closed else ""
                    kept_reasons[unit.name] = (
                        f"{closed_tab}worktree removal failed ({removed.returncode}): {detail}"
                    )
                if failures is not None:
                    failures[unit.name] = (
                        f"worktree removal failed ({removed.returncode}): {detail}"
                    )
                kept.append(unit.name)
                continue
        if branches and unit.branch:
            run(["git", "branch", "-D", unit.branch], check=False)
        closed.append(unit.name)

    if branches:
        remote_report = clean_remote_branches(r, remote=remote, only=only)
        for b in remote_report.deleted:
            print(f"deleted remote branch: {b}")
        for b in remote_report.already_absent:
            print(f"already absent on remote: {b}")
        for b, reason in remote_report.refused:
            print(f"retained remote branch {b}: {reason}")

    if scope is None:
        for label, reason in retire_run_workspaces(r):
            if reason is None:
                closed.append(label)
            else:
                kept.append(label)
                if kept_reasons is not None:
                    kept_reasons[label] = reason
                if failures is not None:
                    failures[label] = reason
        for label, reason in report_unattended_worktrees(r, root):
            kept.append(label)
            if kept_reasons is not None:
                kept_reasons[label] = reason
    return closed, kept


def retire_run_workspaces(r: Run) -> list[tuple[str, str | None]]:
    """Retire the herdr workspaces THIS RUN created; return ``(label, reason kept)`` rows.

    Ownership comes from the record's ``workspaces_created`` list, never from a name pattern: a
    prefix match would eventually retire someone else's workspace. A workspace still holding a
    live agent, or a tab this run does not own, is refused with the agent named -- the cleanup's
    own docstring has always warned about a workspace list that accumulates dead lanes, and this
    is that warning one level up (issue 876).
    """
    rows: list[tuple[str, str | None]] = []
    if not r.workspaces_created:
        return rows
    try:
        agents = live_agents()
    except SystemExit as exc:
        return [
            (f"workspace {name}", f"herdr could not be asked which agents are live: {exc}")
            for name in r.workspaces_created
        ]
    owned_panes = {unit.pane_id for unit in r.units if unit.pane_id}
    for name in list(r.workspaces_created):
        label = f"workspace {name}"
        occupant = next(
            (
                row
                for row in agents
                if str(row.get("pane_id", "")).partition(":")[0] == name
                and row.get("pane_id") not in owned_panes
            ),
            None,
        )
        if occupant is not None:
            rows.append((label, f"it still holds {occupant.get('name', 'an agent')}"))
            continue
        still_live = [
            row for row in agents if str(row.get("pane_id", "")).partition(":")[0] == name
        ]
        if still_live:
            rows.append((label, f"{len(still_live)} of this run's tabs are still open in it"))
            continue
        closed_proc = run(["herdr", "workspace", "close", name], check=False, timeout=60)
        if closed_proc.returncode != 0:
            detail = (closed_proc.stderr or closed_proc.stdout or "unknown error").strip()
            rows.append((label, f"closing it failed ({closed_proc.returncode}): {detail}"))
            continue
        r.workspaces_created.remove(name)
        rows.append((label, None))
    return rows


def report_unattended_worktrees(r: Run, root: Path) -> list[tuple[str, str]]:
    """The one check worth keeping from the retired fleet-doctor command.

    A worktree this run manages with no live session in it is a leaked resource: nothing else
    reports it, and it is the state that leaves a remote branch undeletable long after the run
    has finished. Reported by path; never removed here, because a unit's worktree is also the
    evidence its session failed.
    """
    findings: list[tuple[str, str]] = []
    try:
        agents = live_agents()
    except SystemExit:
        return findings
    live_cwds = {str(row.get("cwd")) for row in agents if row.get("cwd")}
    live_names = {str(row.get("name")) for row in agents if row.get("name")}
    for unit in r.units:
        if not unit.worktree or unit.status in (DONE, *TERMINAL_UNIT_STATUSES):
            continue
        if not os.path.lexists(Path(unit.worktree)):
            continue
        if str(Path(unit.worktree)) in live_cwds:
            continue
        # Match on the agent NAME as well as the working directory. herdr does not always report
        # a cwd, and "this session did not say where it is" must not read as "no session is
        # there" -- absence of information is not evidence of absence, which is the rule this
        # file already applies to a companion it cannot ask.
        if (unit.agent_name or unit.name) in live_names:
            continue
        findings.append(
            (
                f"managed worktree at {unit.worktree}",
                f"{unit.name} is {unit.status} but no live session is standing in it",
            )
        )
    return findings


def cmd_clean(args: argparse.Namespace) -> int:
    """Close tabs and remove worktrees.

    ``--merged`` reaps a unit only when its status is DONE and every commit it made is on the run
    branch. A RUNNING or PENDING unit is never touched, whatever its commit count -- zero commits
    ahead is also exactly what a unit looks like that has not committed yet, and reaping it
    destroys work still in flight. A DONE unit that committed nothing keeps its worktree too:
    that worktree is the evidence the session saved nothing, and this plugin keeps no other
    record.

    Without ``--merged``, every unit is closed regardless of its state. That is a last resort,
    not a routine: run it with the table in front of you.

    Branches are deleted only with ``--branches``: a branch is cheap, and it is the last copy of
    a failed unit's work.

    It also retires the herdr workspaces this run created -- ownership read from the record, never
    from a name pattern -- and reports a managed worktree with no live session in it, which is the
    one check worth keeping from the retired fleet-doctor command.

    **The sweep is total.** Every unit in scope is visited even when an earlier one could not be
    cleaned, and every leftover is named with git's own message. The exit status says so: 0 when
    nothing was left behind, 3 when something was.

    Run it after every ``merge``, not once at the end. A phase's sessions are finished the moment
    their work is on the parent branch, and leaving them open for the rest of the run is how a
    workspace ends up with a dozen idle tabs nobody can tell apart.
    """
    assert_agent_launcher_available()  # reaching `close_run_session`: gate first
    r = Run.load(args.issue, args.store_root)
    if r.unresolvable_branch:
        print(
            f"WARNING: run branch {r.unresolvable_branch!r} does not resolve; "
            "branch-dependent cleanup checks are unavailable"
        )
    remote = getattr(args, "remote", "origin") or "origin"
    kept_reasons: dict[str, str] = {}
    # Kept-by-rule and could-not-be-removed are different things, and only the second is a
    # cleanup failure. `--merged` keeping a running unit is the rule working; an exit code that
    # called that incomplete would make the honest signal useless.
    failures: dict[str, str] = {}
    try:
        closed, kept = reap(
            r,
            merged_only=args.merged,
            branches=args.branches,
            remote=remote,
            kept_reasons=kept_reasons,
            failures=failures,
        )
    finally:
        # Exception-proof by construction: printing, and nothing else. A leftover named only on
        # the happy path is a leftover nobody hears about when it matters (issue 979).
        for name, reason in kept_reasons.items():
            print(f"kept {name}: {reason}")
        with contextlib.suppress(RecordError):
            r.save()
    print(f"closed: {', '.join(closed) or 'nothing'}")
    ordinary_kept = [name for name in kept if name not in kept_reasons]
    if ordinary_kept:
        print(f"kept (not done, or its work not on the run branch): {', '.join(ordinary_kept)}")
    return 3 if failures else 0


def cmd_check(args: argparse.Namespace) -> int:
    """Report where the run record and the repository disagree.

    Read-only: no writes, no merges, no launches. The record is one JSON file and the truth is git
    plus herdr, and the two can drift -- a session started by hand leaves a branch with no row; a
    unit marked done saved nothing; a unit marked running finished while nobody was looking. Each
    shape of drift is reported, and finding any of them is the non-zero exit; ``adopt`` is the
    repair for the first one, and ``settle`` is the repair for the last -- it reads idle twice,
    ``interval`` seconds apart, and only marks the unit done when both readings agree.
    """
    r = Run.load(args.issue, args.store_root)
    findings: list[str] = []
    branch_error = r.unresolvable_branch
    branch_tip = r.resolved_branch

    if branch_error:
        findings.append(f"RUN BRANCH -- run branch {branch_error!r} does not resolve")

    root = repo_root()
    for label, reason in report_unattended_worktrees(r, root):
        findings.append(f"UNATTENDED {label} -- {reason}")

    for name, branch in discover_unrecorded(r):
        findings.append(f"UNRECORDED {name} -- branch {branch} is not a unit in this run")

    # One herdr round for the whole run, not one per row. A pending or failed unit has no session,
    # so it is never matched against the list at all. Without an ingested companion Herdr cannot
    # be asked: the fault prints once and every reading is unknown, never gone.
    agents: list[dict[str, Any]] | None
    if _AGENT_LAUNCHER_AVAILABLE:
        agents = live_agents()
    else:
        _print_companion_fault_once()
        agents = None
        findings.append("LIVENESS UNCHECKED -- companion missing or unusable; herdr was not asked")
    for unit in r.units:
        if (
            _AGENT_LAUNCHER_AVAILABLE
            and branch_error is None
            and has_delivery_warning(unit)
            and not produced_anything(unit, r)
        ):
            findings.append(
                f"DELIVERY WARNING {unit.name} -- sent its task but was never observed starting, "
                "and its branch has no commits"
            )
        if unit.status not in (RUNNING, DONE):
            continue
        state = poll(unit, agents) if agents is not None else "unknown"
        if unit.status == DONE:
            if branch_error is None and not produced_anything(unit, r):
                findings.append(
                    f"NO COMMITS {unit.name} -- marked done, but its branch committed nothing"
                )
            if branch_error is None and unit.merge and r.branch and unit.branch:
                assert branch_tip is not None
                ahead = run(
                    ["git", "rev-list", "--count", f"{branch_tip}..{unit.branch}"], check=False
                )
                count = ahead.stdout.strip() if ahead.returncode == 0 else ""
                if count not in ("", "0"):
                    plural = "commit" if count == "1" else "commits"
                    findings.append(f"NOT LANDED {unit.name} -- {count} {plural} not on {r.branch}")
            if state == "working":
                findings.append(
                    f"STILL WORKING {unit.name} -- marked done, but its session is still working"
                )
        elif state == "gone":
            findings.append(f"SESSION GONE {unit.name} -- marked running, but its session is gone")
        elif branch_error is None and state in {"idle", "done"} and produced_anything(unit, r):
            # Idle with nothing committed is not drift -- a session is also idle between turns,
            # thinking. Idle with commits is a unit that finished while the record still calls it
            # running, and nothing else will notice until an operator asks why the run stopped.
            findings.append(
                f"LOOKS DONE {unit.name} -- marked running, but its session is {state} "
                f"and its branch has commits"
            )

    if not findings:
        print("the record agrees with the repository")
        return 0
    for line in findings:
        print(f"  {line}")
    return 1


def resolve_ref(ref: str) -> str | None:
    """The commit a ref names, or None when nothing resolves -- gone, or never existed."""
    if not ref:
        return None
    got = run(["git", "rev-parse", "--verify", "--quiet", ref], check=False)
    if got.returncode != 0:
        return None
    return got.stdout.strip() or None


def merge_base(ref_a: str, ref_b: str) -> str | None:
    """The newest commit common to both refs, or None when git finds none."""
    got = run(["git", "merge-base", ref_a, ref_b], check=False)
    if got.returncode != 0:
        return None
    return got.stdout.strip() or None


def landing_merges(branch_tips: Mapping[str, str], cmp_ref: str) -> dict[str, str]:
    """Map branches to the first-parent merge that landed each current tip on ``cmp_ref``."""
    branches_by_tip: dict[str, list[str]] = {}
    for branch, tip in branch_tips.items():
        branches_by_tip.setdefault(tip, []).append(branch)
    if not branches_by_tip:
        return {}
    log = run(["git", "log", "--first-parent", "--merges", "--format=%H %P", cmp_ref], check=False)
    if log.returncode != 0:
        return {}
    found: dict[str, str] = {}
    for line in log.stdout.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        for branch in branches_by_tip.get(parts[2], []):
            found.setdefault(branch, parts[0])
    return found


def landing_merge(branch: str, cmp_ref: str) -> str | None:
    """The merge commit that landed ``branch`` onto ``cmp_ref``, or None when it never landed.

    ``land`` creates a ``--no-ff`` merge in a detached worktree and advances the run branch ref, so
    a landed unit branch is the second parent of the merge that brought it in. Finding that merge
    is what lets a landed unit still show its change -- the merge base of the merge's parents is
    where the unit branched -- instead of an empty diff that reads as "this unit changed nothing".
    """
    tip = resolve_ref(branch)
    if tip is None:
        return None
    return landing_merges({branch: tip}, cmp_ref).get(branch)


def diff_against(r: Run) -> str | None:
    """The ref a unit's change is measured against.

    The run branch when there is one; the run base for a run predating it -- those units all
    branched from the base, so it is still the honest comparison. None when neither resolves,
    which leaves nothing to diff against."""
    if r.branch and r.resolved_branch is not None:
        return r.branch
    if resolve_ref(r.base) is not None:
        return r.base
    return None


def print_git_diff(base: str, branch: str, *, stat: bool) -> None:
    """The git diff itself: a full patch, or the stat summary with ``stat``."""
    argv = ["git", "diff"]
    if stat:
        argv.append("--stat")
    argv.append(f"{base}..{branch}")
    body = run(argv).stdout.strip("\n")
    if body:
        print(body)


def show_unit_diff(unit: Unit, cmp_ref: str, *, stat: bool) -> None:
    """One unit's change -- merge base to branch -- or words for why there is nothing to show.

    An empty diff is never printed: it reads as "this unit changed nothing", and a branch
    measures empty in two ways that are both not nothing -- its work already landed on the run
    branch, or the session never committed at all. Each gets words of its own."""
    if not unit.branch:
        print(f"{unit.name}: has no branch -- it was never launched")
        return
    branch = unit.branch
    if resolve_ref(branch) is None:
        print(f"{unit.name}: branch {branch} no longer resolves -- nothing to diff")
        return
    base = merge_base(cmp_ref, branch)
    if base is None:
        print(f"{unit.name}: no commit common to {cmp_ref} and {branch} -- cannot compare")
        return
    own = run(["git", "rev-list", "--count", f"{base}..{branch}"], check=False)
    if own.returncode == 0 and own.stdout.strip() not in ("", "0"):
        print(f"{unit.name}: diff {base[:8]}..{branch}")
        print(
            f"merge base {base[:8]} of {cmp_ref} and {branch} -- work landed on {cmp_ref} "
            "by siblings does not appear in this diff"
        )
        print_git_diff(base, branch, stat=stat)
        return
    # Nothing of its own against the comparison ref. That is either "already landed" or "never
    # committed", and the run branch says which: a landed branch is the second parent of the
    # merge that brought it in.
    merged = landing_merge(branch, cmp_ref)
    if merged is None:
        print(f"{unit.name}: branch {branch} has no commits of its own")
        return
    branched = merge_base(f"{merged}^1", branch)
    if branched is None:
        print(f"{unit.name}: landed in {merged[:8]}, but its branch point no longer resolves")
        return
    print(
        f"{unit.name}: landed on {cmp_ref} in merge {merged[:8]} -- diff {branched[:8]}..{branch}"
    )
    print(f"merge base {branched[:8]} -- where {branch} branched before it was merged")
    print_git_diff(branched, branch, stat=stat)


def diff_summary(r: Run, cmp_ref: str) -> int:
    """The shape of the whole run: one stat summary per unit that has a branch."""
    branched = [u for u in r.units if u.branch]
    if not branched:
        print("no unit has a branch yet -- nothing to diff")
        return 0
    print(f"run {r.run_id} against {cmp_ref} -- each unit's change, merge base to branch")
    for unit in branched:
        print()
        show_unit_diff(unit, cmp_ref, stat=True)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    """Show what a unit actually changed: the diff from the merge base to its branch.

    ``run-branch..unit-branch`` is the obvious comparison and the wrong one for this question:
    every unit in a phase branches from the same base, so the moment a sibling lands, that diff
    reports the sibling's additions as this unit's deletions -- in one run it showed a 391-line
    test file as deleted by a unit that had never touched it. The merge base of the run branch
    and the unit branch is where the unit branched; from there to the branch is its change, and
    nobody else's, whoever else has landed since.

    With no unit name, prints the stat summary of every unit that has a branch -- the shape of
    the whole run in one read.
    """
    r = Run.load(args.issue, args.store_root)
    cmp_ref = diff_against(r)
    if cmp_ref is None:
        print("neither the run branch nor the run base resolves -- nothing to compare against")
        return 1
    if not args.unit:
        return diff_summary(r, cmp_ref)
    show_unit_diff(r.unit(args.unit), cmp_ref, stat=args.stat)
    return 0


def cmd_adopt(args: argparse.Namespace) -> int:
    """Put stranded unit branches back into the run record.

    A unit created outside the run -- a session launched by hand, a run file deleted around live
    work -- leaves a branch the table knows nothing about. This finds those branches and rebuilds a
    row from what is still true: the branch, its worktree, and the session herdr reports there.
    Without ``--yes`` nothing is written; the discovery is printed so the operator can see what
    would be added.
    """
    r = Run.load(args.issue, args.store_root)
    if r.unresolvable_branch:
        print(
            f"WARNING: run branch {r.unresolvable_branch!r} does not resolve; commit-based "
            "adoption checks are unavailable, so units without a live session are marked failed"
        )
    found = discover_unrecorded(r)
    if not found:
        print("nothing to adopt -- every run branch is already a unit")
        return 0

    agents = live_agents()
    rebuilt = [rebuild_unit(name, branch, r, agents) for name, branch in found]
    verb = "adopted" if args.yes else "would adopt"
    for unit in rebuilt:
        line = (
            f"  {verb}: {unit.name}  vendor={unit.vendor}  "
            f"status={unit.status}  branch={unit.branch}"
        )
        print(line)

    if not args.yes:
        print("nothing written -- rerun with --yes")
        return 0
    r.units.extend(rebuilt)
    r.save()
    print(f"{len(rebuilt)} unit(s) written to the run file")
    return 0


def _default_pr_title(unit: Unit, r: Run) -> str:
    issue_ref = r.issues.get(unit.name)
    if issue_ref:
        m = re.search(r"#(\d+)", issue_ref)
        if m:
            return f"fix({unit.name}): resolve #{m.group(1)}"
    m = re.search(r"fix\s+#?(\d+)", unit.task, re.IGNORECASE)
    if m:
        return f"fix({unit.name}): resolve #{m.group(1)}"
    return f"fix({unit.name}): {one_line(unit.task)[:60]}"


def _default_pr_body(unit: Unit, r: Run, parked: dict[str, Any]) -> str:
    lines = [
        f"Coordinator-resumed PR for parked unit `{unit.name}` in run `{r.run_id}`.",
        "",
        f"**Frozen revision:** `{parked.get('frozen_revision', '')}`",
        f"**Remote head:** `{parked.get('remote_head', '')}`",
        f"**Authoritative base:** `{parked.get('base', '')}`",
    ]
    if parked.get("failure_evidence"):
        lines.extend(
            [
                "",
                "**Original PR creation blocker:**",
                f"```\n{parked.get('failure_evidence')}\n```",
            ]
        )
    return "\n".join(lines)


def park_unit(
    r: Run,
    unit_name: str,
    failure_evidence: str,
    *,
    remote: str = "origin",
    base: str | None = None,
) -> Unit:
    """Record a typed parked state for a unit whose push succeeded but PR creation blocked.

    A failed push never enters this path: the pushed commit must be verified on the recorded
    remote branch via `git ls-remote` before the run record is mutated. If the remote branch is
    missing, or its head differs from the local frozen revision, this fails loudly without
    mutating the run record.
    """
    unit = r.unit(unit_name)
    if not unit.branch:
        raise SystemExit(f"unit {unit_name!r} has no branch recorded; cannot park")
    local_tip = resolve_ref(unit.branch)
    if not local_tip:
        raise SystemExit(
            f"unit {unit_name!r} branch {unit.branch!r} does not resolve locally; cannot park"
        )

    remote_ref = unit.branch if unit.branch.startswith("refs/") else f"refs/heads/{unit.branch}"
    ls_remote = run(["git", "ls-remote", remote, remote_ref], check=False)
    if ls_remote.returncode != 0:
        err = (ls_remote.stderr or ls_remote.stdout or "").strip()
        raise SystemExit(f"failed to query remote {remote!r} for branch {unit.branch!r}: {err}")
    output = ls_remote.stdout.strip()
    if not output:
        raise SystemExit(
            f"unit {unit_name!r} branch {unit.branch!r} not found on remote {remote!r}; "
            "a failed push never enters the parked state"
        )
    remote_sha = output.splitlines()[0].split()[0]
    if remote_sha != local_tip:
        raise SystemExit(
            f"unit {unit_name!r} remote head {remote_sha!r} on {remote!r} does not match "
            f"local frozen revision {local_tip!r}; cannot park"
        )

    auth_base = base or (r.branch if r.branch else "main")
    unit.status = PARKED
    unit.parked_state = {
        "unit": unit.name,
        "remote_head": remote_sha,
        "base": auth_base,
        "frozen_revision": local_tip,
        "failure_evidence": failure_evidence,
        "remote_branch": unit.branch,
        "remote": remote,
        "pr_url": None,
        "pr_number": None,
        "resumed": False,
    }
    append_note = (
        f"parked: push verified at {remote_sha[:8]}; PR creation blocked ({failure_evidence})"
    )
    unit.note = f"{unit.note}; {append_note}" if unit.note else append_note
    r.save()
    return unit


def resume_unit(
    r: Run,
    unit_name: str,
    *,
    title: str | None = None,
    body: str | None = None,
    base: str | None = None,
    remote: str | None = None,
) -> tuple[Unit, dict[str, Any]]:
    """Idempotently open or adopt a PR for a parked unit, continuing the original run.

    Fails loudly without mutating the run record if the remote branch is missing or if its
    remote head has changed from the recorded frozen revision.
    """
    unit = r.unit(unit_name)
    if unit.status != PARKED:
        if unit.status == DONE and unit.parked_state and unit.parked_state.get("resumed"):
            pr_info = {
                "action": "already_resumed",
                "pr_url": unit.parked_state.get("pr_url"),
                "pr_number": unit.parked_state.get("pr_number"),
            }
            return unit, pr_info
        raise SystemExit(
            f"unit {unit_name!r} is not in parked state (status={unit.status!r}); cannot resume"
        )

    parked = unit.parked_state
    if not parked or not parked.get("remote_head") or not parked.get("frozen_revision"):
        raise SystemExit(f"unit {unit_name!r} has invalid or missing parked state; cannot resume")

    target_remote = remote or parked.get("remote", "origin")
    remote_branch = parked.get("remote_branch") or unit.branch
    if not remote_branch:
        raise SystemExit(f"unit {unit_name!r} has no remote branch recorded; cannot resume")
    expected_remote_head = parked["remote_head"]
    auth_base = base or parked.get("base") or (r.branch if r.branch else "main")

    # Verify remote head before doing anything
    remote_ref = (
        remote_branch if remote_branch.startswith("refs/") else f"refs/heads/{remote_branch}"
    )
    ls_remote = run(["git", "ls-remote", target_remote, remote_ref], check=False)
    if ls_remote.returncode != 0:
        err = (ls_remote.stderr or ls_remote.stdout or "").strip()
        raise SystemExit(
            f"failed to query remote {target_remote!r} for branch {remote_branch!r}: {err}"
        )
    output = ls_remote.stdout.strip()
    if not output:
        raise SystemExit(
            f"remote branch {remote_branch!r} is missing on remote {target_remote!r}; "
            "cannot resume without verified remote branch"
        )
    current_remote_sha = output.splitlines()[0].split()[0]
    if current_remote_sha != expected_remote_head:
        raise SystemExit(
            f"remote head for {remote_branch!r} on {target_remote!r} has changed: "
            f"expected {expected_remote_head!r}, found {current_remote_sha!r}; "
            "cannot resume"
        )

    # Check for existing matching PR on GitHub
    pr_list = run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            remote_branch,
            "--json",
            "number,url,state,headRefName,headRefOid",
        ],
        check=False,
    )
    existing_pr: dict[str, Any] | None = None
    if pr_list.returncode == 0 and pr_list.stdout.strip():
        try:
            prs = json.loads(pr_list.stdout)
            if isinstance(prs, list) and prs:
                for p in prs:
                    if (
                        p.get("headRefName") == remote_branch
                        or p.get("headRefOid") == expected_remote_head
                    ):
                        existing_pr = p
                        break
                if not existing_pr and prs:
                    existing_pr = prs[0]
        except (ValueError, KeyError):
            existing_pr = None

    if existing_pr is not None:
        pr_url = str(existing_pr.get("url", ""))
        pr_number = existing_pr.get("number")
        action = "adopted"
    else:
        pr_title = title or _default_pr_title(unit, r)
        pr_body = body or _default_pr_body(unit, r, parked)
        create_argv = [
            "gh",
            "pr",
            "create",
            "--head",
            remote_branch,
            "--base",
            auth_base,
            "--title",
            pr_title,
            "--body",
            pr_body,
        ]
        created = run(create_argv, check=False)
        if created.returncode != 0:
            err = (created.stderr or created.stdout or "").strip()
            raise SystemExit(f"failed to create PR for unit {unit_name!r}: {err}")
        pr_url = created.stdout.strip().splitlines()[-1]
        m = re.search(r"/pull/(\d+)", pr_url)
        pr_number = int(m.group(1)) if m else None
        action = "opened"

    unit.parked_state["pr_url"] = pr_url
    unit.parked_state["pr_number"] = pr_number
    unit.parked_state["resumed"] = True
    unit.status = DONE
    note_msg = f"resumed ({action} PR #{pr_number or pr_url})"
    unit.note = f"{unit.note}; {note_msg}" if unit.note else note_msg
    r.save()
    return unit, {"action": action, "pr_url": pr_url, "pr_number": pr_number}


def cmd_park(args: argparse.Namespace) -> int:
    r = Run.load(args.issue, args.store_root)
    evidence = args.evidence.strip()
    if not evidence:
        raise SystemExit("failure evidence must not be empty")
    unit = park_unit(r, args.unit, evidence, remote=args.remote, base=args.base)
    print(
        f"  {unit.name}: parked (remote head {unit.parked_state['remote_head'][:8]} verified on {args.remote})"
    )
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    r = Run.load(args.issue, args.store_root)
    unit, info = resume_unit(
        r,
        args.unit,
        title=args.title,
        body=args.body,
        base=args.base,
        remote=args.remote,
    )
    action = info["action"]
    pr_url = info.get("pr_url", "")
    if action == "already_resumed":
        print(f"  {unit.name}: already resumed ({pr_url})")
    else:
        print(f"  {unit.name}: {action} PR {pr_url} -> status=done")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="orchestrate", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def stateful(name: str, help_text: str) -> argparse.ArgumentParser:
        """A subcommand that reads or writes one issue's run record.

        Every one of them takes ``--issue``: the record is per issue, which is what lets two
        issues be driven in one repository at once. ``--store-root`` exists for the tests and for
        reading a record that belongs to another checkout; nothing in the test suite may write
        into the primary checkout's live store.
        """
        child = sub.add_parser(name, help=help_text)
        child.add_argument("--issue", type=int, required=True, help="the issue this run is for")
        child.add_argument(
            "--store-root", default=None, help="override the resolved run-record store"
        )
        return child

    s = sub.add_parser("plan-check", help="validate a plan completely and create nothing")
    s.add_argument("--plan", required=True)
    s.set_defaults(func=cmd_plan_check)

    s = stateful("start", "create the parent branch and the unit rows from a plan")
    s.add_argument("--plan", required=True)
    s.add_argument("--base", help="commit to branch every unit from (default HEAD)")
    s.add_argument(
        "--branch",
        help="name the run's shared branch; without it, parent/<issue> when the issue has "
        "sub-issues and issue/<issue> when it does not",
    )
    s.set_defaults(func=cmd_start)

    s = sub.add_parser("roster", help="list the agents this machine can actually run")
    s.add_argument("--probe", action="store_true", help="check tier flags against each tool's help")
    s.add_argument("--models", action="store_true", help="ask each vendor which models it has")
    s.add_argument("--limit", type=int, default=12, help="models to show per vendor")
    s.set_defaults(func=cmd_roster)

    s = sub.add_parser("saga", help="how each vendor invokes a saga capability")
    s.add_argument("cap", help="the bare capability name, e.g. plan")
    s.set_defaults(func=cmd_saga)

    s = stateful("expand", "append units to a run in flight, once a phase names them")
    s.add_argument("--plan", required=True)
    s.set_defaults(func=cmd_expand)

    s = stateful(
        "review-result",
        "persist a typed Code Review result verbatim and route its fix requests",
    )
    s.add_argument("--file", required=True, help="UTF-8 file containing the complete typed result")
    s.add_argument(
        "--controller",
        help="which Code Review controller this result belongs to, by unit name or lifecycle; "
        "required when the run carries more than one",
    )
    s.set_defaults(func=cmd_review_result)

    s = stateful("go", "launch every unit whose dependencies are met")
    s.add_argument(
        "--limit",
        type=int,
        default=0,
        help="launch at most this many in THIS call. Not a cap: the run's concurrency allocation "
        "in the record is the cap, and it counts open role panes as well as running units",
    )
    s.set_defaults(func=cmd_go)

    s = stateful("status", "show the table")
    s.set_defaults(func=cmd_status)

    s = stateful("settle", "mark running units done when their session goes idle")
    s.add_argument(
        "--interval",
        type=int,
        default=20,
        help="seconds between the two idle readings (default 20)",
    )
    s.add_argument(
        "--once",
        action="store_true",
        help="a single reading, no confirmation -- the old behaviour, for a caller that wants it",
    )
    s.set_defaults(func=cmd_settle)

    s = stateful("wait", "block until a running unit settles (herdr events, not polling)")
    s.add_argument("--timeout", type=int, default=1800, help="seconds to wait at most")
    s.add_argument(
        "--interval",
        type=int,
        default=20,
        help="seconds between confirming idle readings (default 20)",
    )
    s.add_argument(
        "--confirmations",
        type=confirmation_count,
        default=2,
        help="agreeing idle/done observations required before returning (default 2)",
    )
    s.set_defaults(func=cmd_wait)

    s = stateful("merge", "take a merge turn per ready unit onto the run's parent branch")
    s.add_argument(
        "--clean",
        action="store_true",
        help="after a successful turn, reap the units the merged rule allows; never their branches",
    )
    s.add_argument("--remote", default="origin", help="remote to compare against (default origin)")
    s.add_argument(
        "--compare",
        default="main",
        help="the branch a merge may never take backwards (default main)",
    )
    s.set_defaults(func=cmd_merge)

    s = stateful("clean", "close tabs, remove worktrees, and retire this run's workspaces")
    s.add_argument(
        "--merged",
        action="store_true",
        help="only DONE units whose commits are all on the parent branch",
    )
    s.add_argument("--branches", action="store_true", help="delete the unit branches too")
    s.add_argument(
        "--remote",
        default="origin",
        help="remote name for branch cleanup (default origin)",
    )
    s.set_defaults(func=cmd_clean)

    s = stateful("check", "report where the run record and the repository disagree")
    s.set_defaults(func=cmd_check)

    s = stateful("diff", "what a unit actually changed: merge base to its branch, nothing else")
    s.add_argument(
        "unit",
        nargs="?",
        help="unit to show; omit for a --stat summary of every unit with a branch",
    )
    s.add_argument(
        "--stat", action="store_true", help="print the stat summary instead of the full patch"
    )
    s.set_defaults(func=cmd_diff)

    s = stateful("adopt", "write units for run branches the table does not know")
    s.add_argument(
        "--yes", action="store_true", help="write the discovered units into the run record"
    )
    s.set_defaults(func=cmd_adopt)

    s = stateful(
        "park",
        "record a typed parked state for a unit whose push succeeded but PR creation blocked",
    )
    s.add_argument("--unit", required=True, help="unit name to park")
    s.add_argument(
        "--evidence",
        "--error",
        dest="evidence",
        required=True,
        help="failure evidence or error message explaining why PR creation was blocked",
    )
    s.add_argument("--remote", default="origin", help="remote name (default origin)")
    s.add_argument("--base", help="authoritative base branch (defaults to run branch, or main)")
    s.set_defaults(func=cmd_park)

    s = stateful(
        "resume",
        "idempotently open or adopt a pull request for a parked unit and continue the run",
    )
    s.add_argument("--unit", required=True, help="parked unit name to resume")
    s.add_argument("--title", help="PR title (default derived from unit name/task)")
    s.add_argument("--body", help="PR body")
    s.add_argument("--base", help="authoritative base branch (defaults to recorded parked base)")
    s.add_argument(
        "--remote",
        default=None,
        help="remote name (defaults to recorded parked remote, or origin)",
    )
    s.set_defaults(func=cmd_resume)

    args = p.parse_args(argv)
    # Every record refusal reaches the operator as one line, never a traceback, and the exit codes
    # are the run record's own: 2 a refusal, 3 a version this Orchestrate does not know.
    try:
        return int(args.func(args))
    except UnknownRecordVersionError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except RecordError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
