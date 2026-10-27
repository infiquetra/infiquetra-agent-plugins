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

For Python (a root ``uv.lock``, ``pyproject.toml`` or ``requirements*.txt``), uv installs prebuilt
wheels into a plain ``<packet>/dependencies/python/site-packages`` with ``--target`` against the
operator's ``python3``, never building one and never starting an interpreter over what it
installed: the frozen lock with every package, group and extra when there is one, otherwise what
the files declare, read by saga and passed to uv only as plain ``name[extras] specifier ; marker``
lines, resolved as of the head's commit time. pytest is added when nothing declares it. The packet
holds no interpreter and no console scripts. A package without a wheel is recorded as missing, and
every reason recorded is a fixed word, never uv's output. The reviewer and the re-run each write
their own small environment whose ``bin`` holds only ``python3`` and ``python`` and whose
``site-packages`` is the packet's folder, read-only, and give it to sandboxed commands only.

Run as a script, this module is that watcher: ``review_dependencies.py --limit N --seconds S
--watch PATH ... -- cargo ...``.
"""

from __future__ import annotations

import argparse
import csv
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
import unicodedata
from datetime import datetime, timezone
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "saga.review_dependencies.v1"
FILE = "dependencies.json"
RUST_DIRECTORY = "dependencies/rust"
PYTHON_DIRECTORY = "dependencies/python/site-packages"
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

    def __init__(self, message: str, output: str = "") -> None:
        super().__init__(message)
        #: The failed command's output, for the caller to classify; never written anywhere.
        self.output = output


def fetch(runner: Process, repo: Path, head: str, packet: Path, export: Export) -> dict[str, Any]:
    """Fetch the head's dependencies into *packet* and return ``dependencies.json``'s content.

    *export* writes the head's tracked files into the folder it is given, without symlinks.
    """
    record: dict[str, Any] = {"schema": SCHEMA}
    if _has_file(runner, repo, head, "Cargo.toml"):
        record["rust"] = _fetch_rust(runner, packet, export)
    python = _python_entry(runner, repo, head, packet, export)
    if python is not None:
        record["python"] = python
    _add_node_entry(record, runner, repo, head, packet, export)
    return record


def _add_node_entry(record: dict[str, Any], runner: Process, repo: Path, head: str,
                    packet: Path, export: Export) -> None:
    """The ``node`` entry, from ``review_dependencies_node`` (imported here: it imports this
    module)."""
    import review_dependencies_node  # noqa: PLC0415

    node = review_dependencies_node.entry(runner, repo, head, packet, export)
    if node is not None:
        record["node"] = node


def rust_vendor(packet: Path) -> Path | None:
    """The packet's vendored Rust sources, or ``None`` when there are none to trust.

    The entry counts only when it says ``fetched`` and names a relative directory inside the
    packet that exists, with no symlink anywhere along the way.
    """
    return _packet_directory(packet, "rust", frozenset({"fetched"}))


def python_environment(packet: Path) -> PythonDependencies | None:
    """The packet's installed Python packages, or ``None`` when there are none to trust.

    The entry counts when it says ``installed`` or ``partial``, records the interpreter version
    it was installed for, and names a relative directory inside the packet, with no symlink along
    the way. The directory is a plain ``site-packages``: the packet holds no interpreter and no
    ``bin``, so nothing a wheel installs can be found by name on a ``PATH``.
    """
    site = _packet_directory(packet, "python", PYTHON_USABLE)
    if site is None:
        return None
    try:
        entry = json.loads((packet / FILE).read_text(encoding="utf-8"))["python"]
        version = str(entry["interpreter"]["version"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        return None
    return PythonDependencies(site=site, version=version)


@dataclass(frozen=True)
class PythonDependencies:
    """A packet's ``site-packages`` and the interpreter version its wheels were chosen for."""

    site: Path
    version: str

    @property
    def minor(self) -> str:
        return ".".join(self.version.split(".")[:2])


def interpreter_version(python: str) -> str | None:
    """*python*'s ``major.minor.micro``, asked of the interpreter itself in isolated mode."""
    try:
        proc = subprocess.run(  # nosec B603
            [python, "-I", "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"],
            capture_output=True, text=True, timeout=30, check=False, env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    version = proc.stdout.strip()
    return version if proc.returncode == 0 and re.fullmatch(r"\d+\.\d+\.\d+", version) else None


def write_python_shim(directory: Path, deps: PythonDependencies, python: str) -> Path | None:
    """A virtual environment in *directory* that saga writes and owns, over the packet's packages.

    ``bin`` holds only ``python3`` and ``python``, links to *python* (the operator's interpreter,
    found on the operator's ``PATH``), and ``lib/pythonX.Y/site-packages`` links to the packet's
    folder, so its ``.pth`` files and import order are a normal environment's. Nothing in the
    packet is ever put on a ``PATH``. Returns the environment, or ``None`` when *python*'s
    major and minor version are not the ones the packages were installed for.
    """
    version = interpreter_version(python)
    if version is None or ".".join(version.split(".")[:2]) != deps.minor:
        return None
    real = Path(os.path.realpath(python))
    (directory / "bin").mkdir(parents=True, exist_ok=True)
    lib = directory / "lib" / f"python{deps.minor}"
    lib.mkdir(parents=True, exist_ok=True)
    (directory / "pyvenv.cfg").write_text(
        f"home = {real.parent}\ninclude-system-site-packages = false\nversion = {version}\n",
        encoding="utf-8",
    )
    for name in ("python3", "python"):
        (directory / "bin" / name).symlink_to(real)
    (lib / "site-packages").symlink_to(deps.site.resolve())
    return directory


def python_shim_env(shim: Path, path: str | None = None) -> dict[str, str]:
    """The shim's ``bin`` first on ``PATH``, and ``VIRTUAL_ENV``: for sandboxed commands only."""
    rest = os.environ.get("PATH", "") if path is None else path
    return {
        "PATH": os.pathsep.join([str(shim / "bin"), *([rest] if rest else [])]),
        "VIRTUAL_ENV": str(shim),
    }


def python_toolchain(shim: Path, deps: PythonDependencies) -> tuple[Path, ...]:
    """What a confined ``python3`` from *shim* must read and map: the shim, the packet's
    packages (compiled extensions load from there), and the ``bin`` and ``lib`` of the install
    the interpreter belongs to, minus any :func:`read_problem`."""
    paths = [shim, deps.site.resolve()]
    try:
        real = (shim / "bin" / "python3").resolve(strict=True)
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
    timed_out: str | None = None,
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
        raise NotFetched(f"{label} exited {result.code}{_detail(result)}",
                         output=f"{result.stdout or ''}{result.stderr or ''}")
    return result


def _detail(result: Any) -> str:
    """The last line of a failed cargo command's output, which says why."""
    lines = (result.stderr or result.stdout or "").strip().splitlines()
    return f": {lines[-1][:200]}" if lines else ""


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
#: The one shape of requirement uv is given: ``name[extras] specifiers ; marker``. No option,
#: no URL, no ``@`` direct reference, no path: nothing that names a file, an index or a host.
_PLAIN = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)"
    r"(?P<extras>\s*\[[A-Za-z0-9._,\s-]*\])?"
    r"(?P<spec>\s*(?:\(\s*)?(?:(?:===|==|!=|~=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+\s*,?\s*)*(?:\))?)"
    r"(?P<marker>\s*;(?P<expression>.*))?$"
)
#: A marker, token by token (PEP 508): quoted strings, the marker variables, ``and``, ``or``,
#: ``in``, ``not``, comparison operators and parentheses. Anything else, an unquoted ``-r`` or
#: ``--index-url`` included, refuses the line, so uv never reads it as an option.
_MARKER_TOKEN = re.compile(
    r"\s*(?:'[^'\\\n]*'|\"[^\"\\\n]*\"|===|==|!=|~=|<=|>=|<|>|\(|\)|[A-Za-z_][A-Za-z0-9_.]*)"
)
_MARKER_WORDS = frozenset({
    "and", "or", "in", "not", "extra", "python_version", "python_full_version", "os_name",
    "sys_platform", "platform_release", "platform_system", "platform_version",
    "platform_machine", "platform_python_implementation", "implementation_name",
    "implementation_version", "os.name", "sys.platform", "platform.version",
    "platform.machine", "platform.python_implementation", "python_implementation",
    "dependency_groups", "extras",
})
_HASH = re.compile(r"--hash=(sha256:[0-9a-f]{64})")
#: The fixed reasons recorded in ``dependencies.json``. uv's own words never reach the packet:
#: its output can repeat whatever a requirement or an index sent it.
REASONS = frozenset({
    "no-wheel", "not-found", "network", "unresolvable", "install-failed", "timeout",
    "size-limit", "uv-missing", "python3-missing", "export-failed", "symlinked-input",
    "lock-without-pyproject", "subfolder-project", "nothing-installed", "head-export",
    "overlap-unresolved",
})
#: The one rule for a file that more than one installed distribution ships: the copy from the
#: distribution whose normalized name sorts last is kept, whatever order uv installed them in.
OVERLAP_RULE = "name-sorts-last"
#: The uv commands' own flags: no configuration file is read and nothing is printed but errors.
_UV_QUIET = ("--quiet", "--no-config")
_PYTHON_ENV_FLAGS = {"UV_PYTHON_DOWNLOADS": "never", "UV_NO_PROGRESS": "1"}
#: How many packages without a wheel a resolve may set aside before it gives up.
_MAX_SET_ASIDE = 25
_NO_WHEEL = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:==\S+)? has no usable wheels")
_NETWORK = re.compile(
    r"Failed to fetch|error sending request|dns error|Connection refused|connection reset|"
    r"tcp connect error|operation timed out|Could not connect|network", re.IGNORECASE)
_NOT_FOUND = re.compile(r"not found in the package registry|was not found in|"
                        r"no versions of|not found in the provided", re.IGNORECASE)
#: Where wheels are copied from uv's cache: an APFS clone on macOS shares blocks until written,
#: and is a separate file, so the packet stays independent of the cache.
_LINK_MODE = "clone" if sys.platform == "darwin" else "copy"


def _tree(runner: Process, repo: Path, head: str, recursive: bool = False) -> dict[str, str]:
    """The head's paths (root only, or every path) and their git modes."""
    argv = ["git", "ls-tree", *(["-r"] if recursive else []), head]
    result = runner(argv, cwd=repo, env=dict(os.environ), timeout=60, shell=False)
    if result.code != 0:
        return {}
    found: dict[str, str] = {}
    for line in (result.stdout or "").splitlines():
        meta, _tab, name = line.partition("\t")
        if name:
            found[name] = meta.split(" ")[0]
    return found


def _python_inputs(names: Mapping[str, str]) -> list[str]:
    """The root files that declare the head's Python dependencies, sorted."""
    return sorted(name for name in names if name in _PYTHON_FILES or _REQUIREMENTS.match(name))


#: A folder name the record may repeat. Names come from the reviewed repository, so anything
#: else (a newline, a control character, a quote, an overlong name) is left out, not cleaned.
_RECORDED_FOLDER = re.compile(r"[A-Za-z0-9._/-]{1,100}")
_MAX_RECORDED_FOLDERS = 20


def _subfolder_projects(runner: Process, repo: Path, head: str) -> list[str] | None:
    """Folders below the root that hold a Python project's declaring file, as many as
    :data:`_MAX_RECORDED_FOLDERS`, each one matching :data:`_RECORDED_FOLDER`; ``None`` when
    there is no such folder at all (an empty list when there are only unsafe names)."""
    folders = set()
    for path in _tree(runner, repo, head, recursive=True):
        folder, _sep, name = path.rpartition("/")
        if folder and (name in _PYTHON_FILES or _REQUIREMENTS.match(name)):
            folders.add(folder)
    if not folders:
        return None
    safe = sorted(folder for folder in folders if _RECORDED_FOLDER.fullmatch(folder))
    return safe[:_MAX_RECORDED_FOLDERS]


def _python_entry(
    runner: Process, repo: Path, head: str, packet: Path, export: Export,
) -> dict[str, Any] | None:
    """The ``python`` entry for the head, or ``None`` when it holds no Python project at all."""
    root = _tree(runner, repo, head)
    inputs = _python_inputs(root)
    if not inputs:
        projects = _subfolder_projects(runner, repo, head)
        if projects is not None:
            return {"state": "not-installed", "reason": "subfolder-project", "projects": projects}
        return None
    if any(root[name] == "120000" for name in inputs):
        return {"state": "not-installed", "reason": "symlinked-input"}
    if "uv.lock" in inputs and "pyproject.toml" not in inputs:
        return {"state": "not-installed", "reason": "lock-without-pyproject"}
    return _install_python(runner, repo, head, packet, export, frozenset(inputs))


class _PythonFailure(Exception):
    """The Python install stopped, for one of :data:`REASONS`."""

    def __init__(self, reason: str) -> None:
        assert reason in REASONS, reason
        super().__init__(reason)
        self.reason = reason


def _install_python(
    runner: Process, repo: Path, head: str, packet: Path, export: Export, inputs: frozenset[str],
) -> dict[str, Any]:
    target = packet / PYTHON_DIRECTORY
    deadline = time.monotonic() + PYTHON_TIMEOUT
    with _temporary("saga-review-python-") as work:
        source = work / "head"
        source.mkdir()
        try:
            if not export(source):
                raise _PythonFailure("head-export")
            for name in inputs:
                if (source / name).is_symlink() or not (source / name).is_file():
                    raise _PythonFailure("symlinked-input")
            interpreter = shutil.which("python3")
            version = interpreter_version(interpreter) if interpreter else None
            if interpreter is None or version is None:
                raise _PythonFailure("python3-missing")
            env = _uv_env(work)
            # The retry and overlap installs count toward the same byte limit as the target.
            uv = _Uv(runner, work, env, [target, work / "home", work / "tmp", work / "trial",
                                         work / "overlap"], deadline)
            dropped: dict[str, int] = {}
            if "uv.lock" in inputs:
                exported = uv.run(
                    ["uv", "export", *_UV_QUIET, "--frozen", "--all-packages", "--all-groups",
                     "--all-extras", "--no-emit-project", "--no-emit-workspace",
                     "--no-emit-local", "--no-header", "--no-annotate",
                     "--format", "requirements.txt", "--project", str(source)],
                    "export-failed",
                ).stdout
                entries = _plain_entries(exported.splitlines(), dropped, hashes=True)
                pytest = "declared" if "pytest" in entries else "added"
                if pytest == "added":
                    constraints = work / "constraints.txt"
                    constraints.write_text("".join(
                        f"{_HASH.sub('', text).strip()}\n" for text in entries.values()
                    ), encoding="utf-8")
                    resolved, _aside = _compile_without_sdists(
                        uv, [*_compile(interpreter, _commit_time(runner, repo, head)),
                             "-c", str(constraints), str(_write(work / "pytest.in", "pytest\n"))],
                        work,
                    )
                    for name, text in _plain_entries(resolved.splitlines(), {}, True).items():
                        entries.setdefault(name, text)
                source_label = "uv.lock"
                unresolved: list[dict[str, str]] = []
            else:
                declared, source_label = _declared(source, inputs, dropped)
                pytest = "declared" if "pytest" in declared else "added"
                wanted = work / "declared.in"
                _write(wanted, "".join(f"{line}\n" for line in declared.values()) + "pytest\n")
                resolved, unresolved = _compile_without_sdists(
                    uv, [*_compile(interpreter, _commit_time(runner, repo, head)), str(wanted)],
                    work,
                )
                entries = _plain_entries(resolved.splitlines(), {}, hashes=True)
            missing = unresolved + _install_set(uv, interpreter, target, entries, work)
            missing.sort(key=lambda item: item["name"])
            overlaps = _resolve_overlaps(uv, interpreter, target, entries, work)
            _tidy(target)
            packages = _installed(target)
            if not packages:
                raise _PythonFailure("nothing-installed")
            requirements = "".join(f"{entries[name]}\n" for name in sorted(entries))
            note = {"overlaps": overlaps} if overlaps else {}
            return {
                "state": "partial" if missing else "installed",
                "directory": PYTHON_DIRECTORY,
                "interpreter": {"version": version},
                "source": source_label,
                "pytest": pytest,
                "packages": packages,
                "missing": missing,
                "dropped": dict(sorted(dropped.items())),
                "requirements_sha256": hashlib.sha256(requirements.encode("utf-8")).hexdigest(),
                **note,
            }
        except _PythonFailure as exc:
            _remove(target)
            return {"state": "not-installed", "reason": exc.reason}


class _Uv:
    """Runs uv under the watcher, inside the Python install's one shared deadline. A failure
    becomes a :class:`_PythonFailure` with a fixed reason; uv's output is kept only in memory,
    to choose that reason and to name a package without a wheel."""

    def __init__(self, runner: Process, cwd: Path, env: Mapping[str, str], watched: list[Path],
                 deadline: float) -> None:
        self.runner, self.cwd, self.env, self.watched = runner, cwd, env, watched
        self.deadline = deadline
        self.last_output = ""

    def run(self, argv: list[str], failed: str) -> Any:
        seconds = min(FETCH_TIMEOUT, self.deadline - time.monotonic())
        if seconds <= 0:
            raise _PythonFailure("timeout")
        try:
            return _watched(self.runner, argv, argv[1], self.cwd, self.env, self.watched,
                            seconds=seconds, missing="uv-missing", timed_out="timeout")
        except NotFetched as exc:
            self.last_output = exc.output
            message = str(exc)
            if message in ("uv-missing", "timeout"):
                raise _PythonFailure(message) from None
            if "byte limit" in message:
                raise _PythonFailure("size-limit") from None
            if _NETWORK.search(exc.output):
                raise _PythonFailure("network") from None
            if _NO_WHEEL.search(exc.output):
                raise _PythonFailure("no-wheel") from None
            if _NOT_FOUND.search(exc.output):
                raise _PythonFailure("not-found") from None
            raise _PythonFailure(failed) from None


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def _uv_env(work: Path) -> dict[str, str]:
    """The allow-list, a fresh home and temp folder, and the operator's uv cache.

    The cache only saves downloads: every file is checked against the lock's or the compiled
    hashes, and the install copies (or, on macOS, clones) out of it, so no file is shared.
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


def _compile(python: str, when: str) -> list[str]:
    """``uv pip compile`` for the operator's *python*, with no build, as of *when*, hashed."""
    return ["uv", "pip", "compile", *_UV_QUIET, "--python", python, "--no-build",
            "--exclude-newer", when, "--generate-hashes", "--no-header", "--no-annotate"]


def _commit_time(runner: Process, repo: Path, head: str) -> str:
    """The head's commit time in UTC: newer releases are left out, so a resolve repeats."""
    result = runner(["git", "show", "-s", "--format=%ct", head], cwd=repo, env=dict(os.environ),
                    timeout=60, shell=False)
    try:
        seconds = int((result.stdout or "").strip())
    except ValueError:
        raise _PythonFailure("unresolvable") from None
    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compile_without_sdists(
    uv: _Uv, argv: list[str], work: Path,
) -> tuple[str, list[dict[str, str]]]:
    """Resolve *argv*; each package uv names as having no wheel is set aside and the resolve
    repeated without it, through an override whose marker never holds.

    Returns the compiled requirements and the packages set aside, with the reason ``no-wheel``.
    """
    overrides = work / "saga-overrides.txt"
    aside: list[dict[str, str]] = []
    while True:
        extra = ["--overrides", str(overrides)] if aside else []
        try:
            return uv.run([*argv, *extra], "unresolvable").stdout, aside
        except _PythonFailure as exc:
            found = _NO_WHEEL.search(uv.last_output) if exc.reason == "no-wheel" else None
            name = _normalize(found.group(1)) if found else None
            if name is None or len(aside) >= _MAX_SET_ASIDE or any(
                item["name"] == name for item in aside
            ):
                raise
            aside.append({"name": name, "reason": "no-wheel"})
            _write(overrides, "".join(f"{item['name']} ; python_version < '0'\n"
                                      for item in aside))


def _logical_lines(lines: Sequence[str]) -> list[str]:
    """Lines with comments removed and continuations joined."""
    joined: list[str] = []
    for raw in lines:
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if joined and joined[-1].endswith("\\"):
            joined[-1] = (joined[-1][:-1].rstrip() + " " + line).strip()
        elif line:
            joined.append(line)
    return [line.rstrip("\\").strip() for line in joined if line.rstrip("\\").strip()]


def _plain(line: str, dropped: dict[str, int], hashes: bool) -> tuple[str, str] | None:
    """``(name, line)`` for a plain requirement, or ``None``, counting what was dropped and why."""
    found = _HASH.findall(line) if hashes else []
    body = _HASH.sub("", line).strip() if hashes else line.strip()
    if body.startswith("-"):
        dropped["options"] = dropped.get("options", 0) + 1
        return None
    if "@" in body.split(";")[0] or "://" in body or "/" in body or "\\" in body:
        dropped["references"] = dropped.get("references", 0) + 1
        return None
    match = _PLAIN.match(body)
    if match is None or "--hash" in body or not _marker_ok(match.group("expression")):
        dropped["unparsed"] = dropped.get("unparsed", 0) + 1
        return None
    text = " ".join(body.split())
    if found:
        text += "".join(f" --hash={item}" for item in found)
    return _normalize(match.group("name")), text


def _marker_ok(expression: str | None) -> bool:
    """True when *expression* (the text after ``;``) is made only of marker tokens."""
    if expression is None:
        return True
    position, tokens = 0, 0
    while position < len(expression):
        if not expression[position:].strip():
            break
        found = _MARKER_TOKEN.match(expression, position)
        if found is None:
            return False
        token = found.group(0).strip()
        if token[0].isalpha() or token[0] == "_":
            if token not in _MARKER_WORDS:
                return False
        position, tokens = found.end(), tokens + 1
    return tokens > 0


def _plain_entries(lines: Sequence[str], dropped: dict[str, int], hashes: bool) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line in _logical_lines(lines):
        kept = _plain(line, dropped, hashes)
        if kept is not None:
            entries[kept[0]] = kept[1]
    return entries


def _declared(
    source: Path, inputs: frozenset[str], dropped: dict[str, int],
) -> tuple[dict[str, str], str]:
    """The head's declared requirements, read here and never by uv, and where they came from.

    From ``pyproject.toml``: ``project.dependencies`` (unless dynamic), every optional
    dependency set (unless dynamic) and every dependency group. From each root
    ``requirements*.txt``: its plain lines; ``-r``, ``-c``, index and other options, URLs, ``@``
    references and paths are dropped and counted, never followed.
    """
    declared: dict[str, str] = {}
    used: list[str] = []
    if "pyproject.toml" in inputs:
        lines, dynamic = _pyproject_requirements(source / "pyproject.toml")
        if lines or not dynamic:
            used.append("pyproject.toml")
        if dynamic:
            dropped["dynamic"] = 1
        for line in lines:
            kept = _plain(line, dropped, hashes=False)
            if kept is not None:
                declared.setdefault(*kept)
    for name in sorted(inputs):
        if not _REQUIREMENTS.match(name):
            continue
        text = (source / name).read_text(encoding="utf-8", errors="replace")
        for name_, line in _plain_entries(text.splitlines(), dropped, hashes=False).items():
            declared.setdefault(name_, line)
        used.append(name)
    return declared, " ".join(used)


def _pyproject_requirements(path: Path) -> tuple[list[str], bool]:
    """The requirement strings ``pyproject.toml`` declares statically, and whether its project
    dependencies are dynamic (then the requirements files stand in for them)."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return [], True
    project = data.get("project") if isinstance(data.get("project"), Mapping) else {}
    raw_dynamic = project.get("dynamic")
    dynamic = set(raw_dynamic) if isinstance(raw_dynamic, list) else set()
    lines: list[str] = []
    if "dependencies" not in dynamic:
        lines += [item for item in project.get("dependencies") or [] if isinstance(item, str)]
    optional = project.get("optional-dependencies")
    if "optional-dependencies" not in dynamic and isinstance(optional, Mapping):
        for name in sorted(optional):
            values = optional[name]
            lines += [item for item in values if isinstance(item, str)] if isinstance(
                values, list) else []
    groups = data.get("dependency-groups")
    if isinstance(groups, Mapping):
        for name in sorted(groups):
            values = groups[name]
            lines += [item for item in values if isinstance(item, str)] if isinstance(
                values, list) else []
    return lines, "dependencies" in dynamic


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _install_set(
    uv: _Uv, python: str, target: Path, entries: Mapping[str, str], work: Path,
) -> list[dict[str, str]]:
    """Install *entries* into *target* with ``--target`` against the operator's *python*.

    The packet's packages are never imported here: uv is pointed at the operator's interpreter,
    and *target* is a plain folder, so no ``.pth`` file a wheel installs runs during prepare.
    When the one transaction fails, each entry is tried on its own in a scratch folder to find
    the ones that cannot install, and the rest are installed again, together, into an empty
    *target*. Returns the entries left out, with a fixed reason, sorted by name.
    """
    def install(names: Sequence[str], into: Path) -> None:
        _install_into(uv, python, into, entries, names, work)

    names = sorted(entries)
    try:
        install(names, target)
        return []
    except _PythonFailure as exc:
        if exc.reason in ("network", "timeout", "size-limit", "uv-missing"):
            raise
    _remove(target)
    missing: list[dict[str, str]] = []
    good: list[str] = []
    for name in names:
        trial = work / "trial"
        _remove(trial)
        try:
            install([name], trial)
            good.append(name)
        except _PythonFailure as exc:
            if exc.reason in ("network", "timeout", "size-limit", "uv-missing"):
                raise
            missing.append({"name": name, "reason": exc.reason})
        finally:
            _remove(trial)
    if good:
        install(good, target)
    return missing


def _install_into(
    uv: _Uv, python: str, into: Path, entries: Mapping[str, str], names: Sequence[str],
    work: Path,
) -> None:
    """One ``uv pip install --target`` of *names* from *entries*, hashes required, no builds."""
    requirements = _write(work / "requirements.txt",
                          "".join(f"{entries[name]}\n" for name in names))
    uv.run(["uv", "pip", "install", *_UV_QUIET, "--python", python, "--target", str(into),
            "--link-mode", _LINK_MODE, "--no-deps", "--no-build", "--require-hashes",
            "-r", str(requirements)], "install-failed")


@dataclass(frozen=True)
class _Overlap:
    """Files more than one installed distribution ships at one path, compared case-folded."""

    #: Each spelling of the path the ``RECORD`` files use; more than one means a case or Unicode
    #: form clash, whose folder spelling on a case-insensitive disk depends on install order.
    spellings: tuple[str, ...]
    #: The distributions' normalized names, sorted.
    names: tuple[str, ...]


def _fold(path: str) -> str:
    """*path* as a case-insensitive, normalization-insensitive disk sees it."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", path).casefold())


_PIN = re.compile(r"==\s*([A-Za-z0-9.!+_-]+)")


def _same_version(pinned: str, folder: str) -> bool:
    """Whether a requirement's pinned version and a ``.dist-info`` folder's name the same one,
    ignoring case and the ``-``/``_``/``.`` separators PEP 440 treats alike."""
    def canon(text: str) -> str:
        return re.sub(r"[-_.]+", ".", text.strip().lower())

    return canon(pinned) == canon(folder)


def _claims(target: Path, entries: Mapping[str, str]) -> dict[str, _Overlap]:
    """Each path in *target* that more than one installed distribution's ``RECORD`` lists, by
    its folded form (:func:`_fold`), so ``Foo/x.py`` and ``foo/x.py`` count as one.

    Which ``.dist-info`` folders are real is decided only from *entries*, the requirements uv
    installed: a folder must be named ``<name>-<version>`` for one of them, with its pinned
    version, one folder per name, and hold a readable ``RECORD`` that is not a symlink. uv
    rewrites each ``RECORD`` to list the files it wrote. Any other ``.dist-info`` folder, or a
    ``RECORD`` that lists a path inside a ``.dist-info`` folder other than its own, means a wheel
    shipped files there, and stops the install (``overlap-unresolved``); such a folder is never
    merely skipped. Paths outside *target* (console scripts under ``../``) and under ``bin`` are
    never shared, and a malformed row is skipped.
    """
    records: dict[str, tuple[str, list[str]]] = {}
    if not target.is_dir() or target.is_symlink():
        return {}
    for info in sorted(target.iterdir(), key=lambda path: path.name):
        if not _fold(info.name).endswith(".dist-info"):
            continue
        raw, _sep, version = info.name[: -len(".dist-info")].rpartition("-")
        name = _normalize(raw)
        pinned = _PIN.search(entries.get(name, ""))
        record = info / "RECORD"
        if (not raw or name not in entries or name in records or info.is_symlink()
                or not info.is_dir() or record.is_symlink() or not record.is_file()
                or (pinned is not None and not _same_version(pinned.group(1), version))):
            raise _PythonFailure("overlap-unresolved")
        try:
            with record.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.reader(handle))
        except (OSError, UnicodeDecodeError, csv.Error):
            raise _PythonFailure("overlap-unresolved") from None
        paths = [path for row in rows if (path := _record_path(row, dist_info=True))]
        records[name] = (_fold(info.name), paths)
    claimed: dict[str, dict[str, set[str]]] = {}
    for name, (own, paths) in records.items():
        for path in paths:
            first = _fold(PurePosixPath(path).parts[0])
            if first.endswith(".dist-info"):
                if first != own:
                    raise _PythonFailure("overlap-unresolved")
                continue
            claimed.setdefault(_fold(path), {}).setdefault(path, set()).add(name)
    found: dict[str, _Overlap] = {}
    for key, spellings in sorted(claimed.items()):
        names = sorted(set().union(*spellings.values()))
        if len(names) > 1:
            found[key] = _Overlap(tuple(sorted(spellings)), tuple(names))
    return found


def _record_path(row: Sequence[Any], dist_info: bool = False) -> str | None:
    """The relative path a ``RECORD`` row names inside the install, or ``None`` to skip the row.

    ``RECORD`` comes from the wheel, so it is untrusted: an empty, absolute, ``.``/``..`` or NUL
    path, a path under ``bin``, a path inside a ``.dist-info`` folder unless *dist_info*, and
    anything else malformed is skipped, never an error.
    """
    try:
        text = row[0] if row else ""
        if not isinstance(text, str) or not text or "\0" in text or "\\" in text:
            return None
        path = PurePosixPath(text)
        parts = path.parts
        if (not parts or path.is_absolute() or ".." in parts or "." in parts
                or _fold(parts[0]) == "bin"
                or (_fold(parts[0]).endswith(".dist-info") and not dist_info)):
            return None
        return path.as_posix()
    except (TypeError, ValueError, IndexError):
        return None


def _resolve_overlaps(
    uv: _Uv, python: str, target: Path, entries: Mapping[str, str], work: Path,
) -> list[dict[str, Any]]:
    """Make every file that two installed distributions ship the same on every prepare.

    uv installs wheels in parallel, so which copy of a shared file is left depends on timing.
    Each such file is replaced by the copy from the distribution whose normalized name sorts
    last (:data:`OVERLAP_RULE`), taken from an install of that distribution alone. Returns one
    note per set of distributions that share files: their names, the one kept, the rule and how
    many files, and nothing else from the packages. A shared file that cannot be taken from
    that install, or one the distributions spell differently only by case or Unicode form,
    stops the Python install (``overlap-unresolved``).
    """
    claims = _claims(target, entries)
    if not claims:
        return []
    by_winner: dict[str, list[str]] = {}
    groups: dict[tuple[str, ...], int] = {}
    for overlap in claims.values():
        if len(overlap.spellings) > 1:
            # Which spelling of a folder a case-insensitive disk keeps depends on install order.
            raise _PythonFailure("overlap-unresolved")
        by_winner.setdefault(overlap.names[-1], []).append(overlap.spellings[0])
        groups[overlap.names] = groups.get(overlap.names, 0) + 1
    trial = work / "overlap"
    for winner, paths in sorted(by_winner.items()):
        if winner not in entries:
            raise _PythonFailure("overlap-unresolved")
        _remove(trial)
        try:
            _install_into(uv, python, trial, entries, [winner], work)
            for path in paths:
                parts = PurePosixPath(path).parts
                _replace_file(trial, trial.joinpath(*parts), target, target.joinpath(*parts))
        finally:
            _remove(trial)
    return [{"names": list(names), "kept": names[-1], "rule": OVERLAP_RULE, "files": count}
            for names, count in sorted(groups.items())]


def _replace_file(source: Path, origin: Path, target: Path, destination: Path) -> None:
    """Replace *destination* in *target* with *origin* from *source*, or stop the install.

    Both must be regular files, not symlinks, reached through real folders inside their roots;
    *destination* may also be missing. Any other shape, or any error while copying, is
    ``overlap-unresolved``; the caller then removes the whole install.
    """
    try:
        if (_through_link(source, origin) or origin.is_symlink() or not origin.is_file()
                or not origin.resolve().is_relative_to(source.resolve())):
            raise _PythonFailure("overlap-unresolved")
        if _through_link(target, destination.parent) or destination.is_symlink() or (
                destination.exists() and not destination.is_file()):
            raise _PythonFailure("overlap-unresolved")
        if not destination.resolve().is_relative_to(target.resolve()):
            raise _PythonFailure("overlap-unresolved")
        destination.unlink(missing_ok=True)
        shutil.copyfile(origin, destination, follow_symlinks=False)
        shutil.copymode(origin, destination, follow_symlinks=False)
    except OSError:
        raise _PythonFailure("overlap-unresolved") from None


def _through_link(root: Path, path: Path) -> bool:
    """True when *path*, or a folder between *root* and it, is a symlink or missing, or when
    *path* is not below *root* at all."""
    if path != root and root not in path.parents:
        return True
    cursor = path
    while cursor != root:
        if cursor.is_symlink() or (cursor != path and not cursor.is_dir()):
            return True
        cursor = cursor.parent
    return False


def _tidy(target: Path) -> None:
    """Remove what differs between runs or could be found by name: uv's empty lock file, and
    the console scripts, which carry the interpreter's absolute path."""
    lock = target / ".lock"
    if lock.is_file() or lock.is_symlink():
        lock.unlink()
    _remove(target / "bin")


def _installed(target: Path) -> list[dict[str, str]]:
    """The distributions in *target*, by name, from their ``.dist-info``."""
    packages = []
    if target.is_dir() and not target.is_symlink():
        for info in sorted(target.glob("*.dist-info")):
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
