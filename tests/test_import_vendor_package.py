"""Tests for the one-shot import of a Claude Code plugin into the portable layout.

Every test builds its own upstream: a real git repository in a temporary
directory, holding a synthetic package with inert example values, committed so
the import reads it exactly as it reads the real one -- through
`git show <commit>:<path>`. A fixture that handed the importer a working tree
would not exercise the property the importer exists to have, which is that the
upstream checkout's current state cannot change what lands here.

Expectations derive from the module rather than restating it: the surface table,
the exclusion lists, and the classification class names are read from
`import_vendor_package`, so a surface added without a test covering it fails
here instead of passing silently.

Standard library only, matching the repository baseline.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import import_vendor_package as ivp  # noqa: E402
import sync_vendor_source as svs  # noqa: E402


PACKAGE = "example"

#: The upstream manifest every fixture starts from. Inert throughout: a package
#: name that ships nowhere, an example.com author, and no credential-shaped
#: value, per the repository's publication rules.
UPSTREAM_MANIFEST = {
    "name": PACKAGE,
    "version": "1.2.3",
    "description": "An example package used only by this test.",
    "author": {"name": "Example", "email": "nobody@example.com"},
    "repository": "https://example.com/upstream",
    "keywords": ["example"],
}

#: A skill document whose frontmatter carries the one top-level key the
#: `normalize-skill-frontmatter` rule folds under `metadata`.
SKILL_WITH_WHEN_TO_USE = """---
name: example
description: An example skill.
when_to_use: When the example is needed.
---

# Example
"""

#: The exact upstream shape `resolve-bundled-fleet-module` matches: the client's
#: own directory inserted on `sys.path`, the shim imported, and one module
#: loaded through it.
CLIENT_WITH_SHIM = '''#!/usr/bin/env python3
"""An example client."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fleet_commons_shim

_retry = fleet_commons_shim.load("retry_backoff")


def main() -> int:
    return 0
'''

#: A shim use inside a function, which none of the three rules matches. Carried
#: unchanged and reported, never guessed at.
CLIENT_WITH_UNMATCHED_SHIM = '''#!/usr/bin/env python3
"""An example client that loads lazily."""


def _late():
    import fleet_commons_shim

    return fleet_commons_shim.load("tier_palette")
'''

HOOKS_DESCRIPTOR = {
    "hooks": {
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/hooks/stop_hook.py"',
                        "timeout": 5,
                    }
                ]
            }
        ]
    }
}

MCP_SERVERS = {
    "example": {
        "command": "python3",
        "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/mcp_server.py"],
    }
}


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2) + "\n"


class Upstream:
    """A synthetic upstream repository, committed, with one package in it."""

    def __init__(self, directory: Path) -> None:
        self.path = directory
        self.commit = ""

    def build(self, files: dict[str, str]) -> str:
        """Write `files` under `plugins/<PACKAGE>/`, commit, return the commit."""
        for relative, content in files.items():
            target = self.path / "plugins" / PACKAGE / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        self._git("init", "-q", "-b", "main")
        self._git("config", "user.email", "nobody@example.com")
        self._git("config", "user.name", "Example")
        self._git("add", "-A", "-f")
        self._git("commit", "-q", "-m", "example")
        self.commit = self._git("rev-parse", "HEAD").strip()
        return self.commit

    def _git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", "-C", str(self.path), *arguments],
            capture_output=True,
            check=True,
            text=True,
        )
        return completed.stdout


def minimal_files(**extra: str) -> dict[str, str]:
    """The smallest upstream package, with any extra path added."""
    files = {
        ".claude-plugin/plugin.json": _json(UPSTREAM_MANIFEST),
        "README.md": "# Example\n",
    }
    files.update(extra)
    return files


class ImportCase(unittest.TestCase):
    """Base: one temporary upstream and one temporary destination per test."""

    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        base = Path(self._directory.name)
        self.output = ""
        self.upstream = Upstream(base / "upstream")
        (base / "upstream").mkdir()
        self.destination = base / "repository"
        self.destination.mkdir()

    def run_import(self, *flags: str) -> int:
        """Invoke the command exactly as the CLI does, into the scratch root.

        Its report is captured rather than printed: the command is deliberately
        talkative, and forty-eight copies of it would bury the suite's own
        output. `self.output` holds it for a test that asserts on it.
        """
        original = ivp.repository_root
        ivp.repository_root = lambda: self.destination  # type: ignore[assignment]
        captured = io.StringIO()
        errors = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured), contextlib.redirect_stderr(errors):
                code = ivp.main(
                    [
                        "--package",
                        PACKAGE,
                        "--source",
                        str(self.upstream.path),
                        "--commit",
                        self.upstream.commit,
                        *flags,
                    ]
                )
        finally:
            ivp.repository_root = original  # type: ignore[assignment]
        self.output = captured.getvalue() + errors.getvalue()
        return code

    def plan(self) -> list[ivp.PlannedFile]:
        return ivp.plan_import(self.upstream.path, self.upstream.commit, PACKAGE)

    @property
    def package_directory(self) -> Path:
        return self.destination / "plugins" / PACKAGE

    def read(self, relative: str) -> str:
        return (self.package_directory / relative).read_text(encoding="utf-8")

    def load(self, relative: str) -> dict:
        return json.loads(self.read(relative))

    def destinations(self) -> dict[str, ivp.PlannedFile]:
        return {entry.source: entry for entry in self.plan()}


class ClassificationTests(ImportCase):
    """Portable core keeps the root; every Claude surface moves under the adapter."""

    def test_every_declared_adapter_surface_moves_under_the_extension(self) -> None:
        """The corpus is the module's own table, so a new surface is covered."""
        files = minimal_files()
        for surface in ivp.ADAPTER_SURFACES:
            path = f"{surface.upstream}/example.md" if surface.is_directory else surface.upstream
            files[path] = "{}\n" if path.endswith(".json") else "# example\n"
        self.upstream.build(files)

        planned = self.destinations()
        for surface in ivp.ADAPTER_SURFACES:
            path = f"{surface.upstream}/example.md" if surface.is_directory else surface.upstream
            with self.subTest(surface=surface.upstream):
                entry = planned[path]
                self.assertEqual(entry.classification, ivp.CLAUDE_ADAPTER)
                assert entry.destination is not None
                self.assertTrue(
                    entry.destination.startswith(f"{ivp.CLIENT_EXTENSION_DIR}/"),
                    entry.destination,
                )

    def test_portable_core_keeps_its_place_at_the_package_root(self) -> None:
        self.upstream.build(
            minimal_files(
                **{
                    "scripts/tool.py": "print(0)\n",
                    "references/note.md": "# note\n",
                    "schemas/thing.schema.json": "{}\n",
                    "config/defaults.json": "{}\n",
                    "tests/test_tool.py": "def test_ok():\n    assert True\n",
                    "CHANGELOG.md": "# Changelog\n",
                }
            )
        )
        planned = self.destinations()
        for relative in (
            "scripts/tool.py",
            "references/note.md",
            "schemas/thing.schema.json",
            "config/defaults.json",
            "tests/test_tool.py",
            "CHANGELOG.md",
            "README.md",
        ):
            with self.subTest(path=relative):
                entry = planned[relative]
                self.assertEqual(entry.classification, ivp.PORTABLE_CORE)
                self.assertEqual(entry.destination, relative)

    def test_a_root_hooks_json_and_a_hooks_directory_land_in_one_place(self) -> None:
        """The Claude manifest's `hooks` key names a file, so both spellings agree."""
        self.upstream.build(
            minimal_files(**{"hooks/stop_hook.py": "print(0)\n", "hooks.json": _json(HOOKS_DESCRIPTOR)})
        )
        planned = self.destinations()
        self.assertEqual(
            planned["hooks.json"].destination,
            f"{ivp.CLIENT_EXTENSION_DIR}/hooks/hooks.json",
        )
        self.assertEqual(
            planned["hooks/stop_hook.py"].destination,
            f"{ivp.CLIENT_EXTENSION_DIR}/hooks/stop_hook.py",
        )

    def test_the_mcp_declaration_lands_where_voice_keeps_it(self) -> None:
        self.upstream.build(minimal_files(**{".mcp.json": _json(MCP_SERVERS)}))
        self.assertEqual(
            self.destinations()[".mcp.json"].destination,
            f"{ivp.CLIENT_EXTENSION_DIR}/mcp/servers.json",
        )

    def test_the_upstream_claude_manifest_is_relocated_by_the_shared_rule(self) -> None:
        self.upstream.build(minimal_files())
        entry = self.destinations()[ivp.CLAUDE_MANIFEST_PATH]
        self.assertEqual(entry.rule, svs.MANIFEST_TRANSFORM_NAME)
        self.assertEqual(
            entry.destination, f"{ivp.CLIENT_EXTENSION_DIR}/{ivp.CLAUDE_MANIFEST_NAME}"
        )
        assert entry.payload is not None
        self.assertEqual(json.loads(entry.payload)["name"], PACKAGE)

    def test_the_shim_source_file_is_dropped_rather_than_carried(self) -> None:
        """The portable package replaces it with the build-time bundle."""
        self.upstream.build(minimal_files(**{"scripts/fleet_commons_shim.py": "def load(n):\n    ...\n"}))
        entry = self.destinations()["scripts/fleet_commons_shim.py"]
        self.assertEqual(entry.classification, ivp.DROPPED)
        self.assertIsNone(entry.destination)


class ExclusionTests(ImportCase):
    """Checkout noise and build residue are never copied, under any class."""

    def test_every_excluded_directory_and_file_is_left_behind(self) -> None:
        """The corpus is the module's own lists, so a new exclusion is covered."""
        files = minimal_files()
        expected = []
        for name in ivp.EXCLUDED_DIRECTORY_NAMES:
            path = f"skills/example/{name}/lib/thing.txt"
            files[path] = "noise\n"
            expected.append(path)
        for name in ivp.EXCLUDED_FILE_NAMES:
            path = f"skills/example/{name}"
            files[path] = "noise\n"
            expected.append(path)
        for suffix in ivp.EXCLUDED_SUFFIXES:
            path = f"scripts/compiled{suffix}"
            files[path] = "noise\n"
            expected.append(path)
        self.upstream.build(files)

        planned = self.destinations()
        for path in expected:
            with self.subTest(path=path):
                self.assertEqual(planned[path].classification, ivp.EXCLUDED)
                self.assertIsNone(planned[path].destination)

    def test_a_vendored_virtual_environment_never_reaches_the_package(self) -> None:
        """`home-lab-ops` carries one under a skill, which is why this is here."""
        self.upstream.build(
            minimal_files(
                **{
                    "skills/example/scripts/.venv/bin/python": "binary\n",
                    "skills/example/scripts/.venv/lib/site.py": "import sys\n",
                    "skills/example/scripts/real.py": "print(0)\n",
                }
            )
        )
        self.assertEqual(self.run_import(), 0)
        self.assertFalse((self.package_directory / "skills/example/scripts/.venv").exists())
        self.assertTrue((self.package_directory / "skills/example/scripts/real.py").is_file())


class ManifestGenerationTests(ImportCase):
    """The two manifests the package root carries, and what each may say."""

    def test_the_claude_manifest_declares_only_surfaces_that_exist(self) -> None:
        self.upstream.build(minimal_files(**{"commands/run.md": "# run\n"}))
        self.assertEqual(self.run_import(), 0)
        manifest = self.load(ivp.CLAUDE_MANIFEST_PATH)
        self.assertEqual(manifest["commands"], f"./{ivp.CLIENT_EXTENSION_DIR}/commands/")
        for absent in ("agents", "hooks", "mcpServers", "outputStyles"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, manifest)

    def test_every_declared_component_path_is_relative_and_resolves(self) -> None:
        self.upstream.build(
            minimal_files(
                **{
                    "commands/run.md": "# run\n",
                    "agents/helper.md": "# helper\n",
                    "output-styles/house.md": "# house\n",
                    "hooks.json": _json(HOOKS_DESCRIPTOR),
                    "hooks/stop_hook.py": "print(0)\n",
                    ".mcp.json": _json(MCP_SERVERS),
                    "skills/example/SKILL.md": SKILL_WITH_WHEN_TO_USE,
                }
            )
        )
        self.assertEqual(self.run_import(), 0)
        manifest = self.load(ivp.CLAUDE_MANIFEST_PATH)
        declared = {
            key: value
            for key, value in manifest.items()
            if key in ("commands", "agents", "hooks", "mcpServers", "outputStyles", "skills")
        }
        self.assertEqual(len(declared), 6, declared)
        for key, value in declared.items():
            with self.subTest(component=key):
                # `agents` is a list of files (the CLI validator refuses a
                # directory there); every other surface is one path.
                entries = value if isinstance(value, list) else [value]
                self.assertEqual(key in ivp.MANIFEST_FIELDS_LISTING_FILES, isinstance(value, list), value)
                for entry in entries:
                    self.assertTrue(entry.startswith("./"), entry)
                    self.assertNotIn("..", Path(entry).parts)
                    self.assertTrue((self.package_directory / entry).exists(), entry)
        self.assertEqual(declared["agents"], ["./com.infiquetra.claude/agents/helper.md"])

    def test_the_claude_manifest_carries_paths_and_no_behaviour(self) -> None:
        """AGENTS.md's condition for a vendor manifest outside its adapter."""
        self.upstream.build(minimal_files(**{"commands/run.md": "# run\n"}))
        self.assertEqual(self.run_import(), 0)
        manifest = self.load(ivp.CLAUDE_MANIFEST_PATH)
        for value in manifest.values():
            if isinstance(value, str):
                self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", value)

    def test_the_claude_manifest_names_this_repository_not_the_upstream(self) -> None:
        self.upstream.build(minimal_files())
        self.assertEqual(self.run_import(), 0)
        self.assertEqual(self.load(ivp.CLAUDE_MANIFEST_PATH)["repository"], ivp.THIS_REPOSITORY)

    def test_the_relocated_manifest_keeps_the_upstream_repository(self) -> None:
        """It is the upstream's own manifest, preserved, not a rewritten copy."""
        self.upstream.build(minimal_files())
        self.assertEqual(self.run_import(), 0)
        relocated = self.load(f"{ivp.CLIENT_EXTENSION_DIR}/{ivp.CLAUDE_MANIFEST_NAME}")
        self.assertEqual(relocated["repository"], UPSTREAM_MANIFEST["repository"])

    def test_the_portable_manifest_is_the_agent_plugins_shape(self) -> None:
        self.upstream.build(minimal_files())
        self.assertEqual(self.run_import(), 0)
        portable = self.load(ivp.PORTABLE_MANIFEST_NAME)
        self.assertEqual(portable["$schema"], check_repo.PLUGIN_SCHEMA)
        for field in check_repo.REPOSITORY_REQUIRED_MANIFEST_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(portable[field], UPSTREAM_MANIFEST[field])

    def test_the_two_manifests_are_different_specs(self) -> None:
        self.upstream.build(minimal_files())
        self.assertEqual(self.run_import(), 0)
        self.assertNotIn("$schema", self.load(ivp.CLAUDE_MANIFEST_PATH))

    def test_an_upstream_manifest_missing_identity_stops_the_import(self) -> None:
        incomplete = dict(UPSTREAM_MANIFEST)
        del incomplete["version"]
        self.upstream.build({".claude-plugin/plugin.json": _json(incomplete)})
        with self.assertRaises(ivp.ImportVendorError) as caught:
            self.plan()
        self.assertIn("version", str(caught.exception))

    def test_a_package_with_no_claude_manifest_stops_the_import(self) -> None:
        self.upstream.build({"README.md": "# Example\n"})
        with self.assertRaises(ivp.ImportVendorError) as caught:
            self.plan()
        self.assertIn(ivp.CLAUDE_MANIFEST_PATH, str(caught.exception))


class HooksPathRewriteTests(ImportCase):
    """A path that named a surface at the upstream root names nothing after the move."""

    def test_a_hook_command_is_re_anchored_into_the_adapter(self) -> None:
        self.upstream.build(
            minimal_files(**{"hooks.json": _json(HOOKS_DESCRIPTOR), "hooks/stop_hook.py": "print(0)\n"})
        )
        self.assertEqual(self.run_import(), 0)
        descriptor = self.load(f"{ivp.CLIENT_EXTENSION_DIR}/hooks/hooks.json")
        command = descriptor["hooks"]["Stop"][0]["hooks"][0]["command"]
        self.assertIn(f"{ivp.CLIENT_EXTENSION_DIR}/hooks/stop_hook.py", command)
        relative = command.split(ivp.PLUGIN_ROOT_TOKEN, 1)[1].lstrip("/").rstrip('"')
        self.assertTrue((self.package_directory / relative).is_file(), relative)

    def test_a_reference_to_the_moved_mcp_file_is_re_anchored(self) -> None:
        self.upstream.build(
            minimal_files(
                **{
                    ".mcp.json": _json(MCP_SERVERS),
                    "commands/run.md": f"Read {ivp.PLUGIN_ROOT_TOKEN}/.mcp.json first.\n",
                }
            )
        )
        self.assertEqual(self.run_import(), 0)
        body = self.read(f"{ivp.CLIENT_EXTENSION_DIR}/commands/run.md")
        self.assertIn(f"{ivp.CLIENT_EXTENSION_DIR}/mcp/servers.json", body)
        self.assertNotIn(f"{ivp.PLUGIN_ROOT_TOKEN}/.mcp.json", body)

    def test_portable_core_paths_are_left_exactly_as_they_are(self) -> None:
        """`skills/` and `scripts/` stay at the root, so their paths still resolve."""
        self.upstream.build(
            minimal_files(
                **{
                    ".mcp.json": _json(MCP_SERVERS),
                    "scripts/mcp_server.py": "print(0)\n",
                }
            )
        )
        self.assertEqual(self.run_import(), 0)
        servers = self.load(f"{ivp.CLIENT_EXTENSION_DIR}/mcp/servers.json")
        self.assertEqual(
            servers["example"]["args"], [f"{ivp.PLUGIN_ROOT_TOKEN}/scripts/mcp_server.py"]
        )


class SkillFrontmatterTests(ImportCase):
    """The shared normalization rule, applied rather than reimplemented."""

    def test_a_top_level_when_to_use_key_is_folded_under_metadata(self) -> None:
        self.upstream.build(minimal_files(**{"skills/example/SKILL.md": SKILL_WITH_WHEN_TO_USE}))
        self.assertEqual(self.run_import(), 0)
        body = self.read("skills/example/SKILL.md")
        self.assertIn("metadata:", body)
        self.assertNotIn("\nwhen_to_use:", body)

    def test_the_imported_skill_passes_the_repository_frontmatter_check(self) -> None:
        self.upstream.build(minimal_files(**{"skills/example/SKILL.md": SKILL_WITH_WHEN_TO_USE}))
        self.assertEqual(self.run_import(), 0)
        self.assertEqual(check_repo.check_skill_frontmatter(self.destination), [])

    def test_the_rule_recorded_is_the_shared_one(self) -> None:
        self.upstream.build(minimal_files(**{"skills/example/SKILL.md": SKILL_WITH_WHEN_TO_USE}))
        self.assertEqual(
            self.destinations()["skills/example/SKILL.md"].rule,
            svs.FRONTMATTER_TRANSFORM_NAME,
        )


class FleetBundleTests(ImportCase):
    """The shim is dropped, so every module it reached has to be declared."""

    def test_a_shim_load_is_rewritten_to_the_bundled_module(self) -> None:
        self.upstream.build(minimal_files(**{"scripts/client.py": CLIENT_WITH_SHIM}))
        self.assertEqual(self.run_import(), 0)
        body = self.read("scripts/client.py")
        # The rule leaves a comment naming the shim it replaced, so what must be
        # gone is the import statement and the load call, not the word.
        self.assertNotIn("import fleet_commons_shim", body)
        self.assertNotIn("fleet_commons_shim.load(", body)
        self.assertIn("import retry_backoff", body)
        self.assertIn(check_repo.BUNDLE_DIRECTORY_NAME, body)

    def test_the_declaration_names_exactly_the_modules_reached(self) -> None:
        self.upstream.build(minimal_files(**{"scripts/client.py": CLIENT_WITH_SHIM}))
        self.assertEqual(self.run_import(), 0)
        declaration = self.load(check_repo.FLEET_BUNDLE_FILENAME)
        self.assertEqual([module["name"] for module in declaration["modules"]], ["retry_backoff"])

    def test_the_destination_follows_the_client_rather_than_the_package_root(self) -> None:
        """The rewritten import inserts the bundle beside the client's own file."""
        self.upstream.build(
            minimal_files(**{"skills/example/scripts/client.py": CLIENT_WITH_SHIM})
        )
        self.assertEqual(self.run_import(), 0)
        declaration = self.load(check_repo.FLEET_BUNDLE_FILENAME)
        self.assertEqual(
            declaration["modules"][0]["destinations"],
            [f"skills/example/scripts/{check_repo.BUNDLE_DIRECTORY_NAME}/retry_backoff.py"],
        )

    def test_two_clients_reaching_one_module_declare_both_destinations(self) -> None:
        self.upstream.build(
            minimal_files(
                **{
                    "skills/one/scripts/client.py": CLIENT_WITH_SHIM,
                    "skills/two/scripts/client.py": CLIENT_WITH_SHIM,
                }
            )
        )
        self.assertEqual(self.run_import(), 0)
        declaration = self.load(check_repo.FLEET_BUNDLE_FILENAME)
        self.assertEqual(
            declaration["modules"][0]["destinations"],
            [
                f"skills/one/scripts/{check_repo.BUNDLE_DIRECTORY_NAME}/retry_backoff.py",
                f"skills/two/scripts/{check_repo.BUNDLE_DIRECTORY_NAME}/retry_backoff.py",
            ],
        )

    def test_the_declaration_passes_the_repository_schema_check(self) -> None:
        self.upstream.build(minimal_files(**{"scripts/client.py": CLIENT_WITH_SHIM}))
        self.assertEqual(self.run_import(), 0)
        self.assertEqual(check_repo.check_fleet_bundle_declarations(self.destination), [])

    def test_a_package_reaching_no_module_declares_no_bundle(self) -> None:
        self.upstream.build(minimal_files())
        self.assertEqual(self.run_import(), 0)
        self.assertFalse((self.package_directory / check_repo.FLEET_BUNDLE_FILENAME).exists())

    def test_the_import_does_not_run_the_bundler(self) -> None:
        """The bundle is a build step, named in the output rather than performed."""
        self.upstream.build(minimal_files(**{"scripts/client.py": CLIENT_WITH_SHIM}))
        self.assertEqual(self.run_import(), 0)
        self.assertFalse(
            (self.package_directory / "scripts" / check_repo.BUNDLE_DIRECTORY_NAME).exists()
        )
        steps = ivp.next_steps(self.plan(), PACKAGE)
        self.assertTrue(
            any("bundle_fleet_module.py" in step for step in steps),
            steps,
        )


class UnresolvedShimTests(ImportCase):
    """A shape no rule matches is carried, reported, and exits non-zero."""

    def test_the_file_is_carried_unchanged(self) -> None:
        self.upstream.build(minimal_files(**{"scripts/late.py": CLIENT_WITH_UNMATCHED_SHIM}))
        self.assertEqual(self.run_import(), 1)
        self.assertEqual(self.read("scripts/late.py"), CLIENT_WITH_UNMATCHED_SHIM)

    def test_it_is_named_rather_than_left_to_fail_at_runtime(self) -> None:
        self.upstream.build(minimal_files(**{"scripts/late.py": CLIENT_WITH_UNMATCHED_SHIM}))
        planned = self.plan()
        self.assertEqual(ivp.unresolved_shim_files(planned), ["scripts/late.py"])
        self.assertIn("scripts/late.py", ivp.summarize(planned, PACKAGE, "0" * 40))

    def test_the_module_it_reaches_is_still_declared(self) -> None:
        """So the bundle is on disk once the import is rewritten by hand."""
        self.upstream.build(minimal_files(**{"scripts/late.py": CLIENT_WITH_UNMATCHED_SHIM}))
        self.assertEqual(self.run_import(), 1)
        declaration = self.load(check_repo.FLEET_BUNDLE_FILENAME)
        self.assertEqual([module["name"] for module in declaration["modules"]], ["tier_palette"])

    def test_a_clean_package_exits_zero(self) -> None:
        self.upstream.build(minimal_files(**{"scripts/client.py": CLIENT_WITH_SHIM}))
        self.assertEqual(self.run_import(), 0)


class DryRunTests(ImportCase):
    """A dry run prints the table and writes nothing."""

    def test_nothing_is_written(self) -> None:
        self.upstream.build(minimal_files(**{"commands/run.md": "# run\n"}))
        self.assertEqual(self.run_import("--dry-run"), 0)
        self.assertFalse(self.package_directory.exists())

    def test_the_table_names_every_path_its_destination_and_its_rule(self) -> None:
        self.upstream.build(
            minimal_files(
                **{
                    "commands/run.md": "# run\n",
                    "skills/example/SKILL.md": SKILL_WITH_WHEN_TO_USE,
                    "scripts/compiled.pyc": "noise\n",
                }
            )
        )
        table = ivp.format_table(self.plan())
        self.assertIn("commands/run.md", table)
        self.assertIn(f"{ivp.CLIENT_EXTENSION_DIR}/commands/run.md", table)
        self.assertIn(svs.FRONTMATTER_TRANSFORM_NAME, table)
        self.assertIn(ivp.EXCLUDE_RULE, table)
        self.assertIn("(not carried)", table)

    def test_the_table_reports_a_generated_manifest_as_generated(self) -> None:
        self.upstream.build(minimal_files())
        classes = {entry.classification for entry in self.plan()}
        self.assertIn(ivp.GENERATED, classes)


class OverwriteTests(ImportCase):
    """An import replaces a tree wholesale, so it refuses to do it by accident."""

    def test_an_existing_package_is_refused_without_force(self) -> None:
        self.upstream.build(minimal_files())
        self.package_directory.mkdir(parents=True)
        (self.package_directory / "authored.md").write_text("keep me\n", encoding="utf-8")
        self.assertEqual(self.run_import(), 1)
        self.assertEqual(self.read("authored.md"), "keep me\n")

    def test_force_replaces_the_tree(self) -> None:
        self.upstream.build(minimal_files())
        self.package_directory.mkdir(parents=True)
        (self.package_directory / "stale.md").write_text("old\n", encoding="utf-8")
        self.assertEqual(self.run_import("--force"), 0)
        self.assertFalse((self.package_directory / "stale.md").exists())
        self.assertTrue((self.package_directory / ivp.PORTABLE_MANIFEST_NAME).is_file())


class ProvenanceTests(ImportCase):
    """The import is a one-shot read, so it leaves nothing to re-derive from."""

    def test_no_provenance_manifest_is_written(self) -> None:
        self.upstream.build(minimal_files())
        self.assertEqual(self.run_import(), 0)
        self.assertFalse((self.package_directory / check_repo.PROVENANCE_FILENAME).exists())

    def test_the_package_passes_the_provenance_check_by_being_authored(self) -> None:
        self.upstream.build(minimal_files())
        self.assertEqual(self.run_import(), 0)
        self.assertEqual(check_repo.check_provenance_manifests(self.destination), [])


class PinnedReadTests(ImportCase):
    """The upstream working tree cannot change what lands here."""

    def test_the_working_tree_is_never_read(self) -> None:
        self.upstream.build(minimal_files(**{"scripts/tool.py": "print(0)\n"}))
        edited = self.upstream.path / "plugins" / PACKAGE / "scripts" / "tool.py"
        edited.write_text("print('uncommitted')\n", encoding="utf-8")
        (self.upstream.path / "plugins" / PACKAGE / "scripts" / "extra.py").write_text(
            "print('untracked')\n", encoding="utf-8"
        )
        self.assertEqual(self.run_import(), 0)
        self.assertEqual(self.read("scripts/tool.py"), "print(0)\n")
        self.assertFalse((self.package_directory / "scripts" / "extra.py").exists())

    def test_an_unknown_commit_is_refused(self) -> None:
        self.upstream.build(minimal_files())
        with self.assertRaises(ivp.ImportVendorError):
            ivp.plan_import(self.upstream.path, "0" * 40, PACKAGE)

    def test_a_package_the_upstream_does_not_carry_is_refused(self) -> None:
        self.upstream.build(minimal_files())
        with self.assertRaises(ivp.ImportVendorError) as caught:
            ivp.plan_import(self.upstream.path, self.upstream.commit, "absent")
        self.assertIn("absent", str(caught.exception))


class RepositoryGateTests(ImportCase):
    """An imported package satisfies the checks the repository gate runs."""

    def _full_package(self) -> None:
        self.upstream.build(
            minimal_files(
                **{
                    "commands/run.md": "# run\n",
                    "agents/helper.md": "# helper\n",
                    "hooks.json": _json(HOOKS_DESCRIPTOR),
                    "hooks/stop_hook.py": "print(0)\n",
                    ".mcp.json": _json(MCP_SERVERS),
                    "output-styles/house.md": "# house\n",
                    "skills/example/SKILL.md": SKILL_WITH_WHEN_TO_USE,
                    "scripts/mcp_server.py": "print(0)\n",
                }
            )
        )
        self.assertEqual(self.run_import(), 0)

    def test_the_imported_manifest_passes_the_manifest_check(self) -> None:
        self._full_package()
        self.assertEqual(check_repo.check_plugin_manifests(self.destination), [])

    def test_the_imported_skill_passes_the_frontmatter_check(self) -> None:
        self._full_package()
        self.assertEqual(check_repo.check_skill_frontmatter(self.destination), [])

    def test_no_claude_convention_directory_sits_at_the_portable_root(self) -> None:
        """Another vendor's adapter would read one as portable core."""
        self._full_package()
        for name in ("commands", "agents", "hooks", "output-styles"):
            with self.subTest(directory=name):
                self.assertFalse((self.package_directory / name).exists())

    def test_the_package_carries_no_secret_shaped_value(self) -> None:
        self._full_package()
        self.assertEqual(check_repo.check_secret_free_values(self.destination), [])


if __name__ == "__main__":
    unittest.main()
