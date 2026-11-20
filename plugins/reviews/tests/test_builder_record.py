"""Tests for the builder-record writer and the declaration check (issue #162).

The module under test is the reviews ``builder_record``. ``check`` is judged against a temporary
git repository and never reads an issue file. ``write`` merges into ``issue-<N>.json`` under an
explicit store directory.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "plugins" / "reviews" / "scripts"
PLUGIN = REPO_ROOT / "plugins" / "reviews"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_records"


def _load(name: str) -> ModuleType:
    key = f"infiquetra_reviews.{name}"
    path = SCRIPTS / f"{name}.py"
    existing = sys.modules.get(key)
    if existing is not None and getattr(existing, "__file__", None) == str(path):
        return existing
    spec = importlib.util.spec_from_file_location(key, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


builder_record = _load("builder_record")
question_banks = builder_record.question_banks
review_records = builder_record.review_records

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
    raise AssertionError("check opened an issue file")


def test_declaration_check_passes_a_complete_record_without_an_issue_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder_record, "_load_issue", _forbid)
    monkeypatch.setattr(builder_record, "_save_issue", _forbid)
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


def _store(tmp_path: Path, **over: Any) -> Path:
    root = tmp_path / "runs"
    root.mkdir()
    payload: dict[str, Any] = {
        "schema": builder_record._RUN_SCHEMA,
        "issue": 162,
        "updated_at": "1999-01-01T00:00:00+00:00",
        "units": [{"id": "U1"}],
    }
    payload.update(over)
    (root / "issue-162.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def _stored_builder(store: Path, unit: str = "U1") -> dict[str, Any] | None:
    payload = json.loads((store / "issue-162.json").read_text(encoding="utf-8"))
    return builder_record._builder_on(payload, unit)


def test_write_refuses_a_record_the_validator_rejects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    rejected = dict(_record())
    del rejected["reasons"]
    path = _write_record(tmp_path / "rejected.json", rejected)
    before = (store / "issue-162.json").read_bytes()
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
    assert (store / "issue-162.json").read_bytes() == before
    assert _stored_builder(store) is None

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
    kept = _stored_builder(store)
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
    assert _stored_builder(store) == kept


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
    stored = _stored_builder(store)
    assert stored is not None
    assert review_records.validate(stored) == []
    by_question = {item["question"]: item for item in stored["declarations"]}
    assert set(by_question) == {first_id, second_id}
    assert by_question[first_id]["applies"] is True
    assert by_question[first_id]["proving_test"] == "test_ok.py::test_ok"
    assert by_question[second_id]["applies"] is False
    kinds = {item["kind"] for item in stored["reasons"]}
    assert kinds == {"coverage-gap", "unaffected"}


def _write_issue(store: Path, record: Path) -> int:
    return builder_record.main(
        [
            "write",
            "--issue",
            "162",
            "--unit",
            "U1",
            "--record",
            str(record),
            "--store-root",
            str(store),
        ]
    )


class WriteIssueFileTests(unittest.TestCase):
    """Regressions for a write that must refuse a bad issue file and keep its mode."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.record = _write_record(self.tmp_path / "record.json", _record())

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_write_rejects_an_unsupported_schema(self) -> None:
        for name, payload in (
            ("other", {"schema": "other.v1", "issue": 162, "units": [{"id": "U1"}]}),
            ("missing", {"issue": 162, "units": [{"id": "U1"}]}),
        ):
            with self.subTest(name=name):
                store = self.tmp_path / name
                store.mkdir()
                path = store / "issue-162.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                before = path.read_bytes()
                self.assertEqual(_write_issue(store, self.record), 2)
                self.assertEqual(path.read_bytes(), before)

    def test_write_rejects_a_mismatched_issue_id(self) -> None:
        store = self.tmp_path / "runs"
        store.mkdir()
        path = store / "issue-162.json"
        path.write_text(
            json.dumps(
                {
                    "schema": builder_record._RUN_SCHEMA,
                    "issue": 99,
                    "units": [{"id": "U1", "kept": True}],
                }
            ),
            encoding="utf-8",
        )
        before = path.read_bytes()
        self.assertEqual(_write_issue(store, self.record), 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["issue"], 99)

    def test_write_rejects_units_that_are_not_a_list(self) -> None:
        store = self.tmp_path / "runs"
        store.mkdir()
        path = store / "issue-162.json"
        original = {
            "schema": builder_record._RUN_SCHEMA,
            "issue": 162,
            "units": {"id": "U1", "kept": True},
        }
        path.write_text(json.dumps(original), encoding="utf-8")
        before = path.read_bytes()
        self.assertEqual(_write_issue(store, self.record), 2)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["units"], original["units"])

    def test_write_keeps_the_record_mode_and_refreshes_updated_at(self) -> None:
        store = _store(
            self.tmp_path,
            units=[{"id": "U1", "note": "keep"}, {"id": "U2", "note": "other"}],
        )
        path = store / "issue-162.json"
        path.chmod(0o640)
        self.assertEqual(_write_issue(store, self.record), 0)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertNotEqual(payload["updated_at"], "1999-01-01T00:00:00+00:00")
        self.assertGreater(
            datetime.fromisoformat(payload["updated_at"]),
            datetime.fromisoformat("1999-01-01T00:00:00+00:00"),
        )
        by_id = {row["id"]: row for row in payload["units"]}
        self.assertEqual(by_id["U1"]["note"], "keep")
        self.assertIn("builder_record", by_id["U1"])
        self.assertEqual(by_id["U2"], {"id": "U2", "note": "other"})


def test_write_needs_a_store_and_refuses_a_missing_owned_row(tmp_path: Path) -> None:
    record = _write_record(tmp_path / "record.json", _record())
    assert (
        builder_record.main(
            ["write", "--issue", "162", "--unit", "U1", "--record", str(record)]
        )
        == 2
    )
    store = _store(tmp_path)
    payload = json.loads((store / "issue-162.json").read_text(encoding="utf-8"))
    payload["orchestrate"] = {"drives": True}
    (store / "issue-162.json").write_text(json.dumps(payload), encoding="utf-8")
    code = builder_record.main(
        [
            "write",
            "--issue",
            "162",
            "--unit",
            "U9",
            "--record",
            str(record),
            "--store-root",
            str(store),
        ]
    )
    assert code == 5
    assert _stored_builder(store, "U9") is None
    assert _stored_builder(store, "U1") is None


def test_builder_record_fixtures_match_the_validator() -> None:
    valid = json.loads((FIXTURES / "valid" / "builder_record.json").read_text(encoding="utf-8"))
    assert review_records.validate(valid) == []
    for path in sorted((FIXTURES / "invalid").glob("builder_record--*.json")):
        field = path.stem.split("--", 1)[1]
        problems = review_records.validate(json.loads(path.read_text(encoding="utf-8")))
        assert any(line.startswith(f"{field}:") for line in problems), problems


def test_check_runs_from_the_repo_root_and_from_an_installed_copy(tmp_path: Path) -> None:
    help_at_root = subprocess.run(
        [sys.executable, str(SCRIPTS / "builder_record.py"), "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_at_root.returncode == 0, help_at_root.stderr
    assert "check" in help_at_root.stdout

    installed = tmp_path / "installed"
    shutil.copytree(
        PLUGIN,
        installed,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    script = installed / "scripts" / "builder_record.py"
    help_installed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=outside,
        capture_output=True,
        text=True,
        check=False,
    )
    assert help_installed.returncode == 0, help_installed.stderr
    bad = outside / "bad.json"
    bad.write_text('{"kind": "builder_record"}', encoding="utf-8")
    checked = subprocess.run(
        [
            sys.executable,
            str(script),
            "check",
            "--record",
            str(bad),
            "--revision",
            "HEAD",
            "--repo",
            str(outside),
        ],
        cwd=outside,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 2, checked.stderr
    assert "missing file" not in checked.stderr
    assert "schema:" in checked.stderr or "kind:" in checked.stderr
