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
from pathlib import Path, PurePosixPath
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
    # Like the Rust and Python toolchain folders: never home, a shared root or a credential path.
    return tuple(part for part in parts if part.is_dir() and D.read_problem(part) is None)


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
            problem = vet_manifests(source)
            if problem is not None:
                raise _Failure(problem)
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
            dropped += _prune_escaping_links(target)
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
            seal(target)
            return record
        except _Failure as exc:
            unseal(target)
            D._remove(target)
            return {"state": "not-installed", "reason": exc.reason}
        except OSError:
            unseal(target)
            D._remove(target)
            return {"state": "not-installed", "reason": "install-failed"}


def seal(tree: Path) -> None:
    """Make every file in *tree* 0444 (0555 when executable) and every folder 0555, without
    following links, so a write
    that reaches it outside the OS sandbox (a vendor's own file tools) is refused too."""
    if tree.is_symlink() or not tree.is_dir():
        return
    for folder, dirs, files in os.walk(tree, topdown=False):
        for name in files:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                # A package's scripts keep their execute bit: ``node_modules/.bin`` runs them.
                os.chmod(path, 0o555 if os.stat(path).st_mode & 0o111 else 0o444)
        for name in dirs:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                os.chmod(path, 0o555)
    os.chmod(tree, 0o555)


def unseal(tree: Path) -> None:
    """Give folders under *tree* back their owner's write permission, so it can be removed. Does
    nothing when there is no such folder; never follows a link."""
    if tree.is_symlink() or not tree.is_dir():
        return
    os.chmod(tree, 0o755)
    for folder, dirs, _files in os.walk(tree):
        for name in dirs:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                os.chmod(path, 0o755)


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


def _prune_escaping_links(target: Path) -> int:
    """Remove every link in *target* that, resolved one component at a time through the links
    inside *target*, would leave it. Returns how many were removed."""
    removed = 0
    for folder, dirs, files in os.walk(target):
        for name in sorted(dirs + files):
            path = Path(folder) / name
            if path.is_symlink() and not _resolves_inside(target, path.relative_to(target)):
                path.unlink()
                removed += 1
                if name in dirs:
                    dirs.remove(name)
    return removed


def _resolves_inside(root: Path, relative: Path, hops: int = 40) -> bool:
    """Whether *relative* (a path under *root*) resolves inside *root*. Each component that is a
    link inside *root* is replaced by its target; a ``..`` above *root*, an absolute target or
    too many hops is outside. Nothing outside *root* is ever looked at."""
    queue = list(PurePosixPath(relative.as_posix()).parts)
    current: list[str] = []
    while queue:
        part = queue.pop(0)
        if part in ("", "."):
            continue
        if part == "..":
            if not current:
                return False
            current.pop()
            continue
        candidate = root.joinpath(*current, part)
        if candidate.is_symlink():
            hops -= 1
            target = os.readlink(candidate)
            if hops < 0 or os.path.isabs(target) or "\0" in target:
                return False
            queue = list(PurePosixPath(target).parts) + queue
            continue
        current.append(part)
    return True


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
    """Every ``node_modules/...`` entry, the lockfile's own ``inBundle`` flag ignored (npm works
    bundling out for itself): a plain version, and either a public-registry ``resolved`` with an
    ``integrity``, or, for an entry that says it is bundled, no ``resolved`` at all."""
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
        version = item.get("version")
        if not isinstance(version, str) or not _PLAIN_VERSION.fullmatch(version):
            return "non-registry-source"
        resolved = item.get("resolved")
        if resolved is None and item.get("inBundle") is True:
            continue  # it arrives inside its parent's registry tarball
        if not _registry_url(resolved) or not _INTEGRITY.fullmatch(str(item.get("integrity"))):
            return "non-registry-source"
    return None


_PLAIN_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]*)?")
_INTEGRITY = re.compile(r"sha(?:1|256|384|512)-[A-Za-z0-9+/]+={0,2}")
#: A dependency range a manifest or a yarn.lock header may name: plain semver range syntax, or
#: an ``npm:`` alias of one. No URL, path, git or tag with a ``:`` or ``/``.
_RANGE = re.compile(r"[0-9A-Za-z.*^~<>=|+ \-]*")
_NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]*", re.IGNORECASE)


def _plain_spec(spec: str) -> bool:
    """Whether *spec* is a registry range: plain semver syntax, or ``npm:<name>@<range>``."""
    if spec.startswith("npm:"):
        name, at, rest = spec[4:].rpartition("@")
        if not at or not name:
            name, rest = spec[4:], ""
        return bool(_NAME.fullmatch(name)) and bool(_RANGE.fullmatch(rest))
    return bool(spec) and bool(_RANGE.fullmatch(spec))


def _split_key(key: str) -> tuple[str, str] | None:
    """``name@spec`` split at the ``@`` after the (possibly scoped) name."""
    at = key.find("@", 1)
    if at <= 0:
        return None
    name, spec = key[:at], key[at + 1:]
    return (name, spec) if _NAME.fullmatch(name) else None


def vet_manifests(source: Path) -> str | None:
    """Every ``package.json`` in the export, outside ``node_modules``: each dependency it names
    is a registry range, an ``npm:`` alias or a ``workspace:`` reference inside the head."""
    for folder, dirs, files in os.walk(source):
        dirs[:] = sorted(d for d in dirs if d != "node_modules")
        if "package.json" not in files:
            continue
        here = Path(folder).relative_to(source).as_posix()
        try:
            data = json.loads((Path(folder) / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "unsupported-lockfile"
        if not isinstance(data, dict):
            return "unsupported-lockfile"
        for field in ("dependencies", "devDependencies", "optionalDependencies",
                      "peerDependencies", "overrides", "resolutions"):
            table = data.get(field)
            if table is None:
                continue
            if not isinstance(table, dict):
                return "unsupported-lockfile"
            for spec in _leaf_specs(table):
                if spec == "catalog:" or re.fullmatch(r"catalog:[A-Za-z0-9._-]+", spec):
                    continue  # pnpm's catalogs: the lockfile records what each resolves to
                if spec.startswith("workspace:"):
                    rest = spec[len("workspace:"):]
                    if not (_RANGE.fullmatch(rest) or _inside_head(here, rest)):
                        return "non-registry-source"
                elif spec.startswith("$"):
                    continue  # an npm override naming a direct dependency's own range
                elif not _plain_spec(spec):
                    return "non-registry-source"
    return None


def _leaf_specs(table: Mapping[str, Any]) -> list[str]:
    found: list[str] = []
    for value in table.values():
        if isinstance(value, dict):
            found += _leaf_specs(value)
        else:
            found.append(value if isinstance(value, str) else "\0")
    return found


# yarn.lock, classic (version 1), read the way yarn reads it: an entry starts at every line with
# no indent, its fields are indented two spaces, and a dependency table's lines four.
_YARN_KEY = re.compile(r'"([^"\\]+)"|([^\s",:#][^\s",:#]*)')
_YARN_FIELD = re.compile(r'([A-Za-z]+) ("(?:[^"\\]*)"|[^\s"]+)')
_YARN_DEPENDENCY = re.compile(r'(?:"[^"\\]+"|[^\s"]+) "[^"\\]*"')
_YARN_TABLES = frozenset({"dependencies", "optionalDependencies"})
_YARN_FIELDS = frozenset({"version", "resolved", "integrity", "uid"})


def _vet_yarn(text: str) -> str | None:
    if not text.startswith("# ") or "# yarn lockfile v1" not in text.splitlines()[:3]:
        return "unsupported-lockfile"
    seen: set[str] = set()
    entry: dict[str, list[str]] | None = None
    table = False
    entries: list[dict[str, list[str]]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        if line.startswith("#"):
            if entry is not None:
                return "unsupported-lockfile"
            continue
        if "\t" in line or "\r" in line or "\\" in line:
            return "unsupported-lockfile"
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if indent == 0:
            if not body.endswith(":"):
                return "unsupported-lockfile"
            keys = _yarn_keys(body[:-1])
            if keys is None:
                return "unsupported-lockfile"
            for key in keys:
                if key in seen:
                    return "unsupported-lockfile"
                seen.add(key)
                parts = _split_key(key)
                if parts is None or not _plain_spec(parts[1]):
                    return "non-registry-source"
            entry, table = {}, False
            entries.append(entry)
        elif entry is None:
            return "unsupported-lockfile"
        elif indent == 2:
            if body.endswith(":") and body[:-1] in _YARN_TABLES:
                if body[:-1] in entry:
                    return "unsupported-lockfile"
                entry[body[:-1]] = []
                table = True
                continue
            match = _YARN_FIELD.fullmatch(body)
            if match is None or match.group(1) not in _YARN_FIELDS or match.group(1) in entry:
                return "unsupported-lockfile"
            entry[match.group(1)] = [match.group(2).strip('"')]
            table = False
        elif indent == 4 and table:
            if not _YARN_DEPENDENCY.fullmatch(body):
                return "unsupported-lockfile"
        else:
            return "unsupported-lockfile"
    for item in entries:
        resolved = item.get("resolved", [""])[0]
        integrity = item.get("integrity", [""])[0]
        if not _registry_url(resolved) or not _INTEGRITY.fullmatch(integrity):
            return "non-registry-source"
        if not _PLAIN_VERSION.fullmatch(item.get("version", [""])[0]):
            return "non-registry-source"
    return None


def _yarn_keys(header: str) -> list[str] | None:
    """The comma-separated keys of an entry header, each quoted with no escape or plain."""
    keys: list[str] = []
    position = 0
    while True:
        match = _YARN_KEY.match(header, position)
        if match is None:
            return None
        keys.append(match.group(1) or match.group(2))
        position = match.end()
        if position == len(header):
            return keys
        if header[position:position + 2] != ", ":
            return None
        position += 2


# pnpm-lock.yaml: a strict reader of the block YAML pnpm itself writes, failing closed on
# everything else (see the DECISIONS entry): plain or single-quoted keys and scalars, one-level
# flow mappings and sequences, ``- item`` lists. No anchors, aliases, tags, merge keys, explicit
# keys, block or multi-line scalars, documents, directives, comments or duplicate keys.
class _Unsupported(Exception):
    pass


_PNPM_QUOTED = re.compile(r"'(?:[^']|'')*'")
#: The first character of a plain scalar: never one YAML reserves for another construct.
_PNPM_PLAIN_START = re.compile(r"[^\s\-?:,\[\]{}#&*!|>'\"%@`]|[-?:][^\s,\[\]{}]")


def _pnpm_scalar(text: str, flow: bool = False) -> str:
    """A single-quoted, simple double-quoted or plain scalar; *flow* is inside ``{}`` or ``[]``,
    where a plain scalar may not hold ``,[]{}``."""
    text = text.strip()
    if _PNPM_QUOTED.fullmatch(text):
        return text[1:-1].replace("''", "'")
    if text.startswith('"'):
        if re.fullmatch(r'"[^"\\]*"', text):
            return text[1:-1]
        raise _Unsupported
    if (not text or not _PNPM_PLAIN_START.match(text) or ": " in text or " #" in text
            or text.endswith(":") or (flow and any(c in text for c in ",[]{}"))):
        raise _Unsupported
    return text


def _pnpm_flow(text: str) -> Any:
    """A one-level ``{k: v, ...}`` or ``[a, b]``, or a scalar."""
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        close = "}" if text[0] == "{" else "]"
        if not text.endswith(close):
            raise _Unsupported
        inner = text[1:-1].strip()
        items = [part for part in _split_flow(inner)] if inner else []
        if close == "]":
            return [_pnpm_scalar(item, flow=True) for item in items]
        mapping: dict[str, str] = {}
        for item in items:
            key, sep, value = item.partition(": ")
            key = _pnpm_scalar(key, flow=True)
            if not sep or key in mapping:
                raise _Unsupported
            mapping[key] = _pnpm_scalar(value, flow=True)
        return mapping
    return _pnpm_scalar(text)


def _split_flow(inner: str) -> list[str]:
    parts, current, quoted = [], "", False
    for char in inner:
        if char == "'":
            quoted = not quoted
        if char in "{}[]" and not quoted:
            raise _Unsupported  # one level only
        if char == "," and not quoted:
            parts.append(current)
            current = ""
        else:
            current += char
    if quoted:
        raise _Unsupported
    return [*parts, current]


def _pnpm_key(text: str) -> str:
    if text.startswith("? ") or text.startswith("<<") or text.startswith("&"):
        raise _Unsupported
    return _pnpm_scalar(text)


def _pnpm_parse(text: str) -> Any:
    """The subset of YAML pnpm writes, as dicts, lists and strings; :class:`_Unsupported` for
    anything outside it."""
    root: dict[str, Any] = {}
    #: (the indent this container's entries sit at, the container)
    stack: list[tuple[int, Any]] = [(0, root)]
    pending: tuple[dict[str, Any], str, int] | None = None
    for raw in text.split("\n"):
        if not raw.strip():
            continue
        if "\t" in raw or "\r" in raw or raw.lstrip().startswith(("#", "---", "...", "%")):
            raise _Unsupported
        indent = len(raw) - len(raw.lstrip(" "))
        body = raw.strip()
        if pending is not None:
            owner, key, key_indent = pending
            pending = None
            if indent > key_indent:
                child: Any = [] if body.startswith("- ") else {}
                owner[key] = child
                stack.append((indent, child))
            else:
                owner[key] = {}
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        level, container = stack[-1]
        if indent != level:
            raise _Unsupported  # a continuation line, or a level no key opened
        if isinstance(container, list):
            if not body.startswith("- "):
                raise _Unsupported
            container.append(_pnpm_flow(body[2:]))
            continue
        key_text, sep, value = _partition_key(body)
        if not sep:
            raise _Unsupported
        key = _pnpm_key(key_text)
        if key in container:
            raise _Unsupported
        if value.strip():
            container[key] = _pnpm_flow(value)
        else:
            container[key] = {}
            pending = (container, key, indent)
    return root


def _partition_key(body: str) -> tuple[str, str, str]:
    """``key: value`` or ``key:``, with a single-quoted key allowed to hold ``: ``."""
    if body.startswith("'"):
        match = _PNPM_QUOTED.match(body)
        if match is None:
            raise _Unsupported
        rest = body[match.end():]
        if rest == ":":
            return match.group(0), ":", ""
        if rest.startswith(": "):
            return match.group(0), ":", rest[2:]
        raise _Unsupported
    if body.endswith(":") and ": " not in body:
        return body[:-1], ":", ""
    key, sep, value = body.partition(": ")
    return key, (":" if sep else ""), value


_PNPM_TOP = frozenset({
    "lockfileVersion", "settings", "importers", "packages", "snapshots", "overrides",
    "dependencies", "devDependencies", "optionalDependencies", "catalogs",
    "patchedDependencies", "packageExtensionsChecksum", "pnpmfileChecksum",
    "ignoredOptionalDependencies", "time", "onlyBuiltDependencies", "neverBuiltDependencies",
})
_PNPM_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.+-]*)?(?:\(.*\))?")
_PNPM_IMPORTER_TABLES = ("dependencies", "devDependencies", "optionalDependencies")


def _vet_pnpm(text: str) -> str | None:
    try:
        data = _pnpm_parse(text)
    except (_Unsupported, RecursionError):
        return "unsupported-lockfile"
    version = data.get("lockfileVersion")
    if not isinstance(version, str) or version.split(".")[0] not in ("6", "9"):
        return "unsupported-lockfile"
    if set(data) - _PNPM_TOP:
        return "unsupported-lockfile"
    importers = data.get("importers") if "importers" in data else {".": {
        name: data[name] for name in _PNPM_IMPORTER_TABLES if name in data}}
    if not isinstance(importers, dict):
        return "unsupported-lockfile"
    for path, importer in importers.items():
        if not _inside_head(".", path) or not isinstance(importer, dict):
            return "non-registry-source"
        for table_name in _PNPM_IMPORTER_TABLES:
            table = importer.get(table_name) or {}
            if not isinstance(table, dict):
                return "unsupported-lockfile"
            for item in table.values():
                spec = item.get("version") if isinstance(item, dict) else item
                if not isinstance(spec, str):
                    return "unsupported-lockfile"
                if spec.startswith("link:"):
                    if not _inside_head(path, spec[len("link:"):]):
                        return "non-registry-source"
                elif not _pnpm_version(spec):
                    return "non-registry-source"
    packages = data.get("packages") or {}
    if not isinstance(packages, dict):
        return "unsupported-lockfile"
    for key, item in packages.items():
        if not isinstance(item, dict) or set(item.get("resolution") or {}) != {"integrity"} or (
                not isinstance(item.get("resolution"), dict)):
            return "non-registry-source"
        if not _INTEGRITY.fullmatch(item["resolution"]["integrity"]):
            return "non-registry-source"
        bare = key.lstrip("/")
        parts = _split_key(bare)
        if parts is None or not _PNPM_VERSION.fullmatch(parts[1]):
            return "non-registry-source"
    snapshots = data.get("snapshots") or {}
    if not isinstance(snapshots, dict):
        return "unsupported-lockfile"
    for key, item in snapshots.items():
        parts = _split_key(key)
        if parts is None or not _PNPM_VERSION.fullmatch(parts[1]):
            return "non-registry-source"
        for table_name in ("dependencies", "optionalDependencies"):
            table = (item or {}).get(table_name) if isinstance(item, dict) else None
            for spec in (table or {}).values():
                if not isinstance(spec, str) or not _pnpm_version(spec):
                    return "non-registry-source"
    patched = data.get("patchedDependencies") or {}
    for value in (patched.values() if isinstance(patched, dict) else [None]):
        path = value.get("path") if isinstance(value, dict) else value
        if not _inside_head(".", path):
            return "non-registry-source"
    return None


def _pnpm_version(spec: str) -> bool:
    """A resolved version, maybe with a peer suffix, or an alias ``name@version``."""
    if _PNPM_VERSION.fullmatch(spec.lstrip("/")):
        return True
    parts = _split_key(spec.lstrip("/"))
    return parts is not None and bool(_PNPM_VERSION.fullmatch(parts[1]))


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
