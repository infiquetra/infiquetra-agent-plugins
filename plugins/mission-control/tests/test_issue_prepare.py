"""Tests for prepared issue draft contracts and readiness profiles."""

# ruff: noqa: E402,I001

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


# Updated 2026-06-14 for the U8 context-package contract: an actionable card now
# carries the always-required Intent (R1) + Context library links (R4), and the
# acceptance criteria name a runnable check (R2/KTD8). This is a medium-risk card
# in its test, so the risk-conditional fields (R5-R7) are not required.
OLYMPUS_BODY = """### Objective
Add a prepared issue workflow.

### Intent
Authoring agents need a draft-then-approve path; without it cards skip review.
End-state: every prepared card is drafted, gated, and only then created.

### Acceptance criteria
- [ ] Drafts are written before GitHub mutation; `uv run pytest plugins/mission-control/tests/test_issue_prepare.py` exits 0

### Out-of-scope / non-goals
- Do not auto-move issues to Ready

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_issue_prepare.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_issue_prepare.py
```

### Context library links
_none_
"""


ASGARD_BODY = """### Intent
Shape a rapid-action issue preparation path.

### Target repo / surface
hermes-claude-code-router issue intake

### Mode
Rapid Action

### Constraints
Keep issue creation separate from draft review.

### Risk
Low operational risk.

### Transfer notes
- [ ] No cross-team transfer requested.
"""


def test_prepare_olympus_writes_ready_draft_and_sidecar(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Prepared issue workflow",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert draft.exists()
    assert sidecar["state"] == "ready_to_create"
    assert sidecar["repo"] == "hermes-claude-code-router"
    assert sidecar["readiness"]["passed"] is True
    assert sidecar["labels"] == ["capability", "needs-plan"]
    assert sidecar["handoff_maturity"] == "requirements-ready"
    assert "### Handoff maturity" in draft.read_text()


def test_prepare_olympus_blocks_missing_verification(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source="Implement the router issue workflow.",
        title="Incomplete Olympus draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    assert sidecar["readiness"]["passed"] is False
    assert any("Verification" in gap for gap in sidecar["readiness"]["blocking_gaps"])
    body = draft.read_text()
    for header in (
        "Objective",
        "Intent",
        "Out-of-scope / non-goals",
        "Files expected to change",
        "Tests to add or update",
        "Context library links",
        "Acceptance criteria",
        "Verification",
    ):
        assert f"### {header}" in body


def test_prepare_high_risk_fallback_includes_risk_conditional_sections(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source="Implement the router issue workflow.",
        title="High-risk fallback",
        status=None,
        risk="high",
        mode=None,
        draft_dir=tmp_path,
    )

    body = draft.read_text()
    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    for header in ("Inputs inventory", "Failure modes / pre-mortem", "Stop conditions"):
        assert f"### {header}" in body
        assert any(header in gap for gap in sidecar["readiness"]["blocking_gaps"])


def test_prepare_asgard_accepts_shaping_quality_input(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="exploration",
        team="asgard",
        project="asgard",
        source=ASGARD_BODY,
        title="Asgard shaping issue",
        status=None,
        risk="low",
        mode="Rapid Action",
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "ready_to_create"
    assert sidecar["readiness"]["passed"] is True
    assert sidecar["readiness"]["warnings"] == []


def test_prepare_asgard_actionable_uses_hermes_contract(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="asgard",
        project="asgard",
        source=ASGARD_BODY,
        title="Asgard actionable issue",
        status=None,
        risk="low",
        mode="Rapid Action",
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    assert any("Objective" in gap for gap in sidecar["readiness"]["blocking_gaps"])
    assert not any(
        "Missing Asgard mode metadata" in gap for gap in sidecar["readiness"]["blocking_gaps"]
    )


def test_ready_status_blocks_prepared_draft(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="exploration",
        team="asgard",
        project="asgard",
        source=ASGARD_BODY,
        title="Too ready",
        status="Ready",
        risk="low",
        mode="Rapid Action",
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    assert "Prepared issues must not start in Ready" in sidecar["readiness"]["blocking_gaps"]


def test_prepare_records_explicit_handoff_maturity(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Plan handoff",
        status=None,
        risk="medium",
        mode=None,
        handoff_maturity="plan-ready",
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())
    body = draft.read_text()

    assert sidecar["handoff_maturity"] == "plan-ready"
    assert "### Handoff maturity\nplan-ready" in body
    assert "Use `/work <issue>`" in body


def test_non_default_status_blocks_prepared_draft(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Wrong status",
        status="In Progress",
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    assert (
        "Prepared campps issues must start in 'Idea', not 'In Progress'"
        in sidecar["readiness"]["blocking_gaps"]
    )


def test_olympus_requires_actionable_labels_and_risk(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Missing risk",
        status=None,
        risk=None,
        mode=None,
        draft_dir=tmp_path,
    )

    draft.write_text(
        draft.read_text().replace("labels: capability, needs-plan", "labels: capability")
    )
    sidecar_path = draft.with_suffix(".json")
    sidecar = json.loads(sidecar_path.read_text())
    sidecar["labels"] = ["capability"]
    sidecar_path.write_text(json.dumps(sidecar))

    issue = sdlc_manager._read_prepared_issue(draft)
    readiness = sdlc_manager._readiness_for_prepared_issue(issue)

    assert not readiness.passed
    assert any("Missing expected labels" in gap for gap in readiness.blocking_gaps)
    assert "Missing author-visible risk metadata" in readiness.blocking_gaps


def test_sidecar_conflict_blocks_draft_parse(tmp_path) -> None:
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Conflict draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    sidecar_path = draft.with_suffix(".json")
    sidecar = json.loads(sidecar_path.read_text())
    sidecar["repo"] = "other-repo"
    sidecar_path.write_text(json.dumps(sidecar))

    with pytest.raises(RuntimeError, match="conflicts with sidecar"):
        sdlc_manager._read_prepared_issue(draft)
