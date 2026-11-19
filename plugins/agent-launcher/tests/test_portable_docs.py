"""Documentation guards for the slim agent-launcher skill and README.

The skill and README document the Herdr app ``agents`` wrapper, herdr core
``hc``, the roles library, and the headless reviewer. They must not document
the removed old-Herdr launch surface or an Orchestrate ingest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
SKILL = PACKAGE / "skills" / "agent-launcher" / "SKILL.md"
README = PACKAGE / "README.md"

# Claude-cache discovery must never appear. ``$CLAUDE_PLUGIN_ROOT`` is the
# installed package root, so it is not on this list.
FORBIDDEN_CLAUDE_RUNTIME_PATHS = (
    "~/.claude/plugins/cache",
    ".claude/plugins/cache",
)

STOP_CONDITION_MARKERS = (
    "agents --workspace",
    "--app-machine",
    "agents --crew",
    "hc ls",
    "hc read",
    "hc send",
    "hc wait",
    "roles/",
    "launcher.py review",
    "reviewer-probe",
    "/private/var/folders",
)

FORBIDDEN_LEGACY_CLAIMS = (
    "herdr workspace",
    "herdr tab",
    "herdr pane",
    "herdr agent",
    "Orchestrate",
    "PaneWriter",
    "ORCHESTRATE_",
    "models.json",
    "roster.py",
    "composer.py",
)


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_skill_resolves_the_script_package_relative(skill_text: str) -> None:
    assert "skills/agent-launcher/scripts/launcher.py" in skill_text
    assert "Resolve the script from this package" in skill_text


@pytest.mark.parametrize("forbidden", FORBIDDEN_CLAUDE_RUNTIME_PATHS)
def test_skill_never_names_claude_runtime_discovery(skill_text: str, forbidden: str) -> None:
    assert forbidden not in skill_text


@pytest.mark.parametrize("marker", STOP_CONDITION_MARKERS)
def test_skill_documents_the_remaining_surface(skill_text: str, marker: str) -> None:
    assert marker in skill_text


@pytest.mark.parametrize("claim", FORBIDDEN_LEGACY_CLAIMS)
def test_skill_has_no_legacy_launch_or_orchestrate_claim(skill_text: str, claim: str) -> None:
    assert claim not in skill_text


def test_skill_frontmatter_name_matches_the_directory(skill_text: str) -> None:
    assert skill_text.startswith("---\n")
    assert "name: agent-launcher\n" in skill_text.split("---", 2)[1]


def test_readme_opens_as_a_portable_package_document(readme_text: str) -> None:
    assert "Portable Agent Plugins 1.0 package" in readme_text
    assert "python>=3.12" in readme_text
    assert "installed `agents` wrapper and herdr core (`hc`)" in readme_text
    assert "no vendor or model registry" in readme_text


@pytest.mark.parametrize("marker", STOP_CONDITION_MARKERS)
def test_readme_documents_the_remaining_surface(readme_text: str, marker: str) -> None:
    assert marker in readme_text


@pytest.mark.parametrize("claim", FORBIDDEN_LEGACY_CLAIMS)
def test_readme_has_no_legacy_launch_or_orchestrate_claim(readme_text: str, claim: str) -> None:
    assert claim not in readme_text
