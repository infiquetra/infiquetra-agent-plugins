"""A fake ``uv`` for saga's Python dependency tests: offline, and it never builds anything."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

COMMIT_SECONDS = "1767225600"  # 2026-01-01T00:00:00Z
HASH_A = "--hash=sha256:" + "aa" * 32
HASH_B = "--hash=sha256:" + "bb" * 32
EXPORTED = (
    f"inertdep==1.0.0 \\\n    {HASH_A}\n"
    f"otherdep==2.0.0 ; python_full_version >= '3.10' \\\n    {HASH_B}\n"
)
PYTEST = f"pytest==9.0.0 \\\n    {HASH_B}\n"


class Result:
    def __init__(self, code: int, stdout: str = "", stderr: str = "") -> None:
        self.code, self.stdout, self.stderr = code, stdout, stderr


def real_interpreter() -> Path:
    return Path(os.path.realpath(sys.executable))


def unwrap(argv: list[str]) -> list[str]:
    """The command inside the fetch watcher's argument vector."""
    assert argv[:2] == [sys.executable, "-I"] and "--" in argv, argv
    return argv[argv.index("--") + 1:]


def _entries(text: str) -> list[str]:
    return [line.split()[0] for line in text.splitlines()
            if line.strip() and not line.startswith(("-", " "))]


class FakeUv:
    """git answers ``ls-tree`` and ``show`` from the given names (a name ending in ``@`` is a
    symlink), or runs for real when *real_git*; uv is faked, offline.

    ``uv pip install --target`` writes each requested package as a module, unless it is in
    *sdist_only*, which fails the way uv does for a package with no wheel. Each package in
    *shared* also ships ``sharedpkg/__init__.py``, with its own name in it, and every package
    gets a ``RECORD`` listing every file written, as uv rewrites it. *ships* adds files to a
    package, by package name. Packages install in the requirements
    file's order, or the reverse with *reverse*, and a later one overwrites a shared file, as
    uv's parallel install may. ``pytest`` gets a
    ``.pth`` back to this run's own pytest, so a re-run can start it. Every requirements file
    uv is given is kept in ``inputs``.
    """

    def __init__(self, *, exported: str = "", compiled: str = "",
                 sdist_only: frozenset[str] = frozenset(), names: tuple[str, ...] = (),
                 real_git: bool = False, fail_install: str = "",
                 shared: frozenset[str] = frozenset(), reverse: bool = False,
                 ships: dict[str, dict[str, str]] | None = None) -> None:
        self.exported, self.compiled, self.sdist_only = exported, compiled, sdist_only
        self.shared, self.reverse, self.ships = shared, reverse, ships or {}
        self.raw: list[list[str]] = []
        self.names = names
        self.real_git = real_git
        self.fail_install = fail_install
        self.calls: list[dict[str, Any]] = []
        self.inputs: list[str] = []

    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
                 shell: bool, umask: int | None = None) -> Any:
        assert shell is False
        if self.real_git and argv[0] == "git":
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                                  check=False, timeout=timeout)
            return Result(proc.returncode, proc.stdout, proc.stderr)
        if argv[:2] == ["git", "ls-tree"]:
            lines = []
            for name in self.names:
                mode = "120000 blob" if name.endswith("@") else "100644 blob"
                lines.append(f"{mode} {'0' * 40}\t{name.rstrip('@')}\n")
            if "-r" not in argv:
                lines = [line for line in lines if "/" not in line.split("\t")[1]]
            return Result(0, "".join(lines))
        if argv[:2] == ["git", "show"]:
            return Result(0, f"{COMMIT_SECONDS}\n")
        if argv[:2] == ["git", "cat-file"]:
            return Result(1)
        command = unwrap(argv)
        self.raw.append(list(argv))
        self.calls.append({"argv": command, "cwd": Path(cwd), "env": dict(env)})
        assert command[0] == "uv", command
        for index, part in enumerate(command[:-1]):
            if part in ("-r", "-c", "--overrides"):
                self.inputs.append(Path(command[index + 1]).read_text(encoding="utf-8"))
        if command[-1].endswith((".in", ".txt")) and command[1:3] == ["pip", "compile"]:
            self.inputs.append(Path(command[-1]).read_text(encoding="utf-8"))
        if command[1] == "export":
            return Result(0, self.exported)
        if command[1:3] == ["pip", "compile"]:
            return self._compile(command)
        if command[1:3] == ["pip", "install"]:
            return self._install(command)
        raise AssertionError(f"unexpected uv command {command}")

    def _compile(self, command: list[str]) -> Any:
        assert "--no-build" in command and "--generate-hashes" in command
        when = command[command.index("--exclude-newer") + 1]
        assert self.real_git or when == "2026-01-01T00:00:00Z", when
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", when), when
        names = {line.split("==")[0] for line in self.compiled.splitlines() if "==" in line}
        blocked = sorted(names & self.sdist_only)
        if "--overrides" in command:
            aside = Path(command[command.index("--overrides") + 1]).read_text(encoding="utf-8")
            blocked = [name for name in blocked if f"{name} ;" not in aside]
        if blocked:
            return Result(1, "", f"  x No solution found when resolving dependencies:\n"
                                 f"  cause: Because {blocked[0]}==0.6.2 has no usable wheels and "
                                 "you require it, we can conclude that your requirements are "
                                 "unsatisfiable.\n")
        lines = [line for line in self.compiled.splitlines(keepends=True)
                 if line.split("==")[0] not in self.sdist_only or "==" not in line]
        return Result(0, "".join(lines))

    def _install(self, command: list[str]) -> Any:
        for flag in ("--no-build", "--no-deps", "--require-hashes", "--target"):
            assert flag in command, (flag, command)
        assert command[command.index("--link-mode") + 1] in ("copy", "clone")
        if self.fail_install:
            return Result(2, "", self.fail_install)
        target = Path(command[command.index("--target") + 1])
        entries = _entries(Path(command[command.index("-r") + 1]).read_text(encoding="utf-8"))
        for entry in entries:
            if entry.split("==")[0] in self.sdist_only:
                return Result(1, "", f"  cause: Because {entry} has no usable wheels and you "
                                     f"require {entry}, we can conclude that your requirements "
                                     "are unsatisfiable.\n")
        target.mkdir(parents=True, exist_ok=True)
        (target / ".lock").write_text("", encoding="utf-8")
        (target / "bin").mkdir(exist_ok=True)
        for entry in (reversed(entries) if self.reverse else entries):
            name, version = entry.split("==")
            info = target / f"{name.replace('-', '_')}-{version}.dist-info"
            info.mkdir(exist_ok=True)
            files = {f"{info.name}/METADATA": f"Name: {name}\nVersion: {version}\n",
                     # A console script, as a wheel would install: never kept in the packet.
                     f"../../bin/{name}": "#!/bin/sh\nexit 0\n"}
            if name == "pytest":
                import pytest as running  # noqa: PLC0415

                files["saga_test_pytest.pth"] = (
                    f"{Path(running.__file__).resolve().parent.parent}\n")
            else:
                files[f"{name.replace('-', '_')}/__init__.py"] = "def two():\n    return 2\n"
            if name in self.shared:
                files["sharedpkg/__init__.py"] = f"SHIPPED_BY = {name!r}\n"
            files.update(self.ships.get(name, {}))
            rows = []
            for relative, text in files.items():
                path = target / "bin" / name if relative.startswith("../") else target / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, "utf-8")
                digest = base64.urlsafe_b64encode(
                    hashlib.sha256(text.encode()).digest()).rstrip(b"=").decode()
                rows.append(f"{relative},sha256={digest},{len(text.encode())}\n")
            rows.append(f"{info.name}/RECORD,,\n")
            (info / "RECORD").write_text("".join(rows), "utf-8")
        return Result(0)
