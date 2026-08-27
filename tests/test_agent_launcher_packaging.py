"""Packaging smoke for the generated agent-launcher package.

The package is assembled by the portability workflow (descriptor + sync), so
the smoke binds the assembly: the relocated Claude manifest preserves the
upstream identity and version, the portable manifest is the Agent Plugins
shape at the same version, the package root carries no Claude convention
directories, and the repository marketplace does not list the package —
catalog distribution is withheld pending an operator decision (QUEUED.md P1,
plan KTD7).

Standard library only, matching the repository baseline.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "plugins" / "agent-launcher"
AGENT_PLUGINS_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
CLAUDE_CONVENTION_DIRS = ("hooks", "agents", "commands")


class RelocatedManifestTests(unittest.TestCase):
    """The Claude manifest arrives under the client extension, bytes preserved."""

    def setUp(self) -> None:
        self.manifest_path = PACKAGE / "com.infiquetra.claude" / "plugin.json"
        self.provenance = json.loads((PACKAGE / "PROVENANCE.json").read_text(encoding="utf-8"))

    def test_the_relocated_manifest_preserves_upstream_identity(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "agent-launcher")
        self.assertEqual(manifest["version"], self.provenance["source_version"])

    def test_the_relocated_manifest_is_the_transform_output(self) -> None:
        entries = {
            entry["path"]: entry
            for entry in self.provenance["files"]
            if entry["path"] == "com.infiquetra.claude/plugin.json"
        }
        self.assertEqual(len(entries), 1)
        entry = entries["com.infiquetra.claude/plugin.json"]
        self.assertEqual(entry["classification"], "deterministic-transform")
        self.assertEqual(entry["source_path"], "plugins/agent-launcher/.claude-plugin/plugin.json")


class PortableManifestTests(unittest.TestCase):
    """The portable manifest is the Agent Plugins shape at the derived version."""

    def setUp(self) -> None:
        self.manifest = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
        self.provenance = json.loads((PACKAGE / "PROVENANCE.json").read_text(encoding="utf-8"))

    def test_the_portable_manifest_is_agent_plugins_shape(self) -> None:
        self.assertEqual(self.manifest["$schema"], AGENT_PLUGINS_SCHEMA)
        for field in ("name", "version", "description"):
            with self.subTest(field=field):
                self.assertTrue(
                    isinstance(self.manifest[field], str) and self.manifest[field]
                )

    def test_the_portable_version_is_the_derivation_claim(self) -> None:
        self.assertEqual(self.manifest["name"], "agent-launcher")
        self.assertEqual(self.manifest["version"], self.provenance["source_version"])


class PackageRootShapeTests(unittest.TestCase):
    """The portable root carries no Claude convention directories."""

    def test_no_convention_directory_sits_at_the_portable_root(self) -> None:
        for name in CLAUDE_CONVENTION_DIRS:
            with self.subTest(directory=name):
                self.assertFalse((PACKAGE / name).exists())


class MarketplaceScopeTests(unittest.TestCase):
    """The repository marketplace exists and does not list this package (KTD7)."""

    def test_the_marketplace_lists_voice_only_not_agent_launcher(self) -> None:
        marketplace_path = ROOT / ".claude-plugin" / "marketplace.json"
        self.assertTrue(marketplace_path.exists())
        listed = {
            entry.get("name")
            for entry in json.loads(marketplace_path.read_text(encoding="utf-8")).get(
                "plugins", []
            )
        }
        self.assertNotIn("agent-launcher", listed)


if __name__ == "__main__":
    unittest.main()
