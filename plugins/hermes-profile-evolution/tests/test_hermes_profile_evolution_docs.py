"""Documentation contract for the Hermes profile-evolution package.

Carried from infiquetra-claude-plugins ``tests/test_hermes_profile_evolution_docs.py``
at acc99fe7. The release-surface check reads this repository's marketplace and
the three manifests that state the package version.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
DOCS = PACKAGE / "docs"
SCRIPT = PACKAGE / "scripts/profile_request.py"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_documentation_package_is_complete_and_uses_rendered_art() -> None:
    expected = {
        "usage.md",
        "architecture.md",
        "development.md",
        "troubleshooting.md",
        "assets/profile-evolution-claude-code-front-door.svg",
        "assets/profile-evolution-claude-code-front-door.png",
        "assets/renderer-receipt.md",
    }

    assert expected <= {
        path.relative_to(DOCS).as_posix() for path in DOCS.rglob("*") if path.is_file()
    }
    combined = "\n".join(path.read_text() for path in DOCS.rglob("*.md"))
    assert "```mermaid" not in combined
    for tool in ("`Write`", "`Edit`", "`MultiEdit`", "`NotebookEdit`"):
        assert tool in combined
    assert "Bash" in combined and "external editors" in combined
    assert "Team Mimir operator hub" in combined
    assert "Hermes producer" in combined


def test_renderer_receipt_binds_the_committed_source_and_render() -> None:
    assets = DOCS / "assets"
    receipt = (assets / "renderer-receipt.md").read_text()
    assert re.search(r"rsvg-convert version \d+\.\d+\.\d+", receipt)
    for suffix in ("svg", "png"):
        path = assets / f"profile-evolution-claude-code-front-door.{suffix}"
        assert _sha256(path) in receipt


def test_usage_documents_every_released_operator_action() -> None:
    usage = (DOCS / "usage.md").read_text()
    for action in ("suggest", "reply", "resume", "status"):
        assert f'python3 "$PROFILE_ADAPTER" {action}' in usage
    assert "hermes profile-request doctor --target brokkr" in usage
    assert "no public `doctor` action" in usage


def test_cli_help_matches_documented_doctor_boundary() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    for action in ("suggest", "reply", "resume", "status", "census"):
        assert action in result.stdout
    assert "doctor" not in result.stdout


def test_release_surfaces_agree_on_one_version() -> None:
    def load(path: Path) -> dict[str, object]:
        return json.loads(path.read_text())

    portable = load(PACKAGE / "plugin.json")
    claude = load(PACKAGE / ".claude-plugin/plugin.json")
    extension = load(PACKAGE / "com.infiquetra.claude/plugin.json")
    marketplace = load(REPO / ".claude-plugin/marketplace.json")
    entry = next(
        plugin
        for plugin in marketplace["plugins"]
        if plugin["name"] == "hermes-profile-evolution"
    )
    version = portable["version"]
    assert isinstance(version, str) and version
    assert claude["version"] == version
    assert extension["version"] == version
    assert entry["version"] == version
    assert f"source version documented here is `{version}`" in (DOCS / "usage.md").read_text()
    changelog = (PACKAGE / "CHANGELOG.md").read_text()
    assert f"## [{version}]" in changelog
    assert "infiquetra-claude-plugins@acc99fe7" in changelog
    assert "no provenance manifest" in changelog


def test_architecture_does_not_claim_target_mutation_or_commit_authority() -> None:
    text = (DOCS / "architecture.md").read_text()
    assert "cannot edit or commit target behavior" in text
