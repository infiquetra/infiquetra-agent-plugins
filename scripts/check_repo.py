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

# The only files inside a derived package that its manifest is not required to
# classify: the manifest itself, which cannot record its own digest, and
# interpreter artifacts, which are never committed. Everything else must be
# accounted for, in both directions.
#
# The bytecode exemption is about *placement*, not about the suffix. Keyed on
# the suffix alone it exempted those suffixes anywhere in the tree at any depth,
# so `plugins/unifi/skills/unifi-network/scripts/smuggled.pyo` could hold
# arbitrary text and pass this gate unlisted. See `_is_interpreter_bytecode`.
PROVENANCE_UNMANAGED_NAMES = (PROVENANCE_FILENAME,)
PROVENANCE_UNMANAGED_DIRECTORY_NAMES = ("__pycache__",)
PROVENANCE_BYTECODE_SUFFIXES = (".pyc", ".pyo")

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
BUNDLE_GENERATED_BY_FIELD = "generated-by"
BUNDLE_SOURCE_VERSION_FIELD = "source-version"
BUNDLE_SOURCE_COMMIT_FIELD = "source-commit"

# Every field the bundler writes into a stamp is required here. Any one of them
# left optional can simply be deleted by hand, which disables the comparison it
# feeds while this gate still reports green: without `source-path` and
# `source-sha256` there is no comparison with Fleet Core at all, and without
# `source-version` and `source-commit` nothing records which upstream release
# the bytes came from.
BUNDLE_REQUIRED_STAMP_FIELDS = (
    BUNDLE_GENERATED_BY_FIELD,
    BUNDLE_SOURCE_VERSION_FIELD,
    BUNDLE_SOURCE_COMMIT_FIELD,
    BUNDLE_SOURCE_PATH_FIELD,
    BUNDLE_SOURCE_DIGEST_FIELD,
    BUNDLE_OUTPUT_DIGEST_FIELD,
)
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

# Credential detection by value rather than by field name. Every other guard in
# this repository rejects credential-shaped field *names*; a real key, password,
# or bearer token pasted into an allowed free-text value — a profile's `notes`,
# `description`, or `ownership` string — passes all of them. These two families
# close that gap. A bare high-entropy scan was rejected as the third family: a
# provenance manifest is nothing but sha256 digests, so bare entropy would fire
# on every package in the catalog and the gate would be turned off within a day.
#
# Family one: literal formats that are credentials wherever they appear. Matched
# in every text file of a package, source included, because a real key committed
# into source is a leak regardless of what the surrounding code does with it.
CREDENTIAL_FORMATS = (
    ("AWS access key id", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe secret key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{24,}\b")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    (
        "JSON web token",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    ("private key block", re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----")),
    ("credential embedded in a URL", re.compile(r"://[^/\s:@]+:[^/\s@]{3,}@")),
)

# Family two: a credential-shaped key assigned a value that carries real entropy.
# Applied only to data and documentation files, never to source. Source that
# *handles* a credential legitimately names one on almost every line
# (`api_key = (api_key or "").strip()`, `"X-Api-Key": self.api_key`), and firing
# there produces nothing but false positives; a literal key in source is family
# one's job.
CREDENTIAL_VALUE_DATA_SUFFIXES = (
    ".cfg",
    ".conf",
    ".env",
    ".ini",
    ".json",
    ".md",
    ".properties",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
)
# Mirrors ``site_profile.CREDENTIAL_NAME_FRAGMENTS``. The strict in-text key set
# is derived from it rather than spelled out a second time, which is what stops
# the gate and the two loaders drifting into separate dialects of one rule.
CREDENTIAL_NAME_FRAGMENTS = (
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "passphrase",
    "passwd",
    "password",
    "privatekey",
    "secret",
    "token",
)

# Mirrors ``site_profile.CREDENTIAL_KEY_EXACT_IN_TEXT``. Short and compound
# spellings that occur inside free text but never as a schema property name.
# Matched whole, so a field called ``author`` is not mistaken for ``auth``.
CREDENTIAL_KEY_EXACT_IN_TEXT = ("auth", "accesskey", "clientsecret")

# Mirrors ``site_profile.CREDENTIAL_ASSIGNMENT_IN_TEXT``. The value is captured
# by lookahead so the match itself ends at the delimiter.
# Consuming the value instead let an innocent key swallow a strict one standing
# inside it: in ``"notes": "controller password=hunter2"`` the scan matched
# ``notes``, found it harmless, and resumed *after* the password it had eaten.#
# An assignment is one line, and "one line" has to mean the same thing here as it
# does in the gate, which reads a line with ``str.splitlines()``. Naming only
# ``\n`` was the first repair of this defect and fixed one instance of it: nine
# other boundaries still diverged and eight were fail-open in the loader.
#: Every boundary ``str.splitlines()`` recognises, which is the definition the
#: repository gate reads a line by. ``\r\n`` needs no separate entry: both of its
#: characters are here, so neither can be consumed as horizontal whitespace and
#: neither can appear inside a value.
CREDENTIAL_LINE_BREAKS = "\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029"

#: The same set as a regular-expression character-class body, built from the
#: string above so the two cannot disagree.
_LINE_BREAK_CLASS = "".join(
    f"\\x{ord(character):02x}" if ord(character) < 0x100 else f"\\u{ord(character):04x}"
    for character in CREDENTIAL_LINE_BREAKS
)

CREDENTIAL_ASSIGNMENT_IN_TEXT = re.compile(
    r"(?i)(?:^|[^A-Za-z0-9_-])([A-Za-z][A-Za-z0-9_-]{1,31})[\"']?"
    rf"[^\S{_LINE_BREAK_CLASS}]*[:=][^\S{_LINE_BREAK_CLASS}]*"
    rf"[\"']?(?=([^\"',;{_LINE_BREAK_CLASS}]{{1,200}}))"
)

# Mirrors ``site_profile.CREDENTIAL_SCHEME_WORDS``. An auth scheme word sits
# between the key and the credential in ``authorization: Bearer <token>``, so
# scheme words and placeholders are stepped over and the literal standing behind
# them is what gets graded.
CREDENTIAL_SCHEME_WORDS = frozenset(
    {"bearer", "basic", "digest", "token", "apikey", "hmac", "negotiate"}
)

# Mirrors ``site_profile.CREDENTIAL_TEMPLATE_EXPRESSION``. A reference written in
# several whitespace-separated pieces is collapsed to one placeholder before the
# value is split, so a bare inner word is never graded as the candidate.
CREDENTIAL_TEMPLATE_EXPRESSION = re.compile(
    r"\$\{[^}]*\}|\{\{[^}]*\}\}|\{%[^%]*%\}|%\([^)]*\)s?|\$[A-Za-z_][A-Za-z0-9_]*"
)

# Values that name a secret rather than being one. A profile is expected to point
# at where the credential lives, so these must never be reported.
CREDENTIAL_PLACEHOLDER = re.compile(
    r"(?i)^(?:redacted|removed|omitted|none|null|true|false|unset|empty|"
    r"change[_-]?me|example|placeholder|your[_-].*|my[_-].*|"
    r"x{3,}|\*{3,}|\.{3,}|-{3,}|_{3,})$"
)
CREDENTIAL_REFERENCE_PREFIX = re.compile(
    r"(?i)^(?:env|vault|op|aws|gcp|azure|secretref|ref)[:/]"
)


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


def _is_interpreter_bytecode(plugin_dir: Path, relative: Path) -> bool:
    """Compiled bytecode sitting where the interpreter actually writes it.

    CPython writes bytecode in exactly two places (PEP 3147): under a
    ``__pycache__`` directory, and — in the legacy sourceless layout — beside
    the ``.py`` file it was compiled from. Those two shapes are checkout noise
    and stay exempt from the closed set.

    A bytecode suffix anywhere else names an ordinary package file wearing a
    costume, and the manifest has to classify it. Exempting the suffix at any
    depth is what let a file named ``smuggled.pyo``, holding plain text, pass
    this gate without appearing in any provenance manifest.
    """
    if relative.suffix not in PROVENANCE_BYTECODE_SUFFIXES:
        return False
    if any(part in PROVENANCE_UNMANAGED_DIRECTORY_NAMES for part in relative.parts):
        return True
    return (plugin_dir / relative).with_suffix(".py").is_file()


def _managed_package_files(plugin_dir: Path) -> list[str]:
    """Every file inside a package that its provenance manifest must classify."""
    found: list[str] = []
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(plugin_dir)
        if any(part in PROVENANCE_UNMANAGED_DIRECTORY_NAMES for part in relative.parts):
            continue
        if relative.name in PROVENANCE_UNMANAGED_NAMES:
            continue
        if _is_interpreter_bytecode(plugin_dir, relative):
            continue
        found.append(relative.as_posix())
    return found


def _closed_set_errors(
    root: Path,
    plugin_dir: Path,
    relative_manifest: Path,
    entries: list[object],
) -> list[str]:
    """Report the manifest and the package tree disagreeing on which files exist.

    ``_check_provenance_entry`` verifies only what the manifest already lists, so
    on its own it stays green after a managed entry is deleted from the manifest
    and after an unlisted executable is added to the package. Both directions are
    the same defect — the manifest has stopped describing the tree — so both are
    errors here, together with a path listed twice, which would otherwise let one
    file carry two different classifications and break the package's promise that
    every path has exactly one.

    Entries with an unusable path are skipped rather than counted as listed:
    ``_check_provenance_entry`` has already reported them by name.
    """
    listed: set[str] = set()
    duplicates: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path_value = entry.get("path")
        if not isinstance(path_value, str) or not path_value.strip():
            continue
        candidate = Path(path_value)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        normalized = candidate.as_posix()
        if normalized in listed:
            if normalized not in duplicates:
                duplicates.append(normalized)
            continue
        listed.add(normalized)

    errors = [
        f"duplicate provenance entry for {(plugin_dir / path).relative_to(root)} "
        f"in {relative_manifest}"
        for path in duplicates
    ]
    errors.extend(
        f"unlisted package file: {(plugin_dir / path).relative_to(root)} is not "
        f"classified by {relative_manifest}"
        for path in _managed_package_files(plugin_dir)
        if path not in listed
    )
    return errors


def check_provenance_manifests(root: Path) -> list[str]:
    """Verify each derived package against its own provenance manifest.

    The check is pure local computation: it recomputes the digest of every file
    the manifest lists and compares it to the recorded value. A package with no
    manifest is not an error here, because a package authored in this
    repository has no upstream to pin.

    The manifest is also closed over the package tree. Recomputing listed digests
    says nothing about a file the manifest never mentions, so ``_closed_set_errors``
    compares the two sets in both directions and rejects duplicate entries.
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
        errors.extend(_closed_set_errors(root, plugin_dir, relative, entries))
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

    Every field in ``BUNDLE_REQUIRED_STAMP_FIELDS`` is required and reported by
    name when absent. An optional field is a comparison that can be switched off
    by deleting one line, which is the same as not having the comparison.
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
        for field in BUNDLE_REQUIRED_STAMP_FIELDS:
            if not stamp.get(field, "").strip():
                errors.append(f"generated bundle stamp missing {field}: {relative}")
        recorded = stamp.get(BUNDLE_OUTPUT_DIGEST_FIELD)
        if recorded:
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

    Both stamp fields this reads are required by ``check_bundled_files``, so a
    stamp missing either has already been reported there by name; returning
    nothing here only avoids naming the same omission twice. The comparison
    itself is skipped when the tree carries no portable Fleet Core package,
    because there is then no live module to compare against. The two digest
    domains are independent, so a hand-edited body still reports as a stale
    bundle even when the source digest still matches.
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


def check_fleet_bundle_outputs(root: Path) -> list[str]:
    """Verify the build declaration and the generated tree name the same files.

    ``check_bundled_files`` reads the bundles that are on disk, so it cannot see
    a bundle that was never generated at all. That blind spot is what let this
    package ship two client scripts importing a module nothing had written: the
    declaration named it, the tree did not carry it, and every validator passed.
    A declared module with no generated bundle, and a generated bundle no
    declaration accounts for, are both reported here.
    """
    # Lazy import for the same reason as the declaration check above: the
    # bundler imports this module for its stamp helpers.
    from bundle_fleet_module import BundleError, plan_copies, presence_errors
    from bundle_fleet_module import validate_declaration_file

    errors: list[str] = []
    for plugin_dir in plugin_directories(root):
        declaration = plugin_dir / FLEET_BUNDLE_FILENAME
        if not declaration.is_file():
            continue
        relative = str(declaration.relative_to(root))
        if validate_declaration_file(declaration, origin=relative):
            # A payload that fails its own schema cannot be planned from, and
            # check_fleet_bundle_declarations has already named the field.
            continue
        try:
            planned = plan_copies(root, plugin_dir)
        except BundleError as exc:
            errors.append(f"unusable fleet-bundle declaration {relative}: {exc}")
            continue
        errors.extend(presence_errors(root, plugin_dir, planned))
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


def _names_a_secret(value: str) -> bool:
    """True when the value points at where a credential lives instead of being one."""
    if CREDENTIAL_PLACEHOLDER.match(value):
        return True
    if CREDENTIAL_REFERENCE_PREFIX.match(value):
        return True
    if value.startswith(("$", "<", "{{", "{%", "%(")) or value.endswith(">"):
        return True
    if "${" in value or "{{" in value:
        return True
    return len(set(value)) <= 2 or value.isdigit()


def _is_strict_credential_key(key: str) -> bool:
    """Mirrors ``site_profile._is_strict_credential_key``."""
    normalized = "".join(character for character in key.lower() if character.isalnum())
    if any(fragment in normalized for fragment in CREDENTIAL_NAME_FRAGMENTS):
        return True
    return normalized in CREDENTIAL_KEY_EXACT_IN_TEXT


def _substantive_tokens(assigned: str) -> list[str]:
    """Mirrors ``site_profile._substantive_tokens``."""
    collapsed = CREDENTIAL_TEMPLATE_EXPRESSION.sub(" <redacted> ", assigned)
    return [
        token
        for token in collapsed.split()
        if token.lower() not in CREDENTIAL_SCHEME_WORDS and not _names_a_secret(token)
    ]


def credential_findings(text: str, *, include_assignments: bool) -> list[str]:
    """Describe every credential-shaped *value* in ``text``, by line.

    ``include_assignments`` turns on the credential-key-plus-entropy family. Pass
    it for data and documentation, not for source: see the note above
    ``CREDENTIAL_VALUE_DATA_SUFFIXES``.
    """
    findings: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for label, pattern in CREDENTIAL_FORMATS:
            if pattern.search(line):
                findings.append(f"line {number}: {label}")
        if not include_assignments:
            continue
        for match in CREDENTIAL_ASSIGNMENT_IN_TEXT.finditer(line):
            key, value = match.group(1), match.group(2)
            if not _is_strict_credential_key(key):
                continue
            tokens = _substantive_tokens(value)
            if len(tokens) != 1:
                # No substantive token is a placeholder, a reference or a bare
                # scheme word. Several of them is a sentence about a credential,
                # and every file this gate reads is prose or source, so the
                # descriptive reading applies throughout.
                continue
            findings.append(
                f"line {number}: {key!r} is assigned a credential-shaped value"
            )
    return findings


def check_secret_free_values(root: Path) -> list[str]:
    """Reject a credential written as a *value* anywhere inside a package.

    The repository's other guards — the site profile loader, its schema, and the
    compatibility matrix redaction check — all inspect field *names*. A password,
    API key, or bearer token pasted into an allowed free-text value such as
    ``notes``, ``description``, or ``ownership`` satisfies every one of them, so
    an operator told that validation excludes credentials can still ship one.

    Scoped to ``plugins/`` on purpose. These are the trees that leave this
    repository and land on an operator's machine, and it is the same scope every
    other package check here uses. Widening it to the whole repository would also
    make ``docs/reviews/`` a failure surface, and those reviewer reports are
    immutable evidence that quote credential-shaped text on purpose.
    """
    errors: list[str] = []
    plugins = root / "plugins"
    if not plugins.is_dir():
        return errors
    for path in sorted(plugins.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Not text, so there is no value to read. A binary blob in a package
            # is check_provenance_manifests' problem, not this check's.
            continue
        relative = path.relative_to(root)
        include = path.suffix.lower() in CREDENTIAL_VALUE_DATA_SUFFIXES
        for finding in credential_findings(text, include_assignments=include):
            errors.append(f"credential value in {relative}, {finding}")
    return errors


def check_repo(root: Path) -> list[str]:
    return [
        *check_required_paths(root),
        *check_markdown_links(root),
        *check_plugin_manifests(root),
        *check_provenance_manifests(root),
        *check_bundled_files(root),
        *check_fleet_bundle_declarations(root),
        *check_fleet_bundle_outputs(root),
        *check_skill_frontmatter(root),
        *check_secret_free_values(root),
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
