"""Shared git and runner helpers for the issue 155 scripted-check tests.

The six test modules load this file with importlib. Pytest does not collect it.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = REPO / "plugins" / "saga" / "scripts"
FIXTURES = REPO / "plugins" / "saga" / "tests" / "fixtures" / "review_checks"
PYTEST = f"{sys.executable} -m pytest -q"

_STUB = """#!/bin/sh
for arg in "$@"; do
    case "$arg" in
        --version|-version)
            printf '%s\\n' '0.0.1'
            exit 0
            ;;
    esac
done
exit 0
"""


def load(name: str) -> ModuleType:
    """Load one script. A second test file reuses the module the first file loaded."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    loaded = sys.modules.get(name)
    expected = str(SCRIPTS / f"{name}.py")
    if loaded is not None and getattr(loaded, "__file__", None) == expected:
        return loaded
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


T = load("review_tools")
C = load("review_checks")
R = load("review_records")
F = load("review_formula")


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    )
    return proc.stdout.strip()


def init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "review-checks@example.com")
    git(repo, "config", "user.name", "review-checks")
    git(repo, "config", "commit.gpgsign", "false")


def write(repo: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def commit(repo: Path, message: str, *, allow_empty: bool = False) -> str:
    git(repo, "add", "-A")
    args = ["commit", "-m", message]
    if allow_empty:
        args.append("--allow-empty")
    git(repo, *args)
    return git(repo, "rev-parse", "HEAD")


def make_repo(
    tmp: Path, base_files: dict[str, str], head_files: dict[str, str],
) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    init(repo)
    write(repo, base_files)
    base = commit(repo, "base")
    write(repo, head_files)
    head = commit(repo, "head")
    return repo, base, head


def profile(path: Path, command: str) -> Path:
    path.write_text(
        json.dumps({"functional_test_environment": {"test_command": command}}),
        encoding="utf-8",
    )
    return path


def adapter(check: str) -> Any:
    return next(item for item in C.ADAPTERS if item.id == check)


def run(
    repo: Path,
    base: str,
    head: str,
    profile_path: Path,
    output: Path,
    home: Path,
    adapters: list[Any],
    *,
    framework: bool = False,
    builder: Path | None = None,
    runner: Any = None,
) -> int:
    home.mkdir(parents=True, exist_ok=True)
    return T.run(
        repo, base, head, profile_path, output,
        home=home, builder=builder, adapters=adapters, runner=runner, framework=framework,
    )


def one(
    tmp: Path,
    base_files: dict[str, str],
    head_files: dict[str, str],
    check: str,
    command: str,
    *,
    framework: bool = False,
    builder: Path | None = None,
    runner: Any = None,
) -> tuple[int, Path, Path, str, str]:
    repo, base, head = make_repo(tmp, base_files, head_files)
    output = tmp / "out"
    code = run(
        repo, base, head, profile(tmp / "profile.json", command), output, tmp / "home",
        [adapter(check)], framework=framework, builder=builder, runner=runner,
    )
    return code, output, repo, base, head


def read(output: Path, name: str) -> Any:
    return json.loads((output / name).read_text(encoding="utf-8"))


def valid(output: Path) -> None:
    for record in read(output, "findings.json"):
        assert R.validate(record) == []


def outcomes_for(output: Path, ref: str) -> list[dict[str, Any]]:
    return [
        item for item in read(output, "outcomes.json")["findings"]
        if item["rule"]["ref"] == ref
    ]


def gaps(output: Path) -> list[dict[str, str]]:
    return list(read(output, "degraded.json"))


def builder(finding_id: str, kind: str, path: Path) -> Path:
    record = {
        "kind": "builder_record",
        "schema": R.SCHEMA,
        "unit": "U3",
        "acceptance_criteria": [],
        "declarations": [],
        "reasons": [{
            "kind": kind,
            "finding_id": finding_id,
            "text": "The builder recorded why this finding does not block.",
        }],
    }
    assert R.validate(record) == []
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def git_bin(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    target = shutil.which("git")
    assert target is not None
    link = directory / "git"
    if not link.exists():
        link.symlink_to(target)
    return directory


def prepend(monkeypatch: Any, directory: Path) -> None:
    current = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", str(directory) + os.pathsep + current)


def install_stubs(directory: Path) -> None:
    skipped = {"git", "python3", "python"}
    names = {
        item.tool for item in T.default_adapters()
        if item.tool and item.tool not in skipped
    }
    names.add("uv")
    for name in sorted(names):
        executable(directory / name, _STUB)


def recording_runner(record: list[list[str]]) -> Any:
    script = str(SCRIPTS / "review_checks.py")

    def _run(
        argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int, shell: bool,
    ) -> Any:
        assert shell is False
        record.append(list(argv))
        if script in argv:
            proc = subprocess.run(
                list(argv), cwd=cwd, env=dict(env), timeout=timeout,
                capture_output=True, text=True, check=False,
            )
            return T.ProcessResult(proc.returncode, proc.stdout, proc.stderr)
        if "--version" in argv or "-version" in argv:
            return T.ProcessResult(0, "0.0.1\n")
        return T.ProcessResult(0, "")

    return _run
