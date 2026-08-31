"""Drift guards for SDLC issue template documentation."""

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sync_template_docs  # noqa: E402, I001


TEMPLATE_DIR = sync_template_docs.template_directory()
pytestmark = pytest.mark.skipif(
    not TEMPLATE_DIR.exists(),
    reason=f"Templates not at {TEMPLATE_DIR}; skipping drift checks",
)


STALE_ACTIONABLE_TERMS = {
    "needs-analysis",
    "needs-triage",
    "Business Value",
    "Risk Level",
    "Technical Risk",
    "Current State",
    "Proposed Improvement",
    "Priority",
    "Impact Assessment",
}


EXPECTED_ACTIONABLE_REQUIRED_FIELDS = [
    "Objective",
    "Intent",
    "Out-of-scope / non-goals",
    "Files expected to change",
    "Tests to add or update",
    "Context library links",
    "Acceptance criteria",
    "Verification",
]


EXPECTED_OPTIONAL_ACTIONABLE_FIELDS = {
    "capability": [
        "Inputs inventory",
        "Failure modes / pre-mortem",
        "Stop conditions",
        "Notes / conventions",
        "Lifecycle Origin",
        "Capability size (human planning hint)",
    ],
    "enhancement": [
        "Inputs inventory",
        "Failure modes / pre-mortem",
        "Stop conditions",
        "Notes / conventions",
        "Lifecycle Origin",
    ],
    "defect": [
        "Inputs inventory",
        "Failure modes / pre-mortem",
        "Stop conditions",
        "Notes / conventions",
        "Lifecycle Origin",
    ],
}


def _load_template(template_name: str) -> dict:
    template_path = sync_template_docs.template_directory() / f"{template_name}.yml"
    with template_path.open(encoding="utf-8") as template_file:
        template = yaml.safe_load(template_file)

    assert isinstance(template, dict)
    return template


def _section(markdown: str, heading: str) -> str:
    marker = f"## {heading}\n"
    start = markdown.index(marker)
    next_start = markdown.find("\n## ", start + len(marker))
    if next_start == -1:
        return markdown[start:]
    return markdown[start:next_start]


def test_generated_reference_matches_checked_in_file() -> None:
    """Checked-in docs must be generated from the canonical YAML templates."""
    expected = sync_template_docs.render_reference()
    actual = sync_template_docs.REFERENCE_PATH.read_text(encoding="utf-8")
    assert actual == expected


def test_actionable_template_labels_match_canonical_yaml() -> None:
    """Actionable docs must list the exact canonical labels from YAML."""
    markdown = sync_template_docs.render_reference()

    for template_name in sync_template_docs.ACTIONABLE_TEMPLATES:
        template = _load_template(template_name)
        section = _section(markdown, sync_template_docs.display_name(template_name))
        labels = template["labels"]

        assert "Card contract: required" in section
        assert f"Labels: {sync_template_docs.format_inline_code(labels)}" in section
        assert "`needs-plan`" in section
        # the retired Hermes dispatch markers must not come back
        assert "hermes-task" not in section
        assert "hermes-not-actionable" not in section


def test_non_actionable_template_labels_match_canonical_yaml() -> None:
    """Non-actionable docs must not present exploration/context-update as tasks."""
    markdown = sync_template_docs.render_reference()

    for template_name in sync_template_docs.NON_ACTIONABLE_TEMPLATES:
        template = _load_template(template_name)
        section = _section(markdown, sync_template_docs.display_name(template_name))

        assert "Card contract: not required" in section
        assert f"Labels: {sync_template_docs.format_inline_code(template['labels'])}" in section
        assert "hermes-not-actionable" not in section
        assert "hermes-task" not in section


def test_actionable_fields_match_canonical_contract() -> None:
    """Actionable docs must document required and optional fields from YAML."""
    markdown = sync_template_docs.render_reference()

    for template_name in sync_template_docs.ACTIONABLE_TEMPLATES:
        section = _section(markdown, sync_template_docs.display_name(template_name))
        required_fields, optional_fields = sync_template_docs.extract_fields(
            _load_template(template_name)
        )

        assert required_fields == EXPECTED_ACTIONABLE_REQUIRED_FIELDS
        assert optional_fields == EXPECTED_OPTIONAL_ACTIONABLE_FIELDS[template_name]

        for field_name in required_fields:
            assert f"- {field_name}" in section
        for field_name in optional_fields:
            assert f"- {field_name}" in section


def test_stale_actionable_label_and_field_terms_are_absent() -> None:
    """Actionable sections must not mention retired labels or legacy field names."""
    markdown = sync_template_docs.render_reference()

    for template_name in sync_template_docs.ACTIONABLE_TEMPLATES:
        section = _section(markdown, sync_template_docs.display_name(template_name))
        for stale_term in STALE_ACTIONABLE_TERMS:
            assert stale_term not in section


def test_shared_contract_docs_include_context_and_risk_rules() -> None:
    markdown = sync_template_docs.render_reference()

    shared_required = _section(markdown, "Shared actionable required fields")
    assert "- Intent" in shared_required
    assert "- Context library links" in shared_required

    risk_conditional = _section(markdown, "Shared actionable risk-conditional fields")
    assert "- Inputs inventory" in risk_conditional
    assert "- Failure modes / pre-mortem" in risk_conditional
    assert "- Stop conditions" in risk_conditional

    assert "optional Context library links" not in markdown
    assert "six required fields" not in markdown


def test_find_package_root_resolves_plugin_root() -> None:
    root = sync_template_docs._find_package_root()
    assert (root / "com.infiquetra.claude" / "plugin.json").is_file()
    assert (root / "config" / "generated" / "issue_contract_data.py").is_file()
    assert (root / "skills" / "issues" / "references" / "templates-reference.md").is_file()
    assert root == sync_template_docs.PACKAGE_ROOT


def test_find_package_root_fails_loudly_when_missing(tmp_path: Path) -> None:
    dummy_file = tmp_path / "deep" / "nested" / "file.py"
    dummy_file.parent.mkdir(parents=True)
    dummy_file.touch()
    with pytest.raises(
        RuntimeError, match=r"package root containing com\.infiquetra\.claude/plugin\.json not found"
    ):
        sync_template_docs._find_package_root(dummy_file)
