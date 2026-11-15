"""A changed file that is not UTF-8 text must not stop the testing leads."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

SCRIPTS = Path(__file__).resolve().parents[3] / "plugins" / "saga" / "scripts"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = _load("review_command")
T = C.review_tools
D = C.review_diff

_LATIN_1 = "# -*- coding: latin-1 -*-\ndef greet():\n    return 'gr\u00fc\u00df'\n".encode("latin-1")
_UTF_8 = "def greet():\n    return 'gr\u00fc\u00df'\n".encode("utf-8")


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, check=True)
    return done.stdout.decode("utf-8").strip()


def _repo(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "a@example.invalid")
    _git(repo, "config", "user.name", "a")
    for name, data in files.items():
        target = repo / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "files")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_head_text_is_none_for_a_file_that_is_not_utf8(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path, {"src/a.py": _LATIN_1})
    cache: dict[str, str | None] = {}

    assert C._head_text(T.subprocess_runner, repo, head, "src/a.py", cache) is None
    assert cache == {"src/a.py": None}


def test_head_text_returns_utf8_text(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path, {"src/a.py": _UTF_8})

    assert C._head_text(T.subprocess_runner, repo, head, "src/a.py", {}) == _UTF_8.decode("utf-8")


def test_head_text_is_none_for_a_missing_file(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path, {"src/a.py": _UTF_8})

    assert C._head_text(T.subprocess_runner, repo, head, "src/missing.py", {}) is None


def test_lead_items_survive_a_changed_file_that_is_not_utf8(tmp_path: Path) -> None:
    repo, head = _repo(tmp_path, {"src/a.py": _LATIN_1, "src/b.py": _UTF_8})
    change = D.Change(files=(
        D.FileChange(path="src/a.py", status="modified", lines=frozenset({2, 3})),
        D.FileChange(path="src/b.py", status="modified", lines=frozenset({1, 2})),
    ))

    items, degraded = C._lead_items([], change, T.subprocess_runner, repo, head)

    assert items == []
    assert degraded == []


def _mutant_finding(path: str, line: int) -> dict[str, object]:
    return {
        "kind": "finding", "lens": "testing", "language": "python",
        "statement": "A mutant survived (core/Not).",
        "rule": {"row": "testing.surviving-mutant", "ref": "surviving-mutant"},
        "location": {"scope": "lines", "file": path, "anchor": f"{path}:{line}",
                     "lines": {"start": line, "end": line}, "function": None},
        "source": {"kind": "tool", "name": "review-checks", "version": "1.0.0"},
    }


def test_a_lead_in_a_file_that_is_not_utf8_keeps_its_line_and_loses_only_the_function(
    tmp_path: Path,
) -> None:
    repo, head = _repo(tmp_path, {"src/a.py": _LATIN_1, "src/b.py": _UTF_8})
    change = D.Change(files=(
        D.FileChange(path="src/a.py", status="modified", lines=frozenset({3})),
        D.FileChange(path="src/b.py", status="modified", lines=frozenset({2})),
    ))
    findings = [_mutant_finding("src/a.py", 3), _mutant_finding("src/b.py", 2)]

    items, degraded = C._lead_items(findings, change, T.subprocess_runner, repo, head)

    assert degraded == []
    located = {item["location"]["file"]: item["location"] for item in items}
    assert located["src/a.py"]["lines"] == {"start": 3, "end": 3}
    assert located["src/a.py"]["function"] is None
    assert located["src/b.py"]["lines"] == {"start": 2, "end": 2}
    assert located["src/b.py"]["function"] == "greet"
