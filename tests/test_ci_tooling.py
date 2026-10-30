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
    def compare(self, source: str, extras: dict[str, str] | None = None) -> tuple[dict, str]:
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
                cwd=directory, env=env, text=True, capture_output=True, timeout=15,
            )
            new = subprocess.run(
                [sys.executable, str(RUNNER), "--report", str(report)],
                cwd=directory, env=env, text=True, capture_output=True, timeout=15,
            )
            self.assertEqual(new.returncode, old.returncode, (old.stderr, new.stderr))
            self.assertTrue(report.is_file(), new.stderr)
            data = json.loads(report.read_text(encoding="utf-8"))
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
        self.assertEqual(len(data["test_ids"]), 3)
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

    def test_empty_discovery_keeps_unittest_no_tests_exit(self):
        data, _ = self.compare("# No test cases in this control.\n")
        self.assertEqual(data["exit_code"], 5)

    def test_skipped_class_keeps_unittest_skip_semantics(self):
        data, _ = self.compare(
            "import unittest\n@unittest.skip('example class skip')\n"
            "class Control(unittest.TestCase):\n def test_a(self): pass\n"
        )
        self.assertEqual(data["skipped"], 1)


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
            self.assertEqual(call.args[0][:6], ["sudo", "-n", "timeout", "--signal=TERM", "--kill-after=5s", "90s"])
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


class WorkflowPreservationControls(unittest.TestCase):
    def test_all_original_gates_and_separate_jobs_remain(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertIn("group: validate-${{ github.ref }}\n  cancel-in-progress: true", text)
        self.assertEqual(re.findall(r"^  ([a-z-]+):\n    name:", text, re.M), ["validate", "plugin-tests", "claude-mods"])
        root, plugin, vendor = text.split("  validate:", 1)[1].split("  plugin-tests:")[0], text.split("  plugin-tests:")[1].split("  claude-mods:")[0], text.split("  claude-mods:")[1]
        for command in ("python3 scripts/check_repo.py", "scripts/ci/run_root_tests.py", "git diff --check"):
            self.assertIn(command, root)
        self.assertNotIn("pip install", root)
        self.assertIn("pytest plugins/*/tests -q --import-mode=importlib", plugin)
        self.assertIn("['2.1.286', '2.1.289', '2.1.296']", vendor)
        for command in ("npm install", 'claude --version || node "$(npm root -g)/@anthropic-ai/claude-code/install.cjs"', 'grep -Fx', "claude plugin validate --strict", "claude plugin test", "for required in saga orchestrate", "python3 -m unittest tests.test_claude_plugin_packaging -v"):
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
