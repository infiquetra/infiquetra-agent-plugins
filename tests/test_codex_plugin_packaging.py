"""Every package Codex installs must stay installable, and stay portable.

Codex CLI 0.155.1 resolves a marketplace from ``.agents/plugins/marketplace.json``
at the repository root, and a plugin from ``.codex-plugin/plugin.json`` at the
root of the directory a marketplace entry's ``source.path`` names. The CLI
offers no other location for either file. Those two facts decide the layout,
and neither is visible from the files themselves, so they are pinned here.

The manifest outside the adapter is allowed only because the CLI looks
nowhere else, and only while it carries paths. ``skills`` points at the
portable ``skills/`` directory. A path into ``com.infiquetra.codex/`` appears
only when that adapter exists. ``hooks`` and ``interface.defaultPrompt`` are
behaviour, and this module fails if either is written down.

A ``.claude-plugin/`` sibling is allowed. The CLI accepted a plugin directory
that contained one, and an installed ``google-cloud-developer`` contains both.
The subject is derived: every ``plugins/*/`` with a portable ``plugin.json``
is checked, and the marketplace must list exactly that set.

Standard library only, matching the rest of this suite.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_codex_packaging as sync  # noqa: E402


PLUGINS = ROOT / "plugins"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
CODEX_MANIFEST_RELATIVE = Path(".codex-plugin") / "plugin.json"
PORTABLE_MANIFEST_RELATIVE = Path("plugin.json")
ADAPTER_NAME = "com.infiquetra.codex"
PORTABLE_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

#: Directories that would be vendor behaviour if they sat at the package root.
#: ``skills/`` is the portable surface and is allowed there.
BEHAVIOUR_DIRS = ("hooks", "agents", "commands", "output-styles")

#: Manifest keys whose value is a path. Anything else that is an object is
#: either ``author`` or ``interface``, and those are metadata.
PATH_KEYS = ("skills", "mcpServers")
METADATA_OBJECTS = {"author", "interface"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def codex_packages() -> list[Path]:
    """Every package root Codex can install, derived from the tree."""
    if not PLUGINS.is_dir():
        return []
    return sorted(
        path
        for path in PLUGINS.iterdir()
        if path.is_dir() and (path / PORTABLE_MANIFEST_RELATIVE).is_file()
    )


def marketplace_entries() -> dict[str, dict]:
    return {
        entry.get("name"): entry
        for entry in _load(MARKETPLACE).get("plugins", [])
        if isinstance(entry, dict)
    }


class SubjectTests(unittest.TestCase):
    """The derived subject must not be empty, or every rule below is vacuous."""

    def test_at_least_one_package_is_codex_installable(self) -> None:
        self.assertTrue(
            codex_packages(),
            "no plugins/*/ carries plugin.json, so every rule in this module "
            "passes by having nothing to check",
        )

    def test_at_least_one_package_keeps_its_claude_manifest_beside_the_codex_one(self) -> None:
        """A package that ships both manifests keeps both. The CLI accepted that layout."""
        both = [
            package
            for package in codex_packages()
            if (package / ".claude-plugin" / "plugin.json").is_file()
            and (package / CODEX_MANIFEST_RELATIVE).is_file()
        ]
        self.assertTrue(both)


class CodexManifestLocationTests(unittest.TestCase):
    """Where Codex looks, and what it finds when it looks there."""

    def test_the_portable_manifest_is_preserved_beside_it(self) -> None:
        for package in codex_packages():
            with self.subTest(package=package.name):
                portable = package / PORTABLE_MANIFEST_RELATIVE
                codex = package / CODEX_MANIFEST_RELATIVE
                self.assertTrue(portable.is_file())
                self.assertTrue(codex.is_file())
                self.assertEqual(_load(portable).get("$schema"), PORTABLE_SCHEMA)

    def test_the_two_manifests_are_different_specs_not_one_copied_over(self) -> None:
        for package in codex_packages():
            with self.subTest(package=package.name):
                codex = _load(package / CODEX_MANIFEST_RELATIVE)
                portable = _load(package / PORTABLE_MANIFEST_RELATIVE)
                self.assertNotIn("$schema", codex)
                self.assertEqual(codex.get("name"), portable.get("name"))
                self.assertEqual(codex.get("version"), portable.get("version"))
                self.assertEqual(codex.get("description"), portable.get("description"))

    def test_the_manifest_name_is_the_package_directory_name(self) -> None:
        for package in codex_packages():
            with self.subTest(package=package.name):
                self.assertEqual(
                    _load(package / CODEX_MANIFEST_RELATIVE).get("name"),
                    package.name,
                )


class DeclaredPathTests(unittest.TestCase):
    """Every path the Codex manifest declares must resolve, and stay in its lane."""

    def test_every_declared_path_exists_and_stays_inside_the_package(self) -> None:
        for package in codex_packages():
            manifest = _load(package / CODEX_MANIFEST_RELATIVE)
            for key in PATH_KEYS:
                value = manifest.get(key)
                if value is None:
                    continue
                with self.subTest(package=package.name, component=key):
                    self.assertIsInstance(value, str)
                    self.assertTrue(value.startswith("./"))
                    self.assertNotIn("..", Path(value).parts)
                    self.assertTrue((package / value).exists())

    def test_skills_point_at_the_portable_core_when_it_exists(self) -> None:
        for package in codex_packages():
            manifest = _load(package / CODEX_MANIFEST_RELATIVE)
            if (package / "skills").is_dir():
                with self.subTest(package=package.name):
                    self.assertEqual(manifest.get("skills"), "./skills/")
            else:
                with self.subTest(package=package.name):
                    skills = manifest.get("skills")
                    if skills is not None:
                        self.assertTrue(str(skills).startswith(f"./{ADAPTER_NAME}/"))

    def test_an_adapter_path_stays_inside_the_adapter(self) -> None:
        for package in codex_packages():
            manifest = _load(package / CODEX_MANIFEST_RELATIVE)
            adapter = (package / ADAPTER_NAME).resolve()
            for key in PATH_KEYS:
                value = manifest.get(key)
                if not isinstance(value, str) or ADAPTER_NAME not in Path(value).parts:
                    continue
                with self.subTest(package=package.name, component=key):
                    self.assertTrue((package / value).resolve().is_relative_to(adapter))

    def test_the_manifest_carries_paths_and_no_behaviour(self) -> None:
        """The condition AGENTS.md attaches to a manifest outside its adapter."""
        for package in codex_packages():
            manifest = _load(package / CODEX_MANIFEST_RELATIVE)
            with self.subTest(package=package.name):
                self.assertNotIn("hooks", manifest)
                self.assertNotIn("commands", manifest)
                self.assertNotIn("agents", manifest)
                interface = manifest.get("interface")
                self.assertIsInstance(interface, dict)
                self.assertNotIn("defaultPrompt", interface)
                self.assertNotIn("default_prompt", interface)
                for key, value in manifest.items():
                    if isinstance(value, dict):
                        self.assertIn(key, METADATA_OBJECTS)
                    if isinstance(value, str):
                        self.assertNotIn("${", value)

    def test_no_codex_behaviour_directory_sits_at_the_portable_root(self) -> None:
        for package in codex_packages():
            for name in BEHAVIOUR_DIRS:
                with self.subTest(package=package.name, directory=name):
                    self.assertFalse(
                        (package / name).exists(),
                        f"plugins/{package.name}/{name}/ is Codex behaviour and "
                        f"belongs under {ADAPTER_NAME}/",
                    )


class MarketplaceTests(unittest.TestCase):
    """The marketplace is how these packages are installed from this repository."""

    def test_the_marketplace_sits_where_codex_looks(self) -> None:
        self.assertTrue(MARKETPLACE.is_file())
        payload = _load(MARKETPLACE)
        self.assertEqual(payload.get("name"), "infiquetra-agent-plugins")
        interface = payload.get("interface")
        self.assertIsInstance(interface, dict)
        self.assertTrue(interface.get("displayName"))
        self.assertNotIn("defaultPrompt", interface)

    def test_the_committed_file_is_the_generated_one(self) -> None:
        self.assertEqual(sync.check_codex_packaging(ROOT), [])

    def test_each_entry_source_is_the_package_root(self) -> None:
        for name, entry in marketplace_entries().items():
            with self.subTest(package=name):
                self.assertEqual(
                    entry.get("source"),
                    {"source": "local", "path": f"./plugins/{name}"},
                )
                self.assertEqual(
                    entry.get("policy"),
                    {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                )

    def test_the_marketplace_lists_exactly_the_portable_packages(self) -> None:
        self.assertEqual(
            sorted(marketplace_entries()),
            [package.name for package in codex_packages()],
        )
