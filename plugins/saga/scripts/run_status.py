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
first, then newest first. Under ``--all-active`` the resolved issue follows the same rule: a record
whose ``next_step`` is empty is a closed run and is left out, while a run only the envelope knows
(no record yet) stays. A run appears when either store knows it. Each row also carries where the
run stands for the run status band (issue #105): its build loop, its latest code review cycle
against the allowance and how many lenses met their bar, and ``band_line``, the one line every
harness shows. ``summary --band`` prints that line per run.

``review`` prints the latest code review result in the run record, lens by lens (issue #108): for
each selected lens whether it met its bar, did not, did not run, or ran without a bar to meet, and
its findings. Whether a lens met its bar comes from ``review_consensus.lens_outcomes_for_result``,
the rule the verdict itself applies, so a display never re-derives it. A lens that did not run is
never shown with a score.

``unit-for`` answers which unit row a session started in a directory is working (issue #107): the
row whose ``worktree`` (or ``merge_worktree``) is that directory's checkout, else the row whose
``branch`` is the branch checked out there, across every record in the store. The Claude Code
token-capture mod asks it once per session and records nothing when the answer is ``null``.

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
import review_consensus  # noqa: E402
import review_result  # noqa: E402
import review_state  # noqa: E402
import run_record  # noqa: E402

#: The version token of what ``summary --json`` prints.
SCHEMA = "run_status.v1"

#: The version token of what ``review --json`` prints.
REVIEW_SCHEMA = "review_view.v1"

#: How many of a lens's findings the lens list shows under its row.
TOP_FINDINGS = 3

#: A lens's state in the review view. ``not_run`` and ``unscored`` carry no score on purpose.
LENS_STATES = ("met", "not_met", "not_run", "unscored")

#: The reason given for a selected lens that has no row in the result.
REASON_NO_RESULT = "no result recorded"

#: The finding fields the review view carries, in the order a display reads them.
FINDING_FIELDS = (
    "id",
    "severity",
    "path",
    "line",
    "category",
    "dimension",
    "evidence",
    "impact",
    "status",
    "confidence",
)


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
    build_loop = review = None
    if record is not None:
        build_loop = build_loop_view(record, repo_root)
        review = review_progress(record, build_loop["unit"] if build_loop else None)
    row: dict[str, Any] = {
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
        "build_loop": build_loop,
        "review": review,
    }
    notice = None
    if record is not None and isinstance(record.admission, dict):
        stored = record.admission.get("setup_notice")
        if isinstance(stored, dict):
            notice = json.loads(json.dumps(stored))
    row["setup_notice"] = notice
    row["band_line"] = band_line(row)
    return row


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


def current_branch(repo_root: Path, *, runner: Callable[..., Any] | None = None) -> str:
    """The branch checked out at *repo_root*, or the empty string (detached, or not a checkout)."""
    run = runner if runner is not None else subprocess.run
    try:
        result = run(  # nosec B603 - fixed argv, no shell
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def _is_path(value: Any, target: Path) -> bool:
    """Whether *value* is an absolute path naming *target*; a relative or missing one never is."""
    if not isinstance(value, str) or not value.strip() or not Path(value).is_absolute():
        return False
    try:
        return Path(value).resolve() == target
    except OSError:
        return False


#: How a unit row matched, strongest first: its own worktree outranks a shared branch name.
MATCHED_BY: tuple[str, ...] = ("worktree", "branch")

#: The role a matched session records when its row names no staffing role: orchestrate's rows
#: carry ``role`` only for review-loop units, and the session in a unit's worktree is its worker.
DEFAULT_ROLE = "worker"

#: Orchestrate's review-loop roles (``Unit.role``) are a different vocabulary from the staffing
#: roles ``usage add --role`` records and ``cost_report.py`` groups spend by, so each is mapped
#: to the staffing role whose work it does: a fixer or resolver edits code like a worker, and a
#: review controller or external reviewer reviews like a lens reviewer.
REVIEW_LOOP_ROLES: dict[str, str] = {
    "review-fixer": "worker",
    "downstream-resolver": "worker",
    "review-controller": "lens-reviewer",
    "external-reviewer": "lens-reviewer",
}


def staffing_roles() -> frozenset[str]:
    """The staffing role names ``staffing.json`` lists; empty when the registry is unreadable."""
    import bundled_fleet  # noqa: PLC0415  (loaded on use: nothing does I/O at import)

    staffing = bundled_fleet.load("staffing")
    try:
        return frozenset(staffing.roles())
    except staffing.StaffingError as exc:
        print(f"run_status: staffing roles unreadable: {exc}", file=sys.stderr)
        return frozenset()


def staffing_role(named: Any, known: frozenset[str]) -> str:
    """The staffing role a row's ``role`` key records as: mapped from a review-loop role, kept
    when *known* lists it, and otherwise ``worker``."""
    if not isinstance(named, str):
        return DEFAULT_ROLE
    role = REVIEW_LOOP_ROLES.get(named, named)
    return role if role in known else DEFAULT_ROLE


#: The role of a session in a unit's merge-turn worktree (``merge_worktree``, issue 1025).
MERGE_ROLE = "merging-worker"


def unit_for(store_root: Path, repo_root: Path, branch: str) -> dict[str, Any] | None:
    """The unit row a session at *repo_root* on *branch* is working, or ``None``.

    Every record in *store_root* is read; one this saga cannot read is skipped with one line on
    standard error, so a stale or foreign record never hides the unit. A row matches when its
    ``worktree`` is *repo_root* (role: the row's ``role`` as a staffing role, see
    ``staffing_role``, else ``worker``), when its
    ``merge_worktree`` is (role ``merging-worker``), or, failing both, when its ``branch`` is
    *branch*. Of several matches the strongest kind wins, then an active record (a non-empty
    ``next_step``), then the newest ``updated_at``; ``ambiguous`` says there was more than one.
    """
    root = Path(store_root)
    if not root.is_dir():
        return None
    target = Path(repo_root).resolve()
    known = staffing_roles()
    found: list[tuple[int, bool, str, dict[str, Any]]] = []
    for path in sorted(root.glob("issue-*.json")):
        number = path.stem.removeprefix("issue-")
        if not number.isdigit():
            continue
        try:
            record = run_record.load(root, int(number), warn=None)
        except run_record.RunRecordError as exc:
            print(f"run_status: skipped {path.name}: {exc}", file=sys.stderr)
            continue
        if record is None:
            continue
        for row in record.units:
            if not isinstance(row, dict):
                continue
            unit = run_record.unit_key(row)
            if not unit:
                continue
            role = staffing_role(row.get("role"), known)
            if _is_path(row.get("worktree"), target):
                how = "worktree"
            elif _is_path(row.get("merge_worktree"), target):
                how, role = "worktree", MERGE_ROLE
            elif branch and row.get("branch") == branch:
                how = "branch"
            else:
                continue
            found.append(
                (
                    MATCHED_BY.index(how),
                    not record.next_step.strip(),
                    record.updated_at,
                    {
                        "issue": record.issue,
                        "unit": unit,
                        "role": role,
                        "matched_by": how,
                        "record_path": str(run_record.record_path(root, record.issue)),
                        "store_root": str(root),
                    },
                )
            )
    if not found:
        return None
    # Strongest kind first, then active before finished, then newest: sort the time descending.
    found.sort(key=lambda item: item[2], reverse=True)
    found.sort(key=lambda item: (item[0], item[1]))
    return {**found[0][3], "ambiguous": len(found) > 1}


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
    if all_active:
        # ``next_step_context`` treats an empty next step as a closed run: announce nothing. A
        # checkout left on its ``issue/N`` branch must not keep a closed run on the band. A row
        # with no record (``record_path`` null) is a run the envelope alone knows, so it stays.
        runs = [row for row in runs if row["record_path"] is None or row["next_step"].strip()]
    return {"schema": SCHEMA, "repo_root": str(repo_root), "runs": runs}


def render_line(run: dict[str, Any]) -> str:
    """One run as one plain line: the fallback every other harness prints."""
    parts = [f"#{run['issue']}", run["phase"] or "no saga tick"]
    if run["next_step"]:
        parts.append(f"next: {run['next_step']}")
    parts.append(f"plan: {run['plan_path']}" if run["plan_path"] else "no plan recorded")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# ``review``: the latest code review result, lens by lens (issue #108)
# ---------------------------------------------------------------------------


def selected_lenses(record: run_record.RunRecord) -> list[str]:
    """The lenses admission selected for the run: always-on first, then the conditional ones.

    Read from ``run_configuration.applicable_lenses.value`` in the shape ``admission.py`` records
    (an ``always_on`` list and a ``conditional_applies`` mapping or list). Anything else selects
    nothing here; the review's own rows still show.
    """
    block = record.run_configuration.get("applicable_lenses")
    value = block.get("value") if isinstance(block, dict) else None
    if not isinstance(value, dict):
        return []
    lenses: list[str] = []
    always_on = value.get("always_on")
    if isinstance(always_on, list):
        lenses += [str(lens) for lens in always_on]
    applies = value.get("conditional_applies")
    if isinstance(applies, (dict, list)):
        lenses += sorted(str(lens) for lens in applies)
    return list(dict.fromkeys(lenses))


def latest_review(
    record: run_record.RunRecord, *, loop: str, unit: str | None = None
) -> dict[str, Any] | None:
    """The newest ``review_result.v2`` entry in *loop* (and for *unit*, when given), or ``None``.

    Entries are appended in the order the review wrote them, so the newest is the last match.
    Legacy ``review_result.v1`` entries are never chosen.
    """
    for entry in reversed(record.review_cycles):
        if not isinstance(entry, dict) or entry.get("schema") != review_result.RESULT_SCHEMA:
            continue
        if entry.get("loop") != loop:
            continue
        if unit is not None and entry.get("unit") != unit:
            continue
        return entry
    return None


def _finding_order(finding: dict[str, Any]) -> tuple[int, str, int, str]:
    """Most severe first, then by path and line."""
    severity = str(finding.get("severity", ""))
    rank = (
        review_result.SEVERITY_VOCABULARY.index(severity)
        if severity in review_result.SEVERITY_VOCABULARY
        else len(review_result.SEVERITY_VOCABULARY)
    )
    line = str(finding.get("line", ""))
    number = int(line) if line.isdigit() else sys.maxsize
    return (rank, str(finding.get("path", "")), number, line)


def _finding_view(finding: dict[str, Any]) -> dict[str, Any]:
    return {name: finding.get(name) for name in FINDING_FIELDS}


def _lens_state(outcome: review_consensus.LensOutcome) -> str:
    if outcome.usable:
        return "met" if outcome.met else "not_met"
    if outcome.reason == review_consensus.REASON_NOT_EXECUTED:
        return "not_run"
    return "unscored"


def lens_views(
    entry: dict[str, Any], selected: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One view per lens, and the findings no listed lens owns.

    The lenses are the result's rows in its order, then every selected lens the result has no row
    for, shown as ``not_run``. Only a ``met`` or ``not_met`` lens carries ``derived_overall``.
    """
    rows = {
        str(row.get("lens", "")): row
        for row in entry.get("per_lens_results") or []
        if isinstance(row, dict)
    }
    findings = sorted(
        (f for f in entry.get("findings") or [] if isinstance(f, dict)), key=_finding_order
    )
    states: list[tuple[str, str, str | None]] = [
        (outcome.lens_id, _lens_state(outcome), outcome.reason or None)
        for outcome in review_consensus.lens_outcomes_for_result(entry)
    ]
    shown = {lens for lens, _, _ in states}
    states += [(lens, "not_run", REASON_NO_RESULT) for lens in selected if lens not in shown]

    views: list[dict[str, Any]] = []
    for lens, state, reason in states:
        owned = [_finding_view(f) for f in findings if str(f.get("lens", "")) == lens]
        overall = rows.get(lens, {}).get("derived_overall") if state in ("met", "not_met") else None
        views.append(
            {
                "lens": lens,
                "state": state,
                "reason": reason,
                "derived_overall": overall,
                "finding_count": len(owned),
                "top": owned[:TOP_FINDINGS],
                "findings": owned,
            }
        )
    listed = {view["lens"] for view in views}
    unattributed = [_finding_view(f) for f in findings if str(f.get("lens", "")) not in listed]
    return views, unattributed


def review_view(
    store_root: Path,
    repo_root: Path,
    *,
    issue: int | None = None,
    unit: str | None = None,
    loop: str = review_result.LOOP_CODE_REVIEW,
    resolve: Callable[[Path], int | None] = next_step_context.resolve_issue,
) -> dict[str, Any]:
    """The ``review_view.v1`` document ``review`` prints. ``review`` is null without a result.

    Raises the loader's errors as :func:`run_view` does.
    """
    resolved = issue if issue is not None else resolve(Path(repo_root))
    view: dict[str, Any] = {
        "schema": REVIEW_SCHEMA,
        "repo_root": str(repo_root),
        "issue": resolved,
        "record_path": None,
        "legacy_entries": 0,
        "review": None,
    }
    if resolved is None:
        return view
    record = run_record.load(store_root, resolved, warn=None)
    if record is None:
        return view
    view["record_path"] = str(run_record.record_path(store_root, resolved))
    view["legacy_entries"] = len(review_result.legacy_entries(record))
    # The review-state document wins when the redesign's runs exist; the
    # ``review_result.v2`` reader below stays for older records until C10b
    # deletes it. The document is card-level, so --unit/--loop do not filter it.
    if any(
        isinstance(entry, dict) and entry.get("kind") == review_state.KIND_REVIEW_RUN
        for entry in record.review_cycles
    ):
        view["review"] = state_review_view(record)
        return view
    entry = latest_review(record, loop=loop, unit=unit)
    if entry is None:
        return view
    lenses, unattributed = lens_views(entry, selected_lenses(record))
    view["review"] = {
        "unit": entry.get("unit"),
        "cycle": entry.get("cycle"),
        "loop": entry.get("loop"),
        "revision": entry.get("revision"),
        "outcome": entry.get("outcome"),
        "reason": entry.get("reason") or None,
        "lenses": lenses,
        "unattributed_findings": unattributed,
        "advisory_count": len(entry.get("advisory_findings") or []),
        "duplicate_count": len(entry.get("duplicate_findings") or []),
    }
    return view


#: How each state reads in the plain table and in the pane.
STATE_WORDS = {"met": "met", "not_met": "not met", "not_run": "not run", "unscored": "unscored"}


def _finding_line(finding: dict[str, Any]) -> str:
    return f"{finding['severity']} {finding['path']}:{finding['line']} {finding['category']}"


def state_review_view(record: run_record.RunRecord) -> dict[str, Any]:
    """The latest review from the review-state document (issue 164).

    No envelope is read here — ``review`` stays offline — so the merge display
    cannot know the merge setting and says so rather than guessing it.
    """
    document = review_state.build_document(record, None)
    runs = review_state.review_runs(record)
    newest = runs[-1]
    blocking = document["merge_blocking"]
    return {
        "state_schema": review_state.SCHEMA,
        "round": document["round"],
        "loop": review_state.KIND_REVIEW_RUN,
        "revision": newest.get("head"),
        "outcome": "blocked" if blocking else "clear",
        "lenses": document["lenses"],
        "pending_choices": document["pending_choices"],
        "merge": document["merge"],
        # The whole document, for the panes (issue 165): they read it only
        # through this view, never by running the review-state script.
        "state": document,
    }


def render_review(view: dict[str, Any]) -> list[str]:
    """The review as a fixed-width table: the fallback every other harness prints."""
    review = view["review"]
    if review is None:
        which = f"#{view['issue']}" if view["issue"] is not None else "this checkout"
        return [f"run_status: no review result recorded for {which}"]
    if isinstance(review, dict) and "state_schema" in review:
        return render_state_review(view)
    header = (
        f"#{view['issue']} · {review['unit']} · cycle {review['cycle']} · {review['loop']} · "
        f"{review['outcome']} · {str(review['revision'])[:12]}"
    )
    lines = [header]
    width = max([len("lens"), *(len(lens["lens"]) for lens in review["lenses"])])
    lines.append(f"{'lens':<{width}}  {'state':<8}  findings")
    for lens in review["lenses"]:
        reason = f"  ({lens['reason']})" if lens["state"] in ("not_run", "unscored") else ""
        lines.append(
            f"{lens['lens']:<{width}}  {STATE_WORDS[lens['state']]:<8}  "
            f"{lens['finding_count']}{reason}"
        )
        lines += [f"  {_finding_line(finding)}" for finding in lens["top"]]
    if review["unattributed_findings"]:
        lines.append(f"other findings: {len(review['unattributed_findings'])}")
    return lines


def render_state_review(view: dict[str, Any]) -> list[str]:
    """The review-state document as a table plus its numbered questions."""
    review = view["review"]
    lines = [
        f"#{view['issue']} · round {review['round']} · {review['loop']} · "
        f"{review['outcome']} · {str(review['revision'])[:12]}"
    ]
    width = max([len("lens"), *(len(str(lens["lens"])) for lens in review["lenses"])])
    lines.append(f"{'lens':<{width}}  {'grade':<5}  blocking  fix later")
    for lens in review["lenses"]:
        lines.append(
            f"{str(lens['lens']):<{width}}  {str(lens['grade']):<5}  "
            f"{lens['blocking']:<8}  {lens['fix_later']}"
        )
    for number, key in enumerate(review["pending_choices"], start=1):
        lines.append(f"Q{number}. {key}")
    merge = review["merge"]
    lines.append(f"Merge: {'waiting' if merge['waiting'] else 'free to proceed'} — {merge['reason']}")
    return lines


# ---------------------------------------------------------------------------
# Where a run stands, for the run status band (issue #105)
# ---------------------------------------------------------------------------

#: The repair allowances the lifecycle defaults to when the run configuration names none.
DEFAULT_STANDARD_ALLOWANCE = 3
DEFAULT_ESCALATED_ALLOWANCE = 2

#: How much of ``next_step`` stands in for the phase when no saga envelope names one.
PHASE_FALLBACK_CHARS = 40

#: The result arrays of one build-loop iteration (``references/mechanical-baseline.md``).
ITERATION_RESULT_KEYS = ("baseline", "functional_checks", "scenario_smoke")


def _same_path(left: Any, right: Path) -> bool:
    if not isinstance(left, str) or not left.strip():
        return False
    try:
        return Path(left).resolve() == Path(right).resolve()
    except (OSError, RuntimeError):
        return False


def _iteration_counts(iteration: dict[str, Any]) -> tuple[int, int]:
    """How many checks of *iteration* failed, and how many could not execute.

    The preview counts as one more check. ``could-not-execute`` is never folded into ``fail``: an
    environment problem is not a defect in the code (mechanical-baseline.md, "The three statuses").
    """
    statuses: list[str] = []
    for key in ITERATION_RESULT_KEYS:
        results = iteration.get(key)
        if isinstance(results, list):
            statuses += [str(r.get("status", "")) for r in results if isinstance(r, dict)]
    preview = iteration.get("preview")
    if isinstance(preview, dict):
        statuses.append(str(preview.get("status", "")))
    failing = sum(1 for status in statuses if status == "fail")
    unexecuted = sum(1 for status in statuses if status == "could-not-execute")
    return failing, unexecuted


def _last_iteration(row: dict[str, Any]) -> dict[str, Any] | None:
    block = row.get("build_loop")
    iterations = block.get("iterations") if isinstance(block, dict) else None
    if not isinstance(iterations, list):
        return None
    entries = [entry for entry in iterations if isinstance(entry, dict)]
    return entries[-1] if entries else None


def build_loop_view(record: run_record.RunRecord, checkout: Path) -> dict[str, Any] | None:
    """Where the run's build loop stands, or ``None`` when no unit has run it.

    One unit is described when its row's ``worktree`` is *checkout*, or when it is the only unit
    with a build loop: its latest iteration's number, failing and unexecuted checks, and whether it
    was green. Otherwise the view counts the units whose latest iteration was green, and ``unit``
    and the iteration fields are ``None``.
    """
    looped = [
        (row, last)
        for row in record.units
        if isinstance(row, dict) and (last := _last_iteration(row)) is not None
    ]
    if not looped:
        return None
    mine = [pair for pair in looped if _same_path(pair[0].get("worktree"), checkout)]
    chosen = mine[0] if mine else (looped[0] if len(looped) == 1 else None)
    view: dict[str, Any] = {
        "unit": None,
        "pass": None,
        "failing": None,
        "could_not_execute": None,
        "green": None,
        "units_total": len(looped),
        "units_green": sum(1 for _, last in looped if last.get("green") is True),
    }
    if chosen is not None:
        row, last = chosen
        failing, unexecuted = _iteration_counts(last)
        number = last.get("iteration")
        view.update(
            unit=run_record.unit_key(row) or None,
            failing=failing,
            could_not_execute=unexecuted,
            green=last.get("green") is True,
        )
        view["pass"] = number if isinstance(number, int) else None
    return view


def _allowance(record: run_record.RunRecord, key: str, fallback: int) -> int:
    """A cycle allowance from the run configuration (``{"value": n}`` or a bare number)."""
    entry = record.run_configuration.get(key)
    raw = entry.get("value") if isinstance(entry, dict) else entry
    if isinstance(raw, bool):
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value >= 0 else fallback


def state_review_progress(record: run_record.RunRecord) -> dict[str, Any] | None:
    """The code-review round and per-lens grades from the review-state document.

    Built offline with no envelope, like the review view: only the round and
    the stored grades are read, so the merge setting is never needed. The
    old-shape keys stay, unset, so every reader of this view keeps its shape.
    """
    document = review_state.build_document(record, None)
    if document["round"] is None:
        return None
    standard = _allowance(record, "standard_cycle_allowance", DEFAULT_STANDARD_ALLOWANCE)
    escalated = _allowance(record, "escalated_cycle_allowance", DEFAULT_ESCALATED_ALLOWANCE)
    return {
        "unit": None,
        "cycle": None,
        "standard_allowance": standard,
        "escalated_allowance": escalated,
        "is_escalated": False,
        "outcome": None,
        "lenses_met": 0,
        "lenses_total": 0,
        "lenses_not_run": 0,
        "round": document["round"],
        "grades": [
            {"lens": lens["lens"], "grade": lens["grade"]} for lens in document["lenses"]
        ],
    }


def review_progress(record: run_record.RunRecord, unit: str | None) -> dict[str, Any] | None:
    """The latest code review cycle against its allowance, and how many lenses met their bar.

    The entry is *unit*'s latest ``review_result.v2`` code review when it has one, else the run's
    latest. Whether a lens met its bar is the verdict's own rule, through :func:`lens_views`; a
    selected lens with no row counts in the total as not run. A record with C1 review runs takes
    the state branch instead: the round and grades from the review-state document.
    """
    if any(
        isinstance(entry, dict) and entry.get("kind") == review_state.KIND_REVIEW_RUN
        for entry in record.review_cycles
    ):
        return state_review_progress(record)
    loop = review_result.LOOP_CODE_REVIEW
    entry = latest_review(record, loop=loop, unit=unit) if unit else None
    if entry is None:
        entry = latest_review(record, loop=loop)
    if entry is None:
        return None
    lenses, _ = lens_views(entry, selected_lenses(record))
    standard = _allowance(record, "standard_cycle_allowance", DEFAULT_STANDARD_ALLOWANCE)
    escalated = _allowance(record, "escalated_cycle_allowance", DEFAULT_ESCALATED_ALLOWANCE)
    cycle = entry.get("cycle")
    cycle = cycle if isinstance(cycle, int) and not isinstance(cycle, bool) else None
    return {
        "unit": entry.get("unit"),
        "cycle": cycle,
        "standard_allowance": standard,
        "escalated_allowance": escalated,
        "is_escalated": cycle is not None and cycle > standard,
        "outcome": entry.get("outcome"),
        "lenses_met": sum(1 for lens in lenses if lens["state"] == "met"),
        "lenses_total": len(lenses),
        "lenses_not_run": sum(1 for lens in lenses if lens["state"] == "not_run"),
        "round": None,
        "grades": [],
    }


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _build_loop_part(view: dict[str, Any]) -> str:
    if view["unit"] is None or view["pass"] is None:
        return f"build loop {view['units_green']}/{view['units_total']} units green"
    part = f"build loop pass {view['pass']}"
    if view["green"]:
        return f"{part}, green"
    details = []
    if view["failing"]:
        details.append(f"{view['failing']} failing")
    if view["could_not_execute"]:
        details.append(f"{view['could_not_execute']} could not run")
    return f"{part}, {', '.join(details) if details else 'not green'}"


def _review_part(view: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    if view.get("round") is not None:
        parts.append(f"review round {view['round']}")
        pairs = ", ".join(f"{grade['lens']} {grade['grade']}" for grade in view.get("grades") or [])
        if pairs:
            parts.append(pairs)
        return parts
    if view["cycle"] is not None:
        if view["is_escalated"]:
            budget = view["standard_allowance"] + view["escalated_allowance"]
            parts.append(f"review cycle {view['cycle']}/{budget} (escalated)")
        else:
            parts.append(f"review cycle {view['cycle']}/{view['standard_allowance']}")
    if view["lenses_total"]:
        parts.append(f"{view['lenses_met']}/{view['lenses_total']} lenses met")
    return parts


def band_line(row: dict[str, Any]) -> str:
    """One run as the status band's line, the single renderer every harness shows.

    ``#412 · work · build loop pass 3, 2 failing · review cycle 1/3 · 7/10 lenses met``. A part
    the run has no data for is left out. With no saga envelope the phase is the start of
    ``next_step``.
    """
    parts = [f"#{row['issue']}"]
    phase = row.get("phase")
    if not phase:
        step = " ".join(str(row.get("next_step") or "").split())
        if len(step) > PHASE_FALLBACK_CHARS:
            step = step[: PHASE_FALLBACK_CHARS - 1] + "…"
        phase = step
    if phase:
        parts.append(phase)
    if row.get("build_loop"):
        parts.append(_build_loop_part(row["build_loop"]))
    if row.get("review"):
        parts += _review_part(row["review"])
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
        help="Every run whose next step is not empty (the resolved issue too), the resolved issue first.",
    )
    summ.add_argument("--json", action="store_true", help=f"Print the {SCHEMA} document.")
    summ.add_argument(
        "--band",
        action="store_true",
        help="Print each run's status band line instead of its phase, next step and plan.",
    )
    rev = sub.add_parser("review", help="The latest code review result, lens by lens.")
    rev.add_argument("--issue", type=int, default=None, help="This issue (default: resolved).")
    rev.add_argument("--unit", default=None, help="This unit's history only.")
    rev.add_argument(
        "--loop",
        choices=review_result.LOOPS,
        default=review_result.LOOP_CODE_REVIEW,
        help="Which repair loop's history to read (default: code_review).",
    )
    rev.add_argument("--json", action="store_true", help=f"Print the {REVIEW_SCHEMA} document.")
    which = sub.add_parser(
        "unit-for",
        help="The unit row a session in --repo-root is working: by worktree, then by branch.",
    )
    which.add_argument("--json", action="store_true", help=f"Print the {SCHEMA} document.")
    return parser


def _cmd_unit_for(
    args: argparse.Namespace, repo_root: Path, runner: Callable[..., Any] | None
) -> int:
    """Print the matched unit, or ``null``. Outside a git checkout there is no unit: exit 0."""
    branch = current_branch(repo_root, runner=runner)
    try:
        store_root = (
            Path(args.store_root).resolve()
            if args.store_root
            else run_record.resolve_store_root(repo_root, runner=runner)
        )
    except run_record.StoreRootError:
        match = None
    else:
        match = unit_for(store_root, repo_root, branch)
    if args.json:
        view = {
            "schema": SCHEMA,
            "repo_root": str(repo_root),
            "branch": branch,
            "match": match,
        }
        print(json.dumps(view, indent=2, ensure_ascii=False))
    elif match is not None:
        print(f"#{match['issue']} unit {match['unit']} ({match['role']}, by {match['matched_by']})")
    else:
        print("run_status: no saga unit for this checkout")
    return 0


def main(argv: list[str] | None = None, *, runner: Callable[..., Any] | None = None) -> int:
    """Run the command line. Every loader call is inside this one catch, as in ``run_record``."""
    args = build_parser().parse_args(argv)
    try:
        repo_root = repo_toplevel(
            Path(args.repo_root) if args.repo_root else Path.cwd(), runner=runner
        )
        if args.command == "unit-for":
            return _cmd_unit_for(args, repo_root, runner)
        store_root = (
            Path(args.store_root).resolve()
            if args.store_root
            else run_record.resolve_store_root(repo_root, runner=runner)
        )
        if args.command == "review":
            view = review_view(
                store_root, repo_root, issue=args.issue, unit=args.unit, loop=args.loop
            )
        else:
            view = summary(store_root, repo_root, issue=args.issue, all_active=args.all_active)
    except run_record.UnknownRecordVersionError as exc:
        print(f"run_status: {exc}", file=sys.stderr)
        return 3
    except run_record.RunRecordError as exc:
        print(f"run_status: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(view, indent=2, ensure_ascii=False))
    elif args.command == "review":
        print("\n".join(render_review(view)))
    elif view["runs"]:
        for run in view["runs"]:
            print(run["band_line"] if args.band else render_line(run))
    else:
        print("run_status: no saga run for this checkout")
    return 0


if __name__ == "__main__":
    sys.exit(main())
