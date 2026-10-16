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


def _prelude_list(root: Path, *, env: dict[str, str] | None = None) -> list[str]:
    code = T.TRACKED_PRELUDE + (
        f"\nimport sys\nsys.stdout.write(chr(0).join(str(p) for p in tracked_files({str(root)!r})))\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, check=True, env=env,
    )
    return [os.fsdecode(name) for name in proc.stdout.split(b"\0")] if proc.stdout else []


def test_a_tracked_path_under_a_symlinked_directory_is_dropped(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The review's P1: ``is_file`` follows ancestors, so the link must be refused above the leaf."""
    outside = tmp_path / "outside"
    H.write(outside, {"secret.txt": "old_name\n", "leak.sh": "echo leaked\n"})
    H.write(repo, {"linked/secret.txt": "x\n", "linked/leak.sh": "echo hi\n", "kept/ok.txt": "y\n"})
    H.commit(repo, "tracked directory")
    for name in ("secret.txt", "leak.sh"):
        (repo / "linked" / name).unlink()
    (repo / "linked").rmdir()
    (repo / "linked").symlink_to(outside)
    found = _rel(repo, T.scan_files(repo))
    assert "kept/ok.txt" in found
    assert not [name for name in found if name.startswith("linked/")]
    assert _prelude_list(repo) == [str(path) for path in T.scan_files(repo)]
    assert not [path for path in H.C._walk(repo) if "linked" in path.parts]
    shell = _import("review_adapters_shell")
    dest = tmp_path / "dest"
    dest.mkdir()
    called = _run_wrapper(
        shell._SHELLCHECK_WRAPPER, [str(repo), str(dest)], tmp_path, "shellcheck", monkeypatch,
    )
    assert "leak.sh" not in called
    assert not (dest / "linked").exists()


def test_changed_names_never_reads_through_a_symlinked_directory(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    H.write(outside, {"caller.py": "import a\n\nvalue = a.old_name()\n"})
    base = {"a.py": "def old_name():\n    return 1\n", "linked/caller.py": "z = 1\n"}
    head = {"a.py": "def new_name():\n    return 1\n", "linked/caller.py": "z = 1\n"}
    repo, base_sha, _head_sha = H.make_repo(tmp_path, base, head)
    (repo / "linked" / "caller.py").unlink()
    (repo / "linked").rmdir()
    (repo / "linked").symlink_to(outside)
    assert H.C.changed_names(repo, base_sha)["hits"] == []


def test_names_with_a_carriage_return_a_newline_or_a_quote_are_listed(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    H.init(root)
    names = ["cr\rname.py", "new\nline.py", 'quo"te.py', "sp ace.py"]
    H.write(root, {name: "x = 1\n" for name in names})
    H.commit(root, "odd names")
    assert _rel(root, T.scan_files(root)) == sorted(names)
    assert _prelude_list(root) == [str(path) for path in T.scan_files(root)]


def _git_stub(directory: Path, root: Path) -> dict[str, str]:
    """A ``git`` whose ls-tree prints a name that is not UTF-8, then ``ok.py``."""
    H.executable(directory / "git", (
        "#!/bin/sh\n"
        'case "$1" in\n'
        f"  rev-parse) printf '%s\\n' '{root}' ;;\n"
        "  ls-tree) printf 'caf\\351.py\\0ok.py\\0' ;;\n"
        "esac\n"
    ))
    return {**os.environ, "PATH": f"{directory}{os.pathsep}{os.environ['PATH']}"}


def test_a_name_that_is_not_utf8_does_not_break_the_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "plain"
    H.write(root, {"ok.py": "x = 1\n"})
    env = _git_stub(tmp_path / "bin", root.resolve())
    monkeypatch.setenv("PATH", env["PATH"])
    assert _rel(root, T.scan_files(root)) == ["ok.py"]
    assert _prelude_list(root, env=env) == [str(root / "ok.py")]


@pytest.fixture
def with_submodule(tmp_path: Path) -> Path:
    inner = tmp_path / "inner"
    H.init(inner)
    H.write(inner, {"lib.py": "a = 1\n", "docs/lib.md": "# lib\n"})
    H.commit(inner, "inner")
    outer = tmp_path / "outer"
    H.init(outer)
    H.write(outer, {"top.py": "t = 1\n"})
    H.commit(outer, "outer")
    H.git(outer, "-c", "protocol.file.allow=always", "submodule", "add", str(inner), "vendor/sub")
    H.commit(outer, "submodule")
    H.write(outer, {"vendor/sub/junk.py": "j = 1\n", "vendor/sub/target/gen.py": "g = 1\n"})
    return outer


def test_a_checked_out_submodule_contributes_its_tracked_files(with_submodule: Path) -> None:
    found = _rel(with_submodule, T.scan_files(with_submodule))
    assert found == [
        ".gitmodules", "top.py", "vendor/sub/docs/lib.md", "vendor/sub/lib.py",
    ]
    assert _prelude_list(with_submodule) == [
        str(path) for path in T.scan_files(with_submodule)
    ]


def test_a_submodule_path_in_the_prune_set_is_dropped(with_submodule: Path) -> None:
    found = _rel(with_submodule, T.scan_files(with_submodule, frozenset({".git", "sub"})))
    assert found == [".gitmodules", "top.py"]


def test_a_submodule_that_is_not_checked_out_lists_nothing_under_it(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    H.init(outer)
    H.write(outer, {"top.py": "t = 1\n"})
    H.commit(outer, "outer")
    (outer / "vendor" / "sub").mkdir(parents=True)
    H.git(
        outer, "update-index", "--add", "--cacheinfo",
        "160000," + H.git(outer, "rev-parse", "HEAD") + ",vendor/sub",
    )
    H.git(outer, "commit", "-m", "gitlink only")
    assert _rel(outer, T.scan_files(outer)) == ["top.py"]


WORKFLOWS = {
    ".github/workflows/ci.yml": "name: ci\non: push\njobs: {}\n",
    ".github/workflows/notes.txt": "not a workflow\n",
}


@pytest.fixture
def with_workflows(tmp_path: Path) -> Path:
    root = tmp_path / "wf"
    H.init(root)
    H.write(root, WORKFLOWS)
    H.commit(root, "workflows")
    H.write(root, {".github/workflows/scratch.yml": "name: scratch\non: push\njobs: {}\n"})
    return root


def test_the_zizmor_wrapper_copies_only_tracked_workflows(
    with_workflows: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflows = _import("review_adapters_workflows")
    dest = tmp_path / "dest"
    dest.mkdir()
    called = _run_wrapper(
        workflows._ZIZMOR_WRAPPER, [str(with_workflows), str(dest)], tmp_path, "zizmor",
        monkeypatch,
    )
    assert called
    copied = sorted(path.name for path in (dest / ".github" / "workflows").iterdir())
    assert copied == ["ci.yml"]


def test_the_actionlint_wrapper_names_only_tracked_workflows(
    with_workflows: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflows = _import("review_adapters_workflows")
    dest = tmp_path / "dest"
    dest.mkdir()
    config = tmp_path / "actionlint.yaml"
    config.write_text("{}\n", encoding="utf-8")
    called = _run_wrapper(
        workflows._ACTIONLINT_WRAPPER, [str(with_workflows), str(dest), str(config)], tmp_path,
        "actionlint", monkeypatch,
    )
    assert ".github/workflows/ci.yml" in called
    assert "scratch.yml" not in called
    assert sorted(path.name for path in (dest / ".github" / "workflows").iterdir()) == ["ci.yml"]


def test_actionlint_is_not_invoked_for_a_workflow_that_is_not_tracked(tmp_path: Path) -> None:
    root = tmp_path / "wf"
    H.init(root)
    H.write(root, {"README.md": "# x\n"})
    H.commit(root, "readme")
    H.write(root, {".github/workflows/scratch.yml": "name: scratch\n"})
    workflows = _import("review_adapters_workflows")
    context = T.ScanContext(repo=root, root=root, home=tmp_path / "home")
    assert workflows._invoke_actionlint(context) == []


def test_a_workflow_symlinked_outside_the_root_is_not_copied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "wf"
    H.init(root)
    H.write(root, {".github/workflows/ci.yml": "name: ci\n"})
    H.commit(root, "ci")
    outside = tmp_path / "outside.yml"
    outside.write_text("name: secret\n", encoding="utf-8")
    (root / ".github" / "workflows" / "ci.yml").unlink()
    (root / ".github" / "workflows" / "ci.yml").symlink_to(outside)
    workflows = _import("review_adapters_workflows")
    dest = tmp_path / "dest"
    dest.mkdir()
    _run_wrapper(workflows._ZIZMOR_WRAPPER, [str(root), str(dest)], tmp_path, "zizmor", monkeypatch)
    assert not (dest / ".github" / "workflows" / "ci.yml").exists()
