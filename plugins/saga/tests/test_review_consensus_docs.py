"""Tests for review_consensus API documentation, docstrings, and worked examples (issue #784)."""

from __future__ import annotations

import doctest
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / "plugins" / "saga" / "scripts"
MODULE_PATH = SCRIPTS_DIR / "review_consensus.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("review_consensus", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["review_consensus"] = module
    spec.loader.exec_module(module)
    return module


CONSENSUS: Any = _load_module()


def test_public_state_entry_points_have_meaningful_docstrings() -> None:
    """Assert the public state entry points have structured, comprehensive docstrings."""
    record_cycle_doc = CONSENSUS.ReviewCycleState.record_cycle.__doc__
    assert record_cycle_doc is not None
    assert "revision" in record_cycle_doc
    assert "lens_scores" in record_cycle_doc
    assert "findings" in record_cycle_doc
    assert "delta_checks" in record_cycle_doc
    assert "ReviewResult" in record_cycle_doc
    assert "outcome" in record_cycle_doc
    assert "next_lenses" in record_cycle_doc

    finding_doc = CONSENSUS.ReviewFinding.__doc__
    assert finding_doc is not None
    assert "finding_id" in finding_doc
    assert "lens_id" in finding_doc
    assert "severity" in finding_doc
    assert "file" in finding_doc
    assert "line" in finding_doc
    assert "why_it_matters" in finding_doc
    assert "autofix_class" in finding_doc
    assert "confidence" in finding_doc
    assert "evidence" in finding_doc

    readiness_doc = CONSENSUS.evaluate_review_readiness.__doc__
    assert readiness_doc is not None
    assert "lens_scores" in readiness_doc
    assert "independent_gates" in readiness_doc
    assert "ReviewReadiness" in readiness_doc
    assert "can_proceed" in readiness_doc

    state_doc = CONSENSUS.ReviewCycleState.__doc__
    assert state_doc is not None
    assert "MAX_REVIEW_CYCLES" in state_doc or "controller" in state_doc


def test_module_docstring_worked_example_via_doctest() -> None:
    """Run doctests on the review_consensus module to ensure the worked example executes cleanly."""
    results = doctest.testmod(CONSENSUS)
    assert results.failed == 0
    assert results.attempted > 0


def test_worked_example_end_to_end_state_machine_drive() -> None:
    """Execute the worked example end-to-end as documented in the module docstring."""
    roster = {
        "schema": "review_roster.v1",
        "hash": "sha256:docs-example",
        "lenses": [
            {
                "id": "correctness",
                "scorable": True,
                "threshold": {
                    "strictness": "standard",
                    "derived_overall_minimum": 9.0,
                    "applicable_dimension_minimum": 7,
                },
                "dimensions": [{"id": "behaviour-under-the-plan"}],
            }
        ],
    }
    policy = CONSENSUS.policy_from_roster(roster)
    correctness_dims = dict.fromkeys(policy.dimensions_for("correctness"), 9.5)
    correctness_score = CONSENSUS.score_lens_review("correctness", correctness_dims, policy=policy)
    assert correctness_score.accepted is True

    state = CONSENSUS.ReviewCycleState(["correctness"], policy=policy)
    assert state.next_lenses == ("correctness",)

    finding = CONSENSUS.ReviewFinding(
        finding_id="F01",
        lens_id="correctness",
        dimension_id=policy.dimensions_for("correctness")[0],
        title="Documented boundary check",
        severity="P2",
        file="plugins/saga/scripts/review_consensus.py",
        line=1,
        why_it_matters="Ensures callers understand parameter contracts.",
        autofix_class="safe_auto",
        owner="review-fixer",
        requires_verification=True,
        confidence=100,
        evidence=("plugins/saga/scripts/review_consensus.py:1",),
    )

    result = state.record_cycle(
        revision="a1b2c3d4e5f6",
        lens_scores={"correctness": correctness_score},
        findings=[finding],
    )
    assert result.outcome == "accepted"
    assert len(result.lens_results) == 1
    assert result.lens_results[0].score.derived_overall == correctness_score.derived_overall
    assert result.lens_results[0].score.accepted is True

    gate = CONSENSUS.IndependentGateResult(gate_id="unit-tests", passed=True)
    readiness = CONSENSUS.evaluate_review_readiness(
        lens_scores=[item.score for item in result.lens_results],
        independent_gates=[gate],
    )
    assert readiness.can_proceed is True
    assert readiness.review_accepted is True
    assert readiness.independent_gates_passed is True


def test_private_internals_boundary_documented_and_enforced() -> None:
    """Verify private internals boundary is documented and adhered to."""
    module_doc = CONSENSUS.__doc__
    assert module_doc is not None
    assert "Private Internals" in module_doc or "private" in module_doc

    # All __all__ entries are non-private and exist in module
    for public_name in CONSENSUS.__all__:
        assert not public_name.startswith("_")
        assert hasattr(CONSENSUS, public_name)

    # All module-defined functions and classes with leading underscores are not in __all__
    for name in vars(CONSENSUS):
        if name.startswith("_") and not name.startswith("__"):
            assert name not in CONSENSUS.__all__


def test_acceptance_criteria_python_one_liner() -> None:
    """Run the exact python -c command specified in issue #784 acceptance criteria."""
    cmd = [
        sys.executable,
        "-c",
        (
            "import sys; "
            "sys.path.insert(0,'plugins/saga/scripts'); "
            "import review_consensus as rc; "
            "assert rc.ReviewCycleState.record_cycle.__doc__ and "
            "rc.ReviewFinding.__doc__ and "
            "rc.evaluate_review_readiness.__doc__"
        ),
    ]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Command failed: {proc.stderr}"


def test_documented_exception_hierarchy_matches_the_real_one() -> None:
    """The module docstring's exception-hierarchy note must match the actual class nesting.

    The nesting is the reverse of what the names suggest: ReviewConsensusError subclasses
    ReviewScoringError, so `except ReviewConsensusError` does NOT catch a ReviewScoringError.
    A docstring that names the wrong class sends a direct-drive caller's except clause past
    the error it meant to handle.
    """
    assert issubclass(CONSENSUS.ReviewConsensusError, CONSENSUS.ReviewScoringError)
    assert issubclass(CONSENSUS.ContradictoryReviewEvidenceError, CONSENSUS.ReviewScoringError)
    assert issubclass(CONSENSUS.UnsupportedReviewResultSchemaError, CONSENSUS.ReviewConsensusError)
    assert not issubclass(CONSENSUS.ReviewScoringError, CONSENSUS.ReviewConsensusError)

    module_doc = CONSENSUS.__doc__
    assert module_doc is not None
    assert "Exception Hierarchy" in module_doc
    assert "ReviewScoringError" in module_doc

    # An unknown lens escapes ReviewConsensusError, exactly as the constructor docstring says.
    init_doc = CONSENSUS.ReviewCycleState.__init__.__doc__
    assert init_doc is not None
    assert "ReviewScoringError" in init_doc
    declaring_policy = CONSENSUS.policy_from_roster(
        {
            "schema": "review_roster.v1",
            "lenses": [{"id": "correctness", "dimensions": [{"id": "d1"}]}],
        }
    )
    with pytest.raises(CONSENSUS.ReviewScoringError) as unknown_lens:
        CONSENSUS.ReviewCycleState(["not-a-real-lens"], policy=declaring_policy)
    assert not isinstance(unknown_lens.value, CONSENSUS.ReviewConsensusError)


def test_dimension_id_is_documented_as_a_required_argument() -> None:
    """`ReviewFinding.dimension_id` has no default; the docstring must not read as omittable."""
    import dataclasses

    field = next(f for f in dataclasses.fields(CONSENSUS.ReviewFinding) if f.name == "dimension_id")
    assert field.default is dataclasses.MISSING
    assert field.default_factory is dataclasses.MISSING

    finding_doc = CONSENSUS.ReviewFinding.__doc__
    assert finding_doc is not None
    dimension_line = next(
        line for line in finding_doc.splitlines() if line.strip().startswith("dimension_id:")
    )
    assert "Optional" not in dimension_line
    assert "no default" in finding_doc


def test_runner_delivery_input_vocabulary_excludes_return_statuses() -> None:
    """'ready' is a RunnerDeliveryResolution status, never an accepted session_outcome input."""
    state = CONSENSUS.ReviewCycleState(["correctness"])
    for accepted in ("ran-empty", "died", "not-started"):
        fresh = CONSENSUS.ReviewCycleState(["correctness"])
        assert fresh.handle_runner_delivery({"session_outcome": accepted}).status == "incomplete"
    assert state.handle_runner_delivery({"session_outcome": "ran"}).status == "ready"
    with pytest.raises(CONSENSUS.ReviewConsensusError):
        state.handle_runner_delivery({"session_outcome": "ready"})

    delivery_doc = CONSENSUS.ReviewCycleState.handle_runner_delivery.__doc__
    assert delivery_doc is not None
    assert "never an accepted input" in delivery_doc


def test_readiness_docstring_names_the_attribute_that_exists() -> None:
    """`ReviewResult` carries `lens_results`, not `lens_scores`; the docstring must say so."""
    assert "lens_results" in CONSENSUS.ReviewResult.__dataclass_fields__
    assert "lens_scores" not in CONSENSUS.ReviewResult.__dataclass_fields__
    assert not hasattr(CONSENSUS.ReviewResult, "lens_scores")

    readiness_doc = CONSENSUS.evaluate_review_readiness.__doc__
    assert readiness_doc is not None
    assert "ReviewResult.lens_results" in readiness_doc
    collapsed = " ".join(readiness_doc.split())
    assert "it has no `lens_scores` attribute" in collapsed


def test_record_cycle_docstring_covers_the_delta_check_path_to_repairs() -> None:
    """A failing delta-check can force 'repairs_requested' even when every lens score passes."""
    record_cycle_doc = CONSENSUS.ReviewCycleState.record_cycle.__doc__
    assert record_cycle_doc is not None
    assert "DeltaCheckResult" in record_cycle_doc
    assert "repairs_requested" in record_cycle_doc
    assert "ReviewScoringError" in record_cycle_doc
