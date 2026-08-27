"""The Voice package must remain installable by the Claude CLI, and stay portable.

Claude Code resolves a plugin by looking for ``.claude-plugin/plugin.json`` at
the *root of the directory it installs*, and it installs exactly the directory a
marketplace entry's ``source`` names -- nothing above it. Those two facts
together decide this package's whole layout, and neither is visible from the
files themselves, so they are pinned here.

The bug this module exists to prevent: ``plugins/voice/com.infiquetra.claude/``
carried a ``plugin.json`` at its own root, which is where the *portable* Agent
Plugins spec puts a manifest and is not where Claude looks. ``claude plugin
validate`` answered "No manifest found in directory. Expected
.claude-plugin/marketplace.json or .claude-plugin/plugin.json" and the package
could not be installed at all.

Why the installed root is the package, not the client extension: the Stop hook
imports the portable core and spawns ``scripts/speak.py`` from it. Installing
only ``com.infiquetra.claude/`` would copy the hook without the core it calls,
so the plugin would install cleanly and then fail at the first spoken response.
Making the extension self-sufficient instead would mean duplicating the core,
which this catalog does not do. So the installed root is ``plugins/voice/`` and
the Claude manifest declares its behaviour out of the client extension by path.

That leaves two manifests side by side in the package root, deliberately:

- ``plugins/voice/plugin.json`` -- the portable Agent Plugins manifest, carrying
  the ``$schema`` that ``scripts/check_repo.py`` enforces. Vendor-neutral.
- ``plugins/voice/.claude-plugin/plugin.json`` -- Claude's own packaging
  manifest. A different spec with different fields, required by the CLI to sit
  at the installed root.

They are not duplicates and neither substitutes for the other. The Claude
manifest holds no behaviour: every component it declares is a path into
``com.infiquetra.claude/`` or into the portable surface.

Presence is asserted as well as value throughout. A check that only compared the
declarations it found could be satisfied by deleting them, which is the
"guarantee that cannot fail" shape this repository has rejected before.

Standard library only, matching the rest of this suite.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

#: The repository's Claude marketplace. Claude requires this exact location.
MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"

#: The package root Claude installs, and the two manifests that share it.
PLUGIN_ROOT = ROOT / "plugins" / "voice"
CLAUDE_MANIFEST = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
PORTABLE_MANIFEST = PLUGIN_ROOT / "plugin.json"

#: The Claude client extension. Every Claude-specific behaviour lives under it.
EXTENSION = PLUGIN_ROOT / "com.infiquetra.claude"
STOP_HOOK = EXTENSION / "hooks" / "stop_hook.py"

#: The portable Agent Plugins schema, which marks the vendor-neutral manifest.
#: ``scripts/check_repo.py`` is the authority; it is restated here only to prove
#: the two manifests are different specs rather than one copied over the other.
PORTABLE_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"

#: The plugin name both manifests and the marketplace entry must agree on.
PLUGIN_NAME = "voice"

#: Directories Claude scans by convention at a plugin root. None may appear at
#: the portable package root: Claude-specific material belongs in the extension,
#: and anything found here would be loaded as portable core by every other
#: vendor adapter that reads this package.
CLAUDE_CONVENTION_DIRS = ("hooks", "agents", "commands")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _marketplace_entry() -> dict:
    for entry in _load(MARKETPLACE).get("plugins", []):
        if entry.get("name") == PLUGIN_NAME:
            return entry
    raise AssertionError(f"no {PLUGIN_NAME!r} entry in {MARKETPLACE.relative_to(ROOT)}")


class ClaudeManifestLocationTests(unittest.TestCase):
    """Where Claude looks, and what it finds when it looks there."""

    def test_the_installable_root_carries_a_manifest_where_claude_looks(self) -> None:
        # The exact regression: a manifest anywhere else reads to the CLI as no
        # manifest at all, and the package cannot be installed.
        self.assertTrue(
            CLAUDE_MANIFEST.is_file(),
            f"{CLAUDE_MANIFEST.relative_to(ROOT)} is missing; `claude plugin "
            "validate` reports 'No manifest found in directory'",
        )

    def test_the_portable_manifest_is_preserved_beside_it(self) -> None:
        self.assertTrue(PORTABLE_MANIFEST.is_file())
        self.assertEqual(_load(PORTABLE_MANIFEST).get("$schema"), PORTABLE_SCHEMA)

    def test_the_two_manifests_are_different_specs_not_one_copied_over(self) -> None:
        claude = _load(CLAUDE_MANIFEST)
        self.assertNotIn(
            "$schema",
            claude,
            "the Claude manifest must not carry the portable Agent Plugins "
            "schema: they are different specifications",
        )
        self.assertEqual(claude.get("name"), _load(PORTABLE_MANIFEST).get("name"))

    def test_the_client_extension_keeps_its_own_portable_manifest(self) -> None:
        # The extension stays a described package in the portable catalog. What
        # changed is only that Claude installs the package root above it.
        self.assertTrue((EXTENSION / "plugin.json").is_file())


class DeclaredComponentPathTests(unittest.TestCase):
    """Every path the Claude manifest declares must resolve, and stay in its lane."""

    def test_every_declared_component_path_exists(self) -> None:
        manifest = _load(CLAUDE_MANIFEST)
        declared = {
            key: value
            for key, value in manifest.items()
            if key in ("hooks", "skills", "agents", "commands", "mcpServers")
            and isinstance(value, str)
        }
        self.assertTrue(declared, "the Claude manifest declares no component paths")
        for key, value in declared.items():
            with self.subTest(component=key):
                self.assertTrue(
                    value.startswith("./"),
                    f"{key} path {value!r} must be relative to the plugin root",
                )
                self.assertFalse(
                    ".." in Path(value).parts,
                    f"{key} path {value!r} escapes the installed root, which is "
                    "the only thing the install copies",
                )
                self.assertTrue(
                    (PLUGIN_ROOT / value).exists(),
                    f"{key} path {value!r} does not resolve under "
                    f"{PLUGIN_ROOT.relative_to(ROOT)}",
                )

    def test_the_hooks_declaration_points_into_the_client_extension(self) -> None:
        hooks = _load(CLAUDE_MANIFEST).get("hooks")
        self.assertIsInstance(hooks, str, "the hooks path must be declared")
        resolved = (PLUGIN_ROOT / hooks).resolve()
        self.assertTrue(
            resolved.is_relative_to(EXTENSION.resolve()),
            f"hooks path {hooks!r} must live under "
            f"{EXTENSION.relative_to(ROOT)}; Claude-specific behaviour does not "
            "belong in the portable core",
        )

    def test_the_mcp_servers_declaration_points_into_the_client_extension(self) -> None:
        mcp_servers = _load(CLAUDE_MANIFEST).get("mcpServers")
        self.assertIsInstance(mcp_servers, str, "the mcpServers path must be declared")
        resolved = (PLUGIN_ROOT / mcp_servers).resolve()
        self.assertTrue(
            resolved.is_relative_to(EXTENSION.resolve()),
            f"mcpServers path {mcp_servers!r} must live under "
            f"{EXTENSION.relative_to(ROOT)}; Claude-specific behaviour does not "
            "belong in the portable core",
        )

    def test_no_claude_convention_directory_sits_at_the_portable_root(self) -> None:
        for name in CLAUDE_CONVENTION_DIRS:
            with self.subTest(directory=name):
                self.assertFalse(
                    (PLUGIN_ROOT / name).exists(),
                    f"plugins/voice/{name}/ would be read as portable core by "
                    "every other vendor adapter; it belongs in the extension",
                )


class HookRuntimePathTests(unittest.TestCase):
    """The two path resolutions that only break after a successful install."""

    def test_the_hook_command_resolves_from_the_installed_plugin_root(self) -> None:
        # ``${CLAUDE_PLUGIN_ROOT}`` expands to the installed package root. A
        # stale command path here installs and validates cleanly, then fails at
        # the first spoken response with nothing pointing back to this file.
        hooks_file = PLUGIN_ROOT / _load(CLAUDE_MANIFEST)["hooks"]
        entries = _load(hooks_file)["hooks"]
        commands = [
            hook["command"]
            for matchers in entries.values()
            for matcher in matchers
            for hook in matcher["hooks"]
            if hook.get("type") == "command"
        ]
        self.assertTrue(commands, "the hooks descriptor declares no command")
        for command in commands:
            with self.subTest(command=command):
                self.assertIn("${CLAUDE_PLUGIN_ROOT}", command)
                for token in command.split('"'):
                    if "${CLAUDE_PLUGIN_ROOT}" not in token:
                        continue
                    relative = token.split("${CLAUDE_PLUGIN_ROOT}", 1)[1].lstrip("/")
                    self.assertTrue(
                        (PLUGIN_ROOT / relative).is_file(),
                        f"{relative} does not exist under the installed root",
                    )

    def test_the_stop_hook_finds_the_portable_core_inside_the_installed_root(
        self,
    ) -> None:
        # The hook reaches the core with ``parents[2]``. That resolution must
        # land inside the directory the install copies, or the core is simply
        # absent at runtime -- which is what installing only the extension would
        # have produced.
        self.assertTrue(STOP_HOOK.is_file())
        core = STOP_HOOK.resolve().parents[2] / "scripts"
        self.assertEqual(
            core.parent,
            PLUGIN_ROOT.resolve(),
            "the hook resolves the portable core outside the installed root",
        )
        self.assertTrue((core / "speak.py").is_file())


class MCPRuntimePathTests(unittest.TestCase):
    """The MCP server declaration paths and command resolution."""

    def test_the_mcp_server_command_resolves_from_the_installed_plugin_root(
        self,
    ) -> None:
        # ``${CLAUDE_PLUGIN_ROOT}`` expands to the installed package root.
        # The declared command and args must be byte-for-byte the literals
        # U3's executable-entrypoint scenario launches so declaration and proof
        # cannot drift apart.
        mcp_file = PLUGIN_ROOT / _load(CLAUDE_MANIFEST)["mcpServers"]
        self.assertTrue(mcp_file.is_file(), f"{mcp_file} is missing")
        servers = _load(mcp_file)
        self.assertTrue(servers, "the mcpServers descriptor declares no server")
        for name, config in servers.items():
            with self.subTest(server=name):
                command = config.get("command")
                self.assertEqual(command, "python3")
                args = config.get("args")
                self.assertIsInstance(args, list)
                self.assertEqual(args, ["${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py"])
                for arg in args:
                    self.assertIn("${CLAUDE_PLUGIN_ROOT}", arg)
                    relative = arg.split("${CLAUDE_PLUGIN_ROOT}", 1)[1].lstrip("/")
                    self.assertTrue(
                        (PLUGIN_ROOT / relative).is_file(),
                        f"{relative} does not exist under the installed root",
                    )


class MarketplaceEntryTests(unittest.TestCase):
    """The marketplace is how Voice is installed from this repository."""

    def test_the_marketplace_sits_where_claude_looks_and_names_an_owner(self) -> None:
        self.assertTrue(MARKETPLACE.is_file())
        payload = _load(MARKETPLACE)
        self.assertTrue(payload.get("name"))
        self.assertIsInstance(payload.get("owner"), dict)
        # `--strict` treats a missing marketplace description as an error, and
        # continuous integration runs strict.
        self.assertTrue(payload.get("metadata", {}).get("description"))

    def test_the_entry_source_is_the_package_root_not_the_extension(self) -> None:
        source = _marketplace_entry().get("source")
        self.assertIsInstance(source, str)
        resolved = (ROOT / source).resolve()
        self.assertEqual(
            resolved,
            PLUGIN_ROOT.resolve(),
            "source must name the package root: Claude copies exactly this "
            "directory, and the extension alone would arrive without the core",
        )
        self.assertTrue((resolved / ".claude-plugin" / "plugin.json").is_file())

    def test_the_entry_and_the_plugin_manifest_agree(self) -> None:
        # `claude plugin tag` refuses to tag a release whose manifest and
        # enclosing marketplace entry disagree, so the agreement is contract.
        entry = _marketplace_entry()
        manifest = _load(CLAUDE_MANIFEST)
        for field in ("name", "version"):
            with self.subTest(field=field):
                self.assertEqual(entry.get(field), manifest.get(field))

    def test_the_entry_version_matches_the_portable_manifest_too(self) -> None:
        self.assertEqual(
            _marketplace_entry().get("version"),
            _load(PORTABLE_MANIFEST).get("version"),
        )

    def test_all_four_version_sites_agree(self) -> None:
        # A content change that does not bump the version never reaches an
        # installed plugin: `claude plugin update` compares versions, not
        # commits, and answers "already at the latest version" while the cache
        # still holds the old bytes. So a release means editing four files, and
        # four hand-edited copies of one number is exactly the shape that
        # drifts. Presence is asserted too: a site that lost its version would
        # otherwise pass by being absent.
        sites = {
            "marketplace entry": _marketplace_entry().get("version"),
            "claude manifest": _load(CLAUDE_MANIFEST).get("version"),
            "portable manifest": _load(PORTABLE_MANIFEST).get("version"),
            "client extension manifest": _load(EXTENSION / "plugin.json").get("version"),
        }
        for name, value in sites.items():
            with self.subTest(site=name):
                self.assertIsInstance(value, str, f"{name} states no version")
                self.assertTrue(value.strip())
        self.assertEqual(
            len(set(sites.values())),
            1,
            f"version sites disagree: {sites}",
        )
        self.assertEqual(
            list(sites.values())[0],
            "0.3.0",
            f"version must be 0.3.0, got {sites}",
        )


if __name__ == "__main__":
    unittest.main()
