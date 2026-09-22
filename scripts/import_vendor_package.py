#!/usr/bin/env python3
"""Bring a Claude Code plugin under this repository's custody, once.

`sync_vendor_source.py` *derives* a package: it reads a pinned upstream every
run, verifies digests against a custody table, and writes `PROVENANCE.json` so
the next run can prove the tree is still a copy. That is the right tool while an
upstream stays authoritative.

The 2026-09-22 custody decision ends that arrangement. Each package is read out
of `infiquetra-claude-plugins` once, laid out in the portable shape, and
maintained here afterwards like `plugins/voice` -- authored, with no upstream to
re-derive from and therefore no provenance manifest to carry. This script is
that one read. It is not a synchronization and deliberately shares none of its
round-tripping machinery: it writes no `PROVENANCE.json`, records no digests,
and has no `--check` mode, because after it runs there is nothing left to check
the tree against. The pinned commit it read is recorded once, by hand, in the
package's `CHANGELOG.md` and in the decision entry.

What it does lay out, from `<source>/plugins/<package>/` at `<commit>`:

* **portable core at the package root** -- `skills/`, `scripts/`, `references/`,
  `schemas/`, `config/`, `tests/`, `README.md`, `CHANGELOG.md`, and every other
  path that is not a Claude surface. Vendor-neutral, which is what lets another
  harness read it.
* **Claude surfaces under `com.infiquetra.claude/`** -- `commands/`, `agents/`,
  `hooks/` (or a root `hooks.json`), `.mcp.json`, `output-styles/`, and the
  upstream `.claude-plugin/plugin.json`. AGENTS.md puts commands, hooks, agent
  definitions, and client runtime integration in an explicit vendor adapter;
  none of them mean anything to a harness that is not Claude Code.
* **two manifests at the package root**, which is the one exception AGENTS.md
  allows and the 2026-08-25 decision "Claude installs the package root" defines:
  `plugin.json` in the portable Agent Plugins shape, and
  `.claude-plugin/plugin.json` where the Claude CLI insists on looking. The
  second carries paths into the adapter and no behaviour.
* **a `fleet-bundle.json`** naming exactly the Fleet Core modules the package
  reaches through the dropped `fleet_commons_shim`.

The rewriting rules are `sync_vendor_source.py`'s own, imported rather than
reimplemented. A second copy of `normalize-skill-frontmatter` would be a second
rule that could disagree with the first, and the repository already refuses that
shape for the descriptor schema.

Standard library only, and no network access beyond the local `git` the source
checkout already is, matching the rest of this repository's tooling.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_repo  # noqa: E402
import port_config  # noqa: E402
import sync_vendor_source as svs  # noqa: E402


class ImportVendorError(Exception):
    """The import cannot proceed, and says which path or rule stopped it."""


#: The client extension directory every Claude surface lands under. Owned by
#: `sync_vendor_source.py`, read here rather than spelled a second time.
CLIENT_EXTENSION_DIR = svs.PORTABLE_PACKAGE_ROOT_MARKER

#: Where the Claude CLI insists a packaging manifest sits. The name is a loading
#: convention of the installed root, which is why the *upstream* copy is lifted
#: out of it and a fresh one is generated in its place.
CLAUDE_MANIFEST_DIR = ".claude-plugin"
CLAUDE_MANIFEST_NAME = "plugin.json"
CLAUDE_MANIFEST_PATH = f"{CLAUDE_MANIFEST_DIR}/{CLAUDE_MANIFEST_NAME}"

#: The portable Agent Plugins manifest and the schema `check_repo.py` enforces.
PORTABLE_MANIFEST_NAME = "plugin.json"
PORTABLE_SCHEMA = check_repo.PLUGIN_SCHEMA

#: Checkout noise and build residue. Never copied, under any classification.
#: `home-lab-ops` carries a vendored virtual environment under one skill, which
#: is why a suffix list alone would not have been enough.
EXCLUDED_DIRECTORY_NAMES = (
    "__pycache__",
    ".venv",
    "venv",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".tox",
    ".eggs",
)
EXCLUDED_FILE_NAMES = (".DS_Store", ".coverage")
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".pyd")

#: The shim itself is never carried. The portable package replaces its
#: resolution ladder -- Claude-specific runtime discovery -- with the build-time
#: Fleet Core bundle, so copying the file would retain exactly the vendor
#: coupling the port exists to remove. `ports/mission-control.json` records the
#: same drop for the same reason, and this is that decision applied by default
#: rather than re-argued per package.
DROPPED_FILE_NAMES = ("fleet_commons_shim.py",)

#: Classification classes, reported in this order.
PORTABLE_CORE = "portable-core"
CLAUDE_ADAPTER = "claude-adapter"
DROPPED = "dropped"
EXCLUDED = "excluded"
GENERATED = "generated"
CLASSES = (PORTABLE_CORE, CLAUDE_ADAPTER, DROPPED, EXCLUDED, GENERATED)

#: Rule names this script records against a file. The three that rewrite bytes
#: are `sync_vendor_source.py`'s, applied by name so the table a dry run prints
#: and the registry that did the work cannot drift apart.
COPY_RULE = "copy"
ADAPTER_PATH_RULE = "rewrite-adapter-root-paths"
GENERATE_RULE = "generate"
EXCLUDE_RULE = "exclude"
DROP_RULE = "drop"
UNRESOLVED_SHIM_RULE = "unresolved-shim"


class AdapterSurface:
    """One Claude surface: where it sits upstream and where it lands here.

    `manifest_field` is the key the generated Claude manifest declares it under,
    and `manifest_value` the `./`-relative path that key carries. Both are
    omitted for a surface Claude discovers without being told (there are none
    today) and for the relocated upstream manifest, which is not a component.
    """

    __slots__ = ("upstream", "destination", "is_directory", "manifest_field", "manifest_value")

    def __init__(
        self,
        upstream: str,
        destination: str,
        *,
        is_directory: bool,
        manifest_field: str | None = None,
        manifest_value: str | None = None,
    ) -> None:
        self.upstream = upstream
        self.destination = destination
        self.is_directory = is_directory
        self.manifest_field = manifest_field
        self.manifest_value = manifest_value


#: Every Claude surface, in the order a path is tested against them. A path that
#: matches none of these is portable core and keeps its place at the root.
#:
#: `hooks/` and a root `hooks.json` both land at
#: `com.infiquetra.claude/hooks/hooks.json` and below, because the Claude
#: manifest's `hooks` key names a file rather than a directory and the two
#: upstream spellings are the same declaration.
ADAPTER_SURFACES = (
    AdapterSurface(
        "commands",
        f"{CLIENT_EXTENSION_DIR}/commands",
        is_directory=True,
        manifest_field="commands",
        manifest_value=f"./{CLIENT_EXTENSION_DIR}/commands/",
    ),
    AdapterSurface(
        "agents",
        f"{CLIENT_EXTENSION_DIR}/agents",
        is_directory=True,
        manifest_field="agents",
        manifest_value=f"./{CLIENT_EXTENSION_DIR}/agents/",
    ),
    AdapterSurface(
        "output-styles",
        f"{CLIENT_EXTENSION_DIR}/output-styles",
        is_directory=True,
        manifest_field="outputStyles",
        manifest_value=f"./{CLIENT_EXTENSION_DIR}/output-styles/",
    ),
    AdapterSurface(
        "hooks",
        f"{CLIENT_EXTENSION_DIR}/hooks",
        is_directory=True,
    ),
    AdapterSurface(
        "hooks.json",
        f"{CLIENT_EXTENSION_DIR}/hooks/hooks.json",
        is_directory=False,
    ),
    AdapterSurface(
        ".mcp.json",
        f"{CLIENT_EXTENSION_DIR}/mcp/servers.json",
        is_directory=False,
        manifest_field="mcpServers",
        manifest_value=f"./{CLIENT_EXTENSION_DIR}/mcp/servers.json",
    ),
)

#: The hooks declaration is a file inside a surface rather than the surface
#: itself, so it is resolved after the tree is laid out: only a package that
#: actually produced this path declares `hooks`.
HOOKS_MANIFEST_FIELD = "hooks"
HOOKS_DECLARATION_PATH = f"{CLIENT_EXTENSION_DIR}/hooks/hooks.json"

#: The portable skills tree. Declared so a Claude install reaches the portable
#: skills as well as the adapter, exactly as `plugins/voice` declares it. The
#: key adds to Claude's default rather than replacing it, so naming the default
#: location is harmless and makes the declaration readable.
SKILLS_DIRECTORY = "skills"
SKILLS_MANIFEST_FIELD = "skills"
SKILLS_MANIFEST_VALUE = f"./{SKILLS_DIRECTORY}/"

#: Metadata the generated Claude manifest carries over from the upstream one.
#: `repository` is deliberately not among them: it is rewritten to name this
#: repository, which is where the package is maintained after the import.
CARRIED_MANIFEST_FIELDS = (
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "license",
    "keywords",
)
THIS_REPOSITORY = "https://github.com/infiquetra/infiquetra-agent-plugins"

#: A `fleet_commons_shim.load("<module>")` call. Read from the *upstream* bytes,
#: before a transform rewrites them away, because the module name is what the
#: generated `fleet-bundle.json` has to declare.
SHIM_LOAD = re.compile(r"fleet_commons_shim\.load\(\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\s*\)")
SHIM_MENTION = "fleet_commons_shim"

#: The rules that rewrite a shim use, tried in this order. Each matches exactly
#: one upstream shape and raises when it finds zero or more than one, so the
#: first that succeeds is the only one that could have.
FLEET_RULE_NAMES = (
    "resolve-bundled-fleet-module",
    "resolve-bundled-fleet-module-split",
    "resolve-bundled-fleet-module-guarded",
)

#: `${CLAUDE_PLUGIN_ROOT}` expands to the installed package root, so a path that
#: named a surface at the upstream root names nothing once that surface moves
#: under the adapter. Only moved surfaces are rewritten: `skills/` and
#: `scripts/` stay at the root and their paths are already correct.
PLUGIN_ROOT_TOKEN = "${CLAUDE_PLUGIN_ROOT}"

#: Files whose text is scanned for those paths. A binary asset is copied as-is.
TEXT_SUFFIXES = (".json", ".md", ".py", ".sh", ".txt", ".yaml", ".yml", ".toml", ".jsonc")


class PlannedFile:
    """One file the import will write, and how it was decided."""

    __slots__ = ("source", "destination", "classification", "rule", "payload", "note")

    def __init__(
        self,
        source: str,
        destination: str | None,
        classification: str,
        rule: str,
        payload: bytes | None,
        note: str = "",
    ) -> None:
        self.source = source
        self.destination = destination
        self.classification = classification
        self.rule = rule
        self.payload = payload
        self.note = note


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git(source: Path, *arguments: str) -> bytes:
    """Run git in the upstream checkout, or raise with its own message.

    Everything is read through `git show <commit>:<path>` rather than from the
    working tree, so an upstream checkout with uncommitted edits, a different
    branch, or a stale submodule cannot change what lands here. The pin is the
    only input.
    """
    completed = subprocess.run(
        ["git", "-C", str(source), *arguments],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", "replace").strip()
        raise ImportVendorError(f"git {' '.join(arguments)} failed in {source}: {detail}")
    return completed.stdout


def resolve_commit(source: Path, commit: str) -> str:
    if not (source / ".git").exists():
        raise ImportVendorError(f"{source} is not a git checkout, so no commit can be read from it")
    return _git(source, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()


def source_files(source: Path, commit: str, package: str) -> list[str]:
    """Every package-relative path the upstream carries at `commit`."""
    prefix = f"plugins/{package}"
    raw = _git(source, "ls-tree", "-r", "-z", "--name-only", commit, "--", f"{prefix}/")
    names = [name for name in raw.decode("utf-8").split("\0") if name]
    if not names:
        raise ImportVendorError(
            f"{prefix}/ holds no file at {commit[:12]}; the upstream does not carry a package "
            f"called {package!r} at that revision"
        )
    return sorted(name[len(prefix) + 1 :] for name in names)


def read_source_file(source: Path, commit: str, package: str, relative: str) -> bytes:
    return _git(source, "show", f"{commit}:plugins/{package}/{relative}")


def exclusion_reason(relative: str) -> str | None:
    """Why this path is never copied, or `None` when it is carried."""
    parts = Path(relative).parts
    for part in parts[:-1]:
        if part in EXCLUDED_DIRECTORY_NAMES:
            return f"inside {part}/"
    name = parts[-1]
    if name in EXCLUDED_DIRECTORY_NAMES:
        return f"inside {name}/"
    if name in EXCLUDED_FILE_NAMES:
        return name
    if name.endswith(EXCLUDED_SUFFIXES):
        return f"*{Path(name).suffix}"
    return None


def adapter_destination(relative: str) -> tuple[str, AdapterSurface] | None:
    """Where a Claude surface path lands, or `None` for portable core."""
    if relative == CLAUDE_MANIFEST_PATH:
        return None  # handled by the relocation rule, which is not a surface
    for surface in ADAPTER_SURFACES:
        if surface.is_directory:
            if relative == surface.upstream or relative.startswith(f"{surface.upstream}/"):
                remainder = relative[len(surface.upstream) :].lstrip("/")
                return (f"{surface.destination}/{remainder}" if remainder else surface.destination), surface
        elif relative == surface.upstream:
            return surface.destination, surface
    return None


def _is_text(relative: str) -> bool:
    return relative.endswith(TEXT_SUFFIXES)


def rewrite_adapter_root_paths(payload: bytes, relative: str) -> tuple[bytes, int]:
    """Re-anchor `${CLAUDE_PLUGIN_ROOT}` paths that named a moved surface.

    Applied to every file that moves into the adapter, not only to `hooks.json`.
    The path `${CLAUDE_PLUGIN_ROOT}/hooks/stop.py` is wrong after the move
    whichever file says it, and a command or agent document that launches a hook
    script is as broken as the hooks descriptor would be.

    Paths into `skills/` and `scripts/` are left exactly as they are: those trees
    stay at the package root, so their `${CLAUDE_PLUGIN_ROOT}` paths still
    resolve. Rewriting them would break the portable core's one working
    reference into itself.
    """
    if not _is_text(relative):
        return payload, 0
    try:
        body = payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload, 0

    rewrites = 0
    for surface in ADAPTER_SURFACES:
        old = f"{PLUGIN_ROOT_TOKEN}/{surface.upstream}"
        new = f"{PLUGIN_ROOT_TOKEN}/{surface.destination}"
        if surface.is_directory:
            old += "/"
            new += "/"
        count = body.count(old)
        if count:
            body = body.replace(old, new)
            rewrites += count
    if not rewrites:
        return payload, 0
    return body.encode("utf-8"), rewrites


def apply_fleet_rule(payload: bytes, relative: str) -> tuple[bytes, str]:
    """Rewrite a shim use with whichever of the three rules matches it.

    Each rule raises unless it finds exactly one occurrence of the shape it
    describes, so trying them in order is a selection and not a fallback: at
    most one can succeed, and the one that does is named in the report.

    A file no rule matches is carried *unchanged* and reported as unresolved,
    and the import exits non-zero having written the tree. The three shapes in
    the rule family are the ones the ported packages happened to carry; several
    upstream packages use the shim inside a function, or load two modules from
    one file, and stopping the whole import on the first of those would mean no
    package with an unfamiliar shape could be laid out at all.

    Carrying it silently is the other thing this must not do. An unrewritten
    `fleet_commons_shim` import is a package that imports a module nothing
    generated -- the defect AGENTS.md records against the UniFi clients -- and
    it installs cleanly, then fails at the first invocation. So the file is
    named in the summary, named again in the non-zero exit, and the module it
    reaches is still declared in `fleet-bundle.json`, so the bundle is on disk
    when the import is rewritten by hand.
    """
    for name in FLEET_RULE_NAMES:
        rule = svs.TRANSFORM_RULES[name]
        try:
            return rule.apply(payload, relative), name
        except svs.SyncError:
            continue
    return payload, UNRESOLVED_SHIM_RULE


def fleet_modules(payload: bytes) -> list[str]:
    """Every Fleet Core module this file loads through the shim, in order."""
    try:
        body = payload.decode("utf-8")
    except UnicodeDecodeError:
        return []
    seen: list[str] = []
    for module in SHIM_LOAD.findall(body):
        if module not in seen:
            seen.append(module)
    return seen


def bundle_destination(relative: str, module: str) -> str:
    """Where the bundler must write `module` for the client at `relative`.

    The rewritten import inserts the bundle directory *beside the client's own
    file*, so the destination follows the client rather than a fixed location. A
    client under `skills/x/scripts/` needs its bundle at
    `skills/x/scripts/_bundled/`, and declaring the package-root default instead
    would put the module somewhere the client never looks.
    """
    parent = str(Path(relative).parent)
    prefix = "" if parent == "." else f"{parent}/"
    return f"{prefix}{check_repo.BUNDLE_DIRECTORY_NAME}/{module}.py"


def build_fleet_bundle(modules: dict[str, list[str]]) -> dict[str, Any]:
    """The consumer's closed build declaration, or nothing when it reaches none.

    Only modules are declared. A Fleet Core *data* file is reached by path
    rather than through `fleet_commons_shim.load`, so nothing in the upstream
    bytes names one, and inventing a declaration for a file the import cannot
    see would be a guess. A package that needs one adds it by hand, which the
    summary says.
    """
    return {
        "$schema": "../../schemas/fleet-bundle.schema.json",
        # Version 1 because nothing generated here declares `data`. The schema
        # requires version 2 for a declaration that does, so a data entry added
        # by hand later has to bump this, and the bump is checked rather than
        # assumed.
        "schema_version": "1",
        "modules": [
            {"name": name, "destinations": sorted(set(destinations))}
            for name, destinations in sorted(modules.items())
        ],
    }


def build_claude_manifest(upstream: dict[str, Any], declared: dict[str, str]) -> dict[str, Any]:
    """The packaging manifest Claude reads at the installed package root.

    It carries paths and no behaviour, which is the condition AGENTS.md attaches
    to a vendor manifest sitting outside its adapter. Every component key names
    a surface that exists: Claude fails to load a declared path that is not
    there, and a manifest that declared the full set regardless would break
    every package that does not carry all of them.
    """
    manifest: dict[str, Any] = {}
    for field in CARRIED_MANIFEST_FIELDS:
        if field in upstream:
            manifest[field] = upstream[field]
    manifest["repository"] = THIS_REPOSITORY
    manifest.update(declared)
    return manifest


def build_portable_manifest(upstream: dict[str, Any]) -> dict[str, Any]:
    """The vendor-neutral Agent Plugins manifest `check_repo.py` enforces."""
    missing = [field for field in ("name", "version", "description") if not upstream.get(field)]
    if missing:
        raise ImportVendorError(
            f"the upstream Claude manifest states no {', '.join(missing)}; the portable "
            "manifest requires all three and this import will not invent them"
        )
    return {
        "$schema": PORTABLE_SCHEMA,
        "name": upstream["name"],
        "version": upstream["version"],
        "description": upstream["description"],
    }


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def plan_import(source: Path, commit: str, package: str) -> list[PlannedFile]:
    """Every file the import writes, decided but not yet written.

    Planning is complete before anything is written, so a package that stops on
    a rule it cannot apply stops having changed nothing.
    """
    planned: list[PlannedFile] = []
    upstream_manifest: dict[str, Any] | None = None
    modules: dict[str, list[str]] = {}
    produced: set[str] = set()

    for relative in source_files(source, commit, package):
        reason = exclusion_reason(relative)
        if reason is not None:
            planned.append(PlannedFile(relative, None, EXCLUDED, EXCLUDE_RULE, None, reason))
            continue

        if Path(relative).name in DROPPED_FILE_NAMES:
            planned.append(
                PlannedFile(
                    relative,
                    None,
                    DROPPED,
                    DROP_RULE,
                    None,
                    "replaced by the build-time Fleet Core bundle",
                )
            )
            continue

        payload = read_source_file(source, commit, package, relative)

        if relative == CLAUDE_MANIFEST_PATH:
            rewritten = svs.relocate_claude_manifest(payload, relative)
            upstream_manifest = json.loads(rewritten.decode("utf-8"))
            destination = f"{CLIENT_EXTENSION_DIR}/{CLAUDE_MANIFEST_NAME}"
            planned.append(
                PlannedFile(
                    relative,
                    destination,
                    CLAUDE_ADAPTER,
                    svs.MANIFEST_TRANSFORM_NAME,
                    rewritten,
                )
            )
            produced.add(destination)
            continue

        moved = adapter_destination(relative)
        if moved is not None:
            destination, _surface = moved
            rewritten, count = rewrite_adapter_root_paths(payload, relative)
            rule = ADAPTER_PATH_RULE if count else COPY_RULE
            note = f"{count} plugin-root path(s) re-anchored" if count else ""
            planned.append(
                PlannedFile(relative, destination, CLAUDE_ADAPTER, rule, rewritten, note)
            )
            produced.add(destination)
            continue

        rule = COPY_RULE
        note = ""
        if Path(relative).name == check_repo.SKILL_DOCUMENT_NAME:
            payload = svs.normalize_skill_frontmatter(payload, relative)
            rule = svs.FRONTMATTER_TRANSFORM_NAME
        elif relative.endswith(".py") and SHIM_MENTION in payload.decode("utf-8", "replace"):
            reached = fleet_modules(payload)
            payload, rule = apply_fleet_rule(payload, relative)
            for module in reached:
                modules.setdefault(module, []).append(bundle_destination(relative, module))
            if rule == UNRESOLVED_SHIM_RULE:
                note = (
                    f"still imports {SHIM_MENTION}, which this package does not carry; "
                    "rewrite it to import the bundled module"
                )
            else:
                note = f"reaches {', '.join(reached)}" if reached else "shim import only"
        elif _is_text(relative) and PLUGIN_ROOT_TOKEN in payload.decode("utf-8", "replace"):
            _unused, count = rewrite_adapter_root_paths(payload, relative)
            if count:
                note = (
                    f"{count} portable-core path(s) name a moved Claude surface; "
                    "left unchanged, fix by hand"
                )
        planned.append(PlannedFile(relative, relative, PORTABLE_CORE, rule, payload, note))
        produced.add(relative)

    if upstream_manifest is None:
        raise ImportVendorError(
            f"plugins/{package}/{CLAUDE_MANIFEST_PATH} is absent at {commit[:12]}; the import "
            "reads the package's identity and version from it and will not invent them"
        )

    declared: dict[str, str] = {}
    for surface in ADAPTER_SURFACES:
        if surface.manifest_field is None:
            continue
        if any(path == surface.destination or path.startswith(f"{surface.destination}/") for path in produced):
            assert surface.manifest_value is not None
            declared[surface.manifest_field] = surface.manifest_value
    if HOOKS_DECLARATION_PATH in produced:
        declared[HOOKS_MANIFEST_FIELD] = f"./{HOOKS_DECLARATION_PATH}"
    if any(path.startswith(f"{SKILLS_DIRECTORY}/") for path in produced):
        declared[SKILLS_MANIFEST_FIELD] = SKILLS_MANIFEST_VALUE

    planned.append(
        PlannedFile(
            "-",
            CLAUDE_MANIFEST_PATH,
            GENERATED,
            GENERATE_RULE,
            _json_bytes(build_claude_manifest(upstream_manifest, declared)),
            f"declares {', '.join(sorted(declared)) or 'no component'}",
        )
    )
    planned.append(
        PlannedFile(
            "-",
            PORTABLE_MANIFEST_NAME,
            GENERATED,
            GENERATE_RULE,
            _json_bytes(build_portable_manifest(upstream_manifest)),
            "portable Agent Plugins shape",
        )
    )
    if modules:
        planned.append(
            PlannedFile(
                "-",
                check_repo.FLEET_BUNDLE_FILENAME,
                GENERATED,
                GENERATE_RULE,
                _json_bytes(build_fleet_bundle(modules)),
                f"declares {', '.join(sorted(modules))}",
            )
        )
    return planned


def write_import(planned: list[PlannedFile], package_directory: Path) -> list[str]:
    """Write every planned file, and return the paths written."""
    written: list[str] = []
    for entry in planned:
        if entry.destination is None or entry.payload is None:
            continue
        target = package_directory / entry.destination
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(entry.payload)
        written.append(entry.destination)
    return sorted(written)


def format_table(planned: list[PlannedFile]) -> str:
    """The classification table: every upstream path, its destination, its rule."""
    rows = [("UPSTREAM PATH", "DESTINATION", "RULE")]
    for entry in planned:
        rows.append((entry.source, entry.destination or "(not carried)", entry.rule))
    widths = [max(len(row[column]) for row in rows) for column in range(3)]
    lines = []
    for index, row in enumerate(rows):
        lines.append("  ".join(value.ljust(widths[column]) for column, value in enumerate(row)).rstrip())
        if index == 0:
            lines.append("  ".join("-" * width for width in widths))
    notes = [f"  {entry.destination or entry.source}: {entry.note}" for entry in planned if entry.note]
    if notes:
        lines.append("")
        lines.append("Notes:")
        lines.extend(notes)
    return "\n".join(lines)


def unresolved_shim_files(planned: list[PlannedFile]) -> list[str]:
    """Every carried file that still imports the shim this package drops."""
    return [entry.source for entry in planned if entry.rule == UNRESOLVED_SHIM_RULE]


def summarize(planned: list[PlannedFile], package: str, commit: str) -> str:
    counts = {name: 0 for name in CLASSES}
    for entry in planned:
        counts[entry.classification] += 1
    lines = [f"Imported {package} from {commit[:12]}:"]
    for name in CLASSES:
        lines.append(f"  {name}: {counts[name]}")
    not_carried = [
        entry for entry in planned if entry.classification in (EXCLUDED, DROPPED)
    ]
    if not_carried:
        lines.append("")
        lines.append("Not carried:")
        for entry in not_carried:
            lines.append(f"  {entry.source} ({entry.note})")
    unresolved = unresolved_shim_files(planned)
    if unresolved:
        lines.append("")
        lines.append(
            f"UNRESOLVED: {len(unresolved)} file(s) still import {SHIM_MENTION}, which this "
            "package does not carry. Each was written unchanged and will raise "
            "ModuleNotFoundError before parsing an argument. Rewrite each to import the "
            "bundled module beside it:"
        )
        for relative in unresolved:
            lines.append(f"  {relative}")
    return "\n".join(lines)


def next_steps(planned: list[PlannedFile], package: str) -> list[str]:
    """What the import deliberately does not do, spelled as commands.

    The bundler is not run here. It reads `plugins/fleet-core/`, which a
    separate unit may still be importing, and a build step folded into a
    one-shot import would be a build nobody could re-run without re-importing.
    """
    steps: list[str] = []
    if any(entry.destination == check_repo.FLEET_BUNDLE_FILENAME for entry in planned):
        steps.append(f"python3 scripts/bundle_fleet_module.py --plugin {package}")
    if any(entry.destination == CLAUDE_MANIFEST_PATH for entry in planned):
        # The import just made this package Claude-installable, which makes the
        # generated marketplace stale. `check_repo.py` refuses a stale one, so
        # this has to run before it rather than after.
        steps.append("python3 scripts/sync_marketplace.py")
    steps.append("python3 scripts/check_repo.py")
    steps.append("python3 -m unittest discover -s tests")
    steps.append(f"python3 -m pytest plugins/{package}/tests -q")
    return steps


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--package", required=True, help="the package to import")
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help="path to a local checkout of the upstream repository",
    )
    parser.add_argument(
        "--commit",
        required=True,
        help="the upstream revision to read; the working tree state is never read",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the classification table and write nothing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing package tree instead of refusing",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_argument_parser().parse_args(argv)
    root = repository_root()
    package_directory = root / port_config.PACKAGE_PARENT / arguments.package

    try:
        commit = resolve_commit(arguments.source.resolve(), arguments.commit)
        planned = plan_import(arguments.source.resolve(), commit, arguments.package)
    except (ImportVendorError, svs.SyncError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if arguments.dry_run:
        print(format_table(planned))
        print()
        print(summarize(planned, arguments.package, commit))
        print()
        print("Dry run: nothing was written.")
        return 1 if unresolved_shim_files(planned) else 0

    if package_directory.exists():
        if not arguments.force:
            print(
                f"ERROR: {package_directory.relative_to(root)} already exists. An import is a "
                "one-shot read that replaces the tree wholesale, so it refuses rather than "
                "merging into a package someone is maintaining. Re-run with --force to replace "
                "it.",
                file=sys.stderr,
            )
            return 1
        shutil.rmtree(package_directory)

    written = write_import(planned, package_directory)
    print(summarize(planned, arguments.package, commit))
    print()
    print(f"Wrote {len(written)} file(s) under {package_directory.relative_to(root)}/.")
    print()
    print("No PROVENANCE.json was written: this package is authored here from now on.")
    print(f"Record the pin {commit} in plugins/{arguments.package}/CHANGELOG.md.")
    print()
    print("Next:")
    for step in next_steps(planned, arguments.package):
        print(f"  {step}")
    if unresolved_shim_files(planned):
        # The tree is written; the import is not finished. A zero exit here
        # would report success over a package that cannot run, which is the one
        # outcome worth failing for.
        print()
        print(
            "Exiting non-zero: the tree is written, but the unresolved imports above must be "
            "rewritten before this package runs.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
