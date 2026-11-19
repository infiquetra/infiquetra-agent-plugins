"""Owned Node test reports and canonical evidence, without runner console or clocks."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "saga.node-test-result.v1"
FALLBACK = "saga.node-test-console.v1"
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


def report_arguments(kind: str, report: Path, *, console: bool = False) -> list[str]:
    if kind == "vitest":
        return [*(["--reporter=default"] if console else []), "--reporter=json",
                f"--outputFile.json={report}", f"--outputFile={report}"]
    if kind == "jest":
        return ["--json", "--reporters=default", f"--outputFile={report}"]
    raise ValueError("unknown Node test runner")


def dumps(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def _count(data: dict[str, Any], key: str, *, optional: bool = False) -> int:
    value = data.get(key, 0 if optional else None)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid test count")
    return value


def canonical(data: Any, kind: str, version: str, seed: int | None, root: Path) -> dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("testResults"), list):
        raise ValueError("not a test report")
    tests = {status: _count(data, key, optional=status == "todo") for status, key in {
        "total": "numTotalTests", "passed": "numPassedTests", "failed": "numFailedTests",
        "pending": "numPendingTests", "todo": "numTodoTests"}.items()}
    # Vitest's suite counters include describe blocks. testResults has one entry per file.
    files = {"total": len(data["testResults"]), "passed": 0, "failed": 0, "pending": 0,
             "runtime_error": _count(data, "numRuntimeErrorTestSuites", optional=True)}
    spellings = {str(root): ".", str(root.resolve()): "."}
    modules = root / "node_modules"
    if modules.exists():
        spellings[str(modules.resolve())] = "node_modules"

    def message(value: str) -> str:
        value = _ANSI.sub("", value)
        for path, replacement in sorted(spellings.items(), key=lambda item: len(item[0]), reverse=True):
            value = value.replace(path + "/", "" if replacement == "." else replacement + "/")
            value = value.replace(path, replacement)
        return value

    failures: list[dict[str, Any]] = []
    for suite in data["testResults"]:
        if not isinstance(suite, dict) or not isinstance(suite.get("name"), str):
            raise ValueError("invalid suite identity")
        path = Path(suite["name"])
        if path.is_absolute():
            for spelling in (root, root.resolve()):
                if path.is_relative_to(spelling):
                    path = path.relative_to(spelling)
                    break
            else:
                raise ValueError("suite outside project")
        if not path.parts or ".." in path.parts:
            raise ValueError("invalid suite path")
        status = suite.get("status")
        if status in {"skipped", "todo", "disabled"}:
            status = "pending"
        if status not in {"passed", "failed", "pending"}:
            raise ValueError("invalid file status")
        files[status] += 1
        assertions = suite.get("assertionResults")
        if not isinstance(assertions, list):
            raise ValueError("invalid assertions")
        failed_cases = 0
        for case in assertions:
            if (not isinstance(case, dict) or not isinstance(case.get("fullName"), str)
                    or case.get("status") not in {"passed", "failed", "pending", "skipped", "todo", "disabled"}):
                raise ValueError("invalid test identity or status")
            if case["status"] != "failed":
                continue
            messages = case.get("failureMessages", [])
            if not isinstance(messages, list) or not all(isinstance(item, str) for item in messages):
                raise ValueError("invalid failure messages")
            failures.append({"file": path.as_posix(), "full_name": case["fullName"],
                             "messages": sorted(message(item) for item in messages)})
            failed_cases += 1
        if suite.get("status") == "failed" and not failed_cases:
            detail = suite.get("message", "")
            if not isinstance(detail, str):
                raise ValueError("invalid suite failure")
            failures.append({"file": path.as_posix(), "full_name": None,
                             "messages": [message(detail)] if detail else []})
    if (tests["failed"] or files["failed"] or files["runtime_error"]) and not failures:
        raise ValueError("missing failure identities")
    if tests["total"] and not files["total"]:
        raise ValueError("missing test files")
    return {"schema": SCHEMA, "runner": kind, "version": version, "seed": seed,
            "tests": tests, "files": files,
            "failures": sorted(failures, key=lambda item: json.dumps(item, sort_keys=True))}


def read(report: Path, kind: str, version: str, seed: int | None,
         root: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        if report.is_symlink():
            return None, "invalid-json-report"
        text = report.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "missing-json-report"
    except (OSError, UnicodeError):
        return None, "invalid-json-report"
    try:
        return canonical(json.loads(text), kind, version, seed, root), None
    except (ValueError, TypeError, KeyError):
        return None, "invalid-json-report"
