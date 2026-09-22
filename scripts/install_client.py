#!/usr/bin/env python3
"""Place this catalog where each harness on the machine actually looks.

The ten placements are the ones the compatibility matrices and
``scripts/assess_clients.py`` already recorded. This script does not invent a
second method. It also does not run anything unless ``--execute`` is passed;
the default prints every command and file operation and stops.

Two calls that are not obvious from the command list:

* Codex stays ``unsupported``. The marketplaces Codex already loads are
  ``.agents/plugins/marketplace.json`` plus a ``.codex-plugin/plugin.json`` in
  every plugin directory, and that plugin directory must not also contain
  ``.claude-plugin``. This catalog has the Claude manifest and no Codex
  manifest. Writing either file would claim a layout the bytes do not have.
* A Claude marketplace name that is already registered is not registered
  again, and it is not retargeted at this checkout. ``infiquetra-plugins`` on
  Agy is the Antigravity repository; a marketplace name is not proof of the
  old git URL.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


CLIENTS = (
    "claude",
    "codex",
    "cursor",
    "qwen",
    "grok",
    "opencode",
    "gemini",
    "muse",
    "agy",
    "hermes",
)

#: argv0 for each client. Cursor's marketplace command is ``cursor-agent``;
#: ``cursor`` on PATH is the editor.
CLIENT_BINARIES = {
    "claude": "claude",
    "codex": "codex",
    "cursor": "cursor-agent",
    "qwen": "qwen",
    "grok": "grok",
    "opencode": "opencode",
    "gemini": "gemini",
    "muse": "muse",
    "agy": "agy",
    "hermes": "hermes",
}

SKILL_CLIENTS = frozenset({"opencode", "gemini", "muse", "hermes"})

CATALOG_GIT_URL = "https://github.com/infiquetra/infiquetra-agent-plugins"
LEGACY_GIT_URL = "https://github.com/infiquetra/infiquetra-claude-plugins"
CATALOG_SLUG = "infiquetra/infiquetra-agent-plugins"
LEGACY_SLUG = "infiquetra/infiquetra-claude-plugins"
LEGACY_DIR = "infiquetra-claude-plugins"
LEGACY_MARKETPLACE = "infiquetra-plugins"

DEDICATED_REPOS = (
    "infiquetra-codex-plugins",
    "infiquetra-opencode-plugins",
    "infiquetra-antigravity-plugins",
)

OPENCODE_SCHEMA = "infiquetra-opencode-install.v1"
HERMES_SCHEMA = "infiquetra-hermes-install.v1"
MUSE_SCHEMA = "infiquetra-muse-install.v1"
GEMINI_SCHEMA = "infiquetra-gemini-install.v1"
AGY_SCHEMA = "infiquetra-agy-install.v1"

COMMAND_TIMEOUT = 120

CODEX_UNSUPPORTED = (
    "Codex loads a marketplace from .agents/plugins/marketplace.json whose plugin "
    "directories each carry .codex-plugin/plugin.json (skills and interface.defaultPrompt) "
    "and must not contain .claude-plugin. Working copies are the OpenAI bundled marketplace "
    "and infiquetra-codex-plugins. This catalog's packages have a portable plugin.json and "
    ".claude-plugin/plugin.json and no .codex-plugin/plugin.json. A file at "
    "com.infiquetra.codex/marketplace.json is not the path those marketplaces use, and "
    "pointing .agents/plugins/marketplace.json at these packages would claim a Codex plugin "
    "layout the bytes do not have. infiquetra-codex-plugins is not modified."
)


class InstallError(Exception):
    """The run cannot plan, or a command it did run failed."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Package:
    """One ``plugins/<name>/`` that has a portable ``plugin.json``."""

    name: str
    root: Path
    skills: tuple[Path, ...]


@dataclass
class Action:
    """One command or file operation. Dry-run prints it; execute performs it."""

    kind: str
    client: str
    argv: tuple[str, ...] = ()
    stdin: str | None = None
    path: str = ""
    target: str = ""
    payload: dict | None = None
    message: str = ""
    schema: str = ""


@dataclass
class Readback:
    client: str
    package: str
    status: str
    source: str = ""


@dataclass
class Plan:
    actions: list[Action] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)


def default_catalog() -> Path:
    """The repository that contains this script."""
    return Path(__file__).resolve().parent.parent


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Place this catalog for one harness, read the placement back, or remove "
            "placements that record the old infiquetra-claude-plugins marketplace. "
            "The default prints the plan and changes nothing."
        )
    )
    parser.add_argument(
        "--client",
        required=True,
        choices=[*CLIENTS, "all"],
        help="Harness name, or all ten",
    )
    parser.add_argument(
        "--package",
        action="append",
        default=[],
        help="Package directory name under plugins/. Repeatable. Default: every plugin.json",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        help="Catalog root. Default: the repository that contains this script",
    )
    parser.add_argument(
        "--binary",
        action="append",
        default=[],
        metavar="CLIENT=PATH",
        help="Invoke this executable instead of the client name on PATH. Repeatable",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform the plan. Without this flag the plan is only printed",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan and change nothing. This is also the default",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Read each client's own state and print one line per package: "
            "installed-from-catalog, installed-from-elsewhere (<source>), or absent. "
            "Exit 1 if any package is absent"
        ),
    )
    parser.add_argument(
        "--uninstall-legacy",
        action="store_true",
        help=(
            "Remove placements whose recorded source is infiquetra-claude-plugins. "
            "An unsourced copy is left in place. Dedicated repositories are never touched"
        ),
    )
    args = parser.parse_args(argv)
    if args.execute and args.dry_run:
        parser.error("--execute and --dry-run together do not describe one run")
    if args.check and args.execute:
        parser.error("--check reads state and does not install")
    if args.check and args.uninstall_legacy:
        parser.error("--check and --uninstall-legacy are separate runs")
    if args.check and args.dry_run:
        # --check is already read-only. Accept the flag so a plan that adds it is not an error.
        pass
    return args


def selected_clients(name: str) -> tuple[str, ...]:
    if name == "all":
        return CLIENTS
    return (name,)


def parse_binaries(pairs: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise InstallError(f"--binary {pair!r} is not CLIENT=PATH")
        client, path = pair.split("=", 1)
        if client not in CLIENTS:
            raise InstallError(
                f"--binary names {client!r}, which is not one of {', '.join(CLIENTS)}"
            )
        if not path.strip():
            raise InstallError(f"--binary {client}= is missing a path")
        found[client] = path.strip()
    return found


def load_json(path: Path) -> dict | list | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InstallError(f"{path} is not valid JSON ({exc})") from exc


def load_object(path: Path) -> dict | None:
    value = load_json(path)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise InstallError(f"{path} is not a JSON object")
    return value


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def discover_packages(catalog: Path) -> list[Package]:
    root = catalog / "plugins"
    if not root.is_dir():
        raise InstallError(f"{catalog} has no plugins directory")
    found: list[Package] = []
    for child in sorted(path for path in root.iterdir() if path.is_dir()):
        if child.name.startswith("."):
            continue
        manifest_path = child / "plugin.json"
        if not manifest_path.is_file():
            continue
        manifest = load_object(manifest_path)
        if manifest is None:
            continue
        name = manifest.get("name") or child.name
        if not isinstance(name, str) or name != child.name:
            raise InstallError(
                f"{manifest_path} name {name!r} does not match its directory {child.name!r}"
            )
        skills: list[Path] = []
        skills_root = child / "skills"
        if skills_root.is_dir():
            for skill in sorted(path for path in skills_root.iterdir() if path.is_dir()):
                if (skill / "SKILL.md").is_file():
                    skills.append(skill)
        found.append(Package(name=name, root=child.resolve(), skills=tuple(skills)))
    if not found:
        raise InstallError(f"{catalog} has no plugins/<name>/plugin.json packages")
    return found


def select_packages(catalog: Path, names: list[str]) -> list[Package]:
    packages = discover_packages(catalog)
    if not names:
        return packages
    by_name = {package.name: package for package in packages}
    missing = [name for name in names if name not in by_name]
    if missing:
        raise InstallError("unknown package: " + ", ".join(missing))
    return [by_name[name] for name in names]


def require_unique_skills(packages: list[Package]) -> None:
    """Skill-scoped harnesses install by skill directory name, one destination each."""
    owner: dict[str, str] = {}
    for package in packages:
        for skill in package.skills:
            previous = owner.get(skill.name)
            if previous is not None and previous != package.name:
                raise InstallError(
                    f"skill {skill.name!r} is in both {previous!r} and {package.name!r}; "
                    "a skill-scoped harness has one destination directory per name"
                )
            owner[skill.name] = package.name


def marketplace_document(catalog: Path) -> dict:
    path = catalog / ".claude-plugin" / "marketplace.json"
    document = load_object(path)
    if document is None:
        raise InstallError(f"{path} is missing; Claude installs from that marketplace file")
    return document


def marketplace_name(catalog: Path) -> str:
    name = marketplace_document(catalog).get("name")
    if not isinstance(name, str) or not name:
        raise InstallError("marketplace.json is missing a name")
    return name


def marketplace_plugin_names(catalog: Path) -> set[str]:
    entries = marketplace_document(catalog).get("plugins") or []
    if not isinstance(entries, list):
        raise InstallError("marketplace.json plugins is not a list")
    names: set[str] = set()
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str):
            names.add(entry["name"])
    return names


def github_repo(value: str) -> str | None:
    """``owner/repo`` out of a GitHub URL or ``owner/repo`` shorthand. Nothing else."""
    text = value.strip().rstrip("/")
    if text.endswith(".git"):
        text = text[:-4]
    for prefix in (
        "https://github.com/",
        "http://github.com/",
        "ssh://git@github.com/",
        "git@github.com:",
        "github.com/",
    ):
        if text.startswith(prefix):
            rest = text[len(prefix) :]
            parts = [part for part in rest.split("/") if part]
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
            return None
    if text.count("/") == 1 and not text.startswith(".") and " " not in text:
        owner, repo = text.split("/", 1)
        if owner and repo and "/" not in repo:
            return text
    return None


def is_dedicated_source(value: str) -> bool:
    if not value:
        return False
    slug = github_repo(value)
    if slug is not None and slug.split("/", 1)[1] in DEDICATED_REPOS:
        return True
    return any(part in DEDICATED_REPOS for part in Path(value).parts)


def is_legacy_source(value: str) -> bool:
    """True only when the value records infiquetra-claude-plugins, and not a dedicated repo."""
    if not value or is_dedicated_source(value):
        return False
    slug = github_repo(value)
    if slug == LEGACY_SLUG:
        return True
    return LEGACY_DIR in Path(value).parts


def is_catalog_url(value: str) -> bool:
    return github_repo(value) == CATALOG_SLUG


def is_within_catalog(value: str, catalog: Path) -> bool:
    if not value.startswith("/"):
        return False
    try:
        resolved = Path(value).resolve()
        root = catalog.resolve()
    except OSError:
        return False
    return resolved == root or root in resolved.parents


def is_catalog_source(value: str, catalog: Path) -> bool:
    if not value or is_dedicated_source(value):
        return False
    return is_catalog_url(value) or is_within_catalog(value, catalog)


def resolve_executable(client: str, overrides: dict[str, str], *, required: bool) -> str:
    """The executable argv0.

    ``--binary`` mirrors ``assess_clients.resolve_real_binary``: a path that is the
    same file as the launcher on PATH is refused. Pointing a wrapper at itself is
    how that launcher re-executes until the machine runs out of processes. Omitting
    ``--binary`` invokes the name on PATH, which is the wrapper the operator
    actually runs against a real home.
    """
    binary_name = CLIENT_BINARIES[client]
    override = overrides.get(client)
    if override:
        candidate = Path(override)
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise InstallError(
                f"--binary {client}={override!r} is not an executable file"
            )
        launcher = shutil.which(binary_name, path=os.environ.get("PATH"))
        if launcher is not None and os.path.samefile(candidate, launcher):
            raise InstallError(
                f"--binary {client}={override!r} is the same file as the {binary_name!r} "
                "launcher on PATH. A wrapper pointed at itself launches itself recursively. "
                "Pass the real executable, or omit --binary to invoke the launcher by name."
            )
        return str(candidate.resolve())
    found = shutil.which(binary_name, path=os.environ.get("PATH"))
    if found:
        return found
    if required:
        raise InstallError(f"{client}: {binary_name!r} is not on PATH and no --binary was given")
    return binary_name


def command_action(
    client: str,
    args: tuple[str, ...],
    overrides: dict[str, str],
    *,
    required: bool,
    stdin: str | None = None,
) -> Action:
    executable = resolve_executable(client, overrides, required=required)
    return Action("command", client, argv=(executable, *args), stdin=stdin)


def kill_group(process: subprocess.Popen) -> None:
    if not hasattr(os, "killpg"):
        process.kill()
        return
    try:
        os.killpg(process.pid, 15)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, 9)
        except (ProcessLookupError, PermissionError):
            process.kill()


def run_command(action: Action) -> None:
    process = subprocess.Popen(
        action.argv,
        stdin=subprocess.PIPE if action.stdin is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        env=os.environ.copy(),
    )
    try:
        stdout, stderr = process.communicate(action.stdin, timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        kill_group(process)
        process.communicate()
        raise InstallError(
            f"timed out after {COMMAND_TIMEOUT:.0f}s: {shlex.join(action.argv)}",
            code=1,
        ) from exc
    if process.returncode != 0:
        detail = (stderr or stdout or "").strip().splitlines()
        tail = "\n".join(detail[-8:])
        raise InstallError(
            f"command failed ({process.returncode}): {shlex.join(action.argv)}"
            + (f"\n{tail}" if tail else ""),
            code=1,
        )


def format_action(action: Action) -> str:
    if action.kind == "command":
        text = f"{action.client}: command: {shlex.join(action.argv)}"
        if action.stdin is not None:
            text += " stdin=" + action.stdin.replace("\n", "\\n")
        return text
    if action.kind == "symlink":
        return f"{action.client}: symlink: {action.path} -> {action.target}"
    if action.kind == "write-json":
        return f"{action.client}: write: {action.path}"
    if action.kind == "merge-link":
        return f"{action.client}: write: {action.path} target={action.target} link={action.message}"
    if action.kind == "merge-qwen":
        return f"{action.client}: write: {action.path} source={action.target} type=local"
    if action.kind == "merge-agy":
        return f"{action.client}: write: {action.path} package={action.message} source={action.target}"
    if action.kind == "remove":
        return f"{action.client}: remove: {action.path}"
    if action.kind == "drop-link":
        return f"{action.client}: write: {action.path} drop={action.message}"
    if action.kind == "drop-agy":
        return f"{action.client}: write: {action.path} drop={action.message}"
    if action.kind == "unsupported":
        return f"{action.client} unsupported: {action.message}"
    if action.kind == "skip":
        return f"{action.client}: skip: {action.message}"
    if action.kind == "refuse":
        return f"{action.client}: refuse: {action.message}"
    if action.kind == "note":
        return f"{action.client}: note: {action.message}"
    if action.kind == "none":
        return f"{action.client}: no legacy placement"
    return f"{action.client}: {action.kind}: {action.message}"


def direct_child(path: Path, root: Path) -> bool:
    """True when ``path`` is a file or directory directly inside ``root``.

    ``resolve`` is not used on ``path`` itself: a symlink's resolved path is the
    catalog or someone else's tree, and that must not become the thing we delete.
    """
    if path.name in ("", ".", ".."):
        return False
    try:
        return path.parent.resolve() == root.resolve()
    except OSError:
        return False


def remove_placement(path: Path, root: Path) -> None:
    if not direct_child(path, root):
        raise InstallError(f"refusing to remove {path}, which is not directly inside {root}", code=1)
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    raise InstallError(f"refusing to remove {path}", code=1)


# --- manifests ----------------------------------------------------------------


def link_manifest(path: Path, schema: str) -> dict:
    document = load_object(path)
    if document is None:
        if path.exists():
            raise InstallError(f"{path} exists and is not a JSON object; not rewriting it")
        return {"schema": schema, "links": []}
    links = document.get("links", [])
    if not isinstance(links, list):
        raise InstallError(f"{path} field links is not a list; not rewriting it")
    document["links"] = [item for item in links if isinstance(item, dict)]
    if "schema" not in document:
        document["schema"] = schema
    return document


def find_link(document: dict, link: str) -> dict | None:
    for item in document["links"]:
        if item.get("link") == link:
            return item
    return None


def record_link(document: dict, target: str, link: str) -> str:
    """``added``, ``present``, or ``blocked`` when an existing entry points elsewhere."""
    current = find_link(document, link)
    if current is None:
        document["links"].append({"target": target, "link": link})
        return "added"
    if current.get("target") == target:
        return "present"
    return "blocked"


def drop_link(document: dict, link: str) -> bool:
    kept = [item for item in document["links"] if item.get("link") != link]
    if len(kept) == len(document["links"]):
        return False
    document["links"] = kept
    return True


def agy_manifest(path: Path) -> dict:
    document = load_object(path)
    if document is None:
        if path.exists():
            raise InstallError(f"{path} exists and is not a JSON object; not rewriting it")
        return {"schema": AGY_SCHEMA, "packages": {}}
    packages = document.get("packages", {})
    if not isinstance(packages, dict):
        raise InstallError(f"{path} field packages is not an object; not rewriting it")
    document["packages"] = packages
    if "schema" not in document:
        document["schema"] = AGY_SCHEMA
    return document


# --- install planning ---------------------------------------------------------


def claude_registration(home: Path, name: str) -> dict | None:
    """The marketplace entry, if one exists. ``known_marketplaces.json`` wins over settings."""
    known_path = home / ".claude" / "plugins" / "known_marketplaces.json"
    known = load_object(known_path) or {}
    entry = known.get(name)
    if isinstance(entry, dict):
        return entry
    settings = load_object(home / ".claude" / "settings.json") or {}
    extra = settings.get("extraKnownMarketplaces") or {}
    if isinstance(extra, dict) and isinstance(extra.get(name), dict):
        return extra[name]
    return None


def registration_directory(entry: dict) -> str | None:
    source = entry.get("source")
    if isinstance(source, dict) and source.get("source") == "directory":
        path = source.get("path")
        if isinstance(path, str):
            return path
    return None


def registration_summary(entry: dict) -> str:
    source = entry.get("source")
    if not isinstance(source, dict):
        return "unreadable source"
    kind = source.get("source")
    if kind == "directory" and isinstance(source.get("path"), str):
        return source["path"]
    if isinstance(source.get("url"), str):
        return source["url"]
    if isinstance(source.get("repo"), str):
        return str(source["repo"])
    return str(kind or "unknown source")


def plan_claude(
    packages: list[Package],
    catalog: Path,
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    actions: list[Action] = []
    name = marketplace_name(catalog)
    listed = marketplace_plugin_names(catalog)
    entry = claude_registration(home, name)
    if entry is None:
        actions.append(
            command_action(
                "claude",
                ("plugin", "marketplace", "add", str(catalog.resolve())),
                overrides,
                required=required,
            )
        )
    else:
        recorded = registration_directory(entry)
        registered_here = (
            recorded is not None and Path(recorded).resolve() == catalog.resolve()
        )
        if registered_here:
            actions.append(
                Action(
                    "skip",
                    "claude",
                    message=f"marketplace {name} already registered at {recorded}",
                )
            )
        else:
            actions.append(
                Action(
                    "note",
                    "claude",
                    message=(
                        f"marketplace {name} already registered ({registration_summary(entry)}); "
                        f"not adding a second entry and not retargeting it at {catalog.resolve()}"
                    ),
                )
            )
    for package in packages:
        if package.name not in listed:
            actions.append(
                Action(
                    "skip",
                    "claude",
                    message=f"{package.name} is not listed in .claude-plugin/marketplace.json",
                )
            )
            continue
        actions.append(
            command_action(
                "claude",
                ("plugin", "install", f"{package.name}@{name}"),
                overrides,
                required=required,
            )
        )
    return actions


def plan_codex_install() -> list[Action]:
    return [Action("unsupported", "codex", message=CODEX_UNSUPPORTED)]


def cursor_cache(home: Path, repo_dir: str) -> Path:
    return home / ".cursor" / "plugins" / "marketplaces" / "github.com" / "infiquetra" / repo_dir


def cursor_has_manifest(root: Path) -> bool:
    if not root.is_dir():
        return False
    if (root / ".claude-plugin" / "marketplace.json").is_file():
        return True
    for child in root.iterdir():
        if child.is_dir() and (child / ".claude-plugin" / "marketplace.json").is_file():
            return True
    return False


def plan_cursor(
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    cache = cursor_cache(home, "infiquetra-agent-plugins")
    if cursor_has_manifest(cache):
        return [
            Action(
                "skip",
                "cursor",
                message=f"marketplace cache already has a manifest under {cache}",
            )
        ]
    return [
        command_action(
            "cursor",
            ("plugin", "marketplace", "add", CATALOG_GIT_URL),
            overrides,
            required=required,
        )
    ]


def plan_qwen(
    packages: list[Package],
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    """``extensions install`` asks on stdin and, with no answer, exits without installing."""
    actions: list[Action] = []
    for package in packages:
        actions.append(
            command_action(
                "qwen",
                ("extensions", "install", str(package.root)),
                overrides,
                required=required,
                stdin="y\n",
            )
        )
        record = home / ".qwen" / "extensions" / package.name / ".qwen-extension-install.json"
        actions.append(
            Action("merge-qwen", "qwen", path=str(record), target=str(package.root), message=package.name)
        )
    return actions


def plan_grok(
    packages: list[Package],
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    return [
        command_action(
            "grok",
            ("plugin", "install", str(package.root), "--trust"),
            overrides,
            required=required,
        )
        for package in packages
    ]


def plan_agy(
    packages: list[Package],
    catalog: Path,
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    """Install the package directory, unless a copy we did not record is already there.

    Agy drops the package at ``~/.gemini/config/plugins/<name>/`` and does not
    record where it came from. Several of those directories on a real machine
    belong to the Antigravity marketplace, which uses the same folder and is
    not this catalog. Replacing an unsourced directory would delete that copy.
    """
    actions: list[Action] = []
    plugins_root = home / ".gemini" / "config" / "plugins"
    manifest = plugins_root / ".infiquetra-install.json"
    document = agy_manifest(manifest) if manifest.is_file() else {"packages": {}}
    recorded_packages = document.get("packages") if isinstance(document.get("packages"), dict) else {}
    for package in packages:
        recorded = recorded_packages.get(package.name)
        source = recorded.get("source") if isinstance(recorded, dict) else ""
        if not isinstance(source, str):
            source = ""
        directory = plugins_root / package.name
        if directory.exists() and not is_catalog_source(source, catalog):
            if is_dedicated_source(source):
                message = f"{directory} records {source}, a dedicated repository"
            elif source:
                message = f"{directory} already records {source}"
            else:
                message = (
                    f"{directory} exists and has no source manifest; not replacing an unsourced copy"
                )
            actions.append(Action("skip", "agy", message=message))
            continue
        actions.append(
            command_action(
                "agy",
                ("plugin", "install", str(package.root)),
                overrides,
                required=required,
            )
        )
        actions.append(
            Action(
                "merge-agy",
                "agy",
                path=str(manifest),
                target=str(package.root),
                message=package.name,
            )
        )
    return actions


def skill_destinations(client: str, home: Path) -> tuple[Path, Path, str]:
    """``(skills directory, manifest path, schema)`` for one skill-scoped client."""
    if client == "opencode":
        root = home / ".config" / "opencode"
        return root / "skills", root / ".infiquetra-plugins.json", OPENCODE_SCHEMA
    if client == "hermes":
        root = home / ".hermes"
        return root / "skills", root / ".infiquetra-skills.json", HERMES_SCHEMA
    if client == "muse":
        root = home / ".config" / "muse"
        return root / "skills", root / ".infiquetra-skills.json", MUSE_SCHEMA
    if client == "gemini":
        root = home / ".gemini"
        return root / "skills", root / ".infiquetra-skills.json", GEMINI_SCHEMA
    raise InstallError(f"{client} is not skill-scoped")  # pragma: no cover


def existing_link_blocks(dest: Path, target: Path) -> str | None:
    """A destination we must not replace. None when we may create or keep the link."""
    if dest.is_symlink():
        try:
            if dest.resolve() == target.resolve():
                return None
        except OSError:
            return f"{dest} is a broken symlink"
        return f"{dest} already points at {dest.readlink()}"
    if dest.exists():
        return f"{dest} exists and is not a symlink to {target}"
    return None


def plan_symlink_client(client: str, packages: list[Package], home: Path) -> list[Action]:
    skills_root, manifest_path, schema = skill_destinations(client, home)
    document = link_manifest(manifest_path, schema)
    actions: list[Action] = []
    for package in packages:
        if not package.skills:
            actions.append(Action("skip", client, message=f"{package.name} has no skill units"))
            continue
        for skill in package.skills:
            dest = skills_root / skill.name
            target = skill.resolve()
            blocked = existing_link_blocks(dest, target)
            if blocked:
                actions.append(Action("skip", client, message=blocked))
                continue
            if not _resolves_to(dest, target):
                actions.append(Action("symlink", client, path=str(dest), target=str(target)))
            state = record_link(document, str(target), str(dest))
            if state == "blocked":
                current = find_link(document, str(dest))
                recorded = current.get("target") if current else "something else"
                actions.append(
                    Action(
                        "skip",
                        client,
                        message=f"manifest already records {dest} -> {recorded}",
                    )
                )
                continue
            if state == "added":
                actions.append(
                    Action(
                        "merge-link",
                        client,
                        path=str(manifest_path),
                        target=str(target),
                        message=str(dest),
                        schema=schema,
                    )
                )
    return actions


def plan_command_skills(
    client: str,
    argv_for_skill,
    packages: list[Package],
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
    stdin: str | None = None,
) -> list[Action]:
    skills_root, manifest_path, schema = skill_destinations(client, home)
    document = link_manifest(manifest_path, schema)
    actions: list[Action] = []
    for package in packages:
        if not package.skills:
            actions.append(Action("skip", client, message=f"{package.name} has no skill units"))
            continue
        for skill in package.skills:
            dest = skills_root / skill.name
            target = skill.resolve()
            recorded = find_link(document, str(dest))
            if recorded is not None and recorded.get("target") != str(target):
                actions.append(
                    Action(
                        "skip",
                        client,
                        message=f"manifest already records {dest} -> {recorded.get('target')}",
                    )
                )
                continue
            if recorded is not None and recorded.get("target") == str(target) and dest.exists():
                actions.append(Action("skip", client, message=f"{skill.name} already placed at {dest}"))
                continue
            # A directory left by an earlier install, or a link to somewhere else, is
            # not replaced. The client's command would copy over it.
            if dest.exists() and not _resolves_to(dest, target):
                actions.append(
                    Action(
                        "skip",
                        client,
                        message=f"{dest} exists without a manifest entry for {target}",
                    )
                )
                continue
            actions.append(
                command_action(
                    client,
                    argv_for_skill(str(target)),
                    overrides,
                    required=required,
                    stdin=stdin,
                )
            )
            state = record_link(document, str(target), str(dest))
            if state == "added":
                actions.append(
                    Action(
                        "merge-link",
                        client,
                        path=str(manifest_path),
                        target=str(target),
                        message=str(dest),
                        schema=schema,
                    )
                )
    return actions


def _resolves_to(dest: Path, target: Path) -> bool:
    try:
        return dest.resolve() == target.resolve()
    except OSError:
        return False


def plan_gemini(packages, home, overrides, *, required: bool) -> list[Action]:
    # The matrix supplied ``y`` on stdin. Closed stdin hangs this command instead of declining.
    return plan_command_skills(
        "gemini",
        lambda target: ("skills", "link", target),
        packages,
        home,
        overrides,
        required=required,
        stdin="y\n",
    )


def plan_muse(packages, home, overrides, *, required: bool) -> list[Action]:
    return plan_command_skills(
        "muse",
        lambda target: ("skills", "install", target, "--scope", "user"),
        packages,
        home,
        overrides,
        required=required,
    )


def plan_install(
    client: str,
    packages: list[Package],
    catalog: Path,
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    if client == "claude":
        return plan_claude(packages, catalog, home, overrides, required=required)
    if client == "codex":
        return plan_codex_install()
    if client == "cursor":
        return plan_cursor(home, overrides, required=required)
    if client == "qwen":
        return plan_qwen(packages, home, overrides, required=required)
    if client == "grok":
        return plan_grok(packages, overrides, required=required)
    if client == "opencode":
        return plan_symlink_client("opencode", packages, home)
    if client == "hermes":
        return plan_symlink_client("hermes", packages, home)
    if client == "gemini":
        return plan_gemini(packages, home, overrides, required=required)
    if client == "muse":
        return plan_muse(packages, home, overrides, required=required)
    if client == "agy":
        return plan_agy(packages, catalog, home, overrides, required=required)
    raise InstallError(f"unknown client {client}")  # pragma: no cover


# --- uninstall ----------------------------------------------------------------


def toml_marketplaces(path: Path) -> list[tuple[str, str]]:
    """``(table name, source)`` for ``[marketplaces.*]`` tables with a string ``source``.

    The Codex config this reads is a flat table. Values that are not a single
    quoted string are ignored rather than half-parsed.
    """
    if not path.is_file():
        return []
    found: list[tuple[str, str]] = []
    current: str | None = None
    source: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            if current is not None and source is not None:
                found.append((current, source))
            source = None
            header = line[1:-1].strip()
            if header.startswith("marketplaces."):
                current = header.split(".", 1)[1].strip().strip('"')
            else:
                current = None
            continue
        if current is None or not line.startswith("source ") and not line.startswith("source="):
            continue
        _, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            source = value[1:-1]
    if current is not None and source is not None:
        found.append((current, source))
    return found


def plan_codex_uninstall(home: Path, overrides: dict[str, str], *, required: bool) -> list[Action]:
    actions: list[Action] = []
    legacy = False
    for name, source in toml_marketplaces(home / ".codex" / "config.toml"):
        if is_dedicated_source(source) or is_dedicated_source(name):
            actions.append(
                Action(
                    "skip",
                    "codex",
                    message=f"marketplace {name} records {source}, a dedicated repository",
                )
            )
            continue
        if is_legacy_source(source):
            legacy = True
            actions.append(
                command_action(
                    "codex",
                    ("plugin", "marketplace", "remove", name),
                    overrides,
                    required=required,
                )
            )
    if not legacy:
        actions.append(Action("none", "codex"))
    return actions


def claude_source_url(entry: dict) -> str:
    source = entry.get("source")
    if not isinstance(source, dict):
        return ""
    for key in ("url", "repo", "path"):
        value = source.get(key)
        if isinstance(value, str):
            return value
    return ""


def plan_claude_uninstall(
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    actions: list[Action] = []
    known = load_object(home / ".claude" / "plugins" / "known_marketplaces.json") or {}
    entry = known.get(LEGACY_MARKETPLACE)
    if not isinstance(entry, dict):
        actions.append(Action("none", "claude"))
        return actions
    source = claude_source_url(entry)
    if is_dedicated_source(source):
        actions.append(
            Action(
                "skip",
                "claude",
                message=f"marketplace {LEGACY_MARKETPLACE} records {source}, a dedicated repository",
            )
        )
        actions.append(Action("none", "claude"))
        return actions
    if not is_legacy_source(source):
        actions.append(
            Action(
                "refuse",
                "claude",
                message=(
                    f"marketplace {LEGACY_MARKETPLACE} is registered but its source {source!r} "
                    "is not the infiquetra-claude-plugins git URL"
                ),
            )
        )
        return actions
    installed = load_object(home / ".claude" / "plugins" / "installed_plugins.json") or {}
    plugins = installed.get("plugins") if isinstance(installed.get("plugins"), dict) else {}
    names = sorted(key for key in plugins if key.endswith(f"@{LEGACY_MARKETPLACE}"))
    for plugin_id in names:
        actions.append(
            command_action(
                "claude",
                ("plugin", "uninstall", plugin_id),
                overrides,
                required=required,
            )
        )
    actions.append(
        command_action(
            "claude",
            ("plugin", "marketplace", "remove", LEGACY_MARKETPLACE),
            overrides,
            required=required,
        )
    )
    return actions


def plan_cursor_uninstall(home: Path, overrides: dict[str, str], *, required: bool) -> list[Action]:
    legacy = cursor_cache(home, LEGACY_DIR)
    if not cursor_has_manifest(legacy):
        return [Action("none", "cursor")]
    return [
        command_action(
            "cursor",
            ("plugin", "marketplace", "remove", LEGACY_GIT_URL),
            overrides,
            required=required,
        )
    ]


def plan_qwen_uninstall(
    packages: list[Package],
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    actions: list[Action] = []
    extensions = home / ".qwen" / "extensions"
    seen = False
    names = {package.name for package in packages}
    candidates: list[Path] = []
    if extensions.is_dir():
        for child in sorted(path for path in extensions.iterdir() if path.is_dir()):
            record = child / ".qwen-extension-install.json"
            document = load_object(record) if record.is_file() else None
            source = ""
            if isinstance(document, dict) and isinstance(document.get("source"), str):
                source = document["source"]
            if is_legacy_source(source):
                candidates.append(child)
                continue
            if child.name in names and child.exists() and not source:
                actions.append(
                    Action(
                        "refuse",
                        "qwen",
                        message=f"{child} has no install record; not deleting an unsourced copy",
                    )
                )
    for child in candidates:
        seen = True
        record = load_object(child / ".qwen-extension-install.json") or {}
        plugin_name = record.get("pluginName") if isinstance(record.get("pluginName"), str) else child.name
        actions.append(
            command_action(
                "qwen",
                ("extensions", "uninstall", str(plugin_name)),
                overrides,
                required=required,
            )
        )
    if not seen and not any(action.kind == "refuse" for action in actions):
        actions.append(Action("none", "qwen"))
    return actions


def grok_entries(home: Path) -> list[tuple[str, str, list[str]]]:
    """``(repo id, source, plugin names)`` from the Grok install registry."""
    document = load_object(home / ".grok" / "installed-plugins" / "registry.json")
    if not document:
        return []
    repos = document.get("repos")
    if not isinstance(repos, dict):
        return []
    found = []
    for repo_id, entry in repos.items():
        if not isinstance(entry, dict):
            continue
        marketplace = entry.get("marketplace") if isinstance(entry.get("marketplace"), dict) else {}
        source = marketplace.get("source_url_or_path")
        if not isinstance(source, str):
            kind = entry.get("kind") if isinstance(entry.get("kind"), dict) else {}
            source = kind.get("source_path") if isinstance(kind.get("source_path"), str) else ""
        plugins = entry.get("plugins") if isinstance(entry.get("plugins"), dict) else {}
        names = [name for name in plugins if isinstance(name, str)]
        found.append((str(repo_id), source, names))
    return found


def plan_grok_uninstall(home: Path, overrides: dict[str, str], *, required: bool) -> list[Action]:
    actions: list[Action] = []
    removed: set[str] = set()
    for _repo_id, source, names in grok_entries(home):
        if is_dedicated_source(source):
            actions.append(
                Action("skip", "grok", message=f"source {source} is a dedicated repository")
            )
            continue
        if not is_legacy_source(source):
            continue
        for name in names:
            if name in removed:
                continue
            removed.add(name)
            actions.append(
                command_action(
                    "grok",
                    ("plugin", "uninstall", name, "--confirm"),
                    overrides,
                    required=required,
                )
            )
    if not removed and not actions:
        actions.append(Action("none", "grok"))
    elif not removed:
        actions.append(Action("none", "grok"))
    return actions


def plan_agy_uninstall(
    packages: list[Package],
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    actions: list[Action] = []
    plugins_root = home / ".gemini" / "config" / "plugins"
    known = load_object(plugins_root / "known_marketplaces.json") or {}
    for name, entry in sorted(known.items()):
        if not isinstance(entry, dict):
            continue
        source = entry.get("repo") or entry.get("url") or ""
        if not isinstance(source, str):
            source = ""
        nested = entry.get("source")
        if isinstance(nested, dict):
            source = str(nested.get("repo") or nested.get("url") or source)
        if is_dedicated_source(source) or is_dedicated_source(name):
            actions.append(
                Action(
                    "skip",
                    "agy",
                    message=f"marketplace {name} records {source or name}, a dedicated repository",
                )
            )
    manifest_path = plugins_root / ".infiquetra-install.json"
    document = agy_manifest(manifest_path) if manifest_path.is_file() else {"packages": {}}
    packages_field = document.get("packages") if isinstance(document.get("packages"), dict) else {}
    removed = False
    for package in packages:
        recorded = packages_field.get(package.name)
        source = ""
        if isinstance(recorded, dict) and isinstance(recorded.get("source"), str):
            source = recorded["source"]
        directory = plugins_root / package.name
        if is_dedicated_source(source):
            actions.append(Action("skip", "agy", message=f"{package.name} records {source}"))
            continue
        if is_legacy_source(source):
            removed = True
            actions.append(
                command_action(
                    "agy",
                    ("plugin", "uninstall", package.name),
                    overrides,
                    required=required,
                )
            )
            actions.append(Action("drop-agy", "agy", path=str(manifest_path), message=package.name))
            continue
        if directory.exists() and not source:
            actions.append(
                Action(
                    "refuse",
                    "agy",
                    message=f"{directory} has no source manifest; not deleting an unsourced copy",
                )
            )
    if not removed and not any(action.kind in {"refuse", "skip"} for action in actions):
        actions.append(Action("none", "agy"))
    elif not removed and not any(action.kind == "none" for action in actions):
        if not any(action.kind == "refuse" for action in actions):
            actions.append(Action("none", "agy"))
    return actions


def plan_skill_uninstall(
    client: str,
    packages: list[Package],
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
    uninstall_argv,
) -> list[Action]:
    skills_root, manifest_path, schema = skill_destinations(client, home)
    document = link_manifest(manifest_path, schema) if manifest_path.is_file() else {"links": []}
    actions: list[Action] = []
    legacy_links = []
    for item in document.get("links", []):
        if not isinstance(item, dict):
            continue
        target = item.get("target") if isinstance(item.get("target"), str) else ""
        link = item.get("link") if isinstance(item.get("link"), str) else ""
        if is_dedicated_source(target) or is_dedicated_source(link):
            actions.append(
                Action("skip", client, message=f"{link or target} records a dedicated repository")
            )
            continue
        if is_legacy_source(target):
            legacy_links.append((target, link))
    our_names = {skill.name for package in packages for skill in package.skills}
    for target, link in legacy_links:
        if uninstall_argv is not None and link:
            skill_name = Path(link).name
            actions.append(
                command_action(client, uninstall_argv(skill_name), overrides, required=required)
            )
        if link:
            actions.append(Action("remove", client, path=link, target=str(skills_root)))
            actions.append(
                Action("drop-link", client, path=str(manifest_path), message=link, schema=schema)
            )
    for name in sorted(our_names):
        dest = skills_root / name
        if not dest.exists() and not dest.is_symlink():
            continue
        covered = any(isinstance(item, dict) and item.get("link") == str(dest) for item in document.get("links", []))
        if covered:
            continue
        actions.append(
            Action(
                "refuse",
                client,
                message=f"{dest} has no manifest entry; not deleting an unsourced copy",
            )
        )
    if not legacy_links and not any(action.kind == "refuse" for action in actions):
        actions.append(Action("none", client))
    return actions


def plan_uninstall(
    client: str,
    packages: list[Package],
    home: Path,
    overrides: dict[str, str],
    *,
    required: bool,
) -> list[Action]:
    if client == "claude":
        return plan_claude_uninstall(home, overrides, required=required)
    if client == "codex":
        return plan_codex_uninstall(home, overrides, required=required)
    if client == "cursor":
        return plan_cursor_uninstall(home, overrides, required=required)
    if client == "qwen":
        return plan_qwen_uninstall(packages, home, overrides, required=required)
    if client == "grok":
        return plan_grok_uninstall(home, overrides, required=required)
    if client == "agy":
        return plan_agy_uninstall(packages, home, overrides, required=required)
    if client == "opencode":
        return plan_skill_uninstall(
            "opencode", packages, home, overrides, required=required, uninstall_argv=None
        )
    if client == "hermes":
        return plan_skill_uninstall(
            "hermes", packages, home, overrides, required=required, uninstall_argv=None
        )
    if client == "gemini":
        return plan_skill_uninstall(
            "gemini",
            packages,
            home,
            overrides,
            required=required,
            uninstall_argv=lambda name: ("skills", "uninstall", name),
        )
    if client == "muse":
        return plan_skill_uninstall(
            "muse",
            packages,
            home,
            overrides,
            required=required,
            uninstall_argv=lambda name: ("skills", "uninstall", name),
        )
    raise InstallError(f"unknown client {client}")  # pragma: no cover


# --- check --------------------------------------------------------------------


def format_readback(row: Readback) -> str:
    if row.status == "installed-from-elsewhere":
        return f"{row.client} {row.package} installed-from-elsewhere ({row.source})"
    return f"{row.client} {row.package} {row.status}"


def rollup_skills(client: str, package: Package, results: list[tuple[str, str]]) -> Readback:
    if not package.skills or not results:
        return Readback(client, package.name, "absent")
    if any(status == "absent" for status, _source in results):
        return Readback(client, package.name, "absent")
    if all(status == "installed-from-catalog" for status, _source in results):
        return Readback(client, package.name, "installed-from-catalog")
    source = next(source for status, source in results if status != "installed-from-catalog")
    return Readback(client, package.name, "installed-from-elsewhere", source or "unsourced")


def classify_dest(dest: Path, target: Path, recorded: str | None, catalog: Path) -> tuple[str, str]:
    if dest.is_symlink():
        try:
            if dest.resolve() == target.resolve():
                return "installed-from-catalog", ""
        except OSError:
            return "installed-from-elsewhere", "broken-symlink"
        return "installed-from-elsewhere", str(dest.readlink())
    if dest.exists():
        if recorded and (is_catalog_source(recorded, catalog) or Path(recorded).resolve() == target.resolve()):
            return "installed-from-catalog", ""
        if recorded:
            return "installed-from-elsewhere", recorded
        return "installed-from-elsewhere", "unsourced"
    return "absent", ""


def recorded_target(manifest_path: Path, link: Path) -> str | None:
    if not manifest_path.is_file():
        return None
    document = load_object(manifest_path) or {}
    links = document.get("links")
    if not isinstance(links, list):
        return None
    for item in links:
        if isinstance(item, dict) and item.get("link") == str(link) and isinstance(item.get("target"), str):
            return item["target"]
    return None


def check_skill_client(client: str, packages: list[Package], home: Path, catalog: Path) -> list[Readback]:
    skills_root, manifest_path, _schema = skill_destinations(client, home)
    rows = []
    for package in packages:
        results = []
        for skill in package.skills:
            dest = skills_root / skill.name
            recorded = recorded_target(manifest_path, dest)
            results.append(classify_dest(dest, skill.resolve(), recorded, catalog))
        rows.append(rollup_skills(client, package, results))
    return rows


def check_claude(packages: list[Package], catalog: Path, home: Path) -> list[Readback]:
    name = marketplace_name(catalog)
    installed = load_object(home / ".claude" / "plugins" / "installed_plugins.json") or {}
    plugins = installed.get("plugins") if isinstance(installed.get("plugins"), dict) else {}
    settings = load_object(home / ".claude" / "settings.json") or {}
    enabled = settings.get("enabledPlugins") if isinstance(settings.get("enabledPlugins"), dict) else {}
    entry = claude_registration(home, name)
    directory = registration_directory(entry) if entry else None
    directory_matches = bool(directory) and Path(directory).resolve() == catalog.resolve()
    rows = []
    for package in packages:
        catalog_id = f"{package.name}@{name}"
        other_ids = sorted(
            key for key in plugins if key.startswith(f"{package.name}@") and key != catalog_id
        )
        has_catalog = catalog_id in plugins and bool(plugins.get(catalog_id))
        if has_catalog and directory_matches and enabled.get(catalog_id) is True:
            rows.append(Readback("claude", package.name, "installed-from-catalog"))
            continue
        if has_catalog and directory and not directory_matches:
            rows.append(Readback("claude", package.name, "installed-from-elsewhere", directory))
            continue
        if has_catalog and enabled.get(catalog_id) is not True:
            rows.append(
                Readback("claude", package.name, "installed-from-elsewhere", f"{catalog_id} disabled")
            )
            continue
        if other_ids:
            rows.append(Readback("claude", package.name, "installed-from-elsewhere", other_ids[0]))
            continue
        rows.append(Readback("claude", package.name, "absent"))
    return rows


def cached_plugin_names(root: Path) -> set[str]:
    names: set[str] = set()
    manifests = []
    direct = root / ".claude-plugin" / "marketplace.json"
    if direct.is_file():
        manifests.append(direct)
    if root.is_dir():
        for child in root.iterdir():
            candidate = child / ".claude-plugin" / "marketplace.json"
            if child.is_dir() and candidate.is_file():
                manifests.append(candidate)
    for manifest in manifests:
        document = load_object(manifest) or {}
        entries = document.get("plugins")
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and isinstance(entry.get("name"), str):
                names.add(entry["name"])
    return names


def check_cursor(packages: list[Package], home: Path) -> list[Readback]:
    catalog_names = cached_plugin_names(cursor_cache(home, "infiquetra-agent-plugins"))
    legacy_names = cached_plugin_names(cursor_cache(home, LEGACY_DIR))
    rows = []
    for package in packages:
        if package.name in catalog_names:
            rows.append(Readback("cursor", package.name, "installed-from-catalog"))
        elif package.name in legacy_names:
            rows.append(Readback("cursor", package.name, "installed-from-elsewhere", LEGACY_GIT_URL))
        else:
            rows.append(Readback("cursor", package.name, "absent"))
    return rows


def check_qwen(packages: list[Package], home: Path, catalog: Path) -> list[Readback]:
    rows = []
    for package in packages:
        record = home / ".qwen" / "extensions" / package.name / ".qwen-extension-install.json"
        directory = record.parent
        document = load_object(record) if record.is_file() else None
        source = ""
        if isinstance(document, dict) and isinstance(document.get("source"), str):
            source = document["source"]
        if source and is_catalog_source(source, catalog):
            rows.append(Readback("qwen", package.name, "installed-from-catalog"))
        elif source:
            rows.append(Readback("qwen", package.name, "installed-from-elsewhere", source))
        elif directory.is_dir():
            rows.append(Readback("qwen", package.name, "installed-from-elsewhere", "unsourced"))
        else:
            rows.append(Readback("qwen", package.name, "absent"))
    return rows


def check_grok(packages: list[Package], home: Path, catalog: Path) -> list[Readback]:
    rows = []
    entries = grok_entries(home)
    for package in packages:
        matches = [entry for entry in entries if package.name in entry[2]]
        catalog_match = [entry for entry in matches if is_catalog_source(entry[1], catalog)]
        if catalog_match:
            rows.append(Readback("grok", package.name, "installed-from-catalog"))
            continue
        elsewhere = [entry for entry in matches if entry[1]]
        if elsewhere:
            rows.append(Readback("grok", package.name, "installed-from-elsewhere", elsewhere[0][1]))
            continue
        if matches:
            rows.append(Readback("grok", package.name, "installed-from-elsewhere", "unsourced"))
            continue
        rows.append(Readback("grok", package.name, "absent"))
    return rows


def check_agy(packages: list[Package], home: Path, catalog: Path) -> list[Readback]:
    plugins_root = home / ".gemini" / "config" / "plugins"
    document = load_object(plugins_root / ".infiquetra-install.json") or {}
    recorded = document.get("packages") if isinstance(document.get("packages"), dict) else {}
    rows = []
    for package in packages:
        directory = plugins_root / package.name
        entry = recorded.get(package.name)
        source = entry.get("source") if isinstance(entry, dict) else ""
        if not isinstance(source, str):
            source = ""
        if directory.is_dir() and source and is_catalog_source(source, catalog):
            rows.append(Readback("agy", package.name, "installed-from-catalog"))
        elif source:
            rows.append(Readback("agy", package.name, "installed-from-elsewhere", source))
        elif directory.is_dir():
            rows.append(Readback("agy", package.name, "installed-from-elsewhere", "unsourced"))
        else:
            rows.append(Readback("agy", package.name, "absent"))
    return rows


def check_client(client: str, packages: list[Package], catalog: Path, home: Path) -> list[str]:
    if client == "codex":
        return [f"codex unsupported: {CODEX_UNSUPPORTED}"]
    if client == "claude":
        rows = check_claude(packages, catalog, home)
    elif client == "cursor":
        rows = check_cursor(packages, home)
    elif client == "qwen":
        rows = check_qwen(packages, home, catalog)
    elif client == "grok":
        rows = check_grok(packages, home, catalog)
    elif client == "agy":
        rows = check_agy(packages, home, catalog)
    elif client in SKILL_CLIENTS:
        rows = check_skill_client(client, packages, home, catalog)
    else:
        raise InstallError(f"unknown client {client}")  # pragma: no cover
    return [format_readback(row) for row in rows]


def absent_in(lines: list[str]) -> bool:
    return any(line.endswith(" absent") for line in lines)


# --- perform ------------------------------------------------------------------


def merge_qwen(action: Action) -> None:
    path = Path(action.path)
    document = load_object(path) if path.is_file() else None
    if document is None:
        document = {}
    document["source"] = action.target
    document["type"] = "local"
    document["pluginName"] = action.message
    write_json(path, document)


def merge_agy(action: Action) -> None:
    path = Path(action.path)
    document = agy_manifest(path)
    packages = document["packages"]
    current = packages.get(action.message)
    if isinstance(current, dict) and current.get("source") == action.target:
        return
    if isinstance(current, dict) and current.get("source") and current.get("source") != action.target:
        if is_dedicated_source(str(current.get("source"))):
            raise InstallError(
                f"agy manifest already records {action.message} from {current.get('source')}",
                code=1,
            )
    packages[action.message] = {"source": action.target}
    write_json(path, document)


def merge_link_action(action: Action) -> None:
    path = Path(action.path)
    document = link_manifest(path, action.schema)
    state = record_link(document, action.target, action.message)
    if state == "blocked":
        raise InstallError(
            f"{path} already records {action.message} with a different target",
            code=1,
        )
    if state == "added":
        write_json(path, document)


def drop_link_action(action: Action) -> None:
    path = Path(action.path)
    if not path.is_file():
        return
    document = link_manifest(path, action.schema or OPENCODE_SCHEMA)
    if drop_link(document, action.message):
        write_json(path, document)


def drop_agy_action(action: Action) -> None:
    path = Path(action.path)
    if not path.is_file():
        return
    document = agy_manifest(path)
    if action.message in document["packages"]:
        del document["packages"][action.message]
        write_json(path, document)


def perform(action: Action) -> None:
    if action.kind == "command":
        run_command(action)
        return
    if action.kind == "symlink":
        dest = Path(action.path)
        target = Path(action.target)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink() and _resolves_to(dest, target):
            return
        if dest.exists() or dest.is_symlink():
            raise InstallError(f"refusing to replace {dest}", code=1)
        os.symlink(str(target), str(dest))
        return
    if action.kind == "merge-qwen":
        merge_qwen(action)
        return
    if action.kind == "merge-agy":
        merge_agy(action)
        return
    if action.kind == "merge-link":
        merge_link_action(action)
        return
    if action.kind == "remove":
        remove_placement(Path(action.path), Path(action.target))
        return
    if action.kind == "drop-link":
        drop_link_action(action)
        return
    if action.kind == "drop-agy":
        drop_agy_action(action)
        return
    if action.kind in {"skip", "note", "refuse", "unsupported", "none", "write-json"}:
        return
    raise InstallError(f"unknown action {action.kind}", code=1)  # pragma: no cover


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    catalog = (args.catalog or default_catalog()).resolve()
    if not catalog.is_dir():
        raise InstallError(f"--catalog {catalog} is not a directory")
    packages = select_packages(catalog, args.package)
    clients = selected_clients(args.client)
    if any(client in SKILL_CLIENTS for client in clients):
        require_unique_skills(packages)
    overrides = parse_binaries(args.binary)
    home = Path.home()
    required = bool(args.execute) and not args.check
    lines: list[str] = []
    actions: list[Action] = []
    if args.check:
        for client in clients:
            lines.extend(check_client(client, packages, catalog, home))
        print("\n".join(lines))
        return 1 if absent_in(lines) else 0
    for client in clients:
        if args.uninstall_legacy:
            actions.extend(
                plan_uninstall(client, packages, home, overrides, required=required)
            )
        else:
            actions.extend(
                plan_install(client, packages, catalog, home, overrides, required=required)
            )
    for action in actions:
        print(format_action(action))
        if args.execute:
            perform(action)
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except InstallError as exc:
        print(f"install_client: {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
