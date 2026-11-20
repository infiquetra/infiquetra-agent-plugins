"""Enforced closeout: multi-harness upgrade, prune, and standalone execution.

The synthetic home, XDG directories, and client binaries all live under the
test temporary directory. Client names on PATH are hermetic shims. Nothing in
this module reads or writes the operator's real home.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import check_repo  # noqa: E402
import install_client as installer  # noqa: E402
import sync_marketplace  # noqa: E402


BASE_COMMIT = "5550acfbc3ffe1eaf2016c17b007c98e80fb46dc"
FORMULA_SHA256 = "528540c6958cf628d5cdf3ea44dc7fff45c16862ad11412c56a945ceb7e4e839"
SCHEMA_SHA256 = "a505807b505fbb65f98c58f36375256dd99b7afb2e7f3346bac9f79a9b90acd8"
LEAN_PACKAGES = ("reviews", "plan", "investigate")
FULL_CLIENTS = ("claude", "agy", "codex", "opencode", "hermes")
LEAN_CLIENTS = ("cursor", "muse", "grok")
RETIRED_MODULES = frozenset(
    {
        "saga",
        "orchestrate",
        "agy",
        "codex",
        "voice",
        "house_style",
        "hermes_profile_evolution",
        "redis_channel",
    }
)
FOREIGN_MARKET = "https://github.com/example/other"
LEGACY_MARKET = "https://github.com/infiquetra/infiquetra-claude-plugins.git"

SHIM_SOURCE = r'''
import json
import os
import shlex
import sys
from pathlib import Path

ALIAS = "infiquetra-claude-plugins"
MARKET = "infiquetra-agent-plugins"


def home() -> Path:
    return Path(os.environ["HOME"])


def catalog() -> Path:
    return Path(os.environ["CATALOG"])


def log_call() -> None:
    path = os.environ.get("SHIM_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(shlex.join(sys.argv) + "\n")


def read_json(path: Path, fallback: dict) -> dict:
    if not path.is_file():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def owned(source: str) -> bool:
    if not source:
        return False
    root = str(catalog())
    if source == root or source.startswith(root + os.sep):
        return True
    lowered = source.lower()
    return (
        "infiquetra/infiquetra-agent-plugins" in lowered
        or "infiquetra/infiquetra-claude-plugins" in lowered
    )


def claude_known() -> Path:
    return home() / ".claude" / "plugins" / "known_marketplaces.json"


def claude_installed() -> Path:
    return home() / ".claude" / "plugins" / "installed_plugins.json"


def claude_settings() -> Path:
    return home() / ".claude" / "settings.json"


def claude_marketplace_add(slug: str) -> None:
    known = read_json(claude_known(), {})
    known[MARKET] = {"source": {"source": "github", "repo": slug}}
    write_json(claude_known(), known)


def claude_enable(plugin_id: str, present: bool) -> None:
    installed = read_json(claude_installed(), {"plugins": {}})
    plugins = installed.setdefault("plugins", {})
    settings = read_json(claude_settings(), {})
    enabled = settings.setdefault("enabledPlugins", {})
    if present:
        plugins[plugin_id] = [{"version": "0.0.0"}]
        enabled[plugin_id] = True
        name = plugin_id.split("@", 1)[0]
        target = catalog() / "plugins" / name
        cache = home() / ".claude" / "plugins" / "cache" / MARKET / name
        if target.is_dir() and not cache.exists() and not cache.is_symlink():
            cache.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(target, cache)
    else:
        plugins.pop(plugin_id, None)
        enabled.pop(plugin_id, None)
    write_json(claude_installed(), installed)
    write_json(claude_settings(), settings)


def load_codex() -> list[tuple[str, list[str]]]:
    path = home() / ".codex" / "config.toml"
    if not path.is_file():
        return []
    tables: list[tuple[str, list[str]]] = []
    header: str | None = None
    body: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            if header is not None:
                tables.append((header, body))
            header = line[1:-1].strip()
            body = []
            continue
        if header is not None and line:
            body.append(line)
    if header is not None:
        tables.append((header, body))
    return tables


def dump_codex(tables: list[tuple[str, list[str]]]) -> None:
    path = home() / ".codex" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for header, body in tables:
        lines.append("[" + header + "]")
        lines.extend(body)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def codex_marketplace_add(source: str) -> None:
    header = "marketplaces." + MARKET
    tables = [(name, body) for name, body in load_codex() if name != header]
    tables.append((header, ['source = "' + source + '"']))
    dump_codex(tables)


def codex_plugin(plugin_id: str, enabled: bool | None) -> None:
    header = 'plugins."' + plugin_id + '"'
    tables = [(name, body) for name, body in load_codex() if name != header]
    if enabled is not None:
        tables.append((header, ["enabled = " + ("true" if enabled else "false")]))
    dump_codex(tables)


def grok_registry() -> Path:
    return home() / ".grok" / "installed-plugins" / "registry.json"


def grok_source(entry: dict) -> str:
    market = entry.get("marketplace") if isinstance(entry.get("marketplace"), dict) else {}
    source = market.get("source_url_or_path") if isinstance(market, dict) else ""
    if isinstance(source, str) and source:
        return source
    kind = entry.get("kind") if isinstance(entry.get("kind"), dict) else {}
    source = kind.get("source_path") if isinstance(kind, dict) else ""
    return source if isinstance(source, str) else ""


def grok_uninstall(name: str) -> None:
    document = read_json(grok_registry(), {"repos": {}})
    for entry in document.get("repos", {}).values():
        if isinstance(entry, dict) and owned(grok_source(entry)):
            plugins = entry.get("plugins")
            if isinstance(plugins, dict):
                plugins.pop(name, None)
    write_json(grok_registry(), document)


def grok_install(package: str) -> None:
    document = read_json(grok_registry(), {"repos": {}})
    repos = document.setdefault("repos", {})
    chosen = None
    for entry in repos.values():
        if isinstance(entry, dict) and owned(grok_source(entry)):
            chosen = entry
            break
    if chosen is None:
        chosen = {"kind": {"source_path": str(catalog())}, "plugins": {}}
        repos["catalog"] = chosen
    plugins = chosen.setdefault("plugins", {})
    plugins[Path(package).name] = {}
    write_json(grok_registry(), document)


def cursor_add() -> None:
    destination = (
        home()
        / ".cursor"
        / "plugins"
        / "marketplaces"
        / "github.com"
        / "infiquetra"
        / "infiquetra-agent-plugins"
        / ".claude-plugin"
    )
    destination.mkdir(parents=True, exist_ok=True)
    source = catalog() / ".claude-plugin" / "marketplace.json"
    (destination / "marketplace.json").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def agy_install(package: str) -> None:
    destination = home() / ".gemini" / "config" / "plugins" / Path(package).name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        return
    os.symlink(package, destination)


def agy_uninstall(name: str) -> None:
    destination = home() / ".gemini" / "config" / "plugins" / name
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
        return
    if not destination.is_dir():
        return
    resolved = destination.resolve()
    root = catalog().resolve()
    if resolved == root or root in resolved.parents:
        raise SystemExit("refusing to delete the catalog through an agy placement")
    import shutil
    shutil.rmtree(destination)


def muse_registry() -> Path:
    return home() / ".local" / "share" / "muse" / "plugins" / "marketplaces.json"


def muse_state() -> Path:
    return home() / ".local" / "share" / "muse" / "e2e-installed.json"


def muse_names() -> list[str]:
    document = read_json(muse_state(), {"installed": []})
    names = document.get("installed", [])
    return [name for name in names if isinstance(name, str)]


def muse_set(names: list[str]) -> None:
    write_json(muse_state(), {"installed": names})


def muse_root() -> Path | None:
    document = read_json(muse_registry(), {"marketplaces": {}})
    entry = document.get("marketplaces", {}).get(ALIAS)
    if not isinstance(entry, dict):
        return None
    source = entry.get("source")
    if isinstance(source, str):
        return Path(source)
    if isinstance(source, dict) and isinstance(source.get("path"), str):
        return Path(source["path"])
    return None


def muse_add(staging: str) -> None:
    document = read_json(muse_registry(), {"marketplaces": {}})
    markets = document.setdefault("marketplaces", {})
    markets[ALIAS] = {"source": {"path": staging}}
    write_json(muse_registry(), document)


def muse_remove_market(alias: str) -> None:
    document = read_json(muse_registry(), {"marketplaces": {}})
    markets = document.setdefault("marketplaces", {})
    markets.pop(alias, None)
    write_json(muse_registry(), document)


def muse_install(plugin_id: str) -> None:
    name = plugin_id.split("@", 1)[0]
    names = muse_names()
    if name not in names:
        names.append(name)
    muse_set(names)


def muse_uninstall(plugin_id: str) -> None:
    name = plugin_id.split("@", 1)[0]
    muse_set([item for item in muse_names() if item != name])


def muse_list() -> None:
    root = muse_root()
    rows = []
    if root is not None:
        for name in muse_names():
            rows.append(
                {
                    "record": {
                        "id": name + "@" + ALIAS,
                        "enabled": True,
                        "source": {
                            "marketplace": ALIAS,
                            "path": str(root / "plugins" / name),
                            "provenance": "marketplace-user-added",
                        },
                    },
                    "valid": True,
                    "diagnostics": [],
                }
            )
    sys.stdout.write(json.dumps({"plugins": rows}) + "\n")


def muse_available() -> None:
    offered = [
        {"name": name, "marketplace": ALIAS}
        for name in muse_names()
    ]
    sys.stdout.write(json.dumps({"available": offered, "skipped": []}) + "\n")


def main() -> int:
    log_call()
    client = Path(sys.argv[0]).name
    args = sys.argv[1:]
    if client == "claude" and args[:3] == ["plugin", "marketplace", "add"] and len(args) == 4:
        claude_marketplace_add(args[3])
        return 0
    if client == "claude" and args[:2] == ["plugin", "install"] and len(args) == 3:
        claude_enable(args[2], True)
        return 0
    if client == "claude" and args[:2] == ["plugin", "uninstall"] and len(args) == 3:
        claude_enable(args[2], False)
        return 0
    if client == "codex" and args[:3] == ["plugin", "marketplace", "add"] and len(args) == 4:
        codex_marketplace_add(args[3])
        return 0
    if client == "codex" and args[:2] == ["plugin", "add"] and len(args) == 3:
        codex_plugin(args[2], True)
        return 0
    if client == "codex" and args[:2] == ["plugin", "remove"] and len(args) == 3:
        codex_plugin(args[2], None)
        return 0
    if client == "cursor-agent" and args[:3] == ["plugin", "marketplace", "add"] and len(args) == 4:
        cursor_add()
        return 0
    if client == "grok" and args[:2] == ["plugin", "install"] and args[-1:] == ["--trust"]:
        grok_install(args[2])
        return 0
    if client == "grok" and args[:2] == ["plugin", "uninstall"] and args[-1:] == ["--confirm"]:
        grok_uninstall(args[2])
        return 0
    if client == "agy" and args[:2] == ["plugin", "install"] and len(args) == 3:
        agy_install(args[2])
        return 0
    if client == "agy" and args[:2] == ["plugin", "uninstall"] and len(args) == 3:
        agy_uninstall(args[2])
        return 0
    if client == "muse" and args == ["plugins", "list", "--json"]:
        muse_list()
        return 0
    if client == "muse" and args == ["plugins", "list", "--available", "--json"]:
        muse_available()
        return 0
    if client == "muse" and args[:3] == ["plugins", "marketplace", "add"] and len(args) == 4:
        muse_add(args[3])
        return 0
    if client == "muse" and args[:3] == ["plugins", "marketplace", "remove"] and len(args) == 4:
        muse_remove_market(args[3])
        return 0
    if client == "muse" and args[:2] == ["plugins", "install"] and len(args) == 3:
        muse_install(args[2])
        return 0
    if client == "muse" and args[:2] == ["plugins", "uninstall"]:
        if len(args) >= 3:
            muse_uninstall(args[2])
        return 0
    sys.stderr.write("unhandled shim command: " + shlex.join(sys.argv) + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _chmod_private(path: Path) -> None:
    if path.is_symlink():
        return
    path.chmod(0o755 if path.is_dir() else 0o644)
    if path.is_dir():
        for child in path.iterdir():
            _chmod_private(child)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o644)


class PostSagaE2ERolloutTest(unittest.TestCase):
    """Upgrade a legacy home, then run the installed skills outside this repo."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._old_umask = os.umask(0o022)
        cls.addClassCleanup(lambda: os.umask(cls._old_umask))
        cls._temporary = tempfile.TemporaryDirectory(prefix="post-saga-e2e-")
        cls.addClassCleanup(cls._temporary.cleanup)
        cls.base = Path(cls._temporary.name)
        cls.home = cls.base / "home"
        cls.home.mkdir()
        cls.bin = cls.base / "bin"
        cls.bin.mkdir()
        cls.shim_log = cls.base / "shim.log"
        cls.repo = REPO.resolve()
        cls._park_staging()
        packages = installer.discover_packages(cls.repo)
        cls.active = [package.name for package in packages if not installer.is_library_package(package)]
        cls.library = [package.name for package in packages if installer.is_library_package(package)]
        cls._install_shims()
        cls._seed_legacy_home()
        env = cls._installer_env()
        cls.prune = cls._invoke(env, "--client", "all", "--prune-retired", "--execute")
        cls.install = cls._invoke(env, "--client", "all", "--execute")
        cls.check = cls._invoke(env, "--client", "all", "--check")

    @classmethod
    def _park_staging(cls) -> None:
        staging = cls.repo / sync_marketplace.MUSE_STAGING_DEFAULT
        backup = cls.base / "muse-staging-backup"
        cls._staging = staging
        cls._staging_existed = staging.exists()
        if staging.exists():
            staging.rename(backup)

        def restore() -> None:
            if staging.exists():
                import shutil

                shutil.rmtree(staging)
            if backup.exists():
                staging.parent.mkdir(parents=True, exist_ok=True)
                backup.rename(staging)

        cls.addClassCleanup(restore)

    @classmethod
    def _install_shims(cls) -> None:
        shim = cls.bin / "harness-shim"
        shim.write_text("#!/usr/bin/env python3\n" + SHIM_SOURCE, encoding="utf-8")
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        for name in set(installer.CLIENT_BINARIES.values()):
            link = cls.bin / name
            link.symlink_to(shim)

    @classmethod
    def _installer_env(cls) -> dict[str, str]:
        env = os.environ.copy()
        env["HOME"] = str(cls.home)
        env["CATALOG"] = str(cls.repo)
        env["SHIM_LOG"] = str(cls.shim_log)
        env["XDG_CONFIG_HOME"] = str(cls.home / ".config")
        env["XDG_DATA_HOME"] = str(cls.home / ".local" / "share")
        env["XDG_CACHE_HOME"] = str(cls.home / ".cache")
        env["XDG_STATE_HOME"] = str(cls.home / ".local" / "state")
        env["PATH"] = os.pathsep.join([str(cls.bin), env.get("PATH", "")])
        env.pop("AGY_COMPANY_HOME", None)
        return env

    @classmethod
    def _invoke(cls, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(cls.repo / "scripts" / "install_client.py"), "--catalog", str(cls.repo), *args],
            cwd=cls.repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    @classmethod
    def _seed_legacy_home(cls) -> None:
        catalog = cls.repo
        retired = installer.RETIRED_PACKAGES
        skills = installer.SAGA_SKILL_NAMES
        cls.foreign_skill = cls.base / "foreign-skill"
        cls.foreign_skill.mkdir()
        (cls.foreign_skill / "SKILL.md").write_text("foreign-skill\n", encoding="utf-8")
        cls.kept_bytes: dict[str, bytes] = {}

        def seed_skill_client(root: Path, manifest: Path, schema: str, kept_name: str) -> None:
            skill_root = root / "skills"
            skill_root.mkdir(parents=True)
            links = []
            for name in skills:
                link = skill_root / name
                link.symlink_to(catalog / "plugins" / "saga" / "skills" / name)
                links.append({"target": str(catalog / "plugins" / "saga" / "skills" / name), "link": str(link)})
            foreign = skill_root / "foreign-notes"
            foreign.symlink_to(cls.foreign_skill)
            links.append({"target": str(cls.foreign_skill), "link": str(foreign)})
            kept = skill_root / "kept-skill"
            kept.mkdir()
            payload = (kept_name + "\n").encode()
            (kept / "KEEP").write_bytes(payload)
            cls.kept_bytes[str(kept / "KEEP")] = payload
            _write_json(manifest, {"schema": schema, "links": links})

        seed_skill_client(
            cls.home / ".config" / "opencode",
            cls.home / ".config" / "opencode" / ".infiquetra-plugins.json",
            installer.OPENCODE_SCHEMA,
            "kept-opencode",
        )
        seed_skill_client(
            cls.home / ".hermes",
            cls.home / ".hermes" / ".infiquetra-skills.json",
            installer.HERMES_SCHEMA,
            "kept-hermes",
        )
        seed_skill_client(
            cls.home / ".config" / "muse",
            cls.home / ".config" / "muse" / ".infiquetra-skills.json",
            installer.MUSE_SCHEMA,
            "kept-muse",
        )

        plugins_root = cls.home / ".gemini" / "config" / "plugins"
        packages = {}
        for name in retired:
            directory = plugins_root / name
            directory.mkdir(parents=True)
            (directory / "owned").write_text("retired\n", encoding="utf-8")
            packages[name] = {"source": str((catalog / "plugins" / name).resolve())}
        foreign_plugin = plugins_root / "foreign-plugin"
        foreign_plugin.mkdir()
        (foreign_plugin / "keep").write_text("foreign-plugin\n", encoding="utf-8")
        cls.kept_bytes[str(foreign_plugin / "keep")] = b"foreign-plugin\n"
        packages["foreign-plugin"] = {"source": FOREIGN_MARKET}
        unsourced = plugins_root / "unsourced-plugin"
        unsourced.mkdir()
        (unsourced / "keep").write_text("unsourced-plugin\n", encoding="utf-8")
        cls.kept_bytes[str(unsourced / "keep")] = b"unsourced-plugin\n"
        _write_json(
            plugins_root / ".infiquetra-install.json",
            {"schema": installer.AGY_SCHEMA, "packages": packages},
        )

        installed = {
            f"{name}@{installer.marketplace_name(catalog)}": [{"version": "0.0.0"}]
            for name in retired
        }
        installed["my-notes@foreign-market"] = [{"version": "9.9.9"}]
        _write_json(
            cls.home / ".claude" / "plugins" / "installed_plugins.json",
            {"plugins": installed},
        )
        _write_json(
            cls.home / ".claude" / "plugins" / "known_marketplaces.json",
            {
                installer.marketplace_name(catalog): {
                    "source": {"source": "github", "repo": installer.CATALOG_SLUG}
                },
                "foreign-market": {"source": {"source": "github", "repo": "example/other"}},
            },
        )
        _write_json(
            cls.home / ".claude" / "settings.json",
            {
                "enabledPlugins": {
                    **{f"{name}@{installer.marketplace_name(catalog)}": True for name in retired},
                    "my-notes@foreign-market": True,
                }
            },
        )

        codex_lines = [
            f"[marketplaces.{installer.marketplace_name(catalog)}]",
            f'source = "{catalog}"',
            "",
            "[marketplaces.foreign]",
            f'source = "{FOREIGN_MARKET}"',
            "",
        ]
        for name in retired:
            codex_lines.extend(
                [f'[plugins."{name}@{installer.marketplace_name(catalog)}"]', "enabled = true", ""]
            )
        codex_lines.extend(['[plugins."my-notes@foreign"]', "enabled = true", ""])
        codex_config = cls.home / ".codex" / "config.toml"
        codex_config.parent.mkdir(parents=True, exist_ok=True)
        codex_config.write_text("\n".join(codex_lines), encoding="utf-8")

        _write_json(
            cls.home / ".grok" / "installed-plugins" / "registry.json",
            {
                "repos": {
                    "owned": {
                        "kind": {"source_path": str(catalog)},
                        "plugins": {name: {} for name in retired},
                    },
                    "foreign": {
                        "marketplace": {"source_url_or_path": FOREIGN_MARKET},
                        "plugins": {"my-notes": {}},
                    },
                }
            },
        )

        legacy_cursor = (
            cls.home
            / ".cursor"
            / "plugins"
            / "marketplaces"
            / "github.com"
            / "infiquetra"
            / "infiquetra-claude-plugins"
        )
        legacy_cursor.mkdir(parents=True)
        (legacy_cursor / "LEGACY").write_text("leave-this-cache\n", encoding="utf-8")
        cls.kept_bytes[str(legacy_cursor / "LEGACY")] = b"leave-this-cache\n"

        staging = cls._staging
        staged_plugins = staging / "plugins"
        for name in retired:
            directory = staged_plugins / name
            directory.mkdir(parents=True)
            (directory / "owned").write_text("staged-retired\n", encoding="utf-8")
        foreign_bundle = staged_plugins / "foreign-bundle"
        foreign_bundle.mkdir(parents=True)
        (foreign_bundle / "keep").write_text("foreign-bundle-keep\n", encoding="utf-8")
        cls.kept_bytes[str(foreign_bundle / "keep")] = b"foreign-bundle-keep\n"
        manifest = staging / ".claude-plugin"
        manifest.mkdir(parents=True, exist_ok=True)
        _write_json(
            manifest / "marketplace.json",
            {
                "plugins": [
                    {"name": name, "source": f"./plugins/{name}"}
                    for name in retired
                ]
            },
        )
        _write_json(
            staging / ".infiquetra-muse-staging",
            {"version": 1, "catalog": str(catalog), "packages": list(retired)},
        )
        _chmod_private(staging)
        _write_json(
            cls.home / ".local" / "share" / "muse" / "plugins" / "marketplaces.json",
            {
                "marketplaces": {
                    "old-claude": {"source": LEGACY_MARKET},
                    "foreign-mkt": {"source": FOREIGN_MARKET},
                }
            },
        )

    def _failure_text(self, completed: subprocess.CompletedProcess[str]) -> str:
        shim = self.shim_log.read_text(encoding="utf-8") if self.shim_log.is_file() else ""
        return f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}\nshim:\n{shim}"

    def test_legacy_home_upgrades_cleanly_with_prune_retired_across_full_and_lean_tiers(self) -> None:
        self.assertEqual(len(installer.RETIRED_PACKAGES), 8)
        self.assertEqual(len(installer.SAGA_SKILL_NAMES), 15)
        self.assertEqual(self.library, ["fleet-core"])
        self.assertEqual(len(self.active), 11)
        self.assertEqual(self.prune.returncode, 0, self._failure_text(self.prune))
        self.assertEqual(self.install.returncode, 0, self._failure_text(self.install))
        self.assertEqual(self.check.returncode, 0, self._failure_text(self.check))

        live_skills = {
            path.name
            for path in self.repo.glob("plugins/*/skills/*")
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        for root in (
            self.home / ".config" / "opencode" / "skills",
            self.home / ".hermes" / "skills",
            self.home / ".config" / "muse" / "skills",
        ):
            for name in installer.SAGA_SKILL_NAMES:
                link = root / name
                if link.is_symlink():
                    self.assertNotIn("/plugins/saga/", os.readlink(link), str(link))
                if name not in live_skills:
                    self.assertFalse(link.exists(), f"{link} still occupies a retired saga skill name")
            for child in root.iterdir():
                if child.is_symlink():
                    target = os.readlink(child)
                    for package in installer.RETIRED_PACKAGES:
                        self.assertNotIn(f"/plugins/{package}/", target, str(child))

        for name in installer.RETIRED_PACKAGES:
            self.assertFalse((self.home / ".gemini" / "config" / "plugins" / name).exists(), name)
            self.assertFalse((self._staging / "plugins" / name).exists(), name)
        self.assertEqual(
            (self.home / ".gemini" / "config" / "plugins" / "foreign-plugin" / "keep").read_bytes(),
            self.kept_bytes[str(self.home / ".gemini" / "config" / "plugins" / "foreign-plugin" / "keep")],
        )
        self.assertEqual(
            (self.home / ".gemini" / "config" / "plugins" / "unsourced-plugin" / "keep").read_bytes(),
            b"unsourced-plugin\n",
        )
        for kept in self.kept_bytes:
            self.assertEqual(Path(kept).read_bytes(), self.kept_bytes[kept], kept)
        self.assertEqual((self.foreign_skill / "SKILL.md").read_text(encoding="utf-8"), "foreign-skill\n")
        for client_root in (self.home / ".config" / "opencode", self.home / ".hermes"):
            foreign = client_root / "skills" / "foreign-notes"
            self.assertTrue(foreign.is_symlink(), str(foreign))
            self.assertEqual(foreign.resolve(), self.foreign_skill.resolve())

        installed = json.loads(
            (self.home / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8")
        )
        market = installer.marketplace_name(self.repo)
        for name in installer.RETIRED_PACKAGES:
            self.assertNotIn(f"{name}@{market}", installed["plugins"])
        self.assertIn("my-notes@foreign-market", installed["plugins"])
        codex = (self.home / ".codex" / "config.toml").read_text(encoding="utf-8")
        for name in installer.RETIRED_PACKAGES:
            self.assertNotIn(f'[plugins."{name}@{market}"]', codex)
        self.assertIn('[plugins."my-notes@foreign"]', codex)
        grok = json.loads(
            (self.home / ".grok" / "installed-plugins" / "registry.json").read_text(encoding="utf-8")
        )
        owned_plugins = grok["repos"]["owned"]["plugins"]
        for name in installer.RETIRED_PACKAGES:
            self.assertNotIn(name, owned_plugins)
        self.assertIn("my-notes", grok["repos"]["foreign"]["plugins"])
        muse_markets = json.loads(
            (self.home / ".local" / "share" / "muse" / "plugins" / "marketplaces.json").read_text(
                encoding="utf-8"
            )
        )["marketplaces"]
        self.assertNotIn("old-claude", muse_markets)
        self.assertIn("foreign-mkt", muse_markets)

        lines = set(self.check.stdout.splitlines())
        self.assertTrue(any(line.startswith("cursor marketplace whole-repository") for line in lines))
        for client in FULL_CLIENTS:
            for name in self.active:
                self.assertIn(f"{client} {name} installed-from-catalog", lines, client + " " + name)
            self.assertIn(f"{client} fleet-core not-applicable (library)", lines)
        for client in LEAN_CLIENTS:
            for name in LEAN_PACKAGES:
                self.assertIn(f"{client} {name} installed-from-catalog", lines)
            for name in self.active:
                if name not in LEAN_PACKAGES:
                    self.assertIn(f"{client} {name} not-applicable (tier)", lines)
            self.assertIn(f"{client} fleet-core not-applicable (library)", lines)

    def test_installed_reviews_and_plan_execute_standalone_from_opencode_hermes_and_claude_layouts(
        self,
    ) -> None:
        self.assertEqual(self.install.returncode, 0, self._failure_text(self.install))
        target = self.base / "target-repo"
        self._git_repo(target)
        audit = self.base / "audit"
        audit.mkdir()
        (audit / "sitecustomize.py").write_text(
            textwrap.dedent(
                """\
                import os
                import sys

                _LOG = os.environ.get("IMPORT_AUDIT_LOG", "")
                _FORBIDDEN = {"saga", "orchestrate"}

                def _note(fullname):
                    if not _LOG:
                        return
                    if any(part in _FORBIDDEN for part in fullname.split(".")):
                        with open(_LOG, "a", encoding="utf-8") as handle:
                            handle.write(fullname + "\\n")

                class _Finder:
                    def find_spec(self, fullname, path, target=None):
                        _note(fullname)
                        return None

                sys.meta_path.insert(0, _Finder())
                """
            ),
            encoding="utf-8",
        )
        audit_log = self.base / "imports.log"
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        env["XDG_CONFIG_HOME"] = str(self.home / ".config")
        env["XDG_DATA_HOME"] = str(self.home / ".local" / "share")
        env["XDG_CACHE_HOME"] = str(self.home / ".cache")
        env["XDG_STATE_HOME"] = str(self.home / ".local" / "state")
        env["PYTHONPATH"] = str(audit)
        env["IMPORT_AUDIT_LOG"] = str(audit_log)
        env["GIT_CONFIG_GLOBAL"] = str(self.base / "empty-gitconfig")
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        env["SEMGREP_ENABLE_VERSION_CHECK"] = "0"
        for name in ("TYPESAFE_API_KEY", "TYPESAFE_TRANSPORT", "AGY_COMPANY_HOME"):
            env.pop(name, None)
        (self.base / "empty-gitconfig").write_text("", encoding="utf-8")

        profile = self.base / "profile.json"
        profile.write_text(json.dumps({"schema": "repository_profile.v1"}) + "\n", encoding="utf-8")
        builder = self.base / "builder.json"
        builder.write_text(
            json.dumps(
                {
                    "kind": "builder_record",
                    "schema": "review_records.v1",
                    "unit": "U9",
                    "acceptance_criteria": [
                        {"id": "AC-1", "text": "The changed line is reviewed.", "checks": ["line"]}
                    ],
                    "declarations": [],
                    "reasons": [],
                }
            ),
            encoding="utf-8",
        )
        plan = self._complete_plan(target)
        incomplete = target / "docs" / "plans" / "incomplete.md"
        incomplete.write_text("# Draft\n\nTBD\n", encoding="utf-8")
        readme = target / "README.md"
        readme.write_text("# Notes\n", encoding="utf-8")
        doc = target / "docs" / "brainstorms" / "example.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("A local reader for one committed file.\n", encoding="utf-8")
        base, head = self._revisions(target)

        for layout, roots in self._layouts().items():
            with self.subTest(layout=layout):
                reviews = roots["reviews"]
                plan_script = roots["plan"]
                hook = roots["hook"]
                ideate = roots["ideate"]
                brainstorm = roots["brainstorm"]
                for script in (reviews / "review_command.py", reviews / "security_scan.py", reviews / "lifecycle_review.py", plan_script, hook, ideate, brainstorm):
                    self.assertTrue(script.is_file(), script)
                    self.assertTrue(str(script).startswith(str(self.home)), script)

                audit_log.write_text("", encoding="utf-8")
                packet = self.base / f"packet-{layout}"
                prepared = self._python(
                    env,
                    reviews / "review_command.py",
                    "prepare",
                    "--repo",
                    str(target),
                    "--base",
                    base,
                    "--head",
                    head,
                    "--profile",
                    str(profile),
                    "--builder-record",
                    str(builder),
                    "--out",
                    str(packet),
                    "--home",
                    str(self.home),
                    cwd=self.base,
                )
                self.assertEqual(prepared.returncode, 0, prepared.stderr)
                self.assertTrue((packet / "grades.json").is_file())
                self.assertNotIn("Traceback", prepared.stderr)

                scan_out = self.base / f"scan-{layout}"
                scanned = self._python(
                    env,
                    reviews / "security_scan.py",
                    "--repo",
                    str(target),
                    "--output",
                    str(scan_out),
                    cwd=self.base,
                )
                self.assertNotIn("Traceback", scanned.stderr)
                summary_path = scan_out / "summary.json"
                self.assertTrue(summary_path.is_file(), scanned.stderr)
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                self.assertEqual(scanned.returncode, summary["exit_code"], scanned.stderr)
                self.assertTrue(summary["rows"])
                self.assertIn("Repository security scan", (scan_out / "summary.md").read_text(encoding="utf-8"))

                rubrics = self._python(
                    env,
                    reviews / "lifecycle_review.py",
                    "rubrics",
                    "list-cores",
                    "--phase",
                    "idea",
                    cwd=self.base,
                )
                self.assertEqual(rubrics.returncode, 0, rubrics.stderr)
                self.assertIn("problem_framing", rubrics.stdout)

                outside = self._python(
                    env,
                    plan_script,
                    "--root",
                    str(target),
                    str(plan),
                    cwd=self.base,
                )
                self.assertEqual(outside.returncode, 0, outside.stdout + outside.stderr)
                inside = self._python(env, plan_script, str(plan.relative_to(target)), cwd=target)
                self.assertEqual(inside.returncode, 0, inside.stdout + inside.stderr)

                fired = self._hook(env, hook, target, incomplete)
                self.assertEqual(fired.returncode, 0, fired.stderr)
                self.assertIn("additionalContext", fired.stdout)
                self.assertIn("missing section: Summary", fired.stdout)
                silent = self._hook(env, hook, target, readme)
                self.assertEqual(silent.returncode, 0, silent.stderr)
                self.assertEqual(silent.stdout, "")

                for script in (ideate, brainstorm):
                    judged = self._python(env, script, "readiness", "--doc", str(doc), cwd=target)
                    self.assertEqual(judged.returncode, 0, judged.stderr)
                    self.assertNotIn("Traceback", judged.stderr)
                    payload = json.loads(judged.stdout)
                    self.assertEqual(payload.get("judgment"), "readiness")
                    self.assertIs(payload.get("advisory"), True)

                imported = audit_log.read_text(encoding="utf-8")
                self.assertEqual(imported, "", imported)

    def test_zero_retired_package_imports_or_broken_doc_links_remain(self) -> None:
        offenders = self._retired_imports()
        self.assertEqual(offenders, [], "\n".join(offenders))
        self._assert_d2_bytes()
        for script in (
            "bundle_fleet_module.py",
            "sync_marketplace.py",
            "sync_codex_packaging.py",
        ):
            completed = subprocess.run(
                [sys.executable, str(self.repo / "scripts" / script), "--check"],
                cwd=self.repo,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"{script} --check failed\n{completed.stdout}\n{completed.stderr}",
            )
        broken = self._broken_doc_links()
        self.assertEqual(broken, [], "\n".join(broken))

    @classmethod
    def _layouts(cls) -> dict[str, dict[str, Path]]:
        cache = cls.home / ".claude" / "plugins" / "cache" / "infiquetra-agent-plugins"

        def skill_layout(skills: Path) -> dict[str, Path]:
            code_review = skills / "code-review"
            plan = skills / "plan"
            return {
                "reviews": code_review / ".." / ".." / "scripts",
                "plan": plan / "scripts" / "check_plan.py",
                "hook": plan / ".." / ".." / "com.infiquetra.claude" / "hooks" / "validate_plan_write_hook.py",
                "ideate": skills / "ideate" / "scripts" / "shaping_judgments.py",
                "brainstorm": skills / "brainstorm" / "scripts" / "shaping_judgments.py",
            }

        claude_plan = cache / "plan" / "skills" / "plan"
        return {
            "opencode": skill_layout(cls.home / ".config" / "opencode" / "skills"),
            "hermes": skill_layout(cls.home / ".hermes" / "skills"),
            "claude": {
                "reviews": cache / "reviews" / "scripts",
                "plan": claude_plan / "scripts" / "check_plan.py",
                "hook": cache / "plan" / "com.infiquetra.claude" / "hooks" / "validate_plan_write_hook.py",
                "ideate": cache / "ideate" / "skills" / "ideate" / "scripts" / "shaping_judgments.py",
                "brainstorm": cache / "brainstorm" / "skills" / "brainstorm" / "scripts" / "shaping_judgments.py",
            },
        }

    def _python(self, env: dict[str, str], script: Path, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), *args],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )

    def _hook(
        self, env: dict[str, str], hook: Path, root: Path, path: Path
    ) -> subprocess.CompletedProcess[str]:
        payload = json.dumps(
            {"tool_name": "Write", "cwd": str(root), "tool_input": {"file_path": str(path)}}
        )
        return subprocess.run(
            [sys.executable, str(hook)],
            input=payload,
            cwd=self.base,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def _git_repo(self, repo: Path) -> None:
        repo.mkdir()
        git = ["git", "-c", "commit.gpgsign=false", "-c", "init.defaultBranch=main"]
        subprocess.run([*git, "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
        subprocess.run([*git, "config", "user.email", "review@example.com"], cwd=repo, check=True, capture_output=True)
        subprocess.run([*git, "config", "user.name", "review"], cwd=repo, check=True, capture_output=True)
        (repo / "src").mkdir()
        (repo / "src" / "app.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run([*git, "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
        (repo / "src" / "app.py").write_text("def changed():\n    return 2\n", encoding="utf-8")
        subprocess.run([*git, "add", "-A"], cwd=repo, check=True, capture_output=True)
        subprocess.run([*git, "commit", "-m", "head"], cwd=repo, check=True, capture_output=True)

    def _revisions(self, repo: Path) -> tuple[str, str]:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        base = subprocess.run(
            ["git", "rev-parse", "HEAD~1"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        return base, head

    def _complete_plan(self, repo: Path) -> Path:
        (repo / "pkg").mkdir()
        (repo / "pkg" / "reader.py").write_text("reader\n", encoding="utf-8")
        (repo / "pkg" / "test_reader.py").write_text("test\n", encoding="utf-8")
        plan = repo / "docs" / "plans" / "2026-11-19-widget-plan.md"
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(
            "\n".join(
                [
                    "# Widget",
                    "",
                    "## Summary",
                    "",
                    "Add a local reader.",
                    "",
                    "## Non-Goals",
                    "",
                    "- No network calls.",
                    "",
                    "## Key Decisions",
                    "",
                    "- **Read from disk:** the input is already a local file.",
                    "",
                    "## Units",
                    "",
                    "- **Files:** `pkg/reader.py`, `pkg/widget.py` (new)",
                    "- **Tests:** empty input returns an empty list.",
                    "- **Verify:** `python3 -m unittest pkg/test_reader.py`",
                    "",
                    "## Verification",
                    "",
                    "Run the unit test named in the unit.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return plan

    def _retired_imports(self) -> list[str]:
        offenders: list[str] = []
        roots = [self.repo / "plugins", self.repo / "scripts"]
        for root in roots:
            for path in sorted(root.rglob("*.py")):
                if any(part in check_repo.MODULE_SOURCE_PRUNED_DIRECTORY_NAMES for part in path.parts):
                    continue
                if "__pycache__" in path.parts:
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                except SyntaxError as exc:
                    offenders.append(f"{path.relative_to(self.repo)}: {exc}")
                    continue
                for node in ast.walk(tree):
                    modules: list[str] = []
                    if isinstance(node, ast.Import):
                        modules.extend(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        modules.append(node.module)
                    elif isinstance(node, ast.Call):
                        func = node.func
                        called = isinstance(func, ast.Attribute) and func.attr == "import_module"
                        if called or (isinstance(func, ast.Name) and func.id == "__import__"):
                            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                                modules.append(node.args[0].value)
                    for module in modules:
                        parts = {part.replace("-", "_") for part in module.split(".")}
                        if parts & RETIRED_MODULES:
                            offenders.append(
                                f"{path.relative_to(self.repo)}:{getattr(node, 'lineno', 0)} imports {module}"
                            )
        return offenders

    def _assert_d2_bytes(self) -> None:
        formula = self.repo / "plugins" / "reviews" / "scripts" / "review_formula.py"
        schema = self.repo / "plugins" / "reviews" / "references" / "review-records.schema.json"
        formula_bytes = formula.read_bytes()
        schema_bytes = schema.read_bytes()
        self.assertEqual(hashlib.sha256(formula_bytes).hexdigest(), FORMULA_SHA256)
        self.assertEqual(hashlib.sha256(schema_bytes).hexdigest(), SCHEMA_SHA256)
        expected_formula = self.base / "d2-review_formula.py"
        expected_schema = self.base / "d2-review-records.schema.json"
        expected_formula.write_bytes(
            subprocess.check_output(
                ["git", "-C", str(self.repo), "show", f"{BASE_COMMIT}:plugins/saga/scripts/review_formula.py"]
            )
        )
        expected_schema.write_bytes(
            subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(self.repo),
                    "show",
                    f"{BASE_COMMIT}:plugins/saga/references/review-records.schema.json",
                ]
            )
        )
        formula_cmp = subprocess.run(["cmp", str(formula), str(expected_formula)], capture_output=True, check=False)
        schema_cmp = subprocess.run(["cmp", str(schema), str(expected_schema)], capture_output=True, check=False)
        self.assertEqual(formula_cmp.returncode, 0, formula_cmp.stdout + formula_cmp.stderr)
        self.assertEqual(schema_cmp.returncode, 0, schema_cmp.stdout + schema_cmp.stderr)
        self.assertEqual(json.loads(schema_bytes)["$id"], json.loads(expected_schema.read_bytes())["$id"])

    def _broken_doc_links(self) -> list[str]:
        errors: list[str] = []
        roots = [self.repo / "plugins", self.repo / "docs"]
        for root in roots:
            for document in sorted(root.rglob("*.md")):
                relative = document.relative_to(self.repo)
                if any(part in check_repo.MODULE_SOURCE_PRUNED_DIRECTORY_NAMES for part in relative.parts):
                    continue
                if relative.as_posix() == "docs/engineering-journal/ARCHIVE.md":
                    continue
                text = document.read_text(encoding="utf-8")
                for match in check_repo.MARKDOWN_LINK.finditer(text):
                    raw = match.group(1).strip()
                    if raw.startswith(check_repo.EXTERNAL_PREFIXES) or raw.startswith("#"):
                        continue
                    target = check_repo._link_target(raw)
                    if not target or "{" in target or "}" in target:
                        continue
                    destination = (document.parent / target).resolve()
                    if not destination.exists():
                        errors.append(f"broken local link in {relative}: {raw}")
        return errors


if __name__ == "__main__":
    unittest.main()
