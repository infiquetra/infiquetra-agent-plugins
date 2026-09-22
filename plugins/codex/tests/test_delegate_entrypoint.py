"""The wrapper must answer --help without credentials and without a network call.

``tests/test_client_entrypoints.py`` skips a package that has no
``PROVENANCE.json``. This package is authored here, so the same check lives
with the package.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / "scripts" / "codex_delegate.py"
CREDENTIAL_PREFIXES = ("OPENAI_", "CODEX_")


def test_delegate_help_runs_without_credentials() -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(CREDENTIAL_PREFIXES)
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # Keep the opt-in live smoke off, even if the parent suite set it.
    environment.pop("CODEX_DELEGATE_LIVE_SMOKE", None)
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env=environment,
        cwd=PACKAGE,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
    assert "Traceback" not in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr
