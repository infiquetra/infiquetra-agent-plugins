#!/usr/bin/env python3
"""Generate the Codex marketplace and each package's Codex manifest.

Codex CLI 0.155.1 installs a catalog with two commands, and it looks for the
files in exactly two places:

* ``<repository>/.agents/plugins/marketplace.json`` is the marketplace.
  ``codex plugin marketplace add <repository>`` records it as
  ``[marketplaces.<name>]`` with ``source_type = "local"`` and ``source`` set
  to that directory. The command does not install any plugin.
* ``plugins/<package>/.codex-plugin/plugin.json`` is the plugin manifest.
  ``codex plugin add <package>@<marketplace>`` installs it and records
  ``[plugins."<package>@<marketplace>"]`` with ``enabled = true``.

Those paths are the ones the CLI help, ``~/.codex/config.toml``, the OpenAI
bundled marketplace, and ``infiquetra-codex-plugins`` all use. A marketplace
file under ``com.infiquetra.codex/`` is not one of them. The manifest may
sit outside the adapter because the CLI refuses any other location, and it
carries paths, not behaviour.

**What decides the listing.** A package is listed exactly when
``plugins/<package>/plugin.json`` exists. That is the portable manifest.
The Codex manifest is generated beside it. A package that also has
``.claude-plugin/`` stays listed: the CLI accepted that sibling in a local
marketplace add, and an installed copy of ``google-cloud-developer`` contains
both directories. The dedicated Codex repository's own validator rejects the
sibling. That validator is not the CLI.

**Where each field comes from.** ``name``, ``version``, and ``description``
are copied from the portable manifest. ``skills`` is ``./skills/`` when that
directory exists, and ``./com.infiquetra.codex/skills/`` only when the
portable directory does not and the adapter does. ``mcpServers`` is a path
to ``com.infiquetra.codex/.mcp.json`` when that file exists. ``hooks`` and
``interface.defaultPrompt`` are omitted: the CLI listed a plugin that had
neither, the bundled scaffold says validation rejects ``hooks``, and a
prompt is behaviour. ``interface.displayName`` is the package name with
hyphens spelled out, and ``interface.shortDescription`` is the portable
description.

**What is preserved.** The marketplace ``name`` and ``interface``, and each
entry's ``category``, are kept from the existing file. Nothing under
``plugins/`` is a catalog name or a browsing category. The entry ``policy``
is always ``installation = AVAILABLE`` and ``authentication = ON_INSTALL``,
which is the policy block in both marketplaces the CLI already loads.

Standard library only, and no network access, matching the rest of this
repository's tooling.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


MARKETPLACE_PATH = Path(".agents") / "plugins" / "marketplace.json"
PLUGIN_PARENT = "plugins"
PORTABLE_MANIFEST_NAME = "plugin.json"
CODEX_MANIFEST_RELATIVE = Path(".codex-plugin") / "plugin.json"
ADAPTER_NAME = "com.infiquetra.codex"

#: Marketplace keys that describe the catalog, not a package.
PRESERVED_TOP_LEVEL = ("name", "interface")

DEFAULT_MARKETPLACE_NAME = "infiquetra-agent-plugins"
DEFAULT_INTERFACE = {
    "displayName": "Infiquetra Agent Plugins",
    "shortDescription": "Codex marketplace for the Infiquetra portable Agent Plugins catalog.",
}

#: Entry policy in the OpenAI bundled marketplace and in infiquetra-codex-plugins.
ENTRY_POLICY = {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}

#: Portable fields copied when present. Anything else in that file is not a
#: Codex manifest field, and copying it would smuggle behaviour across.
PORTABLE_STRINGS = ("homepage", "repository", "license")


class PackagingError(Exception):
    """The Codex packaging could not be generated, and says why."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PackagingError(f"{path}: could not be read as JSON: {error}") from error
    if not isinstance(payload, dict):
        raise PackagingError(f"{path}: expected a JSON object")
    return payload


def portable_packages(root: Path) -> list[Path]:
    """Every package directory that carries a portable plugin manifest."""
    packages = root / PLUGIN_PARENT
    if not packages.is_dir():
        return []
    return sorted(
        path
        for path in packages.iterdir()
        if path.is_dir()
        and not path.name.startswith(".")
        and (path / PORTABLE_MANIFEST_NAME).is_file()
    )


def _require_text(manifest: dict[str, Any], field: str, path: Path) -> str:
    value = manifest.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PackagingError(f"{path}: {field} must be a non-empty string")
    return value


def display_name(package_name: str) -> str:
    """A display name spelled from the package directory, not from a new label."""
    return " ".join(part.capitalize() for part in package_name.split("-") if part)


def _skills_path(package: Path) -> str | None:
    if (package / "skills").is_dir():
        return "./skills/"
    adapter_skills = package / ADAPTER_NAME / "skills"
    if adapter_skills.is_dir():
        return f"./{ADAPTER_NAME}/skills/"
    return None


def build_plugin_manifest(package: Path) -> dict[str, Any]:
    """The Codex manifest for one package. Paths only, plus identity."""
    portable_path = package / PORTABLE_MANIFEST_NAME
    portable = _load(portable_path)
    name = _require_text(portable, "name", portable_path)
    if name != package.name:
        raise PackagingError(
            f"{portable_path}: names {name!r} but sits in {package.name}/. "
            "The Codex manifest name is the directory name, so the two have to agree"
        )
    version = _require_text(portable, "version", portable_path)
    description = _require_text(portable, "description", portable_path)

    manifest: dict[str, Any] = {
        "name": name,
        "version": version,
        "description": description,
    }
    author = portable.get("author")
    if isinstance(author, dict) and isinstance(author.get("name"), str) and author["name"].strip():
        manifest["author"] = author
    for field in PORTABLE_STRINGS:
        value = portable.get(field)
        if isinstance(value, str) and value.strip():
            manifest[field] = value
    keywords = portable.get("keywords")
    if isinstance(keywords, list) and keywords and all(isinstance(item, str) for item in keywords):
        manifest["keywords"] = keywords

    skills = _skills_path(package)
    if skills is not None:
        manifest["skills"] = skills
    adapter_mcp = package / ADAPTER_NAME / ".mcp.json"
    if adapter_mcp.is_file():
        manifest["mcpServers"] = f"./{ADAPTER_NAME}/.mcp.json"

    manifest["interface"] = {
        "displayName": display_name(name),
        "shortDescription": description,
    }
    return manifest


def _existing_entries(existing: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = existing.get("plugins")
    if not isinstance(entries, list):
        return {}
    return {
        entry.get("name"): entry
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("name"), str)
    }


def build_entry(package: Path, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """One marketplace entry. ``category`` is the only field kept from before."""
    entry: dict[str, Any] = {
        "name": package.name,
        "source": {"source": "local", "path": f"./{PLUGIN_PARENT}/{package.name}"},
        "policy": dict(ENTRY_POLICY),
    }
    category = (existing or {}).get("category")
    if isinstance(category, str) and category.strip():
        entry["category"] = category
    return entry


def build_marketplace(root: Path) -> dict[str, Any]:
    """The marketplace this repository's portable packages describe."""
    existing_path = root / MARKETPLACE_PATH
    existing = _load(existing_path) if existing_path.is_file() else {}
    entries = _existing_entries(existing)

    marketplace: dict[str, Any] = {}
    for key in PRESERVED_TOP_LEVEL:
        if key in existing:
            marketplace[key] = existing[key]
    if "name" not in marketplace:
        marketplace["name"] = DEFAULT_MARKETPLACE_NAME
    if "interface" not in marketplace:
        marketplace["interface"] = dict(DEFAULT_INTERFACE)
    marketplace["plugins"] = [
        build_entry(package, entries.get(package.name)) for package in portable_packages(root)
    ]
    return marketplace


def render(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def expected_texts(root: Path) -> dict[Path, str]:
    """Repository-relative path to the text the generator would write."""
    texts: dict[Path, str] = {}
    for package in portable_packages(root):
        relative = Path(PLUGIN_PARENT) / package.name / CODEX_MANIFEST_RELATIVE
        texts[relative] = render(build_plugin_manifest(package))
    texts[MARKETPLACE_PATH] = render(build_marketplace(root))
    return texts


def _manifests_on_disk(root: Path) -> list[Path]:
    packages = root / PLUGIN_PARENT
    if not packages.is_dir():
        return []
    return sorted(
        path.relative_to(root)
        for path in packages.glob(f"*/{CODEX_MANIFEST_RELATIVE.as_posix()}")
        if path.is_file()
    )


def check_codex_packaging(root: Path) -> list[str]:
    """Problems with the committed Codex packaging, or an empty list when current.

    Imported by ``scripts/check_repo.py`` so a stale manifest fails the
    repository gate rather than being discovered by a person who cannot
    install a package the catalog says it ships.
    """
    try:
        expected = expected_texts(root)
    except PackagingError as error:
        return [f"codex packaging: {error}"]

    problems: list[str] = []
    for relative, text in expected.items():
        path = root / relative
        if not path.is_file():
            problems.append(
                f"missing Codex packaging file: {relative}. "
                "Run `python3 scripts/sync_codex_packaging.py`"
            )
            continue
        if path.read_text(encoding="utf-8") != text:
            problems.append(
                f"{relative} is stale. Run `python3 scripts/sync_codex_packaging.py`"
            )
    expected_manifests = {
        relative
        for relative in expected
        if relative.name == "plugin.json" and ".codex-plugin" in relative.parts
    }
    for relative in _manifests_on_disk(root):
        if relative not in expected_manifests:
            problems.append(
                f"unexpected Codex manifest: {relative}. The generator writes one "
                "only for a package that has a portable plugin.json"
            )
    return problems


def write_packaging(root: Path) -> list[str]:
    """Write the generated files. Returns the relative paths that changed."""
    expected = expected_texts(root)
    changed: list[str] = []
    for relative, text in expected.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        path.write_text(text, encoding="utf-8")
        changed.append(relative.as_posix())
    for relative in _manifests_on_disk(root):
        if relative in expected:
            continue
        path = root / relative
        path.unlink()
        parent = path.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
        changed.append(f"removed {relative.as_posix()}")
    return changed


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify without writing; exit non-zero when a committed file is stale",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    root = repository_root()
    if arguments.check:
        problems = check_codex_packaging(root)
        if problems:
            for problem in problems:
                print(f"ERROR: {problem}", file=sys.stderr)
            return 1
        print("Codex packaging is current.")
        return 0
    try:
        changed = write_packaging(root)
    except PackagingError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if not changed:
        print("No change: Codex packaging already matches the package manifests.")
        return 0
    print("Updated " + ", ".join(changed) + ".")
    return 0


if __name__ == "__main__":
    sys.exit(main())
