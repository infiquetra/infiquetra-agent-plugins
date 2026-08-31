"""Tests for confirmed prepared issue creation and mutation planning."""

# ruff: noqa: E402,I001

import json
import sys
from pathlib import Path
from typing import cast
from unittest.mock import call, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402


# Updated 2026-06-14 for the U8 context-package contract: a hermes-task card now
# carries the always-required Intent (R1) + Context library links (R4), and the
# acceptance criteria name a runnable check (R2/KTD8).
OLYMPUS_BODY = """### Objective
Add a prepared issue workflow.

### Intent
Authoring agents need a draft-then-approve path; without it cards skip review.
End-state: every prepared card is drafted, gated, and only then created.

### Acceptance criteria
- [ ] Drafts are written before GitHub mutation; `uv run pytest plugins/mission-control/tests/test_issue_create_prepared.py` exits 0

### Out-of-scope / non-goals
- Do not auto-move issues to Ready

### Files expected to change
plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
plugins/mission-control/tests/test_issue_create_prepared.py

### Verification
```bash
uv run pytest plugins/mission-control/tests/test_issue_create_prepared.py
```

### Context library links
_none_
"""


def _ready_draft(tmp_path: Path) -> Path:
    # W10: every readiness-passing draft must carry an author-supplied Stage —
    # no default exists (sdlc#91 OQ1 ruling), so the helper supplies one.
    return cast(
        Path,
        sdlc_manager.issue_prepare(
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
            stage="Intake",
        ),
    )


def _blocked_draft(tmp_path: Path) -> Path:
    return cast(
        Path,
        sdlc_manager.issue_prepare(
            repo="hermes-claude-code-router",
            issue_type="capability",
            team="campps",
            project="campps",
            source="Implement it.",
            title="Blocked issue workflow",
            status=None,
            risk="medium",
            mode=None,
            draft_dir=tmp_path,
        ),
    )


def _mapped_config() -> dict:
    return {
        "project_mappings": {
            "projects": {
                "campps": {
                    "number": 4,
                    "name": "CAMPPS",
                    "repositories": ["hermes-claude-code-router"],
                }
            }
        }
    }


def _unmapped_config() -> dict:
    return {
        "project_mappings": {
            "projects": {
                "campps": {
                    "number": 4,
                    "name": "CAMPPS",
                    "repositories": [],
                }
            }
        }
    }


def _write_post_create_pending(
    draft: Path, remaining_steps: list[str] | None = None, issue_number: int = 42
) -> None:
    sidecar_path = draft.with_suffix(".json")
    sidecar = json.loads(sidecar_path.read_text())
    sidecar.update(
        {
            "state": "post_create_pending",
            "created_issue_url": (
                f"https://github.com/infiquetra/hermes-claude-code-router/issues/{issue_number}"
            ),
            "created_issue_number": issue_number,
            "created_at": "2026-06-28T00:00:00+00:00",
            "remaining_steps": remaining_steps or ["board-add", "status"],
            "mutation_summary": [{"action": "issue", "detail": "created"}],
            "mapping_pr_url": None,
            "pending_mapping": False,
        }
    )
    sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")


def test_blocked_draft_refuses_to_mutate(tmp_path) -> None:
    draft = _blocked_draft(tmp_path)

    with (
        patch.object(sdlc_manager, "load_config") as mock_config,
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
        pytest.raises(RuntimeError, match="blocking readiness"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    mock_config.assert_not_called()
    mock_create.assert_not_called()


def test_create_prepared_refuses_unapproved_then_succeeds_after_approval(tmp_path) -> None:
    """The U11 gate is enforced (FIX 1): a ready-but-unapproved draft is refused
    with no GitHub mutation, and the same draft creates once approved."""
    draft = _ready_draft(tmp_path)
    assert (
        json.loads(draft.with_suffix(".json").read_text())["approval_state"]
        == "needs_operator_approval"
    )

    # Refusal path: load_config / _create_github_issue must never be reached.
    with (
        patch.object(sdlc_manager, "load_config") as mock_config,
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
        pytest.raises(RuntimeError, match="awaits operator approval"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)
    mock_config.assert_not_called()
    mock_create.assert_not_called()

    # Approve, then the same draft creates with no skip_approval override.
    sdlc_manager.prepared_approve_batch([draft], fmt="text")
    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/7", 7),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    assert result["number"] == 7


def test_create_prepared_skip_approval_bypasses_gate(tmp_path) -> None:
    """--skip-approval lets the operator's direct prepare->create path through
    the gate without an explicit approve step (FIX 1)."""
    draft = _ready_draft(tmp_path)

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/9", 9),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
    ):
        result = sdlc_manager.issue_create_prepared(
            draft, fmt="text", auto_confirm=True, skip_approval=True
        )

    assert result["created"] is True


def test_declined_confirmation_applies_no_mutation(tmp_path) -> None:
    draft = _ready_draft(tmp_path)

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_safe_input", return_value="n"),
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
    ):
        # skip_approval: this test exercises create *mechanics* (declined
        # confirmation), not the U11 approval gate (covered separately below).
        result = sdlc_manager.issue_create_prepared(
            draft, fmt="text", auto_confirm=False, skip_approval=True
        )

    assert result == {"created": False, "reason": "declined"}
    mock_create.assert_not_called()


def test_create_prepared_creates_issue_and_marks_draft(tmp_path) -> None:
    # Models the REAL operator flow end to end: prepare -> approve -> create.
    # No skip_approval — creation proceeds because the draft was approved first.
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")
    assert json.loads(draft.with_suffix(".json").read_text())["approval_state"] == "approved"

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/42", 42),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add") as mock_board,
        patch.object(sdlc_manager, "flow_set_field") as mock_status,
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    mock_board.assert_called_once_with(
        "hermes-claude-code-router",
        42,
        fmt="text",
        config=_mapped_config(),
        project_name="campps",
        strict=True,
    )
    # W10: the Intake exit writes BOTH lifecycle fields — Stage then Status.
    assert mock_status.call_args_list == [
        call("campps", "hermes-claude-code-router", 42, "Stage", "Intake", fmt="text"),
        call("campps", "hermes-claude-code-router", 42, "Status", "Capturing", fmt="text"),
    ]

    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "created"
    assert sidecar["created_issue_number"] == 42
    assert "## Created Issue" in draft.read_text()


def test_create_prepared_records_pending_state_when_board_add_fails(tmp_path) -> None:
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/42", 42),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add", side_effect=RuntimeError("board add failed")),
        patch.object(sdlc_manager, "flow_set_field") as mock_status,
        pytest.raises(RuntimeError, match="Remaining steps: board-add, stage, status"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    mock_status.assert_not_called()
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "post_create_pending"
    assert sidecar["created_issue_number"] == 42
    # W10: both lifecycle writes are still outstanding after the board-add failure.
    assert sidecar["remaining_steps"] == ["board-add", "stage", "status"]
    assert "## Created Issue" in draft.read_text()


def test_create_prepared_resumes_post_create_without_duplicate_issue(tmp_path) -> None:
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")
    _write_post_create_pending(draft)

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add") as mock_board,
        patch.object(sdlc_manager, "flow_set_field") as mock_status,
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    assert result["number"] == 42
    mock_create.assert_not_called()
    mock_board.assert_called_once_with(
        "hermes-claude-code-router",
        42,
        fmt="text",
        config=_mapped_config(),
        project_name="campps",
        strict=True,
    )
    # W10: the legacy sidecar (no "stage" token) still owes the Stage write, and
    # it happens before the Status write (KTD1a).
    assert mock_status.call_args_list == [
        call("campps", "hermes-claude-code-router", 42, "Stage", "Intake", fmt="text"),
        call("campps", "hermes-claude-code-router", 42, "Status", "Capturing", fmt="text"),
    ]
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "created"
    assert sidecar["remaining_steps"] == []


def test_create_prepared_resume_skips_existing_board_membership(tmp_path) -> None:
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")
    _write_post_create_pending(draft, remaining_steps=["board-add", "status"])

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=True),
        patch.object(sdlc_manager, "board_add") as mock_board,
        patch.object(sdlc_manager, "flow_set_field") as mock_status,
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    assert result["number"] == 42
    mock_create.assert_not_called()
    mock_board.assert_not_called()
    # W10: the legacy sidecar still owes Stage, written before Status.
    assert mock_status.call_args_list == [
        call("campps", "hermes-claude-code-router", 42, "Stage", "Intake", fmt="text"),
        call("campps", "hermes-claude-code-router", 42, "Status", "Capturing", fmt="text"),
    ]
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "created"
    assert sidecar["remaining_steps"] == []


def test_missing_mapping_opens_pr_and_stops_without_override(tmp_path) -> None:
    draft = _ready_draft(tmp_path)

    with (
        patch.object(sdlc_manager, "load_config", return_value=_unmapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_open_mapping_pr", return_value="https://github.com/pr/1"),
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
    ):
        # skip_approval: exercises the missing-mapping stop, not the approval gate.
        result = sdlc_manager.issue_create_prepared(
            draft, fmt="text", auto_confirm=True, skip_approval=True
        )

    assert result == {"created": False, "mapping_pr_url": "https://github.com/pr/1"}
    mock_create.assert_not_called()
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "mapping_pending"
    assert sidecar["pending_mapping"] == {
        "repo": "hermes-claude-code-router",
        "project": "campps",
    }


def test_override_mapping_creates_issue_and_records_pending_mapping(tmp_path) -> None:
    draft = _ready_draft(tmp_path)

    with (
        patch.object(sdlc_manager, "load_config", return_value=_unmapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_open_mapping_pr", return_value="https://github.com/pr/1"),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/42", 42),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
    ):
        # skip_approval: exercises the override-mapping create path, not the gate.
        result = sdlc_manager.issue_create_prepared(
            draft,
            fmt="text",
            auto_confirm=True,
            override_mapping=True,
            skip_approval=True,
        )

    assert result["created"] is True
    assert result["mapping_pr_url"] == "https://github.com/pr/1"
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "created"
    assert sidecar["pending_mapping"] is True


def test_missing_labels_and_templates_are_deployed_after_confirmation(tmp_path) -> None:
    draft = _ready_draft(tmp_path)

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=["hermes-task"]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=["capability.yml"]),
        patch.object(sdlc_manager, "labels_deploy") as mock_labels,
        patch.object(sdlc_manager, "rollout_deploy_templates") as mock_templates,
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/42", 42),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
    ):
        # skip_approval: exercises label/template deploy mechanics, not the gate.
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True, skip_approval=True)

    mock_labels.assert_called_once_with("hermes-claude-code-router", fmt="text")
    mock_templates.assert_called_once_with("hermes-claude-code-router", fmt="text")


def test_mapping_pr_uses_temporary_worktree(tmp_path) -> None:
    worktree_root = tmp_path / "infiquetra-sdlc"
    mapping_path = worktree_root / "config" / "project-mappings.json"
    mapping_path.parent.mkdir(parents=True)
    mapping_path.write_text('{"projects": {"campps": {"repositories": []}}}\n')

    with (
        patch.object(
            sdlc_manager,
            "_mapping_update_target",
            return_value=(mapping_path, worktree_root, "infiquetra-sdlc", None),
        ),
        patch.object(sdlc_manager, "_run_git_command", return_value="ok") as mock_git,
        patch.object(sdlc_manager, "_write_mapping_update") as mock_write,
        patch.object(
            sdlc_manager, "_gh", return_value="https://github.com/infiquetra/infiquetra-sdlc/pull/1"
        ),
    ):
        url = sdlc_manager._open_mapping_pr("hermes-claude-code-router", "campps")

    assert url == "https://github.com/infiquetra/infiquetra-sdlc/pull/1"
    git_args = [call.args[0] for call in mock_git.call_args_list]
    assert any(args[:3] == ["git", "worktree", "add"] for args in git_args)
    assert any(args[:4] == ["git", "worktree", "remove", "--force"] for args in git_args)
    assert not any(args[:2] == ["git", "checkout"] for args in git_args)

    written_path = mock_write.call_args.args[0]
    assert written_path != mapping_path
    assert written_path.name == "project-mappings.json"


# ---------------------------------------------------------------------------
# W10 — Mission Control owns the Intake exit (sdlc#91, AE32).
#
# Every test below round-trips through the production path:
# issue_prepare -> draft written -> _read_prepared_issue -> readiness -> create.
# No test hand-builds a draft file that skips the writer, because
# `_parse_draft_frontmatter` is a naive split(":", 1): a hand-built file could
# never witness that the writer itself never emits the literal "stage: None".
# ---------------------------------------------------------------------------


def _intake_exit_patches(draft: Path, *, flow_side_effect=None):
    """Standard stub set for an approved-draft create: no real GitHub calls."""
    flow_patch = patch.object(sdlc_manager, "flow_set_field", side_effect=flow_side_effect)
    return {
        "config": patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        "labels": patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        "templates": patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        "create": patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/42", 42),
        ),
        "item_exists": patch.object(
            sdlc_manager, "_prepared_project_item_exists", return_value=False
        ),
        "board": patch.object(sdlc_manager, "board_add"),
        "flow": flow_patch,
    }


def test_intake_exit_sets_stage_and_status_at_creation(tmp_path) -> None:
    """AE32: Mission Control creates the issue, joins the project, and sets BOTH
    Stage and Status — exactly two lifecycle writes, once each."""
    draft = _ready_draft(tmp_path)  # carries author-supplied Stage "Intake"
    sdlc_manager.prepared_approve_batch([draft], fmt="text")

    patches = _intake_exit_patches(draft)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"] as mock_create,
        patches["item_exists"],
        patches["board"] as mock_board,
        patches["flow"] as mock_flow,
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    mock_create.assert_called_once()
    assert mock_board.call_count == 1
    assert mock_board.call_args.kwargs["project_name"] == "campps"
    # Exactly two lifecycle writes, one per field — asserted on the recorded call
    # list, not a count, so writing the same field twice fails.
    assert [c.args[3] for c in mock_flow.call_args_list] == ["Stage", "Status"]
    assert [c.args[4] for c in mock_flow.call_args_list] == ["Intake", "Capturing"]
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "created"
    assert sidecar["remaining_steps"] == []


def test_intake_exit_writes_stage_before_status(tmp_path) -> None:
    """KTD1a: if the sequence ever breaks, the surviving card carries a Stage and
    no Status — never the R30/R31 Status-only shape."""
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")

    recorder: list[str] = []

    def _record(_project, _repo, _number, field_name, _option, *, fmt):  # noqa: ARG001
        recorder.append(field_name)

    patches = _intake_exit_patches(draft, flow_side_effect=_record)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"],
        patches["item_exists"],
        patches["board"],
        patches["flow"],
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert recorder == ["Stage", "Status"]


def test_intake_exit_joins_project_before_writing_fields(tmp_path) -> None:
    """R4: the project is joined before either lifecycle field is written — a
    field cannot be set on a board the issue has not joined."""
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")

    events: list[str] = []

    def _record_board(*_args, **_kwargs):
        events.append("board-add")

    def _record_flow(_p, _r, _n, field_name, _o, *, fmt):  # noqa: ARG001
        events.append(field_name)

    patches = _intake_exit_patches(draft, flow_side_effect=_record_flow)
    patches["board"] = patch.object(sdlc_manager, "board_add", side_effect=_record_board)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"],
        patches["item_exists"],
        patches["board"],
        patches["flow"],
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    # One shared recorder: board-add precedes both lifecycle writes, and the
    # writes themselves arrive Stage-then-Status.
    assert events == ["board-add", "Stage", "Status"]


def test_intake_exit_stage_failure_does_not_attempt_status(tmp_path) -> None:
    """R2 fail-stop: a failed Stage write is never followed by a Status write —
    the direct guard against flow_set_fields_bulk's continue-on-failure shape."""
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")

    def _raise_on_stage(_p, _r, _n, field_name, _o, *, fmt):  # noqa: ARG001
        if field_name == "Stage":
            raise RuntimeError("Stage write failed")

    patches = _intake_exit_patches(draft, flow_side_effect=_raise_on_stage)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"],
        patches["item_exists"],
        patches["board"],
        patches["flow"] as mock_flow,
        pytest.raises(RuntimeError, match="Stage write failed"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert [c.args[3] for c in mock_flow.call_args_list] == ["Stage"]
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "post_create_pending"
    assert sidecar["remaining_steps"] == ["stage", "status"]


def test_intake_exit_status_failure_leaves_stage_written_and_resumable(tmp_path) -> None:
    """W10 does not roll back a written Stage: recovery is resume, not rollback."""
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")

    def _raise_on_status(_p, _r, _n, field_name, _o, *, fmt):  # noqa: ARG001
        if field_name == "Status":
            raise RuntimeError("Status write failed")

    patches = _intake_exit_patches(draft, flow_side_effect=_raise_on_status)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"],
        patches["item_exists"],
        patches["board"],
        patches["flow"] as mock_flow,
        pytest.raises(RuntimeError, match="Status write failed"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    # `Stage` was attempted exactly once and completed; `Status` was attempted
    # (recorded before its side effect raised) and no rollback re-wrote Stage.
    assert [c.args[3] for c in mock_flow.call_args_list] == ["Stage", "Status"]
    assert len([c for c in mock_flow.call_args_list if c.args[3] == "Stage"]) == 1
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "post_create_pending"
    assert sidecar["remaining_steps"] == ["status"]


def test_intake_exit_missing_stage_fails_readiness(tmp_path) -> None:
    """R3a: the check runs against a RE-READ draft, so it sees `field()`'s ""
    (not an in-memory None) — and it lands in blocking, not warnings."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Stage-less draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    issue = sdlc_manager._read_prepared_issue(draft)

    readiness = sdlc_manager._readiness_for_prepared_issue(issue)

    assert readiness.passed is False
    assert any("Stage" in gap for gap in readiness.blocking_gaps)
    assert not any("Stage" in warning for warning in readiness.warnings)


def test_intake_exit_missing_stage_creates_no_issue(tmp_path) -> None:
    """The ruling: a draft missing Stage is refused BEFORE GitHub issue creation."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Stage-less draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )

    patches = _intake_exit_patches(draft)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"] as mock_create,
        patches["item_exists"],
        patches["board"],
        patches["flow"],
        pytest.raises(RuntimeError, match="blocking readiness"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    mock_create.assert_not_called()
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar.get("state") != "post_create_pending"


def test_intake_exit_stage_has_no_default(tmp_path) -> None:
    """R3: no team default, no handoff-maturity mapping, no phase-derived value —
    and the writer never serializes Python None as an authored Stage."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Default probe draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
        handoff_maturity="deferred-context",  # ruled: no maturity maps to Stage
        source_artifact=sdlc_manager.SourceArtifact(
            ref="objective-x",
            kind="spec",
            title="t",
            content="c",
            inferred_maturity="idea-ready",
        ),
    )

    assert draft.exists()  # R3b: prepare still produces the draft file
    re_read = sdlc_manager._read_prepared_issue(draft)
    assert not re_read.stage  # missing or empty — never a team default, maturity, or phase value
    # The front matter must not carry the authored string "None" — the naive
    # split(":", 1) parser would otherwise store it as a real Stage.
    assert "stage: None" not in draft.read_text()


def test_intake_exit_resume_does_not_duplicate_issue(tmp_path) -> None:
    """A crashed run resumes against post_create_pending and never re-creates."""
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")
    _write_post_create_pending(draft, remaining_steps=["stage", "status"])

    patches = _intake_exit_patches(draft)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"] as mock_create,
        patches["item_exists"],
        patch.object(sdlc_manager, "board_add"),
        patches["flow"] as mock_flow,
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    mock_create.assert_not_called()
    assert [c.args[3] for c in mock_flow.call_args_list] == ["Stage", "Status"]
    sidecar = json.loads(draft.with_suffix(".json").read_text())
    assert sidecar["state"] == "created"
    assert sidecar["remaining_steps"] == []


def test_intake_exit_resume_honors_legacy_sidecar_without_stage(tmp_path) -> None:
    """A sidecar written before W10 owes the Stage write even without a stage
    token in its remaining_steps — otherwise the draft finishes Status-only."""
    draft = _ready_draft(tmp_path)
    sdlc_manager.prepared_approve_batch([draft], fmt="text")
    _write_post_create_pending(draft, remaining_steps=["status"])

    patches = _intake_exit_patches(draft)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"] as mock_create,
        patches["item_exists"],
        patch.object(sdlc_manager, "board_add"),
        patches["flow"] as mock_flow,
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    mock_create.assert_not_called()
    assert [c.args[3] for c in mock_flow.call_args_list] == ["Stage", "Status"]


def test_intake_exit_mutation_plan_lists_stage_and_status(tmp_path) -> None:
    """The confirmation plan shows both writes, in write order."""
    draft = _ready_draft(tmp_path)
    issue = sdlc_manager._read_prepared_issue(draft)

    with (
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
    ):
        plan = sdlc_manager._build_mutation_plan(issue, _mapped_config())

    actions = [step.action for step in plan.steps]
    assert actions.index("set-stage") < actions.index("set-status")
    stage_step = next(step for step in plan.steps if step.action == "set-stage")
    assert stage_step.detail == f"Set Stage to {issue.stage}"


def test_intake_exit_blocked_draft_still_refuses(tmp_path) -> None:
    """Existing refusal contract: a blocked draft creates nothing and reaches no
    lifecycle write."""
    draft = _blocked_draft(tmp_path)

    patches = _intake_exit_patches(draft)
    with (
        patches["config"],
        patches["labels"],
        patches["templates"],
        patches["create"] as mock_create,
        patches["item_exists"],
        patch.object(sdlc_manager, "board_add"),
        patches["flow"] as mock_flow,
        pytest.raises(RuntimeError, match="blocking readiness"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    mock_create.assert_not_called()
    mock_flow.assert_not_called()


def test_intake_exit_fill_in_round_trips_through_approval_gate(tmp_path) -> None:
    """F-1 / sdlc#91 CR c1: the documented R3b recovery — prepare without Stage,
    edit `stage:` into the draft, create WITHOUT --skip-approval — must not
    bypass the U11 human gate. The repaired-blocked draft is promoted to
    needs_operator_approval and refused; after `issue approve` it creates."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Stage-less fill-in draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    sidecar_path = draft.with_suffix(".json")
    blocked_sidecar = json.loads(sidecar_path.read_text())
    assert blocked_sidecar["state"] == "blocked"
    assert blocked_sidecar["approval_state"] is None

    # The U11 batch approver cannot admit a None approval_state — it SKIPS.
    skip_result = sdlc_manager.prepared_approve_batch([draft], fmt="text")
    assert skip_result["skipped"] and skip_result["skipped"][0]["reason"] == (
        "approval_state is None"
    )

    # The author fills Stage into the draft file — R3b's fill-in surface.
    draft_text = draft.read_text()
    assert "\nstage: " not in draft_text
    draft.write_text(
        draft_text.replace(
            "labels: capability, needs-plan\n",
            "stage: Intake\nstatus: Capturing\nlabels: capability, needs-plan\n",
            1,
        )
    )

    # The re-read draft now passes readiness — but create-prepared without
    # --skip-approval must still refuse, and the sidecar must be promoted.
    re_read = sdlc_manager._read_prepared_issue(draft)
    readiness = sdlc_manager._readiness_for_prepared_issue(re_read)
    assert readiness.passed is True

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_create_github_issue") as mock_create,
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
        pytest.raises(RuntimeError, match="awaits operator approval"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    mock_create.assert_not_called()
    promoted = json.loads(sidecar_path.read_text())
    assert promoted["state"] == "ready_to_create"
    assert promoted["approval_state"] == "needs_operator_approval"

    # The gate admits the promoted draft once approved, and the two-field
    # Intake exit runs normally after approval.
    sdlc_manager.prepared_approve_batch([draft], fmt="text")
    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/11", 11),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field") as mock_flow,
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    assert [c.args[3] for c in mock_flow.call_args_list] == ["Stage", "Status"]


def test_intake_exit_fill_in_stage_only_defaults_status_on_read(tmp_path) -> None:
    """F-3 / cycle-5 (sdlc#91): the R3b fill-in may add ONLY `stage:` — a
    stage-less blocked prepare legitimately emitted no `status:` line, because
    no default is derivable without a Stage. `_read_prepared_issue` applies the
    entry-option default BEFORE readiness evaluates, so the repaired draft is
    readable and readiness-passing without a hand-written Status."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Stage-only fill-in draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    sidecar_path = draft.with_suffix(".json")
    assert json.loads(sidecar_path.read_text())["state"] == "blocked"
    assert "\nstatus: " not in draft.read_text()

    # The author fills Stage into the draft file — R3b's fill-in surface —
    # and nothing else.
    draft.write_text(
        draft.read_text().replace(
            "labels: capability, needs-plan\n",
            "stage: Intake\nlabels: capability, needs-plan\n",
            1,
        )
    )

    re_read = sdlc_manager._read_prepared_issue(draft)
    assert re_read.stage == "Intake"
    assert re_read.status == "Capturing"
    readiness = sdlc_manager._readiness_for_prepared_issue(re_read)
    assert readiness.passed is True
    assert readiness.blocking_gaps == []


def test_intake_exit_fill_in_skip_approval_is_explicit_override(tmp_path) -> None:
    """--skip-approval remains the operator's explicit per-invocation override on
    the repaired-blocked fill-in path — but the STAMP is NOT skipped (CR c2
    F-1): the sidecar must carry needs_operator_approval after this run, so a
    later create WITHOUT the flag refuses instead of falling through as a
    pre-U11 legacy draft. --skip-approval bypasses the gate for THIS
    invocation; it never means 'record that no gate is owed'."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Stage-less override draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    draft.write_text(
        draft.read_text().replace(
            "labels: capability, needs-plan\n",
            "stage: Intake\nstatus: Capturing\nlabels: capability, needs-plan\n",
            1,
        )
    )

    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/12", 12),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
    ):
        result = sdlc_manager.issue_create_prepared(
            draft, fmt="text", auto_confirm=True, skip_approval=True
        )

    assert result["created"] is True
    # F-3 (CR c2): the claim this test makes IS the sidecar stamp. The
    # promotion is not skipped by --skip-approval — the gate record survives.
    stamped = json.loads(draft.with_suffix(".json").read_text())
    assert stamped["approval_state"] == "needs_operator_approval"
    assert stamped["state"] == "created"


def test_intake_exit_fill_in_skip_approval_mapping_resume_stamps_gate(tmp_path) -> None:
    """CR c2 F-1: fill-in + --skip-approval stopping at mapping_pending must
    STAMP the U11 gate. The unmapped create writes state=mapping_pending; after
    the fix the sidecar keeps approval_state=needs_operator_approval, so a
    LATER create WITHOUT --skip-approval refuses instead of falling through
    the None as a pre-U11 legacy draft. _create_github_issue is never called
    on either invocation."""
    draft = sdlc_manager.issue_prepare(
        repo="hermes-claude-code-router",
        issue_type="capability",
        team="campps",
        project="campps",
        source=OLYMPUS_BODY,
        title="Stage-less mapping-resume draft",
        status=None,
        risk="medium",
        mode=None,
        draft_dir=tmp_path,
    )
    # The R3b fill-in: the author edits `stage:` into the blocked draft.
    draft.write_text(
        draft.read_text().replace(
            "labels: capability, needs-plan\n",
            "stage: Intake\nstatus: Capturing\nlabels: capability, needs-plan\n",
            1,
        )
    )
    sidecar_path = draft.with_suffix(".json")

    # Invocation 1: skip_approval + UNMAPPED config → mapping_pending stop.
    with (
        patch.object(sdlc_manager, "load_config", return_value=_unmapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_open_mapping_pr", return_value="https://github.com/pr/2"),
        patch.object(sdlc_manager, "_create_github_issue") as mock_create_first,
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
    ):
        result = sdlc_manager.issue_create_prepared(
            draft, fmt="text", auto_confirm=True, skip_approval=True
        )

    assert result == {"created": False, "mapping_pr_url": "https://github.com/pr/2"}
    mock_create_first.assert_not_called()
    stopped = json.loads(sidecar_path.read_text())
    assert stopped["state"] == "mapping_pending"
    # The stamp: the durable gate record survived the skip-approval invocation.
    assert stopped["approval_state"] == "needs_operator_approval"

    # Invocation 2: skip_approval=False + MAPPED config (the PR has been
    # merged meanwhile) — MUST refuse; the None fall-through is gone.
    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(sdlc_manager, "_create_github_issue") as mock_create_second,
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
        pytest.raises(RuntimeError, match="awaits operator approval"),
    ):
        sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    mock_create_second.assert_not_called()


def test_intake_exit_pre_u11_ready_none_sidecar_still_creates(tmp_path) -> None:
    """CR c2 F-2: the second half of the None split is deliberate load-bearing
    back-compat — a ready_to_create sidecar carrying approval_state=None (a
    pre-U11 legacy draft) proceeds WITHOUT --skip-approval and WITHOUT refusal,
    and runs the two-field Intake exit. Pinned deliberately so a regression
    that blocks every None cannot hide behind the fill-in tests."""
    draft = _ready_draft(tmp_path)  # prepare with Stage (gate path irrelevant)
    sidecar_path = draft.with_suffix(".json")

    # Model a vintage pre-U11 draft: ready sidecar, no recorded approval.
    sidecar = json.loads(sidecar_path.read_text())
    sidecar["state"] = "ready_to_create"
    sidecar["approval_state"] = None
    sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n")

    # The U11 batch approver still cannot admit a None — it skips.
    skip_result = sdlc_manager.prepared_approve_batch([draft], fmt="text")
    assert skip_result["skipped"] and skip_result["skipped"][0]["reason"] == (
        "approval_state is None"
    )

    # The legacy draft falls through the split's None branch and creates.
    with (
        patch.object(sdlc_manager, "load_config", return_value=_mapped_config()),
        patch.object(sdlc_manager, "_repo_missing_labels", return_value=[]),
        patch.object(sdlc_manager, "_repo_missing_templates", return_value=[]),
        patch.object(
            sdlc_manager,
            "_create_github_issue",
            return_value=("https://github.com/infiquetra/hermes-claude-code-router/issues/21", 21),
        ),
        patch.object(sdlc_manager, "_prepared_project_item_exists", return_value=False),
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field") as mock_flow,
    ):
        result = sdlc_manager.issue_create_prepared(draft, fmt="text", auto_confirm=True)

    assert result["created"] is True
    assert [c.args[3] for c in mock_flow.call_args_list] == ["Stage", "Status"]
