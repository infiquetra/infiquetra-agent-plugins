"""Private failure evidence survives retries without changing review outcomes."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
_SPEC = importlib.util.spec_from_file_location("diagnostic_review_tools", SCRIPTS / "review_tools.py")
assert _SPEC is not None and _SPEC.loader is not None
T = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = T
_SPEC.loader.exec_module(T)
D = T.review_diagnostics


def _adapter() -> Any:
    return T.Adapter(
        id="cargo-mutants", tool="fixture", invoke=lambda _context: ["fixture"],
        parse=lambda _text: T.ParseResult(), rows=("testing.surviving-mutant",),
        lens="testing", comparison="lines", mutation=True,
        report_file="mutants.out/outcomes.json", exit_reasons=((4, "baseline-failed"),),
        retry_failures=("baseline-failed",),
    )


@pytest.mark.parametrize("retry", ["failure", "timeout", "success", "budget"])
def test_initial_and_retry_evidence_survive_independently(tmp_path: Path, retry: str) -> None:
    scan = tmp_path / "scan"
    scan.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    diagnostics = tmp_path / "diagnostics"
    context = T.ScanContext(scan, scan, home, diagnostics_directory=diagnostics)
    calls = 0

    def process(argv: list[str], **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        folder = scan / "mutants.out"
        (folder / "log").mkdir(parents=True, exist_ok=True)
        (folder / "log" / "baseline.log").write_text(f"attempt {calls} test failure")
        (folder / "outcomes.json").write_text(json.dumps({"outcomes": [{
            "scenario": "Baseline", "summary": "Failure", "log_path": "log/baseline.log",
        }]}))
        if calls == 2 and retry == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output=b"retry partial", stderr=b"retry error")
        return T.ProcessResult(0 if calls == 2 and retry == "success" else 4,
                               f"console {calls}", f"stderr {calls}")

    deadline = time.monotonic() + (-1 if retry == "budget" else 30)
    degraded: list[Any] = []
    T._once(_adapter(), context, process, {}, 5, "head", degraded, [], deadline)
    attempts = {}
    for path in diagnostics.glob("*/attempt.json"):
        record = json.loads(path.read_text())
        attempts[record["attempt"]] = (path.parent, record)
        assert record["elapsed_seconds"] >= 0
        assert record["remaining_budget_seconds"] >= 0
    initial_path, initial = attempts["initial"]
    assert initial["status"] == "failed" and initial["reason"] == "baseline-failed"
    assert (initial_path / "stdout.txt").read_text() == "console 1"
    baseline = next(initial_path.glob("baseline-*.log"))
    assert baseline.read_text() == "attempt 1 test failure"
    retry_path, record = attempts["retry"]
    expected = {"failure": ("failed", "baseline-failed"), "timeout": ("failed", "timeout"),
                "success": ("succeeded", None), "budget": ("skipped", "budget-exhausted")}
    assert (record["status"], record["reason"]) == expected[retry]
    assert calls == (1 if retry == "budget" else 2)
    assert degraded[0]["reason"] == ("baseline-flaky" if retry == "success" else "baseline-failed")
    if retry == "timeout":
        assert (retry_path / "stdout.txt").read_bytes() == b"retry partial"
    assert diagnostics.stat().st_mode & 0o777 == 0o700
    for path in diagnostics.rglob("*"):
        assert path.stat().st_mode & 0o777 == (0o700 if path.is_dir() else 0o600)


@pytest.mark.skipif(os.name != "posix", reason="safe descriptor reads are POSIX")
def test_report_cannot_redirect_log_reads_outside_scan_root(tmp_path: Path) -> None:
    scan = tmp_path / "scan"
    logs = scan / "mutants.out" / "log"
    logs.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "private.txt"
    sentinel.write_text("MUST_NOT_BE_COPIED")
    (logs / "link").symlink_to(sentinel)
    (logs / "directory-link").symlink_to(outside, target_is_directory=True)
    os.mkfifo(logs / "fifo")
    entries = [str(sentinel), "../../outside/private.txt", "log/link",
               "log/directory-link/private.txt", "log/fifo"]
    (scan / "mutants.out" / "outcomes.json").write_text(json.dumps({
        "outcomes": [{"scenario": "Baseline", "log_path": path} for path in entries],
    }))
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.logs(scan)
    attempt.finish("failed", "baseline-failed", 4)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["rejected_logs"] == len(entries)
    assert record["errors"] == ["baseline-log-unavailable-or-refused"]
    assert not list(attempt.directory.glob("baseline-*.log"))


def test_retained_artifacts_have_a_total_byte_and_file_bound(tmp_path: Path) -> None:
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.console("x" * (D.MAX_BYTES * 2), "y" * D.MAX_BYTES)
    for index in range(12):
        attempt.keep(f"fixture-{index}", b"z" * 65536)
    attempt.finish("failed", "baseline-failed", 4)
    paths = list(attempt.directory.iterdir())
    assert len(paths) <= D.MAX_FILES
    assert sum(path.stat().st_size for path in paths) <= D.MAX_BYTES
    metadata = json.loads((attempt.directory / "attempt.json").read_text())
    assert metadata["artifacts"]["stdout.txt"]["truncated"] is True


def test_unavailable_capture_is_private_telemetry_not_a_scan_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    refused = tmp_path / "diagnostics"
    refused.write_text("a file cannot be a diagnostics directory")
    context = T.ScanContext(tmp_path, tmp_path, tmp_path, diagnostics_directory=refused)
    adapter = _adapter()
    adapter = T.replace(adapter, report_file=None)
    degraded: list[Any] = []
    T._once(adapter, context, lambda *_args, **_kwargs: T.ProcessResult(0, "ok"),
            {}, 5, "head", degraded, [])
    assert degraded == []
    assert "private directory unavailable or refused" in capsys.readouterr().err


def test_artifact_failure_is_recorded_without_changing_status(tmp_path: Path) -> None:
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    (attempt.directory / "stdout.txt").write_text("existing")
    attempt.console("new", "error")
    attempt.finish("succeeded", None, 0)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["status"] == "succeeded"
    assert record["errors"] == ["artifact-write-failed"]


def test_unsupported_safe_open_refuses_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    scan = tmp_path / "scan"
    report = scan / "mutants.out" / "outcomes.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"outcomes": []}')
    monkeypatch.setattr(D.os, "supports_dir_fd", set())
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.logs(scan)
    attempt.finish("succeeded", None, 0)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["errors"] == ["report-unavailable-or-refused"]
    assert not (attempt.directory / "outcomes.json").exists()


def test_pathological_report_is_bounded_and_not_allowed_to_abort_capture(tmp_path: Path) -> None:
    scan = tmp_path / "scan"
    report = scan / "mutants.out" / "outcomes.json"
    report.parent.mkdir(parents=True)
    report.write_text("[" * 2000 + "0" + "]" * 2000)
    attempt = D.Attempt.create(tmp_path / "diagnostics", "cargo-mutants", "head", "initial", None)
    attempt.logs(scan)
    attempt.finish("failed", "baseline-failed", 4)
    record = json.loads((attempt.directory / "attempt.json").read_text())
    assert record["errors"] == ["report-unparseable"]


@pytest.mark.parametrize("log_path", ["log/baseline\0.log", "log/\ud800.log"], ids=["nul", "surrogate"])
def test_invalid_log_representation_preserves_the_production_scan_result(
    tmp_path: Path, log_path: str,
) -> None:
    scan = tmp_path / "scan"
    folder = scan / "mutants.out"
    (folder / "log").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    diagnostics = tmp_path / "diagnostics"
    report = json.dumps({"outcomes": [{
        "scenario": "Baseline", "summary": "Failure", "log_path": log_path,
    }]})

    def process(_argv: list[str], **_kwargs: Any) -> Any:
        (folder / "outcomes.json").write_text(report)
        return T.ProcessResult(4, "baseline failed", "test failed")

    observations = []
    for directory in (None, diagnostics):
        context = T.ScanContext(scan, scan, home, diagnostics_directory=directory)
        degraded: list[Any] = []
        result = T._once(_adapter(), context, process, {}, 5, "head", degraded, [])
        assert [item["reason"] for item in degraded] == ["baseline-failed"]
        assert degraded[0]["raw_output"]
        observations.append((result, degraded))
    assert observations[0] == observations[1]
    records = list(diagnostics.glob("*/attempt.json"))
    assert len(records) == 2
    for path in records:
        record = json.loads(path.read_text())
        assert record["status"] == "failed" and record["reason"] == "baseline-failed"
        assert record["rejected_logs"] == 1
        assert record["errors"] == ["baseline-log-unavailable-or-refused"]
        assert not list(path.parent.glob("baseline-*.log"))
