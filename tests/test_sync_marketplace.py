"""Tests for the generated Claude marketplace.

The marketplace was hand-edited while one package was listed. Twelve import
units are about to add one entry each to the same array, so it is generated
instead: a branch runs the generator and commits the result, and a rebase
conflict is resolved by running it again.

A generated file is only safe if something notices when the committed copy stops
matching, so the check is wired into `scripts/check_repo.py` and exercised here
in both directions.

Every fixture is a scratch repository built in a temporary directory with inert
example values, so nothing here depends on which packages the real tree happens
to carry this week. The committed file is checked too, in one test, because that
is the artifact that ships.

Standard library only, matching the repository baseline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import sync_marketplace as sm  # noqa: E402


CATALOG = {
    "name": "example-catalog",
    "owner": {"name": "Example", "email": "nobody@example.com"},
    "metadata": {"description": "An example catalog.", "version": "1.0.0"},
}


def claude_manifest(name: str, **overrides: object) -> dict:
    manifest = {
        "name": name,
        "version": "1.2.3",
        "description": f"The {name} package.",
        "author": {"name": "Example", "email": "nobody@example.com"},
        "repository": "https://example.com/catalog",
        "license": "MIT",
        "keywords": [name, "example"],
    }
    manifest.update(overrides)
    return manifest


def portable_manifest(name: str, **overrides: object) -> dict:
    manifest = {
        "$schema": check_repo.PLUGIN_SCHEMA,
        "name": name,
        "version": "1.2.3",
        "description": f"The portable {name} package.",
    }
    manifest.update(overrides)
    return manifest


class MarketplaceCase(unittest.TestCase):
    """A scratch repository with whatever packages a test needs."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        (self.root / ".claude-plugin").mkdir()

    def write_catalog(self, marketplace: dict | None = None) -> None:
        payload = CATALOG if marketplace is None else marketplace
        (self.root / sm.MARKETPLACE_PATH).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )

    def add_package(
        self,
        name: str,
        *,
        claude: bool = True,
        portable: dict | None = None,
        claude_overrides: dict | None = None,
    ) -> Path:
        package = self.root / "plugins" / name
        package.mkdir(parents=True)
        if claude:
            manifest = claude_manifest(name)
            manifest.update(claude_overrides or {})
            (package / ".claude-plugin").mkdir()
            (package / sm.CLAUDE_MANIFEST_RELATIVE).write_text(
                json.dumps(manifest, indent=2), encoding="utf-8"
            )
        payload = portable_manifest(name) if portable is None else portable
        (package / sm.PORTABLE_MANIFEST_NAME).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return package

    def generate(self) -> dict:
        return sm.build_marketplace(self.root)

    def entry_names(self) -> list[str]:
        return [entry["name"] for entry in self.generate()["plugins"]]

    def write_generated(self) -> None:
        (self.root / sm.MARKETPLACE_PATH).write_text(
            sm.render(self.generate()), encoding="utf-8"
        )


class ListingRuleTests(MarketplaceCase):
    """A package is listed exactly when Claude can install it."""

    def test_a_package_with_a_claude_manifest_is_listed(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        self.assertEqual(self.entry_names(), ["alpha"])

    def test_a_package_without_one_is_not_listed(self) -> None:
        """It cannot be installed, so an entry for it would be an entry that fails."""
        self.write_catalog()
        self.add_package("alpha")
        self.add_package("beta", claude=False)
        self.assertEqual(self.entry_names(), ["alpha"])

    def test_entries_are_sorted_by_package_name(self) -> None:
        """Order is what keeps twelve branches from conflicting on the array."""
        self.write_catalog()
        for name in ("zulu", "alpha", "mike"):
            self.add_package(name)
        self.assertEqual(self.entry_names(), ["alpha", "mike", "zulu"])

    def test_a_repository_with_no_packages_lists_nothing(self) -> None:
        self.write_catalog()
        self.assertEqual(self.entry_names(), [])


class EntryFieldTests(MarketplaceCase):
    """Every field an entry states is read from the package it describes."""

    def test_the_source_is_the_package_root(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        self.assertEqual(self.generate()["plugins"][0]["source"], "./plugins/alpha")

    def test_version_and_description_come_from_the_claude_manifest(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        entry = self.generate()["plugins"][0]
        manifest = claude_manifest("alpha")
        for field in ("version", "description"):
            with self.subTest(field=field):
                self.assertEqual(entry[field], manifest[field])

    def test_presentation_fields_only_the_claude_manifest_states_are_ignored(self) -> None:
        """The Claude manifest carries none; one that does is not a second source."""
        self.write_catalog()
        self.add_package(
            "alpha", claude_overrides={"homepage": "https://example.com", "category": "tools"}
        )
        entry = self.generate()["plugins"][0]
        for field in ("author", "repository", "license", "homepage", "keywords", "category"):
            with self.subTest(field=field):
                self.assertNotIn(field, entry)

    def test_keywords_prefer_the_portable_manifest(self) -> None:
        self.write_catalog()
        self.add_package(
            "alpha", portable=portable_manifest("alpha", keywords=["portable", "words"])
        )
        self.assertEqual(self.generate()["plugins"][0]["keywords"], ["portable", "words"])

    def test_presentation_metadata_prefers_the_portable_manifest(self) -> None:
        self.write_catalog()
        portable_values = {
            "author": {"name": "Portable", "email": "portable@example.com"},
            "repository": "https://example.com/portable",
            "license": "Apache-2.0",
            "homepage": "https://example.com/home",
        }
        self.add_package("alpha", portable=portable_manifest("alpha", **portable_values))
        entry = self.generate()["plugins"][0]
        for field, value in portable_values.items():
            with self.subTest(field=field):
                self.assertEqual(entry[field], value)

    def test_presentation_metadata_is_read_when_only_the_portable_manifest_states_it(
        self,
    ) -> None:
        self.write_catalog()
        package = self.add_package(
            "alpha",
            portable=portable_manifest(
                "alpha",
                author={"name": "Portable", "email": "portable@example.com"},
                repository="https://example.com/portable",
                license="MIT",
                keywords=["portable"],
            ),
        )
        (package / sm.CLAUDE_MANIFEST_RELATIVE).write_text(
            json.dumps({"name": "alpha", "version": "1.2.3", "description": "Alpha."}),
            encoding="utf-8",
        )
        entry = self.generate()["plugins"][0]
        self.assertEqual(entry["author"]["name"], "Portable")
        self.assertEqual(entry["repository"], "https://example.com/portable")
        self.assertEqual(entry["license"], "MIT")
        self.assertEqual(entry["keywords"], ["portable"])

    def test_the_entry_and_the_manifest_cannot_disagree_on_version(self) -> None:
        """The agreement `claude plugin tag` refuses to release without."""
        self.write_catalog()
        self.add_package("alpha", claude_overrides={"version": "9.9.9"})
        self.assertEqual(self.generate()["plugins"][0]["version"], "9.9.9")


class PreservationTests(MarketplaceCase):
    """What no package could describe is carried from the existing file."""

    def test_the_catalog_block_survives_regeneration(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        generated = self.generate()
        for key in sm.PRESERVED_TOP_LEVEL:
            with self.subTest(key=key):
                self.assertEqual(generated[key], CATALOG[key])

    def test_an_entry_only_category_is_not_dropped(self) -> None:
        # `category` places a package in the catalog's browsing taxonomy and has
        # no home in either manifest. Deriving it would mean inventing a field
        # in a schema this repository does not own, so it is preserved instead.
        catalog = dict(CATALOG)
        catalog["plugins"] = [{"name": "alpha", "category": "development"}]
        self.write_catalog(catalog)
        self.add_package("alpha")
        self.assertEqual(self.generate()["plugins"][0]["category"], "development")

    def test_the_portable_manifest_can_state_a_category_instead(self) -> None:
        self.write_catalog()
        self.add_package("alpha", portable=portable_manifest("alpha", category="utilities"))
        self.assertEqual(self.generate()["plugins"][0]["category"], "utilities")

    def test_regenerating_twice_changes_nothing(self) -> None:
        """A generator whose output is not a fixed point cannot be a gate."""
        self.write_catalog()
        self.add_package("alpha")
        self.add_package("beta")
        self.write_generated()
        first = (self.root / sm.MARKETPLACE_PATH).read_text(encoding="utf-8")
        self.write_generated()
        self.assertEqual((self.root / sm.MARKETPLACE_PATH).read_text(encoding="utf-8"), first)


class RefusalTests(MarketplaceCase):
    """A manifest that would produce an entry pointing elsewhere is refused."""

    def test_a_manifest_whose_name_is_not_its_directory_is_refused(self) -> None:
        self.write_catalog()
        self.add_package("alpha", claude_overrides={"name": "not-alpha"})
        with self.assertRaises(sm.MarketplaceError) as caught:
            self.generate()
        self.assertIn("not-alpha", str(caught.exception))

    def test_a_manifest_with_no_name_is_refused(self) -> None:
        self.write_catalog()
        package = self.add_package("alpha")
        (package / sm.CLAUDE_MANIFEST_RELATIVE).write_text('{"version": "1"}', encoding="utf-8")
        with self.assertRaises(sm.MarketplaceError):
            self.generate()

    def test_unreadable_json_is_reported_rather_than_crashing(self) -> None:
        self.write_catalog()
        package = self.add_package("alpha")
        (package / sm.CLAUDE_MANIFEST_RELATIVE).write_text("{ not json", encoding="utf-8")
        problems = sm.check_marketplace(self.root)
        self.assertTrue(any("could not be read" in problem for problem in problems))


class StalenessTests(MarketplaceCase):
    """The check is what makes a generated file safe to commit."""

    def test_a_current_file_reports_nothing(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        self.write_generated()
        self.assertEqual(sm.check_marketplace(self.root), [])

    def test_a_package_added_without_regenerating_is_reported_by_name(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        self.write_generated()
        self.add_package("beta")
        problems = sm.check_marketplace(self.root)
        self.assertTrue(problems)
        self.assertTrue(any("beta" in problem for problem in problems))

    def test_a_package_removed_without_regenerating_is_reported_by_name(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        self.add_package("beta")
        self.write_generated()
        (self.root / "plugins" / "beta" / sm.CLAUDE_MANIFEST_RELATIVE).unlink()
        problems = sm.check_marketplace(self.root)
        self.assertTrue(any("beta" in problem for problem in problems))

    def test_a_hand_edited_entry_is_reported(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        self.write_generated()
        path = self.root / sm.MARKETPLACE_PATH
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["plugins"][0]["version"] = "0.0.1"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        problems = sm.check_marketplace(self.root)
        self.assertTrue(any("disagree" in problem for problem in problems))

    def test_a_missing_marketplace_is_reported(self) -> None:
        self.add_package("alpha")
        problems = sm.check_marketplace(self.root)
        self.assertTrue(any("missing marketplace" in problem for problem in problems))

    def test_the_message_names_the_command_that_fixes_it(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        self.write_generated()
        self.add_package("beta")
        problems = sm.check_marketplace(self.root)
        self.assertTrue(any("sync_marketplace.py" in problem for problem in problems))

    def test_the_repository_gate_runs_this_check(self) -> None:
        """Wired in, not merely importable: CI is what has to catch a stale file."""
        self.write_catalog()
        self.add_package("alpha")
        self.write_generated()
        self.add_package("beta")
        self.assertTrue(
            any("marketplace" in problem for problem in check_repo.check_repo(self.root))
        )


def muse_manifest(name: str, **overrides: object) -> dict:
    manifest = claude_manifest(name)
    manifest.update(
        {
            "skills": "./skills/",
            "commands": "./com.infiquetra.claude/commands/",
            "agents": ["./com.infiquetra.claude/agents/helper.md"],
            "mcpServers": "./com.infiquetra.claude/mcp/servers.json",
            "types": "./com.infiquetra.claude/types/index.d.ts",
            "outputStyles": "./com.infiquetra.claude/output-styles/",
            "homepage": "https://example.com/home",
        }
    )
    manifest.update(overrides)
    return manifest


class MuseStagingCase(MarketplaceCase):
    """A scratch package carrying every kind of file staging must keep or drop."""

    def add_muse_package(self, name: str, manifest: dict | None = None) -> Path:
        package = self.add_package(name, claude=False)
        (package / ".claude-plugin").mkdir()
        (package / sm.CLAUDE_MANIFEST_RELATIVE).write_text(
            json.dumps(manifest or muse_manifest(name)), encoding="utf-8"
        )
        files = {
            "skills/one/SKILL.md": "---\nname: one\ndescription: One.\n---\n",
            "scripts/run.py": "print('run')\n",
            "references/guide.md": "A guide.\n",
            "roles/role.md": "A role.\n",
            "server/app.py": "print('server')\n",
            "config/settings.json": "{}\n",
            "schemas/s.json": "{}\n",
            "templates/t.txt": "t\n",
            "com.infiquetra.claude/commands/zeta.md": "Zeta.\n",
            "com.infiquetra.claude/commands/alpha.md": "Alpha.\n",
            "com.infiquetra.claude/commands/notes.txt": "Not a command.\n",
            "com.infiquetra.claude/hooks/hooks.json": '{"hooks": {}}\n',
            "com.infiquetra.claude/agents/helper.md": "Helper.\n",
            "com.infiquetra.claude/mcp/servers.json": json.dumps(
                {name: {"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/server/app.py"]}}
            ),
            "README.md": "Readme.\n",
            "CHANGELOG.md": "Changes.\n",
            "LICENSE": "MIT\n",
            ".codex-plugin/plugin.json": "{}\n",
            "__pycache__/x.pyc": "x",
            ".pytest_cache/y": "y",
        }
        for relative, text in files.items():
            path = package / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        return package


class MuseApplicablePackageTests(MuseStagingCase):
    def test_only_packages_declaring_a_loadable_capability_are_applicable(self) -> None:
        self.write_catalog()
        self.add_muse_package("alpha")
        self.add_package("beta", claude=False)
        style = self.add_package("styled")
        (style / sm.CLAUDE_MANIFEST_RELATIVE).write_text(
            json.dumps({"name": "styled", "outputStyles": "./com.infiquetra.claude/styles/"}),
            encoding="utf-8",
        )
        self.assertEqual(
            [package.name for package in sm.muse_applicable_packages(self.root)], ["alpha"]
        )

    def test_the_committed_tree_has_exactly_the_twelve_installable_packages(self) -> None:
        self.assertEqual(
            [package.name for package in sm.muse_applicable_packages(ROOT)],
            [
                "agent-launcher",
                "agy",
                "codex",
                "deploy",
                "hermes-profile-evolution",
                "home-lab-ops",
                "mission-control",
                "orchestrate",
                "redis-channel",
                "saga",
                "unifi",
                "voice",
            ],
        )


class StageMusePluginTests(MuseStagingCase):
    def stage(self, name: str = "alpha", manifest: dict | None = None) -> Path:
        package = self.add_muse_package(name, manifest)
        destination = self.root / "staged" / name
        self.assertEqual(sm.stage_muse_plugin(package, destination), destination)
        return destination

    def staged_manifest(self, staged: Path) -> dict:
        return json.loads((staged / sm.CLAUDE_MANIFEST_RELATIVE).read_text(encoding="utf-8"))

    def test_runtime_directories_and_documents_are_preserved(self) -> None:
        staged = self.stage()
        for relative in (
            "skills/one/SKILL.md",
            "scripts/run.py",
            "references/guide.md",
            "roles/role.md",
            "server/app.py",
            "config/settings.json",
            "schemas/s.json",
            "templates/t.txt",
            "com.infiquetra.claude/commands/alpha.md",
            "com.infiquetra.claude/hooks/hooks.json",
            "com.infiquetra.claude/mcp/servers.json",
            "README.md",
            "CHANGELOG.md",
            "LICENSE",
        ):
            with self.subTest(path=relative):
                self.assertTrue((staged / relative).is_file())

    def test_other_adapters_manifests_and_caches_are_left_behind(self) -> None:
        staged = self.stage()
        for relative in ("plugin.json", ".codex-plugin", "__pycache__", ".pytest_cache"):
            with self.subTest(path=relative):
                self.assertFalse((staged / relative).exists())

    def test_a_nested_plugin_json_is_not_mistaken_for_the_root_one(self) -> None:
        package = self.add_muse_package("alpha")
        (package / "schemas" / "plugin.json").write_text("{}\n", encoding="utf-8")
        staged = self.root / "staged" / "alpha"
        sm.stage_muse_plugin(package, staged)
        self.assertTrue((staged / "schemas" / "plugin.json").is_file())

    #: Written out here, not read from `sm.MUSE_UNSUPPORTED_KEYS`: a test that iterates
    #: the production constant stays green when a key is deleted from it.
    REJECTED_BY_MUSE = (
        "author",
        "repository",
        "keywords",
        "license",
        "homepage",
        "types",
        "outputStyles",
        "agents",
    )

    def test_claude_only_keys_are_removed_from_the_staged_manifest(self) -> None:
        staged = self.stage()
        source_path = self.root / "plugins" / "alpha" / sm.CLAUDE_MANIFEST_RELATIVE
        source = json.loads(source_path.read_text(encoding="utf-8"))
        manifest = self.staged_manifest(staged)
        for key in self.REJECTED_BY_MUSE:
            with self.subTest(key=key):
                self.assertIn(key, source, "the fixture must declare every rejected key")
                self.assertNotIn(key, manifest)
        self.assertEqual(manifest["name"], "alpha")
        self.assertEqual(manifest["version"], "1.2.3")

    def test_skills_become_a_list_and_commands_become_sorted_files(self) -> None:
        manifest = self.staged_manifest(self.stage())
        self.assertEqual(manifest["skills"], ["./skills/"])
        self.assertEqual(
            manifest["commands"],
            [
                "./com.infiquetra.claude/commands/alpha.md",
                "./com.infiquetra.claude/commands/zeta.md",
            ],
        )

    def test_commands_duplicating_skill_shortcuts_are_omitted(self) -> None:
        package = self.add_muse_package("alpha")
        (package / "com.infiquetra.claude/commands/one.md").write_text("# one\n", encoding="utf-8")
        (package / "skills/alpha-delegate").mkdir(parents=True)
        (package / "skills/alpha-delegate/SKILL.md").write_text("---\nname: alpha-delegate\n---\n")
        (package / "com.infiquetra.claude/commands/delegate.md").write_text(
            "# delegate\n", encoding="utf-8"
        )
        staged = sm.stage_muse_plugin(package, self.root / "staged" / "alpha")
        manifest = self.staged_manifest(staged)
        self.assertEqual(
            manifest["commands"],
            [
                "./com.infiquetra.claude/commands/alpha.md",
                "./com.infiquetra.claude/commands/zeta.md",
            ],
        )

        # When every command wrapper duplicates a skill shortcut, drop the empty key.
        (package / "com.infiquetra.claude/commands/alpha.md").unlink()
        (package / "com.infiquetra.claude/commands/zeta.md").unlink()
        staged_empty = sm.stage_muse_plugin(package, self.root / "staged" / "alpha-empty")
        self.assertNotIn("commands", self.staged_manifest(staged_empty))

    def test_a_bare_mcp_server_map_is_wrapped(self) -> None:
        staged = self.stage()
        servers = json.loads(
            (staged / "com.infiquetra.claude/mcp/servers.json").read_text(encoding="utf-8")
        )
        self.assertEqual(list(servers), ["mcpServers"])
        self.assertIn("alpha", servers["mcpServers"])

    def test_an_already_wrapped_mcp_map_is_left_alone(self) -> None:
        package = self.add_muse_package("alpha")
        wrapped = {"mcpServers": {"alpha": {"command": "python3"}}}
        servers = package / "com.infiquetra.claude/mcp/servers.json"
        servers.write_text(json.dumps(wrapped), encoding="utf-8")
        staged = self.root / "staged" / "alpha"
        sm.stage_muse_plugin(package, staged)
        self.assertEqual(
            json.loads((staged / "com.infiquetra.claude/mcp/servers.json").read_text("utf-8")),
            wrapped,
        )

    def test_the_source_package_is_not_modified(self) -> None:
        package = self.add_muse_package("alpha")
        before = (package / sm.CLAUDE_MANIFEST_RELATIVE).read_text(encoding="utf-8")
        servers_before = (package / "com.infiquetra.claude/mcp/servers.json").read_text("utf-8")
        sm.stage_muse_plugin(package, self.root / "staged" / "alpha")
        self.assertEqual((package / sm.CLAUDE_MANIFEST_RELATIVE).read_text("utf-8"), before)
        self.assertEqual(
            (package / "com.infiquetra.claude/mcp/servers.json").read_text("utf-8"),
            servers_before,
        )

    def snapshot(self, directory: Path) -> dict[str, bytes]:
        return {
            str(path.relative_to(directory)): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        }

    def test_a_destination_that_overlaps_the_package_is_refused_and_nothing_is_deleted(
        self,
    ) -> None:
        package = self.add_muse_package("alpha")
        sibling = package.parent / "sibling.txt"
        sibling.write_text("kept\n", encoding="utf-8")
        before = self.snapshot(package.parent)
        for label, destination in (
            ("the package itself", package),
            ("an ancestor", package.parent),
            ("a descendant", package / "nested"),
        ):
            with self.subTest(destination=label):
                with self.assertRaises(sm.MarketplaceError):
                    sm.stage_muse_plugin(package, destination)
                self.assertEqual(self.snapshot(package.parent), before)

    def test_a_manifest_path_that_leaves_the_package_is_refused(self) -> None:
        victim = self.root / "victim.json"
        victim.write_text('{"a": 1}', encoding="utf-8")
        cases = {
            "absolute mcpServers": {"mcpServers": str(victim)},
            "climbing mcpServers": {"mcpServers": "../../victim.json"},
            "climbing commands": {"commands": "../outside/"},
            "absolute commands": {"commands": str(self.root)},
            "climbing skills": {"skills": ["./skills/", "../../elsewhere/"]},
            "non-string skills": {"skills": [3]},
        }
        for label, overrides in cases.items():
            with self.subTest(case=label):
                name = label.replace(" ", "-")
                package = self.add_muse_package(name, muse_manifest(name, **overrides))
                destination = self.root / "staged" / name
                with self.assertRaises(sm.MarketplaceError):
                    sm.stage_muse_plugin(package, destination)
                self.assertFalse(destination.exists())
                self.assertEqual(victim.read_text(encoding="utf-8"), '{"a": 1}')

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are not supported here")
    def test_a_symlink_that_leaves_the_package_is_refused(self) -> None:
        package = self.add_muse_package("alpha")
        outside = self.root / "outside.txt"
        outside.write_text("secret\n", encoding="utf-8")
        (package / "link.txt").symlink_to(outside)
        destination = self.root / "staged" / "alpha"
        with self.assertRaises(sm.MarketplaceError) as caught:
            sm.stage_muse_plugin(package, destination)
        self.assertIn("link.txt", str(caught.exception))
        self.assertFalse(destination.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are not supported here")
    def test_a_symlink_loop_is_refused_and_an_inside_symlink_is_copied(self) -> None:
        package = self.add_muse_package("alpha")
        (package / "loop").symlink_to(package / "loop")
        with self.assertRaises(sm.MarketplaceError):
            sm.stage_muse_plugin(package, self.root / "staged" / "alpha")
        (package / "loop").unlink()
        (package / "alias.md").symlink_to(package / "README.md")
        staged = sm.stage_muse_plugin(package, self.root / "staged" / "alpha")
        self.assertEqual((staged / "alias.md").read_text(encoding="utf-8"), "Readme.\n")


class StageMuseMarketplaceTests(MuseStagingCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_catalog()
        for name in ("alpha", "beta"):
            self.add_muse_package(name)
        self.target = self.root / "out"

    def listed(self) -> list[str]:
        payload = json.loads((self.target / sm.MARKETPLACE_PATH).read_text(encoding="utf-8"))
        return [entry["name"] for entry in payload["plugins"]]

    def test_every_applicable_package_is_staged_and_listed(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        self.assertEqual(self.listed(), ["alpha", "beta"])
        self.assertTrue((self.target / "plugins/alpha/roles/role.md").is_file())
        self.assertTrue((self.target / "plugins/beta/references/guide.md").is_file())
        self.assertTrue((self.target / "plugins/beta/server/app.py").is_file())

    def test_a_partial_run_keeps_the_packages_already_staged(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        sentinel = self.target / "plugins/beta/sentinel.txt"
        sentinel.write_text("kept\n", encoding="utf-8")
        (self.root / "plugins/alpha/README.md").write_text("Changed.\n", encoding="utf-8")
        sm.stage_muse_marketplace(self.root, self.target, packages=["alpha"])
        self.assertEqual(self.listed(), ["alpha", "beta"])
        self.assertTrue(sentinel.is_file())
        self.assertEqual(
            (self.target / "plugins/alpha/README.md").read_text(encoding="utf-8"), "Changed.\n"
        )

    def test_a_full_run_prunes_packages_the_source_no_longer_has(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        shutil.rmtree(self.root / "plugins/beta")
        sm.stage_muse_marketplace(self.root, self.target)
        self.assertEqual(self.listed(), ["alpha"])
        self.assertFalse((self.target / "plugins/beta").exists())

    def test_a_full_run_prunes_packages_muse_can_no_longer_install(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        (self.root / "plugins/beta" / sm.CLAUDE_MANIFEST_RELATIVE).write_text(
            json.dumps({"name": "beta", "outputStyles": "./styles/"}), encoding="utf-8"
        )
        sm.stage_muse_marketplace(self.root, self.target)
        self.assertEqual(self.listed(), ["alpha"])
        self.assertFalse((self.target / "plugins/beta").exists())

    def test_a_partial_run_does_not_prune(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        shutil.rmtree(self.root / "plugins/beta")
        sm.stage_muse_marketplace(self.root, self.target, packages=["alpha"])
        self.assertEqual(self.listed(), ["alpha", "beta"])

    def test_a_target_that_overlaps_the_source_packages_is_refused(self) -> None:
        before = sorted(str(path) for path in (self.root / "plugins").rglob("*"))
        for label, target in (
            ("the repository", self.root),
            ("the packages directory", self.root / "plugins"),
            ("inside the packages", self.root / "plugins" / "alpha" / "out"),
        ):
            with self.subTest(target=label):
                with self.assertRaises(sm.MarketplaceError):
                    sm.stage_muse_marketplace(self.root, target)
                self.assertEqual(
                    sorted(str(path) for path in (self.root / "plugins").rglob("*")), before
                )

    def test_a_partial_run_into_an_empty_target_lists_only_what_it_staged(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target, packages=["beta"])
        self.assertEqual(self.listed(), ["beta"])

    def test_a_package_that_cannot_be_installed_is_refused_by_name(self) -> None:
        with self.assertRaises(sm.MarketplaceError) as caught:
            sm.stage_muse_marketplace(self.root, self.target, packages=["missing"])
        self.assertIn("missing", str(caught.exception))

    def test_the_catalog_block_is_carried_into_the_staged_marketplace(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        payload = json.loads((self.target / sm.MARKETPLACE_PATH).read_text(encoding="utf-8"))
        for key in sm.PRESERVED_TOP_LEVEL:
            with self.subTest(key=key):
                self.assertEqual(payload[key], CATALOG[key])

    def test_staging_name_override_is_owned_by_the_generator(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target, name="explicit-muse-name")
        payload = json.loads((self.target / sm.MARKETPLACE_PATH).read_text())
        self.assertEqual(payload["name"], "explicit-muse-name")
        self.assertTrue((self.target / sm.MUSE_STAGING_MARKER).is_file())

    def test_non_empty_unmarked_target_is_refused_without_deleting_files(self) -> None:
        sentinel = self.target / "plugins/precious-data/keep"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("valuable")
        with self.assertRaises(sm.MarketplaceError):
            sm.stage_muse_marketplace(self.root, self.target)
        self.assertEqual(sentinel.read_text(), "valuable")

    def test_foreign_entries_in_owned_staging_survive_and_are_never_listed(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        foreign = self.target / "plugins/precious-data"
        (foreign / ".claude-plugin").mkdir(parents=True)
        (foreign / ".claude-plugin/plugin.json").write_text(json.dumps({"name": "precious-data"}))
        (foreign / "keep").write_text("valuable")
        sm.stage_muse_marketplace(self.root, self.target)
        self.assertEqual((foreign / "keep").read_text(), "valuable")
        self.assertNotIn("precious-data", self.listed())

    def test_a_symlinked_or_group_writable_staging_path_is_refused(self) -> None:
        other = self.root / "outside-stage"
        other.mkdir()
        self.target.symlink_to(other, target_is_directory=True)
        with self.assertRaises(sm.MarketplaceError):
            sm.stage_muse_marketplace(self.root, self.target)
        self.target.unlink()
        self.target.mkdir()
        self.target.chmod(0o770)
        with self.assertRaises(sm.MarketplaceError):
            sm.stage_muse_marketplace(self.root, self.target)

    def test_another_users_staging_path_is_refused(self) -> None:
        from unittest.mock import patch

        self.target.mkdir()
        with patch.object(sm.os, "getuid", return_value=self.target.stat().st_uid + 1):
            with self.assertRaises(sm.MarketplaceError):
                sm.stage_muse_marketplace(self.root, self.target)

    def test_planted_plugins_symlink_cannot_write_outside_staging(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        shutil.rmtree(self.target / "plugins")
        other = self.root / "unrelated"
        other.mkdir()
        (self.target / "plugins").symlink_to(other, target_is_directory=True)
        with self.assertRaises(sm.MarketplaceError):
            sm.stage_muse_marketplace(self.root, self.target)
        self.assertEqual(list(other.iterdir()), [])

    def test_marker_from_another_catalog_is_refused(self) -> None:
        sm.stage_muse_marketplace(self.root, self.target)
        path = self.target / sm.MUSE_STAGING_MARKER
        payload = json.loads(path.read_text())
        payload["catalog"] = "/example/unrelated"
        path.write_text(json.dumps(payload))
        with self.assertRaises(sm.MarketplaceError):
            sm.stage_muse_marketplace(self.root, self.target)


def _command_count(package: Path) -> int:
    skills = package / "skills"
    return sum(
        1
        for path in package.glob("com.infiquetra.claude/commands/*.md")
        if not (skills / path.stem / "SKILL.md").is_file()
        and not (skills / f"{package.name}-{path.stem}" / "SKILL.md").is_file()
    )


def _hook_count(package: Path) -> int:
    declared = json.loads((package / sm.CLAUDE_MANIFEST_RELATIVE).read_text("utf-8")).get("hooks")
    if not isinstance(declared, str):
        return 0
    entries = json.loads((package / declared).read_text("utf-8")).get("hooks", {})
    return sum(len(matcher["hooks"]) for matchers in entries.values() for matcher in matchers)


def _mcp_count(package: Path) -> int:
    declared = json.loads((package / sm.CLAUDE_MANIFEST_RELATIVE).read_text("utf-8")).get(
        "mcpServers"
    )
    if not isinstance(declared, str):
        return 0
    data = json.loads((package / declared).read_text("utf-8"))
    return len(data.get("mcpServers", data))


class MuseReportContract(unittest.TestCase):
    """What a staged package's `muse plugins validate --json` report must say."""

    def assert_report_is_clean(self, report: dict, expected: dict[str, int]) -> None:
        self.assertTrue(report["valid"])
        self.assertEqual(report["diagnostics"], [])
        found = {k: len(v) for k, v in report["capabilities"].items() if k in expected}
        self.assertEqual(found, expected)


class MuseReportContractTests(MuseReportContract):
    """The contract is proved here without the muse CLI, which CI does not install."""

    EXPECTED = {"skills": 1, "commands": 2, "hooks": 0, "mcp_servers": 1}

    def report(self, **changes: object) -> dict:
        report: dict = {
            "valid": True,
            "diagnostics": [],
            "capabilities": {
                "skills": ["a"],
                "commands": ["a", "b"],
                "hooks": [],
                "mcp_servers": ["a"],
                "reminders": [],
            },
        }
        report.update(changes)
        return report

    def test_a_clean_report_passes(self) -> None:
        self.assert_report_is_clean(self.report(), self.EXPECTED)

    def test_any_diagnostic_fails_whatever_its_code(self) -> None:
        for code in ("unsupported-field", "agent-overlay-inactive", "some-new-warning"):
            with self.subTest(code=code), self.assertRaises(AssertionError):
                self.assert_report_is_clean(
                    self.report(diagnostics=[{"code": code, "severity": "warning"}]),
                    self.EXPECTED,
                )

    def test_an_invalid_report_or_a_lost_capability_fails(self) -> None:
        with self.assertRaises(AssertionError):
            self.assert_report_is_clean(self.report(valid=False), self.EXPECTED)
        lost = self.report()
        lost["capabilities"]["commands"] = ["a"]
        with self.assertRaises(AssertionError):
            self.assert_report_is_clean(lost, self.EXPECTED)


@unittest.skipUnless(shutil.which("muse"), "the muse CLI is not installed")
class MuseValidationTests(MuseReportContract):
    """Muse itself accepts what staging produces."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._directory.cleanup)
        cls.target = sm.stage_muse_marketplace(ROOT, Path(cls._directory.name) / "marketplace")

    def validate(self, name: str) -> dict:
        completed = subprocess.run(
            ["muse", "plugins", "validate", str(self.target / "plugins" / name), "--json"],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
        return json.loads(completed.stdout)

    def test_every_staged_package_validates_with_its_capabilities_intact(self) -> None:
        all_skills: set[str] = set()
        all_commands: list[str] = []
        for package in sm.muse_applicable_packages(ROOT):
            with self.subTest(package=package.name):
                report = self.validate(package.name)
                self.assert_report_is_clean(
                    report,
                    {
                        "skills": len(list(package.glob("skills/*/SKILL.md"))),
                        "commands": _command_count(package),
                        "hooks": _hook_count(package),
                        "mcp_servers": _mcp_count(package),
                    },
                )
                all_skills.update(entry["id"] for entry in report["capabilities"]["skills"])
                all_commands.extend(entry["id"] for entry in report["capabilities"]["commands"])
        self.assertEqual(len(all_commands), len(set(all_commands)))
        self.assertEqual(all_skills & set(all_commands), set())


class CommittedMarketplaceTests(unittest.TestCase):
    """The artifact that ships."""

    def test_it_is_current(self) -> None:
        self.assertEqual(sm.check_marketplace(ROOT), [])

    def test_it_lists_every_claude_installable_package(self) -> None:
        listed = [entry["name"] for entry in sm.build_marketplace(ROOT)["plugins"]]
        self.assertEqual(listed, [package.name for package in sm.claude_packages(ROOT)])

    def test_the_catalog_block_is_intact(self) -> None:
        payload = json.loads((ROOT / sm.MARKETPLACE_PATH).read_text(encoding="utf-8"))
        self.assertTrue(payload.get("name"))
        self.assertIsInstance(payload.get("owner"), dict)
        self.assertTrue(payload.get("metadata", {}).get("description"))


if __name__ == "__main__":
    unittest.main()
