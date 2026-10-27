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
#: A dependency key in a pubspec that points somewhere other than pub.dev, or a path.
_PUBSPEC_SOURCE = re.compile(r"^\s*(git|hosted|url)\s*:", re.MULTILINE)
_PUBSPEC_PATH = re.compile(r"^\s*path\s*:\s*['\"]?([^'\"#\n]+?)['\"]?\s*(?:#.*)?$", re.MULTILINE)
_PUBSPEC_FLUTTER = re.compile(r"^\s*sdk\s*:\s*['\"]?flutter\b", re.MULTILINE)
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
        _check_pubspecs(source)
        sdk = dart_sdk()
        if sdk is None:
            raise _DartFailure("dart-missing")
        env = {name: os.environ[name] for name in deps._ENV_COPIED if name in os.environ}
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


def _read_lock(text: str) -> dict[str, dict[str, Any]]:
    """The ``packages`` map of a ``pubspec.lock``, the subset of YAML pub writes.

    Each package is ``{"source": ..., "version": ..., "description": str | dict}``. A layout this
    reader does not know is refused (``lock-unreadable``), never guessed at.
    """
    packages: dict[str, dict[str, Any]] = {}
    section = None
    current: dict[str, Any] | None = None
    in_description = False
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        key, sep, value = raw.strip().partition(":")
        if not sep:
            raise _DartFailure("lock-unreadable")
        value = _unquote(value.strip())
        if indent == 0:
            section, current, in_description = key, None, False
            continue
        if section != "packages":
            continue
        if indent == 2:
            current = packages.setdefault(_unquote(key), {})
            in_description = False
        elif indent == 4 and current is not None:
            in_description = key == "description" and value == ""
            current[key] = {} if in_description else value
        elif indent == 6 and current is not None and in_description:
            current["description"][key] = value
        else:
            raise _DartFailure("lock-unreadable")
    return packages


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


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


def _check_pubspecs(source: Path) -> None:
    """Refuse a pubspec or override file that names a git source, a host, a path outside the
    head, or the Flutter SDK. pub reads them before it compares them with the lock."""
    for path in sorted(source.rglob("pubspec*.yaml")):
        if ".dart_tool" in path.parts or path.name not in ("pubspec.yaml", "pubspec_overrides.yaml"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if _PUBSPEC_FLUTTER.search(text):
            raise _DartFailure("flutter-unsupported")
        if _PUBSPEC_SOURCE.search(text):
            raise _DartFailure("unsupported-source")
        for found in _PUBSPEC_PATH.finditer(text):
            _inside(source, path.parent, found.group(1).strip())


def _inside(root: Path, base: Path, value: str) -> None:
    joined = Path(os.path.normpath(base / value))
    if not value or Path(value).is_absolute() or not joined.is_relative_to(root):
        raise _DartFailure("unsupported-source")


def _tidy(cache: Path) -> None:
    """Keep only ``hosted/`` and ``hosted-hashes/``: the rest differs between two fetches."""
    for item in list(cache.iterdir()) if cache.is_dir() else []:
        if item.name not in ("hosted", "hosted-hashes"):
            deps._remove(item) if item.is_dir() and not item.is_symlink() else item.unlink()
    for host in (cache / "hosted").iterdir() if (cache / "hosted").is_dir() else []:
        for item in list(host.iterdir()) if host.is_dir() else []:
            if not _PACKAGE_DIR.fullmatch(item.name):
                deps._remove(item) if item.is_dir() and not item.is_symlink() else item.unlink()
