"""The review formula: rows, modifiers, grades, merge and report-only (issue 148).

Every expected outcome below is transcribed from the program design's tables
(``docs/brainstorms/2026-10-05-saga-review-redesign/plan.md``, "Lens by lens" and "Block, fix later
and note"), independently of ``review_formula.ROWS``, so a mis-transcribed row fails here.
"""

from __future__ import annotations

import importlib.util
import itertools
import json
import random
import socket
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


F = _load("review_formula")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here runs with sockets refused, so a network call fails the test."""

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("review formula tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


# Row: (base outcome, builder reason kind that excuses it, blocks when reproduced)
EXPECTED_ROWS: dict[str, tuple[str, str | None, bool]] = {
    "testing.uncovered-branch": ("blocks", "coverage-gap", False),
    "testing.surviving-mutant": ("blocks", "surviving-mutant", False),
    "testing.test-passes-before-change": ("blocks", "test-passes-before-change", False),
    "testing.test-skipped-in-ci": ("blocks", "test-skipped-in-ci", False),
    "testing.flaky-order-or-network": ("fix-later", None, False),
    "testing.fakes-code-under-test": ("fix-later", None, False),
    "testing.writes-live-system": ("fix-later", None, True),
    "testing.dispute": ("fix-later", None, False),
    "security.scanner-high": ("blocks", "scanner-false-positive", False),
    "security.scanner-medium-low": ("fix-later", None, False),
    "security.secret-in-diff": ("blocks", None, False),
    "security.dependency-high": ("blocks", "scanner-false-positive", False),
    "security.workflow-infra-high": ("blocks", None, False),
    "security.required-test-missing": ("blocks", None, False),
    "security.dispute": ("fix-later", None, False),
    "architecture-maintainability.structural-check-fails": ("blocks", None, False),
    "architecture-maintainability.prose-rule-broken": ("fix-later", None, True),
    "architecture-maintainability.relocated-run-fails": ("blocks", None, False),
    "architecture-maintainability.machine-specific-value": ("fix-later", None, False),
    "architecture-maintainability.undocumented-departure": ("note", None, False),
    "architecture-maintainability.duplicate": ("note", None, False),
    "architecture-maintainability.complexity-dead-code-naming": ("note", None, False),
    "architecture-maintainability.dispute": ("fix-later", None, False),
    "correctness.criterion-without-check": ("blocks", None, False),
    "correctness.type-error": ("blocks", None, False),
    "correctness.pattern.release-shares-cleanup": ("blocks", "pattern-check", False),
    "correctness.pattern.swallowed-error": ("blocks", "pattern-check", False),
    "correctness.pattern.silent-skip": ("blocks", "pattern-check", False),
    "correctness.pattern.naive-time-comparison": ("blocks", "pattern-check", False),
    "correctness.pattern.write-skips-shared-update": ("blocks", "pattern-check", False),
    "correctness.pattern.money-as-float": ("blocks", "pattern-check", False),
    "correctness.declared-question-untested": ("blocks", None, False),
    "correctness.unupdated-mention": ("blocks", "unaffected", False),
    "correctness.unupdated-mention-in-document": ("fix-later", None, False),
    "correctness.workflow-dead-end": ("blocks", None, False),
    "correctness.ci-matrix-fails": ("blocks", None, False),
    "correctness.dispute": ("fix-later", None, False),
    "correctness.tool-error": ("blocks", None, False),
    "correctness.tool-warning": ("fix-later", None, False),
    "correctness.tool-style": ("note", None, False),
    "correctness.tool-curated": ("blocks", None, False),
    "correctness.tool-unscoped": ("fix-later", None, False),
    "security.tool-error": ("blocks", None, False),
    "security.tool-warning": ("fix-later", None, False),
    "security.tool-style": ("note", None, False),
    "security.tool-curated": ("blocks", None, False),
    "security.tool-unscoped": ("fix-later", None, False),
    "security.dependency-medium-low": ("fix-later", None, False),
    "security.workflow-infra-medium-low": ("fix-later", None, False),
    "testing.tool-error": ("blocks", None, False),
    "testing.tool-warning": ("fix-later", None, False),
    "testing.tool-style": ("note", None, False),
    "testing.tool-curated": ("blocks", None, False),
    "testing.tool-unscoped": ("fix-later", None, False),
    "architecture-maintainability.tool-error": ("blocks", None, False),
    "architecture-maintainability.tool-warning": ("fix-later", None, False),
    "architecture-maintainability.tool-style": ("note", None, False),
    "architecture-maintainability.tool-curated": ("blocks", None, False),
    "architecture-maintainability.tool-unscoped": ("fix-later", None, False),
}
FIXED_ROWS = sorted(EXPECTED_ROWS)
JUDGED_ROWS = {
    "judged.harm-reproduced",
    "judged.harm-traced",
    "judged.harm-misuse",
    "judged.visible",
    "judged.upkeep",
}


def tool_finding(row: str, ident: str = "rf:1", **over: Any) -> dict[str, Any]:
    finding = {
        "id": ident,
        "lens": row.split(".")[0],
        "rule": {"row": row, "ref": "example-rule"},
        "source": {"kind": "tool", "name": "example-tool", "version": "1.0"},
        "language": "python",
        "consequence": None,
        "trigger": None,
        "evidence": "tool-result",
        "degraded": False,
        "consequence_jev": None,
        "unconfirmed": False,
    }
    finding.update(over)
    return finding


def llm_finding(
    lens: str = "correctness",
    consequence: str = "wrong-result-reported-as-success",
    trigger: str = "normal-use",
    evidence: str = "reproduced",
    jev: str | None = "same",
    ident: str = "rf:2",
    **over: Any,
) -> dict[str, Any]:
    finding = {
        "id": ident,
        "lens": lens,
        "rule": {"row": "judged", "ref": f"{lens}.q-example"},
        "source": {"kind": "llm", "name": "reviewer", "model": "example-model"},
        "language": "python",
        "consequence": consequence,
        "trigger": trigger,
        "evidence": evidence,
        "degraded": False,
        "consequence_jev": consequence if jev == "same" else jev,
        "unconfirmed": jev is None and evidence == "reproduced",
    }
    finding.update(over)
    return finding


def reason(finding_id: str, kind: str) -> dict[str, Any]:
    return {"unit": "U1", "reasons": [{"kind": kind, "finding_id": finding_id, "text": "why"}]}


def severity(finding: dict[str, Any], **kwargs: Any) -> str:
    return F.outcome(finding, **kwargs)["severity"]


def grades(result: dict[str, Any]) -> dict[str, str]:
    return {entry["lens"]: entry["grade"] for entry in result["lens_grades"]}


# --- every row ----------------------------------------------------------------------------------


def test_registry_holds_exactly_the_tested_rows() -> None:
    assert set(F.ROWS) == set(EXPECTED_ROWS) | JUDGED_ROWS


@pytest.mark.parametrize("row", FIXED_ROWS)
def test_row_base_outcome(row: str) -> None:
    expected, _, _ = EXPECTED_ROWS[row]
    result = F.outcome(tool_finding(row))
    assert result["severity"] == expected
    assert result["severity_basis"]["row"] == row


@pytest.mark.parametrize("row", [row for row in FIXED_ROWS if EXPECTED_ROWS[row][1]])
def test_row_with_the_builder_reason_it_allows_is_a_note(row: str) -> None:
    kind = EXPECTED_ROWS[row][1]
    result = F.outcome(tool_finding(row), builder_records=[reason("rf:1", str(kind))])
    assert result["severity"] == "note"
    assert "excused" in result["severity_basis"]["modifiers"]


def test_reason_excuses_only_its_own_testing_row() -> None:
    """Each new testing kind clears its own row, and neither kind clears the other."""
    pre = "testing.test-passes-before-change"
    skipped = "testing.test-skipped-in-ci"
    assert severity(tool_finding(pre)) == "blocks"
    excused = F.outcome(
        tool_finding(pre), builder_records=[reason("rf:1", "test-passes-before-change")]
    )
    assert excused["severity"] == "note"
    assert "excused" in excused["severity_basis"]["modifiers"]
    assert severity(
        tool_finding(pre), builder_records=[reason("rf:1", "test-skipped-in-ci")]
    ) == "blocks"
    assert severity(tool_finding(skipped)) == "blocks"
    cleared = F.outcome(
        tool_finding(skipped), builder_records=[reason("rf:1", "test-skipped-in-ci")]
    )
    assert cleared["severity"] == "note"
    assert "excused" in cleared["severity_basis"]["modifiers"]
    assert severity(
        tool_finding(skipped), builder_records=[reason("rf:1", "test-passes-before-change")]
    ) == "blocks"
    assert severity(
        tool_finding(pre), builder_records=[reason("rf:other", "test-passes-before-change")]
    ) == "blocks"


@pytest.mark.parametrize("row", FIXED_ROWS)
def test_row_ignores_a_reason_of_another_kind_or_finding(row: str) -> None:
    allowed = EXPECTED_ROWS[row][1]
    other = next(kind for kind in F.REASON_KINDS if kind != allowed)
    records = [reason("rf:1", other)]
    if allowed:
        records.append(reason("rf:other", allowed))
    assert severity(tool_finding(row), builder_records=records) == EXPECTED_ROWS[row][0]


@pytest.mark.parametrize("row", [row for row in FIXED_ROWS if EXPECTED_ROWS[row][2]])
def test_row_blocks_when_reproduced(row: str) -> None:
    finding = tool_finding(
        row,
        source={"kind": "llm", "name": "reviewer", "model": "example-model"},
        evidence="reproduced",
        consequence="break-in-supported-use",
        consequence_jev="break-in-supported-use",
        trigger="normal-use",
    )
    result = F.outcome(finding)
    assert result["severity"] == "blocks"
    assert "reproduced" in result["severity_basis"]["modifiers"]


@pytest.mark.parametrize(
    ("name", "consequence", "trigger", "evidence", "row", "expected"),
    [
        ("harm-normal-use-reproduced", "data-lost-or-corrupted", "normal-use", "reproduced",
         "judged.harm-reproduced", "blocks"),
        ("harm-legitimate-condition-reproduced", "two-holders-of-one-exclusive-thing",
         "concurrency", "reproduced", "judged.harm-reproduced", "blocks"),
        ("harm-traced", "money-or-resources-wrongly-moved", "retry", "traced",
         "judged.harm-traced", "fix-later"),
        ("harm-suspected", "required-behaviour-missing", "normal-use", "suspected",
         "judged.harm-traced", "fix-later"),
        ("harm-misuse-reproduced", "security-boundary-crossed", "misuse-only", "reproduced",
         "judged.harm-misuse", "fix-later"),
        ("visible-reproduced", "misleads-a-person", "normal-use", "reproduced",
         "judged.visible", "fix-later"),
        ("visible-traced", "fails-loudly-and-recoverably", "interrupt", "traced",
         "judged.visible", "fix-later"),
        ("upkeep", "costs-future-work", "normal-use", "reproduced", "judged.upkeep", "note"),
        ("upkeep-style", "style", "normal-use", "traced", "judged.upkeep", "note"),
    ],
)
def test_judged_findings_table(
    name: str, consequence: str, trigger: str, evidence: str, row: str, expected: str
) -> None:
    result = F.outcome(llm_finding(consequence=consequence, trigger=trigger, evidence=evidence))
    assert result["severity_basis"]["row"] == row, name
    assert result["severity"] == expected, name


def test_judged_row_cannot_be_cited_by_a_source() -> None:
    with pytest.raises(F.FormulaError, match="rule.row"):
        F.outcome(tool_finding("judged.harm-reproduced-typo"))


# --- no reviewer-written severity --------------------------------------------------------------


@pytest.mark.parametrize("key", ["severity", "severity_basis", "flags", "enforced"])
def test_a_preset_computed_field_is_refused(key: str) -> None:
    with pytest.raises(F.FormulaError, match=key):
        F.compute({"findings": [{**tool_finding("security.secret-in-diff"), key: "note"}]})


# --- the unreproduced-LLM cap and Jev ----------------------------------------------------------


def test_an_unreproduced_llm_finding_is_never_worse_than_fix_later() -> None:
    for consequence, trigger, evidence in itertools.product(
        F.CONSEQUENCES, F.TRIGGERS, ("traced", "suspected")
    ):
        assert severity(
            llm_finding(consequence=consequence, trigger=trigger, evidence=evidence, jev=None,
                        unconfirmed=False)
        ) in ("fix-later", "note"), (consequence, trigger, evidence)
    for row in FIXED_ROWS:
        finding = tool_finding(
            row,
            source={"kind": "llm", "name": "reviewer", "model": "example-model"},
            evidence="traced",
        )
        assert severity(finding) in ("fix-later", "note"), row


def test_llm_and_jev_disagree_the_lower_applies_and_is_flagged() -> None:
    result = F.outcome(
        llm_finding(consequence="money-or-resources-wrongly-moved", jev="misleads-a-person")
    )
    assert result["severity"] == "fix-later"
    assert result["severity_basis"]["row"] == "judged.visible"
    assert "consequence-disagreement" in result["flags"]


def test_llm_and_jev_agree_no_flag() -> None:
    result = F.outcome(llm_finding(consequence="money-or-resources-wrongly-moved"))
    assert result["severity"] == "blocks"
    assert result["flags"] == []


def test_two_different_harms_keep_the_llm_pick_and_are_flagged() -> None:
    result = F.outcome(
        llm_finding(consequence="data-lost-or-corrupted", jev="break-in-supported-use")
    )
    assert result["severity"] == "blocks"
    assert "consequence-disagreement" in result["flags"]


def test_jev_cannot_answer_the_llm_pick_applies_and_is_unconfirmed() -> None:
    result = F.outcome(llm_finding(consequence="money-or-resources-wrongly-moved", jev=None))
    assert result["severity"] == "blocks"
    assert result["severity_basis"]["row"] == "judged.harm-reproduced"
    assert "unconfirmed" in result["flags"]


def test_jev_only_never_blocks() -> None:
    finding = tool_finding(
        "testing.surviving-mutant",
        source={"kind": "classifier", "name": "jev", "model": "example-classifier"},
    )
    result = F.outcome(finding)
    assert result["severity"] == "fix-later"
    assert "classifier-only" in result["severity_basis"]["modifiers"]


# --- degraded and disputes ---------------------------------------------------------------------


def test_a_degraded_blocking_input_counts_as_fix_later_and_is_marked() -> None:
    result = F.compute(
        {"findings": [tool_finding("testing.surviving-mutant", degraded=True)]}
    )
    finding = result["findings"][0]
    assert finding["severity"] == "fix-later"
    assert "degraded" in finding["severity_basis"]["modifiers"]
    testing = next(entry for entry in result["lens_grades"] if entry["lens"] == "testing")
    assert testing["degraded_inputs"] == [{"finding_id": "rf:1"}]
    assert testing["grade"] == "B"


@pytest.mark.parametrize("lens", ["correctness", "security", "testing",
                                  "architecture-maintainability"])
def test_a_dispute_is_fix_later_flagged_for_merge_confirmation(lens: str) -> None:
    finding = tool_finding(
        f"{lens}.dispute", source={"kind": "llm", "name": "reviewer", "model": "example-model"},
        evidence="traced",
    )
    result = F.outcome(finding)
    assert result["severity"] == "fix-later"
    assert "merge-confirmation" in result["flags"]


# --- grades and merge --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("blocks", "fix_later", "expected"),
    [(0, 0, "A"), (0, 1, "B"), (0, 2, "B"), (0, 3, "C"), (0, 10, "C"), (1, 0, "D"),
     (1, 5, "D"), (2, 0, "F"), (7, 7, "F")],
)
def test_grade_boundaries(blocks: int, fix_later: int, expected: str) -> None:
    assert F.grade(blocks, fix_later) == expected


def test_notes_never_move_the_grade_and_fix_later_never_adds_up_to_a_block() -> None:
    notes = [tool_finding("architecture-maintainability.duplicate", f"rf:n{i}") for i in range(4)]
    later = [tool_finding("security.scanner-medium-low", f"rf:f{i}") for i in range(12)]
    result = F.compute({"findings": notes + later, "may_block": {"security": {"python": True}}})
    assert grades(result)["architecture-maintainability"] == "A"
    assert grades(result)["security"] == "C"
    assert result["merge"]["allowed"] is True


def test_merge_needs_every_lens_at_c_or_better() -> None:
    may_block = {lens: {"python": True} for lens in F.LENSES}
    clean = F.compute(
        {"findings": [tool_finding("security.scanner-medium-low", f"rf:{i}") for i in range(3)],
         "may_block": may_block}
    )
    assert grades(clean)["security"] == "C" and clean["merge"]["allowed"] is True
    blocked = F.compute(
        {"findings": [tool_finding("correctness.type-error")], "may_block": may_block}
    )
    assert grades(blocked)["correctness"] == "D"
    assert blocked["merge"] == {
        "allowed": False, "blocking": ["rf:1"], "report_only_blocks": []
    }


# --- report-only -------------------------------------------------------------------------------


def test_with_no_calibration_answer_every_lens_reports_only_and_keeps_its_grade() -> None:
    result = F.compute(
        {"findings": [llm_finding(consequence="money-or-resources-wrongly-moved",
                                  trigger="retry")]}
    )
    assert grades(result)["correctness"] == "D"
    assert result["merge"] == {
        "allowed": True, "blocking": [], "report_only_blocks": ["rf:2"]
    }
    correctness = next(entry for entry in result["lens_grades"] if entry["lens"] == "correctness")
    assert correctness["may_block"] == {"python": False}


@pytest.mark.parametrize("harm", ["data-lost-or-corrupted", "security-boundary-crossed"])
def test_a_reproduced_always_blocking_harm_blocks_a_report_only_lens(harm: str) -> None:
    result = F.compute({"findings": [llm_finding(lens="security", consequence=harm)]})
    assert result["merge"]["allowed"] is False
    assert result["merge"]["blocking"] == ["rf:2"]
    assert "always-blocks" in result["findings"][0]["severity_basis"]["modifiers"]


def test_a_traced_always_blocking_harm_does_not_block_a_report_only_lens() -> None:
    result = F.compute(
        {"findings": [llm_finding(consequence="data-lost-or-corrupted", evidence="traced")]}
    )
    assert result["merge"]["allowed"] is True


def test_a_lens_that_may_block_enforces_any_block_for_that_language_only() -> None:
    finding = llm_finding(consequence="money-or-resources-wrongly-moved")
    on = F.compute({"findings": [finding], "may_block": {"correctness": {"python": True}}})
    assert on["merge"]["allowed"] is False
    other = F.compute({"findings": [finding], "may_block": {"correctness": {"swift": True}}})
    assert other["merge"]["allowed"] is True


# --- determinism -------------------------------------------------------------------------------


def _mixed_inputs() -> dict[str, Any]:
    return {
        "findings": [
            tool_finding("security.scanner-medium-low", "rf:a"),
            llm_finding(ident="rf:b"),
            tool_finding("testing.uncovered-branch", "rf:c"),
            tool_finding("architecture-maintainability.duplicate", "rf:d"),
        ],
        "measurements": [
            {"lens": "testing", "row": "testing.uncovered-branch", "metric": "branch coverage",
             "value": 0.8, "threshold": 0.9, "direction": "at-least"},
            {"lens": "testing", "row": "testing.surviving-mutant", "metric": "mutation score",
             "value": 0.95, "threshold": 0.9, "direction": "at-least"},
        ],
        "builder_records": [reason("rf:c", "coverage-gap")],
        "may_block": {"testing": {"python": True}},
        "degraded_inputs": [
            {"lens": "security", "language": "python", "input": "dependency audit",
             "tool": "pip-audit", "reason": "tool missing"}
        ],
    }


def test_the_same_input_twice_gives_identical_output() -> None:
    first = json.dumps(F.compute(_mixed_inputs()), sort_keys=True)
    second = json.dumps(F.compute(_mixed_inputs()), sort_keys=True)
    assert first == second


def test_input_order_does_not_change_the_output() -> None:
    inputs = _mixed_inputs()
    expected = json.dumps(F.compute(inputs), sort_keys=True)
    shuffled = dict(inputs)
    for key in ("findings", "measurements", "degraded_inputs"):
        items = list(inputs[key])
        random.Random(7).shuffle(items)
        shuffled[key] = list(reversed(items))
    assert json.dumps(F.compute(shuffled), sort_keys=True) == expected


def test_measurements_record_their_condition_and_never_move_the_grade() -> None:
    result = F.compute(_mixed_inputs())
    conditions = {m["metric"]: m["condition"] for m in result["measurements"]}
    assert conditions == {"branch coverage": "missed", "mutation score": "met"}
    testing = next(entry for entry in result["lens_grades"] if entry["lens"] == "testing")
    assert testing["grade"] == "A"  # the uncovered branch is excused; the missed threshold is not counted


# --- plan.md's three worked examples -----------------------------------------------------------


def test_worked_example_blocks_retry_charges_twice() -> None:
    charge = llm_finding(consequence="money-or-resources-wrongly-moved", trigger="retry")
    result = F.compute({"findings": [charge]})
    assert grades(result) == {
        "correctness": "D", "security": "A", "testing": "A", "architecture-maintainability": "A"
    }


def test_worked_example_passes_with_fix_later_items() -> None:
    scanner = tool_finding("security.scanner-medium-low", "rf:s")
    tenant = llm_finding(
        lens="security", consequence="security-boundary-crossed", evidence="traced",
        jev=None, unconfirmed=False, ident="rf:t",
    )
    readme = tool_finding(
        "correctness.unupdated-mention-in-document", "rf:r", language="markdown"
    )
    result = F.compute({"findings": [scanner, tenant, readme]})
    assert grades(result)["security"] == "B"
    assert grades(result)["correctness"] == "B"
    assert result["merge"]["allowed"] is True


def test_worked_example_degraded_swift_change() -> None:
    mutation = tool_finding(
        "testing.surviving-mutant", "rf:m", language="swift", degraded=True,
        source={"kind": "llm", "name": "reviewer", "model": "example-model"}, evidence="traced",
    )
    missing_audit = {"lens": "security", "language": "swift", "input": "dependency audit",
                     "tool": "none available", "reason": "no Swift dependency-audit tool"}
    result = F.compute({"findings": [mutation], "degraded_inputs": [missing_audit]})
    by_lens = {entry["lens"]: entry for entry in result["lens_grades"]}
    assert by_lens["testing"]["grade"] == "B" and by_lens["testing"]["degraded_inputs"]
    assert by_lens["security"]["grade"] == "A"
    assert by_lens["security"]["degraded_inputs"] == [missing_audit]
    assert result["merge"]["allowed"] is True


# --- command line ------------------------------------------------------------------------------


def test_compute_command_prints_the_result(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    inputs = tmp_path / "inputs.json"
    inputs.write_text(json.dumps(_mixed_inputs()), encoding="utf-8")
    assert F.main(["compute", str(inputs)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == json.loads(json.dumps(F.compute(_mixed_inputs())))


def test_compute_command_refuses_a_preset_severity(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inputs = tmp_path / "inputs.json"
    finding = {**tool_finding("correctness.type-error"), "severity": "note"}
    inputs.write_text(json.dumps({"findings": [finding]}), encoding="utf-8")
    assert F.main(["compute", str(inputs)]) == 1
    assert "severity" in capsys.readouterr().err


# --- item 6: tool findings the lens tables do not name -----------------------------------------


@pytest.mark.parametrize("lens", list(F.LENSES))
def test_tool_levels_use_the_row_for_that_lens(lens: str) -> None:
    """Error blocks, warning is fix later, and style and information are the same note."""
    error = F.tool_row(lens, "error", "E1", ())
    warning = F.tool_row(lens, "warning", "W1", ())
    style = F.tool_row(lens, "style", "S1", ())
    info = F.tool_row(lens, "info", "I1", ())
    assert error == f"{lens}.tool-error"
    assert F.ROWS[error].lens == lens
    assert severity(tool_finding(error)) == "blocks"
    assert severity(tool_finding(warning)) == "fix-later"
    assert style.endswith(".tool-style") and info.endswith(".tool-style")
    assert severity(tool_finding(info)) == "note"
    unscoped = F.tool_row(lens, None, "U1", ())
    curated = F.tool_row(lens, None, "U1", ("U1",))
    assert unscoped.endswith(".tool-unscoped")
    assert severity(tool_finding(unscoped)) == "fix-later"
    assert curated.endswith(".tool-curated")
    excused = severity(
        tool_finding(curated),
        builder_records=[reason("rf:1", "scanner-false-positive")],
    )
    assert excused == "blocks"


def test_a_dependency_with_no_score_blocks_until_a_false_positive_reason() -> None:
    row = F.dependency_row(None)
    assert row == "security.dependency-high"
    assert severity(tool_finding(row, "rf:dep")) == "blocks"
    noted = severity(
        tool_finding(row, "rf:dep"),
        builder_records=[reason("rf:dep", "scanner-false-positive")],
    )
    assert noted == "note"


def test_medium_low_and_zero_dependency_scores_are_fix_later() -> None:
    for score in (6.9, 4.0, 3.9, 0.1, 0.0):
        row = F.dependency_row(score)
        assert row == "security.dependency-medium-low"
        assert severity(tool_finding(row)) == "fix-later"
    assert F.dependency_row(7.0) == "security.dependency-high"
    assert F.dependency_row(9.0) == "security.dependency-high"


def test_medium_and_low_workflow_words_are_fix_later() -> None:
    for word in ("medium", "low"):
        row = F.workflow_row(word)
        assert row == "security.workflow-infra-medium-low"
        assert severity(tool_finding(row)) == "fix-later"


def test_two_tools_reporting_one_advisory_take_the_scored_severity() -> None:
    merged = F.merge_advisories(
        [
            {
                "advisory_ids": ["GHSA-EXAMPLE", "CVE-2026-0000"],
                "tool": "osv-scanner",
                "score": None,
                "row": "security.dependency-high",
            },
            {
                "advisory_ids": ["CVE-2026-0000"],
                "tool": "pip-audit",
                "score": 5.0,
                "row": "security.dependency-medium-low",
            },
        ]
    )
    assert len(merged) == 1
    assert merged[0]["row"] == "security.dependency-medium-low"
    assert merged[0]["canonical_id"] == "CVE-2026-0000"
    assert severity(tool_finding(merged[0]["row"])) == "fix-later"


def test_two_unscored_advisories_merge_into_one_block() -> None:
    merged = F.merge_advisories(
        [
            {
                "advisory_ids": ["GHSA-EXAMPLE"],
                "tool": "osv-scanner",
                "score": None,
                "row": "security.dependency-high",
            },
            {
                "advisory_ids": ["GHSA-EXAMPLE", "CVE-2026-0000"],
                "tool": "pip-audit",
                "score": None,
                "row": "security.dependency-high",
            },
        ]
    )
    assert len(merged) == 1
    assert merged[0]["canonical_id"] == "CVE-2026-0000"
    assert severity(tool_finding(merged[0]["row"])) == "blocks"
