"""Release-surface checks for the authored codex package."""

from __future__ import annotations

import json
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.5"
REPOSITORY = "https://github.com/infiquetra/infiquetra-agent-plugins"


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


def test_codex_manifests_agree_on_version_and_repository() -> None:
    claude = json.loads(_read(PLUGIN_ROOT / ".claude-plugin" / "plugin.json"))
    portable = json.loads(_read(PLUGIN_ROOT / "plugin.json"))
    adapter = json.loads(_read(PLUGIN_ROOT / "com.infiquetra.claude" / "plugin.json"))
    assert claude["name"] == portable["name"] == adapter["name"] == "codex"
    assert claude["version"] == portable["version"] == adapter["version"] == VERSION
    assert claude["description"]
    assert portable["description"]
    assert adapter["description"]
    assert claude["author"] == {"name": "Infiquetra", "email": "hello@infiquetra.com"}
    assert claude["repository"] == adapter["repository"] == REPOSITORY
    assert {"codex", "delegation"} <= set(claude["keywords"])
    assert claude["commands"] == "./com.infiquetra.claude/commands/"
    assert claude["agents"] == "./com.infiquetra.claude/agents/"
    assert claude["skills"] == "./skills/"


def test_codex_plugin_surfaces_exist() -> None:
    for relative in (
        ".claude-plugin/plugin.json",
        "plugin.json",
        "README.md",
        "CHANGELOG.md",
        "fleet-bundle.json",
        "com.infiquetra.claude/plugin.json",
        "com.infiquetra.claude/commands/delegate.md",
        "com.infiquetra.claude/agents/codex-coder.md",
        "com.infiquetra.claude/agents/codex-reviewer.md",
        "scripts/codex_delegate.py",
        "scripts/_bundled/bridge_receipt.py",
        "scripts/_bundled/output_attestation.py",
        "skills/codex-delegate/SKILL.md",
    ):
        path = PLUGIN_ROOT / relative
        assert path.is_file(), f"missing packaged surface: {path}"
    assert not (PLUGIN_ROOT / "scripts" / "fleet_commons_shim.py").exists()


def test_codex_command_frontmatter_name() -> None:
    path = PLUGIN_ROOT / "com.infiquetra.claude" / "commands" / "delegate.md"
    assert _frontmatter(path)["name"] == "delegate"


def test_codex_skill_frontmatter_name() -> None:
    skill_path = PLUGIN_ROOT / "skills" / "codex-delegate" / "SKILL.md"
    assert _frontmatter(skill_path)["name"] == "codex-delegate"


def test_codex_agent_frontmatter_names() -> None:
    for agent_name in ("codex-coder", "codex-reviewer"):
        agent_path = PLUGIN_ROOT / "com.infiquetra.claude" / "agents" / f"{agent_name}.md"
        frontmatter = _frontmatter(agent_path)
        assert frontmatter["name"] == agent_name
        assert frontmatter["tools"] == "Bash"
