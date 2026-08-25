#!/usr/bin/env python3
"""Derive a portable package from a pinned revision of its upstream repository.

The portable copy is a derived artifact, never a second writable source. This
script reads the bytes of one named commit in a local upstream checkout, writes
them into the package's own tree, and records a provenance manifest a machine
can check without any network access.

Which package, which upstream path, and which custody each path carries are all
read from that package's port descriptor under `ports/` -- see
`scripts/port_config.py`. Nothing about a particular package is compiled into
this file, so porting a second plugin is a new descriptor rather than an edit
here.

Three classifications, and every path in the derived tree is exactly one of them
(the manifest records which):

* **upstream byte copy** — identical to its source at the pinned commit. It is
  overwritten on every synchronization and its digest must match the source
  exactly. Where the portable tree would need a different byte, the repair is
  authored upstream first; a downstream edit is a defect, not a transform.
* **deterministic transform** — derived from a source file by a versioned,
  repeatable rule, recording the source digest, the output digest, and the
  transform version. Which rule rewrites a path is stated per entry in the
  descriptor's `custody.entrypoint_transforms` table (schema version 3); the
  upstream client manifest always relocates under `relocate-claude-manifest`.
  The rules this tool implements are its `TRANSFORM_RULES` registry, and a
  descriptor naming one it does not implement is refused rather than matched
  by default. `relocate-claude-manifest` lifts the Claude manifest out of
  `.claude-plugin/` into the client extension directory. The
  `resolve-bundled-fleet-module` family rewrites a client's import of the
  dropped `fleet_commons_shim` into an import of the build-time Fleet Core
  bundle this package ships, which is what gives the portable package a working
  entrypoint at all: version 1 matches the single contiguous three-line block;
  `resolve-bundled-fleet-module-split` matches a module-scope import block
  whose load call sits elsewhere in the file; and
  `resolve-bundled-fleet-module-guarded` matches a function-scope, if-guarded
  block that returns the loaded module. `normalize-skill-frontmatter` folds a
  `when_to_use` frontmatter key under the permitted `metadata` key,
  deterministically and idempotently, so a skill the open Agent Skills
  specification does not permit upstream still passes the repository gate here.
* **target-owned portable source** — authored here rather than derived from the
  pinned commit. It is never overwritten and never removed by synchronization,
  which is what stops this script from silently destroying the portable
  site-profile contract and the discovery and drift work beside it. Most of it
  has no upstream counterpart at all. A few paths supersede an upstream file of
  the same name, and those are named in the descriptor's
  `superseded_by_target_owned` list so the custody table still accounts for
  every upstream path without copying it.

Two commands::

    sync_vendor_source.py --package NAME --source PATH --commit SHA
    sync_vendor_source.py --package NAME --source PATH --commit SHA --check

`--package` is required rather than defaulted. A tool that overwrites one tree
and deletes stale paths inside it should say which tree out loud, and a default
would make the first package the silent one.

Standard library only, and no network access: the source is a local checkout and
every byte is read from the pinned commit through `git show`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_repo  # noqa: E402
import port_config  # noqa: E402
from port_config import PortConfig, PortConfigError  # noqa: E402


MANIFEST_TRANSFORM_NAME = "relocate-claude-manifest"
MANIFEST_TRANSFORM_VERSION = "1"

BUNDLED_TRANSFORM_NAME = "resolve-bundled-fleet-module"
BUNDLED_TRANSFORM_VERSION = "1"

SPLIT_BUNDLED_TRANSFORM_NAME = "resolve-bundled-fleet-module-split"
SPLIT_BUNDLED_TRANSFORM_VERSION = "1"

GUARDED_BUNDLED_TRANSFORM_NAME = "resolve-bundled-fleet-module-guarded"
GUARDED_BUNDLED_TRANSFORM_VERSION = "1"

FRONTMATTER_TRANSFORM_NAME = "normalize-skill-frontmatter"
FRONTMATTER_TRANSFORM_VERSION = "1"

GENERATED_BY = "scripts/sync_vendor_source.py"

PROVENANCE_FILENAME = check_repo.PROVENANCE_FILENAME
BYTE_COPY = check_repo.BYTE_COPY
TRANSFORM = check_repo.TRANSFORM
TARGET_OWNED = check_repo.TARGET_OWNED

# The custody table itself is data, in `ports/<package>.json`, under `custody`:
#
# * `byte_copies` -- files whose custody is the portable core. Their path inside
#   the portable package is their path inside the upstream package, unchanged.
# * `entrypoint_transforms` -- files that keep their upstream-relative path but
#   are not byte copies, because upstream reaches a shared primitive through a
#   client-specific shim the portable package drops, or carries a frontmatter
#   key the open Agent Skills specification does not permit. Since descriptor
#   schema version 3 every entry names the transform rule that rewrites its
#   path; `plan_sync` looks the name up in `TRANSFORM_RULES` and refuses one it
#   does not implement, so rule selection is the descriptor's data rather than
#   a constant in this file.
# * `client_byte_copies` -- files whose custody is the client adapter. The
#   client extension directory mirrors the upstream package root path for path,
#   so a reader can recover the origin of every adapter file from its portable
#   path and every one of them stays a byte copy. The client manifest is the
#   single exception, relocated by a transform.
# * `superseded_by_target_owned` -- upstream paths the package supersedes with
#   target-owned portable source of its own. Declared so `classify_source_tree`
#   still accounts for every upstream path, and read nowhere else: no byte is
#   copied, no byte is written, and `target_owned_paths` records the file
#   authored here as `target-owned` on every run without being taught its name.
#
#   UniFi's `README.md` is the worked example. The portable README documents
#   *that* package -- the Agent Plugins 1.0 layout, the client extension
#   directory, the Fleet Core bundle, and commands that run in this repository
#   -- and a byte copy of the upstream README told a consumer of the portable
#   package it was reading about a Claude Code plugin. The custody is recorded
#   in docs/engineering-journal/DECISIONS.md, "The portable UniFi README is
#   target-owned, rewritten site-neutral"; listing it as an upstream byte copy
#   is what made this script contradict that decision and made the next
#   `synchronize()` restore the Claude lede over the portable file.
# * `dropped_from_source` -- dropped rather than copied, each with the
#   descriptor's `provenance.dropped_reason` recorded in the manifest.

# Paths inside the package directory that are neither synchronized nor
# target-owned portable source, and so appear in no `files` entry.
MANIFEST_EXCLUDED_NAMES = (PROVENANCE_FILENAME,)
MANIFEST_EXCLUDED_PARTS = ("__pycache__",)
MANIFEST_EXCLUDED_SUFFIXES = (".pyc", ".pyo")


class SyncError(RuntimeError):
    """Raised when a source checkout, a classification, or an output cannot be trusted."""


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_config(package: str, root: Path | None = None) -> PortConfig:
    """The port descriptor for `package`, validated.

    Re-exported here so a caller that already imports this module does not have
    to reach for a second one, and so the error a bad `--package` produces is
    raised in this module's own terms.
    """
    try:
        return port_config.load(package, root or repository_root())
    except PortConfigError as error:
        raise SyncError(str(error)) from error


def package_directory(config: PortConfig, root: Path | None = None) -> Path:
    """The package tree this synchronization owns.

    `root` overrides the descriptor's own repository root, which is what lets a
    test synchronize into a scratch tree while reading the real descriptor.
    """
    return (root or config.root) / config.package_root


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


def source_package_files(config: PortConfig, source: Path, commit: str) -> list[str]:
    """Every file the upstream package holds at `commit`, package-relative."""
    package_path = config.source.package_path
    listing = _git(source, "ls-tree", "-r", "-z", "--name-only", commit, "--", f"{package_path}/")
    prefix = f"{package_path}/"
    names: list[str] = []
    for raw in listing.decode("utf-8").split("\0"):
        if not raw:
            continue
        if not raw.startswith(prefix):
            raise SyncError(f"unexpected path outside {package_path}: {raw}")
        names.append(raw[len(prefix) :])
    return sorted(names)


def read_source_file(config: PortConfig, source: Path, commit: str, package_relative: str) -> bytes:
    return _git(source, "show", f"{commit}:{config.source.package_path}/{package_relative}")


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
    """One versioned, repeatable rule and the metadata a manifest entry records.

    `apply` rewrites one source payload and names the file in its errors; it is
    part of the rule's identity so `TRANSFORM_RULES` can dispatch a descriptor's
    per-path selection without a second table mapping names onto functions.
    """

    __slots__ = ("name", "version", "rule", "apply")

    def __init__(
        self,
        name: str,
        version: str,
        rule: str,
        apply: Callable[[bytes, str], bytes],
    ) -> None:
        self.name = name
        self.version = version
        self.rule = rule
        self.apply = apply


def _decode_utf8(payload: bytes, path: str) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SyncError(f"{path} is not UTF-8: {exc}") from exc


def bundled_module_transform(payload: bytes, target_path: str) -> bytes:
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
    body = _decode_utf8(payload, target_path)

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


def relocate_claude_manifest(payload: bytes, source_path: str) -> bytes:
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
        raise SyncError(f"{source_path} is not readable JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise SyncError(f"{source_path} is not a JSON object")
    if not isinstance(document.get("name"), str) or not document["name"].strip():
        raise SyncError(f"{source_path} has no non-empty name")
    return payload


#: The comment the `resolve-bundled-fleet-module` family writes where the shim
#: import stood. Version 1 of the family carries the same prose inline in its
#: frozen replacement text; the newer rules render it from here so one family
#: explains the bundle the same way in every shape it rewrites.
BUNDLE_REPLACEMENT_COMMENT = (
    "The build-time Fleet Core bundle replaces the upstream fleet_commons_shim, whose",
    "resolution ladder is Claude-specific runtime discovery this package must not",
    "retain. scripts/bundle_fleet_module.py writes the bundle, so the module is on",
    "disk at install time and Fleet Core is never installed separately.",
)


def _bundle_comment(prefix: str) -> str:
    return "".join(f"{prefix}# {line}\n" for line in BUNDLE_REPLACEMENT_COMMENT)


#: The module-scope split shape: an insert of the script's own directory plus a
#: shim import at module scope, separated by a blank line, with the
#: `fleet_commons_shim.load(NAME)` call somewhere else in the file. Matched in
#: two parts because the shape is split; each part must match exactly once, and
#: a file the pair does not describe fails loudly instead of being half-
#: rewritten. The contiguous three-line shape of `resolve-bundled-fleet-module`
#: v1 cannot match here: that rule's import follows the insert with no blank
#: line between them, and this part requires one.
SPLIT_IMPORT_BLOCK = re.compile(
    r"^sys\.path\.insert\(0, str\(Path\(__file__\)\.resolve\(\)\.parent\)\)\n"
    r"\n"
    r"import fleet_commons_shim(?P<import_tail>[^\n]*)\n",
    re.MULTILINE,
)

SPLIT_LOAD_CALL = re.compile(
    r"^(?P<indent>[ ]*)(?P<binding>[A-Za-z_][A-Za-z0-9_]*) = "
    r"fleet_commons_shim\.load\(\"(?P<module>[A-Za-z_][A-Za-z0-9_]*)\"\)$",
    re.MULTILINE,
)

SPLIT_BUNDLED_TRANSFORM_RULE = (
    "Rewrite the split module-scope shape of the dropped fleet_commons_shim import. Version 1 "
    "matches two sites that must each appear exactly once: a module-scope block inserting the "
    "script's own directory on sys.path, a blank line, and `import fleet_commons_shim`, and the "
    f"separate `BINDING = fleet_commons_shim.load(NAME)` call. It re-emits the block as an "
    f"insertion of the {BUNDLE_DIRECTORY_NAME}/ directory beside the client plus a direct "
    "`import NAME` keeping the source's own trailing comment, and re-emits the call as "
    "`BINDING = NAME`, rebinding the module the new import bound. The shape is matched whole: "
    "either site absent or appearing twice fails the synchronization, because a half-rewritten "
    "client would still import the dropped shim or bind nothing. The module scope pays the "
    "import at import time where upstream paid it at call time; the consumer's fleet-bundle.json "
    "puts the bundle beside the client exactly as for the family's version 1."
)


def split_module_transform(payload: bytes, target_path: str) -> bytes:
    """Transform `resolve-bundled-fleet-module-split`, version 1.

    The rule: find the one module-scope `sys.path` insert + blank line +
    `import fleet_commons_shim` block and the one far-away
    `fleet_commons_shim.load(NAME)` call, and re-emit the block as an insertion
    of the generated bundle directory plus a direct import of NAME, and the
    call as a rebinding of the imported module.

    Mission-control's `executor_profile_lint.py` carries this shape at the
    porting pin: the import at module scope, the `.load("tier_palette")` inside
    the lint function. Neither half matches `resolve-bundled-fleet-module` v1's
    contiguous three-line block, which is why the family grew a named rule for
    this shape instead of loosening the frozen one.
    """
    body = _decode_utf8(payload, target_path)

    blocks = list(SPLIT_IMPORT_BLOCK.finditer(body))
    if len(blocks) != 1:
        raise SyncError(
            f"{target_path}: rule {SPLIT_BUNDLED_TRANSFORM_NAME} expected exactly one "
            f"module-scope fleet_commons_shim import block (sys.path insert, blank line, "
            f"import), found {len(blocks)}; a shape this rule cannot match exactly once is "
            "a synchronization stop, never a first match"
        )
    calls = list(SPLIT_LOAD_CALL.finditer(body))
    if len(calls) != 1:
        raise SyncError(
            f"{target_path}: rule {SPLIT_BUNDLED_TRANSFORM_NAME} expected exactly one "
            f"fleet_commons_shim.load(NAME) call site, found {len(calls)}; a shape this rule "
            "cannot match exactly once is a synchronization stop, never a first match"
        )
    block, call = blocks[0], calls[0]
    if not block.end() <= call.start():
        raise SyncError(
            f"{target_path}: rule {SPLIT_BUNDLED_TRANSFORM_NAME} matched its call site before "
            "its import block; the split shape puts the module-scope block first, so this file "
            "carries a shape the rule does not describe"
        )
    module = call.group("module")
    replacement_block = (
        "sys.path.insert(0, str(Path(__file__).resolve().parent / "
        f'"{BUNDLE_DIRECTORY_NAME}"))\n'
        + _bundle_comment(prefix="")
        + f"import {module}{block.group('import_tail')}\n"
    )
    replacement_call = f"{call.group('indent')}{call.group('binding')} = {module}"
    rewritten = (
        body[: block.start()]
        + replacement_block
        + body[block.end() : call.start()]
        + replacement_call
        + body[call.end() :]
    )
    return rewritten.encode("utf-8")


#: The function-scope guarded-contiguous shape: a binding of the script's own
#: directory, an `if BINDING not in sys.path:` guard around the insert, the
#: shim import, a blank line, and a `return` of the loaded module -- one
#: contiguous block inside a function. The indent is captured and re-emitted so
#: the rule holds wherever the function sits, and the binding name is
#: back-referenced so the three lines must agree on it.
GUARDED_CONTIGUOUS_BLOCK = re.compile(
    r"^(?P<indent>[ ]*)(?P<dir_binding>[A-Za-z_][A-Za-z0-9_]*) = "
    r"str\(Path\(__file__\)\.resolve\(\)\.parent\)\n"
    r"(?P=indent)if (?P=dir_binding) not in sys\.path:\n"
    r"(?P=indent)    sys\.path\.insert\(0, (?P=dir_binding)\)\n"
    r"(?P=indent)import fleet_commons_shim(?P<import_tail>[^\n]*)\n"
    r"\n"
    r"(?P=indent)return fleet_commons_shim\.load\(\"(?P<module>[A-Za-z_][A-Za-z0-9_]*)\"\)$",
    re.MULTILINE,
)

GUARDED_BUNDLED_TRANSFORM_RULE = (
    "Rewrite the function-scope guarded shape of the dropped fleet_commons_shim import. Version "
    "1 matches exactly one contiguous block: a binding of the script's own directory, an `if "
    "BINDING not in sys.path:` guard around the insert, `import fleet_commons_shim`, a blank "
    "line, and `return fleet_commons_shim.load(NAME)`. It re-emits the binding's value as the "
    f"{BUNDLE_DIRECTORY_NAME}/ directory beside the client -- keeping the binding name, which a "
    "deterministic rule cannot know is unused beyond the block -- and the import and return as "
    "the direct module, preserving the source's own trailing comment and the lazy, call-time "
    "import the upstream function documents. The block absent or repeated fails the "
    "synchronization, because a half-rewritten loader would still import the dropped shim."
)


def guarded_module_transform(payload: bytes, target_path: str) -> bytes:
    """Transform `resolve-bundled-fleet-module-guarded`, version 1.

    The rule: find the one function-scope, if-guarded contiguous block that
    inserts the script's directory, imports `fleet_commons_shim`, and returns
    the module it loads, and re-emit it so the guarded insert points at the
    generated bundle directory and the function imports and returns the module
    directly.

    Mission-control's `sdlc_manager.py` carries this shape at the porting pin
    inside `_load_intent_envelope`: the lazy loader stays lazy -- the import
    still happens at call time -- but resolves the build-time bundle instead of
    the dropped shim. The binding keeps its upstream name; only its value
    moves, which is the smallest change that cannot break a use of the binding
    the block does not see.
    """
    body = _decode_utf8(payload, target_path)

    matches = list(GUARDED_CONTIGUOUS_BLOCK.finditer(body))
    if len(matches) != 1:
        raise SyncError(
            f"{target_path}: rule {GUARDED_BUNDLED_TRANSFORM_NAME} expected exactly one "
            f"if-guarded fleet_commons_shim block (binding, guard, insert, import, return "
            f"load), found {len(matches)}; a shape this rule cannot match exactly once is a "
            "synchronization stop, never a first match"
        )
    match = matches[0]
    indent = match.group("indent")
    dir_binding = match.group("dir_binding")
    module = match.group("module")
    replacement = (
        f"{indent}{dir_binding} = str(Path(__file__).resolve().parent / "
        f'"{BUNDLE_DIRECTORY_NAME}")\n'
        f"{indent}if {dir_binding} not in sys.path:\n"
        f"{indent}    sys.path.insert(0, {dir_binding})\n"
        + _bundle_comment(prefix=indent)
        + f"{indent}import {module}{match.group('import_tail')}\n"
        "\n"
        f"{indent}return {module}"
    )
    rewritten = body[: match.start()] + replacement + body[match.end() :]
    return rewritten.encode("utf-8")


#: The open Agent Skills key `when_to_use` is folded under. Permitted by the
#: specification, read by `check_repo.SKILL_FRONTMATTER_FIELDS`; a skill that
#: carries it at top level fails the repository gate, so the portable copy
#: moves it rather than dropping it and upstream keeps it, because Claude Code
#: skill listings read it.
FRONTMATTER_WHEN_TO_USE_KEY = "when_to_use"
FRONTMATTER_METADATA_KEY = "metadata"
FRONTMATTER_DELIMITER_LINE = "---"

#: A top-level frontmatter key line: column zero, the key shape
#: `check_repo.FRONTMATTER_KEY` defines, never an indented continuation.
FRONTMATTER_TOP_LEVEL_KEY = re.compile(r"^(?P<key>[A-Za-z0-9][A-Za-z0-9_.-]*):")

FRONTMATTER_TRANSFORM_RULE = (
    "Fold a top-level when_to_use frontmatter key under the permitted metadata key. Version 1 "
    "reads the YAML frontmatter block line by line -- the repository tooling is standard "
    "library only and ships no YAML parser -- and moves the key line and every line of its "
    "value, block scalar or inline, two columns in, emitting `metadata:` above it where the "
    "key stood. The fold is deterministic and idempotent: a frontmatter without a top-level "
    "when_to_use comes back byte-identical, which is what a second application returns, and "
    "the body below the frontmatter is never touched. A frontmatter that carries a top-level "
    "metadata key beside when_to_use is refused rather than merged, because folding under an "
    "existing mapping is a shape this version does not describe; an unterminated frontmatter "
    "or a second when_to_use key is refused for the same reason. Portable copies only: the "
    "upstream file keeps the key because it is functional in Claude Code skill listings."
)


def normalize_skill_frontmatter(payload: bytes, target_path: str) -> bytes:
    """Transform `normalize-skill-frontmatter`, version 1.

    The rule: move the one top-level `when_to_use` key of a skill's frontmatter
    under a `metadata` key emitted where the key stood, re-indenting its value
    block beneath it. A file with no top-level `when_to_use` is returned
    unchanged, which makes the transform idempotent: applied to its own output
    it is a no-op.

    All seven mission-control `SKILL.md` files carry the key at the porting
    pin, and `when_to_use` is not one of the six fields the open Agent Skills
    specification permits, so a byte copy of any of them would fail
    `check_skill_frontmatter` on the assembled branch. The fold preserves the
    key's content -- the `metadata` mapping is a permitted field -- instead of
    deleting it.
    """
    body = _decode_utf8(payload, target_path)
    lines = body.split("\n")
    if not lines or lines[0].strip() != FRONTMATTER_DELIMITER_LINE:
        raise SyncError(
            f"{target_path}: rule {FRONTMATTER_TRANSFORM_NAME} expected a YAML frontmatter "
            "block opening with --- on the first line"
        )
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_DELIMITER_LINE:
            closing = index
            break
    if closing is None:
        raise SyncError(
            f"{target_path}: rule {FRONTMATTER_TRANSFORM_NAME} found no closing --- for the "
            "frontmatter block"
        )

    key_indices = [
        index
        for index in range(1, closing)
        if FRONTMATTER_TOP_LEVEL_KEY.match(lines[index])
        and FRONTMATTER_TOP_LEVEL_KEY.match(lines[index]).group("key")
        == FRONTMATTER_WHEN_TO_USE_KEY
    ]
    if not key_indices:
        # Nothing to fold: a second application lands here too, which is the
        # idempotence guarantee stated by the rule.
        return payload
    if len(key_indices) != 1:
        raise SyncError(
            f"{target_path}: rule {FRONTMATTER_TRANSFORM_NAME} expected exactly one top-level "
            f"{FRONTMATTER_WHEN_TO_USE_KEY} key, found {len(key_indices)}"
        )
    metadata_indices = [
        index
        for index in range(1, closing)
        if FRONTMATTER_TOP_LEVEL_KEY.match(lines[index])
        and FRONTMATTER_TOP_LEVEL_KEY.match(lines[index]).group("key")
        == FRONTMATTER_METADATA_KEY
    ]
    if metadata_indices:
        raise SyncError(
            f"{target_path}: rule {FRONTMATTER_TRANSFORM_NAME} refuses a frontmatter that "
            f"carries a top-level {FRONTMATTER_METADATA_KEY} key beside "
            f"{FRONTMATTER_WHEN_TO_USE_KEY}; folding under an existing mapping is a shape "
            "this version does not describe"
        )

    key_index = key_indices[0]
    value_end = key_index + 1
    while value_end < closing and (
        not lines[value_end].strip() or lines[value_end][0] in " \t"
    ):
        value_end += 1

    folded = [f"{FRONTMATTER_METADATA_KEY}:"]
    folded.append(f"  {lines[key_index]}")
    for line in lines[key_index + 1 : value_end]:
        folded.append(f"  {line}" if line.strip() else line)
    rewritten_lines = lines[:key_index] + folded + lines[value_end:]
    return "\n".join(rewritten_lines).encode("utf-8")


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
    relocate_claude_manifest,
)

BUNDLED_MODULE_RULE = TransformRule(
    BUNDLED_TRANSFORM_NAME,
    BUNDLED_TRANSFORM_VERSION,
    BUNDLED_TRANSFORM_RULE,
    bundled_module_transform,
)

SPLIT_BUNDLED_MODULE_RULE = TransformRule(
    SPLIT_BUNDLED_TRANSFORM_NAME,
    SPLIT_BUNDLED_TRANSFORM_VERSION,
    SPLIT_BUNDLED_TRANSFORM_RULE,
    split_module_transform,
)

GUARDED_BUNDLED_MODULE_RULE = TransformRule(
    GUARDED_BUNDLED_TRANSFORM_NAME,
    GUARDED_BUNDLED_TRANSFORM_VERSION,
    GUARDED_BUNDLED_TRANSFORM_RULE,
    guarded_module_transform,
)

FRONTMATTER_RULE = TransformRule(
    FRONTMATTER_TRANSFORM_NAME,
    FRONTMATTER_TRANSFORM_VERSION,
    FRONTMATTER_TRANSFORM_RULE,
    normalize_skill_frontmatter,
)


def _build_rule_registry(*rules: TransformRule) -> dict[str, TransformRule]:
    """Every rule this tool implements, by name.

    The descriptor's per-path selection resolves against this table, so a name
    registered twice is a bug that must fail at import, and a descriptor entry
    naming an absent one is refused by `plan_sync` rather than matched by some
    default rule.
    """
    registry: dict[str, TransformRule] = {}
    for rule in rules:
        if rule.name in registry:
            raise ValueError(f"transform rule name registered twice: {rule.name}")
        registry[rule.name] = rule
    return registry


TRANSFORM_RULES = _build_rule_registry(
    RELOCATE_MANIFEST_RULE,
    BUNDLED_MODULE_RULE,
    SPLIT_BUNDLED_MODULE_RULE,
    GUARDED_BUNDLED_MODULE_RULE,
    FRONTMATTER_RULE,
)


def resolve_transform_rule(config: PortConfig, relative: str) -> TransformRule:
    """The rule the descriptor names for `relative`, or a refusal.

    Schema version 3 states the selection per entrypoint-transform path. The
    state is validated as a name only -- which names exist is this module's
    registry to say, so an entry naming a rule this tool does not implement
    fails here at plan time rather than being matched by some default rewrite,
    and a path with no rule named has nothing to apply.
    """
    rule_name = config.custody.entrypoint_rules.get(relative)
    if rule_name is None:
        raise SyncError(
            f"{config.source.package_path}/{relative}: the custody table names no transform "
            "rule for this path; descriptor schema version 3 states the rule every "
            "entrypoint-transforms entry is rewritten by, so a synchronization never has to "
            "assume one"
        )
    rule = TRANSFORM_RULES.get(rule_name)
    if rule is None:
        raise SyncError(
            f"{config.source.package_path}/{relative}: the custody table names the transform "
            f"rule {rule_name!r}, which this tool does not implement; the implemented rules "
            f"are {', '.join(sorted(TRANSFORM_RULES))}"
        )
    return rule


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

    def manifest_entry(self, config: PortConfig) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "path": self.target_path,
            "classification": self.classification,
            "source_path": f"{config.source.package_path}/{self.source_path}",
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


def classify_source_tree(config: PortConfig, present: list[str]) -> None:
    """Fail unless every upstream path is assigned exactly one custody.

    Nothing is left implicit. A file added upstream that the descriptor's table
    does not name would otherwise be dropped in silence, which is how a derived
    tree quietly stops being a copy of anything.

    The upstream client manifest is assigned here rather than in the descriptor:
    it is not a custody choice a package makes, it is the fixed input of the
    `relocate-claude-manifest` transform, and a descriptor that had to list it
    could also forget to.
    """
    declared = list(config.custody.declared())
    if config.source.manifest_path is not None:
        declared.append(config.source.manifest_path)
    assigned = set(declared)
    duplicates = sorted(name for name in assigned if declared.count(name) > 1)
    if duplicates:
        raise SyncError(
            "custody table assigns a path more than one classification: " + ", ".join(duplicates)
        )
    package_path = config.source.package_path
    unclassified = sorted(set(present) - assigned)
    if unclassified:
        raise SyncError(
            "upstream paths carry no custody assignment, so synchronization would drop them "
            "in silence: " + ", ".join(f"{package_path}/{name}" for name in unclassified)
        )
    absent = sorted(assigned - set(present))
    if absent:
        raise SyncError(
            "custody table names paths the pinned commit does not contain: "
            + ", ".join(f"{package_path}/{name}" for name in absent)
        )


def plan_sync(config: PortConfig, source: Path, commit: str) -> list[PlannedFile]:
    """Read the pinned commit and produce the file plan, writing nothing."""
    present = source_package_files(config, source, commit)
    classify_source_tree(config, present)

    planned: list[PlannedFile] = []
    for relative in config.custody.byte_copies:
        payload = read_source_file(config, source, commit, relative)
        planned.append(PlannedFile(relative, relative, BYTE_COPY, payload, payload))
    for relative in config.custody.entrypoint_transforms:
        payload = read_source_file(config, source, commit, relative)
        rule = resolve_transform_rule(config, relative)
        planned.append(
            PlannedFile(
                relative,
                relative,
                TRANSFORM,
                payload,
                rule.apply(payload, relative),
                rule,
            )
        )
    extension_dir = config.source.client_extension_dir
    for relative in config.custody.client_byte_copies:
        payload = read_source_file(config, source, commit, relative)
        target = f"{extension_dir}/{relative}"
        planned.append(PlannedFile(target, relative, BYTE_COPY, payload, payload))

    manifest_source = config.source.manifest_path
    if manifest_source is not None:
        manifest_payload = read_source_file(config, source, commit, manifest_source)
        planned.append(
            PlannedFile(
                f"{extension_dir}/{Path(manifest_source).name}",
                manifest_source,
                TRANSFORM,
                manifest_payload,
                relocate_claude_manifest(manifest_payload, source_path=manifest_source),
                RELOCATE_MANIFEST_RULE,
            )
        )
    planned.sort(key=lambda item: item.target_path)
    return planned


def source_version(config: PortConfig, source: Path, commit: str) -> str:
    """The upstream package's declared version at `commit`.

    Read from the client manifest when the descriptor names one, and from the
    package's own manifest otherwise, so a package with no client adapter still
    records a version rather than being told it has no manifest.
    """
    relative = config.source.manifest_path or config.package_manifest
    document = json.loads(read_source_file(config, source, commit, relative).decode("utf-8"))
    version = document.get("version")
    if not isinstance(version, str) or not version.strip():
        raise SyncError(f"{relative} at {commit} has no non-empty version")
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


def stale_managed_paths(config: PortConfig, plugin_dir: Path, managed: set[str]) -> list[str]:
    """Managed paths an earlier run recorded that the current plan no longer produces.

    The single place the stale set is computed, so the write path and the check
    path cannot disagree about what synchronization is allowed to delete.

    The descriptor's `superseded_by_target_owned` list is subtracted because a
    superseded path is target-owned, and target-owned source is never removed
    here. A tree synchronized before the custody change still carries a manifest
    recording UniFi's `README.md` as an upstream byte copy; without this
    subtraction the first run after the change would read that entry, find the
    path absent from the plan, and unlink the portable README outright -- a
    worse outcome than the overwrite the change exists to prevent.

    Every returned path has already been through `resolve_managed_path` inside
    `previously_managed`, so a manifest naming a path outside the package still
    raises here rather than reaching a caller.
    """
    superseded = set(config.custody.superseded_by_target_owned)
    return sorted(previously_managed(plugin_dir) - managed - superseded)


def build_manifest(
    config: PortConfig,
    planned: list[PlannedFile],
    *,
    commit: str,
    version: str,
    plugin_dir: Path,
) -> dict[str, Any]:
    """The provenance manifest for one synchronization run.

    The `notes` are the descriptor's rather than this script's. They explain one
    package's derivation in that package's own terms -- which paths it drops and
    why, which upstream file its README supersedes -- and a second package that
    inherited the first package's prose would ship a manifest that describes
    something it is not.
    """
    managed = {item.target_path for item in planned}
    files = [item.manifest_entry(config) for item in planned]
    files.extend(
        {"path": path, "classification": TARGET_OWNED}
        for path in target_owned_paths(plugin_dir, managed)
    )
    return {
        "source_repository": config.source.repository,
        "source_commit": commit,
        "source_version": version,
        "source_package_path": config.source.package_path,
        "generated_by": GENERATED_BY,
        "notes": list(config.notes),
        "removed_from_source": [
            {
                "source_path": f"{config.source.package_path}/{relative}",
                "reason": config.dropped_reason,
            }
            for relative in config.custody.dropped_from_source
        ],
        "files": files,
    }


def manifest_text(manifest: dict[str, Any]) -> str:
    return json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"


def apply_plan(config: PortConfig, planned: list[PlannedFile], plugin_dir: Path) -> list[str]:
    """Write every managed path, verify each byte copy, and drop stale managed paths.

    The stale set is read and validated first, before a single byte is written:
    a manifest naming a path outside the package aborts the whole run rather
    than leaving a half-synchronized tree behind.
    """
    managed = {item.target_path for item in planned}
    stale_paths = stale_managed_paths(config, plugin_dir, managed)
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


def verify_plan(config: PortConfig, planned: list[PlannedFile], plugin_dir: Path) -> list[str]:
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
    for stale in stale_managed_paths(config, plugin_dir, {item.target_path for item in planned}):
        if resolve_managed_path(plugin_dir, stale).is_file():
            errors.append(f"stale synchronized file no longer in the plan: {stale}")
    return errors


def synchronize(
    config: PortConfig,
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
    planned = plan_sync(config, source, resolved)
    plugin_dir = package_directory(config, root)
    version = source_version(config, source, resolved)

    if check_only:
        errors = verify_plan(config, planned, plugin_dir)
        manifest = plugin_dir / PROVENANCE_FILENAME
        expected = manifest_text(
            build_manifest(
                config, planned, commit=resolved, version=version, plugin_dir=plugin_dir
            )
        )
        if not manifest.is_file():
            errors.append(f"missing provenance manifest: {PROVENANCE_FILENAME}")
        elif manifest.read_text(encoding="utf-8") != expected:
            errors.append(
                f"provenance manifest does not match the pinned commit: {PROVENANCE_FILENAME}"
            )
        return errors, resolved

    written = apply_plan(config, planned, plugin_dir)
    manifest = build_manifest(
        config, planned, commit=resolved, version=version, plugin_dir=plugin_dir
    )
    manifest_path = plugin_dir / PROVENANCE_FILENAME
    text = manifest_text(manifest)
    if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != text:
        manifest_path.write_text(text, encoding="utf-8")
        written.append(PROVENANCE_FILENAME)
    return sorted(written), resolved


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Derive a portable package from a pinned revision of its upstream repository."
    )
    parser.add_argument(
        "--package",
        required=True,
        help=(
            "the package to derive, named by its descriptor under "
            f"{port_config.CONFIG_DIRECTORY_NAME}/"
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        help="path to a local checkout of the upstream repository the descriptor names",
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
        config = load_config(arguments.package)
        messages, resolved = synchronize(
            config, Path(arguments.source), arguments.commit, check_only=arguments.check
        )
    except SyncError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    repository = config.source.repository
    if arguments.check:
        if messages:
            for message in messages:
                print(f"ERROR: {message}", file=sys.stderr)
            return 1
        print(f"Portable {config.name} package matches {repository} at {resolved}.")
        return 0

    if messages:
        for message in messages:
            print(f"wrote {message}")
    else:
        print("No change: the portable package already matches the pinned commit.")
    print(f"Synchronized {config.package_root} from {repository} at {resolved}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
