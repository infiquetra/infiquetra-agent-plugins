"""Tests for the builder-record writer and the declaration check (issue #162).

The module under test is the real ``builder_record``, loaded at module scope. ``check`` is judged
against a temporary git repository. Nothing here opens the primary checkout's run-record store.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "saga" / "scripts"
PLUGIN = REPO_ROOT / "plugins" / "saga"


def _load(name: str) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


builder_record = _load("builder_record")
question_banks = builder_record.question_banks
review_records = builder_record.review_records
run_record = builder_record.run_record

POLICY_IDS = [entry["id"] for entry in question_banks.load_policy(PLUGIN)["questions"]]
REASON = {
    "kind": "coverage-gap",
    "finding_id": "rf:" + "ab" * 16,
    "text": "The fallback branch is unreachable on supported platforms.",
}


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout)
    return proc.stdout.strip()


def _init(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "builder@example.com")
    _git(repo, "config", "user.name", "Builder")


def _commit_test(repo: Path, body: str) -> str:
    (repo / "test_ok.py").write_text(body, encoding="utf-8")
    _git(repo, "add", "test_ok.py")
    _git(repo, "commit", "-m", "add the proving test")
    return _git(repo, "rev-parse", "HEAD")


def _record(
    *,
    applies: str | None = None,
    proving: str | None = None,
    drop: str | None = None,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    declarations: list[dict[str, Any]] = []
    for question_id in POLICY_IDS:
        if question_id == drop:
            continue
        if question_id == applies:
            declarations.append(
                {"question": question_id, "applies": True, "proving_test": proving}
            )
        else:
            declarations.append({"question": question_id, "applies": False, "proving_test": None})
    declarations.extend(extra or [])
    return {
        "kind": "builder_record",
        "schema": review_records.SCHEMA,
        "unit": "U1",
        "acceptance_criteria": [
            {"id": "AC-1", "text": "The named test passes.", "checks": ["declaration-check"]}
        ],
        "declarations": declarations,
        "reasons": [dict(REASON)],
    }


def _write_record(path: Path, record: dict[str, Any]) -> Path:
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def _forbid(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("check opened a run record")


def test_declaration_check_passes_a_complete_record_with_no_run_record(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_record, "resolve_store_root", _forbid)
    monkeypatch.setattr(run_record, "load", _forbid)
    monkeypatch.setattr(run_record, "update", _forbid)
    repo = tmp_path / "repo"
    _init(repo)
    sha = _commit_test(repo, "def test_ok():\n    assert True\n")
    record = _write_record(
        tmp_path / "record.json",
        _record(applies=POLICY_IDS[0], proving="test_ok.py::test_ok"),
    )
    code = builder_record.main(
        ["check", "--record", str(record), "--revision", sha, "--repo", str(repo)]
    )
    assert code == 0, capsys.readouterr().err
    assert list(tmp_path.rglob("issue-*.json")) == []


def test_declaration_check_names_a_missing_question(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    sha = _commit_test(repo, "def test_ok():\n    assert True\n")
    dropped = POLICY_IDS[-1]
    record = _write_record(tmp_path / "record.json", _record(drop=dropped))
    code = builder_record.main(
        ["check", "--record", str(record), "--revision", sha, "--repo", str(repo)]
    )
    assert code == 1
    assert f"question {dropped}: missing declaration" in capsys.readouterr().err


def test_declaration_check_names_an_absent_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    sha = _commit_test(repo, "def test_ok():\n    assert True\n")
    question_id = POLICY_IDS[0]
    record = _write_record(
        tmp_path / "record.json",
        _record(applies=question_id, proving="test_ok.py::test_missing"),
    )
    code = builder_record.main(
        ["check", "--record", str(record), "--revision", sha, "--repo", str(repo)]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert f"question {question_id}: test absent" in err


def test_declaration_check_names_a_failing_test(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    sha = _commit_test(repo, "def test_ok():\n    assert False\n")
    question_id = POLICY_IDS[0]
    record = _write_record(
        tmp_path / "record.json",
        _record(applies=question_id, proving="test_ok.py::test_ok"),
    )
    code = builder_record.main(
        ["check", "--record", str(record), "--revision", sha, "--repo", str(repo)]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert f"question {question_id}: test failing" in err


def test_declaration_check_rejects_a_repeated_question_before_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("git ran before the duplicate was refused")

    monkeypatch.setattr(builder_record.subprocess, "run", fail)
    question_id = POLICY_IDS[0]
    record = _record(
        extra=[{"question": question_id, "applies": False, "proving_test": None}]
    )
    code, lines = builder_record.evaluate(record, "HEAD", tmp_path)
    assert code == 2
    assert lines == [f"declarations: duplicate question {question_id}"]


def test_declaration_check_names_an_unknown_question(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _init(repo)
    sha = _commit_test(repo, "def test_ok():\n    assert True\n")
    record = _write_record(
        tmp_path / "record.json",
        _record(
            extra=[
                {
                    "question": "not-a-policy-question",
                    "applies": False,
                    "proving_test": None,
                }
            ]
        ),
    )
    code = builder_record.main(
        ["check", "--record", str(record), "--revision", sha, "--repo", str(repo)]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "question not-a-policy-question: unknown question" in err
    assert "missing declaration" not in err


def test_declaration_check_refuses_a_proving_test_outside_the_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("git or pytest ran for a node outside the worktree")

    monkeypatch.setattr(builder_record.subprocess, "run", fail)
    ran: list[str] = []

    def run_test(node: str, _revision: str, _repo: Path) -> str:
        ran.append(node)
        return "pass"

    assert builder_record._escapes_worktree("test_ok.py::test_ok") is False
    assert builder_record._escapes_worktree("./test_ok.py::test_ok") is False
    assert builder_record._escapes_worktree("test_ok.py::test_ok[../param]") is False
    question_id = POLICY_IDS[0]
    for node in (
        "../outside.py::test_ok",
        "/tmp/outside.py::test_ok",
        "tests/../../outside.py::test_ok",
    ):
        record = _record(applies=question_id, proving=node)
        code, lines = builder_record.evaluate(
            record, "HEAD", tmp_path, run_test=run_test
        )
        assert code == 2
        assert lines == [
            f"question {question_id}: proving_test escapes the revision worktree"
        ]
    assert ran == []


def _store(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    run_record.save(root, run_record.RunRecord(issue=162, units=[{"id": "U1"}]))
    return root


def test_write_refuses_a_record_the_validator_rejects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rejected = dict(_record())
    del rejected["reasons"]
    path = _write_record(tmp_path / "rejected.json", rejected)
    code = builder_record.main(
        [
            "write",
            "--issue",
            "162",
            "--unit",
            "U1",
            "--record",
            str(path),
            "--store-root",
            str(store),
        ]
    )
    assert code == 1
    assert review_records.builder_record_for(run_record.load(store, 162), "U1") is None

    valid = _write_record(tmp_path / "valid.json", _record())
    assert (
        builder_record.main(
            [
                "write",
                "--issue",
                "162",
                "--unit",
                "U1",
                "--record",
                str(valid),
                "--store-root",
                str(store),
            ]
        )
        == 0
    )
    kept = review_records.builder_record_for(run_record.load(store, 162), "U1")
    assert kept is not None
    code = builder_record.main(
        [
            "write",
            "--issue",
            "162",
            "--unit",
            "U1",
            "--record",
            str(path),
            "--store-root",
            str(store),
        ]
    )
    assert code == 1
    assert review_records.builder_record_for(run_record.load(store, 162), "U1") == kept


def test_a_repair_write_keeps_earlier_declarations_and_reasons(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first_id, second_id = POLICY_IDS[0], POLICY_IDS[1]
    first = _record()
    first["declarations"] = [
        {"question": first_id, "applies": False, "proving_test": None},
        {"question": second_id, "applies": False, "proving_test": None},
    ]
    first["reasons"] = [dict(REASON)]
    first_path = _write_record(tmp_path / "first.json", first)
    assert (
        builder_record.main(
            [
                "write",
                "--issue",
                "162",
                "--unit",
                "U1",
                "--record",
                str(first_path),
                "--store-root",
                str(store),
            ]
        )
        == 0
    )
    other = {
        "kind": "unaffected",
        "finding_id": "rf:" + "cd" * 16,
        "text": "The second finding is outside this unit.",
    }
    second = _record()
    second["declarations"] = [
        {"question": first_id, "applies": True, "proving_test": "test_ok.py::test_ok"}
    ]
    second["reasons"] = [other]
    second_path = _write_record(tmp_path / "second.json", second)
    assert (
        builder_record.main(
            [
                "write",
                "--issue",
                "162",
                "--unit",
                "U1",
                "--record",
                str(second_path),
                "--store-root",
                str(store),
            ]
        )
        == 0
    )
    stored = review_records.builder_record_for(run_record.load(store, 162), "U1")
    assert stored is not None
    assert review_records.validate(stored) == []
    by_question = {item["question"]: item for item in stored["declarations"]}
    assert set(by_question) == {first_id, second_id}
    assert by_question[first_id]["applies"] is True
    assert by_question[first_id]["proving_test"] == "test_ok.py::test_ok"
    assert by_question[second_id]["applies"] is False
    kinds = {item["kind"] for item in stored["reasons"]}
    assert kinds == {"coverage-gap", "unaffected"}
