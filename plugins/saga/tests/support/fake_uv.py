"""A fake ``uv`` for saga's Python dependency tests: offline, and it never builds anything."""

from __future__ import annotations

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


class FakeUv:
    """git answers ``ls-tree`` and ``show`` from the given names, or runs for real when
    *real_git*; uv is faked, offline.

    ``uv venv`` writes a working virtual environment whose ``python3`` links to this test's own
    interpreter. ``uv pip install`` writes each requested package as a module, unless it is in
    *sdist_only*, which fails the way uv does for a package with no wheel. ``pytest`` gets a
    ``.pth`` back to this run's own pytest, so a re-run can start it.
    """

    def __init__(self, *, exported: str = "", compiled: str = "",
                 sdist_only: frozenset[str] = frozenset(), names: tuple[str, ...] = (),
                 real_git: bool = False) -> None:
        self.exported, self.compiled, self.sdist_only = exported, compiled, sdist_only
        self.names = names
        self.real_git = real_git
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
                 shell: bool, umask: int | None = None) -> Any:
        assert shell is False
        if self.real_git and argv[0] == "git":
            proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True,
                                  check=False, timeout=timeout)
            return Result(proc.returncode, proc.stdout, proc.stderr)
        if argv[:2] == ["git", "ls-tree"]:
            return Result(0, "".join(f"{name}\n" for name in self.names))
        if argv[:2] == ["git", "show"]:
            return Result(0, f"{COMMIT_SECONDS}\n")
        if argv[:2] == ["git", "cat-file"]:
            return Result(1)
        command = unwrap(argv)
        self.calls.append({"argv": command, "cwd": Path(cwd), "env": dict(env)})
        assert command[0] == "uv", command
        if command[1] == "venv":
            return self._venv(Path(command[-1]))
        if command[1] == "export":
            return Result(0, self.exported)
        if command[1:3] == ["pip", "compile"]:
            return self._compile(command)
        if command[1:3] == ["pip", "install"]:
            return self._install(command)
        raise AssertionError(f"unexpected uv command {command}")

    def _venv(self, target: Path) -> Any:
        real = real_interpreter()
        version = ".".join(str(part) for part in sys.version_info[:3])
        (target / "bin").mkdir(parents=True)
        (target / "bin" / "python3").symlink_to(real)
        (target / "lib" / f"python{sys.version_info[0]}.{sys.version_info[1]}"
         / "site-packages").mkdir(parents=True)
        (target / "pyvenv.cfg").write_text(
            f"home = {real.parent}\nimplementation = CPython\nversion_info = {version}\n"
            "include-system-site-packages = false\nrelocatable = true\n", encoding="utf-8",
        )
        (target / ".lock").write_text("", encoding="utf-8")
        return Result(0)

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
        for flag in ("--no-build", "--no-deps", "--require-hashes"):
            assert flag in command, (flag, command)
        assert command[command.index("--link-mode") + 1] == "copy"
        python = Path(command[command.index("--python") + 1])
        site = next((python.parent.parent / "lib").glob("python*/site-packages"))
        requested = Path(command[command.index("-r") + 1]).read_text(encoding="utf-8")
        entries = [line.split()[0] for line in requested.splitlines()
                   if line and not line.startswith("-")]
        for entry in entries:
            name = entry.split("==")[0]
            if name in self.sdist_only:
                return Result(1, "", f"  cause: Because {entry} has no usable wheels and you "
                                      f"require {entry}, we can conclude that your requirements "
                                      "are unsatisfiable.\n")
        for entry in entries:
            name, version = entry.split("==")
            info = site / f"{name.replace('-', '_')}-{version}.dist-info"
            info.mkdir()
            (info / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n", "utf-8")
            if name == "pytest":
                import pytest as running  # noqa: PLC0415

                (site / "saga_test_pytest.pth").write_text(
                    f"{Path(running.__file__).resolve().parent.parent}\n", encoding="utf-8")
            else:
                package = site / name.replace("-", "_")
                package.mkdir()
                (package / "__init__.py").write_text("def two():\n    return 2\n", "utf-8")
        return Result(0)


