"""Offline controls for CI provisioning and the real stdlib runner entrypoint."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.ci import provision_ctags


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "ci" / "run_root_tests.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class RootRunnerControls(unittest.TestCase):
    def compare(
        self, source: str, extras: dict[str, str] | None = None,
        *, expected_ids: list[str] | None = None,
    ) -> tuple[dict, str]:
        """Compare the actual new command with the original unittest command."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            tests = directory / "tests"
            tests.mkdir()
            (tests / "test_control.py").write_text(source, encoding="utf-8")
            for name, text in (extras or {}).items():
                path = tests / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
            report = directory / "report.json"
            summary = directory / "summary.txt"
            env = {**os.environ, "GITHUB_STEP_SUMMARY": str(summary)}
            old = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                cwd=directory, env={**env, "EXECUTION_LOG": str(directory / "old.jsonl")},
                text=True, capture_output=True, timeout=15,
            )
            new = subprocess.run(
                [sys.executable, str(RUNNER), "--report", str(report)],
                cwd=directory, env={**env, "EXECUTION_LOG": str(directory / "new.jsonl")},
                text=True, capture_output=True, timeout=15,
            )
            if expected_ids is not None:
                executed = []
                for name in ("old.jsonl", "new.jsonl"):
                    path = directory / name
                    executed.append([json.loads(line) for line in path.read_text().splitlines()] if path.exists() else [])
                self.assertEqual(executed[0], expected_ids, old.stderr)
                self.assertEqual(executed[1], executed[0], (old.stderr, new.stderr))
            self.assertEqual(new.returncode, old.returncode, (old.stderr, new.stderr))
            self.assertTrue(report.is_file(), new.stderr)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertNotIn("test_ids", data)
            self.assertNotIn("test_id_scope", data)
            # Ignore timings alone: names, failures, tracebacks, skip and
            # subtest output must still match the original command exactly.
            normalize = lambda text: re.sub(r"Ran (\d+) tests? in [\d.]+s", r"Ran \1 tests", text)
            self.assertEqual(normalize(new.stderr), normalize(old.stderr))
            self.assertIn("Root unittest module timings", summary.read_text(encoding="utf-8"))
            self.assertEqual(data["successful"], new.returncode == 0)
            return data, new.stderr

    def test_recursive_discovery_and_load_tests_are_preserved(self):
        data, _ = self.compare(
            "import unittest\n"
            "class Control(unittest.TestCase):\n"
            " def test_a(self): self.assertEqual(2+2, 4)\n"
            " def helper(self): self.assertTrue(True)\n"
            "def load_tests(loader, tests, pattern):\n"
            " tests.addTest(Control('helper'))\n"
            " return tests\n",
            {"nested/__init__.py": "", "nested/test_nested.py":
             "import unittest\nclass Nested(unittest.TestCase):\n def test_b(self): pass\n"},
        )
        self.assertEqual(data["tests_run"], 3)
        self.assertEqual(sum(row["tests"] for row in data["modules"].values()), 3)
        self.assertEqual(set(data["modules"]), {"test_control", "nested.test_nested"})
        self.assertTrue(all(row["seconds"] >= 0 for row in data["modules"].values()))

    def test_skip_expected_failure_and_subtests_remain_successful(self):
        data, _ = self.compare(
            "import unittest\nclass Control(unittest.TestCase):\n"
            " @unittest.skip('example skip')\n def test_skip(self): pass\n"
            " @unittest.expectedFailure\n def test_expected(self): self.fail('example')\n"
            " def test_subtests(self):\n"
            "  for i in range(3):\n"
            "   with self.subTest(i=i): self.assertLess(i, 3)\n"
        )
        self.assertEqual((data["tests_run"], data["skipped"], data["expected_failures"], data["subtests"]), (3, 1, 1, 3))

    def test_failure_error_unexpected_success_and_failed_subtests_block(self):
        data, stderr = self.compare(
            "import unittest\nclass Control(unittest.TestCase):\n"
            " def test_failure(self): self.fail('example assertion diagnostic')\n"
            " def test_error(self): raise RuntimeError('example exception diagnostic')\n"
            " @unittest.expectedFailure\n def test_unexpected(self): pass\n"
            " def test_subtests(self):\n"
            "  for i in range(2):\n"
            "   with self.subTest(i=i): self.assertEqual(i, 0)\n"
        )
        self.assertEqual((data["tests_run"], data["failures"], data["errors"], data["unexpected_successes"]), (4, 2, 1, 1))
        self.assertIn("example assertion diagnostic", stderr)
        self.assertIn("example exception diagnostic", stderr)

    def test_discovery_import_error_blocks_and_writes_report(self):
        data, stderr = self.compare("raise ImportError('example discovery diagnostic')\n")
        self.assertEqual(data["errors"], 1)
        self.assertIn("example discovery diagnostic", stderr)

    def test_class_and_module_fixture_errors_block(self):
        for fixture in (
            "def setUpModule(): raise RuntimeError('module fixture diagnostic')\n",
            "",
        ):
            with self.subTest(fixture=fixture):
                data, _ = self.compare(
                    "import unittest\n" + fixture +
                    "class Control(unittest.TestCase):\n"
                    " @classmethod\n def setUpClass(cls): raise RuntimeError('class fixture diagnostic')\n"
                    " def test_a(self): pass\n"
                )
                self.assertEqual(data["errors"], 1)
                self.assertEqual(data["tests_run"], 0)
                self.assertEqual(data["modules"], {})

    def test_empty_discovery_keeps_unittest_no_tests_exit(self):
        data, _ = self.compare("# No test cases in this control.\n")
        self.assertEqual(data["exit_code"], 5)

    def test_skipped_class_keeps_unittest_skip_semantics(self):
        data, _ = self.compare(
            "import unittest\n@unittest.skip('example class skip')\n"
            "class Control(unittest.TestCase):\n def test_a(self): pass\n"
        )
        self.assertEqual(data["skipped"], 1)

    # The independent execution log comes from the test itself, not from
    # traversing a suite or trusting the candidate's reported inventory.
    RECORDED_CASE = '''import json, os, unittest
class Control(unittest.TestCase):
 def setUp(self):
  with open(os.environ['EXECUTION_LOG'], 'a', encoding='utf-8') as log:
   log.write(json.dumps(self.id()) + '\\n')
 def test_pass(self): pass
 def test_failure(self): self.fail('example hidden failure must execute')
'''

    def test_stateful_nested_suite_cannot_hide_a_failure(self):
        data, _ = self.compare(self.RECORDED_CASE + '''
class Stateful(unittest.TestSuite):
 _cleanup = False
 def __init__(self):
  super().__init__()
  self.iterations = 0
 def __iter__(self):
  self.iterations += 1
  return iter([Control('test_failure')] if self.iterations <= 2 else [])
def load_tests(loader, tests, pattern):
 return unittest.TestSuite([Control('test_pass'), Stateful()])
''', expected_ids=["test_control.Control.test_pass", "test_control.Control.test_failure"])
        self.assertEqual((data["tests_run"], data["failures"], data["exit_code"]), (2, 1, 1))

    def test_lazy_nested_suite_cannot_hide_a_failure(self):
        data, _ = self.compare(self.RECORDED_CASE + '''
class Lazy(unittest.TestSuite):
 _cleanup = False
 def __init__(self):
  super().__init__()
  self.pending = iter([Control('test_failure')])
 def __iter__(self): return self.pending
def load_tests(loader, tests, pattern):
 return unittest.TestSuite([Control('test_pass'), Lazy()])
''', expected_ids=["test_control.Control.test_pass", "test_control.Control.test_failure"])
        self.assertEqual((data["tests_run"], data["failures"], data["exit_code"]), (2, 1, 1))

    def test_callable_duck_suite_needs_no_id_method(self):
        data, _ = self.compare(self.RECORDED_CASE + '''
class DuckSuite:
 def __iter__(self): return iter([Control('test_pass')])
 def __call__(self, result): return Control('test_pass')(result)
 def countTestCases(self): return 1
def load_tests(loader, tests, pattern): return DuckSuite()
''', expected_ids=["test_control.Control.test_pass"])
        self.assertEqual((data["tests_run"], data["exit_code"]), (1, 0))

    def test_base_suite_returned_by_load_tests_is_preserved(self):
        data, _ = self.compare(self.RECORDED_CASE + '''
def load_tests(loader, tests, pattern):
 return unittest.BaseTestSuite([Control('test_pass')])
''', expected_ids=["test_control.Control.test_pass"])
        self.assertEqual((data["tests_run"], data["exit_code"]), (1, 0))

    def test_load_tests_error_blocks_and_writes_report(self):
        data, stderr = self.compare(
            "def load_tests(loader, tests, pattern): raise RuntimeError('example load_tests diagnostic')\n"
        )
        self.assertEqual((data["errors"], data["exit_code"]), (1, 1))
        self.assertIn("example load_tests diagnostic", stderr)

    def test_execution_order_and_duplicate_ids_are_retained(self):
        data, _ = self.compare(self.RECORDED_CASE + '''
def load_tests(loader, tests, pattern):
 return unittest.TestSuite([Control('test_pass'), Control('test_failure'), Control('test_pass')])
''', expected_ids=["test_control.Control.test_pass", "test_control.Control.test_failure", "test_control.Control.test_pass"])
        self.assertEqual((data["tests_run"], data["failures"], data["exit_code"]), (3, 1, 1))

    def test_module_skip_reports_no_started_test_ids(self):
        data, _ = self.compare(
            "import unittest\ndef setUpModule(): raise unittest.SkipTest('example module skip')\n"
            "class Control(unittest.TestCase):\n def test_a(self): pass\n"
        )
        self.assertEqual((data["tests_run"], data["skipped"], data["exit_code"]), (0, 1, 0))
        self.assertEqual(data["modules"], {})

    def test_teardown_and_cleanup_failures_still_report_started_tests(self):
        for fixture in (
            "def tearDownModule(): raise RuntimeError('module teardown diagnostic')\n",
            "",
        ):
            with self.subTest(fixture=fixture):
                data, _ = self.compare(
                    "import unittest\n" + fixture +
                    "class Control(unittest.TestCase):\n"
                    " @classmethod\n def tearDownClass(cls): raise RuntimeError('class teardown diagnostic')\n"
                    " def test_a(self): self.addCleanup(self.fail, 'cleanup diagnostic')\n"
                )
                self.assertFalse(data["successful"])
                self.assertEqual(data["tests_run"], 1)
                self.assertEqual(sum(row["tests"] for row in data["modules"].values()), 1)

    def test_default_warning_policy_matches_unittest(self):
        data, stderr = self.compare(
            "import unittest, warnings\nclass Control(unittest.TestCase):\n"
            " def test_a(self): warnings.warn('example warning', DeprecationWarning)\n"
        )
        self.assertEqual(data["tests_run"], 1)
        self.assertIn("DeprecationWarning: example warning", stderr)

    def test_side_effectful_id_cannot_change_the_failing_method(self):
        data, stderr = self.compare('''import json, os, unittest
def record(event):
 with open(os.environ['EXECUTION_LOG'], 'a', encoding='utf-8') as log:
  log.write(json.dumps(event) + '\\n')
class Control(unittest.TestCase):
 def id(self):
  record('id called')
  self._testMethodName = 'test_success'
  return super().id()
 def test_failure(self):
  record('failure executed')
  self.fail('required failure')
 def test_success(self): record('success executed')
def load_tests(loader, tests, pattern):
 return unittest.TestSuite([Control('test_failure')])
''', expected_ids=["failure executed"])
        self.assertEqual((data["tests_run"], data["failures"], data["exit_code"]), (1, 1, 1))
        self.assertIn("required failure", stderr)

    def test_idless_callable_leaf_passes_like_unittest(self):
        data, _ = self.compare('''import json, os, unittest
class Leaf:
 def __str__(self): return 'example callable leaf'
 def shortDescription(self): return None
 def __call__(self, result):
  result.startTest(self)
  try:
   with open(os.environ['EXECUTION_LOG'], 'a', encoding='utf-8') as log:
    log.write(json.dumps('leaf executed') + '\\n')
   result.addSuccess(self)
  finally:
   result.stopTest(self)
def load_tests(loader, tests, pattern):
 return unittest.BaseTestSuite([Leaf()])
''', expected_ids=["leaf executed"])
        self.assertEqual((data["tests_run"], data["failures"], data["errors"], data["exit_code"]), (1, 0, 0, 0))
        self.assertEqual(data["modules"]["test_control"]["tests"], 1)


class CtagsProvisioningControls(unittest.TestCase):
    def setUp(self):
        self.capture = contextlib.ExitStack()
        self.addCleanup(self.capture.close)
        self.capture.enter_context(contextlib.redirect_stdout(io.StringIO()))
        self.capture.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def test_verified_preinstallation_avoids_apt(self):
        with mock.patch.object(provision_ctags, "probe", return_value=True), mock.patch.object(provision_ctags.subprocess, "run") as run:
            self.assertEqual(provision_ctags.main(), 0)
        run.assert_not_called()

    def test_missing_binary_and_wrong_identity_fail_probe(self):
        for outcome in (FileNotFoundError("example missing tool"), subprocess.CompletedProcess([], 0, "Exuberant Ctags 5.8\n")):
            with self.subTest(outcome=outcome):
                with mock.patch.object(provision_ctags.subprocess, "run", side_effect=[outcome]):
                    self.assertFalse(provision_ctags.probe())

    def test_identity_without_real_feature_output_is_rejected(self):
        results = [subprocess.CompletedProcess([], 0, "Universal Ctags 5.9.0\n"), subprocess.CompletedProcess([], 0, "")]
        with mock.patch.object(provision_ctags.subprocess, "run", side_effect=results):
            self.assertFalse(provision_ctags.probe())

    def test_successful_probe_exercises_all_required_parsers_and_json_fields(self):
        results = [subprocess.CompletedProcess([], 0, "Universal Ctags 5.9.0\n")]
        results += [subprocess.CompletedProcess([], 0, '{"_type":"tag","name":"ci_probe","line":1}\n')] * 3
        with mock.patch.object(provision_ctags.subprocess, "run", side_effect=results) as run:
            self.assertTrue(provision_ctags.probe())
        languages = {next(arg for arg in call.args[0] if arg.startswith("--language-force=")) for call in run.call_args_list[1:]}
        self.assertEqual(languages, {"--language-force=Rust", "--language-force=TypeScript", "--language-force=Sh"})

    def test_signed_bounded_install_requires_a_successful_post_probe(self):
        with mock.patch.object(provision_ctags, "probe", side_effect=[False, True]), mock.patch.object(provision_ctags.subprocess, "run") as run:
            self.assertEqual(provision_ctags.main(), 0)
        self.assertEqual(run.call_count, 2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][:5], ["sudo", "-n", "timeout", "--signal=KILL", "90s"])
            for option in ("Acquire::Retries=1", "Acquire::http::Timeout=15", "Acquire::https::Timeout=15", "DPkg::Lock::Timeout=15", "Acquire::AllowInsecureRepositories=false", "APT::Get::AllowUnauthenticated=false"):
                self.assertIn(option, call.args[0])
            self.assertEqual(call.kwargs, {"check": True, "timeout": 100})
        self.assertIn("--error-on=any", run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0][-3:], ["install", "-y", "universal-ctags"])

    def test_apt_failure_and_timeout_are_fatal_without_retry_loops(self):
        for outcome in (subprocess.CalledProcessError(100, "apt-get"), subprocess.TimeoutExpired("apt-get", 100), FileNotFoundError("sudo")):
            with self.subTest(outcome=outcome):
                with mock.patch.object(provision_ctags, "probe", return_value=False), mock.patch.object(provision_ctags.subprocess, "run", side_effect=outcome) as run:
                    self.assertEqual(provision_ctags.main(), 1)
                    self.assertEqual(run.call_count, 1)

    def test_failed_install_feature_probe_is_fatal(self):
        with mock.patch.object(provision_ctags, "probe", return_value=False), mock.patch.object(provision_ctags.subprocess, "run") as run:
            self.assertEqual(provision_ctags.main(), 1)
            self.assertEqual(run.call_count, 2)

    INVALID_JSON_RECORDS = (
        "[]\n", "null\n", "false\n", "1\n", '"example"\n',
        '{"_type":"tag","name":"ci_probe","line":1}\n[]\n',
        '[]\n{"_type":"tag","name":"ci_probe","line":1}\n',
    )

    def test_nonobject_and_mixed_json_fail_probe(self):
        for output in self.INVALID_JSON_RECORDS:
            with self.subTest(output=output):
                results = [subprocess.CompletedProcess([], 0, "Universal Ctags 5.9.0\n"),
                           subprocess.CompletedProcess([], 0, output)]
                with mock.patch.object(provision_ctags.subprocess, "run", side_effect=results):
                    self.assertFalse(provision_ctags.probe())

    def test_nonobject_output_enters_real_probe_fallback_path(self):
        for output in self.INVALID_JSON_RECORDS:
            with self.subTest(output=output):
                version = subprocess.CompletedProcess([], 0, "Universal Ctags 5.9.0\n")
                invalid = subprocess.CompletedProcess([], 0, output)
                valid = subprocess.CompletedProcess([], 0, '{"_type":"tag","name":"ci_probe","line":1}\n')
                results = [version, invalid, None, None, version, valid, valid, valid]
                with mock.patch.object(provision_ctags.subprocess, "run", side_effect=results) as run:
                    self.assertEqual(provision_ctags.main(), 0)
                apt_calls = [call for call in run.call_args_list if call.args[0][0] == "sudo"]
                self.assertEqual(len(apt_calls), 2)
                self.assertIn("--error-on=any", apt_calls[0].args[0])
                self.assertEqual(apt_calls[1].args[0][-3:], ["install", "-y", "universal-ctags"])
                self.assertEqual(run.call_count, 8)

    def test_postinstall_nonobject_output_is_fatal(self):
        for output in self.INVALID_JSON_RECORDS:
            with self.subTest(output=output):
                version = subprocess.CompletedProcess([], 0, "Universal Ctags 5.9.0\n")
                invalid = subprocess.CompletedProcess([], 0, output)
                results = [version, invalid, None, None, version, invalid]
                with mock.patch.object(provision_ctags.subprocess, "run", side_effect=results) as run:
                    self.assertEqual(provision_ctags.main(), 1)
                self.assertEqual(run.call_count, 6)


class WorkflowPreservationControls(unittest.TestCase):
    def test_all_original_gates_and_separate_jobs_remain(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertIn("group: validate-${{ github.ref }}\n  cancel-in-progress: true", text)
        self.assertEqual(
            re.findall(r"^  ([a-z-]+):\n    name:", text, re.M),
            ["vendor-selection", "validate", "plugin-tests", "vendor-validation", "claude-mods"],
        )
        root, plugin, vendor = text.split("  validate:", 1)[1].split("  plugin-tests:")[0], text.split("  plugin-tests:")[1].split("  claude-mods:")[0], text.split("  claude-mods:")[1]
        for command in ("python3 scripts/check_repo.py", "scripts/ci/run_root_tests.py", "git diff --check"):
            self.assertIn(command, root)
        self.assertNotIn("pip install", root)
        self.assertIn("pytest plugins/*/tests -q --import-mode=importlib", plugin)
        self.assertIn("['2.1.286', '2.1.289', '2.1.296']", vendor)
        for command in ("npm install", 'claude --version || node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"', 'grep -Fx', "claude plugin validate --strict", "claude plugin test", "for required in saga orchestrate", "python3 tests/installed_claude_validation.py --expected-version"):
            self.assertIn(command, vendor)
        self.assertNotIn("continue-on-error", text)
        self.assertNotIn("cache-hit", text)

    def test_download_cache_boundaries_and_failure_reporting(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("restore-keys:", text)
        self.assertIn("hashFiles('requirements-plugin-tests.txt', 'constraints-plugin-tests.txt')", text)
        self.assertIn("steps.python.outputs.python-version", text)
        self.assertIn("steps.pip-platform.outputs.policy", text)
        self.assertIn("steps.npm-platform.outputs.policy", text)
        self.assertIn("${{ matrix.claude-code }}-${{ hashFiles('.github/workflows/ci.yml') }}", text)
        self.assertIn("steps.npm-platform.outputs.allowed == 'true'", text)
        self.assertEqual(text.count("if: runner.environment == 'github-hosted'"), 2)
        self.assertEqual(re.findall(r"^          path: (.+)$", text, re.M), [
            "${{ runner.temp }}/ci-reports/root-timings.json", "${{ env.PIP_CACHE_DIR }}",
            "${{ runner.temp }}/ci-reports/plugin-junit.xml", "${{ env.npm_config_cache }}/_cacache",
        ])
        for name in ("root timing", "plugin test"):
            upload = text.split(f"      - name: Preserve {name} diagnostics", 1)[1].split("\n\n", 1)[0]
            self.assertIn("if: always()", upload)
            self.assertIn("uses: actions/upload-artifact@", upload)
        self.assertNotIn("--upgrade pip", text)
        self.assertEqual(text.count("timeout-minutes: 5"), 4)
        self.assertIn("timeout-minutes: 20", text)
        self.assertIn("timeout-minutes: 10", text)

    def test_requirements_keep_intent_and_every_direct_requirement_is_constrained(self):
        requirements = (ROOT / "requirements-plugin-tests.txt").read_text(encoding="utf-8")
        self.assertIn("mcp>=1,<2", requirements)
        self.assertIn("semgrep==1.179.0", requirements)
        normalized = lambda name: re.sub(r"[-_.]+", "-", name).lower()
        pins = {}
        for line in (ROOT / "constraints-plugin-tests.txt").read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#"):
                name, version = line.split("==")
                self.assertNotIn(normalized(name), pins)
                pins[normalized(name)] = version
        for line in requirements.splitlines():
            if line and not line.startswith("#"):
                self.assertIn(normalized(re.split(r"[<>=]", line)[0]), pins)
        self.assertEqual(pins["semgrep"], "1.179.0")
        self.assertEqual(pins["mcp"].split(".")[0], "1")


if __name__ == "__main__":
    unittest.main()
