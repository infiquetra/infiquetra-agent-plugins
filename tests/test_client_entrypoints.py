"""The portable clients must be runnable, not merely present.

This file guards one seam across all ported packages. A portable package drops
`fleet_commons_shim`, whose resolution ladder is Claude-specific runtime
discovery, and replaces it with a Fleet Core module bundled into the package
at build time. Two separate pieces of tooling own the two halves --
`scripts/sync_vendor_source.py` writes the clients, `scripts/bundle_fleet_module.py`
writes the bundle -- and for a while nothing owned the join between them.
Every validator passed while clients raised `ModuleNotFoundError` on `--help`,
before parsing a single argument, because they imported a module nothing had written.

The tests here run the shipped scripts where they actually live across every
package declared in `ports/*.json`, so the whole resolution path is exercised:
the client's own `sys.path` insertion, the generated bundle directory, and the
bundled module itself.

Transport is stubbed, and only transport. `requests` and `urllib3` are
third-party, and the repository's baseline validation job installs nothing at
all, so the stubs are what let this run under the standard library alone. They
are supplied unconditionally rather than only when the real packages are
absent, so the test asserts the same thing everywhere it runs. Nothing about
the Fleet Core bundle is stubbed: that is the thing under test.

When an entrypoint requires third-party dependencies that are absent in the
hermetic validation job (such as PyYAML), the entrypoint check skips with a clear
reason rather than failing, mirroring the two-CI-job dependency-split convention
(DECISIONS.md 2026-08-22).

No credentials are read and no network call is made. `--help` is answered by
argparse and exits before any client object is constructed, and the subprocess
runs with every package-specific credential variable (e.g. `UNIFI_*`, `GH_*`,
`GITHUB_*`) removed from its environment.
"""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_repo  # noqa: E402
import port_config  # noqa: E402
import sync_vendor_source as svs  # noqa: E402


#: Package-internal or Fleet Core modules that must never be treated as optional
#: third-party dependencies when diagnosing import errors.
BUNDLED_OR_INTERNAL_MODULES = frozenset(
    {
        "fleet_commons_shim",
        "retry_backoff",
        "intent_envelope",
        "tier_palette",
        "tier_resolver",
        "models",
        "site_profile",
        "site_profile_loader",
        "sdlc_manager",
        "board_census",
        "check_pagination",
        "executor_profile_lint",
        "sync_template_docs",
    }
)


def _missing_third_party_dependency(stderr: str) -> str | None:
    """Return the name of an uninstalled third-party dependency if that caused import failure."""
    match = re.search(r"ModuleNotFoundError:\s+No module named '([^']+)'", stderr)
    if not match:
        return None
    missing = match.group(1).split(".")[0]
    if missing in BUNDLED_OR_INTERNAL_MODULES:
        return None
    try:
        importlib.import_module(missing)
        return None
    except ImportError:
        return missing


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


def run_entrypoint(
    script: Path,
    *arguments: str,
    stubs: Path,
    credential_prefixes: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Run a client script with transport stubbed, declared credentials stripped, and no network."""
    environment = {
        key: value
        for key, value in os.environ.items()
        if not any(key.startswith(prefix) for prefix in credential_prefixes)
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


class EntrypointTests(unittest.TestCase):
    """Declared entrypoints across all ported packages must answer `--help` with no credentials and no network."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.stubs = write_transport_stubs(Path(self._temporary.name) / "stubs")

    def test_every_client_entrypoint_imports_cleanly_and_prints_usage(self) -> None:
        for config in port_config.load_all(ROOT):
            package = ROOT / config.package_root
            if not (package / check_repo.PROVENANCE_FILENAME).is_file():
                continue
            for relative in config.assessment.entrypoints:
                with self.subTest(package=config.name, entrypoint=relative):
                    script = package / relative
                    self.assertTrue(script.is_file(), f"{config.name} does not ship {relative}")
                    completed = run_entrypoint(
                        script,
                        "--help",
                        stubs=self.stubs,
                        credential_prefixes=config.assessment.credential_prefixes,
                    )
                    missing = _missing_third_party_dependency(completed.stderr)
                    if missing:
                        self.skipTest(
                            f"{config.name}:{relative} requires third-party dependency {missing!r} "
                            "not present in this environment"
                        )
                    self.assertEqual(
                        completed.returncode,
                        0,
                        f"{config.name}:{relative} --help exited {completed.returncode}\n"
                        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
                    )
                    self.assertTrue(
                        "usage:" in completed.stdout.lower()
                        or "pagination lint passed" in completed.stdout.lower()
                        or script.name in completed.stdout,
                        f"expected usage or help output in {completed.stdout!r}",
                    )
                    self.assertNotIn("ModuleNotFoundError", completed.stderr)
                    self.assertNotIn("Traceback", completed.stderr)

    def test_no_client_entrypoint_needs_credentials_to_report_its_command_surface(self) -> None:
        """`--help` is answered before any credential is read."""
        for config in port_config.load_all(ROOT):
            package = ROOT / config.package_root
            if not (package / check_repo.PROVENANCE_FILENAME).is_file():
                continue
            for relative in config.assessment.entrypoints:
                with self.subTest(package=config.name, entrypoint=relative):
                    script = package / relative
                    completed = run_entrypoint(
                        script,
                        "--help",
                        stubs=self.stubs,
                        credential_prefixes=config.assessment.credential_prefixes,
                    )
                    missing = _missing_third_party_dependency(completed.stderr)
                    if missing:
                        self.skipTest(
                            f"{config.name}:{relative} requires third-party dependency {missing!r} "
                            "not present in this environment"
                        )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    for prefix in config.assessment.credential_prefixes:
                        self.assertNotIn(prefix + "API_KEY", completed.stdout)
                        self.assertNotIn(prefix + "TOKEN", completed.stdout)
                        self.assertNotIn(prefix + "API_KEY", completed.stderr)
                        self.assertNotIn(prefix + "TOKEN", completed.stderr)


class BundleResolutionTests(unittest.TestCase):
    """The entrypoints must resolve the bundle this package ships, not something else.

    Without this, `test_every_client_entrypoint_imports_cleanly_and_prints_usage`
    could pass for the wrong reason -- a bundled module reachable from anywhere
    else on the interpreter's path would satisfy the import just as well and the
    seam would still be open.
    """

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.stubs = write_transport_stubs(Path(self._temporary.name) / "stubs")

    def test_the_generated_bundle_is_where_the_clients_resolve_it(self) -> None:
        for config in port_config.load_all(ROOT):
            package = ROOT / config.package_root
            if not (package / check_repo.PROVENANCE_FILENAME).is_file():
                continue
            for relative in config.custody.entrypoint_transforms:
                rule = config.custody.entrypoint_rules.get(relative, "")
                if not rule.startswith("resolve-bundled-fleet-module"):
                    continue
                with self.subTest(package=config.name, client=relative):
                    bundled_dir = (package / relative).parent / check_repo.BUNDLE_DIRECTORY_NAME
                    self.assertTrue(
                        bundled_dir.is_dir(),
                        f"no generated bundle directory at {bundled_dir} beside {config.name}:{relative}",
                    )
                    bundled_files = [
                        path
                        for path in bundled_dir.iterdir()
                        if path.is_file() and path.suffix == ".py"
                    ]
                    self.assertTrue(
                        bundled_files,
                        f"no python bundles in {bundled_dir} beside {config.name}:{relative}",
                    )
                    for bundled in bundled_files:
                        stamp_lines, _ = check_repo.split_bundle_stamp(
                            bundled.read_text(encoding="utf-8")
                        )
                        self.assertIsNotNone(
                            stamp_lines,
                            f"bundle {bundled.name} beside {config.name}:{relative} carries no stamp",
                        )

    def test_removing_the_generated_bundle_breaks_every_entrypoint(self) -> None:
        for config in port_config.load_all(ROOT):
            package = ROOT / config.package_root
            if not (package / check_repo.PROVENANCE_FILENAME).is_file():
                continue
            copy_pkg = Path(self._temporary.name) / f"package_{config.name}"
            if copy_pkg.exists():
                shutil.rmtree(copy_pkg)
            shutil.copytree(package, copy_pkg)

            for bundled_dir in copy_pkg.rglob(check_repo.BUNDLE_DIRECTORY_NAME):
                if bundled_dir.is_dir():
                    shutil.rmtree(bundled_dir)

            for relative in config.custody.entrypoint_transforms:
                rule = config.custody.entrypoint_rules.get(relative, "")
                if not rule.startswith("resolve-bundled-fleet-module"):
                    continue
                with self.subTest(package=config.name, client=relative):
                    args = (
                        ("issue", "intent-envelope", "--run-mode", "attended")
                        if relative == "scripts/sdlc_manager.py"
                        else ("--help",)
                    )
                    completed = run_entrypoint(
                        copy_pkg / relative,
                        *args,
                        stubs=self.stubs,
                        credential_prefixes=config.assessment.credential_prefixes,
                    )
                    missing = _missing_third_party_dependency(completed.stderr)
                    if missing:
                        self.skipTest(
                            f"{config.name}:{relative} requires third-party dependency {missing!r} "
                            "not present in this environment"
                        )
                    self.assertNotEqual(
                        completed.returncode,
                        0,
                        f"{config.name}:{relative} answered without the bundle it is supposed to import",
                    )
                    self.assertIn("ModuleNotFoundError", completed.stderr)

    def test_the_intact_copy_still_answers_help(self) -> None:
        """The control for the test above: the copy itself is not what breaks it."""
        for config in port_config.load_all(ROOT):
            package = ROOT / config.package_root
            if not (package / check_repo.PROVENANCE_FILENAME).is_file():
                continue
            copy_pkg = Path(self._temporary.name) / f"intact_{config.name}"
            if copy_pkg.exists():
                shutil.rmtree(copy_pkg)
            shutil.copytree(package, copy_pkg)

            for relative in config.custody.entrypoint_transforms:
                rule = config.custody.entrypoint_rules.get(relative, "")
                if not rule.startswith("resolve-bundled-fleet-module"):
                    continue
                with self.subTest(package=config.name, client=relative):
                    completed = run_entrypoint(
                        copy_pkg / relative,
                        "--help",
                        stubs=self.stubs,
                        credential_prefixes=config.assessment.credential_prefixes,
                    )
                    missing = _missing_third_party_dependency(completed.stderr)
                    if missing:
                        self.skipTest(
                            f"{config.name}:{relative} requires third-party dependency {missing!r} "
                            "not present in this environment"
                        )
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertTrue(
                        "usage:" in completed.stdout.lower()
                        or "pagination lint passed" in completed.stdout.lower()
                        or (copy_pkg / relative).name in completed.stdout,
                    )


if __name__ == "__main__":
    unittest.main()
