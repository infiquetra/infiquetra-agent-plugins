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

### Risk
medium
The change is confined to the prepared-issue draft pipeline.

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
low
The change is confined to the rapid-action preparation path.

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
        stage="Intake",  # W10: readiness-passing drafts carry an author-supplied Stage
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert draft.exists()
    assert sidecar["state"] == "ready_to_create"
    assert sidecar["repo"] == "hermes-claude-code-router"
    assert sidecar["readiness"]["passed"] is True
    assert sidecar["labels"] == ["capability", "needs-plan"]
    # Review finding #5: a text-only prepare (no --from, no --maturity)
    # records NO handoff maturity — readiness reports it as a warning and the
    # body renders no handoff section, and no Saga owner is ever loaded.
    assert sidecar["handoff_maturity"] is None
    assert "### Handoff maturity" not in draft.read_text()
    assert any(
        "Missing handoff maturity" in warning for warning in sidecar["readiness"]["warnings"]
    )


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
        stage="Intake",  # W10: readiness-passing drafts carry an author-supplied Stage
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "ready_to_create"
    assert sidecar["readiness"]["passed"] is True
    # Review finding #5: the text-only prepare records no handoff maturity,
    # so readiness reports exactly the missing-maturity warning.
    assert sidecar["readiness"]["warnings"] == ["Missing handoff maturity metadata"]


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
    # #942: the suggested next action is Saga-owned and names its target; a
    # text-only prepare has no published source to route to, so the section is
    # omitted instead of rendering the retired local placeholder prose.
    assert "### Suggested next action" not in body


def test_non_default_status_blocks_prepared_draft(tmp_path) -> None:
    """R49 entry-option rule: a Status other than the declared Stage's entry
    option blocks, naming the entry option — the retired team default is gone."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Wrong status",
        status="Implementing",
        risk="medium",
        mode=None,
        stage="Intake",
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    assert (
        "Prepared issues at Stage 'Intake' must start in one of the Stage's configured "
        "Statuses ['Capturing', 'Needs clarification', 'Triage', 'Backlog'] or the "
        "cross-cutting statuses ['Blocked'], not 'Implementing'"
        in sidecar["readiness"]["blocking_gaps"]
    )


def test_triage_on_intake_is_accepted_and_refusal_names_the_stage(tmp_path) -> None:
    """Cycle-5 operator ruling: readiness accepts any Status configured within the
    declared Stage (Triage is Intake's third option) — NOT the entry option
    exactly, so this test distinguishes the relaxed rule from the pre-repair
    pin — plus the cross-cutting statuses. Out-of-Stage values stay refused with
    a refusal that names the Stage, not the team."""
    draft_triage = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="In-stage Triage status",
        status="Triage",
        risk="medium",
        mode=None,
        stage="Intake",
        draft_dir=tmp_path,
    )
    sidecar_triage = json.loads(draft_triage.with_suffix(".json").read_text())
    assert sidecar_triage["state"] == "ready_to_create"
    assert sidecar_triage["readiness"]["passed"] is True
    assert sidecar_triage["status"] == "Triage"

    draft_blocked = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Cross-cutting Blocked",
        status="Blocked",
        risk="medium",
        mode=None,
        stage="Intake",
        draft_dir=tmp_path,
    )
    sidecar_blocked = json.loads(draft_blocked.with_suffix(".json").read_text())
    assert sidecar_blocked["state"] == "ready_to_create"

    draft_out_of_stage = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Out-of-stage value",
        status="Implementing",
        risk="medium",
        mode=None,
        stage="Intake",
        draft_dir=tmp_path,
    )
    sidecar_out = json.loads(draft_out_of_stage.with_suffix(".json").read_text())
    assert sidecar_out["state"] == "blocked"
    assert any(
        "Prepared issues at Stage 'Intake'" in gap
        and "not 'Implementing'" in gap
        and "campps" not in gap.lower()
        for gap in sidecar_out["readiness"]["blocking_gaps"]
    )


def test_entry_option_default_derived_per_stage(tmp_path) -> None:
    """W10 repair (R49): with no author Status, the default is the entry option
    of the DECLARED Stage — Intake -> Capturing, Planning -> Designing —
    sourced from the schema's stage_flow, not a per-team literal."""
    draft_intake = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Intake default",
        status=None,
        risk="medium",
        mode=None,
        stage="Intake",
        draft_dir=tmp_path,
    )
    sidecar_intake = json.loads(draft_intake.with_suffix(".json").read_text())
    assert sidecar_intake["status"] == "Capturing"
    assert sidecar_intake["state"] == "ready_to_create"

    draft_planning = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Planning default",
        status=None,
        risk="medium",
        mode=None,
        stage="Planning",
        draft_dir=tmp_path,
    )
    sidecar_planning = json.loads(draft_planning.with_suffix(".json").read_text())
    assert sidecar_planning["status"] == "Designing"
    assert sidecar_planning["state"] == "ready_to_create"


def test_author_supplied_status_is_honoured(tmp_path) -> None:
    """An author Status equal to the stage's entry option passes as the author's
    own value — `status or <default>` never substitutes the default for it."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Author status",
        status="Designing",
        risk="medium",
        mode=None,
        stage="Planning",
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["status"] == "Designing"
    assert sidecar["state"] == "ready_to_create"


def test_retired_team_default_statuses_are_gone(tmp_path) -> None:
    """W13 retired 'Idea'/'Shaping' as Status values: the old `_TEAM_SAFE_STATUSES`
    table is gone from the module, a Shaping-Stage draft defaults to the Stage's
    entry option (not the retired Per-team literal), and an author Status of
    'Idea' is refused."""
    assert not hasattr(sdlc_manager, "_TEAM_SAFE_STATUSES")

    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="exploration",
        team="asgard",
        project="asgard",
        source=ASGARD_BODY,
        title="Shaping stage draft",
        status=None,
        risk="low",
        mode="Rapid Action",
        stage="Shaping",
        draft_dir=tmp_path,
    )
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["status"] == "Discovering"
    assert sidecar["state"] == "ready_to_create"

    draft_idea = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Retired Idea status",
        status="Idea",
        risk="medium",
        mode=None,
        stage="Intake",
        draft_dir=tmp_path,
    )
    sidecar_idea = json.loads(draft_idea.with_suffix(".json").read_text())
    assert sidecar_idea["state"] == "blocked"
    assert any(
        "must start in one of the Stage's configured Statuses" in gap and "not 'Idea'" in gap
        for gap in sidecar_idea["readiness"]["blocking_gaps"]
    )


def test_unknown_stage_blocks_entry_status_derivation(tmp_path) -> None:
    """A declared Stage outside the schema's stage_flow cannot derive an entry
    option — readiness blocks on the unknown Stage instead of silently skipping
    the Status rule."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Unknown stage",
        status="Capturing",
        risk="medium",
        mode=None,
        stage="Limbo",
        draft_dir=tmp_path,
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    assert any("Unknown Stage 'Limbo'" in gap for gap in sidecar["readiness"]["blocking_gaps"])


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

    # #1000 U2: Risk is a common body field derived from `### Risk` on every
    # read — strip the section from the draft body and the card blocks again,
    # naming Risk (the retired sidecar/metadata projection no longer decides).
    draft.write_text(
        draft.read_text().replace(
            "### Risk\nmedium\nThe change is confined to the prepared-issue draft pipeline.\n\n",
            "",
        )
    )
    issue = sdlc_manager._read_prepared_issue(draft)
    readiness = sdlc_manager._readiness_for_prepared_issue(issue)

    assert not readiness.passed
    assert any("Risk" in gap for gap in readiness.blocking_gaps)


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


def test_maturity_sidecar_conflict_blocks_draft_parse(tmp_path) -> None:
    """#9: a one-sided handoff_maturity hand-edit is a loud conflict, not honored."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Maturity conflict draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
        handoff_maturity="plan-ready",
    )
    sidecar_path = draft.with_suffix(".json")
    sidecar = json.loads(sidecar_path.read_text())
    assert sidecar["handoff_maturity"] == "plan-ready"
    sidecar["handoff_maturity"] = "idea-ready"
    sidecar_path.write_text(json.dumps(sidecar))

    with pytest.raises(RuntimeError, match="handoff_maturity.*conflicts with sidecar"):
        sdlc_manager._read_prepared_issue(draft)


# --- Review repairs (2026-09-13 code review) ---------------------------------


def test_risk_flag_conflicting_with_body_records_blocking_gap(tmp_path) -> None:
    """#3: a --risk seed contradicting the body's well-formed Risk section blocks."""
    body = OLYMPUS_BODY.replace("### Risk\nmedium\n", "### Risk\nhigh\n")
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=body,
        title="Risk conflict draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
        stage="Intake",
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())

    assert sidecar["state"] == "blocked"
    assert sidecar["readiness"]["passed"] is False
    conflict = [gap for gap in sidecar["readiness"]["blocking_gaps"] if "--risk" in gap]
    assert conflict, sidecar["readiness"]["blocking_gaps"]
    assert "'medium'" in conflict[0] and "'high'" in conflict[0]


def test_explicit_maturity_conflicting_with_declared_source_blocks(tmp_path, monkeypatch) -> None:
    """#4: --maturity may not promote a source whose own declaration differs."""
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "docs" / "sdlc-issue-drafts" / "pending-declared.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Pending declared draft\n")
    path.with_suffix(".json").write_text(json.dumps({"handoff_maturity": "pending-confirmation"}))
    artifact = sdlc_manager.resolve_source_artifact(
        "docs/sdlc-issue-drafts/pending-declared.md", tmp_path
    )
    assert artifact.inferred_maturity == "pending-confirmation"

    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="enhancement",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Maturity override conflict",
        status=None,
        risk=None,
        mode=None,
        draft_dir=tmp_path / "out",
        stage="Intake",
        source_artifact=artifact,
        handoff_maturity="plan-ready",
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "blocked"
    conflict = [gap for gap in sidecar["readiness"]["blocking_gaps"] if "--maturity" in gap]
    assert conflict, sidecar["readiness"]["blocking_gaps"]
    assert "'plan-ready'" in conflict[0] and "'pending-confirmation'" in conflict[0]


def test_explicit_maturity_still_wins_over_path_fallback(tmp_path, monkeypatch) -> None:
    """#4: the override wins over a path-only fallback, which is not a declaration."""
    monkeypatch.chdir(tmp_path)
    plain = tmp_path / "docs" / "brainstorms" / "plain-source.md"
    plain.parent.mkdir(parents=True, exist_ok=True)
    plain.write_text("# Plain brainstorm source\n")
    artifact = sdlc_manager.resolve_source_artifact("docs/brainstorms/plain-source.md", tmp_path)
    assert artifact.inferred_maturity == "requirements-ready"

    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="enhancement",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Path fallback override",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path / "out",
        stage="Intake",
        source_artifact=artifact,
        handoff_maturity="plan-ready",
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["handoff_maturity"] == "plan-ready"
    assert not [gap for gap in sidecar["readiness"]["blocking_gaps"] if "--maturity" in gap]


def test_text_only_prepare_works_with_saga_absent(tmp_path, monkeypatch) -> None:
    """#5: a text-only prepare never loads the owner, so it works with Saga absent."""

    def _missing_owner() -> object:
        raise RuntimeError("Saga readiness owner dependency problem (test stub)")

    monkeypatch.setattr(sdlc_manager, "_load_saga_readiness_owner", _missing_owner)

    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Saga-less text-only draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
        stage="Intake",
    )

    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "ready_to_create"
    assert sidecar["readiness"]["passed"] is True
    assert sidecar["handoff_maturity"] is None
    assert any(
        "Missing handoff maturity" in warning for warning in sidecar["readiness"]["warnings"]
    )
