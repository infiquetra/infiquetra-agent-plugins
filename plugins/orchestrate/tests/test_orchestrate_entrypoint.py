"""The shipped driver must answer ``--help`` the way a user runs it.

No credentials, no network, and no live Herdr. The companion environment
variables are unset so this exercises the catalog default: the sibling
``plugins/agent-launcher``, which in this catalog is below the declared floor
and is not ingested. ``--help`` is still Orchestrate's own parser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / "skills" / "orchestrate" / "scripts" / "orchestrate.py"

_STRIPPED_PREFIXES = ("GH_", "GITHUB_", "AWS_", "UNIFI_")
_STRIPPED_NAMES = ("AGENT_LAUNCHER_ROOT", "CLAUDE_PLUGIN_ROOT", "ORCHESTRATE_RUN_RECORD")


def test_help_exits_zero_without_credentials() -> None:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _STRIPPED_NAMES and not any(key.startswith(prefix) for prefix in _STRIPPED_PREFIXES)
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
    assert "ModuleNotFoundError" not in completed.stderr
    assert "Traceback" not in completed.stderr
