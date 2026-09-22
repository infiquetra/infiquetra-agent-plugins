"""Credential-free entrypoint probes for the authored mission-control package.

tests/test_client_entrypoints.py skips a package that has no PROVENANCE.json.
This module runs the same probe for the scripts the port descriptor names.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
ENTRYPOINTS = (
    "scripts/sdlc_manager.py",
    "scripts/board_census.py",
    "scripts/check_pagination.py",
    "scripts/executor_profile_lint.py",
    "scripts/sync_template_docs.py",
)


@pytest.mark.parametrize("relative", ENTRYPOINTS)
def test_entrypoint_help_exits_zero_without_github_credentials(relative: str) -> None:
    script = PACKAGE / relative
    assert script.is_file()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("GH_", "GITHUB_"))
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    combined = (completed.stdout + completed.stderr).lower()
    assert "usage:" in combined or "pagination lint passed" in combined
