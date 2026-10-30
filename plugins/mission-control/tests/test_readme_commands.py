"""Execute documented commands with the plugin lane's real dependencies."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tests"))
# Share pure helpers through a module alias, never inherit/import a test class
# into pytest's namespace (that would collect the remaining root cases again).
import test_mission_control_readme as _readme

README = _readme.README
SYNC_SENTINEL = _readme.SYNC_SENTINEL
BUNDLE_SENTINEL = _readme.BUNDLE_SENTINEL
documented_bash_commands = _readme.documented_bash_commands
should_skip_running = _readme.should_skip_running


class ProvisionedReadmeTests(unittest.TestCase):
    setUp = _readme.PortableReadmeTests.setUp

    def test_every_fenced_bash_command_is_runnable_from_the_repository_root(self) -> None:
        """A documented command that cannot run is the defect class the pilot shipped."""
        if not SYNC_SENTINEL.is_file():
            self.skipTest(
                "Lane A sync artifacts are absent on this branch "
                f"({SYNC_SENTINEL.relative_to(ROOT)}); runnability asserts on the "
                "assembled integration branch"
            )
        if not BUNDLE_SENTINEL.is_file():
            self.skipTest(
                "Lane C bundle artifacts are absent on this branch "
                f"({BUNDLE_SENTINEL.relative_to(ROOT)}); runnability asserts on the "
                "assembled integration branch"
            )
        commands = documented_bash_commands(self.text)
        self.assertGreater(len(commands), 0, "the README documents no bash commands")
        with tempfile.TemporaryDirectory() as directory:
            xdg = Path(directory) / "config"
            xdg.mkdir()
            environment = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith(("GH_", "GITHUB_"))
            }
            environment["XDG_CONFIG_HOME"] = str(xdg)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            ran = 0
            for command in commands:
                if should_skip_running(command) or not command.startswith("python3 "):
                    continue
                completed = subprocess.run(
                    command,
                    shell=True,
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=60,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"documented command failed: {command}\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )
                ran += 1
            self.assertGreater(ran, 0, "every documented command was skipped rather than run")
