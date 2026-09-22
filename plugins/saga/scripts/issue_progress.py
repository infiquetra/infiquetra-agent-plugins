#!/usr/bin/env python3
"""Render Infiquetra lifecycle issue progress comments."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

EVENT_TITLES = {
    "start": "Loop started",
    "phase": "Phase completed",
    "pr": "PR ready",
    "deploy": "Nonprod deployment",
    "completion": "Loop completed",
}


def _line(label: str, value: object | None) -> str | None:
    if value is None or value == "":
        return None
    return f"- {label}: {value}"


def _checks_lines(checks_run: Sequence[str] | None) -> list[str]:
    if not checks_run:
        return []
    lines = ["- checks run:"]
    lines.extend(f"  - `{check}`" for check in checks_run)
    return lines


def _list_lines(label: str, values: Sequence[str] | None) -> list[str]:
    if not values:
        return []
    lines = [f"- {label}:"]
    lines.extend(f"  - {value}" for value in values)
    return lines


_OVERRIDE_LABELS: dict[str, str] = {
    "doc-review": "doc review override",
    "review-gate": "review gate override",
}


def _override_line(gate: str | None, rationale: str | None) -> str | None:
    """Return the rendered override line for *gate* or raise when the gate is absent/unknown.

    A rationale without a known gate is refused — the caller must name which gate
    was waived. An absent rationale yields None (no line).
    """
    if not rationale:
        return None
    if gate not in _OVERRIDE_LABELS:
        raise ValueError(f"override requires a known gate {sorted(_OVERRIDE_LABELS)}; got {gate!r}")
    return f"- {_OVERRIDE_LABELS[gate]}: {rationale}"


def render_issue_comment(
    *,
    event: str,
    issue_ref: str,
    destination: str,
    summary: str | None = None,
    plan_path: str | None = None,
    work_session_path: str | None = None,
    commit_sha: str | None = None,
    checks_run: Sequence[str] | None = None,
    blockers: str | None = None,
    pr_url: str | None = None,
    review_status: str | None = None,
    doc_review_artifact: str | None = None,
    doc_review_blocked: bool | None = None,
    doc_review_fixes: Sequence[str] | None = None,
    doc_review_findings: Sequence[str] | None = None,
    doc_review_override: str | None = None,
    review_gate_override: str | None = None,
    handoff_maturity: str | None = None,
    handoff_source: str | None = None,
    next_action: str | None = None,
    deploy_status: str | None = None,
    workflow_url: str | None = None,
    evidence_link: str | None = None,
) -> str:
    """Render a concise markdown issue progress update."""

    title = EVENT_TITLES.get(event, event.replace("-", " ").title())
    lines = [f"### {title}", "", f"- issue: {issue_ref}", f"- selected destination: {destination}"]
    override_candidates: list[str | None] = []
    if doc_review_override is not None or review_gate_override is not None:
        # What makes a gate-less waiver impossible is the FLAG SPLIT, not a runtime refusal: there
        # are exactly two override parameters and each one carries its gate's name as a literal
        # here, so an unnamed waiver has nowhere to enter. `_override_line`'s raise is a defensive
        # guard for a direct caller, and is unreachable from this path by construction — the
        # earlier note credited it with enforcing the property, which reads as a runtime check that
        # never runs.
        if doc_review_override is not None:
            override_candidates.append(_override_line("doc-review", doc_review_override))
        if review_gate_override is not None:
            override_candidates.append(_override_line("review-gate", review_gate_override))
    # The legacy direct values, still supported for a caller that validated them itself. The
    # helper above is the canonical path for everything it covers.
    for candidate in (
        _line("summary", summary),
        _line("plan", plan_path),
        _line("work session", work_session_path),
        _line("commit", commit_sha),
        _line("PR", pr_url),
        _line("review status", review_status),
        _line("doc review artifact", doc_review_artifact),
        _line("handoff maturity", handoff_maturity),
        _line("handoff source", handoff_source),
        _line("next action", next_action),
        _line(
            "doc review blocked",
            None if doc_review_blocked is None else ("yes" if doc_review_blocked else "no"),
        ),
        _line("deployment status", deploy_status),
        _line("workflow", workflow_url),
        _line("evidence", evidence_link),
        _line("blockers", blockers),
    ):
        if candidate:
            lines.append(candidate)
    for cand in override_candidates:
        if cand:
            lines.append(cand)
    lines.extend(_list_lines("doc review fixes", doc_review_fixes))
    lines.extend(_list_lines("doc review findings", doc_review_findings))
    lines.extend(_checks_lines(checks_run))
    return "\n".join(lines).rstrip() + "\n"


def _split_pipe(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split("|") if item.strip()]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--issue-ref", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--summary")
    parser.add_argument("--plan-path")
    parser.add_argument("--handoff-maturity")
    parser.add_argument("--handoff-source")
    parser.add_argument("--next-action")
    parser.add_argument("--work-session-path")
    parser.add_argument("--commit-sha")
    parser.add_argument("--checks-run", help="pipe-separated list of checks run")
    parser.add_argument("--blockers")
    parser.add_argument("--pr-url")
    parser.add_argument("--review-status")
    parser.add_argument("--doc-review-artifact")
    parser.add_argument(
        "--doc-review-blocked",
        dest="doc_review_blocked",
        action="store_true",
        default=None,
    )
    parser.add_argument(
        "--no-doc-review-blocked",
        dest="doc_review_blocked",
        action="store_false",
    )
    parser.add_argument(
        "--doc-review-fixes",
        help="pipe-separated list of safe fixes the document review applied",
    )
    parser.add_argument("--doc-review-findings", help="pipe-separated list of doc review findings")
    parser.add_argument("--doc-review-override")
    parser.add_argument("--review-gate-override")
    parser.add_argument("--deploy-status")
    parser.add_argument("--workflow-url")
    parser.add_argument("--evidence-link")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    print(
        render_issue_comment(
            event=args.event,
            issue_ref=args.issue_ref,
            destination=args.destination,
            summary=args.summary,
            plan_path=args.plan_path,
            work_session_path=args.work_session_path,
            commit_sha=args.commit_sha,
            checks_run=_split_pipe(args.checks_run),
            blockers=args.blockers,
            pr_url=args.pr_url,
            review_status=args.review_status,
            doc_review_artifact=args.doc_review_artifact,
            doc_review_blocked=args.doc_review_blocked,
            doc_review_fixes=_split_pipe(args.doc_review_fixes),
            doc_review_findings=_split_pipe(args.doc_review_findings),
            doc_review_override=args.doc_review_override,
            review_gate_override=args.review_gate_override,
            handoff_maturity=args.handoff_maturity,
            handoff_source=args.handoff_source,
            next_action=args.next_action,
            deploy_status=args.deploy_status,
            workflow_url=args.workflow_url,
            evidence_link=args.evidence_link,
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
