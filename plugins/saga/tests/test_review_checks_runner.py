"""The five scripted checks run through the review-tools runner (issue 155)."""

from __future__ import annotations

import importlib.util
import json
import os
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

ROWS = (
    "testing.test-passes-before-change",
    "testing.test-skipped-in-ci",
    "architecture-maintainability.machine-specific-value",
    "correctness.unupdated-mention",
    "correctness.workflow-dead-end",
)
RECORD_FILES = (
    "findings.json",
    "measurements.json",
    "degraded.json",
    "outcomes.json",
    "where-to-look.json",
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused. The host name is patched on socket.gethostname."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _quiet_env() -> dict[str, str]:
    skipped = ("TYPESAFE_", "GH_", "GITHUB_", "INFIQUETRA_")
    return {key: value for key, value in os.environ.items() if not key.startswith(skipped)}


def _component_list(text: str) -> list[str]:
    start = text.index("## Component paths")
    fence = text.index("```", start)
    body = text.index("\n", fence) + 1
    end = text.index("```", body)
    return [line.strip() for line in text[body:end].splitlines() if line.strip()]


def test_checks_help_names_the_five_checks() -> None:
    proc = subprocess.run(
        [sys.executable, str(H.SCRIPTS / "review_checks.py"), "--help"],
        check=False, capture_output=True, text=True, env=_quiet_env(),
    )
    assert proc.returncode == 0
    for name in H.C.CHECKS:
        assert name in proc.stdout


def test_checks_help_version_prints_1_0_0() -> None:
    proc = subprocess.run(
        [sys.executable, str(H.SCRIPTS / "review_checks.py"), "--version"],
        check=False, capture_output=True, text=True, env=_quiet_env(),
    )
    assert proc.returncode == 0
    assert proc.stdout == "1.0.0\n"


def test_checks_runner_invokes_each_check_without_a_run_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("getpass.getuser", lambda: "fixture-user")
    monkeypatch.setattr(socket, "gethostname", lambda: "fixture-host")
    H.install_stubs(tmp_path / "stubs")
    H.prepend(monkeypatch, tmp_path / "stubs")
    repo = tmp_path / "repo"
    H.init(repo)
    H.write(repo, {"notes.txt": "inert\n"})
    base = H.commit(repo, "base")
    head = H.commit(repo, "head", allow_empty=True)
    profile = H.profile(tmp_path / "profile.json", "python3 -m pytest -q")
    output = tmp_path / "cli"
    home = tmp_path / "home"
    home.mkdir()
    argv = [
        sys.executable, str(H.SCRIPTS / "review_tools.py"), "run",
        "--repo", str(repo), "--base", base, "--head", head,
        "--profile", str(profile), "--output", str(output), "--home", str(home),
    ]
    assert "--builder" not in argv
    assert not any("run-record" in item for item in argv)
    proc = subprocess.run(
        argv, check=False, capture_output=True, text=True, env=_quiet_env(), timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert not (output / "review_run.json").exists()
    for name in RECORD_FILES:
        assert (output / name).is_file()
    assert isinstance(json.loads((output / "where-to-look.json").read_text(encoding="utf-8")), list)
    H.valid(output)
    missing = [
        item for item in H.gaps(output)
        if item.get("tool") == "review-checks" and item.get("reason") == "missing"
    ]
    assert missing == []

    record: list[list[str]] = []
    in_process = tmp_path / "in-process"
    code = H.run(
        repo, base, head, profile, in_process, tmp_path / "home-in",
        H.T.default_adapters(), runner=H.recording_runner(record), framework=False,
    )
    assert code == 0
    seen = {name for argv in record for name in H.C.CHECKS if name in argv}
    assert seen == set(H.C.CHECKS)


def test_checks_fingerprint_names_the_script() -> None:
    calibration = H.load("review_calibration")
    assert calibration.COMPONENTS[-1] == "plugins/saga/scripts/review_checks.py"
    text = (H.REPO / "plugins" / "saga" / "references" / "review-calibration.md").read_text(
        encoding="utf-8",
    )
    assert _component_list(text) == list(calibration.COMPONENTS)
    tools = (H.REPO / "plugins" / "saga" / "references" / "review-tools.md").read_text(
        encoding="utf-8",
    )
    for name in (*H.C.CHECKS, *ROWS):
        assert name in tools


def _checks_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "scripts" / "review_checks.py"
    spec = importlib.util.spec_from_file_location("review_checks_for_junit_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_junit_report_with_a_doctype_or_entity_is_refused() -> None:
    checks = _checks_module()
    plain = '<testsuite><testcase name="t" classname="c"><skipped message="m"/></testcase></testsuite>'
    assert checks._junit_cases(plain) == [("t", "c", "m")]
    expansion = (
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]>'
        '<testsuite><testcase name="&b;" classname="c"/></testsuite>'
    )
    assert checks._junit_cases(expansion) == []
    assert checks._junit_cases("<!entity x 'y'>" + plain) == []
    # Refusal degrades the row: with no test named in the log either, the gap reason is returned.
    assert checks._ci_judgement(["tests/test_x.py::test_new"], "", expansion) == ([], "log-names-no-test")


def test_an_oversized_junit_report_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    checks = _checks_module()
    monkeypatch.setattr(checks, "JUNIT_MAX_BYTES", 50)
    report = '<testsuite><testcase name="t" classname="c"><skipped message="m"/></testcase></testsuite>'
    assert checks._junit_cases(report) == []
