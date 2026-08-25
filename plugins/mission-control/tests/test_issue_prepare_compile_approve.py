"""Tests for the U11 prepared-issue compile + approve flow.

Covers the four U11 pieces layered on the existing prepare/sidecar machinery:
  1. project-field population in the sidecar (offline, derived from metadata),
  2. the durable `needs_operator_approval` human gate,
  3. batch approval out of that gate, and
  4. the Phase C validator (`validate_card_body`) as the compile-time acceptance
     gate on agent output (KTD9).

Mirrors the fixtures/conventions in test_issue_prepare.py: tmp_path-scoped,
fully offline (no live GitHub call), sidecar read back as JSON.
"""

# ruff: noqa: E402,I001

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


# A cleanly-compiling olympus card body: carries the always-required Intent (R1)
# + Context library links (R4), and the acceptance criteria name a runnable
# check (R2/KTD8). Same shape as the OLYMPUS_BODY fixture in test_issue_prepare.
OLYMPUS_BODY = """### Objective
Add a prepared issue workflow.

### Intent
Authoring agents need a draft-then-approve path; without it cards skip review.
End-state: every prepared card is drafted, gated, and only then created.

### Acceptance criteria
- [ ] Drafts are written before GitHub mutation; `uv run pytest plugins/mission-control/tests/test_issue_prepare_compile_approve.py` exits 0

### Out-of-scope / non-goals
- Do not auto-move issues to Ready

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_issue_prepare_compile_approve.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_issue_prepare_compile_approve.py
```

### Context library links
_none_
"""


# A body with ALL required H3 sections present and a checklist item, but whose
# acceptance criterion names NO runnable check (no `code span`, no fenced block
# in the acceptance section). This trips ONLY the executable-acceptance check
# (U8/KTD8), proving the gate covers more than absent-headers. Verification still
# has its own fenced block so the failure is isolated to acceptance executability.
NON_EXECUTABLE_ACCEPTANCE_BODY = """### Objective
Add a prepared issue workflow.

### Intent
Authoring agents need a draft-then-approve path; without it cards skip review.
End-state: every prepared card is drafted, gated, and only then created.

### Acceptance criteria
- [ ] The prepared draft is reviewed and looks correct to the operator

### Out-of-scope / non-goals
- Do not auto-move issues to Ready

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_issue_prepare_compile_approve.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_issue_prepare_compile_approve.py
```

### Context library links
_none_
"""


def _prepare_olympus(tmp_path: Path, *, title: str, source: str = OLYMPUS_BODY) -> Path:
    """Prepare an olympus capability draft offline and return its path."""
    # Funnel through a typed local: `sdlc_manager` is imported via sys.path so
    # mypy (with --ignore-missing-imports) sees it as Any; the annotated local
    # pins the return type and avoids no-any-return.
    draft: Path = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=source,
        title=title,
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    return draft


def _sidecar(draft: Path) -> dict:
    data: dict = json.loads(draft.with_suffix(".json").read_text())
    return data


def test_issue_prepare_populates_project_fields(tmp_path) -> None:
    """Preparing a draft records the project-field values in the sidecar."""
    draft = _prepare_olympus(tmp_path, title="Project fields populated")

    fields = _sidecar(draft)["project_fields"]

    # Issue type + Risk come straight from metadata; Lifecycle Origin is the
    # auto-populated field (R10) carrying the handoff maturity that drove this
    # draft. No source artifact was supplied, so no Objective is invented.
    assert fields["Issue Type"] == "capability"
    assert fields["Technical Risk"] == "medium"
    assert fields["Lifecycle Origin"] == "requirements-ready"
    assert "Objective" not in fields


def test_needs_operator_approval_state(tmp_path) -> None:
    """A cleanly-compiled prepared issue lands in Needs Operator Approval."""
    draft = _prepare_olympus(tmp_path, title="Needs approval")

    sidecar = _sidecar(draft)

    # Durable in the sidecar...
    assert sidecar["readiness"]["passed"] is True
    assert sidecar["approval_state"] == "needs_operator_approval"
    # ...and durable in the draft front-matter (what an operator reading the
    # markdown directly sees). NOT auto-created: the creation-pipeline state is
    # still the pre-create ready_to_create, never `created`.
    assert "approval_state: needs_operator_approval" in draft.read_text()
    assert sidecar["state"] == "ready_to_create"


def test_batch_approval(tmp_path) -> None:
    """Batch approval transitions multiple prepared drafts out of the gate."""
    first = _prepare_olympus(tmp_path, title="Batch card one")
    second = _prepare_olympus(tmp_path, title="Batch card two")

    # Pre-condition: both sit in the approval gate.
    assert _sidecar(first)["approval_state"] == "needs_operator_approval"
    assert _sidecar(second)["approval_state"] == "needs_operator_approval"

    result = sdlc_manager.prepared_approve_batch([first, second], fmt="text")

    assert result["approved"] == [str(first), str(second)]
    assert result["skipped"] == []
    for draft in (first, second):
        sidecar = _sidecar(draft)
        assert sidecar["approval_state"] == "approved"
        assert "approved_at" in sidecar
        # Front-matter is kept in lockstep with the sidecar.
        assert "approval_state: approved" in draft.read_text()


def test_batch_approval_is_idempotent_and_preserves_timestamp(tmp_path) -> None:
    """FIX 4: re-approving an already-approved draft is a no-op — it is SKIPPED
    ("already approved") and approved_at/updated_at are NOT rewritten."""
    draft = _prepare_olympus(tmp_path, title="Idempotent card")

    first = sdlc_manager.prepared_approve_batch([draft], fmt="text")
    assert first["approved"] == [str(draft)]
    after_first = _sidecar(draft)
    approved_at = after_first["approved_at"]
    updated_at = after_first["updated_at"]

    # Second approve: skipped, timestamps frozen (true no-op, not a re-stamp).
    second = sdlc_manager.prepared_approve_batch([draft], fmt="text")
    assert second["approved"] == []
    assert second["skipped"] == [{"draft": str(draft), "reason": "already approved"}]
    after_second = _sidecar(draft)
    assert after_second["approved_at"] == approved_at
    assert after_second["updated_at"] == updated_at


def test_batch_approval_rejects_tampered_sidecar(tmp_path) -> None:
    """FIX 3: approval re-derives readiness from the on-disk body, so a sidecar
    hand-edited to `needs_operator_approval` over a body that FAILS the validator
    is skipped ("fails validation"), never approved."""
    # Start from a blocked draft (body fails the validator), then forge its
    # sidecar approval_state to look like it cleared the compile gate.
    draft = _prepare_olympus(tmp_path, title="Forged card", source="Just ship it.")
    sidecar_path = draft.with_suffix(".json")
    tampered = _sidecar(draft)
    assert tampered["readiness"]["passed"] is False  # body really is invalid
    tampered["approval_state"] = "needs_operator_approval"
    sidecar_path.write_text(json.dumps(tampered))

    result = sdlc_manager.prepared_approve_batch([draft], fmt="text")

    assert result["approved"] == []
    assert result["skipped"] == [{"draft": str(draft), "reason": "fails validation"}]
    # The forged draft was NOT pushed to approved.
    assert _sidecar(draft)["approval_state"] == "needs_operator_approval"


def test_batch_approval_skips_blocked_draft(tmp_path) -> None:
    """A blocked draft has no approval gate; batch approval skips it, fault
    isolated, without aborting the rest of the batch."""
    good = _prepare_olympus(tmp_path, title="Approvable card")
    blocked = _prepare_olympus(tmp_path, title="Blocked card", source="Just ship it.")

    # The blocked draft never entered the gate.
    assert _sidecar(blocked)["approval_state"] is None

    result = sdlc_manager.prepared_approve_batch([good, blocked], fmt="text")

    assert result["approved"] == [str(good)]
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["draft"] == str(blocked)
    # The blocked draft is untouched by approval.
    assert _sidecar(blocked)["approval_state"] is None


def test_validator_gates_agent_output(tmp_path) -> None:
    """KTD9: a body that fails validate_card_body is rejected by prepare (does
    NOT reach approval); a valid body passes through to the gate."""
    # A malformed agent body: missing required H3 sections, no executable
    # acceptance, no fenced verification. validate_card_body must reject it.
    malformed = "Implement the prepared issue workflow somehow."
    invalid_ok, invalid_errors = sdlc_manager.validate_card_body(malformed)
    assert invalid_ok is False
    assert invalid_errors  # the gate produced concrete findings

    blocked = _prepare_olympus(tmp_path, title="Malformed agent output", source=malformed)
    blocked_sidecar = _sidecar(blocked)

    # Rejected at prepare time: blocked, never reaches the approval gate, and the
    # validator findings are surfaced as blocking readiness gaps.
    assert blocked_sidecar["readiness"]["passed"] is False
    assert blocked_sidecar["state"] == "blocked"
    assert blocked_sidecar["approval_state"] is None
    assert "approval_state" not in blocked.read_text()

    # Second malformed case (FIX 6): ALL required H3 sections present, but the
    # acceptance criterion names no runnable check. This proves the gate covers
    # the executable-acceptance contract (U8/KTD8), not just absent headers.
    non_exec_ok, non_exec_errors = sdlc_manager.validate_card_body(NON_EXECUTABLE_ACCEPTANCE_BODY)
    assert non_exec_ok is False
    assert any("not executable" in err for err in non_exec_errors)

    non_exec = _prepare_olympus(
        tmp_path, title="Non-executable acceptance", source=NON_EXECUTABLE_ACCEPTANCE_BODY
    )
    non_exec_sidecar = _sidecar(non_exec)
    assert non_exec_sidecar["readiness"]["passed"] is False
    assert non_exec_sidecar["state"] == "blocked"
    assert non_exec_sidecar["approval_state"] is None

    # The same gate lets a valid body through to the approval gate.
    valid_ok, _ = sdlc_manager.validate_card_body(OLYMPUS_BODY)
    assert valid_ok is True

    passing = _prepare_olympus(tmp_path, title="Valid agent output")
    passing_sidecar = _sidecar(passing)
    assert passing_sidecar["readiness"]["passed"] is True
    assert passing_sidecar["approval_state"] == "needs_operator_approval"
