#!/usr/bin/env python3
"""The head's dependencies, fetched once in prepare for an offline reviewer (issue 262).

A targeted reviewer builds and tests the change inside a sandbox with no network, and finish
re-runs its reproduction confined the same way. Neither can download anything, so prepare fetches
the head's dependencies into the packet, and both read them from there, read-only.

For Rust, ``cargo vendor --locked`` writes the crates.io sources into
``<packet>/dependencies/rust`` and compiles nothing, so no build script runs. The fetch works on
an export of the head with the commit's cargo and rustup configuration removed, refuses git and
alternate-registry sources, and runs with a fresh ``HOME``, ``TMPDIR`` and ``CARGO_HOME`` and no
operator variable beyond the allow-list. A watcher stops it once its folders pass
``FETCH_MAX_BYTES``. ``dependencies.json`` in the packet says what happened.

For Python (a root ``uv.lock``, ``pyproject.toml`` or ``requirements*.txt``), uv builds a
relocatable virtual environment at ``<packet>/dependencies/python`` on the operator's ``python3``
and installs prebuilt wheels into it, never building one, so no build script runs: the frozen lock
with every group and extra when there is one, otherwise what the files declare, resolved as of
the head's commit time. pytest is added when nothing declares it. The project itself is not
installed. A package without a wheel is recorded as missing, not fatal. The reviewer and the
re-run put the environment's ``bin`` first on ``PATH``, so ``python3`` is its interpreter, and
read it without writing it.

Run as a script, this module is that watcher: ``review_dependencies.py --limit N --seconds S
--watch PATH ... -- cargo ...``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess  # nosec B404
import sys
import tempfile
import time
import tomllib
from datetime import datetime, timezone
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = "saga.review_dependencies.v1"
FILE = "dependencies.json"
RUST_DIRECTORY = "dependencies/rust"
PYTHON_DIRECTORY = "dependencies/python"
FETCH_TIMEOUT = 600
#: The time the whole Python install may take, across every uv command it runs, including the
#: one-package-at-a-time retry after a failed install.
PYTHON_TIMEOUT = 900
#: The states of a Python entry whose environment the reviewer and the re-run use.
PYTHON_USABLE = frozenset({"installed", "partial"})
#: The most the fetch may write, counted across the vendored folder and its own cargo home, home
#: and temp folder. Measured on ripgrep 3fce3b5: a 70 MB vendored tree peaks at 155 MB, because the
#: cargo home holds the archives and a second extracted copy until the command ends. 2 GiB fits a
#: vendored tree about 13 times ripgrep's, and keeps several prepares running at once in single
#: gigabytes, so a head that depends on huge or very many crates is refused, not left to fill disk.
FETCH_MAX_BYTES = 2 * 1024**3
#: The watcher's exit codes. Cargo exits 101 on its own errors.
LIMIT_EXIT = 125
TIMEOUT_EXIT = 124
MISSING_EXIT = 127
_WATCH_INTERVAL = 0.5
#: The start of the name the reviewer's and the re-run's cargo configuration gives the vendored
#: sources. Each cargo home adds a random suffix, so a commit's own configuration cannot name the
#: source to redefine or chain it.
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

#: Paths under home a confined re-run is never given back, as agent-launcher's
#: ``REVIEWER_CREDENTIAL_PATHS`` and ``REVIEWER_SHARED_ROOTS`` (the packages share no code; a
#: test keeps the two lists equal).
CREDENTIAL_PATHS = (
    "~/.ssh",
    "~/.aws",
    "~/.config/gh",
    "~/.gnupg",
    "~/.netrc",
    "~/.docker/config.json",
    "~/.kube",
    "~/.config/gcloud",
    "~/.azure",
    "~/.claude/.credentials.json",
    "~/.codex/auth.json",
    "~/.git-credentials",
    "~/.pypirc",
    "~/.cargo/credentials",
    "~/.cargo/credentials.toml",
    "~/.terraform.d",
    "~/.vault-token",
    "~/.config/hub",
    "~/.local/share/keyrings",
    "~/.npmrc",
)
SHARED_ROOTS = ('~/.config', '~/.local', '~/.local/share', '~/.cache', '~/Library')

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
    names = _root_names(runner, repo, head)
    if _python_inputs(names):
        record["python"] = _install_python(runner, repo, head, packet, export, names)
    return record


def rust_vendor(packet: Path) -> Path | None:
    """The packet's vendored Rust sources, or ``None`` when there are none to trust.

    The entry counts only when it says ``fetched`` and names a relative directory inside the
    packet that exists, with no symlink anywhere along the way.
    """
    return _packet_directory(packet, "rust", frozenset({"fetched"}))


def python_environment(packet: Path) -> Path | None:
    """The packet's Python environment, or ``None`` when there is none to trust.

    The entry counts when it says ``installed`` or ``partial`` and names a relative directory
    inside the packet, with no symlink along the way, that holds ``pyvenv.cfg`` and ``bin/``.
    """
    venv = _packet_directory(packet, "python", PYTHON_USABLE)
    if venv is None:
        return None
    marker, scripts = venv / "pyvenv.cfg", venv / "bin"
    if marker.is_symlink() or not marker.is_file() or scripts.is_symlink() or not scripts.is_dir():
        return None
    return venv


def python_env(venv: Path, path: str | None = None) -> dict[str, str]:
    """What puts *venv* in front: its ``bin`` first on ``PATH``, and ``VIRTUAL_ENV``.

    ``python3 -m pytest`` then starts the environment's interpreter, so a reviewer's command and
    the re-run's are the same words, wherever the packet is.
    """
    rest = os.environ.get("PATH", "") if path is None else path
    return {
        "PATH": os.pathsep.join([str(venv / "bin"), *([rest] if rest else [])]),
        "VIRTUAL_ENV": str(venv),
    }


def python_toolchain(venv: Path) -> tuple[Path, ...]:
    """What a confined ``python3`` from *venv* must read and map: the environment, and the
    ``bin`` and ``lib`` of the install its interpreter links to, minus any :func:`read_problem`.

    The environment is mapped as code because a wheel's compiled extension is loaded from it.
    """
    paths = [venv]
    try:
        real = (venv / "bin" / "python3").resolve(strict=True)
    except OSError:
        real = None
    if real is not None:
        prefix = real.parent.parent
        paths += [prefix / part for part in ("bin", "lib") if (prefix / part).is_dir()]
    return tuple(path for path in paths if read_problem(path) is None)


def _packet_directory(packet: Path, key: str, states: frozenset[str]) -> Path | None:
    try:
        data = json.loads((packet / FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    entry = data.get(key) if isinstance(data, Mapping) else None
    if not isinstance(entry, Mapping) or entry.get("state") not in states:
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


def cargo_config(vendor: Path | None, source: str = VENDORED_SOURCE) -> str:
    """A ``CARGO_HOME`` ``config.toml``: offline, and crates.io replaced by *vendor* when given."""
    lines = ["# Written by saga for an offline review (issue 262).", ""]
    if vendor is not None:
        lines += [
            "[source.crates-io]",
            f"replace-with = {json.dumps(source)}",
            "",
            f"[source.{json.dumps(source)}]",
            f"directory = {json.dumps(str(vendor))}",
            "",
        ]
    lines += ["[net]", "offline = true", ""]
    return "\n".join(lines)


def cargo_shim(cargo: str, config: Path) -> str:
    """A ``cargo`` that runs *cargo* with *config* passed as ``--config``.

    Measured on cargo 1.98.1: a commit's own ``.cargo/config.toml`` that replaces crates.io
    outranks both the ``CARGO_HOME`` configuration and ``CARGO_SOURCE_*`` variables, and only
    ``--config`` outranks it. A rustup ``+toolchain`` argument has to stay first.
    """
    real, given = shlex.quote(cargo), shlex.quote(str(config))
    return (
        "#!/bin/sh\n"
        "# Written by saga for an offline review (issue 262): this cargo home's configuration\n"
        "# outranks the commit's own.\n"
        'case "${1-}" in\n'
        f'  +*) toolchain=$1; shift; exec {real} "$toolchain" --config {given} "$@" ;;\n'
        "esac\n"
        f'exec {real} --config {given} "$@"\n'
    )


def write_cargo_home(directory: Path, vendor: Path | None, cargo: str | None = None) -> Path | None:
    """Write a cargo home holding a read-only :func:`cargo_config` into *directory*.

    Cargo needs no writable home for an offline build from a directory source (measured on cargo
    1.98.1), so the confined re-run is given this folder read-only. With *cargo*, the real binary,
    ``bin/cargo`` is a :func:`cargo_shim` and its path is returned; otherwise ``None``.
    """
    directory.mkdir(parents=True, exist_ok=True)
    config = directory / "config.toml"
    source = f"{VENDORED_SOURCE}-{secrets.token_hex(8)}"
    config.write_text(cargo_config(vendor, source), encoding="utf-8")
    config.chmod(0o444)
    if cargo is None:
        return None
    shim = directory / "bin" / "cargo"
    shim.parent.mkdir(exist_ok=True)
    shim.write_text(cargo_shim(cargo, config), encoding="utf-8")
    shim.chmod(0o555)
    return shim


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
            watched = [target, *(Path(env[name]) for name in ("HOME", "TMPDIR", "CARGO_HOME"))]
            lock = source / "Cargo.lock"
            if not lock.is_file():
                _cargo(runner, ["cargo", "generate-lockfile", "--manifest-path",
                                str(source / "Cargo.toml")], source, env, watched)
            crates = _check_lock(lock)
            # A lock with no crates.io package is trusted only when no manifest asks for one;
            # otherwise ``cargo vendor --locked`` decides, and refuses a lock that is out of date.
            if crates == 0 and not _declares_registry_dependency(source):
                return {"state": "no-dependencies"}
            _cargo(runner, ["cargo", "vendor", "--locked", "--quiet", "--manifest-path",
                            str(source / "Cargo.toml"), str(target)], source, env, watched)
            if crates == 0 and not os.path.lexists(target):
                return {"state": "no-dependencies"}
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


def _declares_registry_dependency(root: Path) -> bool:
    """True when a manifest declares a dependency that is not a path: one crates.io must supply.

    A plain version string, or a table with no ``path``, counts. ``workspace = true`` inherits
    from ``workspace.dependencies``, which is checked in its own right. ``[patch]`` and
    ``[replace]`` only override, so they declare nothing. The manifests already parsed in
    :func:`_check_manifests`.
    """
    for manifest in sorted(root.rglob("Cargo.toml")):
        data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        for _where, spec in _declared_specs(data):
            if isinstance(spec, Mapping) and ("path" in spec or spec.get("workspace") is True):
                continue
            return True
    return False


def _declared_specs(data: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """The dependency tables that declare: plain, per-target, and the workspace's."""
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
    return [
        (f"{where}.{name}", spec)
        for where, table in tables if isinstance(table, Mapping)
        for name, spec in table.items()
    ]


def _dependency_specs(data: Mapping[str, Any]) -> Iterator[tuple[str, Any]]:
    """Every dependency entry: the plain tables, per-target ones, workspace, patch and replace."""
    yield from _declared_specs(data)
    tables: list[tuple[str, Any]] = []
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
    env.update(rustup_env())
    return env


def rustup_env() -> dict[str, str]:
    """What a rustup proxy needs to pick its toolchain once ``HOME`` is not the operator's.

    ``RUSTUP_HOME`` defaults to the real home's ``.rustup``, as review_tools does, and
    ``RUSTUP_TOOLCHAIN`` passes when set. Without them a proxy reports that no default toolchain
    is configured (seen on CI, whose cargo is rustup's).
    """
    env = {"RUSTUP_HOME": os.environ.get("RUSTUP_HOME") or str(Path.home() / ".rustup")}
    if os.environ.get("RUSTUP_TOOLCHAIN"):
        env["RUSTUP_TOOLCHAIN"] = os.environ["RUSTUP_TOOLCHAIN"]
    return env


def toolchain_paths(cargo: str | None) -> tuple[Path, ...]:
    """What a confined cargo must read and map to run: its own folder, and rustup's toolchains.

    For a rustup proxy under ``~/.cargo/bin`` that is the ``bin`` folder only, never ``~/.cargo``,
    which holds cargo's credentials file, plus ``toolchains`` and ``settings.toml`` under the
    rustup home. A cargo outside home needs nothing, and nothing is added for it but its folder.
    *cargo* is what the operator's ``PATH`` finds, never a path from a reviewer's command, and a
    path that is home or above it, a shared root, or is, is inside or holds a credential path is
    dropped (:func:`read_problem`).
    """
    if cargo is None:
        return ()
    paths = [Path(cargo).absolute().parent]
    rustup = Path(rustup_env()["RUSTUP_HOME"])
    paths += [rustup / part for part in ("toolchains", "settings.toml") if (rustup / part).exists()]
    return tuple(path for path in paths if read_problem(path) is None)


def read_problem(path: Path, home: Path | None = None) -> str | None:
    """Why giving *path* back to a confined command would re-open too much, or ``None``."""
    home = home or Path.home()
    homes = {home.absolute(), home.resolve()}
    for form in {path.absolute(), path.resolve()}:
        if any(form == h or h.is_relative_to(form) for h in homes):
            return f"{path} is the home directory or above it"
        for h in homes:
            if any(form == h / root[2:] for root in SHARED_ROOTS):
                return f"{path} is a shared root"
            for credential in CREDENTIAL_PATHS:
                held = h / credential[2:]
                if form == held or form.is_relative_to(held) or held.is_relative_to(form):
                    return f"{path} is, is inside, or holds the credential path {credential}"
    return None


def _cargo(
    runner: Process, argv: list[str], cwd: Path, env: Mapping[str, str], watched: list[Path],
) -> None:
    """Run cargo under the watcher, which stops it past the time or the byte limit."""
    _watched(runner, argv, f"cargo {argv[1]}", cwd, env, watched, missing="cargo is not installed",
             timed_out=f"{argv[1]} timed out")


def _watched(
    runner: Process, argv: list[str], label: str, cwd: Path, env: Mapping[str, str],
    watched: list[Path], *, seconds: float = FETCH_TIMEOUT, missing: str | None = None,
    timed_out: str | None = None, scrub: Callable[[str], str] = lambda text: text,
) -> Any:
    """Run *argv* under the watcher, which stops it past *seconds* or the byte limit.

    Returns the result; raises :class:`NotFetched`, naming *label*, for anything but exit 0.
    """
    missing = missing or f"{argv[0]} is not installed"
    timed_out = timed_out or f"{label} timed out"
    watcher = [sys.executable, "-I", str(Path(__file__).resolve()),
               "--limit", str(FETCH_MAX_BYTES), "--seconds", f"{seconds:g}"]
    for path in watched:
        watcher += ["--watch", str(path)]
    try:
        result = runner([*watcher, "--", *argv], cwd=cwd, env=dict(env),
                        timeout=int(seconds) + 60, shell=False)
    except FileNotFoundError:
        raise NotFetched(missing) from None
    except subprocess.TimeoutExpired:
        raise NotFetched(timed_out) from None
    marked = (result.stderr or "").rstrip().endswith(_WATCHER_MARK)
    if result.code == LIMIT_EXIT and marked:
        raise NotFetched(f"{label} passed the {FETCH_MAX_BYTES} byte limit")
    if result.code == TIMEOUT_EXIT and marked:
        raise NotFetched(timed_out)
    if result.code == MISSING_EXIT and marked:
        raise NotFetched(missing)
    if result.code != 0:
        raise NotFetched(f"{label} exited {result.code}{_detail(result, scrub)}")
    return result


def _detail(result: Any, scrub: Callable[[str], str]) -> str:
    """The line of a failed command's output that says why: uv's ``cause:``, else the last."""
    lines = [line.strip() for line in (result.stderr or result.stdout or "").strip().splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    cause = next((line for line in lines if line.startswith("cause:")), None)
    chosen = cause[len("cause:"):].strip() if cause else lines[-1]
    return f": {scrub(chosen)[:200]}"


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


# --- Python -------------------------------------------------------------------------------------

#: A root file that makes the head a Python project. ``requirements*.txt`` is matched by pattern.
_PYTHON_FILES = ("uv.lock", "pyproject.toml")
_REQUIREMENTS = re.compile(r"^requirements[^/]*\.txt$")
_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
#: An editable or local line in a requirements file: it names the project or a folder, which
#: would have to be built.
_LOCAL_LINE = re.compile(r"^(-e|--editable)(\s|=)|^(\.|/|file:)")
#: The uv commands' own flags: no configuration file is read, the interpreter is never
#: downloaded, and nothing is built.
_UV_QUIET = ("--quiet", "--no-config")
_PYTHON_ENV_FLAGS = {"UV_PYTHON_DOWNLOADS": "never", "UV_NO_PROGRESS": "1"}


def _root_names(runner: Process, repo: Path, head: str) -> frozenset[str]:
    """The names at the root of the head's tree."""
    result = runner(
        ["git", "ls-tree", "--name-only", head], cwd=repo, env=dict(os.environ), timeout=60,
        shell=False,
    )
    if result.code != 0:
        return frozenset()
    return frozenset(line for line in (result.stdout or "").splitlines() if line)


def _python_inputs(names: frozenset[str]) -> list[str]:
    """The root files that declare the head's Python dependencies, sorted."""
    return sorted(
        name for name in names if name in _PYTHON_FILES or _REQUIREMENTS.match(name)
    )


def _install_python(
    runner: Process, repo: Path, head: str, packet: Path, export: Export, names: frozenset[str],
) -> dict[str, Any]:
    target = packet / PYTHON_DIRECTORY
    deadline = time.monotonic() + PYTHON_TIMEOUT
    with _temporary("saga-review-python-") as work:
        source = work / "head"
        source.mkdir()
        try:
            if not export(source):
                raise NotFetched("the head could not be exported")
            interpreter = shutil.which("python3")
            if interpreter is None:
                raise NotFetched("python3 is not on PATH")
            env = _uv_env(work)
            target.parent.mkdir(parents=True, exist_ok=True)
            uv = _Uv(runner, source, env, [target, work / "home", work / "tmp"], deadline, work,
                     target)
            uv.run(["uv", "venv", *_UV_QUIET, "--relocatable", "--python", interpreter,
                    str(target)], "uv venv")
            python = target / "bin" / "python3"
            if target.is_symlink() or not (target / "pyvenv.cfg").is_file() or not os.path.lexists(
                python
            ):
                raise NotFetched("uv venv wrote no environment")
            configuration = _pyvenv(target / "pyvenv.cfg")
            locked = "uv.lock" in names and "pyproject.toml" in names
            unresolved: list[dict[str, str]] = []
            if locked:
                options, entries = _parse_requirements(uv.run(
                    ["uv", "export", *_UV_QUIET, "--frozen", "--all-groups", "--all-extras",
                     "--no-emit-project", "--no-emit-workspace", "--no-emit-local",
                     "--no-header", "--no-annotate", "--format", "requirements.txt"],
                    "uv export",
                ).stdout)
                pytest = "declared" if "pytest" in entries else "added"
                if pytest == "added":
                    constraints = work / "constraints.txt"
                    constraints.write_text(
                        "".join(_without_hashes(text) + "\n" for text in entries.values()),
                        encoding="utf-8",
                    )
                    _extra_options, extra = _parse_requirements(uv.run(
                        [*_compile(python, _commit_time(runner, repo, head)),
                         "-c", str(constraints), str(_pytest_input(work))],
                        "uv pip compile",
                    ).stdout)
                    for name, text in extra.items():
                        entries.setdefault(name, text)
                source_label = "uv.lock"
            else:
                inputs = _unlocked_inputs(source, names)
                argv = _compile(python, _commit_time(runner, repo, head))
                if "pyproject.toml" in inputs:
                    argv += ["--all-extras", *_group_flags(source / "pyproject.toml")]
                compiled, unresolved = _compile_without_sdists(
                    uv, [*argv, *inputs, str(_pytest_input(work))], work,
                )
                options, entries = _parse_requirements(compiled)
                pytest = "declared" if _declares_pytest(source, inputs) else "added"
                source_label = " ".join(inputs)
            missing = unresolved + _install_entries(uv, python, options, entries, work)
            missing.sort(key=lambda item: item["name"])
            _tidy(target)
            packages = _installed(target)
            if not packages:
                raise NotFetched("uv pip install installed nothing")
            requirements = "".join(f"{line}\n" for line in options) + "".join(
                f"{entries[name]}\n" for name in sorted(entries)
            )
            return {
                "state": "partial" if missing else "installed",
                "directory": PYTHON_DIRECTORY,
                "interpreter": {
                    "implementation": configuration.get("implementation", ""),
                    "version": configuration.get("version_info", ""),
                },
                "source": source_label,
                "pytest": pytest,
                "packages": packages,
                "missing": missing,
                "requirements_sha256": hashlib.sha256(requirements.encode("utf-8")).hexdigest(),
            }
        except NotFetched as exc:
            _remove(target)
            return {"state": "not-installed", "reason": str(exc)}


class _Uv:
    """Runs uv under the watcher, inside the Python install's one shared deadline."""

    def __init__(
        self, runner: Process, cwd: Path, env: Mapping[str, str], watched: list[Path],
        deadline: float, work: Path, target: Path,
    ) -> None:
        self.runner, self.cwd, self.env, self.watched = runner, cwd, env, watched
        self.deadline, self.work, self.target = deadline, work, target

    def remaining(self) -> float:
        return self.deadline - time.monotonic()

    def run(self, argv: list[str], label: str) -> Any:
        seconds = min(FETCH_TIMEOUT, self.remaining())
        if seconds <= 0:
            raise NotFetched(f"{label} timed out")
        return _watched(self.runner, argv, label, self.cwd, self.env, self.watched,
                        seconds=seconds, scrub=self.scrub)

    def scrub(self, text: str) -> str:
        """*text* without the install's temporary paths, so a reason is the same every time."""
        for path, name in ((self.target, "<environment>"), (self.work, "<work>")):
            for form in {str(path), str(path.resolve())}:
                text = text.replace(form, name)
        return text


def _uv_env(work: Path) -> dict[str, str]:
    """The allow-list, a fresh home and temp folder, and the operator's uv cache.

    The cache only saves downloads: every file is checked against the lock's or the compiled
    hashes, and ``--link-mode copy`` keeps the environment from sharing a file with it.
    """
    env = {name: os.environ[name] for name in _ENV_COPIED if name in os.environ}
    for name, folder in (("HOME", "home"), ("TMPDIR", "tmp")):
        path = work / folder
        path.mkdir(mode=0o700)
        env[name] = str(path)
    env["UV_CACHE_DIR"] = _uv_cache()
    env.update(_PYTHON_ENV_FLAGS)
    return env


def _uv_cache() -> str:
    given = os.environ.get("UV_CACHE_DIR")
    if given:
        return given
    xdg = os.environ.get("XDG_CACHE_HOME")
    return str(Path(xdg) / "uv") if xdg else str(Path.home() / ".cache" / "uv")


def _compile(python: Path, when: str) -> list[str]:
    """``uv pip compile`` for *python*, with no build, as of *when*, with hashes."""
    return ["uv", "pip", "compile", *_UV_QUIET, "--python", str(python), "--no-build",
            "--exclude-newer", when, "--generate-hashes", "--no-header", "--no-annotate"]


def _commit_time(runner: Process, repo: Path, head: str) -> str:
    """The head's commit time in UTC: newer releases are left out, so a resolve repeats."""
    result = runner(["git", "show", "-s", "--format=%ct", head], cwd=repo, env=dict(os.environ),
                    timeout=60, shell=False)
    try:
        seconds = int((result.stdout or "").strip())
    except ValueError:
        raise NotFetched("the head's commit time could not be read") from None
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


#: How many packages without a wheel a resolve may set aside before it gives up.
_MAX_SET_ASIDE = 25
_NO_WHEEL = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:==\S+)? has no usable wheels")


def _compile_without_sdists(
    uv: _Uv, argv: list[str], work: Path,
) -> tuple[str, list[dict[str, str]]]:
    """Resolve *argv*; each package uv names as having no wheel is set aside and the resolve
    repeated without it, through an override whose marker never holds.

    Returns the compiled requirements and the packages set aside, with uv's reason.
    """
    overrides = work / "saga-overrides.txt"
    aside: list[dict[str, str]] = []
    while True:
        extra = ["--overrides", str(overrides)] if aside else []
        try:
            return uv.run([*argv, *extra], "uv pip compile").stdout, aside
        except NotFetched as exc:
            found = _NO_WHEEL.search(str(exc))
            name = _normalize(found.group(1)) if found else None
            if name is None or len(aside) >= _MAX_SET_ASIDE or any(
                item["name"] == name for item in aside
            ):
                raise
            aside.append({"name": name, "reason": str(exc)})
            overrides.write_text("".join(f"{item['name']} ; python_version < '0'\n"
                                         for item in aside), encoding="utf-8")


def _pytest_input(work: Path) -> Path:
    path = work / "saga-pytest.in"
    path.write_text("pytest\n", encoding="utf-8")
    return path


def _unlocked_inputs(source: Path, names: frozenset[str]) -> list[str]:
    """The declaring files, relative to the head, with editable and local lines removed."""
    inputs = []
    if "pyproject.toml" in names and (source / "pyproject.toml").is_file():
        inputs.append("pyproject.toml")
    for name in sorted(names):
        path = source / name
        if not _REQUIREMENTS.match(name) or path.is_symlink() or not path.is_file():
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        path.write_text("".join(f"{line}\n" for line in lines
                                if not _LOCAL_LINE.match(line.strip())), encoding="utf-8")
        inputs.append(name)
    return inputs


def _group_flags(pyproject: Path) -> list[str]:
    """``--group`` for every dependency group the head's ``pyproject.toml`` declares."""
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        raise NotFetched("pyproject.toml does not parse") from None
    groups = data.get("dependency-groups")
    flags: list[str] = []
    for name in sorted(groups) if isinstance(groups, Mapping) else []:
        flags += ["--group", f"pyproject.toml:{name}"]
    return flags


def _declares_pytest(source: Path, inputs: Sequence[str]) -> bool:
    for name in inputs:
        text = (source / name).read_text(encoding="utf-8", errors="replace")
        if re.search(r"(^|[\s\"'\[,])pytest\s*([<>=!~;\[\"',]|$)", text, re.MULTILINE):
            return True
    return False


def _parse_requirements(text: str) -> tuple[list[str], dict[str, str]]:
    """The option lines and the pinned entries, by normalized name, from a requirements file.

    An entry spans its continuation lines; it is kept as one line with its hashes.
    """
    joined: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if joined and joined[-1].endswith("\\"):
            joined[-1] = joined[-1][:-1].rstrip() + " " + line
        else:
            joined.append(line)
    options: list[str] = []
    entries: dict[str, str] = {}
    for line in joined:
        line = line.rstrip("\\").strip()
        if line.startswith("-"):
            options.append(line)
            continue
        match = _REQUIREMENT_NAME.match(line)
        if match:
            entries[_normalize(match.group(1))] = line
    return sorted(set(options)), entries


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _without_hashes(text: str) -> str:
    return re.sub(r"\s+--hash=\S+", "", text).strip()


def _install_entries(
    uv: _Uv, python: Path, options: list[str], entries: Mapping[str, str], work: Path,
) -> list[dict[str, str]]:
    """Install every entry in one command; after a failure, each on its own.

    Returns the entries that did not install, with uv's reason, sorted by name.
    """
    base = ["uv", "pip", "install", *_UV_QUIET, "--python", str(python), "--link-mode", "copy",
            "--no-deps", "--no-build", "--require-hashes"]
    every = work / "requirements.txt"
    every.write_text("".join(f"{line}\n" for line in options)
                     + "".join(f"{entries[name]}\n" for name in sorted(entries)), encoding="utf-8")
    try:
        uv.run([*base, "-r", str(every)], "uv pip install")
        return []
    except NotFetched:
        pass
    missing: list[dict[str, str]] = []
    for number, name in enumerate(sorted(entries)):
        one = work / f"requirement-{number}.txt"
        one.write_text("".join(f"{line}\n" for line in options) + f"{entries[name]}\n",
                       encoding="utf-8")
        try:
            uv.run([*base, "-r", str(one)], "uv pip install")
        except NotFetched as exc:
            missing.append({"name": name, "reason": uv.scrub(str(exc))})
    return missing


def _pyvenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip()
    return values


def _tidy(venv: Path) -> None:
    """Remove what uv leaves that differs between runs or invites a write: its empty lock file."""
    lock = venv / ".lock"
    if lock.is_file() or lock.is_symlink():
        lock.unlink()


def _installed(venv: Path) -> list[dict[str, str]]:
    """The distributions in *venv*'s ``site-packages``, by name, from their ``.dist-info``."""
    packages = []
    for site in sorted(venv.glob("lib/python*/site-packages")):
        if site.is_symlink() or not site.is_dir():
            continue
        for info in sorted(site.glob("*.dist-info")):
            name, _sep, version = info.name[: -len(".dist-info")].rpartition("-")
            if name:
                packages.append({"name": _normalize(name), "version": version})
    return sorted(packages, key=lambda item: (item["name"], item["version"]))


# --- the watcher ---------------------------------------------------------------------------------

_WATCHER_MARK = "(saga fetch watcher)"


def _bytes(
    paths: list[Path], limit: int | None = None, deadline: float | None = None,
) -> tuple[int, bool]:
    """The bytes of the regular files under *paths*, not following symlinks, and whether the
    count is complete.

    The count stops early once it passes *limit* or the clock passes *deadline*, so one walk of a
    huge tree cannot keep the watcher from its own deadline. A count cut short by the deadline is
    incomplete, and the watcher never treats it as under the limit.
    """
    total = 0
    for root in paths:
        for folder, _dirs, files in os.walk(root):
            for name in files:
                try:
                    total += os.lstat(os.path.join(folder, name)).st_size
                except OSError:
                    continue
            if limit is not None and total > limit:
                return total, True
            if deadline is not None and time.monotonic() > deadline:
                return total, False
    return total, True


class _Stopped(Exception):
    """The watcher itself was asked to stop."""


def _raise_stopped(_signum: int, _frame: Any) -> None:
    raise _Stopped


def _stop(proc: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()
    proc.wait()


def watch(argv: list[str], watched: list[Path], limit: int, seconds: float) -> int:
    """Run *argv* in its own process group; stop it once *watched* passes *limit* bytes.

    The last check runs after the command ends, so a command quicker than one interval is
    counted too. Returns the command's exit code, :data:`LIMIT_EXIT` or :data:`TIMEOUT_EXIT`.
    However the watcher leaves, short of ``SIGKILL``, the command's process group goes with it:
    ``SIGTERM``, ``SIGINT`` and ``SIGHUP`` stop it, and so does any exception.
    """
    proc = subprocess.Popen(argv, start_new_session=True)  # nosec B603
    deadline = time.monotonic() + seconds
    previous = {sig: signal.signal(sig, _raise_stopped)
                for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        while True:
            try:
                code: int | None = proc.wait(timeout=_WATCH_INTERVAL)
            except subprocess.TimeoutExpired:
                code = None
            used, complete = _bytes(watched, limit, deadline)
            if used > limit:
                print(f"saga: the fetch wrote at least {used} bytes, over its {limit} byte limit "
                      f"{_WATCHER_MARK}", file=sys.stderr)
                return LIMIT_EXIT
            # Fail closed: the command's own code counts only after a complete count.
            if code is not None and complete:
                return code
            if not complete or time.monotonic() > deadline:
                print(f"saga: the fetch ran past {seconds:g} seconds {_WATCHER_MARK}",
                      file=sys.stderr)
                return TIMEOUT_EXIT
    except _Stopped:
        return TIMEOUT_EXIT
    finally:
        if proc.poll() is None:
            _stop(proc)
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(arguments: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run cargo with a byte and a time limit.")
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--seconds", type=float, required=True)
    parser.add_argument("--watch", type=Path, action="append", default=[])
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no command after --")
    try:
        return watch(command, args.watch, args.limit, args.seconds)
    except FileNotFoundError:
        print(f"saga: {command[0]} is not installed {_WATCHER_MARK}", file=sys.stderr)
        return MISSING_EXIT


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
