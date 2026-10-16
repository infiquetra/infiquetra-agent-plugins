"""Review checks and adapters read only the files git tracks at HEAD (issue 252)."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest


def _harness() -> Any:
    path = Path(__file__).resolve().parent / "review_check_harness.py"
    spec = importlib.util.spec_from_file_location("review_check_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = _harness()
T = H.T

TRACKED = {
    ".gitignore": "ignored/\n",
    "src/app.py": "x = 1\n",
    "src/notes.md": "# Notes\n",
    "scripts/run.sh": "echo hi\n",
    "infra/stack.yaml": "Resources: {}\n",
    "infra/other.template": "Resources: {}\n",
    "requirements.txt": "requests\n",
    "web/pnpm-lock.yaml": "lockfileVersion: 9\n",
    "web/package.json": "{}\n",
    "crate/Cargo.toml": "[package]\n",
}
# Files a tool left in the copy, or that the repository ignores. None is a repository file.
UNTRACKED = {
    "target/debug/gen.py": "y = 2\n",
    "target/debug/gen.md": "# Gen\n",
    "target/debug/gen.sh": "echo no\n",
    "target/debug/stack.yaml": "Resources: {}\n",
    "mutants.out/requirements.txt": "flask\n",
    "mutants.out/pnpm-lock.yaml": "lockfileVersion: 9\n",
    "ignored/cache.py": "z = 3\n",
    "ignored/cache.md": "# Cache\n",
    "crate/target/Cargo.toml": "[package]\n",
    "web/node_modules/pnpm-lock.yaml": "lockfileVersion: 9\n",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed repository with a tool's leftovers written after the commit."""
    root = tmp_path / "repo"
    H.init(root)
    H.write(root, TRACKED)
    H.commit(root, "head")
    H.write(root, UNTRACKED)
    return root


def _rel(root: Path, paths: Any) -> list[str]:
    return sorted(Path(item).relative_to(root).as_posix() for item in paths)


def test_scan_files_lists_only_the_tracked_files(repo: Path) -> None:
    assert _rel(repo, T.scan_files(repo)) == sorted(TRACKED)


def test_scan_files_lists_the_same_files_before_and_after_a_tool_writes(repo: Path) -> None:
    after = _rel(repo, T.scan_files(repo))
    for name in UNTRACKED:
        (repo / name).unlink()
    assert _rel(repo, T.scan_files(repo)) == after


def test_a_pruned_directory_is_dropped_even_when_git_tracks_it(repo: Path) -> None:
    H.write(repo, {"vendor/lib.py": "a = 1\n", "src/vendor/keep.py": "b = 2\n"})
    H.commit(repo, "vendor")
    found = _rel(repo, T.scan_files(repo, frozenset({".git", "vendor"})))
    assert "vendor/lib.py" not in found
    assert "src/vendor/keep.py" not in found
    assert "src/app.py" in found


def test_a_tracked_file_that_is_gone_from_disk_is_not_listed(repo: Path) -> None:
    (repo / "src" / "app.py").unlink()
    assert "src/app.py" not in _rel(repo, T.scan_files(repo))


def test_a_symlink_is_listed_as_a_path_and_not_followed(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text("q = 1\n", encoding="utf-8")
    (repo / "link.py").symlink_to(outside)
    H.commit(repo, "link")
    assert "link.py" in _rel(repo, T.scan_files(repo))


def test_a_root_that_is_not_a_git_repository_falls_back_to_every_file(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    H.write(plain, {**TRACKED, **UNTRACKED, ".git/config": "x\n"})
    found = _rel(plain, T.scan_files(plain, frozenset({".git", "node_modules"})))
    assert ".git/config" not in found
    assert "web/node_modules/pnpm-lock.yaml" not in found
    assert set(TRACKED) | (set(UNTRACKED) - {"web/node_modules/pnpm-lock.yaml"}) == set(found)


def test_a_directory_inside_a_repository_is_not_read_as_the_repository(repo: Path) -> None:
    """A subdirectory is not a scan root: git would list the enclosing repository's files."""
    inner = repo / "target"
    found = _rel(inner, T.scan_files(inner))
    assert found == sorted(
        name.removeprefix("target/") for name in UNTRACKED if name.startswith("target/")
    )


def test_the_wrapper_prelude_lists_what_scan_files_lists(repo: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    H.write(plain, {**TRACKED, **UNTRACKED})
    for root in (repo, plain, repo / "target"):
        code = T.TRACKED_PRELUDE + f"\nfor p in tracked_files({str(root)!r}): print(p)\n"
        proc = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        )
        assert proc.stdout.splitlines() == [str(path) for path in T.scan_files(root)]


def _import(name: str) -> Any:
    return H.load(name)


def _python_files(root: Path) -> list[str]:
    return _import("review_adapters_python")._py_rels(root)


def _markdown_files(root: Path) -> list[str]:
    return _import("review_adapters_markdown")._markdown_files(root)


def _lockfiles(root: Path) -> list[str]:
    found = _import("review_adapters_all_languages")._lockfiles(root)
    return _rel(root, found)


def _requirements(root: Path) -> list[str]:
    python = _import("review_adapters_python")
    context = T.ScanContext(repo=root, root=root, home=root)
    argv = python._invoke_pip_audit(context)
    return sorted(token for token in argv if token.endswith(".txt"))


def _language_walk(language: str) -> Callable[[Path], list[str]]:
    def walk(root: Path) -> list[str]:
        return _rel(root, _import(f"review_adapters_{language}")._walk(root))

    return walk


@pytest.mark.parametrize(
    ("walk", "expected"),
    [
        (_python_files, ["src/app.py"]),
        (_markdown_files, ["src/notes.md"]),
        (_lockfiles, ["requirements.txt", "web/pnpm-lock.yaml"]),
        (_requirements, ["requirements.txt"]),
    ],
    ids=["python", "markdown", "lockfiles", "pip-audit"],
)
def test_an_adapter_walk_sees_only_tracked_files(
    repo: Path, walk: Callable[[Path], list[str]], expected: list[str],
) -> None:
    assert walk(repo) == expected


@pytest.mark.parametrize(
    ("language", "marker", "leftover"),
    [
        ("rust", "crate/Cargo.toml", "crate/target/Cargo.toml"),
        ("typescript", "web/package.json", "web/node_modules/pnpm-lock.yaml"),
    ],
)
def test_a_language_adapter_walk_sees_only_tracked_files(
    repo: Path, language: str, marker: str, leftover: str,
) -> None:
    found = _language_walk(language)(repo)
    assert marker in found
    assert leftover not in found
    assert set(found) <= set(TRACKED)


@pytest.mark.parametrize("language", ["dart", "swift"])
def test_the_other_language_walks_drop_a_tool_cache(repo: Path, language: str) -> None:
    cache = {"dart": ".dart_tool/x.dart", "swift": ".build/x.swift"}[language]
    H.write(repo, {cache: "x\n"})
    assert cache not in _language_walk(language)(repo)


def _stub_tool(directory: Path, name: str, log: Path) -> None:
    H.executable(directory / name, f'#!/bin/sh\nprintf "%s\\n" "$@" >> "{log}"\necho "[]"\n')


def _run_wrapper(
    wrapper: str, args: list[str], tmp: Path, tool: str, monkeypatch: pytest.MonkeyPatch,
) -> str:
    log = tmp / "tool.log"
    _stub_tool(tmp / "bin", tool, log)
    monkeypatch.setenv("PATH", f"{tmp / 'bin'}{os.pathsep}{os.environ['PATH']}")
    subprocess.run(
        [sys.executable, "-c", wrapper, *args], capture_output=True, text=True, check=False,
    )
    return log.read_text(encoding="utf-8") if log.exists() else ""


def test_the_shellcheck_wrapper_copies_only_tracked_scripts(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    shell = _import("review_adapters_shell")
    dest = tmp_path / "dest"
    dest.mkdir()
    called = _run_wrapper(
        shell._SHELLCHECK_WRAPPER, [str(repo), str(dest)], tmp_path, "shellcheck", monkeypatch,
    )
    assert "scripts/run.sh" in called
    assert "target/debug/gen.sh" not in called
    assert not (dest / "target").exists()


def test_the_cfn_lint_wrapper_copies_only_tracked_templates(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    infra = _import("review_adapters_infrastructure")
    dest = tmp_path / "dest"
    dest.mkdir()
    called = _run_wrapper(
        infra._CFN_WRAPPER, [str(repo), str(dest)], tmp_path, "cfn-lint", monkeypatch,
    )
    assert "infra/stack.yaml" in called
    assert "infra/other.template" in called
    assert "target/debug/stack.yaml" not in called


def test_the_checkov_wrapper_copies_only_tracked_templates(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    infra = _import("review_adapters_infrastructure")
    dest = tmp_path / "dest"
    dest.mkdir()
    _run_wrapper(
        infra._CHECKOV_WRAPPER, ["cfn", str(repo), str(dest)], tmp_path, "checkov", monkeypatch,
    )
    copied = sorted(
        path.relative_to(dest).as_posix() for path in dest.rglob("*") if path.is_file()
    )
    assert "infra/stack.yaml" in copied
    assert not [name for name in copied if name.startswith(("target/", "mutants.out/"))]
