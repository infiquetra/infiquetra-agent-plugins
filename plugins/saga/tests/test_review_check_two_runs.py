"""A new test that passes on the code before the change (issue 155)."""

from __future__ import annotations

import importlib.util
import socket
import subprocess
import sys
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
APP_BASE = "def add(a, b):\n    return a - b\n"
APP_HEAD = "def add(a, b):\n    return a + b\n"
SAMPLE = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
    "from app import add\n"
    "\n"
    "\n"
    "def test_fixed():\n"
    "    assert add(1, 1) == 2\n"
    "\n"
    "\n"
    "def test_already():\n"
    "    assert add(0, 0) == 0\n"
)
CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef sample():\n    return 0\n"
SAMPLE_FIXTURE = (
    "import sys\n"
    "from pathlib import Path\n"
    "\n"
    "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
    "from app import add\n"
    "\n"
    "\n"
    "def test_fixed():\n"
    "    assert add(1, 1) == 2\n"
    "\n"
    "\n"
    "def test_already(sample):\n"
    "    assert add(sample, sample) == 0\n"
)
ALREADY = "tests/test_sample.py::test_already"
FIXED = "tests/test_sample.py::test_fixed"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused. The check's own processes are separate programs."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _base() -> dict[str, str]:
    return {"pytest.ini": INI, "app.py": APP_BASE, "tests/test_keep.py": KEEP}


def _head(sample: str, *, conftest: bool = False) -> dict[str, str]:
    files = {
        "pytest.ini": INI,
        "app.py": APP_HEAD,
        "tests/test_keep.py": KEEP,
        "tests/test_sample.py": sample,
    }
    if conftest:
        files["tests/conftest.py"] = CONFTEST
    return files


def _refs(output: Path) -> set[str]:
    return {str(item["rule"]["ref"]) for item in H.read(output, "findings.json")}


def _review_gaps(output: Path) -> list[dict[str, str]]:
    return [item for item in H.gaps(output) if item.get("tool") == "review-checks"]


def test_a_new_test_that_passes_before_the_change_blocks(tmp_path: Path) -> None:
    code, output, *_rest = H.one(tmp_path, _base(), _head(SAMPLE), "two-runs", H.PYTEST)
    assert code == 0
    H.valid(output)
    refs = _refs(output)
    assert ALREADY in refs
    assert FIXED not in refs
    found = H.outcomes_for(output, ALREADY)
    assert len(found) == 1
    assert found[0]["severity"] == "blocks"
    assert found[0]["rule"]["row"] == "testing.test-passes-before-change"


def test_a_fixture_in_conftest_is_copied(tmp_path: Path) -> None:
    code, output, *_rest = H.one(
        tmp_path, _base(), _head(SAMPLE_FIXTURE, conftest=True), "two-runs", H.PYTEST,
    )
    assert code == 0
    H.valid(output)
    refs = _refs(output)
    assert ALREADY in refs
    assert FIXED not in refs


def test_a_builder_reason_turns_the_block_into_a_note(tmp_path: Path) -> None:
    code, first, *_rest = H.one(tmp_path, _base(), _head(SAMPLE), "two-runs", H.PYTEST)
    assert code == 0
    finding = next(
        item for item in H.read(first, "findings.json") if item["rule"]["ref"] == ALREADY
    )
    repo, base, head = H.make_repo(tmp_path / "again", _base(), _head(SAMPLE))
    record = H.builder(finding["id"], "test-passes-before-change", tmp_path / "builder.json")
    second = tmp_path / "second"
    code = H.run(
        repo, base, head, H.profile(tmp_path / "profile-again.json", H.PYTEST),
        second, tmp_path / "home-again", [H.adapter("two-runs")], builder=record,
    )
    assert code == 0
    found = H.outcomes_for(second, ALREADY)
    assert len(found) == 1
    assert found[0]["severity"] == "note"
    assert "excused" in found[0]["severity_basis"]["modifiers"]


def test_a_command_that_is_not_a_lister_is_no_test_list(tmp_path: Path) -> None:
    code, output, *_rest = H.one(
        tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"}, "two-runs", "echo ok",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "no-test-list" for item in _review_gaps(output))


def _pytest_stub(directory: Path, text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    H.executable(directory / "pytest", text)
    H.prepend(monkeypatch, directory)


def test_pytest_that_exits_nonzero_is_no_test_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pytest_stub(tmp_path / "bin", "#!/bin/sh\nexit 1\n", monkeypatch)
    code, output, *_rest = H.one(
        tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"}, "two-runs", "pytest -q",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "no-test-list" for item in _review_gaps(output))


def test_pytest_that_prints_no_node_id_is_no_test_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pytest_stub(tmp_path / "bin", "#!/bin/sh\necho 'no ids here'\nexit 0\n", monkeypatch)
    code, output, *_rest = H.one(
        tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"}, "two-runs", "pytest -q",
    )
    assert code == 0
    assert H.read(output, "findings.json") == []
    assert any(item["reason"] == "no-test-list" for item in _review_gaps(output))


def test_a_listing_timeout_is_reason_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pytest_stub(tmp_path / "bin", "#!/bin/sh\nsleep 2\nexit 0\n", monkeypatch)
    repo, base, _head = H.make_repo(tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"})
    payload = H.C.two_runs(repo, base, [("none", "pytest -q")], command_timeout=0.2)
    assert payload["hits"] == []
    assert payload["gaps"] == [{
        "reason": "timeout", "row": "testing.test-passes-before-change",
    }]


def test_a_missing_pytest_is_reason_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", str(H.git_bin(tmp_path / "bin")))
    repo, base, _head = H.make_repo(tmp_path, {"notes.txt": "one\n"}, {"notes.txt": "two\n"})
    payload = H.C.two_runs(repo, base, [("none", "pytest -q")])
    assert payload["hits"] == []
    assert payload["gaps"][0]["reason"] == "missing"


def test_the_run_subcommand_records_the_check_without_a_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    H.install_stubs(tmp_path / "stubs")
    H.prepend(monkeypatch, tmp_path / "stubs")
    repo, base, head = H.make_repo(tmp_path, _base(), _head(SAMPLE))
    profile = H.profile(tmp_path / "profile.json", H.PYTEST)
    output = tmp_path / "cli"
    home = tmp_path / "cli-home"
    home.mkdir()
    argv = [
        sys.executable, str(H.SCRIPTS / "review_tools.py"), "run",
        "--repo", str(repo), "--base", base, "--head", head,
        "--profile", str(profile), "--output", str(output), "--home", str(home),
    ]
    assert "--builder" not in argv
    assert not any("run-record" in item for item in argv)
    proc = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stderr
    assert not (output / "review_run.json").exists()
    for name in (
        "findings.json", "measurements.json", "degraded.json",
        "outcomes.json", "where-to-look.json",
    ):
        assert (output / name).is_file()
    H.valid(output)
    assert ALREADY in _refs(output)
