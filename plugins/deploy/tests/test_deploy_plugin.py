"""Contract tests for the deploy package.

Carried from infiquetra-claude-plugins ``tests/test_deploy_plugin.py`` at
acc99fe7. The upstream file lived in the repository-wide ``tests/`` directory
and resolved the package as ``<repo>/plugins/deploy``. Here the test lives in
the package, so the package root is the parent of this file.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PACKAGE_ROOT.parent.parent
ADAPTER = PACKAGE_ROOT / "com.infiquetra.claude"
SKILL_ROOT = PACKAGE_ROOT / "skills" / "deploy-state"
SCRIPTS = SKILL_ROOT / "scripts"
AUTHORED_VERSION = "0.2.3"
ENTRYPOINTS = ("mint_tag.py", "query_deployments.py", "preview_release_notes.py")
CREDENTIAL_PREFIXES = ("GH_", "GITHUB_")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_module(script_name: str):
    path = SCRIPTS / script_name
    spec = importlib.util.spec_from_file_location(script_name.removesuffix(".py"), path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _frontmatter_name(path: Path) -> str:
    lines = _read(path).splitlines()
    assert lines[0] == "---"
    for line in lines[1:]:
        if line.startswith("name: "):
            return line.removeprefix("name: ").strip()
    raise AssertionError(f"{path} has no frontmatter name")


def test_version_sites_agree_on_the_authored_cut() -> None:
    portable = json.loads(_read(PACKAGE_ROOT / "plugin.json"))
    claude = json.loads(_read(PACKAGE_ROOT / ".claude-plugin" / "plugin.json"))
    adapter = json.loads(_read(ADAPTER / "plugin.json"))
    marketplace = json.loads(_read(REPO_ROOT / ".claude-plugin" / "marketplace.json"))
    entry = next(plugin for plugin in marketplace["plugins"] if plugin["name"] == "deploy")

    assert portable["name"] == "deploy"
    assert portable["$schema"].endswith("/plugin.schema.json")
    assert "$schema" not in claude
    assert (
        portable["version"]
        == claude["version"]
        == adapter["version"]
        == entry["version"]
        == AUTHORED_VERSION
    )
    assert entry["source"] == "./plugins/deploy"
    assert "tag-promotion" in claude["description"]
    assert {"deploy", "tag-promotion", "rollback", "hotfix"} <= set(claude["keywords"])
    assert claude["commands"] == "./com.infiquetra.claude/commands/"
    assert claude["agents"] == ["./com.infiquetra.claude/agents/release-orchestrator.md"]
    assert claude["skills"] == "./skills/"


def test_commands_agent_skill_and_scripts_are_packaged() -> None:
    for command in ("deploy", "deploy-status", "deploy-notes", "deploy-hotfix"):
        path = ADAPTER / "commands" / f"{command}.md"
        assert path.is_file()
        text = _read(path)
        assert "plugins/deploy/scripts/" not in text
        assert "${CLAUDE_PLUGIN_ROOT}/skills/deploy-state/" in text
        assert not (PACKAGE_ROOT / "commands" / f"{command}.md").exists()

    skill_path = SKILL_ROOT / "SKILL.md"
    assert _frontmatter_name(skill_path) == "deploy-state"
    skill = _read(skill_path)
    assert "ADR-0004" in skill
    assert "plugins/deploy/scripts/" not in skill
    assert "scripts/mint_tag.py" in skill
    assert "GH_TOKEN" in skill
    assert "GITHUB_TOKEN" in skill

    agent_path = ADAPTER / "agents" / "release-orchestrator.md"
    assert _frontmatter_name(agent_path) == "release-orchestrator"
    assert not (PACKAGE_ROOT / "agents").exists()

    for script in ENTRYPOINTS:
        assert (SCRIPTS / script).is_file()
    assert not (PACKAGE_ROOT / "scripts").exists()


def test_entrypoints_answer_help_without_credentials() -> None:
    """Run each script the way a user runs it: ``python3 <script> --help``."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(CREDENTIAL_PREFIXES)
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    for script in ENTRYPOINTS:
        completed = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--help"],
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert "usage:" in completed.stdout.lower()
        assert "Traceback" not in completed.stderr
        assert "ModuleNotFoundError" not in completed.stderr


def test_mint_tag_uses_infiquetra_environments_and_tag_prefixes() -> None:
    mint_tag = _load_module("mint_tag.py")

    assert mint_tag.ENV_TO_PREFIX == {
        "nonprod": "nonprod",
        "staging": "staging",
        "production": "production",
    }
    assert mint_tag.build_tag_name("staging", "1.2.3", rollback=False) == "staging-v1.2.3"
    assert (
        mint_tag.build_tag_name("production", "1.2.3", rollback=True)
        == "rollback-production-v1.2.3"
    )
    assert mint_tag.build_tag_name("production", "1.2.3.1", rollback=False) == "production-v1.2.3.1"


def test_mint_tag_resolves_and_rejects_repository_owners(monkeypatch) -> None:
    mint_tag = _load_module("mint_tag.py")

    assert mint_tag.resolve_repo("campps-service") == "infiquetra/campps-service"
    assert mint_tag.resolve_repo("infiquetra/campps-service") == "infiquetra/campps-service"

    def fake_run(cmd: list[str], *, check: bool = True, capture: bool = True) -> str:
        assert cmd == ["git", "remote", "get-url", "origin"]
        return "git@github.com:other-org/service.git"

    monkeypatch.setattr(mint_tag, "run", fake_run)

    try:
        mint_tag.resolve_repo(None)
    except SystemExit as exc:
        assert "expected github.com/infiquetra/*" in str(exc)
    else:
        raise AssertionError("non-Infiquetra remote should be rejected")


def test_query_deployments_strips_infiquetra_tag_prefixes() -> None:
    query_deployments = _load_module("query_deployments.py")

    assert query_deployments.strip_prefix("v1.2.3") == "1.2.3"
    assert query_deployments.strip_prefix("nonprod-v1.2.3") == "1.2.3"
    assert query_deployments.strip_prefix("staging-v1.2.3") == "1.2.3"
    assert query_deployments.strip_prefix("production-v1.2.3") == "1.2.3"
    assert query_deployments.strip_prefix("rollback-production-v1.2.3") == "1.2.3"


def test_is_tag_ref_accepts_tags_and_rejects_branches() -> None:
    query_deployments = _load_module("query_deployments.py")

    assert query_deployments.is_tag_ref("v0.1.0")
    assert query_deployments.is_tag_ref("nonprod-v1.2.3")
    assert query_deployments.is_tag_ref("staging-v1.2.3")
    assert query_deployments.is_tag_ref("production-v1.2.3")
    assert query_deployments.is_tag_ref("rollback-production-v1.2.3")

    # Branch and SHA refs, and a loose v-prefixed branch name, are rejected.
    assert not query_deployments.is_tag_ref("main")
    assert not query_deployments.is_tag_ref("feature/deploy")
    assert not query_deployments.is_tag_ref("version-bump")
    assert not query_deployments.is_tag_ref("9f8c1de")
    assert not query_deployments.is_tag_ref("")
    assert not query_deployments.is_tag_ref(None)


def test_latest_deployment_issues_get_and_selects_newest_tag_ref(monkeypatch) -> None:
    query_deployments = _load_module("query_deployments.py")

    captured: dict[str, list[str]] = {}

    def fake_run(cmd: list[str], *, check: bool = True) -> str:
        captured["cmd"] = cmd
        # GitHub returns newest-first: a branch-ref CI deployment newer than the real tag.
        return json.dumps(
            [
                {"ref": "main", "sha": "9f8c1de"},
                {"ref": "v0.1.0", "sha": "abc1234"},
            ]
        )

    monkeypatch.setattr(query_deployments, "run", fake_run)

    deployment = query_deployments.latest_deployment("infiquetra/campps-identity-access", "nonprod")

    assert deployment is not None
    assert deployment["ref"] == "v0.1.0"

    # The gh call must be a GET so the HTTP 422 from a POST create cannot regress.
    cmd = captured["cmd"]
    assert cmd[:2] == ["gh", "api"]
    method_index = cmd.index("--method")
    assert cmd[method_index + 1] == "GET"
    assert "environment=nonprod" in cmd
    assert "per_page=20" in cmd


def test_latest_deployment_returns_none_without_tag_refs(monkeypatch) -> None:
    query_deployments = _load_module("query_deployments.py")

    def fake_run(cmd: list[str], *, check: bool = True) -> str:
        return json.dumps([{"ref": "main"}, {"ref": "dependabot/pip/foo"}])

    monkeypatch.setattr(query_deployments, "run", fake_run)

    assert query_deployments.latest_deployment("infiquetra/x", "nonprod") is None


def test_render_status_reports_and_omits_drift() -> None:
    query_deployments = _load_module("query_deployments.py")

    drifted = query_deployments.render_status(
        "infiquetra/x",
        {
            "nonprod": {"ref": "nonprod-v0.1.1"},
            "staging": {"ref": "staging-v0.1.0"},
            "production": {"ref": "production-v0.1.0"},
        },
    )
    assert "drift:" in drifted
    assert "drift: none detected" not in drifted
    assert "0.1.1" in drifted

    aligned = query_deployments.render_status(
        "infiquetra/x",
        {
            "nonprod": {"ref": "nonprod-v0.1.0"},
            "staging": {"ref": "staging-v0.1.0"},
            "production": {"ref": "production-v0.1.0"},
        },
    )
    assert "drift: none detected" in aligned
