"""The redis-channel entrypoints must answer --help with no credentials.

Follows tests/test_client_entrypoints.py. The repository-wide check only
runs entrypoints for packages that still carry PROVENANCE.json. This package
is authored here, so the same run lives next to the package.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MCP_SERVER = PACKAGE_ROOT / "scripts" / "mcp_server.py"
INTEG = PACKAGE_ROOT / "scripts" / "integ_test.py"
WRAPPER = PACKAGE_ROOT / "scripts" / "claude-channel.sh"


def _env_without_channel_credentials() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("REDIS_CHANNEL_") and key != "HERMES_REDIS_PASSWORD"
    }


def _run(argv: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        capture_output=True,
        text=True,
        env=_env_without_channel_credentials(),
        timeout=30,
        check=False,
    )


class EntrypointTests(unittest.TestCase):
    def test_mcp_server_help_needs_no_runtime_packages_or_credentials(self) -> None:
        completed = _run([sys.executable, str(MCP_SERVER), "--help"])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())
        self.assertNotIn("Traceback", completed.stderr)
        self.assertNotIn("ModuleNotFoundError", completed.stderr)

    def test_module_help_needs_no_runtime_packages(self) -> None:
        completed = _run([sys.executable, "-m", "server", "--help"], cwd=PACKAGE_ROOT)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage:", completed.stdout.lower())
        self.assertNotIn("Traceback", completed.stderr)

    def test_integration_help_and_skip_when_unset(self) -> None:
        help_run = _run([sys.executable, str(INTEG), "--help"])
        self.assertEqual(help_run.returncode, 0, help_run.stderr)
        self.assertIn("usage:", help_run.stdout.lower())

        skipped = _run([sys.executable, str(INTEG)])
        self.assertEqual(skipped.returncode, 0, skipped.stderr)
        self.assertIn("REDIS_CHANNEL_INTEG_HOST", skipped.stderr)
        self.assertIn("skip:", skipped.stderr)

    def test_wrapper_help_does_not_require_claude(self) -> None:
        completed = _run(["bash", str(WRAPPER), "--help"])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--session-name", completed.stdout)
        self.assertIn("infiquetra-agent-plugins", completed.stdout)

    def test_server_info_version_matches_the_package_manifests(self) -> None:
        import json
        import re

        literal = re.search(
            r'"serverInfo":\s*\{[^}]*"version":\s*"([^"]+)"',
            MCP_SERVER.read_text(encoding="utf-8"),
        )
        self.assertIsNotNone(literal)
        assert literal is not None
        version = literal.group(1)
        for relative in (
            "plugin.json",
            ".claude-plugin/plugin.json",
            "com.infiquetra.claude/plugin.json",
        ):
            manifest = json.loads((PACKAGE_ROOT / relative).read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], version, relative)
        sys.path.insert(0, str(PACKAGE_ROOT))
        from server import __version__

        self.assertEqual(__version__, version)


if __name__ == "__main__":
    unittest.main()
