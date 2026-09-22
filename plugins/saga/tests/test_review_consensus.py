"""Focused behavior tests for Code Review scoring and independent gates (U5)."""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins" / "saga" / "scripts" / "review_consensus.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("review_consensus", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_consensus"] = module
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


def _scores(
    lens_id: str = "correctness",
    score: float = 9.4,
) -> dict[str, float]:
    return dict.fromkeys(TEST_POLICY.dimensions_for(lens_id), score)


def _score_lens(
    *,
    lens_id: str = "correctness",
    score: float = 9.4,
    **kwargs: Any,
) -> Any:
    kwargs.setdefault("policy", TEST_POLICY)
    return CONSENSUS.score_lens_review(lens_id, _scores(lens_id, score), **kwargs)


def test_lens_averaging_nine_point_four_with_no_low_dimension_is_accepted() -> None:
    result = _score_lens(reported_overall=9.4)

    assert result.derived_overall == pytest.approx(9.4)
    assert result.accepted is True
    assert result.failing_dimensions == ()


def test_lens_averaging_nine_point_four_with_a_six_point_nine_dimension_fails_floor() -> None:
    dimensions = _scores("architecture-maintainability")
    values = (6.9, 9.8, 9.8, 9.8, 9.8, 9.85, 9.85)
    for dimension_id, value in zip(dimensions, values, strict=True):
        dimensions[dimension_id] = value

    result = CONSENSUS.score_lens_review(
        "architecture-maintainability",
        dimensions,
        reported_overall=9.4,
    )

    assert result.derived_overall == pytest.approx(9.4)
    assert result.accepted is False
    assert result.failing_dimensions == (next(iter(dimensions)),)


def test_exact_overall_and_dimension_boundaries_are_inclusive() -> None:
    dimensions = _scores(score=9.5)
    first_dimension = next(iter(dimensions))
    dimensions[first_dimension] = 7.0

    result = CONSENSUS.score_lens_review(
        "correctness",
        dimensions,
        reported_overall=9.0,
    )

    assert result.derived_overall == pytest.approx(9.0)
    assert result.accepted is True
    assert result.failing_dimensions == ()


def test_mean_below_nine_fails_even_when_every_dimension_clears_the_floor() -> None:
    result = _score_lens(score=8.9, reported_overall=8.9)

    assert result.derived_overall == pytest.approx(8.9)
    assert result.accepted is False
    assert result.failing_dimensions == ()


def test_dimension_below_seven_fails_even_when_mean_reaches_nine() -> None:
    dimensions = _scores(score=9.525)
    first_dimension = next(iter(dimensions))
    dimensions[first_dimension] = 6.9

    result = CONSENSUS.score_lens_review(
        "correctness",
        dimensions,
        reported_overall=9.0,
    )

    assert result.derived_overall == pytest.approx(9.0)
    assert result.accepted is False
    assert result.failing_dimensions == (first_dimension,)


def test_selected_lens_with_no_applicable_dimensions_is_rejected() -> None:
    with pytest.raises(
        CONSENSUS.ReviewScoringError,
        match="at least one applicable dimension",
    ):
        CONSENSUS.score_lens_review("correctness", {})


def test_reported_overall_that_disagrees_with_dimensions_is_contradictory() -> None:
    with pytest.raises(
        CONSENSUS.ContradictoryReviewEvidenceError,
        match="reported overall",
    ):
        _score_lens(score=7.0, reported_overall=9.9)


def test_non_applicable_dimension_requires_a_recorded_cause() -> None:
    dimensions = _scores()
    excluded_dimension = next(iter(dimensions))
    del dimensions[excluded_dimension]

    with pytest.raises(
        CONSENSUS.ReviewScoringError,
        match="non-applicable dimension.*cause",
    ):
        CONSENSUS.score_lens_review(
            "correctness",
            dimensions,
            non_applicable_dimensions={excluded_dimension: ""},
        )


def test_non_applicable_dimension_with_a_cause_is_excluded_from_the_mean() -> None:
    dimensions = _scores()
    excluded_dimension = next(iter(dimensions))
    del dimensions[excluded_dimension]

    result = CONSENSUS.score_lens_review(
        "correctness",
        dimensions,
        non_applicable_dimensions={
            excluded_dimension: "The reviewed change has no state transition."
        },
        reported_overall=9.4,
    )

    assert result.accepted is True
    assert result.derived_overall == pytest.approx(9.4)
    assert result.non_applicable_dimensions == {
        excluded_dimension: "The reviewed change has no state transition."
    }


def test_dimension_at_four_point_nine_uses_the_same_floor_failure_path() -> None:
    dimensions = _scores("architecture-maintainability", score=10.0)
    first_dimension = next(iter(dimensions))
    dimensions[first_dimension] = 4.9

    result = CONSENSUS.score_lens_review("architecture-maintainability", dimensions)

    assert result.derived_overall >= TEST_POLICY.overall_minimum
    assert result.accepted is False
    assert result.failing_dimensions == (first_dimension,)


def test_passing_dimension_with_unresolved_critical_evidence_is_contradictory() -> None:
    dimension_id = next(iter(_scores()))
    finding = CONSENSUS.FindingEvidence(
        finding_id="F-critical",
        dimension_id=dimension_id,
        critical=True,
        resolved=False,
        priority="P3",
        confidence=0,
    )

    with pytest.raises(
        CONSENSUS.ContradictoryReviewEvidenceError,
        match="unresolved critical finding.*passing score",
    ):
        _score_lens(score=9.0, findings=(finding,))


def test_critical_evidence_with_honest_low_score_is_valid_but_fails_floor() -> None:
    dimensions = _scores(score=9.525)
    dimension_id = next(iter(dimensions))
    dimensions[dimension_id] = 6.9
    finding = CONSENSUS.FindingEvidence(
        finding_id="F-critical",
        dimension_id=dimension_id,
        critical=True,
        resolved=False,
        priority="P3",
        confidence=0,
    )

    result = CONSENSUS.score_lens_review(
        "correctness",
        dimensions,
        reported_overall=9.0,
        findings=(finding,),
    )

    assert result.accepted is False
    assert result.failing_dimensions == (dimension_id,)


def test_priority_and_confidence_metadata_are_not_acceptance_gates() -> None:
    dimension_id = next(iter(_scores()))
    finding = CONSENSUS.FindingEvidence(
        finding_id="F-metadata-only",
        dimension_id=dimension_id,
        critical=False,
        resolved=False,
        priority="P0",
        confidence=100,
    )

    result = _score_lens(score=9.0, findings=(finding,))

    assert result.accepted is True


def test_built_versus_planned_failure_blocks_readiness_outside_scoring() -> None:
    score = _score_lens()
    readiness = CONSENSUS.evaluate_review_readiness(
        (score,),
        (
            CONSENSUS.IndependentGateResult("built-versus-planned", False),
            CONSENSUS.IndependentGateResult("scanner", True),
            CONSENSUS.IndependentGateResult("test", True),
            CONSENSUS.IndependentGateResult("deployment", True),
        ),
    )

    assert score.accepted is True
    assert score.derived_overall == pytest.approx(9.4)
    assert readiness.review_accepted is True
    assert readiness.independent_gates_passed is False
    assert readiness.failed_independent_gates == ("built-versus-planned",)
    assert readiness.can_proceed is False


def test_passed_scanner_test_and_deployment_gates_do_not_change_score() -> None:
    score = _score_lens()
    readiness = CONSENSUS.evaluate_review_readiness(
        (score,),
        (
            CONSENSUS.IndependentGateResult("scanner", True),
            CONSENSUS.IndependentGateResult("test", True),
            CONSENSUS.IndependentGateResult("deployment", True),
            CONSENSUS.IndependentGateResult("casualty", True),
            CONSENSUS.IndependentGateResult("operational-safety", True),
        ),
    )

    assert readiness.lens_scores == (score,)
    assert score.derived_overall == pytest.approx(9.4)
    assert readiness.review_accepted is True
    assert readiness.independent_gates_passed is True
    assert readiness.can_proceed is True


@pytest.mark.parametrize(
    "gate_id",
    ["scanner", "test", "deployment", "casualty", "operational-safety"],
)
def test_failed_safety_gate_blocks_readiness_without_changing_acceptance(gate_id: str) -> None:
    score = _score_lens()

    readiness = CONSENSUS.evaluate_review_readiness(
        (score,),
        (CONSENSUS.IndependentGateResult(gate_id, False),),
    )

    assert score.accepted is True
    assert score.derived_overall == pytest.approx(9.4)
    assert readiness.review_accepted is True
    assert readiness.failed_independent_gates == (gate_id,)
    assert readiness.can_proceed is False


def test_declared_dimensions_must_be_accounted_for_exactly_once() -> None:
    missing = _scores()
    missing.pop(next(iter(missing)))
    with pytest.raises(CONSENSUS.ReviewScoringError, match="missing dimensions"):
        CONSENSUS.score_lens_review("correctness", missing, policy=TEST_POLICY)

    unknown = _scores()
    unknown["invented-dimension"] = 9.4
    with pytest.raises(CONSENSUS.ReviewScoringError, match="unknown dimensions"):
        CONSENSUS.score_lens_review("correctness", unknown, policy=TEST_POLICY)


@pytest.mark.parametrize("invalid_score", [True, -0.1, 10.1, float("nan"), float("inf")])
def test_dimension_scores_must_be_finite_roster_scale_numbers(invalid_score: object) -> None:
    dimensions: dict[str, object] = {}
    dimensions.update(_scores())
    dimensions[next(iter(dimensions))] = invalid_score

    with pytest.raises(CONSENSUS.ReviewScoringError, match="finite number within"):
        CONSENSUS.score_lens_review("correctness", dimensions)


def test_policy_values_and_dimensions_come_from_the_resolved_roster() -> None:
    """Thresholds and dimensions arrive as an argument, never from a file in this plugin.

    Until issue 1001 this module read `references/lens-roster.json`, a fourteen-lens
    quality policy shipped inside the plugin. A plugin upgrade could therefore change
    the acceptance bar for every repository with no decision anywhere that said so,
    which is what architecture decision record ADR-001 removes. The thresholds now
    come off the roster the run resolved from the lifecycle repository's catalogue.
    """
    policy = CONSENSUS.policy_from_roster(TEST_ROSTER)

    assert policy.overall_minimum == 9.0
    assert policy.dimension_floor == 7.0
    assert policy.minimum_score == 0.0
    assert policy.maximum_score == 10.0
    assert policy.dimensions_for("correctness") == tuple(
        dimension["id"]
        for dimension in next(
            lens for lens in TEST_ROSTER["lenses"] if lens["id"] == "correctness"
        )["dimensions"]
    )
    assert policy.declares_dimensions is True


def test_no_roster_file_is_read_from_this_plugin() -> None:
    """The deleted policy file has no reader left, and the module names no path to one."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "ROSTER_PATH" not in source

    # The module docstring still NAMES the deleted file, to say why it is gone. A
    # blanket string check would forbid that explanation, so this walks the parsed
    # module instead and asserts no code outside a docstring mentions the path —
    # which is the property that actually matters.
    tree = ast.parse(source)
    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstring_nodes.add(id(body[0].value))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "lens-roster.json" in node.value
        ):
            assert id(node) in docstring_nodes, (
                "a live string names the deleted policy file; only a docstring "
                "explaining its removal may mention it"
            )

    assert not (ROOT / "plugins" / "saga" / "references" / "lens-roster.json").exists()


def test_the_default_policy_declares_no_lens_dimensions() -> None:
    """Without a roster the plugin has thresholds but no lens vocabulary of its own.

    That is the executor boundary showing through: which dimensions a lens has is
    catalogue content, and a default that carried its own copy would be this plugin
    owning policy again.
    """
    assert CONSENSUS.DEFAULT_SCORING_POLICY.declares_dimensions is False
    assert CONSENSUS.DEFAULT_SCORING_POLICY.dimensions_for("correctness") == ()
    assert CONSENSUS.DEFAULT_SCORING_POLICY.overall_minimum == 9.0
    assert CONSENSUS.DEFAULT_SCORING_POLICY.dimension_floor == 7.0
