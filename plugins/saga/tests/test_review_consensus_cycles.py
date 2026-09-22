"""Focused state-machine and transport tests for Code Review consensus (U6)."""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import MISSING, fields
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins" / "saga" / "scripts" / "review_consensus.py"
FINDINGS_SCHEMA_PATH = (
    ROOT / "plugins" / "saga" / "skills" / "code-review" / "references" / "findings-schema.md"
)
WORK_COMMAND_PATH = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "commands" / "work.md"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("review_consensus_cycles", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_consensus_cycles"] = module
    spec.loader.exec_module(module)
    return module


CONSENSUS: Any = _load_module()


# The lens dimensions and thresholds these tests score against, in the shape the
# lifecycle repository's generator emits. Issue 1001 deleted the plugin's own
# policy file; a review takes its thresholds from the roster resolved for the run,
# so a test takes them from a roster too. The dimension names are the catalogue's.
TEST_ROSTER: dict[str, Any] = {
    "schema": "review_roster.v1",
    "hash": "sha256:test-roster",
    "lenses": [
        {
            "id": lens_id,
            "always_on": True,
            "scorable": True,
            "threshold": {
                "strictness": "standard",
                "derived_overall_minimum": 9.0,
                "applicable_dimension_minimum": 7,
            },
            "dimensions": [{"id": f"{lens_id}-d{index}"} for index in range(1, count + 1)],
        }
        # The counts are the lifecycle catalogue's own, at revision 5efc869f:
        # seven dimensions on architecture and maintainability, five on each of
        # the other three always-on lenses. A fixture with the wrong count would
        # let a lens pass here that the real catalogue would not.
        for lens_id, count in (
            ("architecture-maintainability", 7),
            ("correctness", 5),
            ("security", 5),
            ("testing", 5),
        )
    ],
}

TEST_POLICY: Any = CONSENSUS.policy_from_roster(TEST_ROSTER)


def _score(
    lens_id: str,
    value: float,
    *,
    findings: tuple[Any, ...] = (),
) -> Any:
    dimensions = dict.fromkeys(TEST_POLICY.dimensions_for(lens_id), value)
    return CONSENSUS.score_lens_review(lens_id, dimensions, findings=findings)


def _delta(
    lens_id: str,
    reviewed_revision: str,
    checked_revision: str,
    *,
    passed: bool,
) -> Any:
    return CONSENSUS.DeltaCheckResult(
        lens_id=lens_id,
        reviewed_revision=reviewed_revision,
        checked_revision=checked_revision,
        passed=passed,
        cause="No regression in the reviewed lens."
        if passed
        else "The repair regressed this lens.",
        evidence_refs=(f"delta:{lens_id}:{checked_revision}",),
    )


def _finding(
    lens_id: str,
    finding_id: str,
    *,
    autofix_class: str = "safe_auto",
    owner: str = "review-fixer",
    severity: str = "P1",
    pre_existing: bool = False,
) -> Any:
    return CONSENSUS.ReviewFinding(
        finding_id=finding_id,
        lens_id=lens_id,
        dimension_id=(
            None if lens_id == "external-reviewer" else TEST_POLICY.dimensions_for(lens_id)[0]
        ),
        title=f"Repair {finding_id}",
        severity=severity,
        file=f"src/{lens_id}.py",
        line=10,
        why_it_matters="The reviewed behavior remains incorrect.",
        autofix_class=autofix_class,
        owner=owner,
        requires_verification=True,
        confidence=100,
        evidence=(f"src/{lens_id}.py:10",),
        pre_existing=pre_existing,
        suggested_fix="Apply the bounded repair and rerun this lens.",
    )


def _accepted_result() -> Any:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    return state.record_cycle("revision-1", {"correctness": _score("correctness", 9.4)})


def _repairs_result() -> Any:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    return state.record_cycle("revision-1", {"correctness": _score("correctness", 8.9)})


def _cycle_cap_result() -> Any:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    state.record_cycle("revision-1", {"correctness": _score("correctness", 8.9)})
    state.record_cycle("revision-2", {"correctness": _score("correctness", 8.8)})
    return state.record_cycle("revision-3", {"correctness": _score("correctness", 8.7)})


def _incomplete_result() -> Any:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    return state.handle_runner_delivery(
        {"session_outcome": "died", "reason": "bounded retries exhausted"}
    ).review_result


def test_only_failing_lenses_are_rerun_and_accepted_revisions_are_retained() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness", "security", "testing"))

    first = state.record_cycle(
        "revision-1",
        {
            "correctness": _score("correctness", 8.9),
            "security": _score("security", 8.9),
            "testing": _score("testing", 9.4),
        },
    )
    assert first.outcome == "repairs_requested"
    assert state.next_lenses == ("correctness", "security")

    second = state.record_cycle(
        "revision-2",
        {
            "correctness": _score("correctness", 9.4),
            "security": _score("security", 8.9),
        },
    )
    assert second.outcome == "repairs_requested"
    assert state.next_lenses == ("security",)

    final = state.record_cycle(
        "revision-3",
        {"security": _score("security", 9.4)},
        delta_checks=(
            _delta("correctness", "revision-2", "revision-3", passed=True),
            _delta("testing", "revision-1", "revision-3", passed=True),
        ),
    )

    assert final.outcome == "accepted"
    assert [record.attempted_lenses for record in final.cycle_history] == [
        ("correctness", "security", "testing"),
        ("correctness", "security"),
        ("security",),
    ]
    assert {result.lens_id: result.reviewed_revision for result in final.lens_results} == {
        "correctness": "revision-2",
        "security": "revision-3",
        "testing": "revision-1",
    }


def test_critical_typed_finding_cannot_bypass_scoring_or_result_validation() -> None:
    finding = _finding("correctness", "F-critical-route", severity="P0")
    state = CONSENSUS.ReviewCycleState(("correctness",))

    with pytest.raises(
        CONSENSUS.ContradictoryReviewEvidenceError,
        match="unresolved critical finding.*passing score",
    ):
        state.record_cycle(
            "revision-1",
            {"correctness": _score("correctness", 9.4)},
            findings=(finding,),
        )
    assert state.cycle_count == 0

    accepted_payload = _accepted_result().to_dict()
    fix_requests = CONSENSUS.consolidate_fix_requests((finding,))
    accepted_payload["findings"] = [finding.to_dict()]
    accepted_payload["fix_requests"] = [item.to_dict() for item in fix_requests]
    accepted_payload["unresolved_fix_ids"] = [item.fix_id for item in fix_requests]
    accepted_payload["residual_summary"]["unresolved_fix_ids"] = [
        item.fix_id for item in fix_requests
    ]
    with pytest.raises(
        CONSENSUS.ContradictoryReviewEvidenceError,
        match="unresolved critical finding.*passing score",
    ):
        CONSENSUS.ReviewResult.from_dict(accepted_payload)

    silent_critical = _finding("correctness", "F-default-critical", severity="P0")
    default_evidence = CONSENSUS.FindingEvidence(
        finding_id=silent_critical.finding_id,
        dimension_id=silent_critical.dimension_id,
        resolved=False,
        priority=silent_critical.severity,
        confidence=silent_critical.confidence,
    )
    assert default_evidence.critical is False
    evidence_state = CONSENSUS.ReviewCycleState(("correctness",))

    with pytest.raises(
        CONSENSUS.ContradictoryReviewEvidenceError,
        match="unresolved critical finding.*passing score",
    ):
        evidence_state.record_cycle(
            "revision-1",
            {
                "correctness": _score(
                    "correctness",
                    9.4,
                    findings=(default_evidence,),
                )
            },
            findings=(silent_critical,),
        )
    assert evidence_state.cycle_count == 0


def test_priority_alone_does_not_gate_a_passing_dimension() -> None:
    finding = _finding("correctness", "F-priority-metadata", severity="P2")
    state = CONSENSUS.ReviewCycleState(("correctness",))

    result = state.record_cycle(
        "revision-1",
        {"correctness": _score("correctness", 9.4)},
        findings=(finding,),
    )

    assert result.outcome == "accepted"
    assert result.fix_requests
    assert result.lens_results[0].score.findings[0].critical is False
    assert result.lens_results[0].score.findings[0].priority == "P2"


@pytest.mark.parametrize(
    ("autofix_class", "pre_existing"),
    (
        pytest.param("safe_auto", True, id="pre-existing"),
        pytest.param("advisory", False, id="advisory"),
    ),
)
def test_non_gating_p0_findings_remain_metadata_on_passing_scores(
    autofix_class: str,
    pre_existing: bool,
) -> None:
    finding = _finding(
        "correctness",
        f"F-{autofix_class}",
        autofix_class=autofix_class,
        severity="P0",
        pre_existing=pre_existing,
    )
    state = CONSENSUS.ReviewCycleState(("correctness",))

    result = state.record_cycle(
        "revision-1",
        {"correctness": _score("correctness", 9.4)},
        findings=(finding,),
    )

    assert result.outcome == "accepted"
    assert result.fix_requests == ()
    assert result.lens_results[0].score.findings[0].critical is False
    assert result.lens_results[0].score.findings[0].priority == "P0"


def test_review_finding_dimension_and_critical_evidence_are_documented() -> None:
    dimension = next(
        field for field in fields(CONSENSUS.ReviewFinding) if field.name == "dimension_id"
    )
    schema = FINDINGS_SCHEMA_PATH.read_text(encoding="utf-8")

    assert dimension.default is MISSING
    assert "| `dimension_id` | yes |" in schema
    assert "| `critical` | yes |" in schema
    assert "A reviewer sets it\nto `true` when an unresolved finding" in schema
    assert "an omitted or default `false` cannot downgrade" in schema


def test_work_command_uses_typed_outcome_and_keeps_freshness_separate() -> None:
    contract = WORK_COMMAND_PATH.read_text(encoding="utf-8")

    assert "typed `outcome` as the sole\nacceptance decision" in contract
    assert "stale review as a freshness check" in contract
    assert "unresolved P0/P1 findings" not in contract


def test_three_failing_cycles_return_latest_revision_and_complete_residuals() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness", "security"))

    for cycle in (1, 2):
        result = state.record_cycle(
            f"revision-{cycle}",
            {
                "correctness": _score("correctness", 8.9),
                "security": _score("security", 8.8),
            },
            findings=(
                _finding("correctness", "F-correctness"),
                _finding("security", "F-security"),
            ),
        )
        assert result.outcome == "repairs_requested"

    final = state.record_cycle(
        "revision-3",
        {
            "correctness": _score("correctness", 8.7),
            "security": _score("security", 8.6),
        },
        findings=(
            _finding("correctness", "F-correctness"),
            _finding("security", "F-security"),
        ),
    )

    residual = final.residual_summary.to_dict()
    assert final.outcome == "cycle_cap_best_available"
    assert final.best_available_revision == "revision-3"
    assert set(residual["final_lens_scores"]) == {"correctness", "security"}
    assert set(residual["unresolved_fix_ids"]) == set(final.unresolved_fix_ids)
    assert set(final.unresolved_fix_ids) == {request.fix_id for request in final.fix_requests}


def test_a_fourth_cycle_is_never_attempted() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    state.record_cycle("revision-1", {"correctness": _score("correctness", 8.9)})
    state.record_cycle("revision-2", {"correctness": _score("correctness", 8.8)})
    state.record_cycle("revision-3", {"correctness": _score("correctness", 8.7)})

    with pytest.raises(CONSENSUS.ReviewConsensusError, match="no further cycle|fourth"):
        state.record_cycle("revision-4", {"correctness": _score("correctness", 9.4)})


def test_cycle_three_score_regression_is_reported_but_adds_no_gate() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    state.record_cycle("revision-1", {"correctness": _score("correctness", 8.9)})
    state.record_cycle("revision-2", {"correctness": _score("correctness", 8.8)})
    final = state.record_cycle("revision-3", {"correctness": _score("correctness", 8.0)})

    assert final.outcome == "cycle_cap_best_available"
    assert any(
        regression.cycle == 3
        and regression.previous_overall == pytest.approx(8.8)
        and regression.current_overall == pytest.approx(8.0)
        for regression in final.residual_summary.score_regressions
    )


def test_delivery_exhaustion_returns_incomplete_without_a_cycle_or_score() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness",))

    resolution = state.handle_runner_delivery(
        {"session_outcome": "died", "reason": "bounded retries exhausted"}
    )

    assert resolution.status == "incomplete"
    assert resolution.review_result is not None
    assert resolution.review_result.outcome == "review_incomplete"
    assert resolution.review_result.lens_results == ()
    assert resolution.review_result.cycle_history == ()
    assert state.cycle_count == 0


def test_result_serialization_round_trips_schema_revision_bindings_and_routes() -> None:
    state = CONSENSUS.ReviewCycleState(
        ("correctness",),
        evidence_ledger={"lens:correctness": "ledger-entry-1"},
    )
    result = state.record_cycle(
        "0123456789abcdef0123456789abcdef01234567",
        {"correctness": _score("correctness", 9.4)},
    )

    serialized = result.to_json()
    restored = CONSENSUS.ReviewResult.from_json(serialized)
    payload = json.loads(serialized)

    assert restored.to_json() == serialized
    assert payload["schema"] == "review_result.v2"
    assert payload["collection_operation"] == {
        "operation": "collect",
        "schema": "review_result.v2",
    }
    assert payload["revision_binding"]["lens_revisions"] == {
        "correctness": "0123456789abcdef0123456789abcdef01234567"
    }
    assert payload["evidence_ledger"] == {"lens:correctness": "ledger-entry-1"}
    assert "verdict" not in payload


def test_unknown_result_schema_is_refused_instead_of_guessed() -> None:
    payload = _accepted_result().to_dict()
    payload["schema"] = "review_result.v3"

    with pytest.raises(
        CONSENSUS.UnsupportedReviewResultSchemaError,
        match="unsupported review result schema",
    ):
        CONSENSUS.ReviewResult.from_dict(payload)


def test_each_outcome_allows_only_its_named_resume_transition() -> None:
    results = (
        _accepted_result(),
        _repairs_result(),
        _cycle_cap_result(),
        _incomplete_result(),
    )

    for result in results:
        assert result.resume_transitions == (result.next_action,)
        assert result.require_resume_transition(result.next_action) == result.next_action
        with pytest.raises(CONSENSUS.ReviewConsensusError, match="does not allow transition"):
            result.require_resume_transition("undefined_transition")


def test_failed_delta_check_returns_an_accepted_lens_to_the_failing_set() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness", "security"))
    state.record_cycle(
        "revision-1",
        {
            "correctness": _score("correctness", 9.4),
            "security": _score("security", 8.9),
        },
    )
    state.record_cycle(
        "revision-2",
        {"security": _score("security", 8.8)},
    )

    result = state.record_cycle(
        "revision-3",
        {"security": _score("security", 9.4)},
        delta_checks=(_delta("correctness", "revision-1", "revision-3", passed=False),),
    )

    retained = next(item for item in result.lens_results if item.lens_id == "correctness")
    assert result.outcome == "cycle_cap_best_available"
    assert result.failing_lenses == ("correctness",)
    assert state.next_lenses == ()
    assert retained.accepted is False


def test_passing_delta_check_retains_original_revision_without_a_full_rerun() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness", "security"))
    state.record_cycle(
        "revision-1",
        {
            "correctness": _score("correctness", 9.4),
            "security": _score("security", 8.9),
        },
    )

    result = state.record_cycle(
        "revision-2",
        {"security": _score("security", 9.4)},
        delta_checks=(_delta("correctness", "revision-1", "revision-2", passed=True),),
    )

    retained = next(item for item in result.lens_results if item.lens_id == "correctness")
    assert result.outcome == "accepted"
    assert retained.reviewed_revision == "revision-1"
    assert retained.delta_check is not None
    assert result.cycle_history[1].attempted_lenses == ("security",)


@pytest.mark.parametrize("session_outcome", ["ran-empty", "died"])
def test_terminal_empty_or_dead_runner_delivery_does_not_consume_a_cycle(
    session_outcome: str,
) -> None:
    state = CONSENSUS.ReviewCycleState(("correctness",))

    resolution = state.handle_runner_delivery({"session_outcome": session_outcome})

    assert resolution.status == "incomplete"
    assert resolution.review_result is not None
    assert resolution.review_result.outcome == "review_incomplete"
    assert state.cycle_count == 0


def test_pending_runner_is_collected_once_and_never_read_as_empty_or_relaunched() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    calls: list[dict[str, Any]] = []

    def collect(invocation: dict[str, Any]) -> dict[str, Any]:
        calls.append(invocation)
        return {
            "session_outcome": "ran",
            "findings": [{"content": "whole-diff evidence"}],
        }

    resolution = state.handle_runner_delivery(
        {
            "session_outcome": "pending",
            "handle": {"request_digest": "digest", "result_path": "result.json"},
        },
        collector=collect,
    )

    assert resolution.status == "ready"
    assert resolution.payload["findings"] == [{"content": "whole-diff evidence"}]
    assert calls == [
        {
            "operation": "collect",
            "handle": {"request_digest": "digest", "result_path": "result.json"},
        }
    ]
    assert state.cycle_count == 0


def test_cycle_state_round_trips_and_resumes_the_same_selective_rerun() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness", "security"))
    state.record_cycle(
        "revision-1",
        {
            "correctness": _score("correctness", 9.4),
            "security": _score("security", 8.9),
        },
    )

    restored = CONSENSUS.ReviewCycleState.from_json(state.to_json())
    assert restored.next_lenses == ("security",)
    assert restored.cycle_count == 1

    result = restored.record_cycle(
        "revision-2",
        {"security": _score("security", 9.4)},
        delta_checks=(_delta("correctness", "revision-1", "revision-2", passed=True),),
    )
    assert result.outcome == "accepted"


def test_finding_routes_serialize_into_consolidated_fix_requests() -> None:
    state = CONSENSUS.ReviewCycleState(("correctness",))
    result = state.record_cycle(
        "revision-1",
        {"correctness": _score("correctness", 8.9)},
        findings=(_finding("correctness", "F-route"),),
    )

    payload = result.to_dict()
    assert payload["findings"][0]["autofix_class"] == "safe_auto"
    assert payload["findings"][0]["owner"] == "review-fixer"
    assert payload["fix_requests"][0]["finding_ids"] == ["F-route"]
    assert payload["fix_requests"][0]["touched_paths"] == ["src/correctness.py"]


def test_accepted_result_cannot_carry_active_findings() -> None:
    """#894: accepted + empty failing + empty unresolved cannot serialize with status=active."""
    leftover = _finding(
        "correctness",
        "F-active-p2",
        severity="P2",
        pre_existing=True,
    )
    assert leftover.status == "active"
    state = CONSENSUS.ReviewCycleState(("correctness",))
    result = state.record_cycle(
        "revision-1",
        {"correctness": _score("correctness", 9.4)},
        findings=(leftover,),
    )

    assert result.outcome == "accepted"
    assert result.failing_lenses == ()
    assert result.unresolved_fix_ids == ()
    assert result.findings
    assert all(item.status != "active" for item in result.findings)

    round_tripped = CONSENSUS.ReviewResult.from_json(result.to_json())
    assert all(item.status != "active" for item in round_tripped.findings)

    illegal = result.to_dict()
    illegal["findings"] = [leftover.to_dict()]
    for lens_result in illegal["lens_results"]:
        lens_result["scoring_findings"] = [
            {
                "finding_id": leftover.finding_id,
                "dimension_id": leftover.dimension_id,
                "critical": False,
                "resolved": False,
                "priority": leftover.severity,
                "confidence": leftover.confidence,
            }
        ]
    with pytest.raises(
        CONSENSUS.ReviewConsensusError,
        match="accepted result cannot carry findings still marked active",
    ):
        CONSENSUS.ReviewResult.from_dict(illegal)


def test_repairs_requested_may_carry_active_findings() -> None:
    """#894: repairs_requested and cycle_cap_best_available may still list status=active."""
    open_finding = _finding("correctness", "F-open", severity="P1")
    repairs = CONSENSUS.ReviewCycleState(("correctness",)).record_cycle(
        "revision-1",
        {"correctness": _score("correctness", 8.9)},
        findings=(open_finding,),
    )
    assert repairs.outcome == "repairs_requested"
    assert any(item.status == "active" for item in repairs.findings)

    capped_state = CONSENSUS.ReviewCycleState(("correctness",))
    capped_state.record_cycle(
        "revision-1",
        {"correctness": _score("correctness", 8.9)},
        findings=(open_finding,),
    )
    capped_state.record_cycle(
        "revision-2",
        {"correctness": _score("correctness", 8.8)},
        findings=(open_finding,),
    )
    capped = capped_state.record_cycle(
        "revision-3",
        {"correctness": _score("correctness", 8.7)},
        findings=(open_finding,),
    )
    assert capped.outcome == "cycle_cap_best_available"
    assert any(item.status == "active" for item in capped.findings)


def test_fix_identifiers_differ_across_lifecycles_and_are_stable_within_one() -> None:
    """#899: lifecycle namespaces the identity; resume and re-derive keep the same id."""
    finding = _finding("correctness", "F-shared")
    scores = {"correctness": _score("correctness", 8.9)}

    first = CONSENSUS.ReviewCycleState(("correctness",), lifecycle="c2")
    first_result = first.record_cycle("revision-1", scores, findings=(finding,))
    second = CONSENSUS.ReviewCycleState(("correctness",), lifecycle="c6")
    second_result = second.record_cycle("revision-1", scores, findings=(finding,))
    assert first_result.fix_requests[0].fix_id != second_result.fix_requests[0].fix_id

    again = CONSENSUS.ReviewCycleState(("correctness",), lifecycle="c2")
    again_result = again.record_cycle("revision-1", scores, findings=(finding,))
    assert again_result.fix_requests[0].fix_id == first_result.fix_requests[0].fix_id

    restored = CONSENSUS.ReviewCycleState.from_json(first.to_json())
    restored_payload = json.loads(first.to_json())
    assert restored_payload["lifecycle"] == "c2"
    assert "lifecycle" not in json.loads(CONSENSUS.ReviewCycleState(("correctness",)).to_json())
    restored_again = CONSENSUS.ReviewCycleState(("correctness",), lifecycle="c2")
    restored_again_result = restored_again.record_cycle("revision-1", scores, findings=(finding,))
    assert restored_again_result.fix_requests[0].fix_id == first_result.fix_requests[0].fix_id
    assert json.loads(restored.to_json())["lifecycle"] == "c2"

    unscoped = CONSENSUS.ReviewCycleState(("correctness",)).record_cycle(
        "revision-1", scores, findings=(finding,)
    )
    assert (
        unscoped.fix_requests[0].fix_id == CONSENSUS.consolidate_fix_requests((finding,))[0].fix_id
    )
    assert "lifecycle" not in unscoped.to_dict()
