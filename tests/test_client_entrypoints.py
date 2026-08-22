"""The portable clients must be runnable, not merely present.

This file guards one seam. The portable package drops `fleet_commons_shim`,
whose resolution ladder is Claude-specific runtime discovery, and replaces it
with a Fleet Core module bundled into the package at build time. Two separate
pieces of tooling own the two halves -- `scripts/sync_vendor_source.py` writes
the clients, `scripts/bundle_fleet_module.py` writes the bundle -- and for a
while nothing owned the join between them. Every validator passed while both
clients raised `ModuleNotFoundError` on `--help`, before parsing a single
argument, because they imported a module nothing had written.

The tests here run the shipped scripts where they actually live, so the whole
resolution path is exercised: the client's own `sys.path` insertion, the
generated bundle directory, and the bundled module itself.

Transport is stubbed, and only transport. `requests` and `urllib3` are
third-party, and the repository's baseline validation job installs nothing at
all, so the stubs are what let this run under the standard library alone. They
are supplied unconditionally rather than only when the real packages are
absent, so the test asserts the same thing everywhere it runs. Nothing about
the Fleet Core bundle is stubbed: that is the thing under test.

No credentials are read and no network call is made. `--help` is answered by
argparse and exits before any client object is constructed, and the subprocess
runs with every `UNIFI_*` variable removed from its environment.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import sync_vendor_source as svs  # noqa: E402


PACKAGE = ROOT / "plugins" / svs.TARGET_PACKAGE


def bundle_beside(client: Path, module: str = "retry_backoff") -> Path:
    """The generated bundle a rewritten client resolves, beside the client itself."""
    return client.parent / svs.BUNDLE_DIRECTORY_NAME / f"{module}.py"

#: Inert stand-ins for the two third-party imports the clients make at module
#: scope. Neither participates in building an argument parser.
TRANSPORT_STUBS: dict[str, str] = {
    "requests.py": (
        '"""Inert stand-in for the requests package (test transport stub)."""\n'
        "\n\n"
        "class Session:  # pragma: no cover - never called by --help\n"
        "    pass\n"
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


def run_entrypoint(script: Path, *arguments: str, stubs: Path) -> subprocess.CompletedProcess[str]:
    """Run a client script with transport stubbed, no credentials, and no network."""
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("UNIFI_")
    }
    environment["PYTHONPATH"] = str(stubs)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(script), *arguments],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
    )


def _skip_unless_shipped(test: unittest.TestCase) -> None:
    if not (PACKAGE / check_repo.PROVENANCE_FILENAME).is_file():
        test.skipTest("the portable unifi package has not been synchronized yet")


class EntrypointTests(unittest.TestCase):
    """Both clients must answer `--help` with no credentials and no network."""

    def setUp(self) -> None:
        _skip_unless_shipped(self)
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.stubs = write_transport_stubs(Path(self._temporary.name) / "stubs")

    def test_every_client_entrypoint_imports_cleanly_and_prints_usage(self) -> None:
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                script = PACKAGE / relative
                self.assertTrue(script.is_file(), f"the package does not ship {relative}")
                completed = run_entrypoint(script, "--help", stubs=self.stubs)
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{relative} --help exited {completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                )
                self.assertIn("usage:", completed.stdout)
                self.assertIn(script.name, completed.stdout)
                self.assertNotIn("ModuleNotFoundError", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_no_client_entrypoint_needs_credentials_to_report_its_command_surface(self) -> None:
        """`--help` is answered before any credential is read.

        The clients exit 1 on an absent API key, so a `--help` that reached the
        client constructor would fail here rather than print usage.
        """
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                completed = run_entrypoint(PACKAGE / relative, "--help", stubs=self.stubs)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertNotIn("UNIFI_API_KEY", completed.stdout)
                self.assertNotIn("UNIFI_API_KEY", completed.stderr)


class BundleResolutionTests(unittest.TestCase):
    """The entrypoints must resolve the bundle this package ships, not something else.

    Without this, `test_every_client_entrypoint_imports_cleanly_and_prints_usage`
    could pass for the wrong reason -- a `retry_backoff` reachable from anywhere
    else on the interpreter's path would satisfy the import just as well and the
    seam would still be open.
    """

    def setUp(self) -> None:
        _skip_unless_shipped(self)
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.stubs = write_transport_stubs(Path(self._temporary.name) / "stubs")
        self.copy = Path(self._temporary.name) / "package"
        shutil.copytree(PACKAGE, self.copy)

    def test_the_generated_bundle_is_where_the_clients_resolve_it(self) -> None:
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                bundled = bundle_beside(PACKAGE / relative)
                self.assertTrue(bundled.is_file(), f"no generated bundle at {bundled}")
                stamp_lines, _ = check_repo.split_bundle_stamp(
                    bundled.read_text(encoding="utf-8")
                )
                self.assertIsNotNone(
                    stamp_lines, "the bundle the client imports carries no stamp"
                )

    def test_removing_the_generated_bundle_breaks_every_entrypoint(self) -> None:
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            bundle_beside(self.copy / relative).unlink()
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                completed = run_entrypoint(self.copy / relative, "--help", stubs=self.stubs)
                self.assertNotEqual(
                    completed.returncode,
                    0,
                    f"{relative} answered --help without the bundle it is supposed to import",
                )
                self.assertIn("ModuleNotFoundError", completed.stderr)

    def test_the_intact_copy_still_answers_help(self) -> None:
        """The control for the test above: the copy itself is not what breaks it."""
        for relative in svs.PORTABLE_ENTRYPOINT_TRANSFORMS:
            with self.subTest(client=relative):
                completed = run_entrypoint(self.copy / relative, "--help", stubs=self.stubs)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("usage:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
