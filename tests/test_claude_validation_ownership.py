"""Ownership and entrypoint failure controls; no real Claude process is run."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import test_claude_plugin_packaging as packaging
import installed_claude_validation as installed

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "tests" / "installed_claude_validation.py"
LIVE_CASE = "test_every_root_manifest_passes_the_cli_validator_when_the_cli_is_present"

# Transport injection only: this runs the actual entrypoint/parser/TestProgram
# in a child interpreter. It does not stand in for the real three-build proof.
DRIVER = '''import json, runpy, subprocess, sys
from pathlib import Path
from unittest.mock import patch
entry, config_path, trace_path = map(Path, sys.argv[1:])
config = json.loads(config_path.read_text())
sys.path.insert(0, str(entry.parent))
import test_claude_plugin_packaging as packaging
if 'plugins' in config:
    packaging.PLUGINS = Path(config['plugins'])
def run(command, **kwargs):
    with trace_path.open('a', encoding='utf-8') as trace:
        trace.write(json.dumps({'command': command, 'options': kwargs}) + '\\n')
    if command[1:] == ['--version']:
        if config.get('failure') == 'version-timeout':
            raise subprocess.TimeoutExpired(command, 60)
        return subprocess.CompletedProcess(command, config.get('version_code', 0),
            config.get('version', '2.1.289 (Claude Code)\\n'), '')
    assert command[1:3] == ['plugin', 'validate'], command
    if config.get('failure') == 'validator-timeout':
        raise subprocess.TimeoutExpired(command, 120)
    code = config.get('validator_code', 0)
    message = config.get('validator_message', 'Validation passed')
    if config.get('parse_fixture'):
        try:
            json.loads((Path(command[3]) / packaging.CLAUDE_MANIFEST_RELATIVE).read_text())
        except ValueError:
            code, message = 1, 'Invalid manifest JSON'
    return subprocess.CompletedProcess(command, code, message, '')
sys.argv = [str(entry), *config.get('arguments', ['--expected-version', '2.1.289'])]
with patch('shutil.which', return_value=None if config.get('missing') else 'example-claude'), \\
     patch('subprocess.run', side_effect=run):
    runpy.run_path(str(entry), run_name='__main__')
'''


class ClaudeValidationOwnershipTests(unittest.TestCase):
    def run_entrypoint(self, config: dict) -> tuple[subprocess.CompletedProcess, list[dict]]:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            driver, settings, trace = (directory / name for name in ("driver.py", "config.json", "trace.jsonl"))
            driver.write_text(DRIVER, encoding="utf-8")
            settings.write_text(json.dumps(config), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-I", "-S", str(driver), str(ENTRYPOINT), str(settings), str(trace)],
                cwd=ROOT, capture_output=True, text=True, timeout=15,
                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1"},
            )
            calls = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
            return completed, calls

    def test_loader_ownership_is_35_static_cases_and_one_explicit_live_case(self):
        loader = unittest.TestLoader()
        self.assertEqual(loader.loadTestsFromModule(packaging).countTestCases(), 35)
        self.assertEqual(loader.loadTestsFromModule(installed).countTestCases(), 1)
        self.assertFalse(hasattr(packaging.AgentsDeclarationTests, LIVE_CASE))
        # Perform ordinary root discovery on a separate suite; never execute
        # or supply it to the production runner after this inspection.
        root_loader = unittest.TestLoader()
        with mock.patch.object(sys, "path", [str(ROOT), *sys.path]):
            suite = root_loader.discover(str(ROOT / "tests"))
        self.assertEqual(root_loader.errors, [])
        def check(group):
            for item in group:
                if isinstance(item, unittest.TestSuite):
                    check(item)
                else:
                    self.assertNotIn("installed_claude_validation", type(item).__module__)
        check(suite)

    def test_each_expected_matrix_build_validates_every_catalogue_manifest_once(self):
        expected = sorted(str(path.parent.parent) for path in (ROOT / "plugins").glob("*/.claude-plugin/plugin.json"))
        self.assertTrue(expected)
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        commands = [line.removeprefix("        run: ") for line in workflow.splitlines()
                    if line.startswith("        run: ") and "installed_claude_validation.py" in line]
        self.assertEqual(len(commands), 1)
        for version in ("2.1.286", "2.1.289", "2.1.296"):
            with self.subTest(version=version):
                command = shlex.split(commands[0].replace("${{ matrix.claude-code }}", version))
                self.assertEqual(command[0], "python3")
                self.assertEqual(ROOT / command[1], ENTRYPOINT)
                result, calls = self.run_entrypoint({
                    "version": version + " (Claude Code)\n",
                    "arguments": command[2:],
                })
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Ran 1 test", result.stderr)
                self.assertNotIn("skipped", result.stderr)
                self.assertEqual(calls[0]["command"][1:], ["--version"])
                self.assertEqual([call["command"][3] for call in calls[1:]], expected)
                for call in calls[1:]:
                    self.assertEqual(call["command"][1:3], ["plugin", "validate"])
                    self.assertEqual(call["options"]["timeout"], 120)

    def test_missing_cli_fails_without_skipping(self):
        result, calls = self.run_entrypoint({"missing": True})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("requires claude on PATH", result.stderr)
        self.assertNotIn("skipped", result.stderr)
        self.assertEqual(calls, [])

    def test_wrong_below_floor_malformed_or_failing_version_never_validates(self):
        for config in (
            {"version": "2.1.296 (Claude Code)\n"},
            {"version": "2.1.285 (Claude Code)\n"},
            {"version": "not a version\n"},
            {"version": "2.1.289 (different program)\n"},
            {"version_code": 2},
        ):
            with self.subTest(config=config):
                result, calls = self.run_entrypoint(config)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn("skipped", result.stderr)
                self.assertEqual(len(calls), 1)

    def test_missing_or_invalid_expected_build_is_an_argument_error(self):
        for arguments in ([], ["--expected-version", "invalid"], ["--expected-version", "2.1"]):
            with self.subTest(arguments=arguments):
                result, calls = self.run_entrypoint({"arguments": arguments})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(calls, [])

    def test_an_empty_catalogue_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, calls = self.run_entrypoint({"plugins": temporary})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("no Claude-installable packages", result.stderr)
        self.assertEqual(len(calls), 1)

    def test_invalid_manifest_reaches_validator_and_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "example" / ".claude-plugin" / "plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text("{invalid", encoding="utf-8")
            result, calls = self.run_entrypoint({"plugins": temporary, "parse_fixture": True})
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Invalid manifest JSON", result.stderr)
        self.assertEqual(calls[1]["command"][1:3], ["plugin", "validate"])
        self.assertEqual(len(calls), 2)

    def test_nonzero_validator_or_missing_success_diagnostic_fails(self):
        for config in ({"validator_code": 7}, {"validator_message": "validation did not run"}):
            with self.subTest(config=config):
                result, calls = self.run_entrypoint(config)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn("skipped", result.stderr)
                self.assertEqual(len(calls) - 1, len(packaging.claude_packages()))

    def test_transport_timeouts_remain_errors(self):
        for failure in ("version-timeout", "validator-timeout"):
            with self.subTest(failure=failure):
                result, _calls = self.run_entrypoint({"failure": failure})
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("TimeoutExpired", result.stderr)
                self.assertNotIn("skipped", result.stderr)


if __name__ == "__main__":
    unittest.main()
