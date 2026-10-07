"""The diff reader reports the added and modified lines git reports (issue 151)."""

from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D = _load("review_diff")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("review diff tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-tools@example.com")
    _git(repo, "config", "user.name", "review-tools")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_added_modified_and_deleted_lines_match_git(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "kept.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (repo / "gone.txt").write_text("delete me\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "kept.txt").write_text("one\nTWO\nthree\nfour\n", encoding="utf-8")
    (repo / "added.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    (repo / "gone.txt").unlink()
    head = _commit(repo, "head")

    change = D.read(repo, base, head)
    by_path = {item.path: item for item in change.files}
    assert by_path["kept.txt"].status == "modified"
    assert by_path["kept.txt"].lines == frozenset({2, 4})
    assert by_path["added.txt"].status == "added"
    assert by_path["added.txt"].lines == frozenset({1, 2})
    assert by_path["gone.txt"].status == "deleted"
    assert by_path["gone.txt"].lines == frozenset()


def test_a_pure_rename_has_no_changed_lines_and_an_edit_keeps_only_the_edit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "old.txt").write_text("one\ntwo\n", encoding="utf-8")
    base = _commit(repo, "base")
    _git(repo, "mv", "old.txt", "new.txt")
    renamed = _commit(repo, "rename")
    pure = D.read(repo, base, renamed)
    assert len(pure.files) == 1
    assert pure.files[0].path == "new.txt"
    assert pure.files[0].status == "renamed"
    assert pure.files[0].lines == frozenset()
    assert pure.files[0].old_path == "old.txt"

    (repo / "new.txt").write_text("one\nTWO\n", encoding="utf-8")
    edited = _commit(repo, "edit")
    change = D.read(repo, renamed, edited)
    assert change.files[0].status == "modified"
    assert change.lines_for("new.txt") == frozenset({2})


def test_a_binary_file_contributes_no_lines(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "note.txt").write_text("text\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "blob.bin").write_bytes(b"\0\1\2")
    head = _commit(repo, "head")
    change = D.read(repo, base, head)
    binary = next(item for item in change.files if item.path == "blob.bin")
    assert binary.status == "binary"
    assert binary.lines == frozenset()
    assert change.lines_for("blob.bin") == frozenset()


def test_a_revision_that_is_not_a_commit_raises(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    (repo / "note.txt").write_text("text\n", encoding="utf-8")
    head = _commit(repo, "base")
    with pytest.raises(D.ReviewDiffError):
        D.read(repo, "not-a-commit", head)
