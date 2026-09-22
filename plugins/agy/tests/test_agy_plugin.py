"""Contract tests for the agy plugin release surface."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = ROOT
WRAPPER_PATH = "plugins/agy/scripts/agy_delegate.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter(path: Path) -> dict[str, str]:
    lines = _read(path).splitlines()
    assert lines[0] == "---"

    data: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return data
        if ": " in line:
            key, value = line.split(": ", 1)
            data[key] = value.strip()

    raise AssertionError(f"{path} has no closing frontmatter marker")


def test_agy_metadata_is_marketplace_registered() -> None:
    plugin_json = json.loads(_read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json"))
    marketplace = json.loads(_read(REPO / ".claude-plugin" / "marketplace.json"))
    marketplace_entry = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "agy")

    assert plugin_json["name"] == "agy"
    assert plugin_json["version"] == "0.6.2"
    assert "Antigravity" in plugin_json["description"]
    assert {"agy", "antigravity", "delegation", "teammate", "evidence"} <= set(
        plugin_json["keywords"]
    )
    assert marketplace_entry["source"] == "./plugins/agy"
    assert marketplace_entry["version"] == plugin_json["version"]
    # marketplace.json is generated from plugin.json (#429) — keyword order must match exactly.
    assert marketplace_entry["keywords"] == plugin_json["keywords"]


def test_agy_commands_skills_references_and_agents_are_packaged() -> None:
    expected_paths = (
        ".claude-plugin/plugin.json",
        "README.md",
        "CHANGELOG.md",
        "com.infiquetra.claude/commands/delegate.md",
        "docs/harness-proof.md",
        "scripts/agy_delegate.py",
        "scripts/audit_harness_transcript.py",
        "skills/agy-delegate/SKILL.md",
        "skills/agy-delegate/scripts/agy_delegate.py",
        "skills/agy-delegate/references/delegation-contract.md",
        "com.infiquetra.claude/agents/agy-coder.md",
        "com.infiquetra.claude/agents/agy-reviewer.md",
        "plugin.json",
        "fleet-bundle.json",
    )

    for relative_path in expected_paths:
        assert (PLUGIN_ROOT / relative_path).exists(), f"missing agy file: {relative_path}"

    assert _frontmatter(PLUGIN_ROOT / "com.infiquetra.claude" / "commands" / "delegate.md")["name"] == "delegate"
    assert (
        _frontmatter(PLUGIN_ROOT / "skills" / "agy-delegate" / "SKILL.md")["name"] == "agy-delegate"
    )
    assert _frontmatter(PLUGIN_ROOT / "com.infiquetra.claude" / "agents" / "agy-coder.md")["name"] == "agy-coder"
    assert (
        _frontmatter(PLUGIN_ROOT / "com.infiquetra.claude" / "agents" / "agy-reviewer.md")["name"]
        == "agy-reviewer"
    )


def test_agy_agents_are_bash_only_bridge_agents() -> None:
    for agent_name in ("agy-coder", "agy-reviewer"):
        path = PLUGIN_ROOT / "com.infiquetra.claude" / "agents" / f"{agent_name}.md"
        frontmatter = _frontmatter(path)
        text = _read(path)

        assert frontmatter["tools"] == "Bash"
        assert WRAPPER_PATH in text
        assert "exactly one wrapper run" in text
        assert "Do not invoke raw `agy`" in text
        assert "Do not read, edit, or write repository files directly" in text


def test_agy_command_and_skill_route_to_shared_wrapper() -> None:
    command_doc = _read(PLUGIN_ROOT / "com.infiquetra.claude" / "commands" / "delegate.md")
    skill_doc = _read(PLUGIN_ROOT / "skills" / "agy-delegate" / "SKILL.md")
    contract_doc = _read(
        PLUGIN_ROOT / "skills" / "agy-delegate" / "references" / "delegation-contract.md"
    )
    readme = _read(PLUGIN_ROOT / "README.md")

    for text in (command_doc, skill_doc, contract_doc, readme):
        assert WRAPPER_PATH in text

    assert "agy.delegation.v1" in command_doc
    assert "agy.delegation.v1" in skill_doc
    assert "agy.delegation.v1" in contract_doc
    assert "Do not invoke raw `agy` directly" in command_doc
    assert "The wrapper is the only supported execution path" in skill_doc


def test_agy_readme_changelog_and_harness_proof_are_release_ready() -> None:
    changelog = _read(PLUGIN_ROOT / "CHANGELOG.md")
    readme = _read(PLUGIN_ROOT / "README.md")
    harness = _read(PLUGIN_ROOT / "docs" / "harness-proof.md")

    assert "## [Unreleased]" in changelog
    assert "## [0.1.0] - 2026-06-30" in changelog
    assert "Claude Code harness proof" in changelog
    assert "registered in `.claude-plugin/marketplace.json`" in readme
    assert "auto-if-clean" in readme
    assert "Status: passed live run on 2026-06-30" in harness
    assert "Wrapper status: `applied`" in harness
    assert WRAPPER_PATH in changelog
