#!/usr/bin/env python3
"""saga's IntentEnvelope surface — re-export of the canonical fleet schema (#380).

The schema, interview registry, and resolvers live at the canonical fleet-commons home
(``plugins/fleet-core/scripts/fleet_commons/intent_envelope.py``) because the envelope
has consumers in three plugins; this module re-exports them for saga's siblings
(``outcome_spec.py``, ``outcome_orchestrator.py``, ``execution_spec.py``, ``outcome.py``)
exactly as ``execution_spec.py`` re-exports ``tier_palette`` — never a second schema.

What lives HERE (saga-only glue that needs saga siblings):

* :func:`compute_stakes` — the data-backed interview numbers (T4-F4-2):
  ``parallel_width`` from the spec's dependency layers and ``critical_path_estimate``
  via ``outcome_costs.critical_path_wall`` at unit weight (the emitter's existing
  A7-table logic, reused rather than re-derived).
* :func:`implied_required_checks` — the ``ceremony_gates.reviews_required`` consumer
  (T8-F1-3): when a spec's committed intent declares ``reviews_required: "gate"``, every
  ``code`` leaf's ``done`` transition additionally requires ``code-review`` evidence
  through the existing closure gate (``closure_gate.py`` + ``evidence_ledger.py``) —
  reusing the shipped evidence machinery, never a parallel gate.
* :func:`seeded_tier` — the run-start posture seeding hook (T12-F1-2): per-unit tier
  defaults read the spec's committed ``intent`` (its ``run_mode``) through the same
  ``recommend_tier`` matrix, so `/plan`'s tier table proposes mode-aware defaults
  instead of re-interrogating per unit.
* The CLI — ``interview`` / ``capture`` / ``from-issue`` / ``recommend`` / ``spend`` —
  the doc-plus-CLI surface ``{#operator-choice-framework}`` calls for (no runtime
  injection; skills shell out to this).

The single-asker rule (G-negative-space-1): no saga skill or script defines its own
run-start posture question — everything resolves through this registry. The fleet
drift-guard test (``tests/test_intent_envelope.py``) enforces that mechanically.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "_bundled"))
# The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose
# resolution ladder is Claude-specific runtime discovery this package must not
# retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on
# disk at install time and Fleet Core is never installed separately.
import intent_envelope  # noqa: E402  (after the sys.path shim, by design)

_canonical = intent_envelope

# Re-exported canonical API (single source of truth — never redefined here).
SCHEMA_VERSION = _canonical.SCHEMA_VERSION
ATTENDED = _canonical.ATTENDED
UNATTENDED = _canonical.UNATTENDED
RUN_MODES = _canonical.RUN_MODES
GATE = _canonical.GATE
AUTO = _canonical.AUTO
GATE_SETTINGS = _canonical.GATE_SETTINGS
CEREMONY_GATE_FIELDS = _canonical.CEREMONY_GATE_FIELDS
ISSUE_BLOCK_FENCE = _canonical.ISSUE_BLOCK_FENCE
ISSUE_BLOCK_HEADING = _canonical.ISSUE_BLOCK_HEADING
IntentEnvelopeError = _canonical.IntentEnvelopeError
PostureError = _canonical.PostureError
CeremonyGates = _canonical.CeremonyGates
IntentEnvelope = _canonical.IntentEnvelope
PostureQuestion = _canonical.PostureQuestion
INTERVIEW = _canonical.INTERVIEW
Stakes = _canonical.Stakes
interview_manifest = _canonical.interview_manifest
render_interview = _canonical.render_interview
apply_answers = _canonical.apply_answers
unanswered_questions = _canonical.unanswered_questions
TierRecommendation = _canonical.TierRecommendation
recommend_tier = _canonical.recommend_tier
spend_posture = _canonical.spend_posture
SpendDecision = _canonical.SpendDecision
resolve_spend_action = _canonical.resolve_spend_action
# #373 dispatch-seam posture (optional additive v1 fields, enforced at the /outcome seam).
INTENT_DEGRADE_HALT = _canonical.INTENT_DEGRADE_HALT
INTENT_DEGRADE_ONE_RUNG = _canonical.INTENT_DEGRADE_ONE_RUNG
INTENT_DEGRADE_POLICIES = _canonical.INTENT_DEGRADE_POLICIES
SPEND_ENVELOPE_FIELDS = _canonical.SPEND_ENVELOPE_FIELDS
SpendEnvelope = _canonical.SpendEnvelope
SpendAuthorization = _canonical.SpendAuthorization
authorize_spend = _canonical.authorize_spend
SelfSelectedPosture = _canonical.SelfSelectedPosture
self_select_posture = _canonical.self_select_posture
render_issue_block = _canonical.render_issue_block
extract_issue_block = _canonical.extract_issue_block
envelope_from_issue_body = _canonical.envelope_from_issue_body
StartDecision = _canonical.StartDecision
outcome_start_decision = _canonical.outcome_start_decision

# The evidence check id a reviews_required=gate posture implies on code leaves —
# the id `/code-review` records in the evidence ledger (closure_gate's vocabulary).
REVIEW_CHECK_ID = "code-review"


def compute_stakes(spec: Any) -> Any:
    """Compute the interview's data-backed stakes from an outcome spec (T4-F4-2).

    ``parallel_width`` = the widest Kahn layer (the biggest concurrent wave the DAG can
    run); ``critical_path_estimate`` = the longest dependency chain at unit weight,
    computed by the SAME ``critical_path_wall`` the cost rollup's A7 comparison uses —
    reused, not re-derived, so the prompt and the rollup can never disagree about shape.
    """
    # The width and depth came from the outcome spec's dependency layers and the cost rollup's
    # critical-path walk. Issue 1030 removed both with the outcome coordinator, so stakes are no
    # longer derived from a DAG shape -- a run is one issue, and the caller supplies them.
    raise NotImplementedError(
        "stakes are no longer derived from an outcome spec; pass Stakes explicitly"
    )


def implied_required_checks(intent: dict[str, Any] | None, node_kind: str) -> tuple[str, ...]:
    """The closure-gate checks a spec-level intent implies for one node (T8-F1-3).

    ``reviews_required: "gate"`` implies ``code-review`` evidence on every ``code``
    leaf before it may harvest ``done``. No intent (every pre-existing spec) implies
    nothing — behavior is byte-identical to today. An invalid intent dict raises
    (fail closed) rather than silently implying nothing; ``OutcomeSpec.validate()``
    rejects it earlier on every normal path.
    """
    if intent is None:
        return ()
    envelope = IntentEnvelope.from_dict(intent)
    if node_kind == "code" and envelope.ceremony_gates.reviews_required == GATE:
        return (REVIEW_CHECK_ID,)
    return ()


def seeded_tier(spec: Any, work_shape: str) -> Any:
    """Per-unit tier default seeded from a spec's committed run-start posture (T12-F1-2).

    Reads the spec's ``intent`` (``ExecutionSpec.intent`` / ``OutcomeSpec.intent``) and
    resolves the work shape through the one ``recommend_tier`` matrix. A spec with no
    committed intent seeds the attended default — exactly today's behavior.
    """
    intent = getattr(spec, "intent", None)
    run_mode = ATTENDED
    if intent is not None:
        run_mode = IntentEnvelope.from_dict(intent).run_mode
    return recommend_tier(work_shape, run_mode)


# ---------------------------------------------------------------------------
# CLI — the doc-plus-CLI operator surface ({#operator-choice-framework}).
# ---------------------------------------------------------------------------


def _cli_interview(args: argparse.Namespace) -> int:
    # --outcome-spec derived stakes from an outcome DAG. Issue 1030 removed the outcome
    # coordinator, so there is no spec to read and stakes are supplied by the caller.
    stakes = None
    if args.json:
        print(json.dumps(interview_manifest(stakes), indent=2))
    else:
        print(render_interview(stakes), end="")
    return 0


def _cli_capture(args: argparse.Namespace) -> int:
    raw = (
        sys.stdin.read()
        if args.answers_json == "-"
        else Path(args.answers_json).read_text(encoding="utf-8")
    )
    envelope = apply_answers(json.loads(raw), source=args.source, authored_by=args.authored_by)
    print(envelope.to_json(), end="")
    return 0


def _cli_from_issue(args: argparse.Namespace) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8")
    decision = outcome_start_decision(body)
    print(json.dumps(decision.to_dict(), indent=2))
    return 0


def _cli_recommend(args: argparse.Namespace) -> int:
    rec = recommend_tier(args.work_shape, args.run_mode)
    print(json.dumps({"model": rec.model, "effort": rec.effort, "because": rec.because}, indent=2))
    return 0


def _cli_spend(args: argparse.Namespace) -> int:
    decision = resolve_spend_action(
        args.run_mode,
        spend_increase=args.spend_increase,
        approval_token=args.approval_token,
    )
    print(json.dumps(decision.to_dict(), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="intent_envelope",
        description="The fleet's single run-start posture surface (#380).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_interview = sub.add_parser(
        "interview", help="render the composed run-start posture interview (the single asker)"
    )
    p_interview.add_argument(
        "--outcome-spec",
        default=None,
        help="outcome-spec.json to compute data-backed stakes from (parallel width, critical path)",
    )
    p_interview.add_argument(
        "--json", action="store_true", help="emit the machine-parseable manifest instead of text"
    )
    p_interview.set_defaults(func=_cli_interview)

    p_capture = sub.add_parser(
        "capture", help="turn a typed answer set (JSON {qid: option}) into a validated envelope"
    )
    p_capture.add_argument("answers_json", help="path to the answers JSON, or - for stdin")
    p_capture.add_argument("--source", default="interview")
    p_capture.add_argument("--authored-by", default="")
    p_capture.set_defaults(func=_cli_capture)

    p_from_issue = sub.add_parser(
        "from-issue", help="read an issue body file and print the /outcome start decision"
    )
    p_from_issue.add_argument("body_file")
    p_from_issue.set_defaults(func=_cli_from_issue)

    p_recommend = sub.add_parser(
        "recommend", help="the mode-aware tier recommendation for a work shape"
    )
    p_recommend.add_argument("--work-shape", required=True)
    p_recommend.add_argument("--run-mode", required=True, choices=list(RUN_MODES))
    p_recommend.set_defaults(func=_cli_recommend)

    p_spend = sub.add_parser("spend", help="resolve one spend decision through the envelope")
    p_spend.add_argument("--run-mode", required=True, choices=list(RUN_MODES))
    p_spend.add_argument("--spend-increase", action="store_true")
    p_spend.add_argument("--approval-token", default=None)
    p_spend.set_defaults(func=_cli_spend)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except (IntentEnvelopeError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
