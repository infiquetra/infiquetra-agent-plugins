#!/usr/bin/env python3
"""Render mission-control issue template docs from canonical YAML templates."""

from __future__ import annotations

import argparse
import difflib
import importlib.util
import os
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
REFERENCE_PATH = (
    REPO_ROOT / "plugins/mission-control/skills/issues/references/templates-reference.md"
)
DEFAULT_SDLC_PATH = Path.home() / "workspace" / "infiquetra" / "infiquetra-sdlc"

ACTIONABLE_TEMPLATES = ("capability", "enhancement", "defect")
NON_ACTIONABLE_TEMPLATES = ("exploration", "context-update")
TEMPLATE_ORDER = ACTIONABLE_TEMPLATES + NON_ACTIONABLE_TEMPLATES
CONTRACT_DATA_PATH = REPO_ROOT / "plugins/mission-control/config/generated/issue_contract_data.py"

_contract_spec = importlib.util.spec_from_file_location("issue_contract_data", CONTRACT_DATA_PATH)
if _contract_spec is None or _contract_spec.loader is None:  # pragma: no cover - defensive
    raise ImportError(f"vendored issue-contract data not loadable at {CONTRACT_DATA_PATH}")
_contract = importlib.util.module_from_spec(_contract_spec)
_contract_spec.loader.exec_module(_contract)

CONTRACT_REQUIRED_FIELDS = [
    _contract.FIELD_HEADERS[field_key] for field_key in _contract.REQUIRED_FIELDS
]
RISK_CONDITIONAL_FIELDS = [
    _contract.FIELD_HEADERS[field_key]
    for field_key in ("inputs", "failure_modes", "stop_conditions")
]
AUTO_POPULATED_FIELDS = [
    _contract.FIELD_HEADERS[field_key]
    for field_key in _contract.REQUIRED_MATRIX["auto_populated_fields"]
]

ACTIONABLE_TEMPLATE_NOTES = {
    "capability": (
        "Capability represents complete end-to-end deployable functionality. "
        "Its optional Capability size field is a human planning hint only."
    ),
    "enhancement": "Enhancement improves existing functionality without creating a new capability.",
    "defect": "Defect captures broken behavior that a Hermes agent can plan and fix.",
}

NON_ACTIONABLE_TEMPLATE_NOTES = {
    "objective": (
        "Objective coordinates multiple capabilities and should not be treated as a Hermes task card."
    ),
    "exploration": (
        "Exploration produces research, recommendations, or POC findings rather than production code."
    ),
    "context-update": (
        "Context Update maintains Blueprint documentation and is not dispatched as a Hermes task."
    ),
}


def sdlc_path() -> Path:
    """Return the configured infiquetra-sdlc checkout path."""
    configured_path = os.environ.get("INFIQUETRA_SDLC_PATH")
    if configured_path:
        return Path(configured_path).expanduser()
    return DEFAULT_SDLC_PATH


def template_directory() -> Path:
    """Return the canonical issue template directory."""
    return sdlc_path() / ".github" / "ISSUE_TEMPLATE"


def display_name(template_name: str) -> str:
    """Convert a template slug to its YAML display name."""
    template = load_template(template_name)
    return str(template["name"])


def format_inline_code(values: list[str]) -> str:
    """Render values as a comma-separated inline-code list."""
    return ", ".join(f"`{value}`" for value in values)


def format_template_files(template_names: tuple[str, ...]) -> str:
    return format_inline_code([f"{template}.yml" for template in template_names])


def load_template(template_name: str) -> dict[str, Any]:
    """Load one canonical issue template by slug."""
    template_path = template_directory() / f"{template_name}.yml"
    if not template_path.exists():
        raise FileNotFoundError(
            f"Missing canonical issue template: {template_path}. "
            "Set INFIQUETRA_SDLC_PATH or use the default checkout at "
            "~/workspace/infiquetra/infiquetra-sdlc."
        )

    with template_path.open(encoding="utf-8") as template_file:
        data = yaml.safe_load(template_file)

    if not isinstance(data, dict):
        raise ValueError(f"Template did not parse to a mapping: {template_path}")
    return data


def extract_fields(template: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Extract required and optional field labels from a GitHub issue form."""
    required_fields: list[str] = []
    optional_fields: list[str] = []

    for item in template.get("body", []):
        if item.get("type") not in {"input", "textarea", "dropdown", "checkboxes"}:
            continue

        attributes = item.get("attributes", {})
        label = attributes.get("label")
        if not label:
            continue

        validations = item.get("validations", {})
        if validations.get("required") is True:
            required_fields.append(label)
        else:
            optional_fields.append(label)

    return required_fields, optional_fields


def _render_field_list(fields: list[str]) -> list[str]:
    if not fields:
        return ["- None"]
    return [f"- {field}" for field in fields]


def _render_actionable(template_name: str, template: dict[str, Any]) -> list[str]:
    required_fields, optional_fields = extract_fields(template)
    labels = template["labels"]

    lines = [
        f"## {template['name']}",
        "",
        f"- File: `{template_name}.yml`",
        f"- Title prefix: `{template['title']}`",
        "- Card contract: required",
        f"- Labels: {format_inline_code(labels)}",
        f"- Summary: {ACTIONABLE_TEMPLATE_NOTES[template_name]}",
        "",
        "### Required fields",
        "",
        *_render_field_list(required_fields),
        "",
        "### Optional fields",
        "",
        *_render_field_list(optional_fields),
        "",
        "### Card validator contract",
        "",
        "- Actionable cards must carry `needs-plan` and the type label.",
        "- GitHub issue forms must render required fields as exact `### <Field label>` headers.",
        "- `Context library links` is required for readiness; use `_none_` when no context applies.",
        "- `Acceptance criteria` must include at least one `- [ ]` checklist item and name a runnable check.",
        "- Verification must include exact commands in a fenced shell code block.",
        "- High and very-high risk cards also require `Inputs inventory`, "
        "`Failure modes / pre-mortem`, and `Stop conditions`.",
        "- `Lifecycle Origin` is auto-populated by prepared handoff flows, not author supplied.",
        "",
    ]
    return lines


def _render_non_actionable(template_name: str, template: dict[str, Any]) -> list[str]:
    required_fields, optional_fields = extract_fields(template)
    labels = template["labels"]

    lines = [
        f"## {template['name']}",
        "",
        f"- File: `{template_name}.yml`",
        f"- Title prefix: `{template['title']}`",
        "- Card contract: not required",
        f"- Labels: {format_inline_code(labels)}",
        f"- Summary: {NON_ACTIONABLE_TEMPLATE_NOTES[template_name]}",
        "",
        "### Required fields",
        "",
        *_render_field_list(required_fields),
        "",
        "### Optional fields",
        "",
        *_render_field_list(optional_fields),
        "",
        "### Dispatch behavior",
        "",
        "- Non-actionable cards carry only their type and context labels.",
        "- Do not document or treat this template as an actionable task card.",
        "- Use these cards for coordination, research, or documentation context rather than agent dispatch.",
        "",
    ]
    return lines


def validate_templates_present() -> None:
    """Fail clearly when the canonical templates are unavailable."""
    if not template_directory().exists():
        raise FileNotFoundError(
            f"Canonical template directory not found: {template_directory()}. "
            "Set INFIQUETRA_SDLC_PATH or use the default checkout at "
            "~/workspace/infiquetra/infiquetra-sdlc."
        )

    for template_name in TEMPLATE_ORDER:
        load_template(template_name)


def render_reference() -> str:
    """Render the templates reference document from canonical YAML templates."""
    validate_templates_present()

    lines = [
        "# SDLC Issue Templates Reference",
        "",
        "This file is generated by `plugins/mission-control/scripts/sync_template_docs.py` from",
        "the canonical templates in `$INFIQUETRA_SDLC_PATH/.github/ISSUE_TEMPLATE/`.",
        "Do not edit this file by hand; update the canonical templates or the renderer instead.",
        "",
        "## Card taxonomy",
        "",
        f"- Actionable templates: {format_template_files(ACTIONABLE_TEMPLATES)}.",
        "- Actionable labels: `needs-plan` plus the type label.",
        f"- Non-actionable templates: {format_template_files(NON_ACTIONABLE_TEMPLATES)}.",
        "- Non-actionable labels: template-specific context labels only.",
        "",
        "## Shared actionable required fields",
        "",
        *_render_field_list(CONTRACT_REQUIRED_FIELDS),
        "",
        "## Shared actionable risk-conditional fields",
        "",
        *_render_field_list(RISK_CONDITIONAL_FIELDS),
        "",
        "## Shared actionable generated fields",
        "",
        *_render_field_list(AUTO_POPULATED_FIELDS),
        "",
        "## Shared actionable optional fields",
        "",
        "- Notes / conventions",
        "- Capability size (human planning hint) on capability cards only",
        "",
    ]

    for template_name in ACTIONABLE_TEMPLATES:
        lines.extend(_render_actionable(template_name, load_template(template_name)))

    for template_name in NON_ACTIONABLE_TEMPLATES:
        lines.extend(_render_non_actionable(template_name, load_template(template_name)))

    return "\n".join(lines).rstrip() + "\n"


def write_reference() -> None:
    """Write the generated reference document."""
    REFERENCE_PATH.write_text(render_reference(), encoding="utf-8")


def check_reference() -> bool:
    """Return True when the checked-in reference matches generated output."""
    expected = render_reference()
    actual = REFERENCE_PATH.read_text(encoding="utf-8") if REFERENCE_PATH.exists() else ""
    if actual == expected:
        return True

    diff = difflib.unified_diff(
        actual.splitlines(keepends=True),
        expected.splitlines(keepends=True),
        fromfile=str(REFERENCE_PATH),
        tofile="generated templates-reference.md",
    )
    sys.stderr.writelines(diff)
    return False


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Sync mission-control template reference docs from canonical issue templates."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if templates-reference.md is not already in sync.",
    )
    return parser.parse_args()


def main() -> int:
    """CLI entry point."""
    args = parse_args()
    try:
        if args.check:
            if check_reference():
                print(f"Template docs are in sync: {REFERENCE_PATH}")
                return 0
            return 1

        write_reference()
        print(f"Wrote {REFERENCE_PATH}")
        return 0
    except (FileNotFoundError, ValueError, yaml.YAMLError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
