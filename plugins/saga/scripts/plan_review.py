#!/usr/bin/env python3
"""Plan review in one pass: record the findings, answer each, gate on the check.

Issue #163 (card C12). ``/plan`` dispatches the plan reviewer once; the reviewer
reports C1 finding records and never edits the plan. This script owns everything
after that:

* ``record --issue N --plan P --findings F`` validates ``F`` as plan findings
  (subject ``plan``, ``section`` locations) through C1's validator and appends one
  entry to the run record's ``review_cycles`` with a fingerprint of the plan file.
  A second record on the unchanged plan is refused.
* ``answer --issue N --finding <id> (--fixed S | --rejected T)`` records the
  author's answer: ``S`` is the plan section changed, ``T`` the rejection reason.
  ``--fixed`` is accepted only if the plan changed since the review; the plan path
  is read from the stored entry, never from the caller.
* ``check --issue N`` exits 1 while any finding is unanswered or the
  acceptance-criteria mapping fails, and 0 otherwise, printing every rejection
  with its reason. Rejections never hold the run; a mapping gap clears only by
  editing the plan until the mapping passes.

The findings file holds a JSON list of finding records. A finding without an
``id`` gets the computed C1 identity filled in — a reviewer cannot mint a
SHA-256 by hand — and a handed-in identity that does not match is refused.

Exit codes are the ``functional_checks.py`` table exactly: 0 ok, 1 the check's
gate (a finding unanswered or the mapping failing), 2 any refusal or anything
that cannot run.

House testability pattern, mirroring ``build_loop.py``: every filesystem function
takes its path as an explicit argument, the issue-body reader is injectable, and
nothing does I/O at import.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_loop  # noqa: E402  (after the sys.path shim, by design)
import functional_checks  # noqa: E402
import parse_issue  # noqa: E402
import review_records  # noqa: E402
import run_record  # noqa: E402

#: The ``review_cycles`` loop value this module's entries carry.
LOOP = "plan_review"

#: Exit codes, the ``functional_checks.py`` table exactly.
EXIT_OK = functional_checks.EXIT_OK
EXIT_NOT_READY = functional_checks.EXIT_NOT_READY
EXIT_REFUSED = functional_checks.EXIT_REFUSED
EXIT_UNKNOWN_VERSION = functional_checks.EXIT_UNKNOWN_VERSION


class PlanReviewError(ValueError):
    """A refusal this module owns. The command line maps it to ``EXIT_REFUSED``."""


# ---------------------------------------------------------------------------
# Plan fingerprints and paths.
# ---------------------------------------------------------------------------


def fingerprint(plan: Path) -> str:
    """The SHA-256 of the plan file's bytes, hex. Missing file: a refusal."""
    if not plan.is_file():
        raise PlanReviewError(f"no plan at {plan}")
    return hashlib.sha256(plan.read_bytes()).hexdigest()


def reviewed_revision(plan: Path) -> str:
    """The commit the plan is reviewed at, or ``working tree`` when unknowable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=plan.resolve().parent,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "working tree"
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else "working tree"


def _primary_work_tree(record_file: Path, store_root: Path | None) -> Path | None:
    """The primary checkout above a store, or ``None`` when not derivable.

    A store root is ``<primary>/.claude/saga/runs`` (``references/run-record.md``),
    so the primary is three parents up. An explicit ``--record`` outside a store
    (the tests' tmp files) yields a meaningless climb, which simply never matches.
    """
    root = store_root if store_root is not None else record_file.parent
    parents = root.parents
    return parents[2] if len(parents) > 2 else None


def resolve_plan_path(
    stored: str, *, record_file: Path, store_root: Path | None = None
) -> Path:
    """Where the stored plan path resolves: as given, else under the primary tree.

    ``/work`` runs the check from another worktree, where a relative stored path
    may only exist under the primary checkout. A path found in neither place is a
    refusal naming it — never a pass.
    """
    given = Path(stored)
    candidates = [given if given.is_absolute() else Path.cwd() / given]
    primary = _primary_work_tree(record_file, store_root)
    if primary is not None and not given.is_absolute():
        candidates.append(primary / given)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise PlanReviewError(
        f"the reviewed plan {stored!r} is neither at its stored path nor under the "
        "primary checkout; record the review again at the plan's current path"
    )


# ---------------------------------------------------------------------------
# Findings.
# ---------------------------------------------------------------------------


def load_findings(path: Path) -> list[Any]:
    """The findings file: a JSON list of finding records."""
    if not path.is_file():
        raise PlanReviewError(f"no findings at {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PlanReviewError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise PlanReviewError(f"{path} must hold a JSON list of finding records")
    return raw


def prepare_findings(raw: Sequence[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Validate plan findings and fill computed identities; ``(findings, problems)``.

    A finding without an ``id`` gets ``finding_identity`` filled in when its lens,
    rule and location are present; a handed-in identity that mismatches is refused
    by the validator. Plan-review rules beyond C1: subject must be ``plan`` and
    every location a ``section`` scope. Duplicate identities in one record are
    refused, since answers key on them.
    """
    findings: list[dict[str, Any]] = []
    problems: list[str] = []
    for position, item in enumerate(raw, start=1):
        label = f"finding {position}"
        if not isinstance(item, Mapping):
            problems.append(f"{label}: each finding is a JSON object")
            continue
        finding = dict(item)
        if "id" not in finding and (
            isinstance(finding.get("rule"), Mapping)
            and isinstance(finding.get("location"), Mapping)
            and isinstance(finding.get("lens"), str)
        ):
            finding["id"] = review_records.finding_identity(
                finding["lens"], finding["rule"], finding["location"]
            )
        for problem in review_records.validate(finding):
            problems.append(f"{label}: {problem}")
        if finding.get("subject") != "plan":
            problems.append(f"{label}: subject must be \"plan\" for a plan review")
        location = finding.get("location")
        if isinstance(location, Mapping) and location.get("scope") != "section":
            problems.append(
                f"{label}: a plan finding's location names a plan section"
            )
        findings.append(finding)
    seen: dict[str, int] = {}
    for position, finding in enumerate(findings, start=1):
        identity = finding.get("id")
        if isinstance(identity, str) and identity:
            if identity in seen:
                problems.append(
                    f"finding {position}: identity {identity} is already used by "
                    f"finding {seen[identity]}"
                )
            else:
                seen[identity] = position
    return findings, problems


def plan_review_entries(record: run_record.RunRecord) -> list[dict[str, Any]]:
    """Every ``plan_review`` entry in ``review_cycles``, oldest first."""
    return [
        entry
        for entry in record.review_cycles
        if isinstance(entry, dict) and entry.get("loop") == LOOP
    ]


def unanswered(
    findings: Sequence[Mapping[str, Any]], answers: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The findings no answer names, in recorded order."""
    return [dict(f) for f in findings if f.get("id") not in answers]


# ---------------------------------------------------------------------------
# Record paths.
# ---------------------------------------------------------------------------


def record_path_for(
    record: str | None, issue: int | None, store_root: str | None
) -> tuple[Path, Path | None]:
    """The record path plus the store root behind it (``None`` when explicit)."""
    if record:
        return Path(record).resolve(), None
    if issue is None:
        raise PlanReviewError("name the record with --record <path> or --issue <N>")
    root = Path(store_root).resolve() if store_root else run_record.resolve_store_root()
    return run_record.record_path(root, issue), root


# ---------------------------------------------------------------------------
# The three subcommands.
# ---------------------------------------------------------------------------


def do_record(
    record_file: Path,
    plan: Path,
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Append one plan-review entry; refuse a second review of the same revision."""
    sha = fingerprint(plan)
    with run_record.file_lock(record_file):
        record = build_loop.load_record_file(record_file)
        entries = plan_review_entries(record)
        if entries and entries[-1].get("plan_sha256") == sha:
            raise PlanReviewError(
                "the plan is unchanged since the latest recorded review; answer its "
                "findings instead of recording the same revision again"
            )
        entry = {
            "loop": LOOP,
            "plan_path": str(plan),
            "plan_sha256": sha,
            "reviewed_revision": reviewed_revision(plan),
            "findings": findings,
            "answers": {},
        }
        record.review_cycles.append(entry)
        build_loop.save_record_file(record_file, record)
        return entry


def do_answer(
    record_file: Path,
    finding_id: str,
    *,
    fixed: str | None = None,
    rejected: str | None = None,
    store_root: Path | None = None,
) -> dict[str, Any]:
    """Answer every unanswered occurrence of *finding_id*; refuse the rest.

    The plan path comes from the newest entry holding the finding, never from
    the caller — a caller-supplied path would let any changed file stand in for
    the reviewed plan. The same finding may repeat across two reviews of a
    changed plan; one answer covers every still-open occurrence, so no occurrence
    is left unanswerable. ``--fixed`` is accepted only when the plan changed
    since the newest open occurrence's review.
    """
    if (fixed is None) == (rejected is None):
        raise PlanReviewError("answer with exactly one of --fixed or --rejected")
    if fixed is not None and not fixed.strip():
        raise PlanReviewError("--fixed names the plan section changed")
    if rejected is not None and not rejected.strip():
        raise PlanReviewError("--rejected needs a reason")
    with run_record.file_lock(record_file):
        record = build_loop.load_record_file(record_file)
        entries = plan_review_entries(record)
        holders = [
            entry
            for entry in entries
            if any(f.get("id") == finding_id for f in entry.get("findings", []))
        ]
        if not holders:
            raise PlanReviewError(f"no recorded finding {finding_id!r}")
        plan = resolve_plan_path(
            holders[-1].get("plan_path", ""),
            record_file=record_file,
            store_root=store_root,
        )
        sha = fingerprint(plan)
        open_holders = [
            entry for entry in holders if finding_id not in entry.get("answers", {})
        ]
        if not open_holders:
            raise PlanReviewError(f"finding {finding_id!r} is already answered")
        if fixed is not None and sha == open_holders[-1].get("plan_sha256"):
            raise PlanReviewError(
                f"the plan is unchanged since finding {finding_id!r} was recorded; "
                "fix the plan first"
            )
        stored = (
            {"verdict": "fixed", "section": fixed.strip()}
            if fixed is not None
            else {"verdict": "rejected", "reason": rejected.strip()}
        )
        for entry in open_holders:
            entry.setdefault("answers", {})[finding_id] = dict(stored)
        build_loop.save_record_file(record_file, record)
        return stored


def mapping_for(
    plan: Path,
    record: run_record.RunRecord | None,
    body: str,
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """The acceptance-criteria mapping for *plan* against the issue *body*."""
    parsed = functional_checks.read_plan(plan)
    criteria = parse_issue.acceptance_criteria(body)
    if not criteria:
        raise PlanReviewError(
            f"the issue has no ### {parse_issue.ACCEPTANCE_HEADING} section with "
            "items, so there is nothing to map the plan's checks to"
        )
    try:
        profile = build_loop.load_profile(repo_root)
    except build_loop.BuildLoopError as exc:
        raise PlanReviewError(str(exc)) from exc
    return functional_checks.map_criteria(
        parsed, criteria, waiver=functional_checks.waiver_for(record, profile, parsed)
    )


def check_state(
    record: run_record.RunRecord,
    mapping: dict[str, Any],
) -> dict[str, Any]:
    """Unanswered findings and rejections across every recorded review."""
    entries = plan_review_entries(record)
    open_findings: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    for entry in entries:
        answers = entry.get("answers", {})
        open_findings.extend(unanswered(entry.get("findings", []), answers))
        for finding in entry.get("findings", []):
            answer = answers.get(finding.get("id"))
            if isinstance(answer, Mapping) and answer.get("verdict") == "rejected":
                rejections.append(
                    {
                        "id": finding.get("id"),
                        "statement": finding.get("statement"),
                        "section": (finding.get("location") or {}).get("section"),
                        "reason": answer.get("reason"),
                    }
                )
    status = (
        functional_checks.STATUS_NOT_READY
        if open_findings or mapping["status"] == functional_checks.STATUS_NOT_READY
        else functional_checks.STATUS_READY
    )
    if mapping["status"] == functional_checks.STATUS_WAIVED and not open_findings:
        status = functional_checks.STATUS_WAIVED
    return {
        "status": status,
        "unanswered": [
            {
                "id": f.get("id"),
                "section": (f.get("location") or {}).get("section"),
                "statement": f.get("statement"),
            }
            for f in open_findings
        ],
        "rejections": rejections,
        "mapping": mapping,
    }


def format_check(state: dict[str, Any]) -> str:
    """The check's printout: what is open, then every rejection with its reason."""
    lines: list[str] = []
    if state["unanswered"]:
        lines.append(
            f"plan_review: {len(state['unanswered'])} finding(s) unanswered:"
        )
        for item in state["unanswered"]:
            lines.append(f"  unanswered: {item['id']} [{item['section']}] {item['statement']}")
    mapping = state["mapping"]
    if mapping["status"] == functional_checks.STATUS_NOT_READY:
        lines.append(functional_checks.format_mapping(mapping))
    elif mapping["status"] == functional_checks.STATUS_WAIVED:
        lines.append("plan_review: the mapping check was skipped (functional testing waived)")
    if state["status"] == functional_checks.STATUS_NOT_READY:
        return "\n".join(lines)
    if state["rejections"]:
        lines.append(
            f"plan_review: all findings answered; {len(state['rejections'])} rejection(s):"
        )
        for item in state["rejections"]:
            lines.append(f"  rejected: {item['statement']} — {item['reason']}")
    else:
        lines.append("plan_review: all findings answered; no rejections")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command line.
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plan_review.py",
        description=(
            "Record plan-review findings as C1 records, answer each, and gate on "
            "every finding answered plus the acceptance-criteria mapping."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Store one plan review's findings.")
    record.add_argument("--plan", required=True, help="The reviewed plan document.")
    record.add_argument("--findings", required=True, help="A JSON list of findings.")
    record.add_argument("--record", default=None, help="The run record's path.")
    record.add_argument("--issue", type=int, default=None, help="Resolve the record by issue.")
    record.add_argument("--store-root", default=None, help="Override the store directory.")

    answer = sub.add_parser("answer", help="Answer one recorded finding.")
    answer.add_argument("--finding", required=True, help="The finding's id.")
    answer.add_argument(
        "--fixed", default=None, help="The plan section changed to fix it."
    )
    answer.add_argument("--rejected", default=None, help="The reason it was rejected.")
    answer.add_argument("--record", default=None, help="The run record's path.")
    answer.add_argument("--issue", type=int, default=None, help="Resolve the record by issue.")
    answer.add_argument("--store-root", default=None, help="Override the store directory.")

    check = sub.add_parser("check", help="Gate on every finding answered plus the mapping.")
    check.add_argument("--record", default=None, help="The run record's path.")
    check.add_argument("--issue", type=int, default=None, help="Resolve the record by issue.")
    check.add_argument("--store-root", default=None, help="Override the store directory.")
    check.add_argument("--repo", default=None, help="owner/repo for --issue.")
    check.add_argument("--body-file", default=None, help="Read the issue body from this file.")
    check.add_argument(
        "--repo-root",
        default=None,
        help="Where .saga-profile.json lives, for a record admitted before it recorded a waiver.",
    )
    check.add_argument("--json", action="store_true", help="Print the state as JSON.")
    return parser


def _issue_body(
    args: argparse.Namespace,
    record: run_record.RunRecord | None,
    fetch: Callable[[int, str | None], str],
) -> tuple[str, int | None]:
    if args.body_file:
        path = Path(args.body_file)
        if not path.is_file():
            raise PlanReviewError(f"no issue body at {path}")
        issue = args.issue if args.issue is not None else getattr(record, "issue", None)
        return path.read_text(encoding="utf-8"), issue
    issue = args.issue if args.issue is not None else getattr(record, "issue", None)
    if issue is None:
        raise PlanReviewError("name the issue with --issue <N> or --body-file <path>")
    repo = args.repo or getattr(record, "repo", None)
    try:
        return fetch(int(issue), repo), int(issue)
    except (OSError, RuntimeError) as exc:
        raise PlanReviewError(f"the issue body could not be read: {exc}") from exc


def _post_trace(
    record_file: Path,
    repo: Path,
    *,
    entry: Mapping[str, Any] | None = None,
    finding_id: str | None = None,
    opener: Callable[..., Any] | None = None,
) -> None:
    """Post the review's trace, or an answer's score, to Langfuse (issue 166).

    The run record is already written. Nothing here changes it or the exit code: a failure
    prints one line, and what could not go waits in the owner-only queue for a later post.
    """
    try:
        import review_trace  # noqa: PLC0415 - loaded late so a broken bundle cannot stop a review

        record = run_record.to_dict(build_loop.load_record_file(record_file))
        if entry is not None:
            summary = review_trace.post_plan_review(
                entry, record=record, repo=repo, home=Path.home(), urlopen=opener,
            )
        else:
            summary = review_trace.post_plan_answer(
                record, str(finding_id), repo=repo, home=Path.home(), urlopen=opener,
            )
        print(review_trace.summary_line(summary), file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - a Langfuse problem never fails a plan review
        print(f"langfuse: not posted ({exc.__class__.__name__})", file=sys.stderr)


def _plan_repo(record_file: Path, finding_id: str) -> Path:
    """The checkout holding the newest reviewed plan with this finding, else here."""
    try:
        record = build_loop.load_record_file(record_file)
    except Exception:  # noqa: BLE001 - an unreadable record falls back to the working directory
        return Path.cwd()
    for entry in reversed(plan_review_entries(record)):
        if any(f.get("id") == finding_id for f in entry.get("findings", [])):
            parent = Path(str(entry.get("plan_path") or "")).resolve().parent
            return parent if parent.is_dir() else Path.cwd()
    return Path.cwd()


def main(
    argv: list[str] | None = None,
    *,
    fetch: Callable[[int, str | None], str] = parse_issue.fetch_issue_body,
    trace_opener: Callable[..., Any] | None = None,
) -> int:
    """Run the command line. Every loader call sits inside this one catch."""
    args = build_parser().parse_args(argv)
    try:
        record_file, store_root = record_path_for(args.record, args.issue, args.store_root)
        if args.command == "record":
            plan = Path(args.plan)
            findings, problems = prepare_findings(load_findings(Path(args.findings)))
            if problems:
                raise PlanReviewError(
                    "the findings are not plan-review finding records:\n  "
                    + "\n  ".join(problems)
                )
            entry = do_record(record_file, plan, findings)
            _post_trace(record_file, plan.resolve().parent, entry=entry, opener=trace_opener)
            print(
                json.dumps(
                    {
                        "recorded": len(findings),
                        "plan_sha256": entry["plan_sha256"][:12],
                        "reviewed_revision": entry["reviewed_revision"],
                    },
                    indent=2,
                )
            )
            return EXIT_OK
        if args.command == "answer":
            stored = do_answer(
                record_file,
                args.finding,
                fixed=args.fixed,
                rejected=args.rejected,
                store_root=store_root,
            )
            print(json.dumps({"finding": args.finding, **stored}, indent=2))
            _post_trace(
                record_file, _plan_repo(record_file, args.finding),
                finding_id=args.finding, opener=trace_opener,
            )
            return EXIT_OK
        record = build_loop.load_record_file(record_file)
        entries = plan_review_entries(record)
        if not entries:
            print(f"plan_review: no plan review recorded for issue {record.issue}")
            return EXIT_NOT_READY
        plan = resolve_plan_path(
            entries[-1].get("plan_path", ""), record_file=record_file, store_root=store_root
        )
        body, _ = _issue_body(args, record, fetch)
        repo_root = Path(args.repo_root).resolve() if args.repo_root else Path.cwd()
        mapping = mapping_for(plan, record, body, repo_root=repo_root)
        state = check_state(record, mapping)
        print(json.dumps(state, indent=2) if args.json else format_check(state))
        return EXIT_OK if state["status"] != functional_checks.STATUS_NOT_READY else EXIT_NOT_READY
    except run_record.UnknownRecordVersionError as exc:
        print(f"plan_review: {exc}", file=sys.stderr)
        return EXIT_UNKNOWN_VERSION
    except (PlanReviewError, build_loop.BuildLoopError, run_record.RunRecordError) as exc:
        print(f"plan_review: {exc}", file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
