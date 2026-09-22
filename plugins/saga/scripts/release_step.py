#!/usr/bin/env python3
"""release_step — the release, the functional test, and the close, over the run record (1028).

These three steps used to live only in prose in a skill document, which meant three of card 1028's
requirements had no executable guard. Behaviour that cannot be tested is behaviour nobody can tell
is broken, so it lives here instead and the skill calls it.

Three commands, and what each one refuses:

* ``release`` merges the parent pull request and records what landed. It binds the merge to the
  head it waited on with ``gh pr merge --match-head-commit``, so the server that owns the reference
  performs the compare-and-swap: a local read-then-compare is a time-of-check-to-time-of-use race,
  which this repository's journal records at ``DECISIONS.md:9485``. It classifies a refusal from
  GitHub's ``mergeStateStatus`` rather than trusting a watch command's exit status — the same
  journal records a pull request squash-merged while its merge state was ``UNSTABLE``
  (``LEARNINGS.md:11001``). The commit that lands is recorded SEPARATELY from the head that was
  checked, because a squash or a rebase produces a different commit and a closing comment that
  links a commit nothing ever checked is worse than one that links nothing.
* ``deploy`` hands the merged revision to the deploy plugin's existing handoff — but only where the
  repository profile declares a non-production destination. Where it declares ``none``, as this
  repository does, the absence is RECORDED with its reason and nothing is deployed. That is a
  result, not an error: the lifecycle's closeout rule forbids fabricating a deployment record, and
  failing here would block every run in a repository that has no lower environment.
* ``functional-test`` records each prescribed scenario's terminal state and counts a failure
  against the post-merge allowance, which keeps its own counter of three standard and two escalated
  cycles plus exactly one recorded extension.
* ``close`` composes the closeout comment the lifecycle repository's ``terminal-outcomes.md``
  requires, and REFUSES to compose one that would state an environment, a deployment or an
  acceptance result the record does not carry.

No production deployment exists anywhere in this module, and there is no argument that would
produce one.

House pattern: pure functions over explicit values, an injected runner for every ``gh`` call so no
test reaches GitHub, and no I/O at import.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

Runner = Callable[..., Any]

#: The merge states that mean "not yet, and here is what to do about it". Anything else that is not
#: ``CLEAN`` is reported verbatim rather than guessed at.
MERGE_STATE_ROUTES = {
    "BEHIND": "the pull request is behind its base; re-integrate the base branch and try again",
    "DIRTY": "the pull request conflicts with its base; the conflict is resolved before the merge",
    "BLOCKED": "a required check or review is not satisfied yet; the release keeps waiting",
    "UNSTABLE": "a required check has not passed on this head; the release keeps waiting",
    "UNKNOWN": "GitHub has not computed mergeability yet; the release keeps waiting",
}

#: The terminal states a prescribed scenario may end in. An unrun scenario is never folded into a
#: pass — the lifecycle repository's functional-testing rule, as a value set.
SCENARIO_STATES = ("passed", "failed", "blocked")

#: The closeout comment's required parts, from ``docs/process/terminal-outcomes.md``. Each one is
#: recorded, and where a practice does not apply its absence is recorded WITH A REASON.
CLOSEOUT_PARTS = (
    "delivered_revision",
    "environment",
    "acceptance_results",
    "residual_risks",
    "documentation_status",
    "cleanup_confirmation",
    "closure_reason",
    "disposition",
)

#: The five dispositions and the GitHub closure reason each maps to. The mapping is fixed by the
#: lifecycle repository; this module never invents a sixth.
DISPOSITIONS = {
    "delivered": "COMPLETED",
    "duplicate": "DUPLICATE",
    "superseded": "NOT_PLANNED",
    "declined": "NOT_PLANNED",
    "canceled": "NOT_PLANNED",
}

#: Dispositions that must link their replacement before the issue closes.
REPLACEMENT_REQUIRED = ("duplicate", "superseded")


class ReleaseStepError(RuntimeError):
    """A refusal stated in one line — never a traceback at the command line."""


def _run(runner: Runner | None, argv: list[str], *, timeout: int = 300) -> Any:
    call = runner if runner is not None else subprocess.run
    return call(argv, capture_output=True, text=True, timeout=timeout)


def _out(result: Any) -> str:
    return str(getattr(result, "stdout", "") or "").strip()


def _ok(result: Any) -> bool:
    return getattr(result, "returncode", 1) == 0


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


def pull_request_state(repo: str, number: int, *, runner: Runner | None = None) -> dict[str, Any]:
    """The pull request's head, merge state and required-check results, read from GitHub."""
    result = _run(
        runner,
        [
            "gh",
            "pr",
            "view",
            str(number),
            "--repo",
            repo,
            "--json",
            "headRefOid,mergeStateStatus,mergeable,statusCheckRollup,url",
        ],
    )
    if not _ok(result):
        raise ReleaseStepError(f"could not read pull request {repo}#{number}: {_out(result)}")
    try:
        return dict(json.loads(_out(result) or "{}"))
    except json.JSONDecodeError as exc:
        raise ReleaseStepError(
            f"pull request {repo}#{number} returned invalid JSON: {exc}"
        ) from exc


def failing_checks(state: dict[str, Any]) -> list[str]:
    """Required checks on this head that did not conclude successfully, by name."""
    failing: list[str] = []
    for check in state.get("statusCheckRollup") or []:
        if not isinstance(check, dict):
            continue
        conclusion = str(check.get("conclusion") or check.get("state") or "").upper()
        name = str(check.get("name") or check.get("context") or "a check")
        if conclusion in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            continue
        failing.append(f"{name} ({conclusion or 'PENDING'})")
    return failing


def release(
    *,
    repo: str,
    number: int,
    merge_method: str = "merge",
    runner: Runner | None = None,
) -> dict[str, Any]:
    """Merge the parent pull request, bound to the exact head its checks ran against.

    Returns the release state to record. It never reports success on a merge it did not observe:
    the ``gh`` call either merged or it did not, and a refusal carries GitHub's own reason.
    """
    state = pull_request_state(repo, number, runner=runner)
    head = str(state.get("headRefOid") or "")
    if not head:
        raise ReleaseStepError(f"pull request {repo}#{number} reports no head commit")
    merge_state = str(state.get("mergeStateStatus") or "UNKNOWN").upper()
    unfinished = failing_checks(state)
    if merge_state != "CLEAN" or unfinished:
        route = MERGE_STATE_ROUTES.get(
            merge_state, f"GitHub reports mergeStateStatus {merge_state}"
        )
        detail = f"; not concluded on this head: {', '.join(unfinished)}" if unfinished else ""
        return {
            "status": "waiting",
            "repo": repo,
            "pull_request": number,
            "url": state.get("url", ""),
            "reviewed_head": head,
            "merge_state": merge_state,
            "reason": route + detail,
        }

    merged = _run(
        runner,
        [
            "gh",
            "pr",
            "merge",
            str(number),
            "--repo",
            repo,
            f"--{merge_method}",
            "--match-head-commit",
            head,
        ],
    )
    if not _ok(merged):
        return {
            "status": "refused",
            "repo": repo,
            "pull_request": number,
            "reviewed_head": head,
            "merge_state": merge_state,
            "reason": f"GitHub refused the merge bound to {head[:12]}: {_out(merged) or 'no detail'}",
        }
    landed = _run(
        runner, ["gh", "pr", "view", str(number), "--repo", repo, "--json", "mergeCommit,url"]
    )
    landed_commit = ""
    url = str(state.get("url") or "")
    if _ok(landed):
        try:
            payload = json.loads(_out(landed) or "{}")
            landed_commit = str((payload.get("mergeCommit") or {}).get("oid") or "")
            url = str(payload.get("url") or url)
        except json.JSONDecodeError:
            landed_commit = ""
    return {
        "status": "merged",
        "repo": repo,
        "pull_request": number,
        "url": url,
        "reviewed_head": head,
        "landed_commit": landed_commit,
        "merge_method": merge_method,
        "merge_state": merge_state,
    }


# ---------------------------------------------------------------------------
# deploy
# ---------------------------------------------------------------------------


def nonproduction_destination(record: dict[str, Any]) -> str:
    """The run's declared lower environment, or the empty string when it declares none."""
    parameters = record.get("run_configuration") or {}
    entry = parameters.get("nonproduction_destination")
    value = entry.get("value") if isinstance(entry, dict) else entry
    text = str(value or "").strip()
    return "" if text.lower() in ("", "none", "null") else text


def deploy(
    record: dict[str, Any],
    *,
    saga_id: str,
    release_state: dict[str, Any],
    handoff: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Hand the merged revision to the deploy plugin, or record that there is nowhere to send it.

    ``handoff`` is the deploy plugin's ``deploy_handoff.offer``, injected so a test can prove both
    halves without a deploy plugin present and without anything being deployed.
    """
    destination = nonproduction_destination(record)
    if not destination:
        return {
            "status": "no-destination",
            "deployed": False,
            "reason": (
                "this repository's profile declares nonproduction_destination 'none', so there is "
                "no lower environment to deploy to; nothing was deployed and no deployment is "
                "recorded"
            ),
        }
    if release_state.get("status") != "merged":
        raise ReleaseStepError(
            "the release has not merged, so there is no revision to deploy; deploy follows the "
            "merge and never precedes it"
        )
    if handoff is None:
        raise ReleaseStepError(
            f"this run declares the non-production destination {destination!r} but no deploy "
            "handoff was supplied; the baton is never released without an acknowledgement"
        )
    envelope = handoff(saga_id=saga_id, offered_by="saga release step")
    return {
        "status": "handed-off",
        "deployed": True,
        "destination": destination,
        "revision": release_state.get("landed_commit") or release_state.get("reviewed_head", ""),
        "handoff": envelope,
    }


# ---------------------------------------------------------------------------
# functional test
# ---------------------------------------------------------------------------


def post_merge_allowance(record: dict[str, Any]) -> dict[str, int]:
    """The post-merge repair loop's own budget, read from the run configuration.

    Its own counter, not the code review's: the lifecycle repository gives the post-merge loop a
    separate one under the same rules, plus exactly one recorded extension.
    """
    parameters = record.get("run_configuration") or {}

    def _value(key: str, fallback: int) -> int:
        entry = parameters.get(key)
        raw = entry.get("value") if isinstance(entry, dict) else entry
        try:
            return int(raw)
        except (TypeError, ValueError):
            return fallback

    return {
        "standard": _value("standard_cycle_allowance", 3),
        "escalated": _value("escalated_cycle_allowance", 2),
    }


def record_functional_test(
    record: dict[str, Any], scenarios: list[dict[str, Any]]
) -> dict[str, Any]:
    """Record one functional-test pass and say what happens next.

    An unrun scenario is never folded into a pass: every prescribed scenario ends the pass with a
    terminal state, and a scenario carrying anything else is refused by name.

    Three states go in and five statuses come out, because ``blocked`` routes differently from
    both of its neighbours. A **required** blocked scenario returns ``blocked``: it proved nothing,
    and its causes — environment, credential, permission — are the operator's approval boundaries,
    which no build loop can repair, so it stops for him and never counts a repair cycle. An
    **optional** blocked scenario returns ``passed-with-proof-debt``, carrying the debt by name.
    A scenario that does not say which it is counts as required, because the safe default is the
    one that cannot pass unproved.

    This arithmetic was originally computed from the failed list alone, which reported a scenario
    list holding nothing but blocked entries as ``passed`` — the silent skip prescribed testing
    exists to remove (LEARNINGS ``{#1039-record-functional-test-counts-only-failures}``).
    """
    for scenario in scenarios:
        state = str(scenario.get("state") or "")
        if state not in SCENARIO_STATES:
            raise ReleaseStepError(
                f"scenario {scenario.get('name', '?')!r} ended in {state!r}; a prescribed scenario "
                f"ends in one of: {', '.join(SCENARIO_STATES)}"
            )
        if state == "blocked" and not str(scenario.get("cause") or "").strip():
            raise ReleaseStepError(
                f"scenario {scenario.get('name', '?')!r} is blocked with no cause named; a blocked "
                "scenario records what blocked it"
            )
    existing = record.get("functional_test") or {}
    cycles = int(existing.get("post_merge_cycles") or 0)
    extension_taken = bool(existing.get("extension_taken"))
    failed = [s for s in scenarios if s.get("state") == "failed"]
    blocked = [s for s in scenarios if s.get("state") == "blocked"]
    required_blocked = [s for s in blocked if s.get("required", True)]
    optional_blocked = [s for s in blocked if not s.get("required", True)]
    allowance = post_merge_allowance(record)
    budget = allowance["standard"] + allowance["escalated"]

    # A required block outranks a failure: the loop can repair the failure and cannot repair the
    # block, so sending this to the loop would spend a cycle on work that cannot clear the stop.
    if required_blocked:
        named = "; ".join(
            f"{s.get('name', '?')}: {s.get('cause', '')}".strip() for s in required_blocked
        )
        return {
            "status": "blocked",
            "scenarios": scenarios,
            "post_merge_cycles": cycles,
            "extension_taken": extension_taken,
            "reason": (
                f"{len(required_blocked)} required scenario(s) could not run, so nothing was "
                f"proved about them: {named}. The causes of a block are environment, credential "
                "and permission, none of which the build loop can repair, so this goes to the "
                "operator and no repair cycle is counted"
            ),
        }

    if not failed:
        if optional_blocked:
            return {
                "status": "passed-with-proof-debt",
                "scenarios": scenarios,
                "post_merge_cycles": cycles,
                "extension_taken": extension_taken,
                "proof_debt": [
                    {"name": str(s.get("name", "?")), "cause": str(s.get("cause", ""))}
                    for s in optional_blocked
                ],
                "reason": (
                    f"every required scenario passed and {len(optional_blocked)} optional "
                    "scenario(s) could not run; the debt is recorded rather than hidden"
                ),
            }
        return {
            "status": "passed",
            "scenarios": scenarios,
            "post_merge_cycles": cycles,
            "extension_taken": extension_taken,
        }
    cycles += 1
    if cycles <= budget:
        return {
            "status": "re-enters-the-build-loop",
            "scenarios": scenarios,
            "post_merge_cycles": cycles,
            "extension_taken": extension_taken,
            "reason": (
                f"{len(failed)} scenario(s) failed; cycle {cycles} of {budget} in the post-merge "
                "allowance"
            ),
        }
    if not extension_taken:
        return {
            "status": "re-enters-the-build-loop",
            "scenarios": scenarios,
            "post_merge_cycles": cycles,
            "extension_taken": True,
            "reason": (
                f"the post-merge allowance of {budget} cycles is spent; taking the one recorded "
                "extension, which no role may grant twice"
            ),
        }
    return {
        "status": "exhausted",
        "scenarios": scenarios,
        "post_merge_cycles": cycles,
        "extension_taken": True,
        "reason": (
            "the post-merge allowance and its one extension are both spent; the result goes to the "
            "operator and prescribed testing is never weakened to fit inside it"
        ),
    }


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def closeout_comment(
    record: dict[str, Any],
    *,
    disposition: str,
    replacement: str = "",
) -> dict[str, Any]:
    """The closeout comment's parts, refusing to state anything the record does not carry.

    Returns ``{"disposition", "closure_reason", "parts", "body"}``. Each part is either a value from
    the record or a recorded absence WITH a reason — never a fabricated environment, deployment or
    acceptance result.
    """
    if disposition not in DISPOSITIONS:
        raise ReleaseStepError(
            f"unknown disposition {disposition!r}; the five terminal dispositions are: "
            f"{', '.join(DISPOSITIONS)}"
        )
    if disposition in REPLACEMENT_REQUIRED and not replacement.strip():
        raise ReleaseStepError(
            f"a {disposition} issue links its replacement before it closes, and none was given"
        )
    release_state = record.get("release") or {}
    deploy_state = record.get("deployment") or {}
    test_state = record.get("functional_test") or {}

    revision = str(release_state.get("landed_commit") or release_state.get("reviewed_head") or "")
    parts: dict[str, str] = {
        "delivered_revision": revision
        or "not recorded: this run's release state carries no merged revision",
        "environment": str(deploy_state.get("destination") or "")
        or f"not applicable: {deploy_state.get('reason', 'no deployment state is recorded')}",
        "acceptance_results": _acceptance_line(test_state),
        "residual_risks": str(record.get("residual_risks") or "") or "none recorded for this run",
        "documentation_status": str(record.get("documentation_status") or "")
        or "not recorded: this run's record carries no documentation status",
        "cleanup_confirmation": str(record.get("cleanup") or "")
        or "not recorded: this run's record carries no cleanup confirmation",
        "closure_reason": DISPOSITIONS[disposition],
        "disposition": disposition,
    }
    if replacement.strip():
        parts["replacement"] = replacement.strip()
    missing = [part for part in CLOSEOUT_PARTS if not parts.get(part)]
    if missing:
        raise ReleaseStepError(
            f"the closeout comment is missing {', '.join(missing)}; a practice that does not apply "
            "is recorded with a reason, never left blank"
        )
    lines = [f"- **{key.replace('_', ' ')}**: {value}" for key, value in parts.items()]
    body = "## Closeout\n\n" + "\n".join(lines) + "\n"
    return {
        "disposition": disposition,
        "closure_reason": DISPOSITIONS[disposition],
        "parts": parts,
        "body": body,
    }


def _acceptance_line(test_state: dict[str, Any]) -> str:
    scenarios = test_state.get("scenarios") or []
    if not scenarios:
        return "not recorded: this run's record carries no functional-test result"
    counts: dict[str, int] = {}
    for scenario in scenarios:
        state = str(scenario.get("state") or "unknown")
        counts[state] = counts.get(state, 0) + 1
    return ", ".join(f"{count} {state}" for state, count in sorted(counts.items()))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="The saga release, functional test, and close.")
    parser.add_argument("--record", required=True, help="path to the run record JSON file")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_release = sub.add_parser("release", help="merge the parent pull request and record it")
    p_release.add_argument("--pull-request", required=True, type=int)
    p_release.add_argument("--merge-method", default="merge", choices=["merge", "squash", "rebase"])
    p_release.add_argument("--dry-run", action="store_true")
    p_deploy = sub.add_parser("deploy", help="hand off to deploy, or record that there is nowhere")
    p_deploy.add_argument("--saga-id", default="")
    p_close = sub.add_parser("close", help="compose the closeout comment")
    p_close.add_argument("--disposition", default="delivered")
    p_close.add_argument("--replacement", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.record).resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if args.cmd == "release":
            if args.dry_run:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "repo": raw.get("repo", ""),
                            "pull_request": args.pull_request,
                            "merge_method": args.merge_method,
                        }
                    )
                )
                return 0
            print(
                json.dumps(
                    release(
                        repo=str(raw.get("repo") or ""),
                        number=args.pull_request,
                        merge_method=args.merge_method,
                    )
                )
            )
            return 0
        if args.cmd == "deploy":
            print(
                json.dumps(
                    deploy(
                        raw,
                        saga_id=args.saga_id or f"issue-{raw.get('issue', '')}",
                        release_state=raw.get("release") or {},
                    )
                )
            )
            return 0
        print(
            json.dumps(
                closeout_comment(raw, disposition=args.disposition, replacement=args.replacement)
            )
        )
        return 0
    except (OSError, ValueError, ReleaseStepError) as exc:
        print(f"release_step: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
