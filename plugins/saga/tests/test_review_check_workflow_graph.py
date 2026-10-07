"""A run-model state with no path to an end state (issue 155)."""

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

ROW = "correctness.workflow-dead-end"
ACTIONS = (
    "name: example\n"
    "on: push\n"
    "jobs:\n"
    "  build:\n"
    "    runs-on: ubuntu-latest\n"
    "    steps:\n"
    "      - run: echo ok\n"
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _fixture(name: str) -> str:
    return (H.FIXTURES / name).read_text(encoding="utf-8")


def _refs(output: Path) -> set[str]:
    return {str(item["rule"]["ref"]) for item in H.read(output, "findings.json")}


def test_a_state_with_no_path_to_an_end_blocks(tmp_path: Path) -> None:
    code, output, *_rest = H.one(
        tmp_path,
        {"readme.txt": "a\n"},
        {"readme.txt": "a\n", "workflow-dead-end.json": _fixture("workflow-dead-end.json")},
        "workflow-graph",
        "echo ok",
    )
    assert code == 0
    H.valid(output)
    assert _refs(output) == {"work"}
    found = H.outcomes_for(output, "work")
    assert len(found) == 1
    assert found[0]["severity"] == "blocks"
    assert found[0]["rule"]["row"] == ROW
    assert found[0]["language"] == "none"
    raw = H.read(output, "findings.json")[0]
    assert raw["statement"] == "This state has no path to an end state."


def test_a_cycle_with_no_exit_blocks_each_state(tmp_path: Path) -> None:
    code, output, *_rest = H.one(
        tmp_path,
        {"readme.txt": "a\n"},
        {"readme.txt": "a\n", "workflow-loop.json": _fixture("workflow-loop.json")},
        "workflow-graph",
        "echo ok",
    )
    assert code == 0
    assert _refs(output) == {"left", "right"}
    for ref in ("left", "right"):
        found = H.outcomes_for(output, ref)
        assert len(found) == 1
        assert found[0]["severity"] == "blocks"
        assert found[0]["rule"]["row"] == ROW


def test_a_dead_end_present_at_base_is_absent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    H.init(repo)
    H.write(repo, {"workflow-base-dead-end.json": _fixture("workflow-base-dead-end.json")})
    base = H.commit(repo, "base")
    head = H.commit(repo, "head", allow_empty=True)
    record: list[list[str]] = []
    output = tmp_path / "out"
    code = H.run(
        repo, base, head, H.profile(tmp_path / "profile.json", "echo ok"),
        output, tmp_path / "home", [H.adapter("workflow-graph")],
        runner=H.recording_runner(record),
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    calls = [argv for argv in record if "workflow-graph" in argv and "--version" not in argv]
    assert len(calls) == 2


def test_a_github_actions_workflow_yields_nothing(tmp_path: Path) -> None:
    head = {
        "readme.txt": "b\n",
        ".github/workflows/example.yml": ACTIONS,
        "plain.json": json.dumps({"name": "not a model"}) + "\n",
    }
    code, output, *_rest = H.one(
        tmp_path, {"readme.txt": "a\n"}, head, "workflow-graph", "echo ok",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert not any(item.get("tool") == "review-checks" for item in H.gaps(output))


def test_an_end_state_alone_yields_nothing(tmp_path: Path) -> None:
    body = json.dumps({
        "nodes": [{"id": "done", "kind": "terminal"}],
        "transitions": [],
    })
    code, output, *_rest = H.one(
        tmp_path,
        {"readme.txt": "a\n"},
        {"readme.txt": "a\n", "end-only.json": body + "\n"},
        "workflow-graph",
        "echo ok",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
