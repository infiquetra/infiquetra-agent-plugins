"""Muse plugin CLI JSON and parser compatibility contract shared by catalog tools."""

from __future__ import annotations

from pathlib import Path

# Compatibility alias for this repository's Muse projection, not the legacy source.
MUSE_CATALOG_MARKETPLACE_ALIAS = "infiquetra-claude-plugins"
MUSE_REGISTRY_RELATIVE = Path(".local/share/muse/plugins/marketplaces.json")


class MuseCLIError(RuntimeError):
    """Muse JSON does not satisfy its command contract."""


def registry_entries(document: dict) -> dict[str, dict]:
    entries = document.get("marketplaces", {})
    if not isinstance(entries, dict) or any(
        not isinstance(name, str) or not isinstance(entry, dict) for name, entry in entries.items()
    ):
        raise MuseCLIError("muse: marketplaces must be an object of registration objects")
    return entries


def registration_source(entry: dict) -> str:
    source = entry.get("source", {})
    if isinstance(source, str):
        return source
    value = source.get("path", "") if isinstance(source, dict) else ""
    return value if isinstance(value, str) else ""


def record_source(record: dict) -> str:
    source = record.get("source", {})
    path = source.get("path", "") if isinstance(source, dict) else ""
    return path if isinstance(path, str) else ""


def source_marketplace(
    record: dict,
    available: dict | None = None,
    staging_dir: Path | None = None,
    registrations: dict[str, dict] | None = None,
    home: Path | None = None,
) -> str:
    """Attribute a bare installed id using registered paths and available sources.

    Local installs retain the original staged path. Git installs can retain a
    generation's worktree path under Muse's own data directory. A familiar alias
    alone never establishes that the registration owns the legacy repository.
    """
    source = record.get("source", {})
    if not isinstance(source, dict):
        return ""
    named = source.get("marketplace")
    if isinstance(named, str):
        return named
    identity = record.get("id", "")
    name, _, suffix = identity.partition("@") if isinstance(identity, str) else ("", "", "")
    if suffix:
        return suffix
    path = record_source(record)
    if (
        not path
        or not Path(path).is_absolute()
        or source.get("provenance") != "marketplace-user-added"
    ):
        return ""
    resolved = Path(path).resolve()
    if staging_dir is not None and resolved == (staging_dir / "plugins" / name).resolve():
        return MUSE_CATALOG_MARKETPLACE_ALIAS
    candidates: set[str] = set()
    for alias, entry in (registrations or {}).items():
        stored = registration_source(entry)
        if (
            stored
            and Path(stored).is_absolute()
            and resolved == (Path(stored) / "plugins" / name).resolve()
        ):
            candidates.add(alias)
        details = entry.get("source", {})
        worktree = details.get("worktree_path", "") if isinstance(details, dict) else ""
        if isinstance(worktree, str) and worktree and home is not None:
            base = Path(worktree)
            if not base.is_absolute():
                base = home / ".local/share/muse" / base
            if resolved == (base / "plugins" / name).resolve():
                candidates.add(alias)
        if home is not None:
            managed = home / MUSE_REGISTRY_RELATIVE.parent / "marketplaces" / alias
            if resolved.is_relative_to(managed.resolve()):
                candidates.add(alias)
    offered = (available or {}).get("available", [])
    for row in offered if isinstance(offered, list) else []:
        if not isinstance(row, dict) or not isinstance(row.get("marketplace"), str):
            continue
        install = row.get("install", {})
        candidate = install.get("source") if isinstance(install, dict) else None
        if (
            isinstance(candidate, str)
            and Path(candidate).is_absolute()
            and Path(candidate).resolve() == resolved
        ):
            candidates.add(row["marketplace"])
    return candidates.pop() if len(candidates) == 1 else ""


def plugin_rows(document: dict) -> list[dict]:
    rows = document.get("plugins")
    if not isinstance(rows, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("record"), dict)
        or not isinstance(row["record"].get("id"), str)
        for row in rows
    ):
        raise MuseCLIError("muse: list JSON must contain plugins with record objects")
    return rows


def available_problems(document: dict, names: list[str]) -> list[str]:
    available, skipped = document.get("available"), document.get("skipped")
    if not isinstance(available, list) or not isinstance(skipped, list):
        return ["muse: available JSON must contain available and skipped lists"]
    found = {
        row.get("name")
        for row in available
        if isinstance(row, dict)
        and isinstance(row.get("name"), str)
        and row.get("marketplace") == MUSE_CATALOG_MARKETPLACE_ALIAS
    }
    problems = [
        f"muse: {name} is unavailable from {MUSE_CATALOG_MARKETPLACE_ALIAS}"
        for name in names
        if name not in found
    ]
    if any(not isinstance(row, dict) for row in skipped):
        problems.append("muse: malformed skipped entry")
    if any(
        isinstance(row, dict) and row.get("marketplace") == MUSE_CATALOG_MARKETPLACE_ALIAS
        for row in skipped
    ):
        problems.append(f"muse: {MUSE_CATALOG_MARKETPLACE_ALIAS} has skipped packages")
    return problems


def fallback_argv(argv: tuple[str, ...], stdout: str, stderr: str) -> tuple[str, ...] | None:
    """Older Muse builds name the marketplace on add and call uninstall `remove`.

    Retry only these explicit parser refusals. An installation or runtime failure
    must retain its error instead of being retried through a different command.
    """
    output = stdout + stderr
    if (
        argv[1:4] == ("plugins", "marketplace", "add")
        and len(argv) == 5
        and "usage: muse plugins marketplace add <name> <source>" in output
    ):
        return (*argv[:4], MUSE_CATALOG_MARKETPLACE_ALIAS, argv[4])
    if (
        argv[1:3] == ("plugins", "uninstall")
        and "unsupported plugins command `uninstall`" in output
    ):
        # This build has a single user registry and removes by bare id. Project
        # scope must never silently become a user removal.
        if argv[-2:] == ("--scope", "user"):
            return (argv[0], "plugins", "remove", argv[3].partition("@")[0])
    return None
