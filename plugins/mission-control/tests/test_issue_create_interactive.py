"""Tests for the rewritten interactive `issue create` flow.

The flow is per-project-schema-aware, defaults-driven, capability-adaptive,
paired-card capable, and supports optional decomposition parents. These tests
exercise the small composable helpers (`_select_issue_type`,
`_prompt_parent_issue`, `_prompt_choice`, `_prompt_paired_card`,
`_apply_post_create_metadata`) plus the integration via skip_metadata.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

# --- _select_issue_type ----------------------------------------------------


def test_select_issue_type_returns_typed_choice() -> None:
    with patch("builtins.input", return_value="defect"):
        assert sdlc_manager._select_issue_type() == "defect"


def test_select_issue_type_returns_default_on_blank() -> None:
    """Empty input → default (custom or built-in 'capability')."""
    with patch("builtins.input", return_value=""):
        assert sdlc_manager._select_issue_type() == "capability"
    with patch("builtins.input", return_value=""):
        assert sdlc_manager._select_issue_type(default="enhancement") == "enhancement"


def test_select_issue_type_falls_back_on_invalid() -> None:
    """Garbage input falls back to default rather than crashing."""
    with patch("builtins.input", return_value="bogus-type"):
        assert sdlc_manager._select_issue_type() == "capability"


def test_select_issue_type_handles_eof_returns_default() -> None:
    """Ctrl+D returns the default — no traceback."""
    with patch("builtins.input", side_effect=EOFError):
        assert sdlc_manager._select_issue_type(default="defect") == "defect"


# --- _prompt_parent_issue --------------------------------------------------


def test_parent_prompt_parses_direct_ref() -> None:
    """Operator pastes 'campps-context-library#42' directly at the prompt."""
    with patch("builtins.input", return_value="campps-context-library#42"):
        assert sdlc_manager._prompt_parent_issue() == ("campps-context-library", 42)


def test_parent_prompt_yes_then_ref() -> None:
    """Operator says 'yes', then provides ref at the follow-up."""
    with patch("builtins.input", side_effect=["yes", "mimir#7"]):
        assert sdlc_manager._prompt_parent_issue() == ("mimir", 7)


def test_parent_prompt_blank_defaults_to_no_parent() -> None:
    """Empty input keeps a top-level card top-level."""
    with patch("builtins.input", return_value=""):
        assert sdlc_manager._prompt_parent_issue() is None


def test_parent_prompt_no_returns_none() -> None:
    """'no' → free-floating card, return None."""
    with patch("builtins.input", return_value="no"):
        assert sdlc_manager._prompt_parent_issue() is None
    with patch("builtins.input", return_value="n"):
        assert sdlc_manager._prompt_parent_issue() is None


def test_parent_prompt_invalid_ref_warns_and_returns_none() -> None:
    """A garbage ref doesn't crash — falls through to no-parent + warns."""
    with patch("builtins.input", return_value="not-a-ref"):
        assert sdlc_manager._prompt_parent_issue() is None


def test_parent_prompt_eof_returns_none() -> None:
    """Ctrl+D returns None gracefully."""
    with patch("builtins.input", side_effect=EOFError):
        assert sdlc_manager._prompt_parent_issue() is None


# --- _prompt_choice (per-project schema discovery) -------------------------


def test_prompt_choice_returns_none_when_field_does_not_exist() -> None:
    """If options=None (signaled by `_project_field_options` for missing
    fields), the prompt is silently skipped — caller doesn't ask the
    operator about a field the project doesn't expose."""
    # No input call expected — the function returns immediately
    assert sdlc_manager._prompt_choice("Initiative", options=None) is None


def test_prompt_choice_accepts_valid_option() -> None:
    with patch("builtins.input", return_value="olympus-quality"):
        result = sdlc_manager._prompt_choice(
            "Initiative",
            options=["olympus-quality", "olympus-performance"],
        )
        assert result == "olympus-quality"


def test_prompt_choice_uses_default_on_blank_input() -> None:
    """Empty input + a default that's in the options list → default."""
    with patch("builtins.input", return_value=""):
        result = sdlc_manager._prompt_choice(
            "Status",
            options=["Backlog", "Ready", "In Review"],
            default="Backlog",
        )
        assert result == "Backlog"


def test_prompt_choice_skips_on_dash() -> None:
    with patch("builtins.input", return_value="-"):
        result = sdlc_manager._prompt_choice(
            "Initiative",
            options=["olympus-quality"],
        )
        assert result is None


def test_prompt_choice_warns_on_invalid_value(capsys) -> None:
    """A typo doesn't crash — operator gets a warning + skip."""
    with patch("builtins.input", return_value="olympusqulaity"):
        result = sdlc_manager._prompt_choice(
            "Initiative",
            options=["olympus-quality", "olympus-performance"],
        )
        assert result is None
    captured = capsys.readouterr()
    assert (
        "not in" in (captured.out + captured.err).lower()
        or "skipping" in (captured.out + captured.err).lower()
    )


# --- _prompt_paired_card ---------------------------------------------------


def test_paired_card_default_is_no() -> None:
    """Empty input → no paired card (the safe default)."""
    with patch("builtins.input", return_value=""):
        assert sdlc_manager._prompt_paired_card("campps-mvp", 42) is None


def test_paired_card_yes_returns_target_repo() -> None:
    """y → prompts for target repo. Phase C v1 only captures the target
    repo; the title/body delta prompts were removed because the orchestrator
    was discarding them anyway (UX promise we don't keep)."""
    inputs = ["y", "campps-flutter-app"]
    with patch("builtins.input", side_effect=inputs):
        result = sdlc_manager._prompt_paired_card("campps-mvp", 42)
        assert result == "campps-flutter-app"


def test_paired_card_yes_no_target_returns_none() -> None:
    """y → empty target repo → None (operator changed their mind)."""
    inputs = ["y", ""]
    with patch("builtins.input", side_effect=inputs):
        assert sdlc_manager._prompt_paired_card("campps-mvp", 42) is None


def test_paired_card_recursion_guard() -> None:
    """When `issue_create` is called with `_in_paired_card=True`, the
    paired-card prompt is suppressed — preventing chain-recursion if an
    operator types yes-yes-yes."""
    # We mock everything below the paired-card check so the test only
    # exercises the recursion-suppression branch.
    with (
        patch.object(sdlc_manager, "load_user_defaults", return_value={}),
        patch.object(
            sdlc_manager, "load_config", return_value={"project_mappings": {"projects": {}}}
        ),
        patch.object(sdlc_manager, "get_projects_for_repo", return_value=[]),
        patch.object(sdlc_manager, "_prompt_parent_issue", return_value=None),
        patch.object(sdlc_manager, "_open_gh_issue_create_web"),
        patch.object(sdlc_manager, "_prompt_issue_number", return_value=42),
        patch.object(sdlc_manager, "_apply_post_create_metadata"),
        patch.object(sdlc_manager, "_prompt_paired_card") as mock_paired,
        patch("builtins.input", return_value="y"),
    ):  # confirm "Open browser?"
        sdlc_manager.issue_create(
            "campps-mvp",
            "capability",
            "text",
            _in_paired_card=True,
        )
    # The paired-card prompt must NOT have been called when recursing
    mock_paired.assert_not_called()


# --- _apply_post_create_metadata ------------------------------------------


def test_metadata_applies_type_labels_for_actionable_types() -> None:
    """Capability/enhancement/defect get their type label plus `needs-plan`.

    This path used to guarantee only the retired `hermes-task` dispatch marker —
    not even the type label — so a card whose browser template failed to prefill
    landed untyped.
    """
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
        patch.object(sdlc_manager, "flow_link_sub_issue"),
        patch.object(sdlc_manager, "load_config", return_value={}),
    ):
        sdlc_manager._apply_post_create_metadata(
            repo="campps-mvp",
            issue_number=42,
            issue_type="capability",
            project_name=None,
            parent=None,
            field_values={},
            fmt="text",
        )
    cmd_calls = [c.args[0] for c in mock_gh.call_args_list]
    label_call = next((c for c in cmd_calls if "edit" in c and "--add-label" in c), None)
    assert label_call is not None
    applied = label_call[label_call.index("--add-label") + 1]
    assert applied == "capability,needs-plan"
    assert "hermes" not in applied


def test_objective_is_not_a_creatable_issue_type() -> None:
    assert "objective" not in sdlc_manager._ISSUE_TYPES

    with pytest.raises(RuntimeError, match="Unknown or retired issue type 'objective'"):
        sdlc_manager._apply_post_create_metadata(
            repo="campps-context-library",
            issue_number=1,
            issue_type="objective",
            project_name=None,
            parent=None,
            field_values={},
            fmt="text",
        )


def test_metadata_applies_context_labels_for_exploration() -> None:
    """Exploration/context-update are non-actionable template types."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "board_add"),
        patch.object(sdlc_manager, "flow_set_field"),
        patch.object(sdlc_manager, "flow_link_sub_issue"),
        patch.object(sdlc_manager, "load_config", return_value={}),
    ):
        sdlc_manager._apply_post_create_metadata(
            repo="campps-context-library",
            issue_number=2,
            issue_type="exploration",
            project_name=None,
            parent=None,
            field_values={},
            fmt="text",
        )
    cmd_calls = [c.args[0] for c in mock_gh.call_args_list]
    label_call = next((c for c in cmd_calls if "edit" in c and "--add-label" in c), None)
    assert label_call is not None
    applied = label_call[label_call.index("--add-label") + 1]
    assert applied == "exploration,research"
    assert not any("hermes" in str(call) for call in cmd_calls)


def test_metadata_label_failure_does_not_abort_other_steps() -> None:
    """If the hermes-task label apply fails, the project field assignment
    + sub-issue link should still be attempted. Each step is isolated."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "board_add") as mock_board,
        patch.object(sdlc_manager, "flow_set_field") as mock_set_field,
        patch.object(sdlc_manager, "flow_link_sub_issue") as mock_link,
        patch.object(sdlc_manager, "load_config", return_value={}),
    ):
        # First call (label apply) fails; downstream calls still happen
        mock_gh.side_effect = sdlc_manager.GhApiError("label apply failed")
        sdlc_manager._apply_post_create_metadata(
            repo="campps-mvp",
            issue_number=42,
            issue_type="capability",
            project_name="campps",
            parent=("campps-context-library", 1),
            field_values={"Initiative": "olympus-quality"},
            fmt="text",
        )
    # board_add was still called despite the label failure
    mock_board.assert_called_once()
    # flow_set_field was called for the Initiative
    mock_set_field.assert_called_once()
    # flow_link_sub_issue was called for the parent
    mock_link.assert_called_once()


def test_metadata_skips_field_apply_when_no_project() -> None:
    """If the repo isn't mapped to a project, skip board add + field
    assignment but still apply hermes labels + sub-issue link."""
    with (
        patch.object(sdlc_manager, "_gh"),
        patch.object(sdlc_manager, "board_add") as mock_board,
        patch.object(sdlc_manager, "flow_set_field") as mock_set_field,
        patch.object(sdlc_manager, "flow_link_sub_issue") as mock_link,
        patch.object(sdlc_manager, "load_config", return_value={}),
    ):
        sdlc_manager._apply_post_create_metadata(
            repo="some-unmapped-repo",
            issue_number=42,
            issue_type="capability",
            project_name=None,
            parent=("campps-context-library", 1),
            field_values={"Initiative": "olympus-quality"},
            fmt="text",
        )
    mock_board.assert_not_called()
    mock_set_field.assert_not_called()  # no project = no fields to set
    mock_link.assert_called_once()  # sub-issue link still applies


def test_parent_ref_regex_accepts_realistic_refs() -> None:
    """Coverage of the parent-ref regex used by both the prompt and the
    --parent-ref CLI flag."""

    def parse(s: str):
        return sdlc_manager._PARENT_REF_RE.match(s)

    assert parse("campps-context-library#42") is not None
    assert parse("infiquetra-sdlc#7") is not None
    assert parse("a.b.c#99") is not None  # dots allowed for completeness
    assert parse("repo#0") is not None  # not pretty but valid syntactically
    # Negative cases
    assert parse("just-text") is None
    assert parse("#42") is None  # missing repo
    assert parse("repo-only") is None  # missing #N


# --- _gate_created_issue_body ----------------------------------------------
# The interactive path used to apply labels + board membership with no body
# check, so a blank template landed on the board looking like a good card.
# These cover each branch of the gate.

_GOOD_BODY = """### Objective
platform-quality

### Intent
Wire the card validator into the interactive create path.

### Out-of-scope / non-goals
- Does not change the prepared path.

### Files expected to change
- plugins/mission-control/scripts/sdlc_manager.py

### Tests to add or update
- plugins/mission-control/tests/test_issue_create_interactive.py

### Context library links
_none_

### Acceptance criteria
- [ ] A malformed body blocks metadata: `uv run pytest -q`

### Verification
```bash
uv run pytest plugins/mission-control/tests/ -q
```
"""


def test_gate_skips_non_actionable_types() -> None:
    """exploration/context-update ship different field sets by design — the
    eight-section contract must not be applied to them."""
    for issue_type in ("exploration", "context-update"):
        with patch.object(sdlc_manager, "_rest_get") as rest:
            assert sdlc_manager._gate_created_issue_body("repo", 1, issue_type, "text") is True
            rest.assert_not_called()


def test_gate_passes_a_conformant_body() -> None:
    with patch.object(sdlc_manager, "_rest_get", return_value={"body": _GOOD_BODY}):
        assert sdlc_manager._gate_created_issue_body("repo", 42, "capability", "text") is True


def test_gate_blocks_empty_body_by_default() -> None:
    """Enter (or 'n') at the override prompt leaves the issue un-carded."""
    with (
        patch.object(sdlc_manager, "_rest_get", return_value={"body": ""}),
        patch.object(sdlc_manager, "_safe_input", return_value=""),
    ):
        assert sdlc_manager._gate_created_issue_body("repo", 42, "defect", "text") is False


def test_gate_blocks_malformed_body_and_reports_gaps(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch.object(sdlc_manager, "_rest_get", return_value={"body": "### Objective\nonly this"}),
        patch.object(sdlc_manager, "_safe_input", return_value="n"),
    ):
        assert sdlc_manager._gate_created_issue_body("repo", 7, "enhancement", "text") is False
    out = capsys.readouterr().out
    assert "INVALID: repo#7" in out
    assert "gh issue edit 7" in out
    assert "not applied" in out


def test_gate_honours_explicit_override() -> None:
    """The operator can still proceed knowingly — this is a stop, not a veto."""
    with (
        patch.object(sdlc_manager, "_rest_get", return_value={"body": "nope"}),
        patch.object(sdlc_manager, "_safe_input", return_value="y"),
    ):
        assert sdlc_manager._gate_created_issue_body("repo", 7, "capability", "text") is True


def test_gate_does_not_prompt_in_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    """A non-interactive caller gets a structured refusal, never a hung prompt."""
    with (
        patch.object(sdlc_manager, "_rest_get", return_value={"body": "nope"}),
        patch.object(sdlc_manager, "_safe_input") as ask,
    ):
        assert sdlc_manager._gate_created_issue_body("repo", 7, "defect", "json") is False
        ask.assert_not_called()
    assert '"metadata_applied": false' in capsys.readouterr().out


def test_gate_proceeds_when_the_issue_cannot_be_fetched() -> None:
    """An API hiccup must not strand a good issue — fetch failure is not a
    validation failure."""
    with patch.object(sdlc_manager, "_rest_get", side_effect=RuntimeError("502")):
        assert sdlc_manager._gate_created_issue_body("repo", 7, "capability", "text") is True
