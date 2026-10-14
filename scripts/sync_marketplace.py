#!/usr/bin/env python3
"""Generate the Claude marketplace from the packages that carry a Claude manifest.

`.claude-plugin/marketplace.json` is how Claude Code installs anything from this
repository. It used to be hand-edited, which was affordable while one package
was listed. The 2026-09-22 custody decision makes every package
Claude-installable, and the twelve import units that follow each add one entry
to the same array -- twelve branches editing one file, which is twelve conflicts
on merge, each resolved by hand against a file whose correctness nobody can see
by reading the diff.

So the file is generated. An import unit runs this script and commits the
result; a rebase conflict on the marketplace is resolved by running it again
rather than by merging JSON by hand.

**What decides the listing.** A package is listed exactly when it carries
`.claude-plugin/plugin.json`, because that is the file the Claude CLI needs to
install it. Nothing else is consulted: a package without one cannot be
installed, and listing it would produce an entry whose install ends in "No
manifest found in directory".

**Where each field comes from.** Everything an entry states about a package is
read from that package's own manifests, so the entry cannot drift from the
manifest it describes -- which is the agreement `claude plugin tag` refuses to
release without. `version` and `description` come from the Claude manifest. The
presentation fields (`author`, `repository`, `license`, `keywords`, `homepage`,
`category`) are authored once, in the portable `plugin.json`, and fall back to
the Claude manifest only when the portable one does not state them. Claude's own
manifest carries no presentation metadata, because Muse's foreign-plugin loader
reports those keys as unsupported.

**Muse staging.** Muse reads the same `.claude-plugin/plugin.json` but rejects
several keys and shapes Claude accepts. `stage_muse_marketplace` copies the
Muse-installable packages into a scratch marketplace, rewriting only the staged
copy, so the committed manifests stay exactly what Claude installs.

**What is preserved.** The top-level `name`, `owner`, and `metadata` block are
carried from the existing file unchanged. They describe the catalog rather than
any package, so nothing in `plugins/` could derive them.

Standard library only, and no network access, matching the rest of this
repository's tooling.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

MARKETPLACE_PATH = Path(".claude-plugin") / "marketplace.json"

PLUGIN_PARENT = "plugins"

#: Claude's own packaging manifest, at the root of the directory it installs.
#: Carrying one is what makes a package Claude-installable, and therefore what
#: puts it in the marketplace.
CLAUDE_MANIFEST_RELATIVE = Path(".claude-plugin") / "plugin.json"

#: The portable Agent Plugins manifest beside it.
PORTABLE_MANIFEST_NAME = "plugin.json"

#: Entry fields copied from the package's Claude manifest when it states them,
#: in the order they are written. `name` and `source` are computed, so they are
#: not here.
CARRIED_FROM_CLAUDE_MANIFEST = (
    "version",
    "description",
)

#: Entry fields read from the portable manifest first and the Claude manifest
#: only when the portable one states nothing, in the order they are written.
#: `keywords` and `category` follow, because an empty value is omitted.
CARRIED_FROM_PORTABLE_MANIFEST = (
    "author",
    "repository",
    "license",
    "homepage",
)

#: Catalog-level keys preserved from the existing file. Nothing under
#: `plugins/` describes the catalog itself, so these cannot be derived.
PRESERVED_TOP_LEVEL = ("name", "owner", "metadata")


#: Claude manifest keys Muse's foreign-plugin loader reports as unsupported or
#: inactive, removed from the staged copy only. `agents` is the Claude agent
#: overlay, which Muse cannot activate.
MUSE_UNSUPPORTED_KEYS = (
    "author",
    "repository",
    "keywords",
    "license",
    "homepage",
    "types",
    "outputStyles",
    "agents",
)

#: Manifest keys declaring a capability Muse can load. A package declaring none
#: of them has nothing to install there.
MUSE_CAPABILITY_KEYS = ("skills", "commands", "hooks", "mcpServers")

#: Names skipped when staging. The root `plugin.json` and `.codex-plugin/` are
#: other adapters' manifests and would make Muse see several manifests.
MUSE_STAGING_IGNORED = (".codex-plugin", ".git", "__pycache__", ".pytest_cache")

#: Where staged marketplaces are written by default. `build/` is not tracked.
MUSE_STAGING_DEFAULT = Path("build") / "muse-marketplace"


class MarketplaceError(Exception):
    """The marketplace could not be generated, and says why."""


def repository_root() -> Path:
    return ROOT


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MarketplaceError(f"{path}: could not be read as JSON: {error}") from error
    if not isinstance(payload, dict):
        raise MarketplaceError(f"{path}: expected a JSON object")
    return payload


def claude_packages(root: Path) -> list[Path]:
    """Every package directory that carries a Claude packaging manifest."""
    packages = root / PLUGIN_PARENT
    if not packages.is_dir():
        return []
    return sorted(
        path
        for path in packages.iterdir()
        if path.is_dir() and (path / CLAUDE_MANIFEST_RELATIVE).is_file()
    )


def build_entry(package: Path, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """One marketplace entry, derived from the package's manifests.

    `existing` is this package's current entry, consulted for `category` alone.
    That field is marketplace-entry-only: it describes where a package sits in
    the catalog's browsing taxonomy, and neither manifest has anywhere to put
    it, so deriving it would mean inventing a field in a schema this repository
    does not own. Preserving it is what keeps regenerating the file from
    silently dropping it.
    """
    claude = _load(package / CLAUDE_MANIFEST_RELATIVE)
    portable_path = package / PORTABLE_MANIFEST_NAME
    portable = _load(portable_path) if portable_path.is_file() else {}

    name = claude.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MarketplaceError(
            f"{(package / CLAUDE_MANIFEST_RELATIVE)}: states no name, so no entry can name it"
        )
    if name != package.name:
        raise MarketplaceError(
            f"{(package / CLAUDE_MANIFEST_RELATIVE)}: names {name!r} but sits in "
            f"{package.name}/. The entry's source is the directory and its name is the "
            "manifest's, so the two have to agree or the entry points somewhere else"
        )

    entry: dict[str, Any] = {
        "name": name,
        # Claude copies exactly this directory. The client extension alone would
        # arrive without the portable core the hooks inside it call.
        "source": f"./{PLUGIN_PARENT}/{package.name}",
    }
    for field in CARRIED_FROM_CLAUDE_MANIFEST:
        if field in claude:
            entry[field] = claude[field]
    for field in CARRIED_FROM_PORTABLE_MANIFEST:
        if field in portable:
            entry[field] = portable[field]
        elif field in claude:
            entry[field] = claude[field]

    keywords = portable.get("keywords", claude.get("keywords"))
    if keywords:
        entry["keywords"] = keywords
    category = portable.get("category", claude.get("category", (existing or {}).get("category")))
    if category:
        entry["category"] = category
    return entry


def build_marketplace(root: Path) -> dict[str, Any]:
    """The marketplace this repository's packages describe."""
    existing_path = root / MARKETPLACE_PATH
    existing = _load(existing_path) if existing_path.is_file() else {}

    entries = {
        entry.get("name"): entry
        for entry in existing.get("plugins", [])
        if isinstance(entry, dict)
    }

    marketplace: dict[str, Any] = {}
    for key in PRESERVED_TOP_LEVEL:
        if key in existing:
            marketplace[key] = existing[key]
    marketplace["plugins"] = [
        build_entry(package, entries.get(package.name)) for package in claude_packages(root)
    ]
    return marketplace


def render(marketplace: dict[str, Any]) -> str:
    return json.dumps(marketplace, indent=2, ensure_ascii=False) + "\n"


def check_marketplace(root: Path) -> list[str]:
    """Problems with the committed marketplace, or an empty list when it is current.

    Imported by `scripts/check_repo.py` so a stale marketplace fails the
    repository gate rather than being discovered by a person who cannot install
    a package the catalog says it ships.
    """
    path = root / MARKETPLACE_PATH
    if not path.is_file():
        return [f"missing marketplace manifest: {MARKETPLACE_PATH}"]
    try:
        expected = render(build_marketplace(root))
    except MarketplaceError as error:
        return [f"marketplace: {error}"]
    current = path.read_text(encoding="utf-8")
    if current == expected:
        return []

    problems = [
        f"{MARKETPLACE_PATH} is stale: it does not match what the package manifests "
        "describe. Run `python3 scripts/sync_marketplace.py` to regenerate it"
    ]
    problems.extend(_difference_summary(current, expected))
    return problems


def _entry_names(text: str) -> list[str]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    return [
        entry.get("name")
        for entry in payload.get("plugins", [])
        if isinstance(entry, dict)
    ]


def _difference_summary(current: str, expected: str) -> list[str]:
    """Name what differs, so the gate's message is actionable without a diff tool."""
    listed = _entry_names(current)
    wanted = _entry_names(expected)
    problems = []
    missing = [name for name in wanted if name not in listed]
    extra = [name for name in listed if name not in wanted]
    if missing:
        problems.append(
            f"  not listed, but carries a Claude manifest: {', '.join(str(n) for n in missing)}"
        )
    if extra:
        problems.append(
            f"  listed, but carries no Claude manifest: {', '.join(str(n) for n in extra)}"
        )
    if listed != wanted and not missing and not extra:
        problems.append("  the same packages are listed, but not in package-name order")
    if not missing and not extra:
        problems.append("  one or more entries disagree with the manifest they describe")
    return problems


def muse_applicable_packages(root: Path = ROOT) -> list[Path]:
    """Every package directory Muse can install: a Claude manifest declaring a capability.

    A library with no Claude manifest, and a package that declares only keys
    Muse cannot load (an output style), have nothing to stage.
    """
    return [
        package
        for package in claude_packages(root)
        if any(key in _load(package / CLAUDE_MANIFEST_RELATIVE) for key in MUSE_CAPABILITY_KEYS)
    ]


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else [value]


def _expand_commands(package: Path, value: Any) -> list[str]:
    """A `commands` directory path becomes the sorted `.md` files inside it."""
    expanded: list[str] = []
    for item in _as_list(value):
        directory = package / item
        if isinstance(item, str) and directory.is_dir():
            prefix = item.rstrip("/")
            expanded.extend(
                f"{prefix}/{path.name}" for path in sorted(directory.glob("*.md")) if path.is_file()
            )
        else:
            expanded.append(item)
    return expanded


def stage_muse_plugin(package_dir: Path, dest_dir: Path) -> Path:
    """Copy one package to `dest_dir` in the shape Muse's loader accepts.

    Only the copy is rewritten: Claude-only keys are dropped from its
    `.claude-plugin/plugin.json`, `skills` and `commands` become lists of paths,
    and a bare MCP server map is wrapped under `mcpServers`.
    """
    package_dir = Path(package_dir)
    dest_dir = Path(dest_dir)
    if dest_dir.resolve() == package_dir.resolve():
        raise MarketplaceError(f"{dest_dir}: staging would overwrite the package it copies")
    if dest_dir.exists():
        shutil.rmtree(dest_dir)

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = {name for name in names if name in MUSE_STAGING_IGNORED}
        if Path(directory) == package_dir and PORTABLE_MANIFEST_NAME in names:
            skipped.add(PORTABLE_MANIFEST_NAME)
        return skipped

    shutil.copytree(package_dir, dest_dir, ignore=ignore)

    manifest_path = dest_dir / CLAUDE_MANIFEST_RELATIVE
    manifest = _load(manifest_path)
    for key in MUSE_UNSUPPORTED_KEYS:
        manifest.pop(key, None)
    if "skills" in manifest:
        manifest["skills"] = _as_list(manifest["skills"])
    if "commands" in manifest:
        manifest["commands"] = _expand_commands(package_dir, manifest["commands"])
    manifest_path.write_text(render(manifest), encoding="utf-8")

    servers = manifest.get("mcpServers")
    if isinstance(servers, str):
        servers_path = dest_dir / servers
        if servers_path.is_file():
            data = _load(servers_path)
            if "mcpServers" not in data:
                servers_path.write_text(render({"mcpServers": data}), encoding="utf-8")
    return dest_dir


def stage_muse_marketplace(
    root: Path = ROOT,
    target_dir: Path = ROOT / MUSE_STAGING_DEFAULT,
    packages: Iterable[str] | None = None,
) -> Path:
    """Stage Muse-installable packages into `target_dir` and list them.

    `packages` restricts which are (re)staged; packages already staged there are
    kept, so a partial run updates only what it names. The marketplace file lists
    everything present under `target_dir/plugins`.
    """
    target_dir = Path(target_dir)
    applicable = {package.name: package for package in muse_applicable_packages(root)}
    if packages is None:
        selected = sorted(applicable)
    else:
        selected = sorted(set(packages))
        unknown = [name for name in selected if name not in applicable]
        if unknown:
            raise MarketplaceError(
                f"not installable in Muse: {', '.join(unknown)}. "
                f"Installable packages are {', '.join(sorted(applicable))}"
            )

    plugins_dir = target_dir / PLUGIN_PARENT
    plugins_dir.mkdir(parents=True, exist_ok=True)
    for name in selected:
        stage_muse_plugin(applicable[name], plugins_dir / name)

    existing_path = root / MARKETPLACE_PATH
    catalog = _load(existing_path) if existing_path.is_file() else {}
    staged = sorted(
        path
        for path in plugins_dir.iterdir()
        if path.is_dir() and (path / CLAUDE_MANIFEST_RELATIVE).is_file()
    )
    marketplace: dict[str, Any] = {}
    for key in PRESERVED_TOP_LEVEL:
        if key in catalog:
            marketplace[key] = catalog[key]
    entries = {
        entry.get("name"): entry for entry in catalog.get("plugins", []) if isinstance(entry, dict)
    }
    marketplace["plugins"] = []
    for package in staged:
        manifest = _load(package / CLAUDE_MANIFEST_RELATIVE)
        entry: dict[str, Any] = {
            "name": package.name,
            "source": f"./{PLUGIN_PARENT}/{package.name}",
        }
        for field in CARRIED_FROM_CLAUDE_MANIFEST:
            if field in manifest:
                entry[field] = manifest[field]
        category = entries.get(package.name, {}).get("category")
        if category:
            entry["category"] = category
        marketplace["plugins"].append(entry)
    marketplace_path = target_dir / MARKETPLACE_PATH
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(render(marketplace), encoding="utf-8")
    return target_dir


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify without writing; exit non-zero when the committed file is stale",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    root = repository_root()

    if arguments.check:
        problems = check_marketplace(root)
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            return 1
        print("Marketplace is current.")
        return 0

    try:
        expected = render(build_marketplace(root))
    except MarketplaceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    path = root / MARKETPLACE_PATH
    if path.is_file() and path.read_text(encoding="utf-8") == expected:
        print("No change: the marketplace already matches the package manifests.")
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(expected, encoding="utf-8")
    listed = ", ".join(str(name) for name in _entry_names(expected)) or "nothing"
    print(f"Wrote {MARKETPLACE_PATH}, listing {listed}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
