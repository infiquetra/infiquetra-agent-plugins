#!/usr/bin/env python3
"""One JSON run record per issue — the single place a run's state lives (issue #1023).

Saga keeps run state in six separate stores today: the run-fact ledger, the evidence-custody
ledger, the dispatch-settlement ledger, the effort ledger, the envelope tokens and the ship
receipts. None of them can answer "what is the next step for issue 1023?". This module is the one
file that can: the admission answers, the thirteen run-configuration parameters, the seven approval
boundaries, the roster with its pane identifiers, the units with their worktree, branch and
merge-turn state, the review results by cycle, and ``next_step``.

Four decisions in this file are contract for every later reader, and each is a decision the plan
argues for rather than a preference:

* **The store root is the git common directory's parent** (plan KTD1). ``git rev-parse
  --git-common-dir`` returns ``<primary>/.git`` from the primary checkout and the *same*
  ``<primary>/.git`` from every linked worktree, so one absolute path is resolved identically from
  anywhere. A repository-relative ``.claude/saga`` would resolve inside the worktree, where the
  git-ignored directory does not exist — the failure issue 886's fifth finding reported against the
  orchestrate plugin's ``.orchestrate/``, and the reason this is not a detail.
* **The version field is ``schema``, holding ``run_record.v1``** (plan KTD2). An unknown value is
  one line on standard error and exit 3 from the command line, never a traceback — issue 975's
  finding F124 is exactly that defect in the orchestrate run file.
* **Unknown top-level fields round-trip and are warned about by name** (plan KTD3), the way
  ``saga.py``'s ``Saga.extra`` already preserves unknown frontmatter. Issue 989's finding F138 is
  the silent-drop half of this.
* **Writes are an atomic replace and take no lock** (plan KTD4b). The parent issue 1018 forbids
  adding a lease, reservation or lock, and one coordinator owns one run record, so ``updated_at``
  is what a reader compares rather than a lock it takes.

House testability pattern, mirroring ``saga.py`` and ``outcome_store.py``: every filesystem
function takes its root as an explicit argument, ``now`` and ``runner`` are injectable, and nothing
does I/O at import.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - fixed argv, no shell
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))


#: The version token. The family name says *which* artifact this is, which a bare version number
#: does not — the convention ``plan_pre_answers.v1``, ``roles_index.v1`` and
#: ``lifecycle_snapshot.v1`` already follow in this repository.
SCHEMA = "run_record.v1"

#: Where the records live, relative to the PRIMARY CHECKOUT root (never to the process's working
#: directory — that is the bug, see the module docstring).
STORE_SUBPATH = Path(".claude/saga/runs")

#: The record's top-level key set, in write order. Fixed here so no later child of issue 1018
#: invents one. Anything else read off disk is an unknown field and is preserved under ``extra``.
TOP_LEVEL_KEYS: tuple[str, ...] = (
    "schema",
    "issue",
    "repo",
    "created_at",
    "updated_at",
    "admission",
    "run_configuration",
    "approval_scope",
    "roster",
    "units",
    "review_cycles",
    "next_step",
)

#: The thirteen run-configuration parameters of the software-development-lifecycle repository's
#: run model (``docs/lifecycle/run-model.md``, "Run configuration — what is chosen before the work
#: starts"), at the revision this parent is pinned to.
#:
#: These are NOT the thirteen ``required_fields`` of the ``orchestrator-to-controller`` contract,
#: which is a handoff MESSAGE shape carrying ``roster_hash``, ``executors_and_topology`` and
#: ``session_reset_authority``. Both sets number thirteen, both live in the same repository at the
#: same revision, and both look right — which is why
#: ``tests/test_run_record.py`` guards the distinction by name rather than by count.
RUN_CONFIGURATION_PARAMETERS: tuple[str, ...] = (
    "staffing_models_and_efforts",
    "concurrency_allocation",
    "standard_cycle_allowance",
    "escalated_cycle_allowance",
    "escalation_trigger",
    "nonproduction_destination",
    "unfinished_testing_response",
    "applicable_lenses",
    "per_lens_score_threshold",
    "mechanical_tool_baseline",
    "lens_execution_recovery",
    "repair_custody",
    "preflight_checks",
)

#: The names that belong to the run setup contract and must never appear above. A swap of one set
#: for the other is the most likely silent error in this schema, so the names are written down.
RUN_SETUP_CONTRACT_ONLY_FIELDS: tuple[str, ...] = (
    "approval_scope",
    "cycle_allowances",
    "destination",
    "exception_decisions",
    "executors_and_topology",
    "investigator_triggers",
    "models_and_efforts",
    "recovery_rules",
    "roster_hash",
    "session_reset_authority",
    "staffing_per_role",
)

#: The seven approval boundaries, verbatim from the lifecycle repository's escalations chapter and
#: from ``human_approval_state.approval_required_for`` in the vendored
#: ``plugins/mission-control/config/sdlc-schema.json``. They are constants here rather than a read
#: of that file because reading a run record must never fail because a sibling plugin is missing;
#: the test cross-checks them against the vendored schema so the two cannot drift.
APPROVAL_CATEGORIES: tuple[str, ...] = (
    "production changes",
    "destructive operations",
    "secrets or credential changes",
    "IAM or permission changes",
    "billing or cost-impacting actions",
    "external commitments",
    "major team or process authority changes",
)

#: Which actor chooses each parameter, per the run model's "Chosen by" column. Nine are the
#: Delivery Manager's at orchestration setup; four are the Planner's during planning.
PARAMETER_CHOSEN_BY: dict[str, str] = {
    "staffing_models_and_efforts": "delivery_manager",
    "concurrency_allocation": "delivery_manager",
    "standard_cycle_allowance": "delivery_manager",
    "escalated_cycle_allowance": "delivery_manager",
    "escalation_trigger": "delivery_manager",
    "nonproduction_destination": "delivery_manager",
    "unfinished_testing_response": "delivery_manager",
    "applicable_lenses": "planner",
    "per_lens_score_threshold": "planner",
    "mechanical_tool_baseline": "planner",
    "lens_execution_recovery": "delivery_manager",
    "repair_custody": "delivery_manager",
    "preflight_checks": "planner",
}

#: Where a filled value came from. ``operator`` is an answer given; everything else is a default.
VALUE_SOURCES: tuple[str, ...] = ("operator", "profile", "staffing", "lifecycle-default", "unset")


class RunRecordError(ValueError):
    """A refusal this module owns. The command line maps it to exit 2."""


class UnknownRecordVersionError(RunRecordError):
    """The record on disk carries a version this saga does not know. Exit 3, one line."""


class StoreRootError(RunRecordError):
    """The primary checkout's store root could not be resolved. Exit 2, one line."""


def _safe_session_name(name: str) -> str:
    """Reject a path-traversing or empty session identifier before it becomes a filename.

    Lived in ``outcome_store._safe_name`` until issue 1030 removed the outcome coordinator. The
    spore and the run record both key files by a caller-supplied id, so the check belongs with the
    module that owns the store root rather than in a sibling neither of them imports any more.
    """
    text = str(name).strip()
    if not text:
        raise StoreRootError("session_id must not be empty")
    if text in {".", ".."} or "/" in text or "\\" in text or "\x00" in text:
        raise StoreRootError(f"session_id {name!r} is not a safe path segment")
    return text


def _resolve_common_dir(repo_root: Path, *, runner: Callable[..., Any] | None = None) -> Path:
    """Resolve the repository's git **common** directory as an absolute path.

    ``git rev-parse --git-common-dir`` returns the shared git directory: ``.git`` in the primary
    checkout and that same absolute path from every linked worktree. Resolving it therefore yields
    one identical store root from anywhere, which is what lets a worktree read the record the
    primary checkout owns.

    This was `outcome_store.resolve_common_dir` until issue 1030 removed the outcome coordinator.
    It is defined here rather than imported because the run record is now its only consumer in this
    plugin -- the same choice `fleet_commons/audit_store.py` already made and documents, for the
    same reason: a shared primitive with one caller is just that caller's code.

    ``runner`` is resolved at call time, not bound as a default, so a test can monkeypatch
    ``run_record.subprocess.run`` and have it take effect here.
    """
    run = runner if runner is not None else subprocess.run
    try:
        result = run(  # nosec B603 - fixed argv, no shell
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise StoreRootError(f"could not run git to resolve the common dir: {exc}") from exc
    if result.returncode != 0:
        raise StoreRootError(
            f"git rev-parse --git-common-dir failed in {repo_root}: {result.stderr.strip()}"
        )
    raw = result.stdout.strip()
    if not raw:
        raise StoreRootError(f"git rev-parse --git-common-dir returned nothing in {repo_root}")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = Path(repo_root) / candidate
    return candidate.resolve()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(now: datetime) -> str:
    return now.isoformat()


def resolve_store_root(
    start: Path | None = None,
    *,
    runner: Callable[..., Any] | None = None,
) -> Path:
    """Return the absolute ``.claude/saga/runs`` directory of the PRIMARY checkout (KTD1).

    Identical from the primary checkout and from every linked worktree, because
    ``resolve_common_dir`` asks git for the *common* directory rather than the worktree's own.
    Refuses rather than guessing when the common directory is not a ``.git`` inside a checkout —
    writing the record somewhere no later reader will look is worse than stopping.
    """
    anchor = Path(start) if start is not None else Path.cwd()
    try:
        common = _resolve_common_dir(anchor, runner=runner)
    except StoreRootError:
        raise
    except Exception as exc:  # defensive: any other failure is still a store-root failure
        raise StoreRootError(
            f"could not resolve the git common directory from {anchor}: {exc}"
        ) from exc
    if common.name != ".git":
        raise StoreRootError(
            f"the git common directory {common} is not a '.git' inside a checkout, so the primary "
            "checkout root cannot be derived; pass --store-root explicitly"
        )
    return (common.parent / STORE_SUBPATH).resolve()


def record_path(store_root: Path, issue: int) -> Path:
    """Return the absolute path of *issue*'s record inside *store_root*."""
    return (Path(store_root) / f"issue-{int(issue)}.json").resolve()


def empty_run_configuration() -> dict[str, dict[str, Any]]:
    """The thirteen parameters, each unset, each already carrying who chooses it."""
    return {
        name: {"value": None, "chosen_by": PARAMETER_CHOSEN_BY[name], "source": "unset"}
        for name in RUN_CONFIGURATION_PARAMETERS
    }


def empty_approval_scope() -> dict[str, Any]:
    """The seven categories, each with no granted scope yet.

    ``None`` means "not answered"; the string ``"none"`` means the operator granted nothing in that
    category. The lifecycle repository treats an unscoped grant as a MISSING boundary, not a wide
    one, so the two have to be distinguishable.
    """
    return dict.fromkeys(APPROVAL_CATEGORIES)


def empty_admission() -> dict[str, Any]:
    """The admission block before any question has been answered.

    ``destination`` here is saga's own four-value routing intent (``plan-only``, ``pr``, ``merge``,
    ``nonprod-deploy``) — NOT the run configuration's ``nonproduction_destination``, which names
    which lower environment a run deploys to. Two different questions, one English word; the plan
    keeps them apart on purpose.
    """
    return {
        "card_validation": {"performed": False, "passed": None, "errors": []},
        "issue_review_checks": {},
        "answers": {},
        "pending_questions": [],
        "risk_tier": None,
        "risk_justification": None,
        "destination": None,
        "branch_preview": None,
        "main_consumed_directly": None,
        "change_shape": None,
    }


@dataclass(frozen=True)
class RunRecord:
    """One issue's run. Frozen — every mutation derives a new instance.

    ``extra`` preserves unknown top-level fields read off disk so a round trip never drops a field
    a newer writer added (KTD3).
    """

    issue: int
    repo: str = ""
    schema: str = SCHEMA
    created_at: str = ""
    updated_at: str = ""
    admission: dict[str, Any] = field(default_factory=empty_admission)
    run_configuration: dict[str, Any] = field(default_factory=empty_run_configuration)
    approval_scope: dict[str, Any] = field(default_factory=empty_approval_scope)
    roster: list[dict[str, Any]] = field(default_factory=list)
    units: list[dict[str, Any]] = field(default_factory=list)
    review_cycles: list[dict[str, Any]] = field(default_factory=list)
    next_step: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def to_dict(record: RunRecord) -> dict[str, Any]:
    """Render *record* as the on-disk mapping: the twelve keys in order, then any unknown ones."""
    payload: dict[str, Any] = {
        "schema": record.schema,
        "issue": record.issue,
        "repo": record.repo,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "admission": record.admission,
        "run_configuration": record.run_configuration,
        "approval_scope": record.approval_scope,
        "roster": record.roster,
        "units": record.units,
        "review_cycles": record.review_cycles,
        "next_step": record.next_step,
    }
    for key in sorted(record.extra):
        payload[key] = record.extra[key]
    return payload


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def from_dict(
    raw: dict[str, Any],
    *,
    path: Path | str = "<memory>",
    warn: Callable[[str], None] | None = _warn,
) -> RunRecord:
    """Build a record from *raw*, refusing an unknown version and preserving unknown fields.

    A MISSING known key is filled with its empty default rather than refused: that is how a record
    written before a consumer landed presents, and refusing it would make every later child's first
    read fail on a record this module wrote.
    """
    version = raw.get("schema")
    if version != SCHEMA:
        raise UnknownRecordVersionError(
            f"unknown record version {version!r} in {path}; this saga writes {SCHEMA}"
        )
    extra = {key: value for key, value in raw.items() if key not in TOP_LEVEL_KEYS}
    if extra and warn is not None:
        for key in sorted(extra):
            warn(
                f"run_record: unknown top-level field {key!r} in {path}; preserved unchanged "
                f"(this saga writes {SCHEMA})"
            )
    return RunRecord(
        issue=int(raw.get("issue", 0)),
        repo=str(raw.get("repo", "")),
        schema=SCHEMA,
        created_at=str(raw.get("created_at", "")),
        updated_at=str(raw.get("updated_at", "")),
        admission=raw.get("admission") or empty_admission(),
        run_configuration=raw.get("run_configuration") or empty_run_configuration(),
        approval_scope=raw.get("approval_scope") or empty_approval_scope(),
        roster=list(raw.get("roster") or []),
        units=list(raw.get("units") or []),
        review_cycles=list(raw.get("review_cycles") or []),
        next_step=str(raw.get("next_step", "")),
        extra=extra,
    )


def load(
    store_root: Path,
    issue: int,
    *,
    warn: Callable[[str], None] | None = _warn,
) -> RunRecord | None:
    """Read *issue*'s record from *store_root*, or ``None`` when there is none yet."""
    path = record_path(store_root, issue)
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunRecordError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise RunRecordError(f"{path} does not hold a JSON object")
    return from_dict(raw, path=path, warn=warn)


def save(
    store_root: Path,
    record: RunRecord,
    *,
    now: datetime | None = None,
) -> Path:
    """Write *record* into *store_root* with an atomic replace, and return the path (KTD4b).

    No lock, no lease, no reservation: the parent issue 1018 forbids adding one and one coordinator
    owns one record. ``updated_at`` is refreshed on every write so a reader can tell whether the
    copy it holds is the newest.
    """
    stamp = _timestamp(now or _utc_now())
    created = record.created_at or stamp
    payload = to_dict(RunRecord(**{**record.__dict__, "created_at": created, "updated_at": stamp}))
    path = record_path(store_root, record.issue)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def set_next_step(
    store_root: Path, issue: int, next_step: str, *, now: datetime | None = None
) -> Path:
    """Write *next_step* onto *issue*'s record, creating the record when there is none.

    The record's ``next_step`` is authoritative over the saga envelope's (plan KTD8a): the envelope
    log is append-only history whose older ticks are MEANT to hold stale values, while the record is
    the one file every role reads.
    """
    existing = load(store_root, issue, warn=None)
    record = existing or RunRecord(issue=int(issue))
    return save(store_root, RunRecord(**{**record.__dict__, "next_step": next_step}), now=now)


def get_next_step(store_root: Path, issue: int) -> str:
    """Return *issue*'s authoritative ``next_step``, or the empty string when there is no record."""
    record = load(store_root, issue, warn=None)
    return record.next_step if record is not None else ""


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_record.py",
        description="Read one issue's saga run record.",
    )
    parser.add_argument(
        "--store-root",
        default=None,
        help="Override the resolved store directory (tests and cross-checkout use).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="Print the record as JSON.")
    show.add_argument("issue", type=int)

    where = sub.add_parser("path", help="Print the record's absolute path.")
    where.add_argument("issue", type=int)

    return parser


def _store_root(args: argparse.Namespace) -> Path:
    if args.store_root:
        return Path(args.store_root).resolve()
    return resolve_store_root()


def _cmd_show(args: argparse.Namespace) -> int:
    root = _store_root(args)
    record = load(root, args.issue)
    if record is None:
        print(
            f"run_record: no record for issue {args.issue} at {record_path(root, args.issue)}",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(to_dict(record), indent=2, ensure_ascii=False))
    return 0


def _cmd_path(args: argparse.Namespace) -> int:
    print(record_path(_store_root(args), args.issue))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line. Every loader call is inside this one catch (KTD2).

    Issue 975's finding F124 is precisely the opposite arrangement: ``main`` called the subcommand
    bare while every subcommand opened with a load, so a known refusal reached the user as a
    six-frame traceback.
    """
    args = build_parser().parse_args(argv)
    handlers = {"show": _cmd_show, "path": _cmd_path}
    try:
        return handlers[args.command](args)
    except UnknownRecordVersionError as exc:
        print(f"run_record: {exc}", file=sys.stderr)
        return 3
    except RunRecordError as exc:
        print(f"run_record: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
