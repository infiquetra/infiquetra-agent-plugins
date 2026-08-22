#!/usr/bin/env python3
"""Validate the public repository baseline and future plugin packages.

Standard library only, and no network access. This validator is the repository's
hermetic baseline: it must keep passing when a package index is unreachable, so
it never imports a third-party module and never fetches a schema. The published
Agent Plugins 1.0 specification requires the same of a client (section 5.2), so
the canonical ``$schema`` identifier is compared as a literal rather than
resolved.
"""

from __future__ import annotations

import hashlib
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

# Agent Plugins 1.0 requires exactly two manifest fields: `$schema` and `name`.
# This repository additionally requires `version` and `description`. That extra
# strictness is deliberate and repository-local: every package published from
# this catalog carries a real release lifecycle, so a manifest with no version
# or no description is a defect here even though the specification tolerates
# one. Recording the distinction in code keeps the repository rule from being
# mistaken for a specification rule by a later reader.
SPECIFICATION_REQUIRED_MANIFEST_FIELDS = ("name",)
REPOSITORY_REQUIRED_MANIFEST_FIELDS = ("name", "version", "description")

# The provenance manifest a synchronization script writes beside a derived
# package. It records where the bytes came from and what may be done to each
# path on the next synchronization.
PROVENANCE_FILENAME = "PROVENANCE.json"
PROVENANCE_REQUIRED_FIELDS = ("source_repository", "source_commit")

# Every path in a derived tree is exactly one of these three kinds.
BYTE_COPY = "upstream-byte-copy"
TRANSFORM = "deterministic-transform"
TARGET_OWNED = "target-owned"
PATH_CLASSIFICATIONS = (BYTE_COPY, TRANSFORM, TARGET_OWNED)

# Generated, read-only bundles live under this directory name inside a
# consuming package. Each carries a stamp block, and the digest recorded in
# that block covers the file with the stamp block itself removed, because a
# digest can never be computed over bytes that contain it.
BUNDLE_DIRECTORY_NAME = "_bundled"
BUNDLE_STAMP_BEGIN = "# --- generated bundle stamp: do not edit ---"
BUNDLE_STAMP_END = "# --- end generated bundle stamp ---"
BUNDLE_OUTPUT_DIGEST_FIELD = "output-sha256"
BUNDLE_SOURCE_DIGEST_FIELD = "source-sha256"
BUNDLE_SOURCE_PATH_FIELD = "source-path"
FLEET_CORE_PLUGIN_NAME = "fleet-core"
FLEET_BUNDLE_FILENAME = "fleet-bundle.json"

# The open Agent Skills specification permits exactly these six frontmatter
# fields, and requires a skill's `name` to match its parent directory name.
SKILL_FRONTMATTER_FIELDS = (
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
)
SKILL_DOCUMENT_NAME = "SKILL.md"

FRONTMATTER_DELIMITER = "---"
FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_path(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def plugin_directories(root: Path) -> list[Path]:
    plugins = root / "plugins"
    if not plugins.is_dir():
        return []
    return sorted(path for path in plugins.iterdir() if path.is_dir())


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
    errors: list[str] = []
    for plugin_dir in plugin_directories(root):
        manifest = plugin_dir / "plugin.json"
        relative = manifest.relative_to(root)
        if not manifest.is_file():
            # A consumer may land its build declaration (U3) before the
            # portable Agent Plugins manifest is synchronized (U10). That
            # directory is not yet a plugin package, so a missing manifest
            # is not a defect while the declaration is present.
            if (plugin_dir / FLEET_BUNDLE_FILENAME).is_file():
                continue
            errors.append(f"missing plugin manifest: {relative}")
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid plugin manifest {relative}: {exc}")
            continue
        if payload.get("$schema") != PLUGIN_SCHEMA:
            errors.append(f"unexpected or missing $schema in {relative}")
        for field in REPOSITORY_REQUIRED_MANIFEST_FIELDS:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"missing non-empty {field} in {relative}")
    return errors


def _relative_path_error(relative_manifest: Path, index: int, path_value: object) -> str | None:
    if not isinstance(path_value, str) or not path_value.strip():
        return f"provenance entry {index} in {relative_manifest} has no path"
    candidate = Path(path_value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return f"provenance entry {index} in {relative_manifest} has an unsafe path: {path_value}"
    return None


def _check_provenance_entry(
    root: Path,
    plugin_dir: Path,
    relative_manifest: Path,
    index: int,
    entry: object,
) -> list[str]:
    if not isinstance(entry, dict):
        return [f"provenance entry {index} in {relative_manifest} is not an object"]

    path_value = entry.get("path")
    path_error = _relative_path_error(relative_manifest, index, path_value)
    if path_error is not None:
        return [path_error]

    assert isinstance(path_value, str)
    target = plugin_dir / path_value
    relative_target = target.relative_to(root)

    errors: list[str] = []
    classification = entry.get("classification")
    if classification not in PATH_CLASSIFICATIONS:
        errors.append(
            f"unknown provenance classification for {relative_target} in "
            f"{relative_manifest}: {classification!r}"
        )

    if not target.is_file():
        errors.append(f"provenance file missing: {relative_target}")
        return errors

    recorded = entry.get("sha256")
    if classification == TARGET_OWNED:
        # Target-owned source has no upstream counterpart and is never
        # overwritten by synchronization, so pinning its digest here would only
        # make an ordinary edit to it look like tampering.
        if recorded is not None:
            errors.append(
                f"target-owned provenance entry must not record a digest: {relative_target} "
                f"in {relative_manifest}"
            )
        return errors

    if classification == TRANSFORM:
        for field in ("source_sha256", "transform_version"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(
                    f"transform provenance entry missing {field}: {relative_target} "
                    f"in {relative_manifest}"
                )

    if not isinstance(recorded, str) or not recorded.strip():
        errors.append(f"provenance entry missing sha256: {relative_target} in {relative_manifest}")
        return errors

    actual = sha256_path(target)
    if actual != recorded:
        errors.append(
            f"provenance digest mismatch: {relative_target} "
            f"(manifest {recorded}, content {actual})"
        )
    return errors


def check_provenance_manifests(root: Path) -> list[str]:
    """Verify each derived package against its own provenance manifest.

    The check is pure local computation: it recomputes the digest of every file
    the manifest lists and compares it to the recorded value. A package with no
    manifest is not an error here, because a package authored in this
    repository has no upstream to pin.
    """
    errors: list[str] = []
    for plugin_dir in plugin_directories(root):
        manifest = plugin_dir / PROVENANCE_FILENAME
        if not manifest.is_file():
            continue
        relative = manifest.relative_to(root)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid provenance manifest {relative}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"invalid provenance manifest {relative}: expected an object")
            continue
        for field in PROVENANCE_REQUIRED_FIELDS:
            value = payload.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"missing non-empty {field} in {relative}")
        entries = payload.get("files")
        if not isinstance(entries, list):
            errors.append(f"missing files list in {relative}")
            continue
        for index, entry in enumerate(entries):
            errors.extend(_check_provenance_entry(root, plugin_dir, relative, index, entry))
    return errors


def split_bundle_stamp(text: str) -> tuple[list[str] | None, str]:
    """Split a generated bundle into its stamp block and its remaining bytes.

    Returns ``(None, text)`` when the file carries no stamp block. The second
    element is what the recorded output digest covers, so the stamp is never
    inside the bytes it describes.
    """
    lines = text.splitlines(keepends=True)
    begin: int | None = None
    end: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if begin is None:
            if stripped == BUNDLE_STAMP_BEGIN:
                begin = index
        elif stripped == BUNDLE_STAMP_END:
            end = index
            break
    if begin is None or end is None:
        return None, text
    return lines[begin : end + 1], "".join(lines[:begin] + lines[end + 1 :])


def parse_bundle_stamp(stamp_lines: list[str]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in stamp_lines:
        body = line.strip().lstrip("#").strip()
        key, separator, value = body.partition(":")
        if not separator:
            continue
        key = key.strip()
        if key and key not in fields:
            fields[key] = value.strip()
    return fields


def bundle_output_digest(text: str) -> str:
    """Digest of a generated bundle with its own stamp block excluded."""
    _, payload = split_bundle_stamp(text)
    return sha256_text(payload)


def _bundled_files(root: Path) -> list[Path]:
    plugins = root / "plugins"
    if not plugins.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(plugins.rglob("*")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if BUNDLE_DIRECTORY_NAME not in parts or "__pycache__" in parts:
            continue
        found.append(path)
    return found


def check_bundled_files(root: Path) -> list[str]:
    """Reject a generated bundle that is stale against its source or hand-edited.

    Two digest domains, because a stamp cannot hash the bytes that contain it.
    The generated-output digest (``output-sha256``) covers the file with the
    stamp excluded and fails as ``stale bundle`` when the body was edited. The
    source-payload digest (``source-sha256``) covers the live Fleet Core module
    and fails as ``stale source`` when that module moved and the bundle was not
    regenerated. The two signals are independent.
    """
    errors: list[str] = []
    for path in _bundled_files(root):
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"unreadable generated bundle {relative}: {exc}")
            continue
        stamp_lines, payload = split_bundle_stamp(text)
        if stamp_lines is None:
            errors.append(f"unstamped generated bundle: {relative}")
            continue
        stamp = parse_bundle_stamp(stamp_lines)
        recorded = stamp.get(BUNDLE_OUTPUT_DIGEST_FIELD)
        if not recorded:
            errors.append(
                f"generated bundle stamp missing {BUNDLE_OUTPUT_DIGEST_FIELD}: {relative}"
            )
        else:
            actual = sha256_text(payload)
            if actual != recorded:
                errors.append(
                    f"stale bundle: {relative} (stamp {recorded}, content {actual})"
                )
        errors.extend(_check_bundle_source_freshness(root, relative, stamp))
    return errors


def _check_bundle_source_freshness(
    root: Path,
    relative: Path,
    stamp: dict[str, str],
) -> list[str]:
    """Compare the stamp's source-payload digest to the live Fleet Core module.

    Skipped when this tree has no portable Fleet Core package, or when the
    stamp does not name a source path: those are the U1 fixture shape, which
    only asserted the generated-output digest. The two domains are independent,
    so a hand-edited body still reports as a stale bundle even when the source
    digest still matches.
    """
    source_rel = stamp.get(BUNDLE_SOURCE_PATH_FIELD)
    recorded = stamp.get(BUNDLE_SOURCE_DIGEST_FIELD)
    if not source_rel or not recorded:
        return []

    candidate = Path(source_rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        return [f"generated bundle stamp has an unsafe source-path: {relative}"]

    fleet_core = root / "plugins" / FLEET_CORE_PLUGIN_NAME
    if not fleet_core.is_dir():
        return []

    module = candidate.stem
    source_file = fleet_core / candidate
    if not source_file.is_file():
        return [
            f"stale source: {module} in {relative}: source file missing: "
            f"{source_file.relative_to(root)}"
        ]

    actual = sha256_path(source_file)
    if actual == recorded:
        return []
    return [
        f"stale source: {module} in {relative} (stamp {recorded}, source {actual})"
    ]


def check_fleet_bundle_declarations(root: Path) -> list[str]:
    """Validate each consumer's closed Fleet Core build declaration.

    The declaration cannot live in the Agent Plugins manifest, whose schema
    forbids assigning semantics to unrecognized top-level fields. Checking it
    here keeps continuous integration hermetic: no network, no extra tool.
    """
    errors: list[str] = []
    # Lazy import: the bundler imports this module for stamp helpers, so a
    # top-level import would cycle while this file is still loading.
    from bundle_fleet_module import validate_declaration_file

    for plugin_dir in plugin_directories(root):
        declaration = plugin_dir / FLEET_BUNDLE_FILENAME
        if not declaration.is_file():
            continue
        relative = str(declaration.relative_to(root))
        errors.extend(validate_declaration_file(declaration, origin=relative))
    return errors


def read_frontmatter(text: str) -> dict[str, str] | None:
    """Read the top-level scalar keys of a YAML frontmatter block.

    Deliberately minimal, because this validator stays standard-library-only
    and Python ships no YAML parser. It reads top-level keys and their scalar
    values, which is all the two conformance rules need, and ignores nested
    mapping and sequence content. Returns ``None`` when the document carries no
    terminated frontmatter block.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER:
        return None
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == FRONTMATTER_DELIMITER:
            return fields
        if not line.strip() or line[0] in " \t-#":
            continue
        match = FRONTMATTER_KEY.match(line)
        if match:
            fields[match.group(1)] = _frontmatter_scalar(match.group(2))
    return None


def _frontmatter_scalar(raw: str | None) -> str:
    value = (raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def check_skill_frontmatter(root: Path) -> list[str]:
    """Check portable skills against the open Agent Skills specification.

    Only the portable skills tree at a package root is checked. A client
    extension directory carries that client's own conventions and is out of
    scope for the portable rules.
    """
    errors: list[str] = []
    for plugin_dir in plugin_directories(root):
        skills = plugin_dir / "skills"
        if not skills.is_dir():
            continue
        for skill_dir in sorted(path for path in skills.iterdir() if path.is_dir()):
            document = skill_dir / SKILL_DOCUMENT_NAME
            relative = document.relative_to(root)
            if not document.is_file():
                errors.append(f"missing skill document: {relative}")
                continue
            try:
                text = document.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"unreadable skill document {relative}: {exc}")
                continue
            fields = read_frontmatter(text)
            if fields is None:
                errors.append(f"missing or unterminated frontmatter in {relative}")
                continue
            for field in fields:
                if field not in SKILL_FRONTMATTER_FIELDS:
                    errors.append(f"disallowed skill frontmatter field in {relative}: {field}")
            name = fields.get("name")
            if name is None:
                errors.append(f"missing frontmatter name in {relative}")
            elif name != skill_dir.name:
                errors.append(
                    f"skill name mismatch in {relative}: frontmatter name {name!r} "
                    f"does not match directory {skill_dir.name!r}"
                )
    return errors


def check_repo(root: Path) -> list[str]:
    return [
        *check_required_paths(root),
        *check_markdown_links(root),
        *check_plugin_manifests(root),
        *check_provenance_manifests(root),
        *check_bundled_files(root),
        *check_fleet_bundle_declarations(root),
        *check_skill_frontmatter(root),
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
