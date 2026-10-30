"""Explicit installed-CLI gate; excluded from root's test*.py discovery.

Run with --expected-version for the matrix build. Import the static module only
as a module for its pure catalogue, floor and version helpers; do not load its
TestCases here. The root gate owns all static assertions.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import unittest

import test_claude_plugin_packaging as packaging


def installed_claude_version(cli: str) -> tuple[int, int, int] | None:
    completed = subprocess.run(
        [cli, "--version"], capture_output=True, text=True, timeout=60, check=False
    )
    # A different program or a failing version command cannot satisfy the gate
    # just by printing a number. Keep one real version probe per invocation.
    line = completed.stdout.strip()
    suffix = " (Claude Code)"
    if completed.returncode != 0 or not line.endswith(suffix):
        return None
    match = packaging.CLAUDE_VERSION.fullmatch(line.removesuffix(suffix))
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


class InstalledClaudeValidationTests(unittest.TestCase):
    expected_version: tuple[int, int, int] | None = None

    def test_every_root_manifest_passes_the_cli_validator_when_the_cli_is_present(self) -> None:
        self.assertIsNotNone(self.expected_version, "use --expected-version for the matrix build")
        cli = shutil.which("claude")
        self.assertIsNotNone(cli, "the installed Claude validation lane requires claude on PATH")
        assert cli is not None
        version = installed_claude_version(cli)
        self.assertIsNotNone(version, f"could not read a version from `{cli} --version`")
        assert version is not None
        # All supported lanes promise mod compatibility: below-floor or wrong
        # installs fail the lane rather than skipping any mod-bearing package.
        self.assertGreaterEqual(version, packaging.CLAUDE_CODE_FLOOR)
        self.assertEqual(version, self.expected_version, "Claude does not match this matrix build")
        packages = packaging.claude_packages()
        self.assertTrue(packages, "no Claude-installable packages discovered")
        for package_root in packages:
            with self.subTest(package=package_root.name):
                completed = subprocess.run(
                    [cli, "plugin", "validate", str(package_root)],
                    capture_output=True, text=True, timeout=120, check=False,
                )
                self.assertEqual(completed.returncode, 0, (completed.stdout + completed.stderr)[-600:])
                self.assertIn("Validation passed", completed.stdout + completed.stderr,
                              (completed.stdout + completed.stderr)[-600:])


def matrix_version(value: str) -> tuple[int, int, int]:
    match = packaging.CLAUDE_VERSION.fullmatch(value)
    if match is None:
        raise argparse.ArgumentTypeError("expected a complete x.y.z matrix version")
    return tuple(int(match.group(index)) for index in (1, 2, 3))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True, type=matrix_version)
    args = parser.parse_args()
    InstalledClaudeValidationTests.expected_version = args.expected_version
    # TestProgram owns normal unittest failure/error/exit behavior. Only this
    # module's single live case is loaded; the imported static module is not.
    unittest.main(argv=[sys.argv[0], "-v"])


if __name__ == "__main__":
    main()
