"""`review_result.v2`: finding identity, one history per unit, and the cycle cap.

Children 939 (dedupe by fingerprint), 946 (one history per unit) and 885 (residuals
at the cap) are proved here. Every test uses a temporary store root; nothing writes
to the primary checkout's run-record store and nothing reaches the network.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "plugins" / "saga" / "scripts"


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def rr() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    return _load("review_result_under_test", SCRIPTS / "review_result.py")


@pytest.fixture
def record_module() -> ModuleType:
    sys.path.insert(0, str(SCRIPTS))
    return _load("run_record_for_result", SCRIPTS / "run_record.py")


REVISION = "a" * 40
OTHER_REVISION = "b" * 40


def _record(record_module: ModuleType) -> Any:
    return record_module.RunRecord(
        issue=1001,
        repo="infiquetra/infiquetra-claude-plugins",
        run_configuration=record_module.empty_run_configuration(),
        approval_scope=record_module.empty_approval_scope(),
        admission=record_module.empty_admission(),
    )


def _finding(rr: ModuleType, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "path": "plugins/saga/scripts/review_result.py",
        "line": 42,
        "category": "unhandled-error",
        "lens": "correctness",
        "dimension": "intent-behavior-completeness",
        "severity": "P2",
        "evidence": "plugins/saga/scripts/review_result.py:42",
        "impact": "the caller sees a traceback instead of a refusal",
    }
    fields.update(overrides)
    return rr.Finding(**fields)


def _result(rr: ModuleType, **overrides: Any) -> Any:
    fields: dict[str, Any] = {
        "revision": REVISION,
        "roster_hash": "sha256:test",
        "outcome": "repairs_requested",
        "cycle": 1,
        "loop": rr.LOOP_CODE_REVIEW,
        "unit": "issue-1001",
    }
    fields.update(overrides)
    return rr.ReviewResult(**fields)


# ---------------------------------------------------------------------------
# Finding identity and dedupe — child 939
# ---------------------------------------------------------------------------


def test_the_same_defect_from_two_lenses_is_one_finding_with_the_agreement_recorded(
    rr: ModuleType,
) -> None:
    """One fingerprint, one finding. The second is `duplicate-of`, never deleted."""
    first = _finding(rr, lens="correctness")
    second = _finding(rr, lens="security")
    assert first.id == second.id

    survivors, duplicates = rr.deduplicate([first, second])

    assert len(survivors) == 1
    assert survivors[0].lens == "correctness"
    assert survivors[0].agreed_by == ("security",)
    assert len(duplicates) == 1
    assert duplicates[0].status == "duplicate-of"
    assert duplicates[0].duplicate_of == first.id


def test_similar_wording_at_different_locations_stays_two_findings(rr: ModuleType) -> None:
    """Similar wording is not evidence of the same defect.

    Folding two findings together on wording would merge two real problems into one
    repair, and the second would never be fixed.
    """
    first = _finding(rr, line=42, impact="the caller sees a traceback")
    second = _finding(rr, line=430, impact="the caller sees a traceback")

    survivors, duplicates = rr.deduplicate([first, second])

    assert len(survivors) == 2
    assert duplicates == []


def test_the_fingerprint_is_path_line_and_category_only(rr: ModuleType) -> None:
    """The catalogue's three fields, and nothing else — so identity survives a rewording."""
    reworded = _finding(rr, impact="completely different wording", severity="P0")
    assert reworded.id == _finding(rr).id

    moved = _finding(rr, line=43)
    assert moved.id != _finding(rr).id

    recategorised = _finding(rr, category="something-else")
    assert recategorised.id != _finding(rr).id


def test_a_finding_with_no_citation_is_refused(rr: ModuleType) -> None:
    """A finding with no evidence is an evidence gap, not a finding."""
    with pytest.raises(rr.ReviewResultError, match="evidence gap"):
        _finding(rr, evidence="   ")


def test_only_the_catalogues_status_vocabulary_is_accepted(rr: ModuleType) -> None:
    with pytest.raises(rr.ReviewResultError, match="status"):
        _finding(rr, status="mostly-fixed")
    for status in rr.STATUS_VOCABULARY:
        assert _finding(rr, status=status).status == status


def test_only_the_catalogues_four_classifications_are_accepted(rr: ModuleType) -> None:
    """The four classes of operator decision C6, and no invented fifth."""
    with pytest.raises(rr.ReviewResultError, match="classification"):
        _finding(rr, classification="probably-fine")
    for classification in rr.CLASSIFICATION_VOCABULARY:
        assert _finding(rr, classification=classification).classification == classification


# ---------------------------------------------------------------------------
# The reviewed revision
# ---------------------------------------------------------------------------


def test_an_abbreviated_revision_is_refused(rr: ModuleType) -> None:
    """An abbreviation stops meaning anything once the branch moves."""
    with pytest.raises(rr.ReviewResultError, match="forty-character"):
        _result(rr, revision="a1b2c3d")


def test_a_symbolic_revision_is_refused(rr: ModuleType) -> None:
    with pytest.raises(rr.ReviewResultError, match="forty-character"):
        _result(rr, revision="HEAD")


# ---------------------------------------------------------------------------
# One history per unit — child 946
# ---------------------------------------------------------------------------


def test_a_second_history_for_the_same_unit_is_refused(
    rr: ModuleType, record_module: ModuleType
) -> None:
    """A fresh history resets the cycle counter and shows incomparable scores.

    The refusal names how many cycles the existing history holds, so the caller can
    see what it would have discarded.
    """
    record = _record(record_module)
    record = rr.append_result(record, _result(rr, cycle=1))
    record = rr.append_result(record, _result(rr, cycle=2, revision=OTHER_REVISION))

    with pytest.raises(rr.HistoryConflictError) as refusal:
        rr.refuse_second_history(record, "issue-1001", rr.LOOP_CODE_REVIEW)

    message = str(refusal.value)
    assert "2 cycle(s)" in message
    assert OTHER_REVISION in message
    assert "incomparable" in message


def test_a_first_history_for_a_unit_is_allowed(rr: ModuleType, record_module: ModuleType) -> None:
    record = _record(record_module)
    rr.refuse_second_history(record, "issue-1001", rr.LOOP_CODE_REVIEW)


def test_a_different_unit_gets_its_own_history(rr: ModuleType, record_module: ModuleType) -> None:
    record = _record(record_module)
    record = rr.append_result(record, _result(rr, unit="issue-1001"))

    rr.refuse_second_history(record, "issue-1002", rr.LOOP_CODE_REVIEW)


def test_scores_are_compared_only_within_one_declared_lens_set(
    rr: ModuleType, record_module: ModuleType
) -> None:
    """The roster is frozen for the run, so a differing lens set is refused."""
    record = _record(record_module)
    first = _result(rr, cycle=1)
    first.lens_results = [
        rr.LensResult(lens="correctness", strictness="standard", scorable=True),
        rr.LensResult(lens="security", strictness="standard", scorable=True),
    ]
    record = rr.append_result(record, first)

    rr.comparable_lens_set(record, "issue-1001", rr.LOOP_CODE_REVIEW, ["correctness", "security"])

    with pytest.raises(rr.ReviewResultError, match="frozen for the whole run"):
        rr.comparable_lens_set(record, "issue-1001", rr.LOOP_CODE_REVIEW, ["correctness"])


# ---------------------------------------------------------------------------
# One counter per loop
# ---------------------------------------------------------------------------


def test_each_loop_keeps_its_own_counter(rr: ModuleType, record_module: ModuleType) -> None:
    """A long testing phase must not spend the pre-merge budget."""
    record = _record(record_module)
    record = rr.append_result(record, _result(rr, cycle=1, loop=rr.LOOP_CODE_REVIEW))
    record = rr.append_result(record, _result(rr, cycle=2, loop=rr.LOOP_CODE_REVIEW))
    record = rr.append_result(record, _result(rr, cycle=1, loop=rr.LOOP_POST_MERGE))

    assert rr.cycles_used(record, "issue-1001", rr.LOOP_CODE_REVIEW) == 2
    assert rr.cycles_used(record, "issue-1001", rr.LOOP_POST_MERGE) == 1
    assert rr.next_cycle(record, "issue-1001", rr.LOOP_CODE_REVIEW) == 3
    assert rr.next_cycle(record, "issue-1001", rr.LOOP_POST_MERGE) == 2


def test_an_unknown_loop_is_refused(rr: ModuleType) -> None:
    with pytest.raises(rr.ReviewResultError, match="loop"):
        _result(rr, loop="whenever")


# ---------------------------------------------------------------------------
# A legacy entry — the v1 read rule
# ---------------------------------------------------------------------------


def test_a_legacy_entry_is_reported_preserved_and_counted_toward_no_allowance(
    rr: ModuleType, record_module: ModuleType
) -> None:
    """A v1 entry used a different acceptance rule and is not comparable to a v2 one."""
    record = _record(record_module)
    legacy = {"schema": "review_result.v1", "cycle": 1, "outcome": "accepted"}
    record.review_cycles.append(legacy)
    record = rr.append_result(record, _result(rr, cycle=1))

    assert rr.legacy_entries(record) == [legacy]
    assert rr.cycles_used(record, "issue-1001", rr.LOOP_CODE_REVIEW) == 1
    # Preserved exactly as it was: never rewritten, never upgraded.
    assert record.review_cycles[0] == legacy


# ---------------------------------------------------------------------------
# Residuals at the cycle cap — child 885
# ---------------------------------------------------------------------------


def test_at_the_cap_one_residual_is_prepared_per_unresolved_finding(rr: ModuleType) -> None:
    result = _result(rr, outcome="cycle_cap_best_available", cycle=5)
    result.findings = [
        _finding(rr, line=1, status="open"),
        _finding(rr, line=2, status="unresolved"),
        _finding(rr, line=3, status="fixed-verified"),
        _finding(rr, line=4, status="withdrawn"),
        _finding(rr, line=5, status="duplicate-of"),
    ]

    payloads = rr.residual_issue_payloads(result, parent_issue=1001)

    assert len(payloads) == 2
    assert all("#1001" in payload["body"] for payload in payloads)
    assert all(REVISION in payload["body"] for payload in payloads)
    assert all("cycle_cap_best_available" in payload["body"] for payload in payloads)


def test_a_residual_body_names_its_finding_identity(rr: ModuleType) -> None:
    """The residual points back at the finding, so the two never drift apart."""
    result = _result(rr, outcome="cycle_cap_best_available", cycle=5)
    finding = _finding(rr)
    result.findings = [finding]

    payload = rr.residual_issue_payloads(result, parent_issue=1001)[0]

    assert finding.id in payload["body"]
    assert finding.evidence in payload["body"]


def test_filing_the_residuals_is_not_this_modules_job(rr: ModuleType) -> None:
    """Opening an issue is mission-control's ownership lane, not saga's.

    A saga script calling `gh issue` crosses the lane, which
    `tests/test_check_ownership_lanes.py` fails on. This module prepares; the caller
    hands the payloads to mission-control.
    """
    source = (SCRIPTS / "review_result.py").read_text(encoding="utf-8")
    assert "gh issue" not in source
    assert not hasattr(rr, "file_residuals")


# ---------------------------------------------------------------------------
# The derived overall
# ---------------------------------------------------------------------------


def test_the_derived_overall_rounds_half_away_from_zero(rr: ModuleType) -> None:
    """The catalogue's rule, not Python's banker's rounding.

    Two dimensions at 9 and 10 average 9.5 exactly; banker's rounding would give
    9.5 here too, so the case that separates them is one that lands on .x5 at the
    second decimal.
    """
    lens = rr.LensResult(
        lens="correctness",
        strictness="standard",
        scorable=True,
        dimension_scores={"a": 9, "b": 10, "c": 10, "d": 9},
    )
    assert lens.derived_overall() == 9.5

    odd = rr.LensResult(
        lens="correctness",
        strictness="standard",
        scorable=True,
        dimension_scores={"a": 9, "b": 9, "c": 10},
    )
    # 28/3 = 9.333... -> 9.3
    assert odd.derived_overall() == 9.3


def test_a_lens_with_no_scores_has_no_derived_overall(rr: ModuleType) -> None:
    lens = rr.LensResult(lens="adversarial", strictness="baseline", scorable=False)
    assert lens.derived_overall() is None


# ---------------------------------------------------------------------------
# The serialised document
# ---------------------------------------------------------------------------


def test_the_result_declares_v2_and_carries_its_provenance(rr: ModuleType) -> None:
    result = _result(rr)
    result.lens_results = [
        rr.LensResult(
            lens="correctness",
            strictness="standard",
            scorable=True,
            dimension_scores={"a": 9},
            executor={"vendor": "anthropic", "model": "claude-opus-5", "effort": "high"},
            hosting={"session": "review-a", "isolation": "separate session"},
            threshold={"derived_overall_minimum": 9.0, "applicable_dimension_minimum": 7},
        )
    ]

    payload = result.to_dict()

    assert payload["schema"] == "review_result.v2"
    assert payload["revision"] == REVISION
    assert payload["roster_hash"] == "sha256:test"
    assert payload["loop"] == "code_review"
    row = payload["per_lens_results"][0]
    assert row["executor"]["model"] == "claude-opus-5"
    assert row["hosting"]["session"] == "review-a"
    assert row["threshold"]["derived_overall_minimum"] == 9.0
