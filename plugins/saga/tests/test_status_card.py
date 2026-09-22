"""Unit tests for the shared glyph-card renderer and per-surface projections (U1/U3, #278).

Tests are falsifiable and state-driven — they exercise real behaviour rather than keyword
presence.  Conventions mirror tests/test_completeness_gate.py and tests/test_outcome_projection.py:
dynamic module load via importlib.util.spec_from_file_location, factory helpers for specs,
derived-state asserts.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import types
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "saga" / "scripts" / "status_card.py"


def _load() -> ModuleType:
    """Dynamically load status_card as a module (mirrors test_completeness_gate.py)."""
    spec = importlib.util.spec_from_file_location("status_card", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["status_card"] = module
    spec.loader.exec_module(module)
    return module


SC = _load()


# ── Factory helpers ────────────────────────────────────────────────────────────────────────────


def _header(surface: str = "/work", id: str = "saga-1", round: int | None = None) -> object:
    return SC.CardHeader(surface=surface, id=id, round=round)


def _row(
    key: str,
    label: str,
    state_name: str,
    ref: str | None = None,
) -> object:
    state = SC.CardState(state_name)
    return SC.CardRow(key=key, label=label, state=state, ref=ref)


def _gate_spec(rows: list[object]) -> Any:
    return SC.CardSpec(
        archetype="gate-sequence",
        header=_header(),
        rows=tuple(rows),
    )


def _summary_spec(rows: list[object]) -> Any:
    return SC.CardSpec(
        archetype="summary-projection",
        header=_header(surface="/outcome", id="o-1"),
        rows=tuple(rows),
    )


# ── Test 1: both archetypes render a well-formed card ─────────────────────────────────────────


def test_gate_sequence_renders_well_formed() -> None:
    """A gate-sequence card renders with borders, a header, and one body line per row."""
    spec = _gate_spec(
        [
            _row("impl", "Implementation", "done", ref="saga-1/tick.md"),
            _row("tests", "Tests", "in-progress", ref="saga-1/gate_verdicts"),
            _row("merge", "Merge", "not-reached"),
        ]
    )
    card = SC.render(spec)

    lines = card.splitlines()
    # Top border, header, separator, 3 body rows, bottom border = 7 minimum
    assert len(lines) >= 7, f"too few lines: {len(lines)}"
    assert lines[0] == "═" * SC._CARD_WIDTH
    assert "/work" in lines[1]
    assert lines[2] == "═" * SC._CARD_WIDTH
    # Bottom border is the 7th line (index 6)
    assert lines[6] == "═" * SC._CARD_WIDTH


def test_summary_projection_renders_well_formed() -> None:
    """A summary-projection card renders the full fixed row set."""
    spec = _summary_spec(
        [
            _row("progress", "Progress", "in-progress", ref="o-1/spec.md"),
            _row("frontier", "Ready frontier", "done", ref="o-1/store"),
            _row("blocked", "Blocked", "blocked", ref="o-1/store#blocked"),
            _row("attention", "Attention", "not-reached"),
        ]
    )
    card = SC.render(spec)
    assert "Progress" in card
    assert "Ready frontier" in card
    assert "Attention" in card


# ── Test 2: constant size (AE1) ───────────────────────────────────────────────────────────────


def _body_line_count(card: str, card_width: int) -> int:
    """Return the number of body lines between the header separator and the bottom border."""
    borders_seen = 0
    in_body = False
    count = 0
    for line in card.splitlines():
        if line == "═" * card_width:
            borders_seen += 1
            if borders_seen == 2:
                in_body = True  # body starts after the 2nd border (header separator)
            elif borders_seen == 3:
                break  # body ends at the 3rd border (bottom border)
        elif in_body:
            count += 1
    return count


def test_gate_sequence_constant_height_by_state_change() -> None:
    """AE1: gate-sequence card body has the same line count when 1 vs all 5 rows are done."""
    five_rows = [_row(f"g{i}", f"Gate {i}", "done", ref=f"ref-{i}") for i in range(5)]
    spec_all_done = _gate_spec(five_rows)

    one_done = [_row("g0", "Gate 0", "done", ref="ref-0")] + [
        _row(f"g{i}", f"Gate {i}", "not-reached") for i in range(1, 5)
    ]
    spec_one_done = _gate_spec(one_done)

    card_all = SC.render(spec_all_done)
    card_one = SC.render(spec_one_done)

    assert _body_line_count(card_all, SC._CARD_WIDTH) == 5
    assert _body_line_count(card_one, SC._CARD_WIDTH) == 5


def test_summary_projection_constant_height_for_varying_summary_counts() -> None:
    """AE1: a summary-projection card has identical body height for 3-item and 30-item summaries.

    The caller is responsible for collapsing N dynamic items into the fixed row set; the renderer
    always emits exactly len(rows) body lines.
    """

    # 4-row summary-projection regardless of how many items the caller summarised.
    def _make_summary(note: str) -> object:
        return _summary_spec(
            [
                _row("progress", f"Progress ({note})", "in-progress", ref="o/spec"),
                _row("frontier", "Ready frontier", "done", ref="o/store"),
                _row("blocked", "Blocked", "blocked", ref="o/store#b"),
                _row("attention", "Attention", "not-reached"),
            ]
        )

    card_3 = SC.render(_make_summary("3 items"))
    card_30 = SC.render(_make_summary("30 items"))

    # Body height must be identical (4 rows in both cases).
    assert _body_line_count(card_3, SC._CARD_WIDTH) == 4
    assert _body_line_count(card_30, SC._CARD_WIDTH) == 4
    assert _body_line_count(card_3, SC._CARD_WIDTH) == _body_line_count(card_30, SC._CARD_WIDTH)


# ── Test 3: determinism + no writable status field (AE2 / R2) ────────────────────────────────


def test_render_is_deterministic() -> None:
    """AE2: the same CardSpec renders byte-identical output on every call."""
    spec = _gate_spec(
        [
            _row("impl", "Implementation", "done", ref="tick.md"),
            _row("tests", "Tests", "in-progress", ref="gate_verdicts"),
            _row("merge", "Merge", "not-reached"),
        ]
    )
    assert SC.render(spec) == SC.render(spec)
    assert SC.render(spec) == SC.render(spec)


def test_no_writable_status_field_on_card_spec() -> None:
    """AE2/R2: there is no field on CardSpec or CardRow that sets the displayed glyph independently of state.

    The glyph is a pure function of state via GLYPH_MAP — you cannot set a 'display_glyph'
    override on the spec.
    """
    import dataclasses

    row_fields = {f.name for f in dataclasses.fields(SC.CardRow)}
    # These would be violation fields — none should exist.
    forbidden = {"display_glyph", "override_glyph", "status_override", "display_status"}
    assert not (row_fields & forbidden), f"writable display fields found: {row_fields & forbidden}"

    spec_fields = {f.name for f in dataclasses.fields(SC.CardSpec)}
    assert not (spec_fields & forbidden), (
        f"writable display fields found: {spec_fields & forbidden}"
    )


def test_glyph_is_pure_function_of_state() -> None:
    """AE2: changing only the state of a row changes only its glyph in the rendered output."""
    spec_done = _gate_spec([_row("r", "My Gate", "done", ref="r.md")])
    spec_fail = _gate_spec([_row("r", "My Gate", "failed", ref="r.md")])

    card_done = SC.render(spec_done)
    card_fail = SC.render(spec_fail)

    assert SC.GLYPH_MAP["done"] in card_done
    assert SC.GLYPH_MAP["failed"] in card_fail
    # The done glyph must not appear in the failed card's body row.
    body_done = [ln for ln in card_done.splitlines() if "My Gate" in ln][0]
    body_fail = [ln for ln in card_fail.splitlines() if "My Gate" in ln][0]
    assert SC.GLYPH_MAP["done"] in body_done
    assert SC.GLYPH_MAP["failed"] in body_fail
    assert SC.GLYPH_MAP["done"] not in body_fail


# ── Test 4: failure and halt representable (AE9) ─────────────────────────────────────────────


def test_failed_row_renders_glyph_and_footer_ref() -> None:
    """AE9: a row with state=failed renders ✗ and carries a footer ref."""
    spec = _gate_spec([_row("tests", "Tests", "failed", ref="saga/gate_verdicts")])
    card = SC.render(spec)

    assert "✗" in card
    assert "[1] saga/gate_verdicts" in card


def test_halted_row_renders_glyph_and_footer_ref() -> None:
    """AE9: a row with state=halted renders ‖ and carries a footer ref."""
    spec = _gate_spec([_row("review", "Reviewer panel", "halted", ref="saga/review.md")])
    card = SC.render(spec)

    assert "‖" in card
    assert "[1] saga/review.md" in card


def test_failed_and_halted_distinct_glyphs() -> None:
    """AE9: failed and halted use distinct, visually unmistakable glyphs."""
    assert SC.GLYPH_MAP["failed"] != SC.GLYPH_MAP["halted"]
    assert SC.GLYPH_MAP["failed"] == "✗"
    assert SC.GLYPH_MAP["halted"] == "‖"


# ── Test 5: unknown/not-reached carries no footer ref (AE7 / R13) ────────────────────────────


def test_not_reached_row_carries_no_footer_index() -> None:
    """AE7/R13: a NOT_REACHED cell occupies its body line but has no footer index."""
    spec = _gate_spec(
        [
            _row("impl", "Implementation", "done", ref="tick.md"),
            _row("merge", "Merge", "not-reached"),  # no ref; should not appear in footer
        ]
    )
    card = SC.render(spec)

    # Body: done row gets [1], not-reached row gets nothing.
    assert "·" in card  # not-reached glyph present
    assert "[1]" in card  # done row is indexed
    assert "[2]" not in card  # not-reached row is NOT indexed


def test_not_reached_ref_is_silently_ignored() -> None:
    """R13: even if a ref is supplied for a NOT_REACHED row, it must not appear in the footer."""
    spec = _gate_spec([_row("x", "X", "not-reached", ref="should-not-appear-in-footer")])
    card = SC.render(spec)

    assert "should-not-appear-in-footer" not in card
    assert "[1]" not in card


# ── Test 6: label and glyph rename via display maps (AE8 / R9) ───────────────────────────────


def test_glyph_map_rename_changes_only_display_not_wire_state() -> None:
    """AE8/R9: changing GLYPH_MAP changes only the rendered glyph; the wire state value is unchanged."""
    original_glyph = SC.GLYPH_MAP["done"]

    try:
        SC.GLYPH_MAP["done"] = "OK"  # operator-driven glyph swap

        spec = _gate_spec([_row("r", "My Row", "done", ref="r.md")])
        card = SC.render(spec)

        # Rendered card shows the new glyph.
        body_line = [ln for ln in card.splitlines() if "My Row" in ln][0]
        assert "OK" in body_line, "renamed glyph not reflected in render"
        assert original_glyph not in body_line, "old glyph should be gone after map edit"

        # The wire state value on the row is unchanged — it is the frozen enum value "done".
        row = spec.rows[0]
        assert str(row.state) == "done", "wire state value must not change"
        assert row.state == SC.CardState.DONE
    finally:
        SC.GLYPH_MAP["done"] = original_glyph  # restore


def test_operator_label_map_rename_changes_only_label_not_wire_state() -> None:
    """AE8/R9: changing OPERATOR_LABEL_MAP changes only the label returned by display_state_label;
    the stored wire state value is not affected."""
    original_label = SC.OPERATOR_LABEL_MAP["blocked"]

    try:
        SC.OPERATOR_LABEL_MAP["blocked"] = "stalled"

        assert SC.display_state_label(SC.CardState.BLOCKED) == "stalled"
        # Wire value is still the enum member's value string.
        assert SC.CardState.BLOCKED.value == "blocked"
    finally:
        SC.OPERATOR_LABEL_MAP["blocked"] = original_label  # restore


# ── Test 7: --self-test CLI entrypoint (mirrors test_completeness_gate.py::test_self_test_cli) ──


def test_self_test_cli() -> None:
    """The --self-test flag runs clean and emits expected status tokens."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--self-test"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.returncode == 0
    # Self-test must confirm glyphs and structural checks.
    assert "glyphs-present" in result.stdout
    assert "footer-indexed" in result.stdout
    assert "not-reached-no-index" in result.stdout
    assert "determinism" in result.stdout
    assert "self-test: all checks passed" in result.stdout


# ── U3: per-surface projection builders ──────────────────────────────────────────────────────────
# Fixture helpers: use types.SimpleNamespace to mock Saga objects without importing the Saga
# dataclass (which would create a hard import dependency between the test and saga.py internals).

_ABSENT_SENTINEL = object()  # placeholder — the real ABSENT is not a list; isinstance check passes


def _mock_saga(
    saga_id: str = "saga-test-1",
    phase_status: str = "pending",
    review_paths: object = _ABSENT_SENTINEL,
    qa_paths: object = _ABSENT_SENTINEL,
    gate_verdicts: object = _ABSENT_SENTINEL,
    pr_refs: object = _ABSENT_SENTINEL,
    head_sha: str = "",
    destination: str = "plan-only",
) -> object:
    """Build a lightweight mock saga object for projection tests."""
    # Use a non-list sentinel for ABSENT fields (isinstance(obj, list) returns False for sentinel).
    return types.SimpleNamespace(
        saga_id=saga_id,
        phase_status=phase_status,
        review_paths=review_paths,
        qa_paths=qa_paths,
        gate_verdicts=gate_verdicts,
        pr_refs=pr_refs,
        head_sha=head_sha,
        destination=destination,
    )


# ── Fixture text for /code-review tests (based on real artifact format) ───────────────────────────

_CODE_REVIEW_CLEAN = """\
# Code Review — feature-branch (#42)

**Verdict:** **CLEAN** — approved for merge.

Scope Check: CLEAN

## Plan-completion audit

| Unit | Status | Evidence |
|------|--------|----------|
| U1   | DONE   | tests pass |
| U2   | DONE   | reviewer confirmed |

## Lenses applied: security · architecture · testing

Reviewers: Claude (primary) + agy (fan-out second opinion).

## Validators

All validators passed.
"""

_CODE_REVIEW_BLOCKED = """\
# Code Review — hotfix-branch (#99)

**Verdict:** **BLOCKED** — P0 unresolved.

Scope Check: DRIFT DETECTED

## Plan-completion audit

| Unit | Status | Evidence |
|------|--------|----------|
| U1   | DONE   | ok |
| U2   | NOT-DONE | missing tests |

## Lenses: security

Reviewers: Claude.
"""
# ── Fixture text for /qa tests (based on real qa-issue-201-2026-06-07.md format) ──────────────────
# ── Fixture text for /qa tests ────────────────────────────────────────────────────────────────────
# These are functional-test comments as `qa_strategies.py` prints them (issue 1039), not the
# `docs/qa/` report with a health score that `/qa` used to write. The projection was retargeted
# with them: a fixture that still carried a score would have kept the old contract alive in a test
# while the shipped surface had moved on.

_QA_PASS = """\
---
type: qa
verdict: pass
boundary: non-production
route: close
---

## Functional test

**Verdict: `pass`** — every required strategy passed

Boundary: `non-production`. Route: `close`.

### Selection

| Strategy | Required | Why it was selected |
|---|---|---|
| `cli-smoke` | yes | the profile marks this strategy required |
| `installed-surface` | yes | the profile pattern 'plugins/*/skills/**' matched |

### Results

| Strategy | Result | What it proved, or why it did not |
|---|---|---|
| `cli-smoke` | `passed` | 2 declared invocation(s) exited zero |
| `installed-surface` | `passed` | 2 installed plugin root(s) resolve 1.0.0 |
"""

_QA_FAIL = """\
---
type: qa
verdict: fail
boundary: non-production
route: build-loop
---

## Functional test

**Verdict: `fail`** — these required strategies ran and did not meet their threshold: cli-smoke

Boundary: `non-production`. Route: `build-loop`.

### Selection

| Strategy | Required | Why it was selected |
|---|---|---|
| `cli-smoke` | yes | the profile marks this strategy required |

### Results

| Strategy | Result | What it proved, or why it did not |
|---|---|---|
| `cli-smoke` | `failed` | these declared invocations did not exit zero: help |
"""

_QA_BLOCKED = """\
---
type: qa
verdict: fail
boundary: non-production
route: operator-stop
---

## Functional test

**Verdict: `fail`** — these required strategies could not run

Boundary: `non-production`. Route: `operator-stop`.

### Selection

| Strategy | Required | Why it was selected |
|---|---|---|
| `deploy-boundary` | yes | the profile marks this strategy required |

### Results

| Strategy | Result | What it proved, or why it did not |
|---|---|---|
| `deploy-boundary` | `blocked` | the environment variable QA_BASE_URL is unset |
"""

_QA_PROOF_DEBT = """\
---
type: qa
verdict: pass-with-proof-debt
boundary: non-production
route: close
---

## Functional test

**Verdict: `pass-with-proof-debt`** — every required strategy passed; 1 optional strategy could
not run and the debt is recorded

Boundary: `non-production`. Route: `close`.

### Selection

| Strategy | Required | Why it was selected |
|---|---|---|
| `cli-smoke` | yes | the profile marks this strategy required |
| `contract-check` | no | the profile pattern '**/openapi.yaml' matched |

### Results

| Strategy | Result | What it proved, or why it did not |
|---|---|---|
| `cli-smoke` | `passed` | 1 declared invocation(s) exited zero |
| `contract-check` | `blocked` | the profile names no contract-diff command to run |

### Proof debt

- `contract-check`: the profile names no contract-diff command to run
"""


# ── project_work tests ────────────────────────────────────────────────────────────────────────────


def test_project_work_rows_complete() -> None:
    """project_work produces exactly 8 rows in the correct order."""
    saga = _mock_saga(phase_status="in_progress")
    spec = SC.project_work(saga)
    assert spec.archetype == "gate-sequence"
    labels = [r.label for r in spec.rows]
    assert labels == [
        "Implementation",
        "Doc-review",
        "Tests",
        "Reviewer panel",
        "Scanners",
        "CI",
        "Merge (HITL)",
        "Deploy (HITL)",
    ], f"unexpected row labels: {labels}"


def test_project_work_impl_state_from_phase_status() -> None:
    """project_work Implementation row derives from phase_status."""
    for phase_status, expected in [
        ("complete", "done"),
        ("in_progress", "in-progress"),
        ("pending", "not-reached"),
    ]:
        saga = _mock_saga(phase_status=phase_status)
        spec = SC.project_work(saga)
        impl_row = spec.rows[0]
        assert impl_row.key == "impl"
        assert str(impl_row.state) == expected, (
            f"phase_status={phase_status!r} → expected {expected!r}, got {impl_row.state!r}"
        )


def test_project_work_ae4_tests_cell_in_progress_while_running() -> None:
    """AE4: Tests cell is in-progress when gate_verdicts contains tests:in-progress."""
    saga = _mock_saga(gate_verdicts=["tests:in-progress:saga-1/gate_verdicts"])
    spec = SC.project_work(saga)
    tests_row = next(r for r in spec.rows if r.key == "tests")
    assert tests_row.state == SC.CardState.IN_PROGRESS, (
        f"expected in-progress, got {tests_row.state}"
    )
    assert tests_row.ref == "saga-1/gate_verdicts"


def test_project_work_ae4_tests_cell_done_only_on_gate_verdict_done() -> None:
    """AE4: Tests cell is done only when gate_verdicts shows tests:done — not from checks_run."""
    saga = _mock_saga(gate_verdicts=["tests:done:saga-1/gate_verdicts"])
    spec = SC.project_work(saga)
    tests_row = next(r for r in spec.rows if r.key == "tests")
    assert tests_row.state == SC.CardState.DONE
    assert tests_row.ref == "saga-1/gate_verdicts"


def test_project_work_ae4_tests_cell_failed_on_gate_verdict_failed() -> None:
    """AE4: Tests cell is failed when gate_verdicts shows tests:failed."""
    saga = _mock_saga(gate_verdicts=["tests:failed:saga-1/gate_verdicts"])
    spec = SC.project_work(saga)
    tests_row = next(r for r in spec.rows if r.key == "tests")
    assert tests_row.state == SC.CardState.FAILED
    assert tests_row.ref is not None


def test_project_work_ae4_tests_cell_not_reached_without_gate_verdicts() -> None:
    """AE4: Tests cell is not-reached (no ref) when gate_verdicts is absent."""
    saga = _mock_saga()  # gate_verdicts is _ABSENT_SENTINEL (not a list)
    spec = SC.project_work(saga)
    tests_row = next(r for r in spec.rows if r.key == "tests")
    assert tests_row.state == SC.CardState.NOT_REACHED
    assert tests_row.ref is None


def test_project_work_ae6_reviewer_panel_ref_from_review_paths() -> None:
    """AE6: Reviewer panel cell carries a resolvable ref to the code-review artifact."""
    saga = _mock_saga(review_paths=["docs/reviews/2026-06-29-myfeature-review.md"])
    spec = SC.project_work(saga)
    panel_row = next(r for r in spec.rows if r.key == "panel")
    assert panel_row.state == SC.CardState.DONE
    assert panel_row.ref == "docs/reviews/2026-06-29-myfeature-review.md"


def test_project_work_ae7_undeterminable_cell_not_reached_no_ref() -> None:
    """AE7: a cell whose source signal is absent renders NOT_REACHED with ref=None."""
    saga = _mock_saga()  # no review_paths, gate_verdicts, pr_refs
    spec = SC.project_work(saga)
    for row in spec.rows:
        if row.state == SC.CardState.NOT_REACHED:
            assert row.ref is None, (
                f"row {row.key!r} is NOT_REACHED but has ref {row.ref!r} — violates AE7/R13"
            )


def test_project_work_r12_ci_merge_carry_external_ref() -> None:
    """R12 external-read: determinable CI/Merge (HITL) cells carry a resolvable GitHub ref."""
    pr_ref = "https://github.com/infiquetra/infiquetra-claude-plugins/pull/303"
    saga = _mock_saga(pr_refs=[pr_ref], destination="pr")
    spec = SC.project_work(saga)

    ci_row = next(r for r in spec.rows if r.key == "ci")
    assert ci_row.state == SC.CardState.IN_PROGRESS
    assert ci_row.ref == pr_ref, f"CI ref should be external PR ref, got {ci_row.ref!r}"

    merge_row = next(r for r in spec.rows if r.key == "merge")
    assert merge_row.state == SC.CardState.BLOCKED
    assert merge_row.ref == pr_ref


# ── project_code_review tests ─────────────────────────────────────────────────────────────────────


def test_project_code_review_rows_complete() -> None:
    """project_code_review produces exactly 7 rows."""
    spec = SC.project_code_review(_CODE_REVIEW_CLEAN, ref="docs/reviews/clean.md")
    assert spec.archetype == "gate-sequence"
    assert len(spec.rows) == 7
    labels = [r.label for r in spec.rows]
    assert labels == [
        "Scope",
        "Intent",
        "Lenses",
        "Review fan-out",
        "Merge",
        "Validators",
        "Verdict",
    ]


def test_project_code_review_scope_clean() -> None:
    """'Scope Check: CLEAN' → Scope row is done."""
    spec = SC.project_code_review(_CODE_REVIEW_CLEAN, ref="r.md")
    scope_row = next(r for r in spec.rows if r.key == "scope")
    assert scope_row.state == SC.CardState.DONE
    assert scope_row.ref == "r.md"


def test_project_code_review_scope_drift() -> None:
    """'Scope Check: DRIFT DETECTED' → Scope row is blocked."""
    spec = SC.project_code_review(_CODE_REVIEW_BLOCKED, ref="r.md")
    scope_row = next(r for r in spec.rows if r.key == "scope")
    assert scope_row.state == SC.CardState.BLOCKED


def test_project_code_review_intent_all_done() -> None:
    """Intent row is done when all plan-completion audit tokens are DONE."""
    spec = SC.project_code_review(_CODE_REVIEW_CLEAN, ref="r.md")
    intent_row = next(r for r in spec.rows if r.key == "intent")
    assert intent_row.state == SC.CardState.DONE


def test_project_code_review_intent_not_done_blocked() -> None:
    """Intent row is blocked when any plan-completion audit token is NOT-DONE."""
    spec = SC.project_code_review(_CODE_REVIEW_BLOCKED, ref="r.md")
    intent_row = next(r for r in spec.rows if r.key == "intent")
    assert intent_row.state == SC.CardState.BLOCKED


def test_project_code_review_verdict_clean_is_done() -> None:
    """A 'CLEAN' verdict line → Verdict row is done."""
    spec = SC.project_code_review(_CODE_REVIEW_CLEAN, ref="r.md")
    verdict_row = next(r for r in spec.rows if r.key == "verdict")
    assert verdict_row.state == SC.CardState.DONE
    assert verdict_row.ref == "r.md"


def test_project_code_review_verdict_blocked_is_blocked() -> None:
    """A 'BLOCKED' verdict line → Verdict row is blocked."""
    spec = SC.project_code_review(_CODE_REVIEW_BLOCKED, ref="r.md")
    verdict_row = next(r for r in spec.rows if r.key == "verdict")
    assert verdict_row.state == SC.CardState.BLOCKED


def test_project_code_review_ae7_missing_scope_is_not_reached() -> None:
    """AE7: artifact text without 'Scope Check:' → Scope row is not-reached with no ref."""
    minimal = "# Review\n\n**Verdict:** CLEAN\n"
    spec = SC.project_code_review(minimal, ref="r.md")
    scope_row = next(r for r in spec.rows if r.key == "scope")
    assert scope_row.state == SC.CardState.NOT_REACHED
    assert scope_row.ref is None


# ── project_qa tests ──────────────────────────────────────────────────────────────────────────────
# Retargeted by issue 1039 with the rows they now guard. The projection reads the functional-test
# comment instead of a health-scored report, so these tests moved with it rather than being
# deleted: the surface still has a card, and the card still has to tell the truth about it.


def test_project_qa_rows_complete() -> None:
    """project_qa produces exactly 5 rows, in the functional test's own vocabulary."""
    spec = SC.project_qa(_QA_PASS, ref="qa-1039.md")
    assert spec.archetype == "gate-sequence"
    assert len(spec.rows) == 5
    labels = [r.label for r in spec.rows]
    assert labels == ["Selection", "Preflight", "Evidence", "Proof debt", "Verdict"]


def test_project_qa_pass_verdict_done() -> None:
    """'verdict: pass' → the Verdict row is done with ref."""
    spec = SC.project_qa(_QA_PASS, ref="qa-1039.md")
    verdict_row = next(r for r in spec.rows if r.key == "verdict")
    assert verdict_row.state == SC.CardState.DONE
    assert verdict_row.ref == "qa-1039.md"


def test_project_qa_proof_debt_verdict_is_done_and_the_debt_row_is_blocked() -> None:
    """Proof debt passes the run AND stays visible; a debt that rendered done would be hidden."""
    spec = SC.project_qa(_QA_PROOF_DEBT, ref="qa-debt.md")
    verdict_row = next(r for r in spec.rows if r.key == "verdict")
    debt_row = next(r for r in spec.rows if r.key == "debt")
    assert verdict_row.state == SC.CardState.DONE
    assert debt_row.state == SC.CardState.BLOCKED
    assert debt_row.ref == "qa-debt.md"


def test_project_qa_ae9_fail_verdict_is_failed_not_blocked() -> None:
    """AE9: 'verdict: fail' → the Verdict row is FAILED (not blocked, not not-reached) with ref."""
    spec = SC.project_qa(_QA_FAIL, ref="qa-fail.md")
    verdict_row = next(r for r in spec.rows if r.key == "verdict")
    assert verdict_row.state == SC.CardState.FAILED, (
        f"expected FAILED for 'verdict: fail', got {verdict_row.state!r}"
    )
    assert verdict_row.state != SC.CardState.BLOCKED
    assert verdict_row.state != SC.CardState.NOT_REACHED
    assert verdict_row.ref == "qa-fail.md", "AE9: a failed verdict must carry ref"


def test_project_qa_evidence_is_done_when_every_strategy_passed() -> None:
    """The Evidence row follows the per-strategy results, not the verdict word."""
    spec = SC.project_qa(_QA_PASS, ref="r.md")
    evidence_row = next(r for r in spec.rows if r.key == "evidence")
    assert evidence_row.state == SC.CardState.DONE


def test_project_qa_evidence_is_failed_when_a_strategy_failed() -> None:
    spec = SC.project_qa(_QA_FAIL, ref="r.md")
    evidence_row = next(r for r in spec.rows if r.key == "evidence")
    assert evidence_row.state == SC.CardState.FAILED


def test_project_qa_a_blocked_strategy_never_renders_done() -> None:
    """The card must not show a run that proved nothing as a finished one."""
    spec = SC.project_qa(_QA_BLOCKED, ref="r.md")
    evidence_row = next(r for r in spec.rows if r.key == "evidence")
    assert evidence_row.state == SC.CardState.BLOCKED
    assert evidence_row.state != SC.CardState.DONE
    assert evidence_row.ref == "r.md"


def test_project_qa_selection_counts_the_strategies_it_selected() -> None:
    spec = SC.project_qa(_QA_PASS, ref="r.md")
    selection_row = next(r for r in spec.rows if r.key == "selection")
    assert selection_row.state == SC.CardState.DONE
    assert "2" in (selection_row.ref or ""), f"expected the count in {selection_row.ref!r}"


def test_project_qa_preflight_carries_the_boundary_the_run_reached() -> None:
    spec = SC.project_qa(_QA_PASS, ref="r.md")
    preflight_row = next(r for r in spec.rows if r.key == "preflight")
    assert preflight_row.state == SC.CardState.DONE
    assert "non-production" in (preflight_row.ref or "")


def _make_projection(
    *,
    done: int = 3,
    total: int = 10,
    percent: int = 30,
    complete: bool = False,
    frontier: list | None = None,
    blocked: list | None = None,
    attention_count: int = 0,
    state_counts: dict | None = None,
    outcome_id: str = "outcome-test-1",
) -> dict:
    """Build a minimal outcome projection dict mirroring outcome_projection.project() output."""
    return {
        "outcome_id": outcome_id,
        "progress": {"done": done, "total": total, "percent": percent},
        "complete": complete,
        "frontier": frontier if frontier is not None else ["node-A", "node-B"],
        "blocked": blocked if blocked is not None else [],
        "attention": {"count": attention_count, "top": None},
        "state_counts": state_counts if state_counts is not None else {"done": done, "ready": 2},
    }


def _mock_resume_saga(
    saga_id: str = "saga-resume-1",
    phase_status: str = "in_progress",
    destination: str = "pr",
    blockers: str = "",
    open_questions: object = None,  # None → treated as ABSENT (not a list)
    gate_verdicts: object = None,  # None → treated as ABSENT (not a list)
    next_step: str = "",
) -> object:
    """Build a lightweight mock saga object for project_resume tests."""
    return types.SimpleNamespace(
        saga_id=saga_id,
        phase_status=phase_status,
        destination=destination,
        blockers=blockers,
        open_questions=open_questions,
        gate_verdicts=gate_verdicts,
        next_step=next_step,
    )


def test_ae5_done_glyph_consistent_across_work_and_qa() -> None:
    """AE5: the DONE glyph from project_work Tests row matches the DONE glyph from project_qa rows.

    Shared concepts use the SAME glyph via the single GLYPH_MAP — this is guaranteed by construction
    (one render site, one map) but the test makes the invariant explicit and falsifiable.
    """
    # Render project_work with tests:done
    saga = _mock_saga(gate_verdicts=["tests:done:gate_verdicts"])
    work_spec = SC.project_work(saga)
    tests_row = next(r for r in work_spec.rows if r.key == "tests")
    work_tests_card = SC.render(
        SC.CardSpec(
            archetype="gate-sequence",
            header=SC.CardHeader(surface="/work", id="s"),
            rows=(tests_row,),
        )
    )

    # Render project_qa with a passing verdict (the Evidence row will be DONE)
    qa_spec = SC.project_qa(_QA_PASS, ref="qa.md")
    checks_row = next(r for r in qa_spec.rows if r.key == "evidence")
    qa_checks_card = SC.render(
        SC.CardSpec(
            archetype="gate-sequence",
            header=SC.CardHeader(surface="/qa", id="s"),
            rows=(checks_row,),
        )
    )

    done_glyph = SC.GLYPH_MAP["done"]
    assert done_glyph in work_tests_card, "DONE glyph missing from project_work Tests row"
    assert done_glyph in qa_checks_card, "DONE glyph missing from project_qa Evidence row"


# ── project_arc (#344 U3): idea->deploy lifecycle arc ─────────────────────────────────────────────


def _arc_saga(**kw: Any) -> object:
    """A saga namespace carrying the durable fields project_arc reads (not covered by _mock_saga)."""
    base: dict[str, Any] = {
        "saga_id": "saga-arc-1",
        "lifecycle_phase": "",
        "phase_status": "",
        "status": "active",
        "plan_path": "",
        "review_paths": [],
        "pr_refs": [],
        "destination": "plan-only",
    }
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_project_arc_rows_and_archetype() -> None:
    """project_arc is a gate-sequence with the fixed idea->deploy stage set (R3 constant height)."""
    spec = SC.project_arc(
        _arc_saga(lifecycle_phase="work", phase_status="in_progress", plan_path="docs/plans/x.md")
    )
    assert spec.archetype == "gate-sequence"
    assert [r.label for r in spec.rows] == [
        "Idea",
        "Plan",
        "Work",
        "Review",
        "Merge (HITL)",
        "Deploy (HITL)",
    ]


def test_project_arc_is_pure_render_deterministic() -> None:
    """AE5/KD4: identical saga-field input renders byte-identically — no board/external state read."""
    saga = _arc_saga(
        lifecycle_phase="work", phase_status="complete", plan_path="p.md", pr_refs=["owner/repo#5"]
    )
    assert SC.render(SC.project_arc(saga)) == SC.render(SC.project_arc(saga))


def test_project_arc_work_complete_pr_open_merge_blocked() -> None:
    spec = SC.project_arc(
        _arc_saga(
            lifecycle_phase="work",
            phase_status="complete",
            plan_path="p.md",
            pr_refs=["owner/repo#5"],
        )
    )
    by = {r.key: r.state for r in spec.rows}
    assert by["plan"] == SC.CardState.DONE
    assert by["work"] == SC.CardState.DONE
    assert by["merge"] == SC.CardState.BLOCKED  # PR exists, thread not done → awaiting HITL merge
    assert by["deploy"] == SC.CardState.NOT_REACHED  # destination is not a deploy


def test_project_arc_done_thread_deploy_closes_out() -> None:
    spec = SC.project_arc(
        _arc_saga(
            lifecycle_phase="qa",
            phase_status="complete",
            status="done",
            plan_path="p.md",
            review_paths=["docs/reviews/r.md"],
            pr_refs=["owner/repo#5"],
            destination="nonprod-deploy",
        )
    )
    by = {r.key: r.state for r in spec.rows}
    assert by["work"] == SC.CardState.DONE
    assert by["review"] == SC.CardState.DONE
    assert by["merge"] == SC.CardState.DONE
    assert by["deploy"] == SC.CardState.DONE


def test_project_arc_empty_saga_all_not_reached_constant_height() -> None:
    """Safe degradation: a fully-empty object → all six stages NOT_REACHED, height unchanged."""
    spec = SC.project_arc(types.SimpleNamespace())
    assert len(spec.rows) == 6
    assert all(r.state == SC.CardState.NOT_REACHED for r in spec.rows)
