"""Documentation guards for the target-owned portable skill and README.

The portable skill and README supersede the upstream documents
(``ports/agent-launcher.json``, ``superseded_by_target_owned``). These guards
hold the class properties the supersession exists for: package-relative script
discovery, the contract's stop conditions carried verbatim, the herdr
dependency declared without a duplicated herdr skill, and the adapter
limitations stated. The mutation proofs for these guards land with
``tests/test_agent_launcher_rule_audit.py`` at the repository root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
SKILL = PACKAGE / "skills" / "agent-launcher" / "SKILL.md"
README = PACKAGE / "README.md"

# Every Claude-runtime discovery path that must never appear in the portable
# skill: the portable contract resolves its script from this package only.
FORBIDDEN_CLAUDE_RUNTIME_PATHS = (
    "$CLAUDE_PLUGIN_ROOT",
    "CLAUDE_PLUGIN_ROOT",
    "~/.claude/plugins/cache",
    ".claude/plugins/cache",
)

STOP_CONDITION_MARKERS = (
    "Stop before launch if the wrapper dry run does not resolve the requested working",
    "Stop before prompting if Herdr cannot verify the requested agent kind",
    "Stop rather than silently substituting an unavailable agent or launch setting.",
    "Stop cleanup if ownership of the target session cannot be proven",
)


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_skill_resolves_the_script_package_relative(skill_text: str) -> None:
    assert "skills/agent-launcher/scripts/launcher.py" in skill_text
    assert "scripts/launcher.py" in skill_text


@pytest.mark.parametrize("forbidden", FORBIDDEN_CLAUDE_RUNTIME_PATHS)
def test_skill_never_names_claude_runtime_discovery(skill_text: str, forbidden: str) -> None:
    assert forbidden not in skill_text


@pytest.mark.parametrize("marker", STOP_CONDITION_MARKERS)
def test_skill_carries_every_stop_condition(skill_text: str, marker: str) -> None:
    assert marker in skill_text


def test_skill_declares_the_herdr_dependency_without_a_duplicate(skill_text: str) -> None:
    assert "canonical `herdr` skill" in skill_text
    assert "does not ship a copy" in skill_text
    assert not (PACKAGE / "skills" / "herdr").exists()


def test_skill_cleanup_example_redirects_the_receipt(skill_text: str) -> None:
    assert "> receipt.json" in skill_text
    assert "close --receipt-json receipt.json" in skill_text
    assert "close --tab-id <tab_id> --receipt-json <receipt.json>" not in skill_text


def test_skill_frontmatter_name_matches_the_directory(skill_text: str) -> None:
    assert skill_text.startswith("---\n")
    frontmatter = skill_text.split("---\n", 2)[1]
    names = [
        line.split(":", 1)[1].strip()
        for line in frontmatter.splitlines()
        if line.startswith("name:")
    ]
    assert names == ["agent-launcher"]


def test_readme_opens_as_a_portable_package_document(readme_text: str) -> None:
    assert "Portable Agent Plugins 1.0 package" in readme_text
    assert "# agent-launcher portable package" in readme_text


def test_readme_states_the_adapter_limitations(readme_text: str) -> None:
    assert "Account verification applies only to `vendor claude`" in readme_text
    assert "installed `agents` wrapper and Herdr" in readme_text
    assert "no vendor or model registry" in readme_text


def test_readme_declares_the_floor(readme_text: str) -> None:
    assert "python>=3.12" in readme_text
