"""A mention of a removed name outside the edited lines (issue 155)."""

from __future__ import annotations

import importlib.util
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

MENTION = "correctness.unupdated-mention"
DOCUMENT = "correctness.unupdated-mention-in-document"
OLD = "def old_name():\n    return 1\n"
NEW = "def new_name():\n    return 1\n"
CALLER = "import a\n\nvalue = a.old_name()\n"
STATEMENT = "A mention of a removed name remains outside the edited lines."


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _files(base_name: str, head_name: str, **extra: str) -> tuple[dict[str, str], dict[str, str]]:
    base = {"a.py": base_name, **extra}
    head = {"a.py": head_name, **extra}
    return base, head


def _by_file(output: Path, ref: str) -> dict[str, dict[str, Any]]:
    return {item["location"]["file"]: item for item in H.outcomes_for(output, ref)}


def test_a_caller_outside_the_change_blocks(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"caller.py": CALLER})
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    H.valid(output)
    found = _by_file(output, "old_name")
    assert "caller.py" in found
    assert found["caller.py"]["severity"] == "blocks"
    assert found["caller.py"]["rule"]["row"] == MENTION
    raw = next(
        item for item in H.read(output, "findings.json")
        if item["rule"]["ref"] == "old_name" and item["location"]["file"] == "caller.py"
    )
    assert raw["statement"] == STATEMENT


def test_a_builder_reason_of_unaffected_turns_the_mention_into_a_note(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"caller.py": CALLER})
    code, first, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    finding = next(
        item for item in H.read(first, "findings.json")
        if item["rule"]["ref"] == "old_name" and item["location"]["file"] == "caller.py"
    )
    repo, base_sha, head_sha = H.make_repo(tmp_path / "again", base, head)
    record = H.builder(finding["id"], "unaffected", tmp_path / "builder.json")
    second = tmp_path / "second"
    code = H.run(
        repo, base_sha, head_sha, H.profile(tmp_path / "profile.json", "echo ok"),
        second, tmp_path / "home", [H.adapter("changed-names")], builder=record,
    )
    assert code == 0
    found = _by_file(second, "old_name")["caller.py"]
    assert found["severity"] == "note"
    assert "excused" in found["severity_basis"]["modifiers"]


def test_a_document_mention_is_fix_later(tmp_path: Path) -> None:
    note = "The old_name stays in this note.\n"
    base, head = _files(OLD, NEW, **{"notes.md": note})
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")["notes.md"]
    assert found["severity"] == "fix-later"
    assert found["rule"]["row"] == DOCUMENT


def test_an_agent_instruction_and_a_skill_mention_block(tmp_path: Path) -> None:
    extra = {
        "AGENTS.md": "Call old_name from the instruction.\n",
        "skills/guide.md": "Call old_name from the skill.\n",
    }
    base, head = _files(OLD, NEW, **extra)
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")
    for path in ("AGENTS.md", "skills/guide.md"):
        assert found[path]["severity"] == "blocks"
        assert found[path]["rule"]["row"] == MENTION


def test_a_mention_on_an_edited_line_yields_nothing(tmp_path: Path) -> None:
    base = {"a.py": "def old_name():\n    return 1\n\nvalue = 1\n"}
    head = {"a.py": "def new_name():\n    return 1\n\nvalue = old_name()\n"}
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    assert H.outcomes_for(output, "old_name") == []


def test_a_name_that_remains_in_the_same_scope_yields_nothing(tmp_path: Path) -> None:
    base, head = _files(
        "def old_name():\n    return 1\n",
        "def old_name():\n    return 2\n",
        **{"caller.py": CALLER},
    )
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    assert H.outcomes_for(output, "old_name") == []


def test_the_same_spelling_in_another_file_still_blocks(tmp_path: Path) -> None:
    base, head = _files(OLD, NEW, **{"b.py": OLD, "caller.py": CALLER})
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")
    assert "caller.py" in found
    assert found["caller.py"]["severity"] == "blocks"
    assert all(item["severity"] == "blocks" for item in found.values())


def test_a_rust_file_is_degraded_when_ctags_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    H.executable(tmp_path / "bin" / "ctags", "#!/bin/sh\nexit 1\n")
    H.prepend(monkeypatch, tmp_path / "bin")
    base = {"lib.rs": "fn old_name() {}\n", "other.rs": "fn use_it() { old_name(); }\n"}
    head = {"lib.rs": "fn new_name() {}\n", "other.rs": "fn use_it() { old_name(); }\n"}
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")["other.rs"]
    assert found["degraded"] is True
    assert found["severity"] == "fix-later"
    assert "degraded" in found["severity_basis"]["modifiers"]


def test_a_python_file_that_does_not_parse_is_degraded(tmp_path: Path) -> None:
    base, head = _files(
        "def old_name():\n    return 1\n", "def new_name(\n", **{"caller.py": CALLER},
    )
    code, output, *_rest = H.one(tmp_path, base, head, "changed-names", "echo ok")
    assert code == 0
    found = _by_file(output, "old_name")["caller.py"]
    assert found["degraded"] is True
    assert found["severity"] == "fix-later"
