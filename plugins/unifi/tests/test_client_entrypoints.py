"""Run the UniFi clients the way a user runs them: ``--help``, no credentials.

``tests/test_client_entrypoints.py`` at the repository root skips a package
that has no ``PROVENANCE.json``. An authored package has none, so this module
is the check that both clients still answer ``--help``.

Transport is stubbed, and only transport. ``requests`` and ``urllib3`` are
third-party, and ``--help`` exits inside argparse before either is called.
Nothing about the Fleet Core bundle is stubbed: that import is part of
starting the script.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = (
    PACKAGE_ROOT / "skills" / "unifi-network" / "scripts" / "unifi_network_client.py",
    PACKAGE_ROOT / "skills" / "unifi-protect" / "scripts" / "unifi_protect_client.py",
)

TRANSPORT_STUBS: dict[str, str] = {
    "requests.py": (
        '"""Inert stand-in for the requests package (test transport stub)."""\n'
        "\n\n"
        "def request(*arguments, **keywords):  # pragma: no cover - never called by --help\n"
        '    raise AssertionError("--help must not make a network call")\n'
    ),
    "urllib3/__init__.py": (
        '"""Inert stand-in for the urllib3 package (test transport stub)."""\n'
        "\n"
        "from . import exceptions\n"
        "\n\n"
        "def disable_warnings(*arguments, **keywords):\n"
        "    return None\n"
    ),
    "urllib3/exceptions.py": (
        '"""Inert stand-in for urllib3.exceptions (test transport stub)."""\n'
        "\n\n"
        "class InsecureRequestWarning(Warning):\n"
        "    pass\n"
    ),
}


def write_transport_stubs(directory: Path) -> Path:
    for relative, body in TRANSPORT_STUBS.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return directory


class ClientHelpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.stubs = write_transport_stubs(Path(self._temporary.name) / "stubs")

    def test_each_client_answers_help_without_credentials(self) -> None:
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("UNIFI_")
        }
        environment["PYTHONPATH"] = str(self.stubs)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for script in ENTRYPOINTS:
            with self.subTest(script=script.name):
                self.assertTrue(script.is_file(), script)
                completed = subprocess.run(
                    [sys.executable, str(script), "--help"],
                    capture_output=True,
                    text=True,
                    env=environment,
                    timeout=60,
                    check=False,
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{script.name} --help exited {completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )
                self.assertIn("usage:", completed.stdout.lower())
                self.assertNotIn("Traceback", completed.stderr)
                self.assertNotIn("ModuleNotFoundError", completed.stderr)
                self.assertNotIn("UNIFI_API_KEY", completed.stdout)
                self.assertNotIn("UNIFI_API_KEY", completed.stderr)


if __name__ == "__main__":
    unittest.main()
