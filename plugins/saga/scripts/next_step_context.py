#!/usr/bin/env python3
"""What, if anything, should be announced about this repository's run right now (issue #1029).

One rule, read by three callers: the session-start hook, the prompt-submission suggestion hook, and
the compaction spore's renderer. Writing the rule once is the point of the module — two readers of
the same field disagreeing about what "done" looks like is how the next stale-state bug gets
written (plan KTD5).

**The suppression rule (plan KTD1).** The run record says a step is finished by its ``next_step``
being the empty string. There is nothing else to read: the record's twelve top-level keys are
frozen on purpose (``run_record.TOP_LEVEL_KEYS``), so a ``closed_at`` or ``run_state`` key is not
available, and *inferring* doneness from ``review_cycles`` or ``units`` is exactly the kind of
inference over recorded state that produced the stale injection this module exists to prevent. So:

* no record for the issue            → announce nothing
* a record whose ``next_step`` is "" → announce nothing (the step is done, or the run is closed)
* anything unreadable                → announce nothing

**Why this is not a function on ``run_record`` (plan KTD2a).** ``saga_spore`` imports ``saga``, and
``saga`` imports ``run_record`` lazily. A resolver living in ``run_record`` that reached for
``saga_spore.resolve_active_saga`` would close the cycle ``run_record`` → ``saga_spore`` → ``saga``
→ ``run_record``. The lazy import would keep it from crashing, which is worse than crashing,
because the layering violation would survive unnoticed. ``run_record`` stays a leaf that knows
about storage and nothing about sessions.

**Never raises.** Every caller is a hook, and a hook that raises costs the operator a turn. Every
failure here is an absent answer.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_record  # noqa: E402  (after the sys.path shim, by design)

#: A branch whose name carries the issue it belongs to. ``issue/1029`` and ``issue/1029-some-slug``
#: both resolve to 1029; ``work/cp908-review`` and ``main`` resolve to nothing.
BRANCH_ISSUE_RE = re.compile(r"^issue/(\d+)(?:[-_/].*)?$")

#: The saga id shape the envelope store uses for issue-shaped work.
SAGA_ISSUE_PREFIX = "issue-"


def _git(args: list[str], cwd: Path) -> str | None:
    """Run a short read-only git command, or return ``None`` on any failure."""
    try:
        result = subprocess.run(  # noqa: S603  (fixed argv, no shell)
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:  # noqa: BLE001 — a hook never raises; absence is the answer
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def issue_from_active_saga(repo_root: Path) -> int | None:
    """The issue number of this worktree's active saga, or ``None``.

    Imported lazily so that a caller only pays for ``saga_spore`` (which pulls in ``outcome``,
    ``outcome_store`` and ``saga``) when the saga store actually exists.
    """
    try:
        import saga_spore  # noqa: PLC0415  (lazy by design — see the module docstring)

        box = saga_spore.resolve_active_saga(Path(repo_root))
    except Exception:  # noqa: BLE001
        return None
    if not box:
        return None
    saga_id = str(box.get("saga_id") or "")
    if not saga_id.startswith(SAGA_ISSUE_PREFIX):
        return None
    number = saga_id.removeprefix(SAGA_ISSUE_PREFIX)
    return int(number) if number.isdigit() else None


def issue_from_branch(repo_root: Path) -> int | None:
    """The issue number carried by the current branch name, or ``None``.

    ``symbolic-ref`` first, because it answers on an **unborn** branch — a repository whose branch
    is checked out but which carries no commit yet. ``rev-parse --abbrev-ref HEAD`` fails there,
    and prints the bare word ``HEAD`` on a detached head, neither of which is a branch name.
    """
    branch = _git(["symbolic-ref", "--short", "HEAD"], Path(repo_root)) or _git(
        ["rev-parse", "--abbrev-ref", "HEAD"], Path(repo_root)
    )
    if not branch or branch == "HEAD":
        return None
    match = BRANCH_ISSUE_RE.match(branch)
    return int(match.group(1)) if match else None


def resolve_issue(repo_root: Path) -> int | None:
    """Resolve which issue this repository's session is about, locally and without a network call.

    Two steps, in order (plan KTD2): this worktree's active saga, then the branch name.

    **The branch fallback is the ordinary path in a worktree, not the exceptional one.** The saga
    envelope store is per-worktree, while the run record store resolves from the git *common*
    directory and is therefore the primary checkout's for every worktree. A fresh worktree
    typically has no active saga of its own, and the branch name carries the whole answer.
    """
    return issue_from_active_saga(repo_root) or issue_from_branch(repo_root)


def next_step_for(repo_root: Path, *, store_root: Path | None = None) -> dict[str, Any] | None:
    """The announcement for *repo_root*, or ``None`` when there is nothing to announce.

    Returns ``{"issue", "next_step", "updated_at", "path"}``. ``None`` covers every suppressed
    case: no resolvable issue, no record, a record that cannot be read, and — the case this card
    exists for — a record whose ``next_step`` is empty because the step is done or the run closed.
    """
    issue = resolve_issue(Path(repo_root))
    if issue is None:
        return None
    try:
        resolved = (
            Path(store_root)
            if store_root is not None
            else run_record.resolve_store_root(Path(repo_root))
        )
        record = run_record.load(resolved, issue, warn=None)
    except Exception:  # noqa: BLE001
        return None
    if record is None:
        return None
    step = (record.next_step or "").strip()
    if not step:
        return None
    return {
        "issue": record.issue,
        "next_step": step,
        "updated_at": record.updated_at,
        "path": str(run_record.record_path(resolved, issue)),
    }


def render(announcement: dict[str, Any]) -> str:
    """Render an announcement as the one block a session-start hook injects."""
    lines = [
        f"[saga] Issue {announcement['issue']} has an active run. Its next step is:",
        f"  {announcement['next_step']}",
        f"  (recorded {announcement['updated_at']} in {announcement['path']})",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print this repository's announcement as JSON, or nothing. Always exits 0."""
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else Path.cwd()
    announcement = next_step_for(root)
    if announcement is not None:
        print(json.dumps(announcement, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
