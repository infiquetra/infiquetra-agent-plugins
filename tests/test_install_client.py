"""Installer plans, readback, and legacy removal against a fake home.

Client binaries are shell stubs on PATH. They record the argv and stdin they
were given and exit. Nothing in this file reads or writes the operator's home.
"""

from __future__ import annotations

import io
import json
import os
import shlex
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_client as installer  # noqa: E402
import muse_cli  # noqa: E402


LEGACY_URL = "https://github.com/infiquetra/infiquetra-claude-plugins.git"
MUSE_LEGACY_MARKETPLACE = "claude-code-Marketplace"
DEDICATED_CODEX = "https://github.com/infiquetra/infiquetra-codex-plugins.git"


def write_executable(directory: Path, name: str, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class InstallFixture(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.base = Path(self._temporary.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.catalog = self.base / "catalog"
        self.argv_log = self.base / "argv.log"
        self._write_catalog()
        for name in set(installer.CLIENT_BINARIES.values()):
            write_executable(
                self.bin,
                name,
                '{\n'
                '  printf "CMD"\n'
                '  printf " %s" "$0" "$@"\n'
                '  printf "\\nSTDIN:"\n'
                "  cat\n"
                '  printf "\\nEND\\n"\n'
                '} >> "$ARGV_LOG"\n'
                "exit 0\n",
            )
        self.muse_state([], available=["unifi", "voice"])
        self._saved = {
            key: os.environ.get(key) for key in ("HOME", "PATH", "ARGV_LOG")
        }
        os.environ["HOME"] = str(self.home)
        os.environ["PATH"] = os.pathsep.join([str(self.bin), os.environ.get("PATH", "")])
        os.environ["ARGV_LOG"] = str(self.argv_log)
        self.addCleanup(self._restore_env)

    def muse_state(self, rows: list[dict], *, available: list[str] | None = None,
                   skipped: list[dict] | None = None, raw: str | None = None) -> None:
        registry_path = self.home / muse_cli.MUSE_REGISTRY_RELATIVE
        registry = json.loads(registry_path.read_text()) if registry_path.exists() else {"marketplaces": {}}
        for row in rows:
            alias = row.get("record", {}).get("source", {}).get("marketplace")
            if alias == muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS:
                registry["marketplaces"].setdefault(alias, {"source": {"path": str((self.catalog / "build/muse-marketplace").resolve())}})
            elif alias == MUSE_LEGACY_MARKETPLACE:
                registry["marketplaces"].setdefault(alias, {"source": {"path": LEGACY_URL}})
        if registry["marketplaces"]:
            write_json(registry_path, registry)
        installed = json.dumps({"plugins": rows}) if raw is None else raw
        offered = json.dumps({"available": [{"name": name, "marketplace": muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS} for name in (available or [])], "skipped": skipped or []})
        write_executable(self.bin, "muse",
            'printf "%s\\n" "$*" >> "$ARGV_LOG"\n'
            'case "$*" in\n'
            '  "plugins list --available --json") printf "%s\\n" ' + shlex.quote(offered) + ' ;;\n'
            '  "plugins list --json") printf "%s\\n" ' + shlex.quote(installed) + ' ;;\n'
            '  "plugins install "*"@"*"--scope"*) exit 2 ;;\n'
            '  *) exit 0 ;;\n'
            'esac\n')

    def _restore_env(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _write_catalog(self) -> None:
        write_json(
            self.catalog / ".claude-plugin" / "marketplace.json",
            {
                "name": "infiquetra-agent-plugins",
                "plugins": [
                    {"name": "unifi", "source": "./plugins/unifi"},
                    {"name": "voice", "source": "./plugins/voice"},
                ],
            },
        )
        self._package("voice", ["voice"])
        self._package("unifi", ["unifi-network", "unifi-protect"])
        self._package("fleet-core", [])
        write_json(
            self.catalog / ".agents" / "plugins" / "marketplace.json",
            {
                "name": "infiquetra-agent-plugins",
                "interface": {"displayName": "Infiquetra Agent Plugins"},
                "plugins": [
                    {
                        "name": "unifi",
                        "source": {"source": "local", "path": "./plugins/unifi"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    },
                    {
                        "name": "voice",
                        "source": {"source": "local", "path": "./plugins/voice"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    },
                ],
            },
        )

    def _package(self, name: str, skills: list[str]) -> None:
        root = self.catalog / "plugins" / name
        write_json(root / "plugin.json", {"name": name, "version": "0.0.1"})
        if skills:
            write_json(root / ".claude-plugin/plugin.json", {"name": name, "version": "0.0.1", "skills": ["./skills/"]})
        for skill in skills:
            skill_dir = root / "skills" / skill
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: test\n---\n\n",
                encoding="utf-8",
            )

    def invoke(self, *args: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = installer.main(["--catalog", str(self.catalog), *args])
        return code, stdout.getvalue(), stderr.getvalue()

    def command(self, client: str, *args: str, stdin: str | None = None) -> str:
        executable = str(self.bin / installer.CLIENT_BINARIES[client])
        text = f"{client}: command: {shlex.join((executable, *args))}"
        if stdin is not None:
            text += " stdin=" + stdin.replace("\n", "\\n")
        return text

    def logged(self) -> str:
        if not self.argv_log.is_file():
            return ""
        return self.argv_log.read_text(encoding="utf-8")


class ClaudeInstallTest(InstallFixture):
    def test_dry_run_registers_a_missing_marketplace_and_installs_listed_packages(self) -> None:
        code, out, err = self.invoke("--client", "claude", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn(
            self.command(
                "claude", "plugin", "marketplace", "add", "infiquetra/infiquetra-agent-plugins"
            ),
            out,
        )
        self.assertNotIn(str(self.catalog.resolve()), out)
        self.assertIn(self.command("claude", "plugin", "install", "unifi@infiquetra-agent-plugins"), out)
        self.assertIn(self.command("claude", "plugin", "install", "voice@infiquetra-agent-plugins"), out)
        self.assertIn("fleet-core is not listed in .claude-plugin/marketplace.json", out)
        self.assertEqual(self.logged(), "")
        self.assertFalse((self.home / ".claude").exists())

    def test_default_is_dry_run(self) -> None:
        code, out, err = self.invoke("--client", "claude")
        self.assertEqual(code, 0, err)
        self.assertIn("plugin marketplace add", out)
        self.assertEqual(self.logged(), "")

    def test_existing_directory_registration_is_not_duplicated(self) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(self.catalog.resolve())}
                }
            },
        )
        code, out, err = self.invoke("--client", "claude", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertNotIn("marketplace add", out)
        self.assertIn(f"already registered from {self.catalog.resolve()}", out)
        self.assertIn(self.command("claude", "plugin", "install", "voice@infiquetra-agent-plugins"), out)

    def test_a_different_registration_is_not_retargeted(self) -> None:
        other = self.base / "other-checkout"
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(other)}
                }
            },
        )
        code, out, err = self.invoke("--client", "claude", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertNotIn("marketplace add", out)
        self.assertIn("not retargeting", out)
        self.assertIn(str(other), out)

    def _register_claude(self, source: dict) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {"infiquetra-agent-plugins": {"source": source}},
        )

    def _install_claude_voice(self) -> None:
        write_json(
            self.home / ".claude/plugins/installed_plugins.json",
            {"version": 2, "plugins": {"voice@infiquetra-agent-plugins": [{"scope": "user"}]}},
        )
        write_json(
            self.home / ".claude/settings.json",
            {"enabledPlugins": {"voice@infiquetra-agent-plugins": True}},
        )

    def test_a_github_registration_of_this_repository_is_not_added_again(self) -> None:
        self._register_claude({"source": "github", "repo": "infiquetra/infiquetra-agent-plugins"})
        code, out, err = self.invoke("--client", "claude", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertNotIn("marketplace add", out)
        self.assertIn("already registered from infiquetra/infiquetra-agent-plugins", out)
        self.assertNotIn("not retargeting", out)

    def test_check_counts_a_github_registration_of_this_repository_as_catalog(self) -> None:
        self._register_claude({"source": "github", "repo": "Infiquetra/Infiquetra-Agent-Plugins"})
        self._install_claude_voice()
        code, out, err = self.invoke("--client", "claude", "--package", "voice", "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("claude voice installed-from-catalog", out)

    def test_check_counts_a_directory_registration_of_this_checkout_as_catalog(self) -> None:
        self._register_claude({"source": "directory", "path": str(self.catalog.resolve())})
        self._install_claude_voice()
        code, out, err = self.invoke("--client", "claude", "--package", "voice", "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("claude voice installed-from-catalog", out)

    def test_check_counts_this_repository_url_forms_as_catalog(self) -> None:
        for source in (
            {"source": "git", "url": "https://github.com/infiquetra/infiquetra-agent-plugins"},
            {"source": "git", "url": "https://github.com/infiquetra/infiquetra-agent-plugins.git"},
            {"source": "git", "url": "git@github.com:infiquetra/infiquetra-agent-plugins.git"},
            {"source": "url", "url": "https://github.com/infiquetra/infiquetra-agent-plugins.git"},
        ):
            with self.subTest(source=source):
                self._register_claude(source)
                self._install_claude_voice()
                code, out, err = self.invoke("--client", "claude", "--package", "voice", "--check")
                self.assertEqual(code, 0, err)
                self.assertIn("claude voice installed-from-catalog", out)

    def test_check_names_a_registration_that_is_not_this_catalog(self) -> None:
        other = self.base / "other-checkout"
        for source, shown in (
            ({"source": "directory", "path": str(other)}, str(other)),
            (
                {"source": "github", "repo": "infiquetra/infiquetra-codex-plugins"},
                "infiquetra/infiquetra-codex-plugins",
            ),
        ):
            with self.subTest(source=source):
                self._register_claude(source)
                self._install_claude_voice()
                code, out, err = self.invoke("--client", "claude", "--package", "voice", "--check")
                self.assertEqual(code, 0, err)
                self.assertIn(f"claude voice installed-from-elsewhere ({shown})", out)

    def test_execute_invokes_the_stub_and_does_not_edit_the_marketplace_file(self) -> None:
        code, _out, err = self.invoke("--client", "claude", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        log = self.logged()
        self.assertIn("plugin marketplace add", log)
        self.assertIn("plugin install voice@infiquetra-agent-plugins", log)
        self.assertFalse((self.home / ".claude").exists())

    def test_execute_is_idempotent_when_already_installed_from_this_catalog(self) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(self.catalog.resolve())}
                }
            },
        )
        write_json(
            self.home / ".claude/plugins/installed_plugins.json",
            {"version": 2, "plugins": {"voice@infiquetra-agent-plugins": [{"scope": "user"}]}},
        )
        write_json(
            self.home / ".claude/settings.json",
            {"enabledPlugins": {"voice@infiquetra-agent-plugins": True}},
        )
        code, out, err = self.invoke("--client", "claude", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("voice already installed from this catalog", out)
        self.assertNotIn("plugin install", self.logged())

    def test_execute_skips_a_legacy_installed_package_without_the_uninstall_flag(self) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(self.catalog.resolve())}
                },
                "infiquetra-plugins": {"source": {"source": "git", "url": LEGACY_URL}},
            },
        )
        write_json(
            self.home / ".claude/plugins/installed_plugins.json",
            {"version": 2, "plugins": {"voice@infiquetra-plugins": [{"scope": "user"}]}},
        )
        code, out, err = self.invoke("--client", "claude", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("voice already installed from voice@infiquetra-plugins; not replacing", out)
        self.assertIn("--uninstall-legacy --execute", out)
        self.assertNotIn("plugin install", self.logged())

    def test_check_classifies_catalog_elsewhere_and_absent(self) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(self.catalog.resolve())}
                },
                "infiquetra-plugins": {
                    "source": {"source": "git", "url": LEGACY_URL}
                },
            },
        )
        write_json(
            self.home / ".claude/plugins/installed_plugins.json",
            {
                "version": 2,
                "plugins": {
                    "voice@infiquetra-agent-plugins": [{"scope": "user"}],
                    "unifi@infiquetra-plugins": [{"scope": "user", "installPath": "/cache/unifi"}],
                },
            },
        )
        write_json(
            self.home / ".claude/settings.json",
            {"enabledPlugins": {"voice@infiquetra-agent-plugins": True, "unifi@infiquetra-plugins": True}},
        )
        code, out, err = self.invoke("--client", "claude", "--check")
        self.assertEqual(err, "")
        self.assertIn("claude voice installed-from-catalog", out)
        self.assertIn("claude unifi installed-from-elsewhere (unifi@infiquetra-plugins)", out)
        self.assertIn("claude fleet-core not-applicable (library)", out)
        self.assertEqual(code, 0)

    def test_disabled_catalog_install_is_not_counted_as_catalog(self) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(self.catalog.resolve())}
                }
            },
        )
        write_json(
            self.home / ".claude/plugins/installed_plugins.json",
            {"version": 2, "plugins": {"voice@infiquetra-agent-plugins": [{"scope": "user"}]}},
        )
        write_json(self.home / ".claude/settings.json", {"enabledPlugins": {"voice@infiquetra-agent-plugins": False}})
        code, out, err = self.invoke("--client", "claude", "--package", "voice", "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("installed-from-elsewhere (voice@infiquetra-agent-plugins disabled)", out)

    def test_uninstall_removes_only_the_legacy_git_marketplace(self) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-plugins": {"source": {"source": "git", "url": LEGACY_URL}},
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(self.catalog.resolve())}
                },
            },
        )
        write_json(
            self.home / ".claude/plugins/installed_plugins.json",
            {
                "version": 2,
                "plugins": {
                    "unifi@infiquetra-plugins": [{"scope": "user"}],
                    "voice@infiquetra-agent-plugins": [{"scope": "user"}],
                },
            },
        )
        before = (self.home / ".claude/plugins/known_marketplaces.json").read_text(encoding="utf-8")
        code, out, err = self.invoke("--client", "claude", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(self.command("claude", "plugin", "uninstall", "unifi@infiquetra-plugins"), out)
        self.assertIn(self.command("claude", "plugin", "marketplace", "remove", "infiquetra-plugins"), out)
        self.assertNotIn("voice@infiquetra-agent-plugins", out)
        self.assertEqual(
            (self.home / ".claude/plugins/known_marketplaces.json").read_text(encoding="utf-8"),
            before,
        )

    def test_uninstall_refuses_the_name_when_the_url_is_not_legacy(self) -> None:
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-plugins": {
                    "source": {
                        "source": "github",
                        "repo": "infiquetra/infiquetra-antigravity-plugins",
                    }
                }
            },
        )
        code, out, err = self.invoke("--client", "claude", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("dedicated repository", out)
        self.assertEqual(self.logged(), "")


class CodexTest(InstallFixture):
    def _write_config(self, *tables: str) -> None:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("\n".join(tables) + "\n", encoding="utf-8")

    def test_dry_run_adds_the_marketplace_and_the_listed_plugins(self) -> None:
        code, out, err = self.invoke("--client", "codex", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn(
            self.command("codex", "plugin", "marketplace", "add", str(self.catalog.resolve())),
            out,
        )
        self.assertIn(self.command("codex", "plugin", "add", "voice@infiquetra-agent-plugins"), out)
        self.assertIn(self.command("codex", "plugin", "add", "unifi@infiquetra-agent-plugins"), out)
        self.assertIn("fleet-core is not listed in .agents/plugins/marketplace.json", out)
        self.assertNotIn("codex unsupported:", out)
        self.assertEqual(self.logged(), "")

    def test_a_missing_marketplace_file_is_an_error(self) -> None:
        (self.catalog / ".agents" / "plugins" / "marketplace.json").unlink()
        code, _out, err = self.invoke("--client", "codex", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("marketplace.json", err)
        self.assertIn("sync_codex_packaging.py", err)

    def test_an_existing_registration_of_this_checkout_is_not_added_again(self) -> None:
        catalog = str(self.catalog.resolve())
        self._write_config(
            "[marketplaces.infiquetra-agent-plugins]",
            'source_type = "local"',
            f'source = "{catalog}"',
            "",
            '[plugins."voice@infiquetra-agent-plugins"]',
            "enabled = true",
            "",
            '[plugins."unifi@infiquetra-agent-plugins"]',
            "enabled = true",
            "",
        )
        code, out, err = self.invoke("--client", "codex", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn(f"marketplace infiquetra-agent-plugins already registered at {catalog}", out)
        self.assertIn("voice@infiquetra-agent-plugins already enabled", out)
        self.assertIn("unifi@infiquetra-agent-plugins already enabled", out)
        self.assertNotIn("marketplace add", out)
        self.assertNotIn("plugin add", out)

    def test_a_registration_elsewhere_is_not_retargeted_and_installs_nothing(self) -> None:
        self._write_config(
            "[marketplaces.infiquetra-agent-plugins]",
            'source_type = "local"',
            'source = "/tmp/some-other-checkout"',
            "",
        )
        code, out, err = self.invoke("--client", "codex", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("not retargeting", out)
        self.assertIn("points at /tmp/some-other-checkout", out)
        self.assertNotIn("marketplace add", out)
        self.assertNotIn("plugin add", out)

    def test_check_reads_an_enabled_plugin_whose_marketplace_is_this_checkout(self) -> None:
        catalog = str(self.catalog.resolve())
        self._write_config(
            "[marketplaces.infiquetra-agent-plugins]",
            'source_type = "local"',
            f'source = "{catalog}"',
            "",
            '[plugins."voice@infiquetra-agent-plugins"]',
            "enabled = true",
            "",
        )
        code, out, err = self.invoke("--client", "codex", "--check")
        self.assertEqual(err, "")
        self.assertEqual(code, 1)
        self.assertIn("codex voice installed-from-catalog", out)
        self.assertIn("codex unifi absent", out)
        self.assertIn("codex fleet-core not-applicable (library)", out)

    def test_check_treats_a_symlink_to_this_checkout_as_the_catalog(self) -> None:
        link = self.base / "catalog-link"
        link.symlink_to(self.catalog, target_is_directory=True)
        self._write_config(
            "[marketplaces.infiquetra-agent-plugins]",
            'source_type = "local"',
            f'source = "{link}"',
            "",
            '[plugins."voice@infiquetra-agent-plugins"]',
            "enabled = true",
            "",
        )
        code, out, err = self.invoke("--client", "codex", "--check")
        self.assertEqual(err, "")
        self.assertEqual(code, 1)
        self.assertIn("codex voice installed-from-catalog", out)

    def test_check_reports_a_disabled_plugin_as_elsewhere(self) -> None:
        catalog = str(self.catalog.resolve())
        self._write_config(
            "[marketplaces.infiquetra-agent-plugins]",
            'source_type = "local"',
            f'source = "{catalog}"',
            "",
            '[plugins."voice@infiquetra-agent-plugins"]',
            "enabled = false",
            "",
        )
        code, out, err = self.invoke("--client", "codex", "--check")
        self.assertEqual(code, 1, err)
        self.assertIn(
            "codex voice installed-from-elsewhere (voice@infiquetra-agent-plugins disabled)",
            out,
        )

    def test_check_reports_the_dedicated_marketplace_as_elsewhere(self) -> None:
        self._write_config(
            "[marketplaces.infiquetra-codex-plugins]",
            'source_type = "git"',
            f'source = "{DEDICATED_CODEX}"',
            "",
            '[plugins."voice@infiquetra-codex-plugins"]',
            "enabled = true",
            "",
        )
        code, out, err = self.invoke("--client", "codex", "--check")
        self.assertEqual(code, 1, err)
        self.assertIn(f"codex voice installed-from-elsewhere ({DEDICATED_CODEX})", out)
        self.assertIn("codex unifi absent", out)

    def test_uninstall_removes_a_legacy_marketplace_and_keeps_the_dedicated_one(self) -> None:
        config = self.home / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            "\n".join(
                [
                    "[marketplaces.infiquetra-codex-plugins]",
                    'source_type = "git"',
                    f'source = "{DEDICATED_CODEX}"',
                    "",
                    "[marketplaces.old-claude]",
                    'source_type = "git"',
                    f'source = "{LEGACY_URL}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        before = config.read_text(encoding="utf-8")
        code, out, err = self.invoke("--client", "codex", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("dedicated repository", out)
        self.assertIn(self.command("codex", "plugin", "marketplace", "remove", "old-claude"), out)
        self.assertNotIn("remove infiquetra-codex-plugins", out)
        self.assertEqual(config.read_text(encoding="utf-8"), before)


class CursorTest(InstallFixture):
    def test_dry_run_adds_the_git_url(self) -> None:
        code, out, err = self.invoke("--client", "cursor", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn(
            self.command(
                "cursor",
                "plugin",
                "marketplace",
                "add",
                installer.CATALOG_GIT_URL,
            ),
            out,
        )
        self.assertIn("cursor-agent", out)

    def test_check_reads_the_cache_for_this_repo_and_the_old_one(self) -> None:
        write_json(
            self.home
            / ".cursor/plugins/marketplaces/github.com/infiquetra/infiquetra-agent-plugins/abc/.claude-plugin/marketplace.json",
            {"plugins": [{"name": "voice"}]},
        )
        write_json(
            self.home
            / ".cursor/plugins/marketplaces/github.com/infiquetra/infiquetra-claude-plugins/def/.claude-plugin/marketplace.json",
            {"plugins": [{"name": "unifi"}, {"name": "voice"}]},
        )
        code, out, err = self.invoke("--client", "cursor", "--check")
        self.assertEqual(err, "")
        self.assertIn("cursor voice installed-from-catalog", out)
        self.assertIn(
            f"cursor unifi installed-from-elsewhere ({installer.LEGACY_GIT_URL})",
            out,
        )
        self.assertIn("cursor fleet-core not-applicable (library)", out)
        self.assertEqual(code, 0)

    def test_cached_catalog_is_not_added_again(self) -> None:
        write_json(
            self.home
            / ".cursor/plugins/marketplaces/github.com/infiquetra/infiquetra-agent-plugins/abc/.claude-plugin/marketplace.json",
            {"plugins": [{"name": "voice"}]},
        )
        code, out, err = self.invoke("--client", "cursor", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("already has a manifest", out)
        self.assertNotIn("marketplace add", out)

    def test_uninstall_removes_the_legacy_url_only(self) -> None:
        write_json(
            self.home
            / ".cursor/plugins/marketplaces/github.com/infiquetra/infiquetra-claude-plugins/def/.claude-plugin/marketplace.json",
            {"plugins": [{"name": "unifi"}]},
        )
        code, out, err = self.invoke("--client", "cursor", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(
            self.command("cursor", "plugin", "marketplace", "remove", installer.LEGACY_GIT_URL),
            out,
        )
        self.assertNotIn(installer.CATALOG_GIT_URL, self.logged())


class QwenTest(InstallFixture):
    def test_execute_installs_and_records_this_checkout_as_the_source(self) -> None:
        code, out, err = self.invoke("--client", "qwen", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        voice = str((self.catalog / "plugins" / "voice").resolve())
        self.assertIn(self.command("qwen", "extensions", "install", voice, stdin="y\n"), out)
        self.assertIn("STDIN:y\n", self.logged())
        record = self.home / ".qwen/extensions/voice/.qwen-extension-install.json"
        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["source"], str((self.catalog / "plugins" / "voice").resolve()))
        self.assertEqual(payload["type"], "local")
        self.assertEqual(payload["pluginName"], "voice")

    def test_merge_preserves_keys_the_client_already_wrote(self) -> None:
        record = self.home / ".qwen/extensions/voice/.qwen-extension-install.json"
        write_json(record, {"source": LEGACY_URL, "type": "git", "marketplaceConfig": {"name": "kept"}})
        target = self.catalog / "plugins" / "voice"
        installer.merge_qwen(
            installer.Action("merge-qwen", "qwen", path=str(record), target=str(target), message="voice")
        )
        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["marketplaceConfig"], {"name": "kept"})
        self.assertEqual(payload["type"], "local")
        self.assertEqual(payload["source"], str(target))

    def test_execute_is_idempotent_after_a_partial_run(self) -> None:
        record = self.home / ".qwen/extensions/voice/.qwen-extension-install.json"
        write_json(record, {"source": str((self.catalog / "plugins" / "voice").resolve()), "type": "local"})
        code, out, err = self.invoke("--client", "qwen", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("voice already installed from this catalog", out)
        self.assertEqual(self.logged(), "")

    def test_execute_skips_a_legacy_installed_package_without_the_uninstall_flag(self) -> None:
        record = self.home / ".qwen/extensions/voice/.qwen-extension-install.json"
        write_json(record, {"source": LEGACY_URL, "type": "git"})
        code, out, err = self.invoke("--client", "qwen", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(f"voice already installed from {LEGACY_URL}; not replacing", out)
        self.assertIn("--uninstall-legacy --execute", out)
        self.assertEqual(self.logged(), "")
        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["source"], LEGACY_URL)

    def test_check_classifies_the_install_record(self) -> None:
        write_json(
            self.home / ".qwen/extensions/voice/.qwen-extension-install.json",
            {"source": str((self.catalog / "plugins" / "voice").resolve()), "type": "local"},
        )
        write_json(
            self.home / ".qwen/extensions/unifi/.qwen-extension-install.json",
            {"source": LEGACY_URL, "type": "git"},
        )
        (self.home / ".qwen/extensions/fleet-core").mkdir(parents=True)
        code, out, err = self.invoke("--client", "qwen", "--check")
        self.assertEqual(err, "")
        self.assertIn("qwen voice installed-from-catalog", out)
        self.assertIn(f"qwen unifi installed-from-elsewhere ({LEGACY_URL})", out)
        self.assertIn("qwen fleet-core not-applicable (library)", out)
        self.assertEqual(code, 0)

    def test_uninstall_calls_the_client_for_a_legacy_record_and_refuses_an_unsourced_directory(self) -> None:
        legacy = self.home / ".qwen/extensions/unifi"
        write_json(
            legacy / ".qwen-extension-install.json",
            {"source": LEGACY_URL, "type": "git", "pluginName": "unifi"},
        )
        unsourced = self.home / ".qwen/extensions/voice"
        unsourced.mkdir(parents=True)
        (unsourced / "SKILL.md").write_text("keep", encoding="utf-8")
        code, out, err = self.invoke("--client", "qwen", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(self.command("qwen", "extensions", "uninstall", "unifi"), out)
        self.assertIn("no install record", out)
        self.assertTrue((unsourced / "SKILL.md").is_file())
        self.assertTrue((legacy / ".qwen-extension-install.json").is_file())


class GrokTest(InstallFixture):
    def test_install_passes_trust(self) -> None:
        code, out, err = self.invoke("--client", "grok", "--package", "voice", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn(
            self.command("grok", "plugin", "install", str((self.catalog / "plugins" / "voice").resolve()), "--trust"),
            out,
        )

    def test_execute_is_idempotent_when_already_installed_from_this_catalog(self) -> None:
        write_json(
            self.home / ".grok/installed-plugins/registry.json",
            {
                "version": 1,
                "repos": {
                    "voice-local": {
                        "kind": {"type": "Local", "source_path": str((self.catalog / "plugins" / "voice").resolve())},
                        "plugins": {"voice": {"version": "0.0.1"}},
                    },
                },
            },
        )
        code, out, err = self.invoke("--client", "grok", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("voice already installed from this catalog", out)
        self.assertEqual(self.logged(), "")

    def test_execute_skips_a_legacy_installed_package_without_the_uninstall_flag(self) -> None:
        write_json(
            self.home / ".grok/installed-plugins/registry.json",
            {
                "version": 1,
                "repos": {
                    "unifi-old": {
                        "marketplace": {"source_url_or_path": LEGACY_URL},
                        "plugins": {"voice": {"version": "1"}},
                    },
                },
            },
        )
        code, out, err = self.invoke("--client", "grok", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(f"voice already installed from {LEGACY_URL}; not replacing", out)
        self.assertIn("--uninstall-legacy --execute", out)
        self.assertEqual(self.logged(), "")

    def test_check_reads_the_registry_source(self) -> None:
        write_json(
            self.home / ".grok/installed-plugins/registry.json",
            {
                "version": 1,
                "repos": {
                    "voice-local": {
                        "kind": {"type": "Local", "source_path": str((self.catalog / "plugins" / "voice").resolve())},
                        "plugins": {"voice": {"version": "0.0.1"}},
                    },
                    "unifi-old": {
                        "marketplace": {"source_url_or_path": LEGACY_URL},
                        "plugins": {"unifi": {"version": "2.0.6"}},
                    },
                },
            },
        )
        code, out, err = self.invoke("--client", "grok", "--check")
        self.assertEqual(err, "")
        self.assertIn("grok voice installed-from-catalog", out)
        self.assertIn(f"grok unifi installed-from-elsewhere ({LEGACY_URL})", out)
        self.assertIn("grok fleet-core not-applicable (library)", out)
        self.assertEqual(code, 0)

    def test_uninstall_removes_legacy_plugins_and_skips_a_dedicated_source(self) -> None:
        write_json(
            self.home / ".grok/installed-plugins/registry.json",
            {
                "version": 1,
                "repos": {
                    "saga-1": {
                        "marketplace": {"source_url_or_path": LEGACY_URL},
                        "plugins": {"unifi": {"version": "1"}},
                    },
                    "codex-1": {
                        "marketplace": {"source_url_or_path": DEDICATED_CODEX},
                        "plugins": {"voice": {"version": "1"}},
                    },
                },
            },
        )
        code, out, err = self.invoke("--client", "grok", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(self.command("grok", "plugin", "uninstall", "unifi", "--confirm"), out)
        self.assertNotIn("uninstall voice", out)
        self.assertIn("dedicated repository", out)

    def test_uninstall_removes_a_marketplace_backed_legacy_entry_by_marketplace(self) -> None:
        # The real registry records a marketplace name for a legacy install
        # (`source_display_name`), and a same-named catalog install shares no
        # part of that marketplace-cache entry. Removing by marketplace name
        # must not touch the catalog entry, and must run only once even
        # though two plugins share the marketplace.
        write_json(
            self.home / ".grok/installed-plugins/registry.json",
            {
                "version": 1,
                "repos": {
                    "unifi-old": {
                        "kind": {
                            "type": "Local",
                            "source_path": str(self.home / ".grok/marketplace-cache/abc/plugins/unifi"),
                        },
                        "marketplace": {
                            "source_url_or_path": LEGACY_URL,
                            "source_display_name": "infiquetra-plugins",
                        },
                        "plugins": {"unifi": {"version": "1"}},
                    },
                    "voice-old": {
                        "kind": {
                            "type": "Local",
                            "source_path": str(self.home / ".grok/marketplace-cache/abc/plugins/voice"),
                        },
                        "marketplace": {
                            "source_url_or_path": LEGACY_URL,
                            "source_display_name": "infiquetra-plugins",
                        },
                        "plugins": {"voice": {"version": "1"}},
                    },
                    "unifi-catalog": {
                        "kind": {
                            "type": "Local",
                            "source_path": str((self.catalog / "plugins/unifi").resolve()),
                        },
                        "plugins": {"unifi": {"version": "2"}},
                    },
                },
            },
        )
        code, out, err = self.invoke("--client", "grok", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            out.count(self.command("grok", "plugin", "marketplace", "remove", "infiquetra-plugins")),
            1,
        )
        self.assertNotIn("uninstall unifi", out)
        self.assertNotIn("uninstall voice", out)

    def test_uninstall_removes_a_plain_legacy_entry_with_no_catalog_twin(self) -> None:
        legacy_root = self.base / "infiquetra-claude-plugins" / "plugins" / "voice"
        write_json(
            self.home / ".grok/installed-plugins/registry.json",
            {
                "version": 1,
                "repos": {
                    "voice-old": {
                        "kind": {"type": "Local", "source_path": str(legacy_root)},
                        "plugins": {"voice": {"version": "1"}},
                    },
                },
            },
        )
        code, out, err = self.invoke("--client", "grok", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(self.command("grok", "plugin", "uninstall", "voice", "--confirm"), out)

    def test_uninstall_skips_a_plain_legacy_entry_ambiguous_with_a_catalog_entry(self) -> None:
        legacy_root = self.base / "infiquetra-claude-plugins" / "plugins" / "voice"
        write_json(
            self.home / ".grok/installed-plugins/registry.json",
            {
                "version": 1,
                "repos": {
                    "voice-old": {
                        "kind": {"type": "Local", "source_path": str(legacy_root)},
                        "plugins": {"voice": {"version": "1"}},
                    },
                    "voice-catalog": {
                        "kind": {
                            "type": "Local",
                            "source_path": str((self.catalog / "plugins/voice").resolve()),
                        },
                        "plugins": {"voice": {"version": "2"}},
                    },
                },
            },
        )
        code, out, err = self.invoke("--client", "grok", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertNotIn("uninstall voice", out)
        self.assertIn("ambiguous", out)
        self.assertEqual(self.logged(), "")


class OpenCodeTest(InstallFixture):
    def test_dry_run_prints_symlinks_and_writes_nothing(self) -> None:
        code, out, err = self.invoke("--client", "opencode", "--package", "voice", "--dry-run")
        self.assertEqual(code, 0, err)
        link = self.home / ".config/opencode/skills/voice"
        target = (self.catalog / "plugins/voice/skills/voice").resolve()
        self.assertIn(f"opencode: symlink: {link} -> {target}", out)
        self.assertIn("opencode: write:", out)
        self.assertFalse(link.exists())
        self.assertFalse((self.home / ".config/opencode/.infiquetra-plugins.json").exists())

    def test_execute_links_and_preserves_a_dedicated_repo_entry(self) -> None:
        dedicated = self.base / "infiquetra-opencode-plugins" / "plugins" / "saga" / "skills" / "brainstorm"
        dedicated.mkdir(parents=True)
        (dedicated / "SKILL.md").write_text("other", encoding="utf-8")
        link = self.home / ".config/opencode/skills/brainstorm"
        link.parent.mkdir(parents=True)
        link.symlink_to(dedicated)
        write_json(
            self.home / ".config/opencode/.infiquetra-plugins.json",
            {
                "schema": installer.OPENCODE_SCHEMA,
                "links": [{"target": str(dedicated), "link": str(link)}],
            },
        )
        code, _out, err = self.invoke("--client", "opencode", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        voice = self.home / ".config/opencode/skills/voice"
        self.assertTrue(voice.is_symlink())
        self.assertEqual(voice.resolve(), (self.catalog / "plugins/voice/skills/voice").resolve())
        self.assertEqual(link.resolve(), dedicated.resolve())
        document = json.loads(
            (self.home / ".config/opencode/.infiquetra-plugins.json").read_text(encoding="utf-8")
        )
        links = {(item["link"], item["target"]) for item in document["links"]}
        self.assertIn((str(link), str(dedicated)), links)
        self.assertIn((str(voice), str(voice.resolve())), links)

    def test_does_not_retarget_an_existing_skill_link(self) -> None:
        other = self.base / "elsewhere" / "voice"
        other.mkdir(parents=True)
        dest = self.home / ".config/opencode/skills/voice"
        dest.parent.mkdir(parents=True)
        dest.symlink_to(other)
        code, out, err = self.invoke("--client", "opencode", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("already points at", out)
        self.assertEqual(dest.resolve(), other.resolve())
        self.assertFalse((self.home / ".config/opencode/.infiquetra-plugins.json").exists())

    def test_check_reads_the_symlink_target(self) -> None:
        dest = self.home / ".config/opencode/skills/voice"
        dest.parent.mkdir(parents=True)
        dest.symlink_to((self.catalog / "plugins/voice/skills/voice").resolve())
        code, out, err = self.invoke("--client", "opencode", "--package", "voice", "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("opencode voice installed-from-catalog", out)

    def test_uninstall_refuses_an_unsourced_copy_and_unlinks_a_legacy_manifest_entry(self) -> None:
        skills = self.home / ".config/opencode/skills"
        skills.mkdir(parents=True)
        unsourced = skills / "voice"
        unsourced.mkdir()
        (unsourced / "keep").write_text("keep", encoding="utf-8")
        legacy_target = self.base / "infiquetra-claude-plugins" / "plugins" / "unifi" / "skills" / "unifi-network"
        legacy_target.mkdir(parents=True)
        (legacy_target / "SKILL.md").write_text("upstream", encoding="utf-8")
        legacy_link = skills / "unifi-network"
        legacy_link.symlink_to(legacy_target)
        catalog_skill = (self.catalog / "plugins/unifi/skills/unifi-protect").resolve()
        (catalog_skill / "keep").write_text("catalog", encoding="utf-8")
        protect = skills / "unifi-protect"
        protect.symlink_to(catalog_skill)
        write_json(
            self.home / ".config/opencode/.infiquetra-plugins.json",
            {
                "schema": installer.OPENCODE_SCHEMA,
                "links": [
                    {"target": str(legacy_target), "link": str(legacy_link)},
                    {"target": str(catalog_skill), "link": str(protect)},
                ],
            },
        )
        code, out, err = self.invoke("--client", "opencode", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("no manifest entry", out)
        self.assertTrue((unsourced / "keep").is_file())
        self.assertFalse(legacy_link.exists())
        self.assertTrue((legacy_target / "SKILL.md").is_file())
        self.assertTrue(protect.is_symlink())
        self.assertTrue((catalog_skill / "keep").is_file())
        document = json.loads(
            (self.home / ".config/opencode/.infiquetra-plugins.json").read_text(encoding="utf-8")
        )
        self.assertEqual([item["link"] for item in document["links"]], [str(protect)])


class GeminiMuseHermesTest(InstallFixture):
    def test_gemini_link_supplies_the_confirmation_the_matrix_used(self) -> None:
        code, out, err = self.invoke("--client", "gemini", "--package", "voice", "--dry-run")
        self.assertEqual(code, 0, err)
        target = str((self.catalog / "plugins/voice/skills/voice").resolve())
        self.assertIn(self.command("gemini", "skills", "link", target, stdin="y\n"), out)

    def test_gemini_check_treats_a_recorded_copy_as_this_catalog(self) -> None:
        dest = self.home / ".gemini/skills/voice"
        dest.mkdir(parents=True)
        target = str((self.catalog / "plugins/voice/skills/voice").resolve())
        write_json(
            self.home / ".gemini/.infiquetra-skills.json",
            {"schema": installer.GEMINI_SCHEMA, "links": [{"target": target, "link": str(dest)}]},
        )
        code, out, err = self.invoke("--client", "gemini", "--package", "voice", "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("gemini voice installed-from-catalog", out)

    def test_hermes_symlinks_because_its_installer_rejects_a_local_path(self) -> None:
        code, out, err = self.invoke("--client", "hermes", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        dest = self.home / ".hermes/skills/voice"
        self.assertTrue(dest.is_symlink())
        self.assertEqual(dest.resolve(), (self.catalog / "plugins/voice/skills/voice").resolve())
        self.assertNotIn("hermes skills install", self.logged())
        self.assertIn("fleet-core has no skill units", self.invoke("--client", "hermes", "--package", "fleet-core")[1])

    def test_hermes_uninstall_refuses_an_unsourced_copy(self) -> None:
        dest = self.home / ".hermes/skills/voice"
        dest.mkdir(parents=True)
        (dest / "keep").write_text("keep", encoding="utf-8")
        code, out, err = self.invoke("--client", "hermes", "--package", "voice", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("no manifest entry", out)
        self.assertEqual((dest / "keep").read_text(encoding="utf-8"), "keep")

    def test_hermes_uninstall_unlinks_a_legacy_manifest_entry_without_deleting_its_target(self) -> None:
        catalog_skill = (self.catalog / "plugins/voice/skills/voice").resolve()
        (catalog_skill / "keep").write_text("catalog", encoding="utf-8")
        dest = self.home / ".hermes/skills/voice"
        dest.parent.mkdir(parents=True)
        dest.symlink_to(catalog_skill)
        legacy = self.base / "infiquetra-claude-plugins" / "plugins" / "voice" / "skills" / "voice"
        write_json(
            self.home / ".hermes/.infiquetra-skills.json",
            {
                "schema": installer.HERMES_SCHEMA,
                "links": [{"target": str(legacy), "link": str(dest)}],
            },
        )
        code, _out, err = self.invoke("--client", "hermes", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertFalse(dest.exists())
        self.assertEqual((catalog_skill / "keep").read_text(encoding="utf-8"), "catalog")



class AgyTest(InstallFixture):
    def test_execute_installs_the_package_directory_and_records_the_source(self) -> None:
        code, out, err = self.invoke("--client", "agy", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        root = str((self.catalog / "plugins/voice").resolve())
        self.assertIn(self.command("agy", "plugin", "install", root), out)
        document = json.loads(
            (self.home / ".gemini/config/plugins/.infiquetra-install.json").read_text(encoding="utf-8")
        )
        self.assertEqual(document["packages"]["voice"]["source"], root)

    def test_execute_is_idempotent_when_already_installed_from_this_catalog(self) -> None:
        root = str((self.catalog / "plugins/voice").resolve())
        (self.home / ".gemini/config/plugins/voice").mkdir(parents=True)
        write_json(
            self.home / ".gemini/config/plugins/.infiquetra-install.json",
            {"schema": installer.AGY_SCHEMA, "packages": {"voice": {"source": root}}},
        )
        code, out, err = self.invoke("--client", "agy", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("voice already installed from this catalog", out)
        self.assertEqual(self.logged(), "")

    def test_install_does_not_replace_an_unsourced_directory(self) -> None:
        plugins = self.home / ".gemini/config/plugins"
        (plugins / "voice").mkdir(parents=True)
        (plugins / "voice" / "keep").write_text("keep", encoding="utf-8")
        code, out, err = self.invoke("--client", "agy", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("no source manifest", out)
        self.assertEqual((plugins / "voice" / "keep").read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.logged(), "")
        self.assertFalse((plugins / ".infiquetra-install.json").exists())

    def test_check_requires_the_installed_directory_and_the_source_manifest(self) -> None:
        root = str((self.catalog / "plugins/voice").resolve())
        (self.home / ".gemini/config/plugins/voice").mkdir(parents=True)
        write_json(
            self.home / ".gemini/config/plugins/.infiquetra-install.json",
            {"schema": installer.AGY_SCHEMA, "packages": {"voice": {"source": root}}},
        )
        (self.home / ".gemini/config/plugins/unifi").mkdir()
        code, out, err = self.invoke("--client", "agy", "--check")
        self.assertEqual(err, "")
        self.assertIn("agy voice installed-from-catalog", out)
        self.assertIn("agy unifi installed-from-elsewhere (unsourced)", out)
        self.assertIn("agy fleet-core not-applicable (library)", out)
        self.assertEqual(code, 0)

    def test_uninstall_skips_the_antigravity_marketplace_and_refuses_an_unsourced_copy(self) -> None:
        plugins = self.home / ".gemini/config/plugins"
        write_json(
            plugins / "known_marketplaces.json",
            {
                "infiquetra-plugins": {
                    "source": "github",
                    "repo": "infiquetra/infiquetra-antigravity-plugins",
                }
            },
        )
        (plugins / "voice").mkdir(parents=True)
        (plugins / "voice" / "keep").write_text("keep", encoding="utf-8")
        code, out, err = self.invoke("--client", "agy", "--package", "voice", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("infiquetra-antigravity-plugins", out)
        self.assertIn("no source manifest", out)
        self.assertEqual((plugins / "voice" / "keep").read_text(encoding="utf-8"), "keep")
        self.assertEqual(self.logged(), "")

    def test_uninstall_removes_a_package_whose_manifest_records_the_old_url(self) -> None:
        plugins = self.home / ".gemini/config/plugins"
        write_json(
            plugins / ".infiquetra-install.json",
            {
                "schema": installer.AGY_SCHEMA,
                "packages": {"voice": {"source": LEGACY_URL}, "unifi": {"source": str(self.catalog)}},
            },
        )
        code, out, err = self.invoke("--client", "agy", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(self.command("agy", "plugin", "uninstall", "voice"), out)
        self.assertNotIn("uninstall unifi", self.logged())
        document = json.loads((plugins / ".infiquetra-install.json").read_text(encoding="utf-8"))
        self.assertNotIn("voice", document["packages"])
        self.assertIn("unifi", document["packages"])


class InvocationTest(InstallFixture):
    def test_binary_override_refuses_the_launcher_on_path(self) -> None:
        code, _out, err = self.invoke(
            "--client",
            "grok",
            "--binary",
            f"grok={self.bin / 'grok'}",
            "--dry-run",
        )
        self.assertEqual(code, 2)
        self.assertIn("same file", err)
        self.assertIn("recursively", err)

    def test_binary_override_uses_a_different_executable(self) -> None:
        real = write_executable(self.bin, "grok-real", "exit 0\n")
        code, out, err = self.invoke(
            "--client",
            "grok",
            "--package",
            "voice",
            "--binary",
            f"grok={real}",
            "--dry-run",
        )
        self.assertEqual(code, 0, err)
        self.assertIn(str(real), out)
        self.assertNotIn(str(self.bin / "grok") + " plugin", out)

    def test_package_filter_and_unknown_package(self) -> None:
        code, out, err = self.invoke("--client", "claude", "--package", "voice", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertNotIn("unifi@infiquetra-agent-plugins", out)
        self.assertIn("voice@infiquetra-agent-plugins", out)
        code, _out, err = self.invoke("--client", "claude", "--package", "missing")
        self.assertEqual(code, 2)
        self.assertIn("unknown package", err)

    def test_execute_and_dry_run_together_are_rejected(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            installer.main(["--catalog", str(self.catalog), "--client", "claude", "--execute", "--dry-run"])
        self.assertEqual(raised.exception.code, 2)

    def test_all_dry_run_mentions_every_client_and_changes_nothing(self) -> None:
        code, out, err = self.invoke("--client", "all", "--dry-run")
        self.assertEqual(code, 0, err)
        for client in installer.CLIENTS:
            self.assertIn(client, out)
        self.assertIn("plugin marketplace add", out)
        self.assertNotIn("codex unsupported:", out)
        self.assertEqual(self.logged(), "")
        self.assertFalse((self.home / ".qwen").exists())
        self.assertFalse((self.home / ".hermes").exists())

    def test_check_all_exits_nonzero_when_a_package_is_absent(self) -> None:
        code, out, err = self.invoke("--client", "all", "--check")
        self.assertEqual(err, "")
        self.assertEqual(code, 1)
        self.assertIn("claude voice absent", out)
        self.assertIn("codex voice absent", out)
        self.assertNotIn("codex unsupported:", out)

    def test_check_all_does_not_exit_nonzero_for_not_applicable_packages_alone(self) -> None:
        # Every package here is either installed from this catalog or not applicable
        # to the client reading it, so no package is genuinely absent.
        write_json(
            self.home / ".claude/plugins/known_marketplaces.json",
            {
                "infiquetra-agent-plugins": {
                    "source": {"source": "directory", "path": str(self.catalog.resolve())}
                }
            },
        )
        write_json(
            self.home / ".claude/plugins/installed_plugins.json",
            {
                "version": 2,
                "plugins": {
                    "unifi@infiquetra-agent-plugins": [{"scope": "user"}],
                    "voice@infiquetra-agent-plugins": [{"scope": "user"}],
                },
            },
        )
        write_json(
            self.home / ".claude/settings.json",
            {
                "enabledPlugins": {
                    "unifi@infiquetra-agent-plugins": True,
                    "voice@infiquetra-agent-plugins": True,
                }
            },
        )
        code, out, err = self.invoke("--client", "claude", "--check")
        self.assertEqual(err, "")
        self.assertEqual(code, 0, out)
        self.assertIn("claude fleet-core not-applicable (library)", out)

    def test_client_all_execute_continues_past_a_failing_client_and_exits_nonzero(self) -> None:
        write_executable(
            self.bin,
            "grok",
            (
                '{\n'
                '  printf "CMD"\n'
                '  printf " %s" "$0" "$@"\n'
                '  printf "\\nSTDIN:"\n'
                "  cat\n"
                '  printf "\\nEND\\n"\n'
                '} >> "$ARGV_LOG"\n'
                'case "$*" in\n'
                '  *voice*) exit 7 ;;\n'
                '  *) exit 0 ;;\n'
                "esac\n"
            ),
        )
        code, out, err = self.invoke("--client", "all", "--package", "voice", "--execute")
        self.assertEqual(code, 1)
        self.assertIn("failures", err)
        self.assertIn("grok", err)
        log = self.logged()
        self.assertIn("plugin install voice@infiquetra-agent-plugins", log)
        self.assertIn("extensions install", log)

    def test_client_all_execute_continues_past_a_planning_failure(self) -> None:
        (self.catalog / ".agents" / "plugins" / "marketplace.json").unlink()
        code, out, err = self.invoke("--client", "all", "--package", "voice", "--execute")
        self.assertEqual(code, 1)
        self.assertIn("failures", err)
        self.assertIn("codex", err)
        log = self.logged()
        self.assertIn("plugin install voice@infiquetra-agent-plugins", log)
        self.assertIn("extensions install", log)


class MuseMarketplaceTest(InstallFixture):
    def row(self, name="voice", marketplace=None, **changes):
        alias = marketplace or muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS
        source = (
            (self.catalog / "build/muse-marketplace/plugins" / name).resolve()
            if alias == muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS
            else self.home
            / ".local/share/muse/plugins/marketplaces"
            / alias
            / "source/plugins"
            / name
        )
        row = {
            "record": {
                "id": name,
                "enabled": True,
                "source": {
                    "marketplace": alias,
                    "path": str(source),
                    "provenance": "marketplace-user-added",
                },
            },
            "valid": True,
            "diagnostics": [],
        }
        row.update(changes)
        return row

    def test_dry_run_stages_and_installs_plugins_without_running_or_writing(
        self,
    ) -> None:
        sentinel = self.home / ".muse/keep"
        sentinel.parent.mkdir()
        sentinel.write_text("keep")
        code, out, err = self.invoke("--client", "muse", "--dry-run")
        self.assertEqual(code, 0, err)
        staging = (self.catalog / "build/muse-marketplace").resolve()
        self.assertIn(str(staging), out)
        self.assertIn(self.command("muse", "plugins", "marketplace", "add", str(staging)), out)
        for name in ("unifi", "voice"):
            self.assertIn(
                self.command(
                    "muse",
                    "plugins",
                    "install",
                    f"{name}@{muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS}",
                ),
                out,
            )
        self.assertNotIn("skills install", out)
        self.assertNotIn("fleet-core@", out)
        self.assertEqual(self.logged(), "")
        self.assertFalse(staging.exists())
        self.assertEqual(sentinel.read_text(), "keep")

    def test_execute_materializes_the_projection_and_registers_it_before_install(
        self,
    ) -> None:
        source = (self.catalog / "plugins/voice/plugin.json").read_bytes()
        staging = self.base / "staged marketplace"
        code, out, err = self.invoke(
            "--client",
            "muse",
            "--package",
            "voice",
            "--staging-dir",
            str(staging),
            "--scope",
            "user",
            "--execute",
        )
        self.assertEqual(code, 0, err)
        manifest = json.loads((staging / ".claude-plugin/marketplace.json").read_text())
        self.assertEqual(manifest["name"], muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS)
        self.assertEqual([row["name"] for row in manifest["plugins"]], ["voice"])
        self.assertFalse((staging / "plugins/voice/plugin.json").exists())
        self.assertTrue((staging / "plugins/voice/.claude-plugin/plugin.json").is_file())
        self.assertEqual((self.catalog / "plugins/voice/plugin.json").read_bytes(), source)
        log = self.logged()
        self.assertLess(log.index("marketplace add"), log.index("plugins install"))
        self.assertNotIn("--scope", log)
        self.assertFalse((self.home / ".config/muse/skills").exists())

    def test_unrestricted_real_catalog_has_twelve_applicable_packages(self) -> None:
        packages = installer.muse_packages(ROOT, installer.discover_packages(ROOT), filtered=False)
        self.assertEqual(len(packages), 12)
        self.assertNotIn("fleet-core", [p.name for p in packages])
        self.assertNotIn("house-style", [p.name for p in packages])
        self.assertIn("orchestrate", [p.name for p in packages])
        self.assertIn("muse", installer.CLIENT_CHOICES)
        self.assertIn("muse", installer.selected_clients("all"))
        self.assertNotIn("muse", installer.SKILL_CLIENTS)

    def test_explicit_non_applicable_packages_are_refused_before_mutation(self) -> None:
        self._package("house-style", [])
        write_json(
            self.catalog / "plugins/house-style/.claude-plugin/plugin.json",
            {"name": "house-style", "outputStyles": "./styles"},
        )
        for name in ("fleet-core", "house-style"):
            for mode in ("--dry-run", "--execute", "--check"):
                with self.subTest(name=name, mode=mode):
                    code, out, err = self.invoke("--client", "muse", "--package", name, mode)
                    self.assertEqual(code, 2)
                    self.assertIn("not installable in Muse", err)
        self.assertEqual(self.logged(), "")
        self.assertFalse((self.catalog / "build").exists())

    def test_a_command_only_package_is_applicable(self) -> None:
        self._package("commands-only", [])
        root = self.catalog / "plugins/commands-only"
        (root / "commands").mkdir()
        (root / "commands/run.md").write_text("run")
        write_json(
            root / ".claude-plugin/plugin.json",
            {"name": "commands-only", "commands": ["./commands/run.md"]},
        )
        code, out, err = self.invoke("--client", "muse", "--package", "commands-only")
        self.assertEqual(code, 0, err)
        self.assertIn("commands-only@", out)

    def test_partial_staging_keeps_unselected_packages(self) -> None:
        self.assertEqual(self.invoke("--client", "muse", "--execute")[0], 0)
        sentinel = self.catalog / "build/muse-marketplace/plugins/unifi/keep"
        sentinel.write_text("unselected")
        code, out, err = self.invoke("--client", "muse", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertEqual(sentinel.read_text(), "unselected")
        self.assertNotIn("unifi@", out)

    def test_a_wrong_marketplace_registration_is_removed_before_add(self) -> None:
        write_json(
            self.home / ".local/share/muse/plugins/marketplaces.json",
            {
                "marketplaces": {
                    muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS: {
                        "source": {"kind": "local", "path": str(self.catalog)}
                    }
                }
            },
        )
        code, out, err = self.invoke("--client", "muse", "--execute")
        self.assertEqual(code, 0, err)
        log = self.logged()
        self.assertLess(log.index("marketplace remove"), log.index("marketplace add"))
        self.assertLess(log.index("marketplace add"), log.index("plugins install"))

    def test_an_existing_staging_registration_is_updated(self) -> None:
        staging = (self.catalog / "build/muse-marketplace").resolve()
        write_json(
            self.home / ".local/share/muse/plugins/marketplaces.json",
            {
                "marketplaces": {
                    muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS: {"source": {"path": str(staging)}}
                }
            },
        )
        code, out, err = self.invoke("--client", "muse")
        self.assertEqual(code, 0, err)
        self.assertIn("marketplace update", out)
        self.assertNotIn("marketplace remove", out)
        self.assertNotIn("marketplace add", out)
        self.assertEqual(self.logged(), "")

    def test_legacy_plugin_migration_is_selected_and_source_proven(self) -> None:
        self.muse_state(
            [
                self.row("voice", MUSE_LEGACY_MARKETPLACE),
                self.row("unifi", MUSE_LEGACY_MARKETPLACE),
                self.row("external", MUSE_LEGACY_MARKETPLACE),
            ]
        )
        code, out, err = self.invoke(
            "--client", "muse", "--package", "voice", "--uninstall-legacy", "--execute"
        )
        self.assertEqual(code, 0, err)
        log = self.logged()
        expected = f"plugins uninstall voice@{MUSE_LEGACY_MARKETPLACE} --scope user"
        self.assertIn(expected, log)
        self.assertNotIn("uninstall unifi", log)
        self.assertNotIn("uninstall external", log)
        self.assertLess(log.index(expected), log.index("plugins install"))

    def test_legacy_flag_dry_run_does_not_call_the_client(self) -> None:
        self.muse_state([self.row("voice", MUSE_LEGACY_MARKETPLACE)])
        code, out, err = self.invoke("--client", "muse", "--uninstall-legacy", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("inspect:", out)
        self.assertEqual(self.logged(), "")
        self.assertFalse((self.catalog / "build").exists())

    def test_legacy_plugin_in_another_marketplace_is_preserved(self) -> None:
        self.muse_state([self.row("voice", "external-marketplace")])
        code, out, err = self.invoke("--client", "muse", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertNotIn("plugins uninstall", self.logged())

    def test_skill_manifest_cleanup_keeps_unselected_and_unsourced_copies(self) -> None:
        skills = self.home / ".config/muse/skills"
        manifest = skills.parent / ".infiquetra-skills.json"
        for name in ("voice", "unifi-network", "unifi-protect"):
            (skills / name).mkdir(parents=True)
        write_json(
            manifest,
            {
                "schema": installer.MUSE_SCHEMA,
                "links": [
                    {
                        "target": str(self.catalog / "plugins/voice/skills/voice"),
                        "link": str(skills / "voice"),
                    },
                    {
                        "target": str(self.base / "infiquetra-claude-plugins/skills/unifi-network"),
                        "link": str(skills / "unifi-network"),
                    },
                ],
            },
        )
        code, out, err = self.invoke(
            "--client", "muse", "--package", "voice", "--uninstall-legacy", "--execute"
        )
        self.assertEqual(code, 0, err)
        self.assertIn("skills uninstall voice --scope user", self.logged())
        self.assertFalse((skills / "voice").exists())
        self.assertTrue((skills / "unifi-network").exists())
        self.assertTrue((skills / "unifi-protect").exists())
        self.assertEqual(len(json.loads(manifest.read_text())["links"]), 1)
        code, out, err = self.invoke(
            "--client", "muse", "--package", "unifi", "--uninstall-legacy", "--execute"
        )
        self.assertEqual(code, 0, err)
        self.assertFalse(manifest.exists())
        self.assertTrue((skills / "unifi-protect").exists())
        self.assertIn("no manifest entry or lock source", out)

    def test_native_skill_lock_proves_custody_and_preserves_other_entries(self) -> None:
        skills = self.home / ".config/muse/skills"
        (skills / "voice").mkdir(parents=True)
        lock = skills / ".muse/lock.json"
        write_json(
            lock,
            {
                "version": 1,
                "skills": {
                    "voice": {
                        "source": {
                            "type": "local",
                            "path": str(self.catalog / "plugins/voice/skills/voice"),
                        }
                    },
                    "external": {"source": {"type": "local", "path": str(self.base / "external")}},
                },
            },
        )
        code, out, err = self.invoke(
            "--client", "muse", "--package", "voice", "--uninstall-legacy", "--execute"
        )
        self.assertEqual(code, 0, err)
        self.assertFalse((skills / "voice").exists())
        self.assertEqual(set(json.loads(lock.read_text())["skills"]), {"external"})

    def test_check_requires_installed_enabled_clean_marketplace_plugins(self) -> None:
        self.muse_state([self.row("voice"), self.row("unifi")], available=["voice", "unifi"])
        code, out, err = self.invoke("--client", "muse", "--check")
        self.assertEqual(code, 0, err)
        self.assertIn("muse voice installed-from-catalog", out)
        self.assertIn("muse fleet-core not-applicable (library)", out)
        self.assertIn("plugins list --json", self.logged())
        self.assertIn("plugins list --available --json", self.logged())
        self.assertNotIn("plugins install", self.logged())
        self.assertFalse((self.catalog / "build").exists())

    def test_check_fails_for_missing_elsewhere_disabled_invalid_or_diagnostic_plugins(
        self,
    ) -> None:
        disabled = self.row()
        disabled["record"]["enabled"] = False
        for row in (
            None,
            self.row(marketplace="external"),
            disabled,
            self.row(valid=False),
            self.row(diagnostics=[{"code": "warning"}]),
            self.row(diagnostics=None),
        ):
            with self.subTest(row=row):
                self.muse_state([] if row is None else [row], available=["voice"])
                code, out, err = self.invoke("--client", "muse", "--package", "voice", "--check")
                self.assertEqual(code, 1, out + err)

    def test_check_rejects_unavailable_or_skipped_catalog_packages(self) -> None:
        for available, skipped in (
            ([], []),
            (
                ["voice"],
                [
                    {
                        "marketplace": muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS,
                        "name": "unselected",
                        "reason": "invalid",
                    }
                ],
            ),
        ):
            with self.subTest(available=available, skipped=skipped):
                self.muse_state([self.row()], available=available, skipped=skipped)
                code, out, err = self.invoke("--client", "muse", "--package", "voice", "--check")
                self.assertEqual(code, 1, out + err)

    def test_external_diagnostics_and_skipped_packages_do_not_fail_our_check(
        self,
    ) -> None:
        self.muse_state(
            [
                self.row(),
                self.row("external", "external", diagnostics=[{"code": "warning"}]),
            ],
            available=["voice"],
            skipped=[{"marketplace": "external", "name": "external"}],
        )
        code, out, err = self.invoke("--client", "muse", "--package", "voice", "--check")
        self.assertEqual(code, 0, err)

    def test_check_rejects_invalid_json_and_malformed_records(self) -> None:
        for raw in ("not json", "[]", "{}", '{"plugins":[{}]}'):
            with self.subTest(raw=raw):
                self.muse_state([], available=["voice"], raw=raw)
                code, out, err = self.invoke("--client", "muse", "--package", "voice", "--check")
                self.assertEqual(code, 1, out + err)

    def test_check_uses_the_binary_override(self) -> None:
        self.muse_state([self.row()], available=["voice"])
        real = self.base / "muse-real"
        real.write_bytes((self.bin / "muse").read_bytes())
        real.chmod(0o755)
        code, out, err = self.invoke(
            "--client",
            "muse",
            "--package",
            "voice",
            "--binary",
            f"muse={real}",
            "--check",
        )
        self.assertEqual(code, 0, err)

    def test_staging_failure_never_registers_or_installs(self) -> None:
        code, out, err = self.invoke(
            "--client", "muse", "--staging-dir", str(self.catalog), "--execute"
        )
        self.assertEqual(code, 1)
        self.assertIn("staging would overwrite", err)
        self.assertEqual(self.logged(), "")

    def test_known_older_parser_forms_are_supported_without_retrying_runtime_failures(
        self,
    ) -> None:
        argv = ("muse", "plugins", "marketplace", "add", "/example/staged")
        self.assertEqual(
            muse_cli.fallback_argv(
                argv, "", "usage: muse plugins marketplace add <name> <source> [--json]"
            ),
            (
                "muse",
                "plugins",
                "marketplace",
                "add",
                muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS,
                "/example/staged",
            ),
        )
        self.assertIsNone(muse_cli.fallback_argv(argv, "", "failed to load marketplace"))
        old = (
            "muse",
            "plugins",
            "uninstall",
            "voice@claude-code-Marketplace",
            "--scope",
            "user",
        )
        self.assertEqual(
            muse_cli.fallback_argv(old, "", "unsupported plugins command `uninstall`"),
            ("muse", "plugins", "remove", "voice"),
        )
        self.assertIsNone(
            muse_cli.fallback_argv(
                (*old[:-1], "project"), "", "unsupported plugins command `uninstall`"
            )
        )

    def test_client_selection_is_required(self) -> None:
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as caught:
            installer.parse_args([])
        self.assertEqual(caught.exception.code, 2)

    def test_local_path_marketplace_provenance_is_verified_against_available_sources(
        self,
    ) -> None:
        source = str(self.base / "staged/plugins/voice")
        row = self.row()
        row["record"]["source"] = {
            "provenance": "marketplace-user-added",
            "path": source,
        }
        installed = json.dumps({"plugins": [row]})
        available = json.dumps(
            {
                "available": [
                    {
                        "name": "voice",
                        "marketplace": muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS,
                        "install": {"source": source},
                    }
                ],
                "skipped": [],
            }
        )
        write_json(
            self.home / muse_cli.MUSE_REGISTRY_RELATIVE,
            {
                "marketplaces": {
                    muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS: {
                        "source": {"path": str(self.base / "staged")}
                    }
                }
            },
        )
        with patch.object(
            installer,
            "muse_json",
            side_effect=[json.loads(installed), json.loads(available)],
        ):
            packages = installer.select_packages(self.catalog, ["voice"])
            self.assertEqual(
                installer.check_muse(packages, self.catalog, self.home, self.base / "staged", {})[
                    0
                ].status,
                "installed-from-catalog",
            )
        row["record"]["source"]["provenance"] = "foreign-import"
        self.assertEqual(muse_cli.source_marketplace(row["record"], json.loads(available)), "")

    def test_conflicting_native_skill_provenance_prevents_removal(self) -> None:
        skills = self.home / ".config/muse/skills"
        dest = skills / "voice"
        dest.mkdir(parents=True)
        (dest / "keep").write_text("unrelated replacement")
        write_json(
            skills.parent / ".infiquetra-skills.json",
            {
                "schema": installer.MUSE_SCHEMA,
                "links": [
                    {
                        "target": str(self.catalog / "plugins/voice/skills/voice"),
                        "link": str(dest),
                    }
                ],
            },
        )
        write_json(
            skills / ".muse/lock.json",
            {"skills": {"voice": {"source": {"path": str(self.base / "unrelated/voice")}}}},
        )
        code, out, err = self.invoke(
            "--client", "muse", "--package", "voice", "--uninstall-legacy", "--execute"
        )
        self.assertEqual(code, 0, err)
        self.assertEqual((dest / "keep").read_text(), "unrelated replacement")
        self.assertNotIn("skills uninstall voice", self.logged())
        self.assertIn("refuse:", out)

    def test_all_stops_muse_dependency_actions_after_staging_failure(self) -> None:
        code, out, err = self.invoke(
            "--client", "all", "--staging-dir", str(self.catalog), "--execute"
        )
        self.assertEqual(code, 1)
        self.assertIn("muse", err)
        self.assertNotIn("plugins install", self.logged())
        self.assertIn("hermes:", out)

    def test_older_marketplace_add_parser_retry_runs_as_a_real_subprocess(self) -> None:
        write_executable(
            self.bin,
            "muse",
            'printf "%s\\n" "$*" >> "$ARGV_LOG"\n'
            'if [ "$1 $2 $3" = "plugins marketplace add" ] && [ "$#" = 4 ]; then\n'
            '  echo "usage: muse plugins marketplace add <name> <source> [--json]" >&2\n'
            "  exit 2\nfi\nexit 0\n",
        )
        code, out, err = self.invoke("--client", "muse", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn("marketplace add infiquetra-claude-plugins", self.logged())
        self.assertIn("plugins install voice@", self.logged())

    def stateful_muse(self):
        script = r"""
import json, os, sys
from pathlib import Path
home = Path(os.environ['HOME'])
registry = home / '.local/share/muse/plugins/marketplaces.json'
state = home / 'fake-muse-installed.json'
def read(path, fallback):
    return json.loads(path.read_text()) if path.exists() else fallback
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
args = sys.argv[1:]
with open(os.environ['ARGV_LOG'], 'a') as stream:
    stream.write(json.dumps(args) + '\n')
entries = read(registry, {'marketplaces': {}})['marketplaces']
rows = read(state, [])
if args[:3] == ['plugins', 'marketplace', 'add']:
    if len(args) == 4:
        print('usage: muse plugins marketplace add <name> <source> [--json]', file=sys.stderr)
        sys.exit(2)
    entries[args[3]] = {'source': {'path': args[4]}}
    write(registry, {'marketplaces': entries})
elif args[:3] == ['plugins', 'marketplace', 'remove']:
    entries.pop(args[3], None)
    write(registry, {'marketplaces': entries})
elif args[:2] == ['plugins', 'install']:
    if '--scope' in args:
        sys.exit(2)
    name, alias = args[2].split('@')
    source = str((Path(entries[alias]['source']['path']) / 'plugins' / name).resolve())
    existing = next((row for row in rows if row['record']['id'] == name), None)
    if existing and existing['record']['source']['path'] != source:
        print('already installed from a different source', file=sys.stderr)
        sys.exit(1)
    rows = [row for row in rows if row['record']['id'] != name]
    rows.append({'record': {'id': name, 'enabled': True, 'source': {
        'provenance': 'marketplace-user-added', 'path': source}}, 'valid': True, 'diagnostics': []})
    write(state, rows)
elif args[:2] == ['plugins', 'uninstall']:
    print('unsupported plugins command `uninstall`', file=sys.stderr)
    sys.exit(2)
elif args[:2] == ['plugins', 'remove']:
    write(state, [row for row in rows if row['record']['id'] != args[2]])
elif args[:2] == ['plugins', 'list']:
    if '--available' not in args:
        print(json.dumps({'plugins': rows}))
    else:
        available = []
        for alias, entry in entries.items():
            source = entry['source'].get('worktree_path', entry['source']['path'])
            marketplace = Path(source) / '.claude-plugin/marketplace.json'
            for plugin in read(marketplace, {'plugins': []})['plugins']:
                available.append({'name': plugin['name'], 'marketplace': alias,
                                  'install': {'source': str((Path(source) / plugin['source']).resolve())}})
        print(json.dumps({'available': available, 'skipped': []}))
"""
        target = self.bin / "muse"
        target.write_text("#!/usr/bin/env python3\n" + script)
        target.chmod(0o755)

    def test_retarget_uninstalls_only_selected_records_before_registration_removal(self) -> None:
        self.stateful_muse()
        stage_a, stage_b = self.base / "stage-a", self.base / "stage-b"
        code, _, err = self.invoke("--client", "muse", "--staging-dir", str(stage_a), "--execute")
        self.assertEqual(code, 0, err)
        code, _, err = self.invoke(
            "--client", "muse", "--package", "voice", "--staging-dir", str(stage_b), "--execute"
        )
        self.assertEqual(code, 0, err)
        rows = json.loads((self.home / "fake-muse-installed.json").read_text())
        paths = {row["record"]["id"]: row["record"]["source"]["path"] for row in rows}
        self.assertEqual(paths["voice"], str((stage_b / "plugins/voice").resolve()))
        self.assertEqual(paths["unifi"], str((stage_a / "plugins/unifi").resolve()))
        commands = [json.loads(line) for line in self.logged().splitlines()]
        removed = commands.index(["plugins", "remove", "voice"])
        retarget = commands.index(
            ["plugins", "marketplace", "remove", muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS]
        )
        self.assertLess(removed, retarget)
        self.assertNotIn(["plugins", "remove", "unifi"], commands)

    def test_legacy_git_registration_under_infiquetra_is_migrated_by_source(self) -> None:
        self.stateful_muse()
        old = self.base / "legacy-stage"
        installer.sync_marketplace.stage_muse_marketplace(self.catalog, old)
        row = self.row()
        row["record"]["source"] = {
            "provenance": "marketplace-user-added",
            "path": str((old / "plugins/voice").resolve()),
        }
        write_json(self.home / "fake-muse-installed.json", [row])
        write_json(
            self.home / muse_cli.MUSE_REGISTRY_RELATIVE,
            {
                "marketplaces": {
                    "infiquetra": {"source": {"path": LEGACY_URL, "worktree_path": str(old)}}
                }
            },
        )
        code, _, err = self.invoke(
            "--client", "muse", "--package", "voice", "--uninstall-legacy", "--execute"
        )
        self.assertEqual(code, 0, err)
        entries = json.loads((self.home / muse_cli.MUSE_REGISTRY_RELATIVE).read_text())[
            "marketplaces"
        ]
        self.assertNotIn("infiquetra", entries)
        self.assertIn(muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS, entries)
        commands = [json.loads(line) for line in self.logged().splitlines()]
        self.assertIn(["plugins", "uninstall", "voice@infiquetra", "--scope", "user"], commands)
        self.assertIn(["plugins", "marketplace", "remove", "infiquetra"], commands)

    def test_partial_legacy_migration_keeps_registration_needed_by_unselected_records(self) -> None:
        self.stateful_muse()
        old = self.base / "legacy-stage"
        installer.sync_marketplace.stage_muse_marketplace(self.catalog, old)
        rows = [self.row(name) for name in ("voice", "unifi")]
        for row in rows:
            row["record"]["source"] = {
                "provenance": "marketplace-user-added",
                "path": str((old / "plugins" / row["record"]["id"]).resolve()),
            }
        write_json(self.home / "fake-muse-installed.json", rows)
        write_json(
            self.home / muse_cli.MUSE_REGISTRY_RELATIVE,
            {
                "marketplaces": {
                    "infiquetra": {"source": {"path": LEGACY_URL, "worktree_path": str(old)}}
                }
            },
        )
        self.assertEqual(
            self.invoke(
                "--client", "muse", "--package", "voice", "--uninstall-legacy", "--execute"
            )[0],
            0,
        )
        entries = json.loads((self.home / muse_cli.MUSE_REGISTRY_RELATIVE).read_text())[
            "marketplaces"
        ]
        self.assertIn("infiquetra", entries)
        self.assertNotIn('["plugins", "remove", "unifi"]', self.logged())

    def test_all_reports_non_applicable_muse_packages_in_every_mode(self) -> None:
        self._package("house-style", [])
        write_json(
            self.catalog / "plugins/house-style/.claude-plugin/plugin.json",
            {"name": "house-style", "outputStyles": "./styles"},
        )
        for package in ("fleet-core", "house-style"):
            for mode in ("--dry-run", "--check", "--execute"):
                with self.subTest(package=package, mode=mode):
                    code, out, err = self.invoke("--client", "all", "--package", package, mode)
                    self.assertIn(code, (0, 1), err)
                    self.assertIn(f"muse {package} not-applicable", out)
                    self.assertIn("claude", out)
                    self.assertIn("codex", out)
                    self.assertNotIn("not installable in Muse", err)
        self.assertNotIn("plugins install", self.logged())

    def test_muse_project_scope_is_refused_before_planning_or_commands(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as caught:
            installer.main(
                [
                    "--catalog",
                    str(self.catalog),
                    "--client",
                    "muse",
                    "--scope",
                    "project",
                    "--execute",
                ]
            )
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("only user scope", err.getvalue())
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(self.logged(), "")
        self.assertFalse((self.catalog / "build").exists())

    def test_check_requires_the_requested_registration_and_source_paths(self) -> None:
        self.muse_state([self.row()], available=["voice"])
        code, out, err = self.invoke(
            "--client",
            "muse",
            "--package",
            "voice",
            "--staging-dir",
            str(self.base / "different"),
            "--check",
        )
        self.assertEqual(code, 1, err)
        self.assertIn("installed-from-elsewhere", out)
        self.assertEqual(self.invoke("--client", "muse", "--package", "voice", "--check")[0], 0)

    def test_check_fails_for_selected_standalone_skills_without_deleting_them(self) -> None:
        self.muse_state([self.row()], available=["voice"])
        dest = self.home / ".config/muse/skills/voice"
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                dest.parent.mkdir(parents=True, exist_ok=True)
                if symlink:
                    dest.symlink_to(self.catalog / "plugins/voice/skills/voice")
                else:
                    dest.mkdir()
                    (dest / "SKILL.md").write_text("collision")
                write_json(
                    dest.parent.parent / ".infiquetra-skills.json",
                    {
                        "schema": installer.MUSE_SCHEMA,
                        "links": [{"link": str(dest), "target": str(self.base / "external")}],
                    },
                )
                code, _, err = self.invoke("--client", "muse", "--package", "voice", "--check")
                self.assertEqual(code, 1)
                self.assertIn(str(dest), err)
                self.assertTrue(dest.exists())
                if symlink:
                    dest.unlink()
                else:
                    import shutil

                    shutil.rmtree(dest)
        other = dest.parent / "unifi-network"
        other.mkdir()
        self.assertEqual(self.invoke("--client", "muse", "--package", "voice", "--check")[0], 0)

    def test_uninstall_api_never_installs_muse_plugins(self) -> None:
        packages = installer.select_packages(self.catalog, ["voice"])
        actions = installer.plan_uninstall(
            "muse",
            packages,
            self.catalog,
            self.home,
            {},
            required=False,
            options=installer.InstallOptions(uninstall_legacy=True),
        )
        self.assertFalse(any(action.argv[1:3] == ("plugins", "install") for action in actions))

    def test_unmarked_staging_is_refused_before_any_client_command(self) -> None:
        stage = self.base / "valuable"
        sentinel = stage / "plugins/precious-data/keep"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("preserved")
        code, _, err = self.invoke("--client", "muse", "--staging-dir", str(stage), "--execute")
        self.assertEqual(code, 1)
        self.assertIn("lacks .infiquetra-muse-staging", err)
        self.assertEqual(sentinel.read_text(), "preserved")
        self.assertEqual(self.logged(), "")

    def test_legacy_source_using_the_catalog_alias_is_not_removed_twice(self) -> None:
        self.stateful_muse()
        old = self.base / "old"
        installer.sync_marketplace.stage_muse_marketplace(self.catalog, old)
        row = self.row()
        row["record"]["source"] = {
            "provenance": "marketplace-user-added",
            "path": str((old / "plugins/voice").resolve()),
        }
        write_json(self.home / "fake-muse-installed.json", [row])
        write_json(
            self.home / muse_cli.MUSE_REGISTRY_RELATIVE,
            {
                "marketplaces": {
                    muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS: {
                        "source": {"path": LEGACY_URL, "worktree_path": str(old)}
                    }
                }
            },
        )
        code, _, err = self.invoke(
            "--client", "muse", "--package", "voice", "--uninstall-legacy", "--execute"
        )
        self.assertEqual(code, 0, err)
        commands = [json.loads(line) for line in self.logged().splitlines()]
        self.assertEqual(
            commands.count(
                ["plugins", "marketplace", "remove", muse_cli.MUSE_CATALOG_MARKETPLACE_ALIAS]
            ),
            1,
        )
