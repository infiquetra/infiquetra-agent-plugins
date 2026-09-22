"""The wrapper must answer --help the way a user runs it, with no credentials."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
IMPLEMENTATION = PACKAGE / "skills" / "agy-delegate" / "scripts" / "agy_delegate.py"
LAUNCHER = PACKAGE / "scripts" / "agy_delegate.py"
BUNDLE = PACKAGE / "skills" / "agy-delegate" / "scripts" / "_bundled"

_CREDENTIAL_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "_KEY")


def _scrubbed_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for name in list(environment):
        if any(marker in name for marker in _CREDENTIAL_MARKERS):
            del environment[name]
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _help(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        env=_scrubbed_environment(),
        timeout=60,
        check=False,
    )


def test_implementation_and_launcher_print_usage_without_credentials() -> None:
    for script in (IMPLEMENTATION, LAUNCHER):
        completed = _help(script)
        assert completed.returncode == 0, completed.stderr
        assert "usage:" in completed.stdout.lower()
        assert "Traceback" not in completed.stderr
        assert "ModuleNotFoundError" not in completed.stderr
        assert "/Users/" not in completed.stdout
        assert "/Users/" not in completed.stderr


def test_removing_the_bundle_breaks_the_implementation(tmp_path: Path) -> None:
    held = tmp_path / "bundle"
    BUNDLE.rename(held)
    try:
        completed = _help(IMPLEMENTATION)
    finally:
        held.rename(BUNDLE)
    assert completed.returncode != 0
    assert "ModuleNotFoundError" in completed.stderr or "Traceback" in completed.stderr
