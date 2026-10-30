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

    def startTest(self, test):
        super().startTest(test)
        self.started = time.perf_counter()

    def stopTest(self, test):
        elapsed = time.perf_counter() - self.started
        row = self.modules.setdefault(type(test).__module__, {"tests": 0, "seconds": 0.0})
        row["tests"] += 1
        row["seconds"] += elapsed
        super().stopTest(test)

    def addSubTest(self, test, subtest, err):
        self.subtests += 1
        super().addSubTest(test, subtest, err)


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-s", "--start-directory", default="tests")
    parser.add_argument("-p", "--pattern", default="test*.py")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    # Running a script normally puts its directory first; `-m unittest` puts
    # the working directory there. Retain the latter's import environment.
    sys.path[0] = str(Path.cwd())
    # Match `python3 -m unittest discover -s tests -v`, including its sys.path
    # handling and load_tests hooks; do not flatten or rebuild the suite.
    suite = unittest.defaultTestLoader.discover(args.start_directory, pattern=args.pattern)
    inventory = list(test_ids(suite))
    result = unittest.TextTestRunner(
        verbosity=2, resultclass=TimedResult,
        warnings=None if sys.warnoptions else "default",
    ).run(suite)
    # Match unittest's CLI, including its no-tests exit (also used when a
    # class/module fixture fails before any test can start).
    if result.testsRun == 0 and not result.skipped:
        exit_code = 5
    else:
        exit_code = 0 if result.wasSuccessful() else 1
    report = {
        "test_ids": inventory,
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
