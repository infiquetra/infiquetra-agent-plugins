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
