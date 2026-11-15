"""Node runner evidence keeps result identities and diagnostics, independently of console."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

_SPEC = importlib.util.spec_from_file_location("node_report_harness", Path(__file__).with_name("review_check_harness.py"))
assert _SPEC and _SPEC.loader
H = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(H)
N = H.load("review_node_reports")


def _report(root: Path) -> dict[str, Any]:
    return {"numTotalTests": 1, "numPassedTests": 0, "numFailedTests": 1,
        "numPendingTests": 0, "numTotalTestSuites": 1, "numPassedTestSuites": 0,
        "numFailedTestSuites": 1, "numPendingTestSuites": 0,
        "testResults": [{"name": str(root / "example.test.js"), "status": "failed",
            "assertionResults": [{"fullName": "nested full test name", "status": "failed",
                "failureMessages": [f"at {root}/example.test.js:1; duration 12ms at 0xabc"]}]}]}


@pytest.mark.parametrize("kind", ["vitest", "jest"])
def test_relocated_node_run_stores_canonical_report_instead_of_varying_console(
    tmp_path: Path, kind: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    hits = []
    reports: list[Path] = []
    version = "4.1.11" if kind == "vitest" else "30.5.2"
    for attempt in (1, 2):
        work = tmp_path / f"work-{attempt}"
        work.mkdir()
        def process(argv: list[str], **kwargs: Any) -> Any:
            if "--version" in argv:
                return H.T.ProcessResult(0, version)
            assert ("--no-file-parallelism" if kind == "vitest" else "--runInBand") in argv
            destination = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--outputFile=")))
            assert not destination.is_relative_to(root) and not destination.is_relative_to(work)
            reports.append(destination)
            data = _report(root)
            data["startTime"] = attempt * 1000
            data["testResults"][0]["assertionResults"][0]["duration"] = attempt
            destination.write_text(json.dumps(data))
            return H.T.ProcessResult(1, f"{attempt} tests {attempt}ms ({attempt}%)\n✓ optional pass\n",
                                     f"stderr | example.test.js > warning\nwarning ~{attempt}.2s\n")
        gaps: list[Any] = []
        hit = H.T._one_relocated(root, "typescript", kind + (" run" if kind == "vitest" else ""),
                                  process, work, home, gaps)
        assert hit is not None and gaps == []
        hits.append(hit)
    assert hits[0].raw_output == hits[1].raw_output
    data = json.loads((home / ".saga/review-output" / hits[0].raw_output).read_text())
    assert data["runner"] == kind and data["version"] == version and data["seed"] is None
    assert data["failures"][0]["full_name"] == "nested full test name"
    assert data["failures"][0]["messages"] == ["at example.test.js:1; duration 12ms at 0xabc"]
    assert all(not report.parent.exists() for report in reports)


@pytest.mark.parametrize("bad_report,reason", [(None, "missing-json-report"),
    ("not json", "invalid-json-report")])
def test_relocated_node_report_fallback_records_a_gap_and_keeps_diagnostics(
    tmp_path: Path, bad_report: str | None, reason: str,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    def process(argv: list[str], **kwargs: Any) -> Any:
        if "--version" in argv:
            return H.T.ProcessResult(0, "4.1.11")
        destination = Path(next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--outputFile=")))
        if bad_report is not None:
            destination.write_text(bad_report)
        return H.T.ProcessResult(1, "run failed\n", "warning from the test\n")
    gaps: list[Any] = []
    home = tmp_path / "home"
    home.mkdir()
    hit = H.T._one_relocated(root, "typescript", "vitest run", process, work, home, gaps)
    assert hit is not None
    assert {gap["reason"] for gap in gaps} == {reason}
    raw = (home / ".saga/review-output" / hit.raw_output).read_text()
    assert "run failed" in raw and "warning from the test" in raw


def test_collection_failure_keeps_its_file_and_message_without_test_cases(tmp_path: Path) -> None:
    data = _report(tmp_path)
    data.update(numTotalTests=0, numFailedTests=0)
    data["testResults"][0].update(assertionResults=[], message="could not load the test module")
    result = N.canonical(data, "vitest", "4.1.11", 7, tmp_path)
    assert result["failures"] == [{"file": "example.test.js", "full_name": None,
                                   "messages": ["could not load the test module"]}]


def test_vitest_describe_suites_do_not_inflate_the_file_counts(tmp_path: Path) -> None:
    data = _report(tmp_path)
    data.update(numTotalTestSuites=5, numFailedTestSuites=3, numPassedTestSuites=2)
    result = N.canonical(data, "vitest", "4.1.11", 7, tmp_path)
    assert result["files"] == {"total": 1, "failed": 1, "passed": 0, "pending": 0, "runtime_error": 0}


@pytest.mark.parametrize("corruption", ["negative-count", "boolean-count", "outside-file", "missing-failures", "symlink"])
def test_invalid_reports_cannot_become_clean_canonical_evidence(tmp_path: Path, corruption: str) -> None:
    data = _report(tmp_path)
    if corruption == "negative-count":
        data["numTotalTests"] = -1
    elif corruption == "boolean-count":
        data["numTotalTests"] = True
    elif corruption == "outside-file":
        data["testResults"][0]["name"] = str(tmp_path.parent / "outside.test.js")
    elif corruption == "missing-failures":
        data["testResults"] = []
    report = tmp_path / "result.json"
    report.write_text(json.dumps(data))
    if corruption == "symlink":
        link = tmp_path / "link.json"
        link.symlink_to(report)
        report = link
    result, reason = N.read(report, "vitest", "4.1.11", 7, tmp_path)
    assert result is None and reason == "invalid-json-report"
