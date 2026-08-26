"""The stable ``voice`` launcher: what it writes, and what it refuses to write.

The launcher exists because Claude's install path carries the version --
``.../voice/0.1.0/`` -- and a version bump creates a new directory rather than
reusing the old one. A Herdr keybinding written against a versioned path stops
working at the next release without announcing it. So the binding invokes a
launcher that resolves the install at *invocation* time.

These tests cover the two things that make it trustworthy: the emitted file is
genuinely runnable, and installing it never clobbers something that was already
there under that name.

Standard library only. No network, no writes outside a temporary directory.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


_PACKAGE = Path(__file__).resolve().parents[1]
_INSTALLER = _PACKAGE / "com.infiquetra.claude" / "scripts" / "install_launcher.py"

sys.path.insert(0, str(_INSTALLER.parent))
import install_launcher  # noqa: E402


class LauncherEmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name) / "bin" / "voice"

    def test_the_written_launcher_is_executable_and_has_a_shebang(self) -> None:
        path = install_launcher.install(self.destination)
        self.assertEqual(path, self.destination)
        self.assertTrue(path.is_file())
        self.assertTrue(os.access(path, os.X_OK), "the launcher must be executable")
        self.assertTrue(
            path.read_text(encoding="utf-8").startswith("#!"),
            "without a shebang the launcher is not directly runnable",
        )

    def test_the_launcher_resolves_a_recorded_install_and_forwards_arguments(
        self,
    ) -> None:
        # A complete stand-in for Claude's registry and install, so the whole
        # resolution path runs without touching the real one.
        root = Path(self.tmp.name)
        install_root = root / "cache" / "voice" / "9.9.9"
        (install_root / "scripts").mkdir(parents=True)
        (install_root / "scripts" / "voice_cli.py").write_text(
            "import sys\nprint('cli got:', *sys.argv[1:])\n", encoding="utf-8"
        )
        registry = root / "installed_plugins.json"
        registry.write_text(
            '{"plugins": {"voice@infiquetra-agent-plugins": ['
            '{"installPath": "' + str(install_root) + '", '
            '"version": "9.9.9", "lastUpdated": "2026-01-01T00:00:00.000Z"}]}}',
            encoding="utf-8",
        )
        body = install_launcher.render_launcher().replace(
            repr(str(install_launcher.REGISTRY)), repr(str(registry))
        )
        launcher = root / "voice"
        launcher.write_text(body, encoding="utf-8")
        launcher.chmod(0o755)

        done = subprocess.run(
            [sys.executable, str(launcher), "stop"], capture_output=True, text=True
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("cli got: stop", done.stdout)

    def test_the_newest_install_wins_when_several_are_recorded(self) -> None:
        root = Path(self.tmp.name)
        registry = root / "installed_plugins.json"
        entries = []
        for version, stamp in (("1.0.0", "2026-01-01"), ("2.0.0", "2026-06-01")):
            install_root = root / version
            (install_root / "scripts").mkdir(parents=True)
            (install_root / "scripts" / "voice_cli.py").write_text(
                f"print('version {version}')\n", encoding="utf-8"
            )
            entries.append(
                '{"installPath": "' + str(install_root) + '", "version": "'
                + version + '", "lastUpdated": "' + stamp + 'T00:00:00.000Z"}'
            )
        registry.write_text(
            '{"plugins": {"voice@infiquetra-agent-plugins": ['
            + ", ".join(entries) + "]}}",
            encoding="utf-8",
        )
        body = install_launcher.render_launcher().replace(
            repr(str(install_launcher.REGISTRY)), repr(str(registry))
        )
        launcher = root / "voice"
        launcher.write_text(body, encoding="utf-8")
        launcher.chmod(0o755)
        done = subprocess.run(
            [sys.executable, str(launcher)], capture_output=True, text=True
        )
        self.assertIn("version 2.0.0", done.stdout)

    def test_a_missing_install_is_refused_by_name_not_silently(self) -> None:
        # A stop key that fails quietly is the defect this whole module exists
        # to prevent, so the failure path has to say something.
        root = Path(self.tmp.name)
        registry = root / "installed_plugins.json"
        registry.write_text('{"plugins": {}}', encoding="utf-8")
        body = install_launcher.render_launcher().replace(
            repr(str(install_launcher.REGISTRY)), repr(str(registry))
        )
        launcher = root / "voice"
        launcher.write_text(body, encoding="utf-8")
        launcher.chmod(0o755)
        done = subprocess.run(
            [sys.executable, str(launcher), "stop"], capture_output=True, text=True
        )
        self.assertEqual(done.returncode, 1)
        self.assertIn("not installed", done.stderr)


class LauncherOverwriteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.destination = Path(self.tmp.name) / "voice"

    def test_a_foreign_voice_on_path_is_never_clobbered(self) -> None:
        self.destination.write_text("#!/bin/sh\necho someone else's\n", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            install_launcher.install(self.destination)
        self.assertIn("not generated by this command", str(caught.exception))
        self.assertIn("someone else's", self.destination.read_text(encoding="utf-8"))

    def test_force_replaces_a_foreign_file_when_asked(self) -> None:
        self.destination.write_text("#!/bin/sh\necho other\n", encoding="utf-8")
        install_launcher.install(self.destination, force=True)
        self.assertIn("Generated file.", self.destination.read_text(encoding="utf-8"))

    def test_regenerating_over_a_previous_launcher_is_allowed(self) -> None:
        install_launcher.install(self.destination)
        install_launcher.install(self.destination)
        self.assertIn("Generated file.", self.destination.read_text(encoding="utf-8"))

    def test_print_mode_writes_nothing(self) -> None:
        code = install_launcher.main(["--print"])
        self.assertEqual(code, 0)
        self.assertFalse(self.destination.exists())


class PackagedCliTests(unittest.TestCase):
    """The CLI the launcher execs must itself be a runnable file."""

    def test_the_cli_has_a_shebang_and_the_executable_bit(self) -> None:
        cli = _PACKAGE / "scripts" / "voice_cli.py"
        self.assertTrue(
            cli.read_text(encoding="utf-8").startswith("#!"),
            "the CLI is documented as an operator surface; it needs a shebang",
        )
        self.assertTrue(os.access(cli, os.X_OK), "the CLI must be executable")

    def test_the_installer_lives_in_the_claude_extension(self) -> None:
        # Reading Claude's plugin registry is Claude client knowledge, so it
        # belongs in the adapter rather than the portable core.
        self.assertTrue(_INSTALLER.is_file())
        self.assertFalse((_PACKAGE / "scripts" / "install_launcher.py").exists())


if __name__ == "__main__":
    unittest.main()
