"""One coverage adapter agrees across LCOV, Cobertura, and coverage.py (issue 151)."""

from __future__ import annotations

import importlib.util
import json
import socket
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_tools"


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
C = _load("coverage_lines")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("coverage tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _change(*lines: int, path: str = "src/app.py") -> Any:
    return D.Change(files=(D.FileChange(path, "added", frozenset(lines)),))


def test_three_formats_agree_on_the_uncovered_changed_branch() -> None:
    change = _change(2, 4, 10)
    reports = [
        C.parse_lcov((FIXTURES / "sample.lcov").read_text(encoding="utf-8")),
        C.parse_cobertura((FIXTURES / "sample-cobertura.xml").read_text(encoding="utf-8")),
        C.parse_coverage_json((FIXTURES / "sample-coverage.json").read_text(encoding="utf-8")),
    ]
    uncovered = []
    for report in reports:
        numbers = C.uncovered_changed(report, change)
        assert numbers.degraded is False
        uncovered.append({line for _path, line in numbers.uncovered})
    assert uncovered == [{4}, {4}, {4}]


def test_a_report_without_branches_falls_back_to_lines() -> None:
    report = C.parse_coverage_json(json.dumps({
        "files": {"src/app.py": {"missing_lines": [4], "executed_lines": [2, 10]}}
    }))
    numbers = C.uncovered_changed(report, _change(2, 4, 10))
    assert numbers.degraded is True
    assert {line for _path, line in numbers.uncovered} == {4}


def test_an_empty_missing_branches_list_is_branch_data() -> None:
    """The key is present and empty, so a missing line is not a fallback."""
    report = C.parse_coverage_json(json.dumps({
        "files": {"src/app.py": {"missing_lines": [4], "missing_branches": []}}
    }))
    numbers = C.uncovered_changed(report, _change(2, 4, 10))
    assert numbers.degraded is False
    assert numbers.uncovered == frozenset()


def test_an_empty_change_has_nothing_uncovered() -> None:
    report = C.parse_lcov((FIXTURES / "sample.lcov").read_text(encoding="utf-8"))
    numbers = C.uncovered_changed(report, _change())
    assert numbers.uncovered == frozenset()
    assert numbers.total == 0
    assert numbers.degraded is False
