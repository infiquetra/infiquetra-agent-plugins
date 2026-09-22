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
release without. `keywords` and `category` are read from the portable
`plugin.json` when it carries them, falling back to the Claude manifest for
`keywords`, which is where the catalog actually keeps them today.

**What is preserved.** The top-level `name`, `owner`, and `metadata` block are
carried from the existing file unchanged. They describe the catalog rather than
any package, so nothing in `plugins/` could derive them.

Standard library only, and no network access, matching the rest of this
repository's tooling.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

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
    "author",
    "repository",
    "license",
)

#: Catalog-level keys preserved from the existing file. Nothing under
#: `plugins/` describes the catalog itself, so these cannot be derived.
PRESERVED_TOP_LEVEL = ("name", "owner", "metadata")


class MarketplaceError(Exception):
    """The marketplace could not be generated, and says why."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


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

    keywords = portable.get("keywords", claude.get("keywords"))
    if keywords:
        entry["keywords"] = keywords
    category = portable.get("category", (existing or {}).get("category"))
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
