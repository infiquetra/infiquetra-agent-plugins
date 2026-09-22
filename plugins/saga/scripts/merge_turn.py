#!/usr/bin/env python3
"""merge_turn — one worker merges at a time, over the run record (issue 1028).

The lifecycle repository's ``docs/process/parent-branch-integration.md`` describes the protocol
this module implements: exactly one worker holds the merge turn at any moment while implementation
stays parallel, the turn is ordinary execution state rather than a lock service, the merging worker
resolves straightforward conflicts as normal work, and ``main`` is re-integrated into the surviving
branches after each merge.

Four properties are load-bearing, and each one is a test:

* **Only the holder merges.** The holder is derived from the record's ``units[].merge_state``, and
  a row left at ``merging`` by a turn that died is RELEASED rather than trusted — a turn is live
  only while its own merge worktree is still registered and still holds an unfinished merge. That
  derivation is why no lock is needed: there is nothing to expire and nothing to steal.
* **The destination follows the record.** ``admission.destination`` decides whether a unit merges
  onto the run's parent issue branch or onto the default branch. Nothing else chooses.
* **A merge that would revert a newer comparison branch is refused by name.** The guard is
  fleet-core's ``merge_guard``, fetched first; a guard evaluated against a stale remote-tracking
  reference passes silently, which is the failure card 875 reported.
* **Both re-integrations happen and both are reported.** After a merge, the advanced destination
  branch is merged into every surviving unit branch, and where the destination is a parent issue
  branch the freshly fetched comparison branch is merged into it. A conflict in either is named and
  left for the worker who owns it.

**No lock, no lease, no reservation, no receipt.** The parent issue 1018 forbids adding one and
card 1028's stop condition says to stop and report if a merge-turn case would need one to be
correct. None of the cases here does: every refusal above is derived from git or from the record.

House pattern: pure functions over explicit values, an injectable runner so tests drive real git in
a temporary repository, lazy imports of the sibling modules, and no I/O at import.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

#: The three states a unit row's merge turn passes through. They are the values issue 1025
#: documented in ``references/run-record.md``; this module does not invent a fourth.
MERGE_READY = "ready"
MERGE_MERGING = "merging"
MERGE_MERGED = "merged"
MERGE_STATES = (MERGE_READY, MERGE_MERGING, MERGE_MERGED)

#: ``admission.destination`` values that merge onto the run's parent issue branch. ``plan-only``
#: merges nothing at all, and is refused by name rather than treated as a default.
PARENT_BRANCH_DESTINATIONS = ("pr", "merge", "nonprod-deploy")
NO_MERGE_DESTINATIONS = ("plan-only",)

Runner = Callable[..., Any]


class MergeTurnError(RuntimeError):
    """A refusal this module states in one line — never a traceback at the command line."""


# ---------------------------------------------------------------------------
# Sibling modules, resolved lazily
# ---------------------------------------------------------------------------


def _run_record() -> Any:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import run_record as _m  # noqa: PLC0415

    return _m


def _merge_guard() -> Any:
    """fleet-core's shared guard, through the vendored resolution shim.

    The guard lives in fleet-core rather than here because the orchestrate driver needs the same
    refusal, and two copies of a safety rule is how one of them stops matching the other.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import bundled_fleet  # noqa: PLC0415

    return bundled_fleet.load("merge_guard")


def _git(runner: Runner | None, argv: Sequence[str], *, timeout: int | None = 120) -> Any:
    call = runner if runner is not None else subprocess.run
    return call(list(argv), capture_output=True, text=True, timeout=timeout)


def _out(result: Any) -> str:
    return str(getattr(result, "stdout", "") or "").strip()


def _err(result: Any) -> str:
    return (
        str(getattr(result, "stderr", "") or "").strip()
        or str(getattr(result, "stdout", "") or "").strip()
        or "unknown error"
    )


def _ok(result: Any) -> bool:
    return getattr(result, "returncode", 1) == 0


# ---------------------------------------------------------------------------
# Reading the record
# ---------------------------------------------------------------------------


def unit_name(unit: dict[str, Any]) -> str:
    """A unit row's name, however the producer spelled it.

    Issue 1023 fixed the top-level key set and deliberately left a unit row's keys open, so the
    orchestrate driver writes ``name`` and a saga role may write ``unit_id``. Reading both is
    cheaper than making the two producers agree, and a row with neither is named by its index at
    the call site rather than silently skipped.
    """
    for key in ("name", "unit_id", "id"):
        value = unit.get(key)
        if value:
            return str(value)
    return ""


def destination_branch(record: Any, *, parent_branch: str, default_branch: str) -> str:
    """The branch a unit merges onto, from ``admission.destination``.

    A ``plan-only`` run merges nothing, and says so: falling back to the default branch because a
    destination said not to merge is how work lands somewhere nobody chose.
    """
    answers = (record.admission or {}).get("answers") or {}
    raw = answers.get("destination")
    value = str((raw or {}).get("value") if isinstance(raw, dict) else raw or "").strip()
    if value in NO_MERGE_DESTINATIONS:
        raise MergeTurnError(
            f"this run's destination is {value!r}, which merges nothing; no merge turn is taken"
        )
    if value and value not in PARENT_BRANCH_DESTINATIONS:
        raise MergeTurnError(
            f"unknown destination {value!r}; expected one of "
            f"{', '.join(PARENT_BRANCH_DESTINATIONS + NO_MERGE_DESTINATIONS)}"
        )
    return parent_branch or default_branch


def turn_is_live(unit: dict[str, Any], *, runner: Runner | None = None) -> bool:
    """Is this unit's recorded ``merging`` state a turn that is genuinely still in flight?

    Derived, never trusted. A row whose merge worktree is gone, or whose worktree holds no
    unfinished merge, is a turn that died: reporting it as live would block every later turn
    forever, with no expiry to rescue it because there is deliberately no lease here.
    """
    path = str(unit.get("merge_worktree") or "")
    if not path or not os.path.lexists(path):
        return False
    head = _git(runner, ["git", "-C", path, "rev-parse", "--verify", "--quiet", "MERGE_HEAD"])
    return _ok(head)


def holder(record: Any, *, runner: Runner | None = None) -> tuple[dict[str, Any] | None, list[str]]:
    """The unit whose turn is genuinely in flight, and the names of the rows released on the way.

    Releasing is a mutation of the passed rows, so the caller saves the record afterwards. That is
    the "inspect the actual Git and worker state first" step the lifecycle repository prescribes
    for a turn whose outcome is unknown.
    """
    released: list[str] = []
    live: dict[str, Any] | None = None
    for index, unit in enumerate(record.units):
        if str(unit.get("merge_state") or MERGE_READY) != MERGE_MERGING:
            continue
        if turn_is_live(unit, runner=runner):
            live = unit
            continue
        unit["merge_state"] = MERGE_READY
        unit["merge_worktree"] = None
        released.append(unit_name(unit) or f"unit #{index}")
    return live, released


def find_unit(record: Any, name: str) -> dict[str, Any]:
    for unit in record.units:
        if unit_name(unit) == name:
            return unit
    known = ", ".join(sorted(filter(None, (unit_name(u) for u in record.units)))) or "none"
    raise MergeTurnError(f"no unit named {name!r} in this run record; it carries: {known}")


# ---------------------------------------------------------------------------
# Taking the turn
# ---------------------------------------------------------------------------


def take_turn(
    record: Any,
    name: str,
    *,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Give *name* the merge turn, or refuse by naming who holds it.

    Refusing by name matters more than refusing: "another unit is merging" sends the caller to
    guess, and the guess is usually to wait on a turn that died.
    """
    unit = find_unit(record, name)
    live, released = holder(record, runner=runner)
    if live is not None and unit_name(live) != name:
        raise MergeTurnError(
            f"{unit_name(live)} holds the merge turn and its merge is still in flight at "
            f"{live.get('merge_worktree')}; one worker merges at a time"
        )
    unit["merge_state"] = MERGE_MERGING
    return {"unit": name, "released": released, "merge_state": MERGE_MERGING}


def merge_unit(
    record: Any,
    name: str,
    *,
    repo_root: Path,
    parent_branch: str,
    remote: str = "origin",
    default_branch: str = "main",
    runner: Runner | None = None,
    worktree_root: Path | None = None,
) -> dict[str, Any]:
    """Take one merge turn for *name* and merge its branch onto the destination branch.

    The whole turn happens in a detached worktree created and removed inside it, which is issue
    1025's mechanism: the destination branch's own checkout is never disturbed, and a conflicting
    merge aborts somewhere nobody is working.
    """
    guard = _merge_guard()
    unit = find_unit(record, name)
    branch = str(unit.get("branch") or "")
    if not branch:
        raise MergeTurnError(f"unit {name!r} records no branch; there is nothing to merge")

    destination = destination_branch(
        record, parent_branch=parent_branch, default_branch=default_branch
    )
    take_turn(record, name, runner=runner)

    compare_ref = f"{remote}/{default_branch}"
    refusal = guard.fetch_comparison_branch(
        remote, default_branch, cwd=str(repo_root), runner=runner
    )
    if refusal is not None:
        unit["merge_state"] = MERGE_READY
        raise MergeTurnError(refusal)

    tip = _git(runner, ["git", "-C", str(repo_root), "rev-parse", destination])
    if not _ok(tip):
        unit["merge_state"] = MERGE_READY
        raise MergeTurnError(f"destination branch {destination!r} does not resolve: {_err(tip)}")
    destination_tip = _out(tip)

    base = Path(worktree_root) if worktree_root else Path(repo_root) / ".claude" / "merge-turns"
    turn_worktree = base / f"{name}-{destination_tip[:12]}"
    added = _git(
        runner,
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--detach",
            str(turn_worktree),
            destination_tip,
        ],
    )
    if not _ok(added):
        unit["merge_state"] = MERGE_READY
        raise MergeTurnError(
            f"cannot create the merge turn's worktree at {turn_worktree}: {_err(added)}"
        )
    unit["merge_worktree"] = str(turn_worktree)

    try:
        merged = _git(
            runner,
            ["git", "-C", str(turn_worktree), "merge", "--no-ff", "--no-edit", branch],
        )
        if not _ok(merged):
            _git(runner, ["git", "-C", str(turn_worktree), "merge", "--abort"])
            unit["merge_state"] = MERGE_READY
            unit["merge_worktree"] = None
            raise MergeTurnError(
                f"{name}: CONFLICT merging {branch} onto {destination}; the turn is released and "
                f"{destination} is untouched. Merge {destination} into {branch}, resolve it there, "
                "then take the turn again"
            )
        head = _git(runner, ["git", "-C", str(turn_worktree), "rev-parse", "HEAD"])
        if not _ok(head) or not _out(head):
            unit["merge_state"] = MERGE_READY
            unit["merge_worktree"] = None
            raise MergeTurnError(f"{name}: the merge result could not be read")
        merged_tip = _out(head)

        reverted = guard.regression_files(
            merged_tip, compare_ref, cwd=str(repo_root), runner=runner
        )
        if reverted:
            unit["merge_state"] = MERGE_READY
            unit["merge_worktree"] = None
            raise MergeTurnError(
                guard.refusal_for(reverted, branch=branch, compare_ref=compare_ref)
            )

        published = _git(
            runner,
            [
                "git",
                "-C",
                str(repo_root),
                "update-ref",
                f"refs/heads/{destination}",
                merged_tip,
                destination_tip,
            ],
        )
        if not _ok(published):
            unit["merge_state"] = MERGE_READY
            unit["merge_worktree"] = None
            raise MergeTurnError(
                f"{name}: publishing the merge onto {destination} failed, so nothing moved: "
                f"{_err(published)}"
            )
    finally:
        _git(
            runner,
            ["git", "-C", str(repo_root), "worktree", "remove", "--force", str(turn_worktree)],
        )

    unit["merge_state"] = MERGE_MERGED
    unit["merge_worktree"] = None
    unit["merged_tip"] = merged_tip

    reintegration = reintegrate(
        record,
        merged_unit=name,
        repo_root=repo_root,
        destination=destination,
        compare_ref=compare_ref,
        parent_branch=parent_branch,
        default_branch=default_branch,
        runner=runner,
    )
    return {
        "unit": name,
        "destination": destination,
        "merged_tip": merged_tip,
        "merge_state": MERGE_MERGED,
        "reintegration": reintegration,
    }


def reintegrate(
    record: Any,
    *,
    merged_unit: str,
    repo_root: Path,
    destination: str,
    compare_ref: str,
    parent_branch: str,
    default_branch: str,
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Both re-integrations the lifecycle repository asks for, each reported separately.

    They are two different merges and conflating them loses one: the destination branch reaching
    the lanes still running is what keeps parallel work current, and the comparison branch reaching
    the parent branch is what keeps the run from drifting behind what shipped elsewhere.

    What this does and does not do. A branch it can advance by a fast-forward it advances, because
    that changes nothing anyone wrote. A branch that needs a real merge it reports as ``pending``,
    with whether that merge will conflict, and leaves for the worker who owns it: a lane's branch
    is usually checked out in that worker's worktree, and merging into a branch under someone
    else's feet from inside a merge turn is how a turn quietly becomes an owner. Nothing is ever
    force-resolved, and nothing is skipped in silence.
    """
    into_units: list[dict[str, str]] = []
    for unit in record.units:
        name = unit_name(unit)
        branch = str(unit.get("branch") or "")
        if not branch or name == merged_unit:
            continue
        if str(unit.get("merge_state") or MERGE_READY) == MERGE_MERGED:
            continue
        into_units.append(
            _reintegrate_one(repo_root, into_branch=branch, from_ref=destination, runner=runner)
        )

    into_parent: dict[str, str] = {
        "branch": default_branch,
        "status": "skipped",
        "detail": f"the destination IS {default_branch}; there is nothing to re-integrate into it",
    }
    if parent_branch and destination == parent_branch:
        into_parent = _reintegrate_one(
            repo_root, into_branch=parent_branch, from_ref=compare_ref, runner=runner
        )
    return {"into_unit_branches": into_units, "into_parent_branch": into_parent}


def _reintegrate_one(
    repo_root: Path,
    *,
    into_branch: str,
    from_ref: str,
    runner: Runner | None = None,
) -> dict[str, str]:
    """Advance *into_branch* to *from_ref* when that is a fast-forward; otherwise report the work.

    ``git fetch . <from>:<into>`` is the one operation that advances a branch reference without
    needing it checked out and refuses rather than rewriting when the move is not a fast-forward.
    That refusal is the signal, not an error: it means the branch has commits of its own and owes a
    real merge.
    """
    row = {"branch": into_branch, "from": from_ref, "status": "", "detail": ""}
    already = _git(
        runner, ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", from_ref, into_branch]
    )
    if _ok(already):
        row["status"] = "current"
        row["detail"] = f"{into_branch} already contains {from_ref}"
        return row
    forwarded = _git(
        runner, ["git", "-C", str(repo_root), "fetch", ".", f"{from_ref}:{into_branch}"]
    )
    if _ok(forwarded):
        row["status"] = "fast-forwarded"
        row["detail"] = f"{into_branch} was advanced to {from_ref}"
        return row
    probe = _git(
        runner, ["git", "-C", str(repo_root), "merge-tree", "--write-tree", into_branch, from_ref]
    )
    row["status"] = "pending"
    row["detail"] = (
        f"{into_branch} has commits of its own, so {from_ref} needs a real merge by the worker "
        "who owns it" + ("" if _ok(probe) else f"; that merge CONFLICTS with {from_ref} today")
    )
    return row


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="The saga merge turn, over the run record.")
    parser.add_argument("--record", required=True, help="path to the run record JSON file")
    parser.add_argument("--repo-root", default=".", help="the repository the merge happens in")
    parser.add_argument("--parent-branch", default="", help="the run's parent issue branch")
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--default-branch", default="main")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_status = sub.add_parser("status", help="who holds the turn, and which rows were released")
    del p_status
    p_take = sub.add_parser("take", help="give one unit the merge turn")
    p_take.add_argument("--unit", required=True)
    p_merge = sub.add_parser("merge", help="take the turn and merge one unit's branch")
    p_merge.add_argument("--unit", required=True)
    p_merge.add_argument("--dry-run", action="store_true", help="print the turn and change nothing")
    return parser


def _load_record(path: Path) -> tuple[Any, Any, Path]:
    module = _run_record()
    store_root = path.parent
    issue = int(path.stem.rsplit("-", 1)[-1])
    record = module.load(store_root, issue, warn=None)
    if record is None:
        raise MergeTurnError(f"no run record at {path}")
    return module, record, store_root


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        module, record, store_root = _load_record(Path(args.record).resolve())
        if args.cmd == "status":
            live, released = holder(record)
            module.save(store_root, record)
            print(
                json.dumps(
                    {"holder": unit_name(live) if live else None, "released": released}, indent=1
                )
            )
            return 0
        if args.cmd == "take":
            result = take_turn(record, args.unit)
            module.save(store_root, record)
            print(json.dumps(result, indent=1))
            return 0
        if args.dry_run:
            destination = destination_branch(
                record,
                parent_branch=args.parent_branch,
                default_branch=args.default_branch,
            )
            unit = find_unit(record, args.unit)
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "unit": args.unit,
                        "branch": unit.get("branch"),
                        "destination": destination,
                        "compare_ref": f"{args.remote}/{args.default_branch}",
                    },
                    indent=1,
                )
            )
            return 0
        result = merge_unit(
            record,
            args.unit,
            repo_root=Path(args.repo_root).resolve(),
            parent_branch=args.parent_branch,
            remote=args.remote,
            default_branch=args.default_branch,
        )
        module.save(store_root, record)
        print(json.dumps(result, indent=1))
        return 0
    except MergeTurnError as exc:
        print(f"merge_turn: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
