"""Run the full stdlib suite with observational per-module test timings.

Discovery and TextTestRunner retain unittest's fixture, skip, subtest and exit
semantics. Timings sum individual test calls (including per-test fixtures), not
module import or class/module fixture time. No selection or time budget is
applied to tests. Use -s/-p only for exercising this entrypoint's controls.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unittest
from pathlib import Path


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.modules: dict[str, dict[str, float | int]] = {}
        self.subtests = 0
        self.test_ids: list[str] = []

    def startTest(self, test):
        super().startTest(test)
        self.started = time.perf_counter()
        self.test_ids.append(test.id())

    def stopTest(self, test):
        elapsed = time.perf_counter() - self.started
        row = self.modules.setdefault(type(test).__module__, {"tests": 0, "seconds": 0.0})
        row["tests"] += 1
        row["seconds"] += elapsed
        super().stopTest(test)

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-s", "--start-directory", default="tests")
    parser.add_argument("-p", "--pattern", default="test*.py")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    # Running a script normally puts its directory first; `-m unittest` puts
    # the working directory there. Retain the latter's import environment.
    sys.path[0] = str(Path.cwd())
    result = None

    class TimedRunner(unittest.TextTestRunner):
        resultclass = TimedResult

        def run(self, test):
            nonlocal result
            result = super().run(test)
            return result

    # Let the original stdlib program own discovery, warnings, fixtures and
    # exit policy. Never inspect/iterate the suite before it executes: even
    # one extra traversal can consume a lazy load_tests suite and hide red.
    try:
        unittest.main(
            module=None, testRunner=TimedRunner,
            argv=["unittest", "discover", "-s", args.start_directory, "-p", args.pattern, "-v"],
        )
    except SystemExit as exited:
        if result is None:
            raise
        exit_code = exited.code
    report = {
        "test_ids": result.test_ids,
        "test_id_scope": "startTest callbacks in execution order, including duplicates; not a planned inventory",
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "subtests": result.subtests,
        "successful": exit_code == 0,
        "exit_code": exit_code,
        "modules": result.modules,
        "timing_scope": "sum of test calls including per-test fixtures; excludes import/class/module fixtures",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = sorted(result.modules.items(), key=lambda item: item[1]["seconds"], reverse=True)[:20]
    summary = ["Root unittest module timings (20 slowest; observations only):"]
    summary.extend(f"{name}: {row['seconds']:.3f}s ({row['tests']} tests)" for name, row in rows)
    print("\n".join(summary))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
            stream.write("\n```text\n" + "\n".join(summary) + "\n```\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
