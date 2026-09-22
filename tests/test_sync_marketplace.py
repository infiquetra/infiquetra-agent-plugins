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

    def test_identity_and_metadata_come_from_the_claude_manifest(self) -> None:
        self.write_catalog()
        self.add_package("alpha")
        entry = self.generate()["plugins"][0]
        manifest = claude_manifest("alpha")
        for field in ("version", "description", "author", "repository", "license"):
            with self.subTest(field=field):
                self.assertEqual(entry[field], manifest[field])

    def test_a_field_the_manifest_does_not_state_is_omitted(self) -> None:
        self.write_catalog()
        manifest = claude_manifest("alpha")
        del manifest["license"]
        package = self.add_package("alpha")
        (package / sm.CLAUDE_MANIFEST_RELATIVE).write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        self.assertNotIn("license", self.generate()["plugins"][0])

    def test_keywords_prefer_the_portable_manifest(self) -> None:
        self.write_catalog()
        self.add_package(
            "alpha", portable=portable_manifest("alpha", keywords=["portable", "words"])
        )
        self.assertEqual(self.generate()["plugins"][0]["keywords"], ["portable", "words"])

    def test_keywords_fall_back_to_the_claude_manifest(self) -> None:
        """Which is where the catalog actually keeps them today."""
        self.write_catalog()
        self.add_package("alpha")
        self.assertEqual(self.generate()["plugins"][0]["keywords"], ["alpha", "example"])

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
