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
  transform version. There is exactly one: the Claude manifest, lifted out of
  `.claude-plugin/` into the client extension directory.
* **target-owned portable source** — authored here, with no upstream
  counterpart. It is never overwritten and never removed by synchronization,
  which is what stops this script from silently destroying the portable
  site-profile contract and the discovery and drift work beside it.

Two commands::

    sync_vendor_source.py --source PATH --commit SHA     # write
    sync_vendor_source.py --source PATH --commit SHA --check   # write nothing

Standard library only, and no network access: the source is a local checkout and
every byte is read from the pinned commit through `git show`.
"""

from __future__ import annotations

import argparse
import json
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

TRANSFORM_NAME = "relocate-claude-manifest"
TRANSFORM_VERSION = "1"

GENERATED_BY = "scripts/sync_vendor_source.py"

PROVENANCE_FILENAME = check_repo.PROVENANCE_FILENAME
BYTE_COPY = check_repo.BYTE_COPY
TRANSFORM = check_repo.TRANSFORM
TARGET_OWNED = check_repo.TARGET_OWNED

# Files whose custody is the portable core. Their path inside the portable
# package is their path inside the upstream package, unchanged.
PORTABLE_BYTE_COPIES = (
    "README.md",
    "CHANGELOG.md",
    "skills/unifi-network/SKILL.md",
    "skills/unifi-network/references/udm-api-endpoints.md",
    "skills/unifi-network/scripts/unifi_network_client.py",
    "skills/unifi-protect/SKILL.md",
    "skills/unifi-protect/references/protect-api-endpoints.md",
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


# --- the one transform --------------------------------------------------------


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
    ) -> None:
        self.target_path = target_path
        self.source_path = source_path
        self.classification = classification
        self.source_bytes = source_bytes
        self.output_bytes = output_bytes

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
            entry["source_sha256"] = self.source_digest
            entry["sha256"] = self.output_digest
            entry["transform"] = TRANSFORM_NAME
            entry["transform_version"] = TRANSFORM_VERSION
            entry["transform_rule"] = (
                "Re-emit the Claude Code manifest under the client extension directory "
                "the Agent Plugins 1.0 specification's section 8.2 defines. Version 1 "
                "preserves the bytes and derives only the output path, because the "
                "source directory name .claude-plugin/ is a Claude Code loading "
                "convention with no meaning inside the extension directory, and the "
                "portable Agent Plugins manifest already occupies the package root the "
                "Claude manifest would otherwise claim."
            )
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
        *CLIENT_BYTE_COPIES,
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


def previously_managed(plugin_dir: Path) -> set[str]:
    """Sync-managed paths recorded by an earlier run, read from the manifest on disk."""
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
                managed.add(path_value)
    return managed


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
            "first. Target-owned portable source has no upstream counterpart, records no digest, "
            "and is never overwritten and never removed here.",
            "The client extension directory com.infiquetra.claude/ mirrors the upstream package "
            "root path for path, so every Claude-custody file's origin is readable from its "
            "portable path and every one of them stays a byte copy. The Claude Code manifest is "
            "the single exception and the single transform: it is lifted out of .claude-plugin/, "
            "whose name is a loading convention with no meaning inside the extension directory, "
            "and whose portable counterpart already occupies the package root.",
            "Both fleet_commons_shim.py copies are dropped rather than copied, because the "
            "build-time Fleet Core bundle replaces them and their resolution ladder is "
            "Claude-specific discovery the portable package must not retain. Neither client was "
            "edited to match: both are byte copies, and both still carry the upstream "
            "`import fleet_commons_shim` at module scope, so a portable client cannot be "
            "executed until that import is repaired upstream and re-synchronized here. Editing "
            "it downstream would create exactly the divergence the byte-copy rule forbids.",
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
    """Write every managed path, verify each byte copy, and drop stale managed paths."""
    written: list[str] = []
    for item in planned:
        destination = plugin_dir / item.target_path
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

    managed = {item.target_path for item in planned}
    for stale in sorted(previously_managed(plugin_dir) - managed):
        path = plugin_dir / stale
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
    for stale in sorted(previously_managed(plugin_dir) - {item.target_path for item in planned}):
        if (plugin_dir / stale).is_file():
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
