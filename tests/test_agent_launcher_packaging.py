"""Packaging smoke for the authored agent-launcher package.

The 2026-09-22 import drops ``PROVENANCE.json``. The three manifests agree on
name and version. The portable manifest is the Agent Plugins shape. The
package root carries no Claude convention directories. Marketplace membership
is checked by ``tests/test_claude_plugin_packaging.py``, which derives the set
from the tree.

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
    """The Claude manifest lives under the client extension and agrees on version."""

    def setUp(self) -> None:
        self.manifest_path = PACKAGE / "com.infiquetra.claude" / "plugin.json"
        self.portable = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))

    def test_the_relocated_manifest_agrees_with_the_portable_manifest(self) -> None:
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "agent-launcher")
        self.assertEqual(manifest["version"], self.portable["version"])

    def test_there_is_no_provenance_manifest(self) -> None:
        self.assertFalse((PACKAGE / "PROVENANCE.json").exists())


class PortableManifestTests(unittest.TestCase):
    """The portable manifest is the Agent Plugins shape at the authored version."""

    def setUp(self) -> None:
        self.manifest = json.loads((PACKAGE / "plugin.json").read_text(encoding="utf-8"))
        self.claude = json.loads(
            (PACKAGE / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
        )

    def test_the_portable_manifest_is_agent_plugins_shape(self) -> None:
        self.assertEqual(self.manifest["$schema"], AGENT_PLUGINS_SCHEMA)
        for field in ("name", "version", "description"):
            with self.subTest(field=field):
                self.assertTrue(
                    isinstance(self.manifest[field], str) and self.manifest[field]
                )

    def test_the_three_manifests_agree_on_version(self) -> None:
        self.assertEqual(self.manifest["name"], "agent-launcher")
        self.assertEqual(self.manifest["version"], self.claude["version"])
        self.assertEqual(self.claude["skills"], "./skills/")


class PackageRootShapeTests(unittest.TestCase):
    """The portable root carries no Claude convention directories."""

    def test_no_convention_directory_sits_at_the_portable_root(self) -> None:
        for name in CLAUDE_CONVENTION_DIRS:
            with self.subTest(directory=name):
                self.assertFalse((PACKAGE / name).exists())


if __name__ == "__main__":
    unittest.main()
