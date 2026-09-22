"""Generic plugin-root resolution ladder (issue #620, U1).

Oracles pinned here:

* ladder — one test per rung (env override, repo walk-up, installed_plugins.json, cache-sibling
  highest-semver), fail-loud naming every rung when nothing resolves, malformed registry records
  fall through instead of crashing, and an explicit-but-wrong env override raises.
* markers — the sequence is ALL-must-exist, so a root that can serve only part of the caller's
  needs is a rung miss rather than a half-usable success.
* anchor — the default walk-up anchor is the module's own file, so the installed-cache layout
  (``<plugin>/<version>/scripts/``) misses rung 2 instead of resolving one directory short. This
  is the arithmetic that produced #620's version-less ``.../saga/mission-control/config/...`` path.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "plugin_resolution.py"
MC_MARKERS = ("scripts/sdlc_manager.py", "config/sdlc-schema.json")

_LOAD_COUNTER = 0


def _load_module(path: Path = MODULE_PATH) -> ModuleType:
    """Load the resolver under a unique module name so per-test copies never collide."""
    global _LOAD_COUNTER
    _LOAD_COUNTER += 1
    spec = importlib.util.spec_from_file_location(f"_plugin_resolution_{_LOAD_COUNTER}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_mc_root(base: Path, *, version: str = "2.10.1", partial: bool = False) -> Path:
    """Build a minimal valid mission-control root under ``base`` and return it."""
    (base / "scripts").mkdir(parents=True, exist_ok=True)
    (base / "config").mkdir(parents=True, exist_ok=True)
    (base / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (base / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "mission-control", "version": version})
    )
    (base / "scripts" / "sdlc_manager.py").write_text("# stub\n")
    if not partial:
        (base / "config" / "sdlc-schema.json").write_text(json.dumps({"saga_lifecycle": {}}))
    return base


def _write_registry(home: Path, *, install_path: Path, key: str = "mission-control@ip") -> None:
    registry_dir = home / ".claude" / "plugins"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "installed_plugins.json").write_text(
        json.dumps({"version": 2, "plugins": {key: [{"installPath": str(install_path)}]}})
    )


@pytest.fixture()
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> pytest.MonkeyPatch:
    """Scrub every environment surface the ladder reads and point HOME at an empty tmp home."""
    for var in ("MISSION_CONTROL_ROOT", "FLEET_COMMONS_DEBUG", "CLAUDE_PLUGIN_ROOT"):
        monkeypatch.delenv(var, raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    return monkeypatch


@pytest.fixture()
def resolver() -> ModuleType:
    return _load_module()


@pytest.fixture()
def outside_anchor(tmp_path: Path) -> Path:
    """An anchor living outside any repo checkout, so rung 2 cannot match."""
    anchor = tmp_path / "elsewhere" / "scripts" / "mod.py"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("")
    return anchor


# --- rung 1: env override -------------------------------------------------------------------


def test_rung1_env_override_wins(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    root = _make_mc_root(tmp_path / "override-root")
    clean_env.setenv("MISSION_CONTROL_ROOT", str(root))
    assert resolver.resolve_plugin_root(
        "mission-control", markers=MC_MARKERS, env_var="MISSION_CONTROL_ROOT", anchor=outside_anchor
    ) == (root, 1)


def test_rung1_invalid_override_raises_instead_of_falling_through(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    """An explicit-but-wrong override is operator error, not a reason to silently use something else."""
    fallback = _make_mc_root(tmp_path / "fallback")
    _write_registry(tmp_path / "home", install_path=fallback)  # a valid rung-3 root IS available
    clean_env.setenv("MISSION_CONTROL_ROOT", str(tmp_path / "not-a-root"))
    with pytest.raises(RuntimeError, match="MISSION_CONTROL_ROOT"):
        resolver.resolve_plugin_root(
            "mission-control",
            markers=MC_MARKERS,
            env_var="MISSION_CONTROL_ROOT",
            anchor=outside_anchor,
        )


def test_unset_env_var_is_a_miss_not_an_error(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    root = _make_mc_root(tmp_path / "registry-root")
    _write_registry(tmp_path / "home", install_path=root)
    assert resolver.resolve_plugin_root(
        "mission-control", markers=MC_MARKERS, env_var="MISSION_CONTROL_ROOT", anchor=outside_anchor
    ) == (root, 3)


# --- rung 2: repo walk-up -------------------------------------------------------------------


def test_rung2_walk_up_finds_sibling_plugin_in_a_checkout(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".claude-plugin").mkdir(parents=True)
    (checkout / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"plugins": []}))
    root = _make_mc_root(checkout / "plugins" / "mission-control")
    anchor = checkout / "plugins" / "saga" / "scripts" / "mod.py"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("")
    assert resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=anchor) == (
        root,
        2,
    )


def test_rung2_requires_the_marketplace_manifest_not_just_a_plugins_dir(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """A consumer repo that merely HAS a plugins/ directory is not a plugins checkout (#620 R2)."""
    consumer = tmp_path / "consumer"
    _make_mc_root(consumer / "plugins" / "mission-control")  # no marketplace.json anywhere
    anchor = consumer / "src" / "mod.py"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("")
    with pytest.raises(RuntimeError, match="could not resolve"):
        resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=anchor)


def test_default_anchor_under_installed_cache_layout_misses_rung2(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch
) -> None:
    """The #620 arithmetic: <plugin>/<version>/scripts/ has no marketplace ancestor, so rung 2
    must MISS and the ladder must fall through to the registry — never resolve one level short."""
    cache = tmp_path / "cache" / "infiquetra-plugins"
    anchor = cache / "saga" / "0.114.0" / "scripts" / "fleet_commons" / "plugin_resolution.py"
    anchor.parent.mkdir(parents=True)
    anchor.write_text("")
    registry_root = _make_mc_root(cache / "mission-control" / "2.10.1")
    _write_registry(tmp_path / "home", install_path=registry_root)
    root, rung = resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=anchor)
    assert rung == 3
    assert root == registry_root
    # The version segment survives — the bug produced a path with it missing.
    assert root.parent.name == "mission-control"
    assert root.name == "2.10.1"


# --- rung 3: installed_plugins.json ---------------------------------------------------------


def test_rung3_registry_resolves_by_name_prefix(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    root = _make_mc_root(tmp_path / "installed")
    _write_registry(tmp_path / "home", install_path=root, key="mission-control@infiquetra-plugins")
    assert resolver.resolve_plugin_root(
        "mission-control", markers=MC_MARKERS, anchor=outside_anchor
    ) == (root, 3)


def test_rung3_ignores_other_plugins_sharing_a_prefix_boundary(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    """``mission-control@`` must not be satisfied by a differently-named plugin."""
    other = _make_mc_root(tmp_path / "other")
    _write_registry(tmp_path / "home", install_path=other, key="mission-control-extras@ip")
    with pytest.raises(RuntimeError, match="could not resolve"):
        resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=outside_anchor)


def test_rung3_malformed_records_fall_through_without_crashing(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    """One bad record must not poison the scan — a later good record still wins."""
    good = _make_mc_root(tmp_path / "good")
    registry_dir = tmp_path / "home" / ".claude" / "plugins"
    registry_dir.mkdir(parents=True)
    (registry_dir / "installed_plugins.json").write_text(
        json.dumps(
            {
                "version": 2,
                "plugins": {
                    "mission-control@ip": [
                        {"noInstallPath": True},
                        {"installPath": str(tmp_path / "missing")},
                        {"installPath": str(good)},
                    ]
                },
            }
        )
    )
    assert resolver.resolve_plugin_root(
        "mission-control", markers=MC_MARKERS, anchor=outside_anchor
    ) == (good, 3)


def test_rung3_unreadable_registry_is_a_miss_not_a_crash(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    registry_dir = tmp_path / "home" / ".claude" / "plugins"
    registry_dir.mkdir(parents=True)
    (registry_dir / "installed_plugins.json").write_text("{not json")
    with pytest.raises(RuntimeError, match="could not resolve"):
        resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=outside_anchor)


# --- rung 4: cache-sibling ------------------------------------------------------------------


def test_rung4_cache_sibling_picks_highest_semver_and_skips_non_semver(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    cache = tmp_path / "cache" / "infiquetra-plugins"
    _make_mc_root(cache / "mission-control" / "2.9.0")
    newest = _make_mc_root(cache / "mission-control" / "2.10.1")
    (cache / "mission-control" / "not-a-version").mkdir(parents=True)
    saga_root = cache / "saga" / "0.114.0"
    saga_root.mkdir(parents=True)
    clean_env.setenv("CLAUDE_PLUGIN_ROOT", str(saga_root))
    root, rung = resolver.resolve_plugin_root(
        "mission-control", markers=MC_MARKERS, anchor=outside_anchor
    )
    assert (root, rung) == (newest, 4)  # 2.10.1 > 2.9.0 numerically, not lexically


# --- markers ---------------------------------------------------------------------------------


def test_partial_marker_match_is_rejected(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    """A root with the CLI but no schema cannot serve board-sync, so it is a rung miss."""
    partial = _make_mc_root(tmp_path / "partial", partial=True)
    _write_registry(tmp_path / "home", install_path=partial)
    assert (partial / "scripts" / "sdlc_manager.py").is_file()
    with pytest.raises(RuntimeError, match="could not resolve"):
        resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=outside_anchor)


def test_empty_markers_is_rejected(resolver: ModuleType, outside_anchor: Path) -> None:
    with pytest.raises(RuntimeError, match="at least one path"):
        resolver.resolve_plugin_root("mission-control", markers=(), anchor=outside_anchor)


# --- failure message + provenance -------------------------------------------------------------


def test_total_failure_names_every_rung_and_the_escape_hatch(
    resolver: ModuleType, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        resolver.resolve_plugin_root(
            "mission-control",
            markers=MC_MARKERS,
            env_var="MISSION_CONTROL_ROOT",
            anchor=outside_anchor,
        )
    message = str(excinfo.value)
    for fragment in (
        "env override",
        "repo walk-up",
        "installed_plugins.json",
        "cache-sibling",
        "MISSION_CONTROL_ROOT",
        "scripts/sdlc_manager.py",
    ):
        assert fragment in message


def test_provenance_prints_only_under_the_debug_flag(
    resolver: ModuleType,
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,
    outside_anchor: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _make_mc_root(tmp_path / "installed")
    _write_registry(tmp_path / "home", install_path=root)
    resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=outside_anchor)
    assert capsys.readouterr().err == ""

    clean_env.setenv("FLEET_COMMONS_DEBUG", "1")
    resolver.resolve_plugin_root("mission-control", markers=MC_MARKERS, anchor=outside_anchor)
    err = capsys.readouterr().err
    assert "plugin-resolution:" in err
    assert "rung=3" in err
    assert "installed-plugins" in err
    assert str(root) in err


def test_default_markers_accept_any_plugin_root(
    resolver: ModuleType, tmp_path: Path, clean_env: pytest.MonkeyPatch, outside_anchor: Path
) -> None:
    """The default marker is the universal plugin manifest, so the resolver is not
    mission-control-specific."""
    root = tmp_path / "some-plugin"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "unifi"}))
    _write_registry(tmp_path / "home", install_path=root, key="unifi@ip")
    assert resolver.resolve_plugin_root("unifi", anchor=outside_anchor) == (root, 3)


def test_module_is_stdlib_only(resolver: ModuleType) -> None:
    """fleet_commons modules are loaded by path, never installed — no third-party imports."""
    source = MODULE_PATH.read_text()
    assert "import requests" not in source
    assert sys.modules.get("requests") is None or "requests" not in source
