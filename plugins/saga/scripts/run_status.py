#!/usr/bin/env python3
"""A read-only view of this checkout's saga runs, for displays (issue #104).

Saga's scripts own its state, and a display never re-derives it: a Claude Code mod, a status line
or an operator at a shell on another harness runs this script and shows what it prints. It writes
nothing. Two stores feed it, and neither is complete alone:

* the **run record** (``run_record.py``), one JSON file per issue in the primary checkout's
  ``.claude/saga/runs/``, carries ``next_step`` and ``updated_at``;
* the **saga envelope** (``saga.py``), the per-worktree tick log under ``.claude/saga/sagas/``,
  carries the lifecycle phase and the plan path. The run record has no plan path
  (``run_record.TOP_LEVEL_KEYS`` is frozen on purpose), so the plan viewer reads it here.

``summary`` prints one row per run. With ``--issue`` it is that issue; with neither flag it is the
issue ``next_step_context.resolve_issue`` finds (this worktree's active saga, then an ``issue/N``
branch); ``--all-active`` lists every record whose ``next_step`` is not empty, the resolved issue
first, then newest first. A run appears when either store knows it.

Exit codes mirror ``run_record.py``: 0 with a (possibly empty) list, 2 for a refusal (the store
root cannot be resolved, a record is not valid JSON), 3 for a record version this saga does not
write. Each refusal is one line on standard error, never a traceback.

House testability pattern: the store root and the repository root are arguments, the git runner is
injectable, and nothing does I/O at import.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - fixed argv, no shell
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import next_step_context  # noqa: E402  (after the sys.path shim, by design)
import run_record  # noqa: E402

#: The version token of what ``summary --json`` prints.
SCHEMA = "run_status.v1"


def repo_toplevel(start: Path, *, runner: Callable[..., Any] | None = None) -> Path:
    """The checkout's top level from *start*, or *start* itself outside a git checkout.

    The envelope store sits at ``<checkout>/.claude/saga``, so a session started in a subdirectory
    still finds it.
    """
    run = runner if runner is not None else subprocess.run
    try:
        result = run(  # nosec B603 - fixed argv, no shell
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return Path(start).resolve()
    top = (result.stdout or "").strip() if result.returncode == 0 else ""
    return Path(top).resolve() if top else Path(start).resolve()


def envelope_view(repo_root: Path, issue: int) -> dict[str, Any] | None:
    """The phase and plan path of *issue*'s latest saga tick in *repo_root*, or ``None``.

    An envelope that cannot be read counts as absent: the run record is the authority on the run,
    and the envelope only adds what it alone knows.
    """
    try:
        import saga  # noqa: PLC0415  (lazy: only a reader that wants the envelope pays for it)

        tick = saga.restore(Path(repo_root), saga.derive_saga_id("issue", str(issue)))
    except Exception:  # noqa: BLE001 — a display never fails over the envelope
        return None
    if tick is None:
        return None
    plan_path = (tick.plan_path or "").strip()
    plan_file = str((Path(repo_root) / plan_path).resolve()) if plan_path else None
    return {
        "phase": tick.lifecycle_phase or None,
        "plan_path": plan_path or None,
        "plan_file": plan_file,
    }


def run_view(store_root: Path, repo_root: Path, issue: int) -> dict[str, Any] | None:
    """One run's row, or ``None`` when neither the record nor the envelope knows *issue*.

    Raises ``run_record.UnknownRecordVersionError`` and ``run_record.RunRecordError`` as the
    loader does; ``main`` maps them to exit 3 and 2.
    """
    record = run_record.load(store_root, issue, warn=None)
    envelope = envelope_view(repo_root, issue)
    if record is None and envelope is None:
        return None
    return {
        "issue": issue,
        "repo": record.repo if record is not None else None,
        "next_step": record.next_step if record is not None else "",
        "updated_at": record.updated_at if record is not None else None,
        "record_path": (
            str(run_record.record_path(store_root, issue)) if record is not None else None
        ),
        "phase": envelope["phase"] if envelope else None,
        "plan_path": envelope["plan_path"] if envelope else None,
        "plan_file": envelope["plan_file"] if envelope else None,
    }


def active_issues(store_root: Path) -> list[int]:
    """Every issue whose record in *store_root* has a non-empty ``next_step``, newest first.

    ``next_step_context`` defines active this way; a record this saga cannot read is left out of
    the listing (one line on standard error) rather than hiding every other run.
    """
    found: list[tuple[str, int]] = []
    root = Path(store_root)
    if not root.is_dir():
        return []
    for path in root.glob("issue-*.json"):
        number = path.stem.removeprefix("issue-")
        if not number.isdigit():
            continue
        try:
            record = run_record.load(root, int(number), warn=None)
        except run_record.RunRecordError as exc:
            print(f"run_status: skipped {path.name}: {exc}", file=sys.stderr)
            continue
        if record is not None and record.next_step.strip():
            found.append((record.updated_at, record.issue))
    found.sort(reverse=True)
    return [issue for _, issue in found]


def summary(
    store_root: Path,
    repo_root: Path,
    *,
    issue: int | None = None,
    all_active: bool = False,
    resolve: Callable[[Path], int | None] = next_step_context.resolve_issue,
) -> dict[str, Any]:
    """The ``run_status.v1`` document ``summary`` prints."""
    resolved = issue if issue is not None else resolve(Path(repo_root))
    issues: list[int] = [] if resolved is None else [resolved]
    if all_active:
        issues += [number for number in active_issues(store_root) if number != resolved]
    runs = [row for row in (run_view(store_root, repo_root, n) for n in issues) if row is not None]
    return {"schema": SCHEMA, "repo_root": str(repo_root), "runs": runs}


def render_line(run: dict[str, Any]) -> str:
    """One run as one plain line: the fallback every other harness prints."""
    parts = [f"#{run['issue']}", run["phase"] or "no saga tick"]
    if run["next_step"]:
        parts.append(f"next: {run['next_step']}")
    parts.append(f"plan: {run['plan_path']}" if run["plan_path"] else "no plan recorded")
    return " · ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_status.py",
        description="Print a read-only view of this checkout's saga runs.",
    )
    parser.add_argument(
        "--store-root",
        default=None,
        help="Override the resolved run-record directory (tests and cross-checkout use).",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="The checkout whose saga envelopes to read (default: the current directory's).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    summ = sub.add_parser("summary", help="One row per run: phase, next step and plan path.")
    summ.add_argument("--issue", type=int, default=None, help="This issue only.")
    summ.add_argument(
        "--all-active",
        action="store_true",
        help="Every run whose next step is not empty, the resolved issue first.",
    )
    summ.add_argument("--json", action="store_true", help=f"Print the {SCHEMA} document.")
    return parser


def main(argv: list[str] | None = None, *, runner: Callable[..., Any] | None = None) -> int:
    """Run the command line. Every loader call is inside this one catch, as in ``run_record``."""
    args = build_parser().parse_args(argv)
    try:
        repo_root = repo_toplevel(
            Path(args.repo_root) if args.repo_root else Path.cwd(), runner=runner
        )
        store_root = (
            Path(args.store_root).resolve()
            if args.store_root
            else run_record.resolve_store_root(repo_root, runner=runner)
        )
        view = summary(store_root, repo_root, issue=args.issue, all_active=args.all_active)
    except run_record.UnknownRecordVersionError as exc:
        print(f"run_status: {exc}", file=sys.stderr)
        return 3
    except run_record.RunRecordError as exc:
        print(f"run_status: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(view, indent=2, ensure_ascii=False))
    elif view["runs"]:
        for run in view["runs"]:
            print(render_line(run))
    else:
        print("run_status: no saga run for this checkout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
