"""A new test the finished run skipped, or never showed (issue 155)."""

from __future__ import annotations

import importlib.util
import json
import socket
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

INI = "[pytest]\n"
KEEP = "def test_keep():\n    assert True\n"
FOUR = (
    "def test_reason():\n    assert True\n\n"
    "def test_silent():\n    assert True\n\n"
    "def test_missing():\n    assert True\n\n"
    "def test_ran():\n    assert True\n"
)
PAIR = "def test_reason():\n    assert True\n\n" "def test_silent():\n    assert True\n"
NAMED = "def test_sample():\n    assert True\n"
SILENT = "tests/test_sample.py::test_silent"
MISSING = "tests/test_sample.py::test_missing"
REASON = "tests/test_sample.py::test_reason"
RAN = "tests/test_sample.py::test_ran"
ROW = "testing.test-skipped-in-ci"
GH = """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

record = Path(os.environ["CHECK_GH_RECORD"])
cwd = Path.cwd()
names = sorted(path.name for path in cwd.iterdir())
line = json.dumps({"argv": sys.argv[1:], "cwd": str(cwd), "names": names})
with record.open("a", encoding="utf-8") as handle:
    handle.write(line + "\\n")

mode = os.environ.get("CHECK_GH_MODE", "skipped")
argv = sys.argv[1:]


def emit(text: str) -> None:
    sys.stdout.write(text if text.endswith("\\n") else text + "\\n")


if argv[:2] == ["run", "list"]:
    if mode == "empty":
        emit("[]")
    else:
        emit(json.dumps([{
            "databaseId": 10,
            "conclusion": "success",
            "status": "completed",
            "headSha": "abc",
        }]))
elif "--json" in argv and "artifacts" in argv:
    if mode == "junit":
        emit(json.dumps({"artifacts": [{"name": "junit-report"}]}))
    else:
        emit(json.dumps({"artifacts": []}))
elif argv[:2] == ["run", "download"]:
    dest = Path(argv[argv.index("--dir") + 1])
    dest.mkdir(parents=True, exist_ok=True)
    source = Path(os.environ["CHECK_GH_JUNIT"])
    text = source.read_text(encoding="utf-8")
    (dest / "junit.xml").write_text(text, encoding="utf-8")
elif "--log" in argv:
    chosen = {"quiet": "CHECK_GH_QUIET", "named": "CHECK_GH_NAMED"}.get(
        mode, "CHECK_GH_SKIPPED",
    )
    emit(Path(os.environ[chosen]).read_text(encoding="utf-8"))
"""


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused. The stand-in gh writes a file and opens no socket."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _trees(sample: str) -> tuple[dict[str, str], dict[str, str]]:
    base = {"pytest.ini": INI, "tests/test_keep.py": KEEP}
    head = {"pytest.ini": INI, "tests/test_keep.py": KEEP, "tests/test_sample.py": sample}
    return base, head


def _prepare(tmp: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    H.executable(tmp / "bin" / "gh", GH)
    H.prepend(monkeypatch, tmp / "bin")
    monkeypatch.setenv("CHECK_GH_RECORD", str(tmp / "gh.jsonl"))
    monkeypatch.setenv("CHECK_GH_MODE", mode)
    monkeypatch.setenv("CHECK_GH_JUNIT", str(H.FIXTURES / "junit-skipped.xml"))
    monkeypatch.setenv("CHECK_GH_QUIET", str(H.FIXTURES / "ci-quiet.log"))
    monkeypatch.setenv("CHECK_GH_NAMED", str(H.FIXTURES / "ci-named.log"))
    monkeypatch.setenv("CHECK_GH_SKIPPED", str(H.FIXTURES / "ci-skipped.log"))


def _calls(tmp: Path) -> list[dict[str, Any]]:
    path = tmp / "gh.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _away_from_repo(calls: list[dict[str, Any]], repo: Path) -> None:
    for call in calls:
        assert Path(call["cwd"]) != repo
        assert ".git" not in call["names"]
        assert "tests" not in call["names"]


def _review_gaps(output: Path) -> list[dict[str, str]]:
    return [item for item in H.gaps(output) if item.get("tool") == "review-checks"]


def _run(
    tmp: Path, sample: str, mode: str, monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, Path, Path]:
    _prepare(tmp, monkeypatch, mode)
    base, head = _trees(sample)
    code, output, repo, _base, _head = H.one(tmp, base, head, "ci-skips", H.PYTEST)
    _away_from_repo(_calls(tmp), repo)
    return code, output, repo


def test_a_silent_skip_and_a_missing_test_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, output, _repo = _run(tmp_path, FOUR, "skipped", monkeypatch)
    assert code == 0
    H.valid(output)
    refs = {str(item["rule"]["ref"]) for item in H.read(output, "findings.json")}
    assert refs == {SILENT, MISSING}
    for ref in (SILENT, MISSING):
        found = H.outcomes_for(output, ref)
        assert len(found) == 1
        assert found[0]["severity"] == "blocks"
        assert found[0]["rule"]["row"] == ROW
    assert REASON not in refs
    assert RAN not in refs


def test_a_builder_reason_turns_the_skip_into_a_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, first, _repo = _run(tmp_path, FOUR, "skipped", monkeypatch)
    assert code == 0
    finding = next(item for item in H.read(first, "findings.json") if item["rule"]["ref"] == SILENT)
    record = H.builder(finding["id"], "test-skipped-in-ci", tmp_path / "builder.json")
    again = tmp_path / "again"
    _prepare(again, monkeypatch, "skipped")
    base, head_files = _trees(FOUR)
    repo, base_sha, head_sha = H.make_repo(again, base, head_files)
    second = again / "out"
    code = H.run(
        repo, base_sha, head_sha, H.profile(again / "profile.json", H.PYTEST),
        second, again / "home", [H.adapter("ci-skips")], builder=record,
    )
    assert code == 0
    found = H.outcomes_for(second, SILENT)
    assert len(found) == 1
    assert found[0]["severity"] == "note"
    assert "excused" in found[0]["severity_basis"]["modifiers"]


def test_a_junit_report_blocks_only_the_silent_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, output, _repo = _run(tmp_path, PAIR, "junit", monkeypatch)
    assert code == 0
    H.valid(output)
    refs = {str(item["rule"]["ref"]) for item in H.read(output, "findings.json")}
    assert refs == {SILENT}
    assert H.outcomes_for(output, SILENT)[0]["severity"] == "blocks"
    assert H.outcomes_for(output, SILENT)[0]["rule"]["row"] == ROW


def test_a_passed_node_id_yields_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, output, _repo = _run(tmp_path, NAMED, "named", monkeypatch)
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert not any(item["reason"] == "log-names-no-test" for item in _review_gaps(output))


def test_a_log_that_names_no_test_is_a_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, output, _repo = _run(tmp_path, FOUR, "quiet", monkeypatch)
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "log-names-no-test" for item in _review_gaps(output))


def test_an_empty_run_list_is_no_finished_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    code, output, _repo = _run(tmp_path, FOUR, "empty", monkeypatch)
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "no-finished-run" for item in _review_gaps(output))
    calls = _calls(tmp_path)
    assert calls
    assert all(call["argv"][:2] == ["run", "list"] for call in calls)


def test_a_missing_gh_is_reason_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(H.git_bin(tmp_path / "bin")))
    base, head = _trees(FOUR)
    code, output, *_rest = H.one(tmp_path, base, head, "ci-skips", H.PYTEST)
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "missing" for item in _review_gaps(output))


def test_a_gh_timeout_is_reason_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    H.executable(tmp_path / "bin" / "gh", "#!/bin/sh\nsleep 2\nexit 0\n")
    H.prepend(monkeypatch, tmp_path / "bin")
    base, head = _trees(FOUR)
    repo, base_sha, _head = H.make_repo(tmp_path, base, head)
    payload = H.C.ci_skips(repo, base_sha, [("none", H.PYTEST)], gh_timeout=0.2)
    assert payload["hits"] == []
    assert any(item["reason"] == "timeout" for item in payload["gaps"])
