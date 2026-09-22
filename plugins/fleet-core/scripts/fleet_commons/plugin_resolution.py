#!/usr/bin/env python3
"""Generic plugin-root resolution — how any plugin finds a SIBLING plugin at run time.

The ladder in ``fleet_commons_shim`` answers one fixed question ("where is fleet-core?") and is
byte-frozen bootstrap code (DECISIONS ``{#fleet-commons-mechanism-463}``). This module generalizes
the same ladder to an arbitrary plugin name, and lives in the loaded package rather than the shim so
the bootstrap file stays byte-identical across all seven vendored copies (issue #620, DECISIONS
``{#board-sync-plugin-resolution-620}``).

First mover: saga's ``/outcome`` board-sync, which previously located mission-control at
``<repo_root>/plugins/mission-control/...`` and via ``Path(__file__).parents[2]`` — both correct only
inside the plugins monorepo, so every board write failed from a consumer repo.

Resolution ladder (first rung that succeeds wins; provenance is part of the return value):

1. ``env_var`` override when the caller names one — explicit, so an invalid value raises rather than
   falling through.
2. Repo-checkout walk-up from ``anchor``: an ancestor holding both
   ``.claude-plugin/marketplace.json`` and ``plugins/<name>/``.
3. ``~/.claude/plugins/installed_plugins.json`` (schema ``version: 2``): any key with prefix
   ``<name>@`` -> its install records' ``installPath``. Parse/shape trouble is a rung miss, never a
   crash.
4. Cache-sibling scan: ``$CLAUDE_PLUGIN_ROOT/../../<name>/<highest semver>/``.
5. Fail loud (``RuntimeError``) with a message naming every rung tried.

``markers`` is a SEQUENCE and every entry must exist for a candidate root to be valid — a root that
resolves but cannot serve all of the caller's needs is a rung miss, not a success. mission-control
passes both its CLI and its schema so a half-usable install never wins.

Set ``FLEET_COMMONS_DEBUG=1`` to print ``plugin-resolution: name=<n> rung=<n> (<name>) root=<path>``
to stderr on every successful resolve — the same switch the shim uses, deliberately, so one variable
turns on provenance for the whole resolution substrate.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

RUNG_NAMES = {1: "env-override", 2: "repo-walk-up", 3: "installed-plugins", 4: "cache-sibling"}

DEFAULT_MARKERS: tuple[str, ...] = (".claude-plugin/plugin.json",)


def _is_valid_root(root: Path, markers: Sequence[str]) -> bool:
    """True when ``root`` exists and EVERY marker path under it exists."""
    return all((root / marker).exists() for marker in markers)


def _semver_key(name: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in name.split("."))
    except ValueError:
        return None


def _rung_env_override(env_var: str | None, markers: Sequence[str]) -> Path | None:
    """Rung 1. An explicitly-set-but-invalid override RAISES — never a silent fall-through."""
    if not env_var:
        return None
    override = os.environ.get(env_var)
    if not override:
        return None
    root = Path(override)
    if not _is_valid_root(root, markers):
        raise RuntimeError(
            f"plugin-resolution: {env_var}={override!r} is not a valid plugin root "
            f"(expected every marker to exist: {', '.join(markers)})."
        )
    return root


def _rung_repo_walk_up(name: str, anchor: Path, markers: Sequence[str]) -> Path | None:
    """Rung 2. An ancestor of ``anchor`` holding BOTH a marketplace manifest and ``plugins/<name>``."""
    for ancestor in anchor.resolve().parents:
        candidate = ancestor / "plugins" / name
        marketplace = ancestor / ".claude-plugin" / "marketplace.json"
        if marketplace.is_file() and _is_valid_root(candidate, markers):
            return candidate
    return None


def _rung_installed_plugins(name: str, markers: Sequence[str]) -> Path | None:
    """Rung 3. The install registry, keyed by ``<name>@<marketplace>``."""
    registry = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        entries = list(json.loads(registry.read_text(encoding="utf-8"))["plugins"].items())
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None  # undocumented internal registry: any shape surprise is a rung miss
    for key, records in entries:
        if not key.startswith(f"{name}@"):
            continue
        try:
            candidates = list(records)
        except TypeError:
            continue
        for record in candidates:
            # Per-record tolerance: one malformed record must not poison the scan.
            try:
                root = Path(record["installPath"])
            except (KeyError, TypeError):
                continue
            if _is_valid_root(root, markers):
                return root
    return None


def _rung_cache_sibling(name: str, markers: Sequence[str]) -> Path | None:
    """Rung 4. Highest semver under the cache sibling directory for ``name``."""
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if not plugin_root:
        return None
    versions_dir = Path(plugin_root).resolve().parent.parent / name
    if not versions_dir.is_dir():
        return None
    candidates = [
        (key, child)
        for child in versions_dir.iterdir()
        if child.is_dir() and (key := _semver_key(child.name)) is not None
    ]
    for _, root in sorted(candidates, reverse=True):
        if _is_valid_root(root, markers):
            return root
    return None


def resolve_plugin_root(
    name: str,
    *,
    markers: Sequence[str] = DEFAULT_MARKERS,
    env_var: str | None = None,
    anchor: Path | None = None,
) -> tuple[Path, int]:
    """Resolve plugin ``name``'s root; returns ``(root, rung)`` or raises ``RuntimeError``.

    ``anchor`` defaults to THIS module's own file — the fleet-core install — mirroring
    ``fleet_commons_shim.resolve_root``'s walk-up from its own ``__file__``. Callers deliberately do
    NOT pass their own location: a saga-anchored walk-up and a fleet-core-anchored one disagree in
    the mixed case (saga running from the cache while the cwd sits in the monorepo), and one
    resolution substrate must give one answer.
    """
    markers = tuple(markers)
    if not markers:
        raise RuntimeError("plugin-resolution: markers must name at least one path")
    anchor = anchor if anchor is not None else Path(__file__)

    resolved: tuple[Path, int] | None = None
    if (root := _rung_env_override(env_var, markers)) is not None:
        resolved = (root, 1)
    if resolved is None and (root := _rung_repo_walk_up(name, anchor, markers)) is not None:
        resolved = (root, 2)
    if resolved is None and (root := _rung_installed_plugins(name, markers)) is not None:
        resolved = (root, 3)
    if resolved is None and (root := _rung_cache_sibling(name, markers)) is not None:
        resolved = (root, 4)
    if resolved is None:
        hatch = f" or set {env_var} to a checkout's plugins/{name} directory" if env_var else ""
        raise RuntimeError(
            f"plugin-resolution: could not resolve a {name!r} root (tried "
            f"{'env override, ' if env_var else ''}repo walk-up, "
            f"~/.claude/plugins/installed_plugins.json, cache-sibling scan; required markers: "
            f"{', '.join(markers)}). Fix: install the {name} plugin from the infiquetra-plugins "
            f"marketplace{hatch}."
        )
    if os.environ.get("FLEET_COMMONS_DEBUG") == "1":
        root, rung = resolved
        print(
            f"plugin-resolution: name={name} rung={rung} ({RUNG_NAMES[rung]}) root={root}",
            file=sys.stderr,
        )
    return resolved
