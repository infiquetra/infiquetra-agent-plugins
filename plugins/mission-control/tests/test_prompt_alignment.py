"""Drift guards for mission-control prompts, references, and release metadata."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _find_package_root(start: Path | None = None) -> Path:
    current = start or Path(__file__)
    for parent in current.resolve().parents:
        if (parent / ".claude-plugin" / "plugin.json").is_file():
            return parent
    raise RuntimeError(
        f"package root containing .claude-plugin/plugin.json not found from {current.resolve()}"
    )


def _find_repo_root(package_root: Path) -> Path:
    for parent in package_root.resolve().parents:
        if (parent / ".claude-plugin" / "marketplace.json").is_file():
            return parent
    raise RuntimeError(
        f"repository root containing .claude-plugin/marketplace.json not found from {package_root.resolve()}"
    )


PACKAGE_ROOT = _find_package_root()
PLUGIN_ROOT = PACKAGE_ROOT
ADAPTER = PACKAGE_ROOT / "com.infiquetra.claude"
ROOT = _find_repo_root(PACKAGE_ROOT)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_sdlc_manager_metadata_and_marketplace_entry_match() -> None:
    plugin_json = json.loads(_read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json"))
    marketplace = json.loads(_read(ROOT / ".claude-plugin" / "marketplace.json"))
    entry = next(p for p in marketplace["plugins"] if p["name"] == "mission-control")

    assert plugin_json["name"] == "mission-control"
    assert (
        plugin_json["version"] == "2.21.1"
    )  # 2.21.1: authored cut in this catalog; upstream at the import pin is 2.21.0.
    # 2.21.0: the Mount Olympus status vocabulary leaves agent-facing prose
    # and the board move --status help (issue 1042). Predecessor 2.20.0:
    # the saga readiness reader loses its handoff-envelope and
    # reversibility-certificate paths, both removed by issue 1030.
    # Predecessor 2.19.0:
    # the tier-band comment names fleet-core's merged staffing data (issue 1021);
    # renumbered from 2.18.0 when main was folded into parent/1018.
    # Predecessor 2.18.0: board census regenerated and keyed by field name, stage-flow prose,
    # drift guard (issue 1020); renumbered from 2.17.0 in the same fold.
    # Predecessor 2.17.0: advisory triage suggestions and the widen-only labels union (issue 1035)
    # Predecessor 2.16.0: schema resync, Risk body field, Saga readiness delegation
    # (issues 999/1000/942)
    assert entry["version"] == plugin_json["version"]
    assert entry["source"] == "./plugins/mission-control"
    assert "CAMPPS" in plugin_json["description"]
    assert "Mount Olympus" not in plugin_json["description"]
    assert "campps" in plugin_json["keywords"]
    assert "mount-olympus" not in plugin_json["keywords"]
    assert "Operations" in entry["description"]
    assert "Beads" not in entry["description"]
    assert "beads" not in entry["keywords"]


def test_issue_type_reference_uses_current_template_labels() -> None:
    issue_types = _read(PLUGIN_ROOT / "skills/issues/references/issue-types.md")

    assert "`capability`, `needs-plan`" in issue_types
    assert "`enhancement`, `needs-plan`" in issue_types
    assert "`defect`, `needs-plan`" in issue_types
    assert "`exploration`, `research`" in issue_types
    assert "`context-update`, `documentation`" in issue_types
    # the retired Hermes dispatch markers must not come back
    assert "hermes-task" not in issue_types
    assert "hermes-not-actionable" not in issue_types
    assert "`capability`, `needs-analysis` (auto-applied by template)" not in issue_types
    assert "`enhancement`, `needs-analysis` (auto-applied by template)" not in issue_types
    assert "`defect`, `needs-triage` (auto-applied by template)" not in issue_types
    assert "`objective:{short-name}`" not in issue_types
    assert "`initiative:{name}`" not in issue_types


def test_field_first_hierarchy_guidance_is_consistent() -> None:
    issue_skill = _read(PLUGIN_ROOT / "skills/issues/SKILL.md")
    flow_skill = _read(PLUGIN_ROOT / "skills/flow/SKILL.md")
    milestone_skill = _read(PLUGIN_ROOT / "skills/milestones/SKILL.md")
    rollout_hierarchy = _read(PLUGIN_ROOT / "skills/rollout/references/work-hierarchy.md")

    assert "5-type issue" in issue_skill
    assert "Objective is an `Objective` project-field option" in issue_skill
    assert "flow unlink-sub-issue" in flow_skill
    assert "Create the Objective issue" not in milestone_skill
    assert "Capability issue (top-level)" in rollout_hierarchy
    assert "Objective issue + project field option" not in rollout_hierarchy


def test_operator_prompt_honors_the_card_contract_split() -> None:
    operator = _read(ADAPTER / "agents/sdlc-operator.md")

    assert "(capability/enhancement/defect)" in operator
    assert "(exploration/context-update)" in operator
    assert "(capability/enhancement/defect/exploration/context-update)" not in operator
    assert "Step 2: Applied labels (capability, needs-plan)" in operator
    assert "hermes-task" not in operator
    assert "hermes-not-actionable" not in operator
    assert "issue prepare" in operator
    assert "issue create-prepared" in operator
    # W10 cycle-5: starting Status is Stage-derived (R49 entry-option default);
    # readiness accepts any Stage-configured Status or Blocked.
    assert "Status` defaulting to the declared `Stage`'s entry option" in operator
    # The retired team-keyed starting statuses must not come back.
    assert "Asgard `Shaping`, CAMPPS `Idea`" not in operator
    assert "safe statuses: Asgard" not in operator
    # Olympus is retired; it must not be presented as an active safe-start board.
    assert "Olympus `Backlog`" not in operator
    assert "every new card has a parent by default" not in operator
    assert "flow unlink-sub-issue" in operator


def test_triage_command_uses_project_fields_and_current_actionable_labels() -> None:
    triage = _read(ADAPTER / "commands/triage.md")

    assert "Initiative/Objective project field values" in triage
    assert "initiative/objective labels" not in triage
    assert '"capability,needs-plan"' in triage
    assert "hermes-task" not in triage
    assert "Add `needs-analysis` label" not in triage


def test_label_docs_mark_legacy_auto_label_rules_as_fallback() -> None:
    skill = _read(PLUGIN_ROOT / "skills/labels/SKILL.md")
    reference = _read(PLUGIN_ROOT / "skills/labels/references/labels-reference.md")

    assert "legacy fallback behavior" in skill
    assert "legacy fallback labels" in skill
    assert "legacy fallback labels" in reference
    assert "legacy fallback rules" in reference
    assert "Current capability,\nenhancement, and defect templates apply `needs-plan`" in reference


def test_prepared_issue_guidance_routes_natural_language_creation() -> None:
    skill = _read(PLUGIN_ROOT / "skills/issues/SKILL.md")
    create_command = _read(ADAPTER / "commands/issue.md")
    readme = _read(PLUGIN_ROOT / "README.md")

    # NOTE: the former /sdlc-create compatibility alias command was removed in the
    # family rename (mission-control commands = issue/board/metrics/triage). Its
    # alias-specific assertions are gone with it; /issue is the single primary command.
    for text in (skill, create_command, readme):
        assert "issue prepare" in text
        assert "issue create-prepared" in text

    assert "name: issue" in create_command
    assert "--prepare" in create_command
    assert "--draft" in create_command
    assert "--from" in create_command
    assert "--maturity" in create_command
    assert "`/issue` is the primary user-facing command" in skill
    assert "/issue [type]" in readme
    assert "Create a CAMPPS issue from this text" in skill
    assert "Create an Asgard issue from these notes" in skill
    # Olympus is retired; the natural-language router must not steer new work to it.
    assert "Olympus issue from this text" not in skill
    assert "Create an issue from the brainstorm" in skill
    assert "handoff_maturity" in skill
    assert "If team or project is ambiguous, ask" in skill
    assert "Never auto-move a prepared issue to `Ready for Planning`" in skill
    assert "from the brainstorm" in create_command
    assert "handoff the plan" in create_command
    assert "/loop <issue>" not in create_command
    assert "compatibility alias" not in create_command
    assert "remains a compatibility alias" not in create_command


def test_asgard_campps_model_retires_olympus_as_active_target() -> None:
    schema = json.loads(_read(PLUGIN_ROOT / "config/sdlc-schema.json"))
    roles = schema["work_hierarchy"]["roles"]

    assert schema["schema_version"] == "2026-09-07.5"
    assert roles["objective"]["project_view_group_by"] == "Objective"
    assert roles["outcome"]["required_by_default"] is False
    assert roles["capability"]["default_parent_role"] is None
    assert roles["capability"]["allowed_parent_roles"] == ["outcome"]
    assert schema["teams"]["asgard"]["status"] == "active"
    assert schema["teams"]["olympus"]["status"] == "retired_historical"
    assert schema["teams"]["olympus"]["board"] is None
    assert "olympus" not in schema["boards"]
    assert schema["boards"]["campps"]["status"] == "active"
    # The Asgard field set slimmed to the lifecycle pair (Stage/Status) +
    # Objective/Priority; Mode, target surface, risk and transfer intent moved
    # into the issue body per the card contract, and the retired
    # target_team_values list was deleted from team_routing.
    assert "Stage" in schema["fields"]["asgard"]
    assert "Transfer Target" not in schema["fields"]["asgard"]
    assert "Promotion Target" not in schema["fields"]["asgard"]
    assert "cross_team_transfer_rule" in schema["team_routing"]
    assert "asgard_to_olympus_rule" not in schema["team_routing"]
    assert "target_team_values" not in schema["team_routing"]
    assert "Asgard and CAMPPS" in schema["team_routing"]["cross_team_transfer_rule"]
    assert (
        "Mount Olympus is retired historical context"
        in schema["team_routing"]["cross_team_transfer_rule"]
    )

    active_surfaces = [
        PLUGIN_ROOT / "config/sdlc-schema.json",
        PLUGIN_ROOT / "scripts/sdlc_manager.py",
        PLUGIN_ROOT / "skills/board/references/kanban-workflow.md",
        PLUGIN_ROOT / "skills/issues/SKILL.md",
        ADAPTER / "commands/issue.md",
        ADAPTER / "commands/issue.md",
        ADAPTER / "agents/sdlc-operator.md",
        PLUGIN_ROOT / "README.md",
    ]
    stale_phrases = [
        "asgard_to_olympus",
        "Promotion Target",
        "Promotion gaps",
        "Olympus promotion gaps",
        "Asgard Seeds Olympus",
        "seed Olympus",
        "promote to Olympus",
        # W10 cycle-5: the retired team-keyed starting statuses (F-1) must not
        # come back on any active surface — readiness now derives from Stage.
        "Asgard starts in `Shaping`",
        "CAMPPS starts in `Idea`",
        "safe statuses: Asgard `Shaping`",
    ]

    for path in active_surfaces:
        text = _read(path)
        for phrase in stale_phrases:
            assert phrase not in text, f"{path.relative_to(ROOT)} contains stale phrase {phrase!r}"


def test_find_package_root_resolves_plugin_root() -> None:
    root = _find_package_root()
    assert (root / ".claude-plugin" / "plugin.json").is_file()
    assert (root / "skills" / "issues" / "SKILL.md").is_file()
    assert root == PACKAGE_ROOT


def test_find_package_root_fails_loudly_when_missing(tmp_path: Path) -> None:
    dummy_file = tmp_path / "deep" / "nested" / "file.py"
    dummy_file.parent.mkdir(parents=True)
    dummy_file.touch()
    with pytest.raises(
        RuntimeError, match=r"package root containing \.claude-plugin/plugin\.json not found"
    ):
        _find_package_root(dummy_file)


def test_find_repo_root_resolves_repo_root() -> None:
    repo_root = _find_repo_root(PACKAGE_ROOT)
    assert (repo_root / ".claude-plugin" / "marketplace.json").is_file()
    assert repo_root == ROOT


def test_find_repo_root_fails_loudly_when_missing(tmp_path: Path) -> None:
    fake_pkg_root = tmp_path / "somewhere" / "mission-control"
    fake_pkg_root.mkdir(parents=True)
    with pytest.raises(
        RuntimeError,
        match=r"repository root containing \.claude-plugin/marketplace\.json not found",
    ):
        _find_repo_root(fake_pkg_root)


# --- W6 cross-repo Code Review cycle-1 doc-parity regressions (F-4/F-5/F-6) ---


def test_changelog_has_single_h1() -> None:
    """F-4 regression: exactly ONE `# Changelog` H1 — the 2.13.0 entry must
    not sit between two document titles, or outline views split the release."""
    changelog = _read(PLUGIN_ROOT / "CHANGELOG.md")
    h1s = [line for line in changelog.splitlines() if line.startswith("# ")]
    assert h1s == ["# Changelog"], f"expected one H1, found {h1s}"


def test_board_move_project_help_describes_validation_not_targeting() -> None:
    """F-5 regression: `board move --project` help states the validation-not-
    restriction contract — trusting --help must not imply a single-board
    Status write."""
    source = _read(PLUGIN_ROOT / "scripts" / "sdlc_manager.py")
    # Scope to the `board move` parser; `board add`'s membership targeting is
    # a different command and keeps its own wording.
    move_parser_start = source.index('add_parser("move"')
    move_help_region = source[move_parser_start : source.index('add_parser("archive"')]
    assert "VALIDATE against" in move_help_region
    assert "EVERY board carrying the" in move_help_region
    # The old single-board phrasing must be gone from the move help.
    assert "Target a specific project instead of repo-based default routing" not in (
        move_help_region
    )


def test_board_skill_states_compensation_halt_accuracy() -> None:
    """F-6 regression: the board skill's W6 note must NOT claim a failed move
    always leaves zero boards written — a compensation failure leaves boards
    disagreeing, and the skill must tell the agent to read back before
    retrying."""
    board_skill = _read(PLUGIN_ROOT / "skills" / "board" / "SKILL.md")
    assert "no longer leaves other boards written" not in board_skill
    assert "compensation failure" in board_skill
    assert "Do not retry blindly" in board_skill
