"""The team-scaffold command must answer --help the way a user runs it.

No credential is read and no network call is made. ``--help`` is argparse,
and it exits before any checkout is opened. PyYAML is imported while the
package loads; when it is absent the test skips, matching the repository's
split between the hermetic validation job and the plugin-test job.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from team_scaffold.paths import default_context_library, default_hosts_path, home_lab_root

PACKAGE = Path(__file__).resolve().parents[1]
LAUNCHER = PACKAGE / "skills" / "team-scaffold" / "scripts" / "team-scaffold"
MATERIALIZE = PACKAGE / "skills" / "team-scaffold" / "scripts" / "materialize_specs.py"

_STRIPPED = ("ANSIBLE_", "VAULT_", "DISCORD_", "GITHUB_", "GH_")
_REMOVED = ("HOME_LAB_ROOT", "INFIQUETRA_CONTEXT_LIBRARY")


def _environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in _REMOVED and not key.startswith(_STRIPPED)
    }
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *arguments],
        capture_output=True,
        text=True,
        env=_environment(),
        timeout=60,
        check=False,
    )


def _flat(text: str) -> str:
    """Join wrapped help lines, including a hyphen argparse inserts at a break."""
    return "".join(line.strip() for line in text.splitlines())


def _skip_if_yaml_missing(completed: subprocess.CompletedProcess[str]) -> None:
    if "No module named 'yaml'" in completed.stderr or 'No module named "yaml"' in completed.stderr:
        pytest.skip("this command imports pyyaml, which is not installed")


def test_documented_defaults_are_not_a_machine_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HOME_LAB_ROOT", raising=False)
    monkeypatch.delenv("INFIQUETRA_CONTEXT_LIBRARY", raising=False)
    values = (home_lab_root(), default_hosts_path(), default_context_library())
    for value in values:
        assert "/Users/" not in value
        assert "workspace/infiquetra" not in value
    assert home_lab_root() == "~/home-lab"
    assert default_hosts_path() == "~/home-lab/ansible/inventory/hosts.yml"
    assert default_context_library() == "~/infiquetra-context-library"


def test_launcher_help_names_usage_and_the_documented_defaults() -> None:
    completed = _run(str(LAUNCHER), "--help")
    _skip_if_yaml_missing(completed)
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
    assert "Traceback" not in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr

    register = _run(str(LAUNCHER), "register-host", "--help")
    _skip_if_yaml_missing(register)
    stamp = _run(str(LAUNCHER), "stamp", "--help")
    _skip_if_yaml_missing(stamp)
    materialize = _run(str(MATERIALIZE), "--help")
    _skip_if_yaml_missing(materialize)
    for completed_help in (completed, register, stamp, materialize):
        assert completed_help.returncode == 0, completed_help.stderr
        combined = completed_help.stdout + completed_help.stderr
        assert "/Users/" not in combined
        assert "workspace/infiquetra" not in combined
    assert "~/home-lab" in _flat(register.stdout)
    assert "~/home-lab/ansible/inventory/hosts.yml" in _flat(materialize.stdout)
    assert "~/infiquetra-context-library" in _flat(stamp.stdout)
