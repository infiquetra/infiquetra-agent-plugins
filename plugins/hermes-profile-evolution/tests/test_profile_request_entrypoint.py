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
    "metadata",
    "allowed-tools",
)


#: The frontmatter key form, matching ``scripts/check_repo.py``.
FRONTMATTER_KEY = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")

#: A double-quoted or single-quoted scalar at the start of a value.
QUOTED_SCALAR = re.compile(r"""^(?:"([^"]*)"|'([^']*)')""")


def _frontmatter_scalar(raw: str | None) -> str:
    """The scalar a value holds: quotes removed, and any trailing comment dropped."""
    if raw is None:
        return ""
    value = raw.strip()
    quoted = QUOTED_SCALAR.match(value)
    if quoted:
        return quoted.group(1) if quoted.group(1) is not None else quoted.group(2)
    if value.startswith("#"):
        return ""
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def _frontmatter(text: str) -> dict[str, object]:
    """Top-level keys. A key with no value opens a block, read one level deep, like the others."""
    lines = text.splitlines()
    assert lines and lines[0].strip() == "---"
    fields: dict[str, object] = {}
    owner: str | None = None
    child_indent: int | None = None
    for line in lines[1:]:
        if line.strip() == "---":
            return fields
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            owner, child_indent = None, None
            match = FRONTMATTER_KEY.match(line)
            assert match, f"unreadable frontmatter line: {line!r}"
            raw = match.group(2)
            if raw is None or not raw.strip() or raw.strip().startswith("#"):
                owner = match.group(1)
                fields[owner] = {}
            else:
                fields[match.group(1)] = _frontmatter_scalar(raw)
            continue
        if owner is None:
            continue
        if child_indent is None:
            child_indent = indent
        if indent != child_indent:
            continue
        child = line.strip()
        block = fields[owner]
        if child == "-" or child.startswith("- "):
            if isinstance(block, dict) and not block:
                block = fields[owner] = []
            if isinstance(block, list):
                block.append(_frontmatter_scalar(child[1:]))
            continue
        match = FRONTMATTER_KEY.match(child)
        if match and isinstance(block, dict):
            block[match.group(1)] = _frontmatter_scalar(match.group(2))
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
    assert isinstance(fields["description"], str) and fields["description"].strip()
    metadata = fields.get("metadata")
    assert isinstance(metadata, dict)
    assert metadata.get("compatibility") == "python>=3.12"
    assert "compatibility" not in fields
    assert "scripts/profile_request.py" in text
    for action in ACTIONS:
        assert action in text
    assert "HERMES_PROFILE_REQUEST_SSH_ALIAS" in text
    assert "HERMES_TEAM_MIMIR_ROOT" in text
    assert "does not claim shell-command interception" in text
