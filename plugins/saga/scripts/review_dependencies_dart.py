#!/usr/bin/env python3
"""A Dart head's pub packages, fetched once in prepare for an offline reviewer and re-run.

Prepare runs the operator's Dart SDK, ``dart pub get --enforce-lockfile``, on an export of the head
with ``PUB_CACHE`` inside the packet, a fresh ``HOME`` and ``TMPDIR``, telemetry off and no
operator variable beyond the allow-list, under the same watcher as cargo and uv. It never touches
the operator's own pub cache or checkout. The lock is checked first: only pub.dev packages and
paths inside the head are fetched; a git source, another host, or a Flutter SDK package is refused
with a fixed reason. The packet keeps only ``hosted/`` and ``hosted-hashes/``; what pub writes that
differs between runs (``active_roots/``, version listings, ``_temp/``) is removed.

``dart test`` cannot run against that cache as it is: pub's resolution step, which ``dart test``
runs first, records the project under ``PUB_CACHE/active_roots`` even when nothing is fetched, and
the packet is read-only. Version listings (``hosted/*/.cache``) are not kept either: they carry a
fetch time and change whenever a package is published. So the project is resolved first with
``dart pub get --offline --enforce-lockfile`` (finish does it; the reviewer is told to), and
``dart test`` runs with ``PUB_MAX_HTTP_RETRIES=0``. The reviewer and the re-run each get a
writable pub cache folder of their own whose ``hosted`` and ``hosted-hashes`` link to the packet's, and a ``bin`` holding only
``dart``, linked to the SDK's real executable (a Flutter install's ``bin/dart`` is a shell wrapper
that needs git and writes into the SDK). ``DASH__SUPPRESS_ANALYTICS`` keeps the Dart CLI from
opening its telemetry file under the home folder, which the sandbox makes unreadable.

``flutter test`` is not supported: the Flutter tool opens ``<flutter>/bin/cache/lockfile`` for
writing on every run, and the SDK is read-only to the sandbox.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import review_dependencies as deps

DIRECTORY = "dependencies/dart/pub-cache"
TIMEOUT = 600
#: Every reason a ``dart`` entry may record. uv's and pub's own words never reach the packet.
REASONS = frozenset({
    "no-lockfile", "flutter-unsupported", "unsupported-source", "lock-unreadable",
    "pubspec-unreadable",
    "lock-mismatch", "dart-missing", "fetch-failed", "network", "timeout", "size-limit",
    "symlinked-input", "subfolder-project", "head-export", "nothing-installed",
})
#: The reasons a later prepare of the same head may not repeat: the machine or the network.
TRANSIENT = frozenset({"dart-missing", "fetch-failed", "network", "timeout"})
#: Telemetry off: the Dart CLI otherwise opens ``~/.dart-tool/dart-flutter-telemetry.config``
#: first, and exits 255 when the home folder is unreadable.
ENV_FLAGS = {"DASH__SUPPRESS_ANALYTICS": "true"}
#: For the reviewer and the re-run, also no HTTP retry: ``dart test`` asks pub.dev for version
#: listings the packet does not keep, and with retries it waits out the whole time limit on the
#: denied network; without, the request fails at once and the test runs from the resolution.
RUN_FLAGS = {**ENV_FLAGS, "PUB_MAX_HTTP_RETRIES": "0"}
#: What resolves the project against the packet's packages without the network or the version
#: listings, writing ``.dart_tool/package_config.json``. ``dart test`` needs it first.
OFFLINE_GET = ("pub", "get", "--offline", "--enforce-lockfile")
_PUB_HOSTS = frozenset({"https://pub.dev", "https://pub.dartlang.org"})
_NETWORK = re.compile(r"socket error|SocketException|Failed host lookup|HandshakeException|"
                      r"Connection (?:refused|reset|closed)|timed out|network", re.IGNORECASE)
_LOCK_MISMATCH = re.compile(r"Unable to satisfy|would change|enforce-lockfile|"
                            r"does not satisfy|lockfile", re.IGNORECASE)
_PACKAGE_DIR = re.compile(r"[A-Za-z0-9_]+-[A-Za-z0-9.+_-]+")


@dataclass(frozen=True)
class DartDependencies:
    """A packet's pub cache and the SDK version that fetched it."""

    cache: Path
    version: str


@dataclass(frozen=True)
class DartSdk:
    """The SDK's real ``dart`` executable, its root, and its version."""

    executable: Path
    root: Path
    version: str


def dart_packages(packet: Path) -> DartDependencies | None:
    """The packet's pub cache, or ``None`` when there is none to trust.

    The entry counts when it says ``installed``, records the SDK version, and names a relative
    directory inside the packet with no symlink along the way.
    """
    cache = deps._packet_directory(packet, "dart", frozenset({"installed"}))
    if cache is None:
        return None
    try:
        version = str(json.loads((packet / deps.FILE).read_text(encoding="utf-8"))
                      ["dart"]["sdk"]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9.+-]*", version) is None:
        return None
    return DartDependencies(cache=cache, version=version)


def dart_sdk(path: str | None = None) -> DartSdk | None:
    """The Dart SDK the operator's ``PATH`` finds, by its real executable.

    A Flutter install's ``bin/dart`` is a shell wrapper; its SDK is ``bin/cache/dart-sdk``. Only a
    root holding a ``version`` file and a ``bin/dart`` that is not a script counts.
    """
    found = shutil.which("dart", path=os.environ.get("PATH", "") if path is None else path)
    if not found:
        return None
    real = Path(os.path.realpath(found))
    for root in (real.parent.parent, real.parent / "cache" / "dart-sdk"):
        executable = root / "bin" / "dart"
        version_file = root / "version"
        try:
            if not executable.is_file() or not version_file.is_file():
                continue
            with executable.open("rb") as handle:
                if handle.read(2) == b"#!":
                    continue
            version = version_file.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if re.fullmatch(r"\d+\.\d+\.\d+[A-Za-z0-9.+-]*", version):
            return DartSdk(executable=executable.resolve(), root=root.resolve(), version=version)
    return None


def same_release(found: str, recorded: str) -> bool:
    """True when two SDK versions share their major and minor number."""
    return found.split(".")[:2] == recorded.split(".")[:2]


def write_dart_shim(directory: Path, sdk: DartSdk) -> Path:
    """A folder saga writes whose ``bin`` holds only ``dart``, linked to *sdk*'s executable."""
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    (directory / "bin" / "dart").symlink_to(sdk.executable)
    return directory


def write_pub_cache(directory: Path, packages: DartDependencies) -> Path:
    """A writable pub cache whose ``hosted`` and ``hosted-hashes`` link to the packet's.

    pub writes ``active_roots`` here; a write through a link reaches the read-only packet and is
    refused.
    """
    if directory.is_symlink():
        raise OSError(f"{directory} is a link")
    directory.mkdir(parents=True, exist_ok=True)
    for part in ("hosted", "hosted-hashes"):
        source = packages.cache.resolve() / part
        if source.is_dir() and not os.path.lexists(directory / part):
            (directory / part).symlink_to(source)
    return directory


def dart_env(shim: Path, pub_cache: Path, path: str | None = None) -> dict[str, str]:
    """The shim's ``bin`` first on ``PATH``, the writable pub cache, telemetry and retries off."""
    rest = os.environ.get("PATH", "") if path is None else path
    return {
        "PATH": os.pathsep.join([str(shim / "bin"), *([rest] if rest else [])]),
        "PUB_CACHE": str(pub_cache),
        **RUN_FLAGS,
    }


def dart_toolchain(shim: Path, packages: DartDependencies, sdk: DartSdk) -> tuple[Path, ...]:
    """What a confined ``dart`` must read and map: the shim, the packet's cache and the SDK."""
    paths = (shim, packages.cache.resolve(), sdk.root)
    return tuple(path for path in paths if deps.read_problem(path) is None)


# --- prepare --------------------------------------------------------------------------------------


class _DartFailure(Exception):
    def __init__(self, reason: str) -> None:
        assert reason in REASONS, reason
        super().__init__(reason)
        self.reason = reason


def entry(
    runner: deps.Process, repo: Path, head: str, packet: Path, export: deps.Export,
) -> dict[str, Any] | None:
    """The ``dart`` entry for the head, or ``None`` when it holds no Dart package at all."""
    root = deps._tree(runner, repo, head)
    if "pubspec.yaml" not in root:
        projects = _subfolder_packages(runner, repo, head)
        if projects is None:
            return None
        return {"state": "not-installed", "reason": "subfolder-project", "projects": projects}
    try:
        for name in ("pubspec.yaml", "pubspec.lock"):
            if root.get(name) == "120000":
                raise _DartFailure("symlinked-input")
        if "pubspec.lock" not in root:
            raise _DartFailure("no-lockfile")
        return _install(runner, packet, export)
    except _DartFailure as exc:
        _clear(packet)
        return {"state": "not-installed", "reason": exc.reason}


def _clear(packet: Path) -> None:
    """Remove the Dart folder, and ``dependencies/`` when nothing else is left in it."""
    unseal(packet / "dependencies" / "dart")
    deps._remove(packet / "dependencies" / "dart")
    parent = packet / "dependencies"
    if parent.is_dir() and not parent.is_symlink() and not any(parent.iterdir()):
        parent.rmdir()


def _subfolder_packages(runner: deps.Process, repo: Path, head: str) -> list[str] | None:
    folders = set()
    for path in deps._tree(runner, repo, head, recursive=True):
        folder, _sep, name = path.rpartition("/")
        if folder and name == "pubspec.yaml":
            folders.add(folder)
    if not folders:
        return None
    safe = sorted(folder for folder in folders if deps._RECORDED_FOLDER.fullmatch(folder))
    return safe[:deps._MAX_RECORDED_FOLDERS]


def _install(runner: deps.Process, packet: Path, export: deps.Export) -> dict[str, Any]:
    target = packet / DIRECTORY
    with deps._temporary("saga-review-dart-") as work:
        source = work / "head"
        source.mkdir()
        if not export(source):
            raise _DartFailure("head-export")
        lock_path = source / "pubspec.lock"
        if lock_path.is_symlink() or not lock_path.is_file():
            raise _DartFailure("symlinked-input")
        lock = _read_lock(lock_path.read_text(encoding="utf-8", errors="replace"))
        _check_lock(lock, source)
        _check_pubspecs(source, lock)
        sdk = dart_sdk()
        if sdk is None:
            raise _DartFailure("dart-missing")
        env = {name: os.environ[name] for name in deps._ENV_COPIED if name in os.environ}
        # The SDK's own bin, and a folder saga writes holding only the system tools pub runs
        # (``chmod``, to mark package scripts executable): a git source, should one get past the
        # checks, finds no git to run.
        env["PATH"] = os.pathsep.join([str(sdk.root / "bin"), str(_pub_tools(work / "tools"))])
        for name, folder in (("HOME", "home"), ("TMPDIR", "tmp")):
            (work / folder).mkdir(mode=0o700)
            env[name] = str(work / folder)
        env["PUB_CACHE"] = str(target)
        env.update(ENV_FLAGS)
        target.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + TIMEOUT
        try:
            deps._watched(
                runner, [str(sdk.executable), "pub", "get", "--enforce-lockfile"], "pub get",
                source, env, [target, work / "home", work / "tmp"],
                seconds=max(1.0, deadline - time.monotonic()), missing="dart-missing",
                timed_out="timeout",
            )
        except deps.NotFetched as exc:
            raise _DartFailure(_classify(str(exc), exc.output)) from None
        _tidy(target)
        seal(target)
        packages = sorted(
            ({"name": name, "version": str(item.get("version", ""))}
             for name, item in lock.items() if item.get("source") == "hosted"),
            key=lambda item: (item["name"], item["version"]),
        )
        if packages and not any((target / "hosted").glob("*/*")):
            raise _DartFailure("nothing-installed")
        return {
            "state": "installed",
            "directory": DIRECTORY,
            "sdk": {"version": sdk.version},
            "packages": packages,
            "lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
        }


#: The system commands pub runs while it fetches. Nothing else is on its PATH.
_PUB_TOOLS = ("chmod",)


def _pub_tools(folder: Path) -> Path:
    """A folder with links to the system's own ``chmod``, found only in ``/bin`` and ``/usr/bin``."""
    folder.mkdir()
    for name in _PUB_TOOLS:
        found = shutil.which(name, path="/bin:/usr/bin")
        if found:
            (folder / name).symlink_to(found)
    return folder


def _classify(message: str, output: str) -> str:
    if message in ("dart-missing", "timeout"):
        return message
    if "byte limit" in message:
        return "size-limit"
    if _NETWORK.search(output):
        return "network"
    if _LOCK_MISMATCH.search(output):
        return "lock-mismatch"
    return "fetch-failed"


# --- the YAML subset pub writes ---------------------------------------------------------------------
#
# pub runs with the network on and no sandbox during prepare, and it acts on every pubspec it
# reads before it compares anything with the lock. So the files are read here, as the subset of
# YAML that pub itself writes and people write by hand, and anything outside it is refused rather
# than interpreted: a quoted or complex key, a document marker, an anchor, an alias, a tag, a flow
# collection, a block scalar (except a top-level ``description``), a tab, a duplicate key, or a
# line that is none of a key, a list item, a comment or a blank. What this reader returns is then
# what YAML means, so the structural checks below see what pub sees.


class _Unreadable(Exception):
    """The text is outside the YAML subset this reader accepts."""


_KEY = re.compile(r"^(?P<indent> *)(?P<key>[A-Za-z0-9_]+)[ ]*:(?:[ ]+(?P<value>.*?))?[ ]*$")
_ITEM = re.compile(r"^(?P<indent> *)-[ ]+(?P<value>.*?)[ ]*$")
#: Characters YAML gives a meaning to at the start of a plain value.
_INDICATORS = tuple("{[&*!|>%@`,?:-#")
#: Top-level keys whose value may be a folded or multi-line text, which pub never resolves.
_TEXT_KEYS = frozenset({"description"})


def _yaml(text: str) -> dict[str, Any]:
    """Read *text* as nested ``dict``s, ``list``s of scalars and ``str`` scalars."""
    root: dict[str, Any] = {}
    # Each open block: (indent of its keys or items, the container, the key that opened it).
    stack: list[tuple[int, Any]] = [(-1, root)]
    pending: tuple[int, dict[str, Any], str] | None = None
    text_block: tuple[int, dict[str, Any], str] | None = None
    for raw in text.splitlines():
        if "\t" in raw[: len(raw) - len(raw.lstrip())] or "\r" in raw:
            raise _Unreadable
        stripped = raw.strip()
        indent = len(raw) - len(raw.lstrip(" "))
        if text_block is not None:
            block_indent, owner, key = text_block
            if not stripped or indent > block_indent:
                owner[key] = (owner[key] + " " + stripped).strip()
                continue
            text_block = None
        if not stripped or stripped.startswith("#"):
            continue
        if indent == 0 and stripped.startswith(("---", "...", "%")):
            raise _Unreadable
        is_item = _ITEM.match(raw) is not None
        # Close every block this line is outside of. A list written at its key's own indent
        # stays open only for further items.
        while len(stack) > 1 and (
            indent < stack[-1][0]
            or (indent == stack[-1][0] and isinstance(stack[-1][1], list) and not is_item)
        ):
            stack.pop()
        if pending is not None:
            pending_indent, owner, key = pending
            pending = None
            if indent > pending_indent or (indent == pending_indent and _ITEM.match(raw)):
                container: Any = [] if _ITEM.match(raw) else {}
                owner[key] = container
                stack.append((indent, container))
        parent_indent, parent = stack[-1]
        item = _ITEM.match(raw)
        if item:
            if not isinstance(parent, list) or indent != parent_indent:
                raise _Unreadable
            parent.append(_scalar(item.group("value")))
            continue
        found = _KEY.match(raw)
        if found is None or not isinstance(parent, dict):
            raise _Unreadable
        if parent is not root and indent != parent_indent:
            raise _Unreadable
        if parent is root and indent != 0:
            raise _Unreadable
        key = found.group("key")
        if key in parent:
            raise _Unreadable
        value = found.group("value")
        if value is None or value.startswith("#"):
            parent[key] = None
            pending = (indent, parent, key)
            continue
        if parent is root and key in _TEXT_KEYS and re.fullmatch(r"[|>][-+]?", value):
            parent[key] = ""
            text_block = (indent, parent, key)
            continue
        parent[key] = _scalar(value)
        if parent is root and key in _TEXT_KEYS and not value.startswith(("'", '"')):
            # A plain text may go on over more indented lines.
            text_block = (indent, parent, key)
    return root


def _scalar(value: str) -> str:
    """A quoted or plain scalar, with a trailing comment removed; anything else is refused."""
    if value.startswith('"'):
        end = value.find('"', 1)
        if end < 0 or "\\" in value[:end] or value[end + 1:].strip()[:1] not in ("", "#"):
            raise _Unreadable
        return value[1:end]
    if value.startswith("'"):
        end = value.find("'", 1)
        if end < 0 or value[end + 1:].strip()[:1] not in ("", "#"):
            raise _Unreadable
        return value[1:end]
    if value.startswith(_INDICATORS) and not re.match(r"-[0-9]", value):
        raise _Unreadable
    plain = re.split(r"[ ]+#", value, maxsplit=1)[0].rstrip()
    if ": " in plain or plain.endswith(":") or not plain:
        raise _Unreadable
    return plain


def _read_lock(text: str) -> dict[str, dict[str, Any]]:
    """The ``packages`` map of a ``pubspec.lock``, as pub writes it; anything else is refused."""
    try:
        data = _yaml(text)
    except _Unreadable:
        raise _DartFailure("lock-unreadable") from None
    if set(data) - {"packages", "sdks"}:
        raise _DartFailure("lock-unreadable")
    packages = data.get("packages")
    if packages is None:
        return {}
    if not isinstance(packages, dict):
        raise _DartFailure("lock-unreadable")
    for item in packages.values():
        if not isinstance(item, dict) or set(item) - {"dependency", "description", "source",
                                                       "version"}:
            raise _DartFailure("lock-unreadable")
        description = item.get("description")
        if isinstance(description, list) or (
            isinstance(description, dict)
            and any(not isinstance(value, str) for value in description.values())
        ):
            raise _DartFailure("lock-unreadable")
    return packages


def _check_lock(lock: Mapping[str, Mapping[str, Any]], source: Path) -> None:
    """Refuse a lock that needs Flutter, git, another host, or a path outside the head."""
    if any(item.get("source") == "sdk" for item in lock.values()):
        raise _DartFailure("flutter-unsupported")
    for item in lock.values():
        kind, description = item.get("source"), item.get("description")
        if kind == "hosted":
            url = description.get("url") if isinstance(description, Mapping) else None
            if url not in _PUB_HOSTS:
                raise _DartFailure("unsupported-source")
        elif kind == "path":
            if not isinstance(description, Mapping) or str(description.get("relative")) != "true":
                raise _DartFailure("unsupported-source")
            _inside(source, source, str(description.get("path", "")))
        else:
            raise _DartFailure("unsupported-source")


_DEPENDENCY_SECTIONS = ("dependencies", "dev_dependencies", "dependency_overrides")
#: What pub reads from a package that is not a root: only its ``dependencies``. Measured with the
#: Dart SDK 3.13: a path dependency's ``dev_dependencies`` and ``dependency_overrides`` naming an
#: unreachable host were ignored, its ``dependencies`` made pub contact that host.
_PACKAGE_SECTIONS = ("dependencies",)
#: The most pubspecs one head may make saga read, roots and path dependencies together.
_MAX_PUBSPECS = 200


#: The role of a workspace member: every section a root has, and its own ``workspace`` list.
#: pub 3.13 resolves nested workspaces (measured: a member's member's ``dev_dependencies`` made
#: pub contact the host it named).
_WORKSPACE = "workspace"
_MEMBER_SECTIONS = (*_DEPENDENCY_SECTIONS, _WORKSPACE)


def _check_pubspecs(source: Path, lock: Mapping[str, Mapping[str, Any]] | None = None) -> None:
    """Check every pubspec pub reads during resolution, before it compares anything with the
    lock: the root ``pubspec.yaml`` and ``pubspec_overrides.yaml``; each workspace member's
    ``pubspec.yaml``, at any depth, as a root; and, followed from all of those and from the
    lock's path entries, each path dependency's ``pubspec.yaml`` (only its ``dependencies``, as
    pub reads it). A folder reached again with sections not yet checked (a path dependency that
    is also a workspace member, in either order) is read again for the union; a cycle ends.
    Another pubspec in the head (an example app, say) is never read by ``pub get`` at the root,
    so it is not checked."""
    queue: list[tuple[Path, tuple[str, ...]]] = [(source, _MEMBER_SECTIONS)]
    _read_pubspec(source / "pubspec_overrides.yaml", source, required=False,
                  sections=("dependency_overrides",), found=queue)
    for item in (lock or {}).values():
        description = item.get("description")
        if item.get("source") == "path" and isinstance(description, Mapping):
            queue.append((_inside(source, source, description.get("path")), _PACKAGE_SECTIONS))
    checked: dict[Path, set[str]] = {}
    reads = 0
    while queue:
        folder, sections = queue.pop(0)
        key = folder.resolve()
        done = checked.setdefault(key, set())
        wanted = set(sections) - done
        if not wanted:
            continue
        done |= wanted
        reads += 1
        if reads > _MAX_PUBSPECS:
            raise _DartFailure("pubspec-unreadable")
        data = _read_pubspec(folder / "pubspec.yaml", source, required=True,
                             sections=tuple(name for name in _DEPENDENCY_SECTIONS if name in done),
                             found=queue)
        if _WORKSPACE in wanted:
            members = data.get(_WORKSPACE)
            if members is None:
                continue
            if not isinstance(members, list):
                raise _DartFailure("pubspec-unreadable")
            for member in members:
                queue.append((_inside(source, folder, member), _MEMBER_SECTIONS))


def _read_pubspec(
    path: Path, source: Path, *, required: bool, sections: tuple[str, ...],
    found: list[tuple[Path, tuple[str, ...]]],
) -> dict[str, Any]:
    """Read one pubspec, check the *sections* pub reads from it, and add each in-head path
    dependency it names to *found*, to be read as a package."""
    if not os.path.lexists(path):
        if required:
            raise _DartFailure("pubspec-unreadable")
        return {}
    _no_links(source, path)
    try:
        data = _yaml(path.read_text(encoding="utf-8", errors="replace"))
    except _Unreadable:
        raise _DartFailure("pubspec-unreadable") from None
    environment = data.get("environment")
    if environment is not None and (
        not isinstance(environment, dict) or "flutter" in environment
    ):
        raise _DartFailure("flutter-unsupported" if isinstance(environment, dict)
                           else "pubspec-unreadable")
    for section in sections:
        entries = data.get(section)
        if entries is None:
            continue
        if not isinstance(entries, dict):
            raise _DartFailure("pubspec-unreadable")
        for spec in entries.values():
            folder = _check_dependency(spec, path.parent, source)
            if folder is not None:
                found.append((folder, _PACKAGE_SECTIONS))
    return data


def _check_dependency(spec: Any, base: Path, source: Path) -> Path | None:
    """A dependency is a version constraint, or a block with ``version`` and an in-head
    ``path``, whose folder is returned. Flutter's ``sdk`` is refused as unsupported; any other
    key as another source."""
    if spec is None or isinstance(spec, str):
        return None
    if not isinstance(spec, dict):
        raise _DartFailure("pubspec-unreadable")
    if "sdk" in spec:
        raise _DartFailure("flutter-unsupported")
    if set(spec) - {"version", "path"}:
        raise _DartFailure("unsupported-source")
    if "path" not in spec:
        return None
    if not isinstance(spec["path"], str):
        raise _DartFailure("unsupported-source")
    return _inside(source, base, spec["path"])


def _inside(root: Path, base: Path, value: Any) -> Path:
    """*value*, a path relative to *base*, as a folder inside *root* reached through no link."""
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise _DartFailure("unsupported-source")
    joined = Path(os.path.normpath(base / value))
    if not joined.is_relative_to(root):
        raise _DartFailure("unsupported-source")
    _no_links(root, joined)
    if not joined.resolve().is_relative_to(root.resolve()):
        raise _DartFailure("unsupported-source")
    return joined


def _no_links(root: Path, path: Path) -> None:
    """Refuse a link at any step from *root* down to *path*."""
    cursor = root
    for part in path.relative_to(root).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise _DartFailure("symlinked-input")


def seal(cache: Path) -> None:
    """Make the cache's files and folders read-only (0444 or 0555 for files, 0555 for folders).

    The reviewer's file tools run outside the command sandbox; a write that reaches the packet
    through a link then fails at the file. :func:`unseal` gives write back before a removal.
    """
    for folder, dirs, files in os.walk(cache, topdown=False):
        for name in files:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                mode = os.lstat(path).st_mode
                os.chmod(path, 0o555 if mode & 0o111 else 0o444)
        for name in dirs:
            path = os.path.join(folder, name)
            if not os.path.islink(path):
                os.chmod(path, 0o555)
    if cache.is_dir() and not cache.is_symlink():
        cache.chmod(0o555)


def unseal(path: Path) -> None:
    """Give write back to the owner under *path*, without following links, before removing it."""
    if not os.path.lexists(path) or path.is_symlink():
        return
    if path.is_dir():
        path.chmod(0o755)
        for folder, dirs, files in os.walk(path):
            for name in dirs:
                if not os.path.islink(os.path.join(folder, name)):
                    os.chmod(os.path.join(folder, name), 0o755)
            for name in files:
                if not os.path.islink(os.path.join(folder, name)):
                    os.chmod(os.path.join(folder, name), 0o644)


def _tidy(cache: Path) -> None:
    """Keep only ``hosted/`` and ``hosted-hashes/``: the rest differs between two fetches."""
    for item in list(cache.iterdir()) if cache.is_dir() else []:
        if item.name not in ("hosted", "hosted-hashes"):
            deps._remove(item) if item.is_dir() and not item.is_symlink() else item.unlink()
    for host in (cache / "hosted").iterdir() if (cache / "hosted").is_dir() else []:
        for item in list(host.iterdir()) if host.is_dir() else []:
            if not _PACKAGE_DIR.fullmatch(item.name):
                deps._remove(item) if item.is_dir() and not item.is_symlink() else item.unlink()
