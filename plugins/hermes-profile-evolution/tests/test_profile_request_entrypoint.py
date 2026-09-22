"""The request script must answer ``--help`` the way a user runs it.

``tests/test_client_entrypoints.py`` skips a package with no provenance
manifest. This package is authored here, so the credential-free run lives
with the package. Transport stubs are unnecessary: the script imports only
the standard library, and ``--help`` exits before it builds a command.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
SCRIPT = PACKAGE / "scripts/profile_request.py"
GUARD = PACKAGE / "com.infiquetra.claude/hooks/profile_edit_guard.py"
SKILL = PACKAGE / "skills/hermes-profile-evolution/SKILL.md"

ROUTING_PREFIXES = ("HERMES_PROFILE_REQUEST_", "HERMES_TEAM_MIMIR_")
ACTIONS = ("suggest", "reply", "resume", "status", "census")

ALLOWED_FRONTMATTER_FIELDS = (
    "name",
    "description",
    "license",
    "compatibility",
    "metadata",
    "allowed-tools",
)


def _frontmatter(text: str) -> dict[str, str]:
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---"
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if not line.strip() or line[0] in " \t-#":
            continue
        key, separator, value = line.partition(":")
        assert separator
        fields[key.strip()] = value.strip()
    raise AssertionError("skill frontmatter is unterminated")


def _routing_free_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(ROUTING_PREFIXES)
    }


def test_help_runs_without_routing_variables() -> None:
    environment = _routing_free_environment()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
    for action in ACTIONS:
        assert action in completed.stdout
    assert "Traceback" not in completed.stderr
    assert "ModuleNotFoundError" not in completed.stderr
    for prefix in ROUTING_PREFIXES:
        assert prefix not in completed.stdout
        assert prefix not in completed.stderr


def test_routing_variables_have_no_host_default() -> None:
    """Unset means local ``hermes`` or an upward search, never a filled-in host."""
    for path, variable in (
        (SCRIPT, "HERMES_PROFILE_REQUEST_SSH_ALIAS"),
        (GUARD, "HERMES_TEAM_MIMIR_ROOT"),
    ):
        source = path.read_text(encoding="utf-8")
        match = re.search(
            rf'os\.environ\.get\(\s*"{variable}"\s*(?:,\s*[^)]+)?\)',
            source,
        )
        assert match, f"{path.name} does not read {variable}"
        assert "," not in match.group(0), f"{variable} is given a default"


def test_skill_names_the_script_actions_and_routing_variables() -> None:
    text = SKILL.read_text(encoding="utf-8")
    fields = _frontmatter(text)
    assert set(fields) <= set(ALLOWED_FRONTMATTER_FIELDS)
    assert fields["name"] == "hermes-profile-evolution"
    assert fields["description"].strip()
    assert fields.get("compatibility") == "python>=3.12"
    assert "scripts/profile_request.py" in text
    for action in ACTIONS:
        assert action in text
    assert "HERMES_PROFILE_REQUEST_SSH_ALIAS" in text
    assert "HERMES_TEAM_MIMIR_ROOT" in text
    assert "does not claim shell-command interception" in text
