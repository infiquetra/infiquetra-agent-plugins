"""Every package the Claude CLI installs must stay installable, and stay portable.

Claude Code resolves a plugin by looking for ``.claude-plugin/plugin.json`` at
the *root of the directory it installs*, and it installs exactly the directory a
marketplace entry's ``source`` names -- nothing above it. Those two facts
together decide the layout of every package here, and neither is visible from
the files themselves, so they are pinned in this module.

The bug this module exists to prevent: ``plugins/voice/com.infiquetra.claude/``
carried a ``plugin.json`` at its own root, which is where the *portable* Agent
Plugins spec puts a manifest and is not where Claude looks. ``claude plugin
validate`` answered "No manifest found in directory. Expected
.claude-plugin/marketplace.json or .claude-plugin/plugin.json" and the package
could not be installed at all.

Why the installed root is the package, not the client extension: a hook under
the extension imports the portable core and spawns scripts from it. Installing
only ``com.infiquetra.claude/`` would copy the hook without the core it calls,
so the plugin would install cleanly and then fail at the first invocation.
Making the extension self-sufficient instead would mean duplicating the core,
which this catalog does not do. So the installed root is ``plugins/<package>/``
and the Claude manifest declares its behaviour out of the client extension by
path.

That leaves two manifests side by side in each package root, deliberately:

- ``plugins/<package>/plugin.json`` -- the portable Agent Plugins manifest,
  carrying the ``$schema`` that ``scripts/check_repo.py`` enforces.
  Vendor-neutral.
- ``plugins/<package>/.claude-plugin/plugin.json`` -- Claude's own packaging
  manifest. A different spec with different fields, required by the CLI to sit
  at the installed root.

They are not duplicates and neither substitutes for the other. The Claude
manifest holds no behaviour: every component it declares is a path into
``com.infiquetra.claude/`` or into the portable surface.

**The subject is derived, not listed.** Every ``plugins/*/`` that carries a root
Claude manifest is checked, and the marketplace is required to list exactly that
set. Before the 2026-09-22 custody decision this module named ``voice`` in a
constant, which meant a second Claude-installable package could land with none of
these rules applied to it. Deriving the subject is what makes each import unit's
package arrive already covered.

Presence is asserted as well as value throughout. A check that only compared the
declarations it found could be satisfied by deleting them, which is the
"guarantee that cannot fail" shape this repository has rejected before.

Standard library only, matching the rest of this suite.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

#: The repository's Claude marketplace. Claude requires this exact location.
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"

PLUGINS = ROOT / "plugins"

#: Claude's own manifest, at the root of whatever directory it installs.
CLAUDE_MANIFEST_RELATIVE = Path(".claude-plugin") / "plugin.json"

#: The portable Agent Plugins manifest that sits beside it.
PORTABLE_MANIFEST_RELATIVE = Path("plugin.json")

#: The client extension directory. Every Claude-specific behaviour lives here.
EXTENSION_NAME = "com.infiquetra.claude"

#: The portable Agent Plugins schema, which marks the vendor-neutral manifest.
#: ``scripts/check_repo.py`` is the authority; it is restated here only to prove
#: the two manifests are different specs rather than one copied over the other.
PORTABLE_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

#: Directories Claude scans by convention at a plugin root. None may appear at
#: a portable package root: Claude-specific material belongs in the extension,
#: and anything found here would be loaded as portable core by every other
#: vendor adapter that reads the package.
CLAUDE_CONVENTION_DIRS = ("hooks", "agents", "commands", "output-styles")

#: The manifest keys whose value is a path into the package.
COMPONENT_KEYS = ("hooks", "skills", "agents", "commands", "mcpServers", "outputStyles")

#: The component keys that must resolve inside the client extension. A portable
#: surface may be declared too (``skills``), which is why this is a subset.
EXTENSION_ONLY_KEYS = ("hooks", "agents", "commands", "mcpServers", "outputStyles")

#: Expands to the installed package root at runtime.
PLUGIN_ROOT_TOKEN = "${CLAUDE_PLUGIN_ROOT}"

SERVER_INFO_VERSION = re.compile(r'"serverInfo":\s*\{[^}]*"version":\s*"([^"]+)"')


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def claude_packages() -> list[Path]:
    """Every package root the Claude CLI can install, derived from the tree.

    A package is Claude-installable exactly when it carries the manifest at the
    path the CLI looks for. Nothing else decides it, so nothing else is asked.
    """
    if not PLUGINS.is_dir():
        return []
    return sorted(
        path
        for path in PLUGINS.iterdir()
        if path.is_dir() and (path / CLAUDE_MANIFEST_RELATIVE).is_file()
    )


def marketplace_entries() -> dict[str, dict]:
    return {
        entry.get("name"): entry
        for entry in _load(MARKETPLACE).get("plugins", [])
        if isinstance(entry, dict)
    }


def _plugin_root_paths(text: str) -> list[str]:
    """Every package-relative path a ``${CLAUDE_PLUGIN_ROOT}`` reference names."""
    paths = []
    for token in re.split(r'["\s,\]]', text):
        if PLUGIN_ROOT_TOKEN in token:
            paths.append(token.split(PLUGIN_ROOT_TOKEN, 1)[1].lstrip("/"))
    return [path for path in paths if path]


def _mcp_server_versions(package: Path, manifest: dict) -> dict[str, str]:
    """The ``serverInfo.version`` each declared MCP server script states.

    Derived rather than listed: a package that ships no MCP server contributes
    no version site, and one that does has that site checked without this module
    naming its script.
    """
    declared = manifest.get("mcpServers")
    if not isinstance(declared, str):
        return {}
    descriptor = package / declared
    if not descriptor.is_file():
        return {}
    versions: dict[str, str] = {}
    for name, config in _load(descriptor).items():
        for relative in _plugin_root_paths(json.dumps(config)):
            script = package / relative
            if not script.is_file():
                continue
            match = SERVER_INFO_VERSION.search(script.read_text(encoding="utf-8"))
            if match:
                versions[f"mcp server {name} serverInfo"] = match.group(1)
    return versions


def version_sites(package: Path) -> dict[str, str | None]:
    """Every file that states this package's version, and what it states.

    The set is per package rather than a fixed five. Voice has five because it
    ships an MCP server whose ``serverInfo`` repeats the number; a package with
    no extension manifest and no MCP server has three. What matters is that
    every site a package *has* agrees, and that a site cannot pass by being
    absent -- so a value of ``None`` here is a failure, not a skip.
    """
    claude_manifest = _load(package / CLAUDE_MANIFEST_RELATIVE)
    sites: dict[str, str | None] = {
        "claude manifest": claude_manifest.get("version"),
        "portable manifest": _load(package / PORTABLE_MANIFEST_RELATIVE).get("version"),
    }
    entry = marketplace_entries().get(package.name)
    if entry is not None:
        sites["marketplace entry"] = entry.get("version")
    extension_manifest = package / EXTENSION_NAME / "plugin.json"
    if extension_manifest.is_file():
        sites["client extension manifest"] = _load(extension_manifest).get("version")
    sites.update(_mcp_server_versions(package, claude_manifest))
    return sites


class SubjectTests(unittest.TestCase):
    """The derived subject must not be empty, or every rule below is vacuous."""

    def test_at_least_one_package_is_claude_installable(self) -> None:
        self.assertTrue(
            claude_packages(),
            "no plugins/*/ carries .claude-plugin/plugin.json, so every rule in "
            "this module passes by having nothing to check",
        )


class ClaudeManifestLocationTests(unittest.TestCase):
    """Where Claude looks, and what it finds when it looks there."""

    def test_the_portable_manifest_is_preserved_beside_it(self) -> None:
        for package in claude_packages():
            with self.subTest(package=package.name):
                portable = package / PORTABLE_MANIFEST_RELATIVE
                self.assertTrue(portable.is_file())
                self.assertEqual(_load(portable).get("$schema"), PORTABLE_SCHEMA)

    def test_the_two_manifests_are_different_specs_not_one_copied_over(self) -> None:
        for package in claude_packages():
            with self.subTest(package=package.name):
                claude = _load(package / CLAUDE_MANIFEST_RELATIVE)
                self.assertNotIn(
                    "$schema",
                    claude,
                    "the Claude manifest must not carry the portable Agent Plugins "
                    "schema: they are different specifications",
                )
                self.assertEqual(
                    claude.get("name"),
                    _load(package / PORTABLE_MANIFEST_RELATIVE).get("name"),
                )

    def test_the_manifest_name_is_the_package_directory_name(self) -> None:
        for package in claude_packages():
            with self.subTest(package=package.name):
                self.assertEqual(_load(package / CLAUDE_MANIFEST_RELATIVE).get("name"), package.name)

    def test_the_client_extension_keeps_its_own_portable_manifest(self) -> None:
        # The extension stays a described package in the portable catalog. What
        # changed is only that Claude installs the package root above it. A
        # package with no extension directory has nothing to describe.
        for package in claude_packages():
            extension = package / EXTENSION_NAME
            if not extension.is_dir():
                continue
            with self.subTest(package=package.name):
                self.assertTrue((extension / "plugin.json").is_file())


class DeclaredComponentPathTests(unittest.TestCase):
    """Every path the Claude manifest declares must resolve, and stay in its lane."""

    def test_every_declared_component_path_exists(self) -> None:
        for package in claude_packages():
            manifest = _load(package / CLAUDE_MANIFEST_RELATIVE)
            declared = {
                key: value
                for key, value in manifest.items()
                if key in COMPONENT_KEYS and isinstance(value, str)
            }
            with self.subTest(package=package.name):
                self.assertTrue(declared, "the Claude manifest declares no component paths")
            for key, value in declared.items():
                with self.subTest(package=package.name, component=key):
                    self.assertTrue(
                        value.startswith("./"),
                        f"{key} path {value!r} must be relative to the plugin root",
                    )
                    self.assertNotIn(
                        "..",
                        Path(value).parts,
                        f"{key} path {value!r} escapes the installed root, which is "
                        "the only thing the install copies",
                    )
                    self.assertTrue(
                        (package / value).exists(),
                        f"{key} path {value!r} does not resolve under "
                        f"{package.relative_to(ROOT)}",
                    )

    def test_claude_only_declarations_point_into_the_client_extension(self) -> None:
        for package in claude_packages():
            manifest = _load(package / CLAUDE_MANIFEST_RELATIVE)
            extension = (package / EXTENSION_NAME).resolve()
            for key in EXTENSION_ONLY_KEYS:
                value = manifest.get(key)
                if not isinstance(value, str):
                    continue
                with self.subTest(package=package.name, component=key):
                    self.assertTrue(
                        (package / value).resolve().is_relative_to(extension),
                        f"{key} path {value!r} must live under {EXTENSION_NAME}; "
                        "Claude-specific behaviour does not belong in the portable core",
                    )

    def test_the_claude_manifest_carries_paths_and_no_behaviour(self) -> None:
        """The condition AGENTS.md attaches to a manifest outside its adapter."""
        for package in claude_packages():
            with self.subTest(package=package.name):
                for value in _load(package / CLAUDE_MANIFEST_RELATIVE).values():
                    if isinstance(value, str):
                        self.assertNotIn(PLUGIN_ROOT_TOKEN, value)

    def test_no_claude_convention_directory_sits_at_the_portable_root(self) -> None:
        for package in claude_packages():
            for name in CLAUDE_CONVENTION_DIRS:
                with self.subTest(package=package.name, directory=name):
                    self.assertFalse(
                        (package / name).exists(),
                        f"plugins/{package.name}/{name}/ would be read as portable core "
                        "by every other vendor adapter; it belongs in the extension",
                    )


class HookRuntimePathTests(unittest.TestCase):
    """The path resolutions that only break after a successful install."""

    def _hook_commands(self, package: Path) -> list[str]:
        declared = _load(package / CLAUDE_MANIFEST_RELATIVE).get("hooks")
        if not isinstance(declared, str):
            return []
        entries = _load(package / declared).get("hooks", {})
        return [
            hook["command"]
            for matchers in entries.values()
            for matcher in matchers
            for hook in matcher["hooks"]
            if hook.get("type") == "command"
        ]

    def test_the_hook_command_resolves_from_the_installed_plugin_root(self) -> None:
        # ``${CLAUDE_PLUGIN_ROOT}`` expands to the installed package root. A
        # stale command path here installs and validates cleanly, then fails at
        # the first invocation with nothing pointing back to this file.
        for package in claude_packages():
            commands = self._hook_commands(package)
            if not commands:
                continue
            for command in commands:
                with self.subTest(package=package.name, command=command):
                    self.assertIn(PLUGIN_ROOT_TOKEN, command)
                    for relative in _plugin_root_paths(command):
                        self.assertTrue(
                            (package / relative).is_file(),
                            f"{relative} does not exist under the installed root",
                        )

    def test_a_hook_script_reaches_the_core_inside_the_installed_root(self) -> None:
        # A hook under ``com.infiquetra.claude/hooks/`` reaches the portable core
        # with ``parents[2]``. That resolution must land inside the directory the
        # install copies, or the core is simply absent at runtime -- which is what
        # installing only the extension would have produced. Pinning the depth is
        # what keeps the resolution true after a hook is moved.
        for package in claude_packages():
            hooks = package / EXTENSION_NAME / "hooks"
            if not hooks.is_dir():
                continue
            for script in sorted(hooks.glob("*.py")):
                with self.subTest(package=package.name, hook=script.name):
                    self.assertEqual(
                        script.resolve().parents[2],
                        package.resolve(),
                        "the hook does not sit two directories below the installed "
                        "root, so a parents[2] resolution of the core leaves it",
                    )

    def test_a_hook_that_spawns_the_core_finds_what_it_spawns(self) -> None:
        for package in claude_packages():
            hooks = package / EXTENSION_NAME / "hooks"
            if not hooks.is_dir():
                continue
            for script in sorted(hooks.glob("*.py")):
                for relative in _plugin_root_paths(script.read_text(encoding="utf-8")):
                    with self.subTest(package=package.name, hook=script.name, path=relative):
                        self.assertTrue(
                            (package / relative).exists(),
                            f"{relative} does not exist under the installed root",
                        )


class MCPRuntimePathTests(unittest.TestCase):
    """The MCP server declaration paths and command resolution."""

    def test_the_mcp_server_command_resolves_from_the_installed_plugin_root(self) -> None:
        # ``${CLAUDE_PLUGIN_ROOT}`` expands to the installed package root. The
        # declared command and args must name files the install actually copies,
        # so declaration and proof cannot drift apart.
        for package in claude_packages():
            declared = _load(package / CLAUDE_MANIFEST_RELATIVE).get("mcpServers")
            if not isinstance(declared, str):
                continue
            descriptor = package / declared
            with self.subTest(package=package.name):
                self.assertTrue(descriptor.is_file(), f"{descriptor} is missing")
                servers = _load(descriptor)
                self.assertTrue(servers, "the mcpServers descriptor declares no server")
            for name, config in _load(descriptor).items():
                with self.subTest(package=package.name, server=name):
                    command = config.get("command")
                    self.assertIsInstance(command, str)
                    self.assertTrue(command.strip())
                    args = config.get("args")
                    self.assertIsInstance(args, list)
                    referenced = _plugin_root_paths(json.dumps(args))
                    self.assertTrue(
                        referenced,
                        f"no argument of {name!r} resolves from the installed root, so "
                        "the server would be launched from wherever the client happened "
                        "to be",
                    )
                    for relative in referenced:
                        self.assertTrue(
                            (package / relative).is_file(),
                            f"{relative} does not exist under the installed root",
                        )


class MarketplaceTests(unittest.TestCase):
    """The marketplace is how these packages are installed from this repository."""

    def test_the_marketplace_sits_where_claude_looks_and_names_an_owner(self) -> None:
        self.assertTrue(MARKETPLACE.is_file())
        payload = _load(MARKETPLACE)
        self.assertTrue(payload.get("name"))
        self.assertIsInstance(payload.get("owner"), dict)
        # `--strict` treats a missing marketplace description as an error, and
        # continuous integration runs strict.
        self.assertTrue(payload.get("metadata", {}).get("description"))

    def test_it_lists_exactly_the_packages_that_carry_a_claude_manifest(self) -> None:
        """Both directions, because each failure is its own bug.

        An unlisted package is one nobody can install from this repository. A
        listed package with no root manifest is an entry whose install ends in
        "No manifest found in directory".
        """
        self.assertEqual(
            set(marketplace_entries()),
            {package.name for package in claude_packages()},
        )

    def test_each_entry_source_is_the_package_root_not_the_extension(self) -> None:
        for name, entry in marketplace_entries().items():
            with self.subTest(package=name):
                source = entry.get("source")
                self.assertIsInstance(source, str)
                resolved = (ROOT / source).resolve()
                self.assertEqual(
                    resolved,
                    (PLUGINS / name).resolve(),
                    "source must name the package root: Claude copies exactly this "
                    "directory, and the extension alone would arrive without the core",
                )
                self.assertTrue((resolved / CLAUDE_MANIFEST_RELATIVE).is_file())

    def test_each_entry_and_its_plugin_manifest_agree(self) -> None:
        # `claude plugin tag` refuses to tag a release whose manifest and
        # enclosing marketplace entry disagree, so the agreement is contract.
        for name, entry in marketplace_entries().items():
            manifest = _load(PLUGINS / name / CLAUDE_MANIFEST_RELATIVE)
            for field in ("name", "version"):
                with self.subTest(package=name, field=field):
                    self.assertEqual(entry.get(field), manifest.get(field))


class VersionAgreementTests(unittest.TestCase):
    """Every file that states a package's version states the same one."""

    def test_every_version_site_agrees_within_a_package(self) -> None:
        # A content change that does not bump the version never reaches an
        # installed plugin: `claude plugin update` compares versions, not
        # commits, and answers "already at the latest version" while the cache
        # still holds the old bytes. So a release means editing several files,
        # and several hand-edited copies of one number is exactly the shape that
        # drifts. Presence is asserted too: a site that lost its version would
        # otherwise pass by being absent.
        #
        # The number itself is derived from the package rather than written
        # here. A literal would have to be edited by every release, which makes
        # this test a second site that can drift from the five it is checking.
        for package in claude_packages():
            sites = version_sites(package)
            for name, value in sites.items():
                with self.subTest(package=package.name, site=name):
                    self.assertIsInstance(value, str, f"{name} states no version")
                    assert isinstance(value, str)
                    self.assertTrue(value.strip())
            with self.subTest(package=package.name):
                self.assertEqual(len(set(sites.values())), 1, f"version sites disagree: {sites}")

    def test_the_manifest_sites_are_always_among_them(self) -> None:
        """A package cannot agree with itself by having only one site."""
        for package in claude_packages():
            with self.subTest(package=package.name):
                sites = version_sites(package)
                self.assertIn("claude manifest", sites)
                self.assertIn("portable manifest", sites)
                self.assertIn("marketplace entry", sites)


if __name__ == "__main__":
    unittest.main()
