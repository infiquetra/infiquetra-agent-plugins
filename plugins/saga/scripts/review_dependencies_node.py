#!/usr/bin/env python3
"""A JavaScript or TypeScript head's npm packages, installed once in prepare for an offline
reviewer, the way ``review_dependencies.py`` installs a Python head's wheels.

A head with a root ``package.json`` and a lockfile gets its packages installed from that lockfile
alone, by the manager the lockfile belongs to, with install scripts off, into
``<packet>/dependencies/node/node_modules``:

- ``npm-shrinkwrap.json`` or ``package-lock.json``: ``npm ci``;
- ``pnpm-lock.yaml``: ``pnpm install --frozen-lockfile``;
- ``yarn.lock`` (classic, version 1): ``yarn install --frozen-lockfile``;
- ``bun.lock``: ``bun install --frozen-lockfile``.

No lockfile is ever written. Before anything runs, saga reads the lockfile itself and refuses any
package that does not come from the public npm registry (a git, file, link or tarball source,
another registry), so a commit cannot point the install at an operator file or another host. The
install works on an export of the head with every manager configuration file removed (``.npmrc``,
``.yarnrc``, ``.yarnrc.yml``, ``.yarn/``, ``.pnpmfile.cjs``, ``bunfig.toml``), with a fresh
``HOME``, ``TMPDIR`` and cache, no operator variable beyond a short allow-list, corepack barred from
the network, and under the same byte and time watcher as the other installs.

Only the root ``node_modules`` is kept. Files are copied with fixed modes; a symlink is kept only
when it stays inside that folder (``.bin`` entries, pnpm's layout), and any other (a workspace
package's link) is dropped and counted. The managers' own state files are left out, so two
prepares of one head write the same bytes. Every reason recorded is a fixed word from
:data:`REASONS`, never a manager's output.

The reviewer's copy and finish's re-run copy each get a ``node_modules`` symlink at their root
pointing at the packet's folder, which they may read and never write. Node's CommonJS and ESM
resolvers both walk up from the importing file to the nearest ``node_modules``, and so do bun,
vitest and jest; ``NODE_PATH`` would reach CommonJS only.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import shutil
import stat
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import review_dependencies as D  # noqa: E402

KEY = "node"
DIRECTORY = "dependencies/node/node_modules"
#: One deadline for the whole install, as for Python.
TIMEOUT = 900
#: The fixed reasons a ``node`` entry records when it is ``not-installed``.
REASONS = frozenset({
    "no-lockfile", "binary-lockfile", "unsupported-lockfile", "non-registry-source",
    "symlinked-input", "lockfile-mismatch", "manager-missing", "network", "timeout",
    "size-limit", "install-failed", "head-export", "subfolder-project",
})
#: Lockfiles in the order one is chosen when a head has several, and the manager for each.
LOCKFILES = (
    ("npm-shrinkwrap.json", "npm"),
    ("package-lock.json", "npm"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("bun.lock", "bun"),
)
#: bun's older binary lockfile: saga cannot read it, so it cannot vet its sources.
BINARY_LOCKFILE = "bun.lockb"
#: Manager configuration a commit could use to change the registry, run code or read a token.
_CONFIG_FILES = (".npmrc", ".yarnrc", ".yarnrc.yml", ".pnpmfile.cjs", ".pnpmfile.mjs",
                 "bunfig.toml")
_CONFIG_FOLDERS = (".yarn",)
#: The only tarball hosts a lockfile may name: the public npm registry and its yarn mirror.
_REGISTRIES = ("https://registry.npmjs.org/", "https://registry.yarnpkg.com/")
_REGISTRY = "https://registry.npmjs.org/"
#: The managers' own state at the top of ``node_modules``: timestamps, store paths, checksums
#: of the install itself. Never copied into the packet.
_STATE_NAMES = frozenset({
    ".package-lock.json", ".modules.yaml", ".yarn-integrity", ".yarn-state.yml", ".cache",
    ".vite", ".vitest", ".pnpm-debug.log",
})
_STATE_PATTERN = re.compile(r"^\.pnpm-workspace-state.*\.json$")
_ENV_COPIED = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")
_NETWORK = re.compile(
    r"ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ETIMEDOUT|ConnectionRefused|"
    r"trouble with your network|network connection|getaddrinfo|socket hang up",
    re.IGNORECASE)
_MISMATCH = re.compile(
    r"can only install packages when your package\.json and|ERR_PNPM_OUTDATED_LOCKFILE|"
    r"lockfile needs to be updated|lockfile had changes, but lockfile is frozen|"
    r"Missing: .* from lock file|Invalid: lock file",
    re.IGNORECASE)
#: Commands whose re-run needs node's own install: the managers, and anything run from a
#: package's ``.bin`` (a ``#!/usr/bin/env node`` script).
JS_COMMANDS = frozenset({"node", "npm", "npx", "pnpm", "yarn", "bun", "bunx"})


class _Failure(Exception):
    def __init__(self, reason: str) -> None:
        assert reason in REASONS, reason
        super().__init__(reason)
        self.reason = reason


def entry(runner: D.Process, repo: Path, head: str, packet: Path,
          export: D.Export) -> dict[str, Any] | None:
    """The ``node`` entry for the head, or ``None`` when it holds no npm project at all."""
    root = D._tree(runner, repo, head)
    if "package.json" not in root:
        projects = _subfolder_projects(runner, repo, head)
        if projects is not None:
            return {"state": "not-installed", "reason": "subfolder-project", "projects": projects}
        return None
    chosen = next(((name, manager) for name, manager in LOCKFILES if name in root), None)
    if chosen is None:
        reason = "binary-lockfile" if BINARY_LOCKFILE in root else "no-lockfile"
        return {"state": "not-installed", "reason": reason}
    lockfile, manager = chosen
    if root["package.json"] == "120000" or root[lockfile] == "120000":
        return {"state": "not-installed", "reason": "symlinked-input"}
    return _install(runner, packet, export, lockfile, manager)


def node_modules(packet: Path) -> Path | None:
    """The packet's installed ``node_modules``, or ``None`` when there is none to trust: the
    entry must say ``installed`` and name a relative folder inside the packet that exists, with
    no symlink along the way."""
    return D._packet_directory(packet, KEY, frozenset({"installed"}))


def link_into(copy: Path, modules: Path) -> bool:
    """Give *copy* a ``node_modules`` symlink to *modules*, unless the copy already has a path by
    that name. Returns whether the link is there."""
    link = copy / "node_modules"
    if os.path.lexists(link):
        return False
    link.symlink_to(modules.resolve(), target_is_directory=True)
    return True


def node_bin(path: str) -> Path | None:
    """The folder that really holds the ``node`` found on *path*, when it is reached through a
    symlink (a version manager's shim, a link under home), so it can go first on a sandboxed
    command's ``PATH``. ``None`` when there is no node or it is not a link."""
    found = shutil.which("node", path=path)
    if not found:
        return None
    real = Path(os.path.realpath(found))
    return real.parent if real.parent != Path(found).parent else None


def toolchain_paths(path: str) -> tuple[Path, ...]:
    """What a re-run needs to start node and the managers beside it: the install that holds
    the real ``node`` (its ``bin`` and ``lib``), read-only. Empty when there is no node."""
    found = shutil.which("node", path=path)
    if not found:
        return ()
    real = Path(os.path.realpath(found))
    install = real.parent.parent if real.parent.name == "bin" else real.parent
    parts = [install / "bin", install / "lib"] if real.parent.name == "bin" else [real.parent]
    return tuple(part for part in parts if part.is_dir())


def needs_node(argv0: str) -> bool:
    """Whether a re-run of *argv0* needs node's install: a manager, or a package's script."""
    return Path(argv0).name in JS_COMMANDS or "node_modules/.bin/" in argv0


# --- install ------------------------------------------------------------------------------------


def _install(runner: D.Process, packet: Path, export: D.Export, lockfile: str,
             manager: str) -> dict[str, Any]:
    target = packet / DIRECTORY
    deadline = time.monotonic() + TIMEOUT
    with D._temporary("saga-review-node-") as work:
        source = work / "head"
        source.mkdir()
        try:
            if not export(source):
                raise _Failure("head-export")
            for name in ("package.json", lockfile):
                if (source / name).is_symlink() or not (source / name).is_file():
                    raise _Failure("symlinked-input")
            raw = (source / lockfile).read_bytes()
            problem = vet(lockfile, raw.decode("utf-8", "replace"))
            if problem is not None:
                raise _Failure(problem)
            _strip_configuration(source)
            found = shutil.which(manager, path=os.environ.get("PATH", ""))
            if found is None:
                raise _Failure("manager-missing")
            env = _environment(work)
            argv = [found, *_ARGUMENTS[manager](work)]
            _run(runner, argv, source, env, [source / "node_modules", work / "home", work / "tmp",
                                     work / "cache"], deadline)
            installed = source / "node_modules"
            if installed.is_symlink() or not installed.is_dir() or not _packages(installed):
                return {"state": "no-dependencies", "manager": manager, "lockfile": lockfile}
            dropped = _copy_modules(installed, target)
            record: dict[str, Any] = {
                "state": "installed",
                "directory": DIRECTORY,
                "manager": manager,
                "lockfile": lockfile,
                "packages": _packages(target),
                "lockfile_sha256": hashlib.sha256(raw).hexdigest(),
            }
            if dropped:
                record["dropped"] = {"links": dropped}
            return record
        except _Failure as exc:
            D._remove(target)
            return {"state": "not-installed", "reason": exc.reason}
        except OSError:
            D._remove(target)
            return {"state": "not-installed", "reason": "install-failed"}


def _strip_configuration(source: Path) -> None:
    """Remove every manager configuration file the commit carries, at any depth."""
    for folder, dirs, files in os.walk(source):
        for name in files:
            if name in _CONFIG_FILES:
                os.unlink(os.path.join(folder, name))
        for name in list(dirs):
            if name in _CONFIG_FOLDERS:
                shutil.rmtree(os.path.join(folder, name), ignore_errors=True)
                dirs.remove(name)
            elif name == "node_modules":
                dirs.remove(name)


def _environment(work: Path) -> dict[str, str]:
    """The allow-list, a fresh home, temp folder and cache, the public registry, scripts off,
    and corepack kept from the network and from rewriting ``package.json``."""
    env = {name: os.environ[name] for name in _ENV_COPIED if name in os.environ}
    for name, folder in (("HOME", "home"), ("TMPDIR", "tmp")):
        path = work / folder
        path.mkdir(mode=0o700)
        env[name] = str(path)
    cache = work / "cache"
    cache.mkdir(mode=0o700)
    home = Path.home()
    env.update({
        "npm_config_cache": str(cache),
        "npm_config_registry": _REGISTRY,
        "npm_config_userconfig": str(work / "home" / ".npmrc"),
        "npm_config_globalconfig": str(work / "home" / "npmrc"),
        "npm_config_ignore_scripts": "true",
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
        "npm_config_progress": "false",
        "YARN_CACHE_FOLDER": str(cache / "yarn"),
        "YARN_IGNORE_SCRIPTS": "true",
        "BUN_INSTALL_CACHE_DIR": str(cache / "bun"),
        # pnpm and yarn are often corepack shims: let them use a version already on disk, never
        # download one a commit names, and never write a ``packageManager`` field.
        "COREPACK_HOME": os.environ.get("COREPACK_HOME")
        or str(home / ".cache" / "node" / "corepack"),
        "COREPACK_ENABLE_NETWORK": "0",
        "COREPACK_ENABLE_AUTO_PIN": "0",
        "COREPACK_ENABLE_DOWNLOAD_PROMPT": "0",
    })
    return env


_ARGUMENTS: dict[str, Any] = {
    "npm": lambda work: ["ci", "--ignore-scripts", "--no-audit", "--no-fund"],
    "pnpm": lambda work: ["install", "--frozen-lockfile", "--ignore-scripts", "--ignore-pnpmfile",
                          "--reporter=silent", "--store-dir", str(work / "cache" / "pnpm")],
    "yarn": lambda work: ["install", "--frozen-lockfile", "--ignore-scripts", "--non-interactive",
                          "--no-progress", "--cache-folder", str(work / "cache" / "yarn")],
    "bun": lambda work: ["install", "--frozen-lockfile", "--ignore-scripts", "--no-progress",
                         "--no-save", "--cache-dir", str(work / "cache" / "bun")],
}


def _run(runner: D.Process, argv: list[str], cwd: Path, env: Mapping[str, str],
         watched: list[Path], deadline: float) -> None:
    seconds = min(D.FETCH_TIMEOUT, deadline - time.monotonic())
    if seconds <= 0:
        raise _Failure("timeout")
    try:
        D._watched(runner, argv, Path(argv[0]).name, cwd, env, watched, seconds=seconds,
                   missing="manager-missing", timed_out="timeout")
    except D.NotFetched as exc:
        message = str(exc)
        if message in ("manager-missing", "timeout"):
            raise _Failure(message) from None
        if "byte limit" in message:
            raise _Failure("size-limit") from None
        if _MISMATCH.search(exc.output):
            raise _Failure("lockfile-mismatch") from None
        if _NETWORK.search(exc.output):
            raise _Failure("network") from None
        raise _Failure("install-failed") from None


def _packages(modules: Path) -> int:
    """How many packages sit at the top of *modules*, a scope's members counted one by one."""
    count = 0
    for child in modules.iterdir():
        if child.name.startswith("."):
            continue
        if child.name.startswith("@") and child.is_dir() and not child.is_symlink():
            count += sum(1 for item in child.iterdir() if not item.name.startswith("."))
        else:
            count += 1
    return count


def _copy_modules(source: Path, target: Path) -> int:
    """Copy *source* into *target*: regular files with fixed modes, folders, and symlinks that
    stay inside *source*. Returns how many symlinks were dropped."""
    dropped = 0
    roots = {str(source), os.path.realpath(source)}
    target.mkdir(parents=True)
    for folder, dirs, files in os.walk(source):
        here = Path(folder)
        relative = here.relative_to(source)
        dirs.sort()
        files.sort()
        for name in list(dirs) + files:
            path = here / name
            rel = relative / name
            if relative == Path(".") and (name in _STATE_NAMES or _STATE_PATTERN.match(name)):
                if name in dirs:
                    dirs.remove(name)
                continue
            out = target / rel
            if path.is_symlink():
                if name in dirs:
                    dirs.remove(name)
                kept = _inside_link(roots, rel, os.readlink(path))
                if kept is None:
                    dropped += 1
                else:
                    os.symlink(kept, out)
                continue
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                out.mkdir()
            elif stat.S_ISREG(mode):
                shutil.copyfile(path, out, follow_symlinks=False)
                out.chmod(0o755 if mode & 0o111 else 0o644)
    return dropped


def _inside_link(roots: set[str], rel: Path, target: str) -> str | None:
    """The relative target to write for a symlink at *rel* (inside the copied folder) pointing
    at *target*, or ``None`` when it would leave the folder."""
    if "\0" in target:
        return None
    if os.path.isabs(target):
        for root in sorted(roots):
            prefix = root.rstrip("/") + "/"
            if target.startswith(prefix) and target != prefix:
                target = posixpath.relpath(target[len(prefix):], rel.parent.as_posix() or ".")
                break
        else:
            return None
    joined = posixpath.normpath(posixpath.join(rel.parent.as_posix(), target))
    if joined == ".." or joined.startswith("../") or posixpath.isabs(joined):
        return None
    return target


# --- vetting the lockfile -----------------------------------------------------------------------


def vet(lockfile: str, text: str) -> str | None:
    """``None`` when every package *text* names comes from the public npm registry, otherwise
    the fixed reason: ``unsupported-lockfile`` for a format saga does not read, and
    ``non-registry-source`` for a git, file, link, tarball or other-registry package."""
    if lockfile in ("package-lock.json", "npm-shrinkwrap.json"):
        return _vet_npm(text)
    if lockfile == "pnpm-lock.yaml":
        return _vet_pnpm(text)
    if lockfile == "yarn.lock":
        return _vet_yarn(text)
    if lockfile == "bun.lock":
        return _vet_bun(text)
    return "unsupported-lockfile"


_FOREIGN_SPEC = re.compile(r"^(?:file:|link:|git|github:|gitlab:|bitbucket:|https?:|npm:|/|\.)")


def _registry_url(url: Any) -> bool:
    return isinstance(url, str) and url.startswith(_REGISTRIES) and "/../" not in url


def _inside_head(base: str, relative: Any) -> bool:
    if not isinstance(relative, str) or not relative or "\0" in relative or "\\" in relative:
        return False
    if posixpath.isabs(relative):
        return False
    joined = posixpath.normpath(posixpath.join(base, relative))
    return not (joined == ".." or joined.startswith("../"))


def _vet_npm(text: str) -> str | None:
    try:
        data = json.loads(text)
    except ValueError:
        return "unsupported-lockfile"
    packages = data.get("packages") if isinstance(data, dict) else None
    if data.get("lockfileVersion") not in (2, 3) or not isinstance(packages, dict):
        return "unsupported-lockfile"
    for key, item in packages.items():
        if not isinstance(key, str) or not isinstance(item, dict):
            return "unsupported-lockfile"
        if key == "":
            continue
        if not _inside_head(".", key):
            return "non-registry-source"
        if item.get("link"):
            if not _inside_head(".", item.get("resolved")):
                return "non-registry-source"
            continue
        if "node_modules" not in key.split("/"):
            continue  # a workspace package's own folder in the head
        if item.get("inBundle"):
            continue
        version = item.get("version")
        if not isinstance(version, str) or _FOREIGN_SPEC.match(version):
            return "non-registry-source"
        resolved = item.get("resolved")
        if resolved is not None and not _registry_url(resolved):
            return "non-registry-source"
        if not isinstance(item.get("integrity"), str):
            return "non-registry-source"
    return None


def _vet_pnpm(text: str) -> str | None:
    version = re.search(r"^lockfileVersion:\s*'?([0-9.]+)'?\s*$", text, re.MULTILINE)
    if version is None or version.group(1).split(".")[0] not in ("6", "9"):
        return "unsupported-lockfile"
    section, importer = "", "."
    resolution_indent: int | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if indent == 0:
            section = stripped.rstrip(":")
            resolution_indent = None
            continue
        if resolution_indent is not None:
            if indent > resolution_indent:
                if not re.fullmatch(r"integrity:\s*\S+", stripped):
                    return "non-registry-source"
                continue
            resolution_indent = None
        if section == "importers" and indent == 2 and stripped.endswith(":"):
            importer = stripped[:-1].strip("'\"")
            if not _inside_head(".", importer):
                return "non-registry-source"
            continue
        if stripped.startswith("resolution:"):
            rest = stripped[len("resolution:"):].strip()
            if not rest:
                resolution_indent = indent
                continue
            if not re.fullmatch(r"\{\s*integrity:\s*[^,{}]+\}", rest):
                return "non-registry-source"
            continue
        value = stripped.split(":", 1)[1].strip().strip("'\"") if ":" in stripped else ""
        if value.startswith("link:"):
            if section != "importers" or not _inside_head(importer, value[len("link:"):]):
                return "non-registry-source"
        elif re.match(r"^(file:|git\+|github:|https?://)", value):
            return "non-registry-source"
    return None


def _vet_yarn(text: str) -> str | None:
    if "__metadata:" in text or "# yarn lockfile v1" not in text:
        return "unsupported-lockfile"
    for block in re.split(r"\n[ \t]*\n", text):
        lines = [line for line in block.splitlines() if line.strip() and not line.startswith("#")]
        if not lines:
            continue
        if lines[0].startswith((" ", "\t")):
            return "unsupported-lockfile"
        urls = [line.strip()[len("resolved "):].strip().strip('"') for line in lines[1:]
                if line.strip().startswith("resolved ")]
        if len(urls) != 1 or not _registry_url(urls[0]):
            return "non-registry-source"
    return None


def _vet_bun(text: str) -> str | None:
    try:
        data = json.loads(re.sub(r",(\s*[}\]])", r"\1", text))
    except ValueError:
        return "unsupported-lockfile"
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        return "unsupported-lockfile"
    for item in packages.values():
        if not isinstance(item, list) or not item or not isinstance(item[0], str):
            return "unsupported-lockfile"
        spec = item[0][1:].partition("@")[2] if item[0].startswith("@") else (
            item[0].partition("@")[2])
        if spec.startswith("workspace:"):
            if not _inside_head(".", spec[len("workspace:"):]):
                return "non-registry-source"
            continue
        if not spec or _FOREIGN_SPEC.match(spec) or ":" in spec or "/" in spec:
            return "non-registry-source"
        registry = item[1] if len(item) > 1 else ""
        if registry not in ("", _REGISTRY) and not _registry_url(registry):
            return "non-registry-source"
    return None


# --- below the root -----------------------------------------------------------------------------


def _subfolder_projects(runner: D.Process, repo: Path, head: str) -> list[str] | None:
    """Folders below the root that hold a ``package.json`` beside a lockfile, recorded the way
    the Python entry records them; ``None`` when there are none."""
    names = {name for name, _manager in LOCKFILES} | {BINARY_LOCKFILE}
    tree = D._tree(runner, repo, head, recursive=True)
    folders = set()
    for path in tree:
        folder, _sep, name = path.rpartition("/")
        if folder and name in names and f"{folder}/package.json" in tree and (
                "node_modules" not in folder.split("/")):
            folders.add(folder)
    if not folders:
        return None
    safe = sorted(folder for folder in folders if D._RECORDED_FOLDER.fullmatch(folder))
    return safe[:D._MAX_RECORDED_FOLDERS]
