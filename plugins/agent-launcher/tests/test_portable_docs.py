"""Documentation guards for the authored skill and README.

The skill may name ``$CLAUDE_PLUGIN_ROOT`` because that variable is the
installed package root and the scripts stay at ``skills/``. It must not fall
back into a Claude plugin cache. The stop conditions and the receipt contract
are the 1.7.0 wording.
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
    assert "Resolve the script from this package" in skill_text


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


def test_skill_launch_example_delivers_a_prompt(skill_text: str) -> None:
    assert "--prompt <text> > receipt.json" in skill_text


def test_skill_states_the_launcher_receipt_has_no_pane_id(skill_text: str) -> None:
    assert "There is no `pane_id` key" in skill_text


def test_skill_frontmatter_name_matches_the_directory(skill_text: str) -> None:
    assert skill_text.startswith("---\n")
    assert "name: agent-launcher\n" in skill_text.split("---", 2)[1]


def test_readme_opens_as_a_portable_package_document(readme_text: str) -> None:
    assert "Portable Agent Plugins 1.0 package" in readme_text
    assert "python>=3.12" in readme_text


def test_readme_states_the_adapter_limitations(readme_text: str) -> None:
    assert "Account verification applies only to `vendor claude`" in readme_text
    assert "installed `agents` wrapper and Herdr" in readme_text
    assert "no vendor or model registry" in readme_text
