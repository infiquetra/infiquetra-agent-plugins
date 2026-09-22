"""Tests for the generated Codex marketplace and plugin manifests.

Codex installs from ``.agents/plugins/marketplace.json`` and from
``.codex-plugin/plugin.json`` inside each plugin directory. Both are
generated: an import adds a portable manifest, and the packaging has to
follow without a hand edit of a shared JSON file.

A generated file is only safe if something notices when the committed copy
stops matching, so the check is wired into ``scripts/check_repo.py`` and
exercised here in both directions.

Every fixture is a scratch repository with inert example values. The
committed tree is checked too, in one test, because that is the artifact
that ships.

Standard library only, matching the repository baseline.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import sync_codex_packaging as sync  # noqa: E402


def portable_manifest(name: str, **overrides: object) -> dict:
    manifest = {
        "$schema": check_repo.PLUGIN_SCHEMA,
        "name": name,
        "version": "1.2.3",
        "description": f"The portable {name} package.",
    }
    manifest.update(overrides)
    return manifest


class PackagingCase(unittest.TestCase):
    """A scratch repository with whatever packages a test needs."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)

    def add_package(
        self,
        name: str,
        *,
        portable: dict | None = None,
        skills: bool = True,
    ) -> Path:
        package = self.root / "plugins" / name
        package.mkdir(parents=True)
        payload = portable_manifest(name) if portable is None else portable
        (package / "plugin.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
        if skills:
            skill = package / "skills" / name
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: example\n---\n\n",
                encoding="utf-8",
            )
        return package

    def manifest(self, name: str) -> dict:
        return sync.build_plugin_manifest(self.root / "plugins" / name)

    def marketplace(self) -> dict:
        return sync.build_marketplace(self.root)

    def entry_names(self) -> list[str]:
        return [entry["name"] for entry in self.marketplace()["plugins"]]


class ListingRuleTests(PackagingCase):
    """A package is listed exactly when it has a portable manifest."""

    def test_a_package_with_a_portable_manifest_is_listed(self) -> None:
        self.add_package("alpha")
        self.assertEqual(self.entry_names(), ["alpha"])

    def test_a_directory_without_a_portable_manifest_is_not_listed(self) -> None:
        self.add_package("alpha")
        bare = self.root / "plugins" / "beta"
        bare.mkdir(parents=True)
        (bare / "README.md").write_text("not a package\n", encoding="utf-8")
        self.assertEqual(self.entry_names(), ["alpha"])

    def test_entries_are_sorted_by_package_name(self) -> None:
        for name in ("zulu", "alpha", "mike"):
            self.add_package(name)
        self.assertEqual(self.entry_names(), ["alpha", "mike", "zulu"])

    def test_a_repository_with_no_packages_lists_nothing(self) -> None:
        self.assertEqual(self.entry_names(), [])


class ManifestFieldTests(PackagingCase):
    """The manifest carries identity and paths, and nothing that runs."""

    def test_identity_comes_from_the_portable_manifest(self) -> None:
        self.add_package("alpha", portable=portable_manifest("alpha", keywords=["one", "two"]))
        manifest = self.manifest("alpha")
        self.assertEqual(manifest["name"], "alpha")
        self.assertEqual(manifest["version"], "1.2.3")
        self.assertEqual(manifest["description"], "The portable alpha package.")
        self.assertEqual(manifest["keywords"], ["one", "two"])
        self.assertNotIn("$schema", manifest)

    def test_skills_point_at_the_portable_directory(self) -> None:
        self.add_package("alpha")
        self.assertEqual(self.manifest("alpha")["skills"], "./skills/")

    def test_a_package_without_skills_does_not_invent_the_path(self) -> None:
        self.add_package("alpha", skills=False)
        self.assertNotIn("skills", self.manifest("alpha"))

    def test_adapter_skills_are_used_only_when_the_package_has_none(self) -> None:
        package = self.add_package("alpha", skills=False)
        (package / "com.infiquetra.codex" / "skills" / "alpha").mkdir(parents=True)
        self.assertEqual(
            self.manifest("alpha")["skills"],
            "./com.infiquetra.codex/skills/",
        )

    def test_portable_skills_win_when_the_adapter_also_has_skills(self) -> None:
        package = self.add_package("alpha")
        (package / "com.infiquetra.codex" / "skills").mkdir(parents=True)
        self.assertEqual(self.manifest("alpha")["skills"], "./skills/")

    def test_an_adapter_mcp_file_is_a_path(self) -> None:
        package = self.add_package("alpha")
        adapter = package / "com.infiquetra.codex"
        adapter.mkdir()
        (adapter / ".mcp.json").write_text("{}\n", encoding="utf-8")
        manifest = self.manifest("alpha")
        self.assertEqual(manifest["mcpServers"], "./com.infiquetra.codex/.mcp.json")

    def test_a_root_mcp_file_is_not_declared(self) -> None:
        package = self.add_package("alpha")
        (package / ".mcp.json").write_text("{}\n", encoding="utf-8")
        self.assertNotIn("mcpServers", self.manifest("alpha"))

    def test_the_manifest_has_no_hooks_and_no_default_prompt(self) -> None:
        package = self.add_package("alpha")
        (package / "com.infiquetra.codex" / "hooks").mkdir(parents=True)
        manifest = self.manifest("alpha")
        self.assertNotIn("hooks", manifest)
        self.assertNotIn("commands", manifest)
        self.assertNotIn("defaultPrompt", manifest["interface"])
        self.assertEqual(manifest["interface"]["displayName"], "Alpha")
        self.assertEqual(
            manifest["interface"]["shortDescription"],
            "The portable alpha package.",
        )

    def test_a_name_that_disagrees_with_the_directory_is_an_error(self) -> None:
        self.add_package("alpha", portable=portable_manifest("beta"))
        with self.assertRaises(sync.PackagingError):
            self.manifest("alpha")

    def test_a_claude_sibling_does_not_change_the_manifest(self) -> None:
        package = self.add_package("alpha")
        claude = package / ".claude-plugin"
        claude.mkdir()
        (claude / "plugin.json").write_text("{}\n", encoding="utf-8")
        self.assertEqual(self.manifest("alpha")["skills"], "./skills/")


class MarketplaceFieldTests(PackagingCase):
    """The entry shape is the one Codex already loads."""

    def test_the_source_is_a_local_path_to_the_package_root(self) -> None:
        self.add_package("alpha")
        entry = self.marketplace()["plugins"][0]
        self.assertEqual(entry["source"], {"source": "local", "path": "./plugins/alpha"})
        self.assertEqual(
            entry["policy"],
            {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        )

    def test_the_first_marketplace_gets_the_catalog_name(self) -> None:
        self.add_package("alpha")
        payload = self.marketplace()
        self.assertEqual(payload["name"], "infiquetra-agent-plugins")
        self.assertEqual(payload["interface"]["displayName"], "Infiquetra Agent Plugins")

    def test_an_existing_name_interface_and_category_are_preserved(self) -> None:
        self.add_package("alpha")
        sync.write_packaging(self.root)
        path = self.root / sync.MARKETPLACE_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["name"] = "kept-name"
        payload["interface"] = {"displayName": "Kept"}
        payload["plugins"][0]["category"] = "Example"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        rebuilt = self.marketplace()
        self.assertEqual(rebuilt["name"], "kept-name")
        self.assertEqual(rebuilt["interface"], {"displayName": "Kept"})
        self.assertEqual(rebuilt["plugins"][0]["category"], "Example")

    def test_a_category_is_not_invented(self) -> None:
        self.add_package("alpha")
        self.assertNotIn("category", self.marketplace()["plugins"][0])


class StalenessTests(PackagingCase):
    """The check fails when the committed files drift, and says how to fix them."""

    def test_a_fresh_tree_passes_after_a_write(self) -> None:
        self.add_package("alpha")
        self.assertTrue(sync.check_codex_packaging(self.root))
        sync.write_packaging(self.root)
        self.assertEqual(sync.check_codex_packaging(self.root), [])

    def test_a_hand_edited_manifest_is_reported(self) -> None:
        self.add_package("alpha")
        sync.write_packaging(self.root)
        path = self.root / "plugins" / "alpha" / ".codex-plugin" / "plugin.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["hooks"] = {"Stop": []}
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        problems = sync.check_codex_packaging(self.root)
        self.assertTrue(any("stale" in problem for problem in problems))

    def test_a_removed_package_leaves_an_unexpected_manifest_until_regeneration(self) -> None:
        self.add_package("alpha")
        self.add_package("beta")
        sync.write_packaging(self.root)
        (self.root / "plugins" / "beta" / "plugin.json").unlink()
        problems = sync.check_codex_packaging(self.root)
        self.assertTrue(any("unexpected" in problem and "beta" in problem for problem in problems))
        sync.write_packaging(self.root)
        orphan = self.root / "plugins" / "beta" / ".codex-plugin" / "plugin.json"
        self.assertFalse(orphan.exists())
        self.assertEqual(sync.check_codex_packaging(self.root), [])

    def test_the_message_names_the_command_that_fixes_it(self) -> None:
        self.add_package("alpha")
        problems = sync.check_codex_packaging(self.root)
        self.assertTrue(any("sync_codex_packaging.py" in problem for problem in problems))

    def test_the_repository_gate_runs_this_check(self) -> None:
        """Wired in, not merely importable: the gate is what has to catch a stale file."""
        self.add_package("alpha")
        problems = check_repo.check_repo(self.root)
        self.assertTrue(any("sync_codex_packaging.py" in problem for problem in problems))


class CommittedPackagingTests(unittest.TestCase):
    """The artifact that ships."""

    def test_it_is_current(self) -> None:
        self.assertEqual(sync.check_codex_packaging(ROOT), [])
