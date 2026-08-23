#!/usr/bin/env python3
"""Derive the portable UniFi package from a pinned `infiquetra-claude-plugins` revision.

The portable copy is a derived artifact, never a second writable source. This
script reads the bytes of one named commit in a local Claude checkout, writes
them into `plugins/unifi/`, and records a provenance manifest a machine can
check without any network access.

Three classifications, and every path in the derived tree is exactly one of them
(the manifest records which):

* **upstream byte copy** — identical to its source at the pinned commit. It is
  overwritten on every synchronization and its digest must match the source
  exactly. Where the portable tree would need a different byte, the repair is
  authored upstream first; a downstream edit is a defect, not a transform.
* **deterministic transform** — derived from a source file by a versioned,
  repeatable rule, recording the source digest, the output digest, and the
  transform version. There are two rules. `relocate-claude-manifest` lifts the
  Claude manifest out of `.claude-plugin/` into the client extension directory.
  `resolve-bundled-fleet-module` rewrites each client's module-scope import of
  the dropped `fleet_commons_shim` into an import of the build-time Fleet Core
  bundle this package ships, which is what gives the portable package a working
  entrypoint at all.
* **target-owned portable source** — authored here rather than derived from the
  pinned commit. It is never overwritten and never removed by synchronization,
  which is what stops this script from silently destroying the portable
  site-profile contract and the discovery and drift work beside it. Most of it
  has no upstream counterpart at all. A few paths supersede an upstream file of
  the same name, and those are named in `SUPERSEDED_BY_TARGET_OWNED` so the
  custody table still accounts for every upstream path without copying it.

Two commands::

    sync_vendor_source.py --source PATH --commit SHA     # write
    sync_vendor_source.py --source PATH --commit SHA --check   # write nothing

Standard library only, and no network access: the source is a local checkout and
every byte is read from the pinned commit through `git show`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_repo  # noqa: E402


SOURCE_REPOSITORY = "https://github.com/infiquetra/infiquetra-claude-plugins"
SOURCE_PACKAGE_PATH = "plugins/unifi"
TARGET_PACKAGE = "unifi"
SOURCE_MANIFEST_PATH = ".claude-plugin/plugin.json"

#: The client extension directory the Agent Plugins 1.0 specification's section
#: 8.2 defines for one client's own files. Claude-custody files live under it.
CLIENT_EXTENSION_DIR = "com.infiquetra.claude"

MANIFEST_TRANSFORM_NAME = "relocate-claude-manifest"
MANIFEST_TRANSFORM_VERSION = "1"

BUNDLED_TRANSFORM_NAME = "resolve-bundled-fleet-module"
BUNDLED_TRANSFORM_VERSION = "1"

GENERATED_BY = "scripts/sync_vendor_source.py"

PROVENANCE_FILENAME = check_repo.PROVENANCE_FILENAME
BYTE_COPY = check_repo.BYTE_COPY
TRANSFORM = check_repo.TRANSFORM
TARGET_OWNED = check_repo.TARGET_OWNED

# Files whose custody is the portable core. Their path inside the portable
# package is their path inside the upstream package, unchanged.
PORTABLE_BYTE_COPIES = (
    "CHANGELOG.md",
    "skills/unifi-network/SKILL.md",
    "skills/unifi-network/references/udm-api-endpoints.md",
    "skills/unifi-protect/SKILL.md",
    "skills/unifi-protect/references/protect-api-endpoints.md",
)

# Upstream paths this package supersedes with target-owned portable source of
# its own. Declared here so `classify_source_tree` still accounts for every
# upstream path, and read nowhere else: no byte is copied, no byte is written,
# and `target_owned_paths` records the file authored here as `target-owned` on
# every run without being taught its name.
#
# `README.md` is the one such path. The portable README documents *this*
# package -- the Agent Plugins 1.0 layout, the com.infiquetra.claude/ client
# extension directory, the Fleet Core bundle, and commands that run in this
# repository -- and a byte copy of the upstream README told a consumer of the
# portable package it was reading about a Claude Code plugin. The custody is
# recorded in docs/engineering-journal/DECISIONS.md, "The portable UniFi README
# is target-owned, rewritten site-neutral"; listing it as an upstream byte copy
# here is what made this script contradict that decision and made the next
# `synchronize()` restore the Claude lede over the portable file.
SUPERSEDED_BY_TARGET_OWNED = ("README.md",)

# The two executable entrypoints. They keep their upstream-relative path, but
# they are not byte copies: upstream reaches the shared retry primitive through
# `fleet_commons_shim`, which this package deliberately drops, so a byte copy of
# either client cannot be executed at all. The `resolve-bundled-fleet-module`
# transform rewrites that one module-scope import to the build-time Fleet Core
# bundle the package already ships.
PORTABLE_ENTRYPOINT_TRANSFORMS = (
    "skills/unifi-network/scripts/unifi_network_client.py",
    "skills/unifi-protect/scripts/unifi_protect_client.py",
)

# Files whose custody is the Claude adapter. The client extension directory
# mirrors the upstream package root path for path, so a reader can recover the
# origin of every Claude-custody file from its portable path and every one of
# them stays a byte copy. The Claude manifest is the single exception, below.
CLIENT_BYTE_COPIES = (
    "commands/unifi.md",
    "agents/unifi-network-ops.md",
    "skills/unifi-network/scripts/site_profile_loader.py",
)

# Dropped rather than copied. The build-time Fleet Core bundle replaces the
# shim, and its resolution ladder is Claude-specific discovery, which the
# portable package must not retain.
DROPPED_FROM_SOURCE = (
    "skills/unifi-network/scripts/fleet_commons_shim.py",
    "skills/unifi-protect/scripts/fleet_commons_shim.py",
)

# Paths inside the package directory that are neither synchronized nor
# target-owned portable source, and so appear in no `files` entry.
MANIFEST_EXCLUDED_NAMES = (PROVENANCE_FILENAME,)
MANIFEST_EXCLUDED_PARTS = ("__pycache__",)
MANIFEST_EXCLUDED_SUFFIXES = (".pyc", ".pyo")


class SyncError(RuntimeError):
    """Raised when a source checkout, a classification, or an output cannot be trusted."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def package_directory(root: Path | None = None) -> Path:
    return (root or repository_root()) / "plugins" / TARGET_PACKAGE


# --- reading the pinned source ------------------------------------------------


def _git(source: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(source), *arguments],
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise SyncError(f"git {' '.join(arguments)} failed in {source}: {detail}")
    return completed.stdout


def resolve_commit(source: Path, commit: str) -> str:
    """Return the full identifier of `commit`, or fail naming what could not be resolved."""
    if not (source / ".git").exists():
        raise SyncError(f"source is not a git checkout: {source}")
    resolved = _git(source, "rev-parse", "--verify", f"{commit}^{{commit}}")
    return resolved.decode("utf-8").strip()


def require_clean_checkout(source: Path) -> None:
    """Refuse a checkout whose tracked bytes differ from any commit.

    Provenance pinned to a commit that does not describe the bytes on disk is
    worse than no provenance: it asserts a correspondence a later reader cannot
    reproduce. Untracked files are not a reason to refuse, because they cannot
    change what the pin describes.
    """
    status = _git(source, "status", "--porcelain", "--untracked-files=no")
    if status.strip():
        entries = status.decode("utf-8", "replace").strip().splitlines()
        raise SyncError(
            f"refusing to synchronize from a dirty checkout: {source} has "
            f"{len(entries)} tracked modification(s), first: {entries[0].strip()}"
        )


def source_package_files(source: Path, commit: str) -> list[str]:
    """Every file the upstream package holds at `commit`, package-relative."""
    listing = _git(
        source, "ls-tree", "-r", "-z", "--name-only", commit, "--", f"{SOURCE_PACKAGE_PATH}/"
    )
    prefix = f"{SOURCE_PACKAGE_PATH}/"
    names: list[str] = []
    for raw in listing.decode("utf-8").split("\0"):
        if not raw:
            continue
        if not raw.startswith(prefix):
            raise SyncError(f"unexpected path outside {SOURCE_PACKAGE_PATH}: {raw}")
        names.append(raw[len(prefix) :])
    return sorted(names)


def read_source_file(source: Path, commit: str, package_relative: str) -> bytes:
    return _git(source, "show", f"{commit}:{SOURCE_PACKAGE_PATH}/{package_relative}")


# --- the transforms -----------------------------------------------------------


#: The directory name a generated Fleet Core bundle is written into. Read from
#: the validator that owns the name rather than restated here, so the rule that
#: rewrites the client import and the rule that writes the bundle cannot drift
#: apart into a package that imports a path nothing generates. Which directories
#: actually receive a bundle is the consumer's fleet-bundle.json declaration to
#: say; this rule only requires one beside each client, which is where the
#: pilot plan's assembled-package tree puts it.
BUNDLE_DIRECTORY_NAME = check_repo.BUNDLE_DIRECTORY_NAME

#: The upstream module-scope block that reaches the shared retry primitive
#: through the Claude-specific shim. Matched as a whole so a partial or
#: reworded upstream block fails loudly instead of being half-rewritten.
UPSTREAM_SHIM_IMPORT = re.compile(
    r"^sys\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parent\)\)\n"
    r"import fleet_commons_shim\b[^\n]*\n"
    r"\n"
    r"(?P<binding>_[A-Za-z0-9_]*) = fleet_commons_shim\.load\("
    r"\"(?P<module>[A-Za-z_][A-Za-z0-9_]*)\"\)\n",
    re.MULTILINE,
)

BUNDLED_TRANSFORM_RULE = (
    "Rewrite the client's module-scope import of the dropped fleet_commons_shim into an "
    "import of the build-time Fleet Core bundle this package already ships. Version 1 "
    "matches the single upstream block that inserts the client's own directory on sys.path "
    "and calls fleet_commons_shim.load(NAME), and re-emits it as an insertion of the "
    f"{BUNDLE_DIRECTORY_NAME}/ directory beside the client -- the location the pilot plan's "
    "assembled-package tree gives the generated bundle, and the smallest possible change "
    "to the upstream line -- followed by a direct import of NAME under the same binding. "
    "The rule reads the module name and the binding out of the source rather than assuming "
    "them, changes no other byte, and fails loudly when the block is absent or appears more "
    "than once, because a synchronization that silently restored the shim import would ship "
    "a package with no working entrypoint. The consumer's fleet-bundle.json must declare a "
    "destination there; scripts/check_repo.py rejects a declared bundle that is missing and "
    "tests/test_client_entrypoints.py runs the shipped scripts, so the two halves cannot "
    "drift apart unnoticed."
)


class TransformRule:
    """One versioned, repeatable rule and the metadata a manifest entry records."""

    __slots__ = ("name", "version", "rule")

    def __init__(self, name: str, version: str, rule: str) -> None:
        self.name = name
        self.version = version
        self.rule = rule


def bundled_module_transform(payload: bytes, *, target_path: str) -> bytes:
    """Transform `resolve-bundled-fleet-module`, version 1.

    The rule: find the one upstream block that puts the client's own directory
    on `sys.path`, imports `fleet_commons_shim`, and loads a module through it,
    and re-emit it as an insertion of the generated bundle directory beside the
    client, followed by a direct import of that module.

    This is a transform rather than a byte copy because the portable package
    does not carry `fleet_commons_shim` at all: its resolution ladder is
    Claude-specific runtime discovery, and dropping it while copying the import
    verbatim leaves a client that raises `ModuleNotFoundError` before it parses
    a single argument. The bundle is written at build time by
    `scripts/bundle_fleet_module.py`, so the module is on disk when the package
    is installed and Fleet Core is never installed separately.

    The rewritten line stays relative to the client's own file, so it holds
    wherever in the package the client sits and however the package is
    installed. The consumer's `fleet-bundle.json` is what puts a bundle there;
    `scripts/check_repo.py` rejects a declared bundle that was never generated,
    and `tests/test_client_entrypoints.py` runs the shipped scripts, so a
    declaration that stops writing beside a client fails loudly.
    """
    try:
        body = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SyncError(f"{target_path} is not UTF-8: {exc}") from exc

    matches = list(UPSTREAM_SHIM_IMPORT.finditer(body))
    if len(matches) != 1:
        raise SyncError(
            f"{target_path}: expected exactly one fleet_commons_shim import block to rewrite, "
            f"found {len(matches)}; the portable package drops the shim, so a client whose "
            "block this rule cannot find would ship with no working entrypoint"
        )

    match = matches[0]
    replacement = (
        "sys.path.insert(0, str(Path(__file__).resolve().parent / "
        f'"{BUNDLE_DIRECTORY_NAME}"))\n'
        "# The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose\n"
        "# resolution ladder is Claude-specific runtime discovery this package must not\n"
        "# retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on\n"
        "# disk at install time and Fleet Core is never installed separately.\n"
        f"import {match.group('module')} as {match.group('binding')}"
        "  # noqa: E402  (after the sys.path shim, by design)\n"
    )
    rewritten = body[: match.start()] + replacement + body[match.end() :]
    return rewritten.encode("utf-8")


def relocate_claude_manifest(payload: bytes) -> bytes:
    """Transform `relocate-claude-manifest`, version 1.

    The rule: read the Claude Code manifest from `.claude-plugin/plugin.json`
    and re-emit it at `com.infiquetra.claude/plugin.json`, the client extension
    directory. Version 1 preserves the bytes and derives only the output path.

    This is a transform rather than a byte copy because the output path is
    produced by a rule rather than mirrored from the source. Every other
    Claude-custody file keeps its upstream-relative path underneath the
    extension directory; this one is lifted out of a directory whose name,
    `.claude-plugin/`, is a Claude Code loading convention that carries no
    meaning inside the extension directory, and whose portable counterpart --
    the Agent Plugins manifest at the package root -- occupies the location the
    Claude manifest would otherwise claim.

    The rule parses the document before re-emitting it, so a manifest shape it
    does not understand fails loudly here rather than being relocated unread.
    """
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"{SOURCE_MANIFEST_PATH} is not readable JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise SyncError(f"{SOURCE_MANIFEST_PATH} is not a JSON object")
    if not isinstance(document.get("name"), str) or not document["name"].strip():
        raise SyncError(f"{SOURCE_MANIFEST_PATH} has no non-empty name")
    return payload


RELOCATE_MANIFEST_RULE = TransformRule(
    MANIFEST_TRANSFORM_NAME,
    MANIFEST_TRANSFORM_VERSION,
    "Re-emit the Claude Code manifest under the client extension directory "
    "the Agent Plugins 1.0 specification's section 8.2 defines. Version 1 "
    "preserves the bytes and derives only the output path, because the "
    "source directory name .claude-plugin/ is a Claude Code loading "
    "convention with no meaning inside the extension directory, and the "
    "portable Agent Plugins manifest already occupies the package root the "
    "Claude manifest would otherwise claim.",
)

BUNDLED_MODULE_RULE = TransformRule(
    BUNDLED_TRANSFORM_NAME,
    BUNDLED_TRANSFORM_VERSION,
    BUNDLED_TRANSFORM_RULE,
)


# --- planning -----------------------------------------------------------------


class PlannedFile:
    """One path the synchronization owns, with the bytes it must contain."""

    def __init__(
        self,
        target_path: str,
        source_path: str,
        classification: str,
        source_bytes: bytes,
        output_bytes: bytes,
        transform: "TransformRule | None" = None,
    ) -> None:
        self.target_path = target_path
        self.source_path = source_path
        self.classification = classification
        self.source_bytes = source_bytes
        self.output_bytes = output_bytes
        if (classification == TRANSFORM) != (transform is not None):
            raise SyncError(
                f"{target_path}: a deterministic transform records its rule and nothing "
                "else does"
            )
        self.transform = transform

    @property
    def source_digest(self) -> str:
        return check_repo.sha256_bytes(self.source_bytes)

    @property
    def output_digest(self) -> str:
        return check_repo.sha256_bytes(self.output_bytes)

    def manifest_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "path": self.target_path,
            "classification": self.classification,
            "source_path": f"{SOURCE_PACKAGE_PATH}/{self.source_path}",
        }
        if self.classification == TRANSFORM:
            assert self.transform is not None
            entry["source_sha256"] = self.source_digest
            entry["sha256"] = self.output_digest
            entry["transform"] = self.transform.name
            entry["transform_version"] = self.transform.version
            entry["transform_rule"] = self.transform.rule
        else:
            entry["sha256"] = self.output_digest
        return entry


def classify_source_tree(present: list[str]) -> None:
    """Fail unless every upstream path is assigned exactly one custody.

    Nothing is left implicit. A file added upstream that this table does not
    name would otherwise be dropped in silence, which is how a derived tree
    quietly stops being a copy of anything.
    """
    declared = (
        *PORTABLE_BYTE_COPIES,
        *PORTABLE_ENTRYPOINT_TRANSFORMS,
        *CLIENT_BYTE_COPIES,
        *SUPERSEDED_BY_TARGET_OWNED,
        *DROPPED_FROM_SOURCE,
        SOURCE_MANIFEST_PATH,
    )
    assigned = set(declared)
    duplicates = sorted(name for name in assigned if declared.count(name) > 1)
    if duplicates:
        raise SyncError(
            "custody table assigns a path more than one classification: " + ", ".join(duplicates)
        )
    unclassified = sorted(set(present) - assigned)
    if unclassified:
        raise SyncError(
            "upstream paths carry no custody assignment, so synchronization would drop them "
            "in silence: " + ", ".join(f"{SOURCE_PACKAGE_PATH}/{name}" for name in unclassified)
        )
    absent = sorted(assigned - set(present))
    if absent:
        raise SyncError(
            "custody table names paths the pinned commit does not contain: "
            + ", ".join(f"{SOURCE_PACKAGE_PATH}/{name}" for name in absent)
        )


def plan_sync(source: Path, commit: str) -> list[PlannedFile]:
    """Read the pinned commit and produce the file plan, writing nothing."""
    present = source_package_files(source, commit)
    classify_source_tree(present)

    planned: list[PlannedFile] = []
    for relative in PORTABLE_BYTE_COPIES:
        payload = read_source_file(source, commit, relative)
        planned.append(PlannedFile(relative, relative, BYTE_COPY, payload, payload))
    for relative in PORTABLE_ENTRYPOINT_TRANSFORMS:
        payload = read_source_file(source, commit, relative)
        planned.append(
            PlannedFile(
                relative,
                relative,
                TRANSFORM,
                payload,
                bundled_module_transform(payload, target_path=relative),
                BUNDLED_MODULE_RULE,
            )
        )
    for relative in CLIENT_BYTE_COPIES:
        payload = read_source_file(source, commit, relative)
        target = f"{CLIENT_EXTENSION_DIR}/{relative}"
        planned.append(PlannedFile(target, relative, BYTE_COPY, payload, payload))

    manifest_payload = read_source_file(source, commit, SOURCE_MANIFEST_PATH)
    planned.append(
        PlannedFile(
            f"{CLIENT_EXTENSION_DIR}/plugin.json",
            SOURCE_MANIFEST_PATH,
            TRANSFORM,
            manifest_payload,
            relocate_claude_manifest(manifest_payload),
            RELOCATE_MANIFEST_RULE,
        )
    )
    planned.sort(key=lambda item: item.target_path)
    return planned


def source_version(source: Path, commit: str) -> str:
    document = json.loads(read_source_file(source, commit, SOURCE_MANIFEST_PATH).decode("utf-8"))
    version = document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SyncError(f"{SOURCE_MANIFEST_PATH} at {commit} has no non-empty version")
    return version


# --- target-owned discovery ---------------------------------------------------


def _is_manifest_candidate(relative: Path) -> bool:
    if relative.name in MANIFEST_EXCLUDED_NAMES:
        return False
    if any(part in MANIFEST_EXCLUDED_PARTS for part in relative.parts):
        return False
    return relative.suffix not in MANIFEST_EXCLUDED_SUFFIXES


def target_owned_paths(plugin_dir: Path, managed: set[str]) -> list[str]:
    """Every present path the synchronization does not own.

    Discovery is by difference rather than by a second hand-maintained list, so
    a target-owned file added later -- the generated Fleet Core bundle among
    them -- is recorded without this script being edited to know about it.
    """
    if not plugin_dir.is_dir():
        return []
    found: list[str] = []
    for path in sorted(plugin_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(plugin_dir)
        if not _is_manifest_candidate(relative):
            continue
        posix = relative.as_posix()
        if posix in managed:
            continue
        found.append(posix)
    return found


# --- writing ------------------------------------------------------------------


def _managed_path_violation(plugin_dir: Path, path_value: object) -> str | None:
    """Why ``path_value`` may not be written or deleted, or ``None`` if it is safe.

    ``PROVENANCE.json`` is untrusted input the moment a corrupt or hostile
    manifest reaches the tree, and the paths it records are the ones stale
    cleanup unlinks. ``Path`` resolves ``plugin_dir / "/etc/hosts"`` to
    ``/etc/hosts`` and lets ``../../..`` climb out of the package, so an
    unvalidated manifest path turns stale cleanup into arbitrary deletion of any
    user-writable file. Two independent checks, both required:

    * **lexical** — the value has to be a non-blank, package-relative path with
      no ``..`` component. This is the same rule ``check_repo.py`` applies when
      it validates a manifest, restated here rather than imported because that
      helper is private to that module, reports in manifest-entry terms, and
      belongs to a file this repair does not own.
    * **containment** — the resolved path has to stay strictly under the
      resolved package directory. Resolution is what closes the escape a
      lexical check cannot see: a symlink inside the package pointing out of it
      makes ``skills/link/victim`` lexically innocent and still land outside.
    """
    if not isinstance(path_value, str) or not path_value.strip():
        return "a managed path that is not a non-empty string"
    candidate = Path(path_value)
    if candidate.is_absolute() or ".." in candidate.parts:
        return f"an unsafe managed path: {path_value}"
    package = plugin_dir.resolve()
    target = (plugin_dir / candidate).resolve()
    if target == package or not target.is_relative_to(package):
        return f"a managed path that resolves outside the package: {path_value} -> {target}"
    return None


def resolve_managed_path(plugin_dir: Path, path_value: str) -> Path:
    """Return the in-package path ``path_value`` names, or refuse to name one.

    The single chokepoint every write and every deletion goes through. It fails
    closed: an unsafe path raises rather than being skipped, because skipping
    would let a manifest that names one real stale file and one hostile path
    still complete a partial synchronization.
    """
    violation = _managed_path_violation(plugin_dir, path_value)
    if violation is not None:
        raise SyncError(
            f"{PROVENANCE_FILENAME} records {violation}; synchronization writes and deletes "
            "only inside the package, so a manifest that names a path outside it is refused "
            "before anything on disk is touched"
        )
    return plugin_dir / path_value


def previously_managed(plugin_dir: Path) -> set[str]:
    """Sync-managed paths recorded by an earlier run, read from the manifest on disk.

    Every returned path has passed `resolve_managed_path`, so no caller can be
    handed a string that escapes the package. An unreadable or non-conforming
    manifest still yields an empty set — that is a tree with nothing to clean up,
    not an attack — but a manifest that names a path outside the package raises,
    because that is the one shape a caller must never act on.
    """
    manifest = plugin_dir / PROVENANCE_FILENAME
    if not manifest.is_file():
        return set()
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    entries = payload.get("files")
    if not isinstance(entries, list):
        return set()
    managed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("classification") in (BYTE_COPY, TRANSFORM):
            path_value = entry.get("path")
            if isinstance(path_value, str) and path_value.strip():
                resolve_managed_path(plugin_dir, path_value)
                managed.add(path_value)
    return managed


def stale_managed_paths(plugin_dir: Path, managed: set[str]) -> list[str]:
    """Managed paths an earlier run recorded that the current plan no longer produces.

    The single place the stale set is computed, so the write path and the check
    path cannot disagree about what synchronization is allowed to delete.

    `SUPERSEDED_BY_TARGET_OWNED` is subtracted because a superseded path is
    target-owned, and target-owned source is never removed here. A tree
    synchronized before the custody change still carries a manifest recording
    `README.md` as an upstream byte copy; without this subtraction the first run
    after the change would read that entry, find the path absent from the plan,
    and unlink the portable README outright -- a worse outcome than the
    overwrite the change exists to prevent.

    Every returned path has already been through `resolve_managed_path` inside
    `previously_managed`, so a manifest naming a path outside the package still
    raises here rather than reaching a caller.
    """
    return sorted(previously_managed(plugin_dir) - managed - set(SUPERSEDED_BY_TARGET_OWNED))


def build_manifest(
    planned: list[PlannedFile],
    *,
    commit: str,
    version: str,
    plugin_dir: Path,
) -> dict[str, Any]:
    managed = {item.target_path for item in planned}
    files = [item.manifest_entry() for item in planned]
    files.extend(
        {"path": path, "classification": TARGET_OWNED}
        for path in target_owned_paths(plugin_dir, managed)
    )
    return {
        "source_repository": SOURCE_REPOSITORY,
        "source_commit": commit,
        "source_version": version,
        "source_package_path": SOURCE_PACKAGE_PATH,
        "generated_by": GENERATED_BY,
        "notes": [
            "The portable copy is a derived artifact, never a second writable source. The "
            "pinned commit is the corrected upstream revision: the documentation repair, the "
            "topology relocation, and the removal of the hard-coded controller default are all "
            "included at it. Synchronizing from an earlier revision would re-import the defects "
            "that repair removed.",
            "Paths in `files` are relative to this package root, which is what the repository "
            "validator resolves. `source_path` is relative to the upstream repository root.",
            "Every path carries exactly one classification. An upstream byte copy is overwritten "
            "on each synchronization and its digest must equal its source digest exactly; where "
            "the portable tree would need a different byte, the repair is authored upstream "
            "first. Target-owned portable source is authored in this repository rather than "
            "derived from the pinned commit; it records no digest and is never overwritten and "
            "never removed here. Most target-owned paths have no upstream counterpart at all. "
            "README.md is the one that supersedes an upstream path of the same name: it "
            "documents this portable package rather than the Claude plugin, so the upstream "
            "bytes at that path are deliberately never read and never written, which the "
            "custody table in scripts/sync_vendor_source.py records as a superseded path rather "
            "than leaving it unclassified.",
            "The client extension directory com.infiquetra.claude/ mirrors the upstream package "
            "root path for path, so every Claude-custody file's origin is readable from its "
            "portable path and every one of them stays a byte copy. The Claude Code manifest is "
            "the single exception inside that directory: it is lifted out of .claude-plugin/, "
            "whose name is a loading convention with no meaning inside the extension directory, "
            "and whose portable counterpart already occupies the package root.",
            "Both fleet_commons_shim.py copies are dropped rather than copied, because the "
            "build-time Fleet Core bundle replaces them and their resolution ladder is "
            "Claude-specific discovery the portable package must not retain. Dropping the shim "
            "while copying the clients verbatim is what left this package with no working "
            "entrypoint: both clients import fleet_commons_shim at module scope, so `--help` "
            "raised ModuleNotFoundError before any argument was parsed. The two clients are "
            "therefore deterministic transforms rather than byte copies. The "
            "resolve-bundled-fleet-module rule rewrites that one import to the generated "
            "bundle in the " + BUNDLE_DIRECTORY_NAME + "/ directory beside each client, "
            "records the source digest, the output digest, and the transform version here, "
            "and is re-applied on every "
            "synchronization, so a later run cannot silently restore the broken import. This "
            "is not a downstream edit smuggled past the byte-copy rule: it is a versioned rule "
            "over the pinned source, reproducible from the source bytes alone.",
        ],
        "removed_from_source": [
            {
                "source_path": f"{SOURCE_PACKAGE_PATH}/{relative}",
                "reason": (
                    "Replaced by the build-time Fleet Core bundle; its resolution ladder is "
                    "Claude-specific runtime discovery, which the portable package must not "
                    "retain."
                ),
            }
            for relative in DROPPED_FROM_SOURCE
        ],
        "files": files,
    }


def manifest_text(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def apply_plan(planned: list[PlannedFile], plugin_dir: Path) -> list[str]:
    """Write every managed path, verify each byte copy, and drop stale managed paths.

    The stale set is read and validated first, before a single byte is written:
    a manifest naming a path outside the package aborts the whole run rather
    than leaving a half-synchronized tree behind.
    """
    managed = {item.target_path for item in planned}
    stale_paths = stale_managed_paths(plugin_dir, managed)
    written: list[str] = []
    for item in planned:
        destination = resolve_managed_path(plugin_dir, item.target_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.is_file() or destination.read_bytes() != item.output_bytes:
            destination.write_bytes(item.output_bytes)
            written.append(item.target_path)
        if item.classification == BYTE_COPY:
            actual = check_repo.sha256_path(destination)
            if actual != item.source_digest:
                raise SyncError(
                    f"byte copy diverged from its source: {item.target_path} "
                    f"(source {item.source_digest}, output {actual}); a byte copy is never "
                    "recorded as a transform, so the repair belongs upstream"
                )

    for stale in stale_paths:
        path = resolve_managed_path(plugin_dir, stale)
        if path.is_file():
            path.unlink()
            written.append(stale)
    return written


def verify_plan(planned: list[PlannedFile], plugin_dir: Path) -> list[str]:
    """Report every difference between the plan and the tree, writing nothing."""
    errors: list[str] = []
    for item in planned:
        destination = plugin_dir / item.target_path
        if not destination.is_file():
            errors.append(f"missing synchronized file: {item.target_path}")
            continue
        actual = check_repo.sha256_path(destination)
        if item.classification == BYTE_COPY and actual != item.source_digest:
            errors.append(
                f"byte copy diverged from its source: {item.target_path} "
                f"(source {item.source_digest}, content {actual}); a byte copy is never "
                "recorded as a transform, so the repair belongs upstream"
            )
        elif actual != item.output_digest:
            errors.append(
                f"synchronized file does not match its planned output: {item.target_path} "
                f"(planned {item.output_digest}, content {actual})"
            )
    for stale in stale_managed_paths(plugin_dir, {item.target_path for item in planned}):
        if resolve_managed_path(plugin_dir, stale).is_file():
            errors.append(f"stale synchronized file no longer in the plan: {stale}")
    return errors


def synchronize(
    source: Path,
    commit: str,
    *,
    root: Path | None = None,
    check_only: bool = False,
) -> tuple[list[str], str]:
    """Synchronize (or verify) the portable package. Returns (messages, resolved commit)."""
    source = Path(source).resolve()
    resolved = resolve_commit(source, commit)
    require_clean_checkout(source)
    planned = plan_sync(source, resolved)
    plugin_dir = package_directory(root)
    version = source_version(source, resolved)

    if check_only:
        errors = verify_plan(planned, plugin_dir)
        manifest = plugin_dir / PROVENANCE_FILENAME
        expected = manifest_text(build_manifest(planned, commit=resolved, version=version,
                                                plugin_dir=plugin_dir))
        if not manifest.is_file():
            errors.append(f"missing provenance manifest: {PROVENANCE_FILENAME}")
        elif manifest.read_text(encoding="utf-8") != expected:
            errors.append(
                f"provenance manifest does not match the pinned commit: {PROVENANCE_FILENAME}"
            )
        return errors, resolved

    written = apply_plan(planned, plugin_dir)
    manifest = build_manifest(planned, commit=resolved, version=version, plugin_dir=plugin_dir)
    manifest_path = plugin_dir / PROVENANCE_FILENAME
    text = manifest_text(manifest)
    if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != text:
        manifest_path.write_text(text, encoding="utf-8")
        written.append(PROVENANCE_FILENAME)
    return sorted(written), resolved


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Derive the portable UniFi package from a pinned infiquetra-claude-plugins revision."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        help="path to a local infiquetra-claude-plugins checkout",
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="the upstream commit to pin; the corrected revision, never an earlier one",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the tree against the pinned commit and write nothing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    try:
        messages, resolved = synchronize(
            Path(arguments.source), arguments.commit, check_only=arguments.check
        )
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if arguments.check:
        if messages:
            for message in messages:
                print(f"ERROR: {message}", file=sys.stderr)
            return 1
        print(f"Portable {TARGET_PACKAGE} package matches {SOURCE_REPOSITORY} at {resolved}.")
        return 0

    if messages:
        for message in messages:
            print(f"wrote {message}")
    else:
        print("No change: the portable package already matches the pinned commit.")
    print(f"Synchronized plugins/{TARGET_PACKAGE} from {SOURCE_REPOSITORY} at {resolved}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
