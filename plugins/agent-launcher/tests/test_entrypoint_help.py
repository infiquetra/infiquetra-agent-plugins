"""The package entrypoints answer ``--help`` the way a user runs them.

No credential is read and no Herdr call is made. ``--help`` is argparse, and
it exits before roster.py asks saga for a run record.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
SCRIPTS = PACKAGE / "skills" / "agent-launcher" / "scripts"
ENTRYPOINTS = ("launcher.py", "roster.py")


@pytest.mark.parametrize("name", ENTRYPOINTS)
def test_entrypoint_help_exits_zero(name: str) -> None:
    script = SCRIPTS / name
    env = os.environ.copy()
    for key in list(env):
        if key.startswith(("GH_", "GITHUB_", "CLAUDE_")):
            env.pop(key, None)
    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
    assert "Traceback" not in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr
