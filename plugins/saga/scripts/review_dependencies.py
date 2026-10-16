#!/usr/bin/env python3
"""The head's dependencies, fetched once in prepare for an offline reviewer (issue 262).

A targeted reviewer builds and tests the change inside a sandbox with no network, and finish
re-runs its reproduction confined the same way. Neither can download anything, so prepare fetches
the head's dependencies into the packet, and both read them from there, read-only.

Only Rust is fetched. ``cargo vendor --locked`` writes the crates.io sources into
``<packet>/dependencies/rust`` and compiles nothing, so no build script runs. The fetch works on
an export of the head with the commit's cargo and rustup configuration removed, refuses git and
alternate-registry sources, and runs with a fresh ``HOME``, ``TMPDIR`` and ``CARGO_HOME`` and no
operator variable beyond the allow-list. ``dependencies.json`` in the packet says what happened.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404
import tempfile
import tomllib
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = "saga.review_dependencies.v1"
FILE = "dependencies.json"
RUST_DIRECTORY = "dependencies/rust"
FETCH_TIMEOUT = 600
#: The name the reviewer's and the re-run's cargo configuration gives the vendored sources.
VENDORED_SOURCE = "saga-vendored"
#: The two spellings Cargo.lock uses for crates.io, the git index and the sparse one.
CRATES_IO_SOURCES = frozenset({
    "registry+https://github.com/rust-lang/crates.io-index",
    "sparse+https://index.crates.io/",
})
#: What cargo or rustup reads from the working directory and acts on. Cargo config can replace
#: sources, add registries and credential providers, and name ``rustc`` or a wrapper; a toolchain
#: file's ``path`` key makes rustup run whatever ``cargo`` the commit ships.
_CARGO_CONFIG_NAMES = (".cargo/config", ".cargo/config.toml")
_TOOLCHAIN_FILES = ("rust-toolchain", "rust-toolchain.toml")
_DEPENDENCY_TABLES = (
    "dependencies", "dev-dependencies", "dev_dependencies",
    "build-dependencies", "build_dependencies",
)
_REMOTE_KEYS = ("git", "registry", "registry-index")
_ENV_COPIED = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")

Process = Callable[..., Any]
Export = Callable[[Path], bool]


class NotFetched(Exception):
    """The dependencies were not fetched, for the reason given."""


def fetch(runner: Process, repo: Path, head: str, packet: Path, export: Export) -> dict[str, Any]:
    """Fetch the head's dependencies into *packet* and return ``dependencies.json``'s content.

    *export* writes the head's tracked files into the folder it is given, without symlinks.
    """
    record: dict[str, Any] = {"schema": SCHEMA}
    if _has_file(runner, repo, head, "Cargo.toml"):
        record["rust"] = _fetch_rust(runner, packet, export)
    return record


def rust_vendor(packet: Path) -> Path | None:
    """The packet's vendored Rust sources, or ``None`` when there are none to trust.

    The entry counts only when it says ``fetched`` and names a relative directory inside the
    packet that exists, with no symlink anywhere along the way.
    """
    try:
        data = json.loads((packet / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = data.get("rust") if isinstance(data, Mapping) else None
    if not isinstance(entry, Mapping) or entry.get("state") != "fetched":
        return None
    relative = entry.get("directory")
    if not isinstance(relative, str) or not relative:
        return None
    parts = Path(relative).parts
    if Path(relative).is_absolute() or any(part in ("", ".", "..") for part in parts):
        return None
    cursor = packet
    if cursor.is_symlink():
        return None
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            return None
    if not cursor.is_dir():
        return None
    resolved = cursor.resolve()
    if not resolved.is_relative_to(packet.resolve()):
        return None
    return resolved


def cargo_config(vendor: Path | None) -> str:
    """A ``CARGO_HOME`` ``config.toml``: offline, and crates.io replaced by *vendor* when given."""
    lines = ["# Written by saga for an offline review (issue 262).", ""]
    if vendor is not None:
        lines += [
            "[source.crates-io]",
            f"replace-with = {json.dumps(VENDORED_SOURCE)}",
            "",
            f"[source.{VENDORED_SOURCE}]",
            f"directory = {json.dumps(str(vendor))}",
            "",
        ]
    lines += ["[net]", "offline = true", ""]
    return "\n".join(lines)


def write_cargo_home(directory: Path, vendor: Path | None) -> Path:
    """Write a cargo home holding a read-only :func:`cargo_config` into *directory*.

    Cargo needs no writable home for an offline build from a directory source (measured on cargo
    1.98.1), so the confined re-run is given this folder read-only.
    """
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "config.toml"
    config.write_text(cargo_config(vendor), encoding="utf-8")
    config.chmod(0o444)
    return directory


# --- Rust ---------------------------------------------------------------------------------------


def _fetch_rust(runner: Process, packet: Path, export: Export) -> dict[str, Any]:
    target = packet / RUST_DIRECTORY
    with _temporary("saga-review-deps-") as work:
        source = work / "head"
        source.mkdir()
        try:
            if not export(source):
                raise NotFetched("the head could not be exported")
            _strip_configuration(source)
            _check_ancestors(source)
            _check_manifests(source)
            env = _cargo_env(work)
            lock = source / "Cargo.lock"
            if not lock.is_file():
                _cargo(runner, ["cargo", "generate-lockfile", "--manifest-path",
                                str(source / "Cargo.toml")], source, env)
            crates = _check_lock(lock)
            if crates == 0:
                return {"state": "no-dependencies"}
            _cargo(runner, ["cargo", "vendor", "--locked", "--quiet", "--manifest-path",
                            str(source / "Cargo.toml"), str(target)], source, env)
            if target.is_symlink() or not target.is_dir():
                raise NotFetched("cargo vendor wrote no directory")
            return {
                "state": "fetched",
                "directory": RUST_DIRECTORY,
                "crates": sum(1 for item in target.iterdir() if item.is_dir()),
            }
        except NotFetched as exc:
            _remove(target)
            return {"state": "not-fetched", "reason": str(exc)}


def _strip_configuration(root: Path) -> None:
    """Remove the commit's cargo configuration and toolchain files from the fetch's folder."""
    cargo_dir = root / ".cargo"
    if cargo_dir.is_dir() and not cargo_dir.is_symlink():
        shutil.rmtree(cargo_dir)
    elif os.path.lexists(cargo_dir):
        cargo_dir.unlink()
    for name in _TOOLCHAIN_FILES:
        if os.path.lexists(root / name):
            (root / name).unlink()


def _check_ancestors(root: Path) -> None:
    """Refuse when a folder above the fetch holds configuration cargo or rustup would read."""
    for folder in [root, *root.resolve().parents]:
        for name in (*_CARGO_CONFIG_NAMES, *_TOOLCHAIN_FILES):
            if os.path.lexists(folder / name):
                raise NotFetched(f"{folder / name} would configure the fetch")


def _check_manifests(root: Path) -> None:
    """Refuse a manifest that names a git or other-registry source, or a path outside the head."""
    for manifest in sorted(root.rglob("Cargo.toml")):
        relative = manifest.relative_to(root).as_posix()
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            raise NotFetched(f"{relative} does not parse") from None
        for where, spec in _dependency_specs(data):
            if not isinstance(spec, Mapping):
                continue
            remote = [key for key in _REMOTE_KEYS if key in spec]
            if remote:
                raise NotFetched(f"{relative} {where} names {remote[0]}; only crates.io is fetched")
            if isinstance(spec.get("path"), str):
                _inside(root, manifest.parent, spec["path"], f"{relative} {where}")
        patch = data.get("patch")
        if isinstance(patch, Mapping):
            for name in patch:
                if name != "crates-io":
                    raise NotFetched(f"{relative} patches {name}; only crates.io is fetched")
        package = _table(data, "package")
        if isinstance(package.get("workspace"), str):
            _inside(root, manifest.parent, package["workspace"], f"{relative} package.workspace")
        workspace = _table(data, "workspace")
        for key in ("members", "default-members", "exclude"):
            values = workspace.get(key)
            for value in values if isinstance(values, list) else []:
                if isinstance(value, str):
                    _inside(root, manifest.parent, value, f"{relative} workspace.{key}")


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name)
    return value if isinstance(value, Mapping) else {}


def _dependency_specs(data: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    """Every dependency entry: the plain tables, per-target ones, workspace, patch and replace."""
    tables: list[tuple[str, Any]] = [(name, data.get(name)) for name in _DEPENDENCY_TABLES]
    target = data.get("target")
    if isinstance(target, Mapping):
        for platform, section in target.items():
            if isinstance(section, Mapping):
                tables += [(f"target.{platform}.{name}", section.get(name))
                           for name in _DEPENDENCY_TABLES]
    workspace = data.get("workspace")
    if isinstance(workspace, Mapping):
        tables.append(("workspace.dependencies", workspace.get("dependencies")))
    patch = data.get("patch")
    if isinstance(patch, Mapping):
        tables += [(f"patch.{name}", section) for name, section in patch.items()]
    tables.append(("replace", data.get("replace")))
    for where, table in tables:
        if isinstance(table, Mapping):
            for name, spec in table.items():
                yield f"{where}.{name}", spec


def _inside(root: Path, base: Path, value: str, label: str) -> None:
    joined = Path(os.path.normpath(base / value))
    if Path(value).is_absolute() or not joined.is_relative_to(root):
        raise NotFetched(f"{label} points outside the head")


def _check_lock(lock: Path) -> int:
    """The number of crates.io packages in *lock*; refuse any other source."""
    try:
        data = tomllib.loads(lock.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise NotFetched("Cargo.lock is missing or does not parse") from None
    packages = data.get("package")
    count = 0
    for package in packages if isinstance(packages, list) else []:
        source = package.get("source") if isinstance(package, Mapping) else None
        if source is None:
            continue
        if source not in CRATES_IO_SOURCES:
            raise NotFetched(f"Cargo.lock names the source {str(source)[:120]}; only crates.io is "
                             "fetched")
        count += 1
    return count


def _cargo_env(work: Path) -> dict[str, str]:
    """The allow-list, with a fresh home, temp folder and cargo home inside *work*."""
    env = {name: os.environ[name] for name in _ENV_COPIED if name in os.environ}
    for name, folder in (("HOME", "home"), ("TMPDIR", "tmp"), ("CARGO_HOME", "cargo-home")):
        path = work / folder
        path.mkdir(mode=0o700)
        env[name] = str(path)
    env["CARGO_NET_GIT_FETCH_WITH_CLI"] = "false"
    # A rustup proxy finds its toolchain under the real rustup home, as review_tools does.
    env["RUSTUP_HOME"] = os.environ.get("RUSTUP_HOME") or str(Path.home() / ".rustup")
    if "RUSTUP_TOOLCHAIN" in os.environ:
        env["RUSTUP_TOOLCHAIN"] = os.environ["RUSTUP_TOOLCHAIN"]
    return env


def _cargo(runner: Process, argv: list[str], cwd: Path, env: Mapping[str, str]) -> None:
    try:
        result = runner(argv, cwd=cwd, env=dict(env), timeout=FETCH_TIMEOUT, shell=False)
    except FileNotFoundError:
        raise NotFetched("cargo is not installed") from None
    except subprocess.TimeoutExpired:
        raise NotFetched(f"{argv[1]} timed out") from None
    if result.code != 0:
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        detail = f": {lines[-1][:200]}" if lines else ""
        raise NotFetched(f"cargo {argv[1]} exited {result.code}{detail}")


def _has_file(runner: Process, repo: Path, head: str, name: str) -> bool:
    result = runner(
        ["git", "cat-file", "-e", f"{head}:{name}"], cwd=repo, env=dict(os.environ),
        timeout=60, shell=False,
    )
    return result.code == 0


@contextmanager
def _temporary(prefix: str) -> Iterator[Path]:
    """A fresh owner-only folder, removed afterwards."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield path
    finally:
        _remove(path)


def _remove(path: Path) -> None:
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path, ignore_errors=True)
