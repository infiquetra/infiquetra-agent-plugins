#!/usr/bin/env python3
"""Validate the public repository baseline and future plugin packages."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote


REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    ".gitignore",
    "CLAUDE.md",
    "GEMINI.md",
    "llms.txt",
    ".github/CODEOWNERS",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/copilot-instructions.md",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/ISSUE_TEMPLATE/capability.yml",
    ".github/ISSUE_TEMPLATE/enhancement.yml",
    ".github/ISSUE_TEMPLATE/defect.yml",
    ".github/ISSUE_TEMPLATE/exploration.yml",
    ".github/ISSUE_TEMPLATE/context-update.yml",
    ".github/workflows/ci.yml",
    "docs/README.md",
    "docs/public-safe-summary.md",
    "docs/cross-vendor-plugin-architecture-brief.md",
    "docs/engineering-journal/README.md",
    "docs/engineering-journal/LEARNINGS.md",
    "docs/engineering-journal/DECISIONS.md",
    "docs/engineering-journal/QUEUED.md",
    "docs/engineering-journal/ARCHIVE.md",
    "docs/engineering-journal/narratives/_template.md",
    "docs/engineering-journal/audits/_template.md",
)

MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:")
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"


def check_required_paths(root: Path) -> list[str]:
    return [f"missing required path: {path}" for path in REQUIRED_PATHS if not (root / path).exists()]


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        target = target[1 : target.index(">")]
    else:
        target = target.split(maxsplit=1)[0]
    return unquote(target.split("#", 1)[0])


def check_markdown_links(root: Path) -> list[str]:
    errors: list[str] = []
    for document in sorted(root.rglob("*.md")):
        if ".git" in document.parts:
            continue
        text = document.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            raw = match.group(1).strip()
            if raw.startswith(EXTERNAL_PREFIXES) or raw.startswith("#"):
                continue
            target = _link_target(raw)
            if not target or "{" in target or "}" in target:
                continue
            destination = (document.parent / target).resolve()
            if not destination.exists():
                relative_document = document.relative_to(root)
                errors.append(f"broken local link in {relative_document}: {raw}")
    return errors


def check_plugin_manifests(root: Path) -> list[str]:
    plugins = root / "plugins"
    if not plugins.exists():
        return []

    errors: list[str] = []
    for plugin_dir in sorted(path for path in plugins.iterdir() if path.is_dir()):
        manifest = plugin_dir / "plugin.json"
        relative = manifest.relative_to(root)
        if not manifest.is_file():
            errors.append(f"missing plugin manifest: {relative}")
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid plugin manifest {relative}: {exc}")
            continue
        if payload.get("$schema") != PLUGIN_SCHEMA:
            errors.append(f"unexpected or missing $schema in {relative}")
        for field in ("name", "version", "description"):
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"missing non-empty {field} in {relative}")
    return errors


def check_repo(root: Path) -> list[str]:
    return [
        *check_required_paths(root),
        *check_markdown_links(root),
        *check_plugin_manifests(root),
    ]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors = check_repo(root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Repository validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
