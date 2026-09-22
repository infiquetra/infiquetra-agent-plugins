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
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_client as installer  # noqa: E402


LEGACY_URL = "https://github.com/infiquetra/infiquetra-claude-plugins.git"
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
        self._saved = {
            key: os.environ.get(key) for key in ("HOME", "PATH", "ARGV_LOG")
        }
        os.environ["HOME"] = str(self.home)
        os.environ["PATH"] = os.pathsep.join([str(self.bin), os.environ.get("PATH", "")])
        os.environ["ARGV_LOG"] = str(self.argv_log)
        self.addCleanup(self._restore_env)

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
            self.command("claude", "plugin", "marketplace", "add", str(self.catalog.resolve())),
            out,
        )
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
        self.assertIn(f"already registered at {self.catalog.resolve()}", out)
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

    def test_execute_invokes_the_stub_and_does_not_edit_the_marketplace_file(self) -> None:
        code, _out, err = self.invoke("--client", "claude", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        log = self.logged()
        self.assertIn("plugin marketplace add", log)
        self.assertIn("plugin install voice@infiquetra-agent-plugins", log)
        self.assertFalse((self.home / ".claude").exists())

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
        self.assertIn("claude fleet-core absent", out)
        self.assertEqual(code, 1)

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
        self.assertIn("codex fleet-core absent", out)

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
        self.assertIn("cursor fleet-core absent", out)
        self.assertEqual(code, 1)

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

    def test_install_preserves_keys_the_client_already_wrote(self) -> None:
        record = self.home / ".qwen/extensions/voice/.qwen-extension-install.json"
        write_json(record, {"source": LEGACY_URL, "type": "git", "marketplaceConfig": {"name": "kept"}})
        code, _out, err = self.invoke("--client", "qwen", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        payload = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(payload["marketplaceConfig"], {"name": "kept"})
        self.assertEqual(payload["type"], "local")
        self.assertTrue(payload["source"].endswith("/plugins/voice"))

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
        self.assertIn("qwen fleet-core installed-from-elsewhere (unsourced)", out)
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
        self.assertIn("grok fleet-core absent", out)
        self.assertEqual(code, 1)

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

    def test_muse_installs_at_user_scope_and_records_a_manifest(self) -> None:
        code, out, err = self.invoke("--client", "muse", "--package", "voice", "--execute")
        self.assertEqual(code, 0, err)
        target = str((self.catalog / "plugins/voice/skills/voice").resolve())
        self.assertIn(self.command("muse", "skills", "install", target, "--scope", "user"), out)
        manifest = self.home / ".config/muse/.infiquetra-skills.json"
        document = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(document["links"][0]["target"], target)

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

    def test_muse_uninstall_uses_the_client_and_refuses_an_unsourced_directory(self) -> None:
        unsourced = self.home / ".config/muse/skills/voice"
        unsourced.mkdir(parents=True)
        (unsourced / "keep").write_text("keep", encoding="utf-8")
        legacy = self.base / "infiquetra-claude-plugins" / "skills" / "unifi-network"
        copied = self.home / ".config/muse/skills/unifi-network"
        copied.mkdir(parents=True)
        (copied / "copied").write_text("copied", encoding="utf-8")
        write_json(
            self.home / ".config/muse/.infiquetra-skills.json",
            {
                "schema": installer.MUSE_SCHEMA,
                "links": [{"target": str(legacy), "link": str(copied)}],
            },
        )
        code, out, err = self.invoke("--client", "muse", "--uninstall-legacy", "--execute")
        self.assertEqual(code, 0, err)
        self.assertIn(self.command("muse", "skills", "uninstall", "unifi-network"), out)
        self.assertFalse(copied.exists())
        self.assertTrue((unsourced / "keep").is_file())
        self.assertIn("no manifest entry", out)


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
        self.assertIn("agy fleet-core absent", out)
        self.assertEqual(code, 1)

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
