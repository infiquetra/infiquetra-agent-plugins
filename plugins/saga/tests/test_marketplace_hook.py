"""
AE5 tests for the marketplace / plugin.json validation hook.

Covers:
- Valid JSON on marketplace.json / plugin.json → hook exits 0 (pass)
- Invalid JSON (unbalanced bracket) on marketplace.json → hook exits 2 (block) + prints offending line
- Unrelated file → hook exits 0 regardless of content
- Write tool with invalid content → blocked
- Edit tool that would produce invalid JSON → blocked
- Edit tool that produces valid JSON → passes
- Hook is callable as a standalone script
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "validate_json_hook.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    """Run the hook script with the given JSON payload on stdin."""
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )
    return result


def _write_payload(file_path: str, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {
            "file_path": file_path,
            "content": content,
        },
    }


def _edit_payload(file_path: str, old_string: str, new_string: str) -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": file_path,
            "old_string": old_string,
            "new_string": new_string,
        },
    }


# ---------------------------------------------------------------------------
# Hook file existence
# ---------------------------------------------------------------------------


def test_hook_script_exists() -> None:
    """The hook script must exist at the expected path."""
    assert HOOK_SCRIPT.exists(), f"Missing hook script: {HOOK_SCRIPT}"


def test_hooks_json_exists() -> None:
    """hooks.json must exist in the saga plugin's hooks/ dir."""
    hooks_json = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"
    assert hooks_json.exists(), f"Missing hooks.json: {hooks_json}"


def test_hooks_json_is_valid() -> None:
    """hooks.json must itself be parseable JSON."""
    hooks_json = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"
    data = json.loads(hooks_json.read_text())
    assert set(data) == {"hooks"}


def test_hooks_json_wires_pretooluse() -> None:
    """hooks.json must register a PreToolUse hook."""
    hooks_json = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"
    data = json.loads(hooks_json.read_text())
    assert "PreToolUse" in data["hooks"], "hooks.json must have a PreToolUse section"
    entries = data["hooks"]["PreToolUse"]
    assert len(entries) > 0, "PreToolUse must have at least one entry"
    # Each entry must have hooks with a command type
    commands = [
        h["command"]
        for entry in entries
        for h in entry.get("hooks", [])
        if h.get("type") == "command"
    ]
    assert any("validate_json_hook" in cmd for cmd in commands), (
        "PreToolUse must reference validate_json_hook.py"
    )


def test_hooks_json_matcher_covers_write_edit() -> None:
    """The matcher must cover Edit, Write, and MultiEdit."""
    hooks_json = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "hooks.json"
    data = json.loads(hooks_json.read_text())
    entries = data["hooks"]["PreToolUse"]
    matchers = [e.get("matcher", "") for e in entries]
    combined = "|".join(matchers)
    for tool in ("Edit", "Write", "MultiEdit"):
        assert tool in combined, f"matcher must include {tool}; got matchers={matchers}"


# ---------------------------------------------------------------------------
# AE5: Valid JSON → exit 0 (pass)
# ---------------------------------------------------------------------------


def test_valid_marketplace_json_passes() -> None:
    """A syntactically correct marketplace.json Write → exit 0."""
    valid = json.dumps({"name": "infiquetra-plugins", "plugins": [], "version": "3.0.0"})
    result = _run_hook(_write_payload(".claude-plugin/marketplace.json", valid))
    assert result.returncode == 0, f"Expected pass; stderr={result.stderr!r}"


def test_valid_plugin_json_passes() -> None:
    """A syntactically correct plugin.json Write → exit 0."""
    valid = json.dumps({"name": "saga", "version": "0.24.0"})
    result = _run_hook(_write_payload("plugins/saga/.claude-plugin/plugin.json", valid))
    assert result.returncode == 0, f"Expected pass; stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# AE5: Unbalanced brackets → exit 2 (block) + offending line named
# ---------------------------------------------------------------------------


def test_unbalanced_bracket_marketplace_json_is_blocked() -> None:
    """An unbalanced-bracket marketplace.json Write → exit 2, offending line in stderr."""
    broken = '{"name": "infiquetra-plugins", "plugins": []\n]}\n]'
    result = _run_hook(_write_payload(".claude-plugin/marketplace.json", broken))
    assert result.returncode == 2, (
        f"Expected exit 2 (block); got {result.returncode}, stderr={result.stderr!r}"
    )
    # stderr must mention the file path
    assert "marketplace.json" in result.stderr, f"stderr must name the file; got: {result.stderr!r}"
    # stderr must indicate a line number
    assert "line" in result.stderr, f"stderr must name the offending line; got: {result.stderr!r}"


def test_unbalanced_bracket_plugin_json_is_blocked() -> None:
    """An unbalanced-bracket plugin.json Write → exit 2, offending line in stderr."""
    broken = '{"name": "saga", "version": "0.24.0"'  # missing closing }
    result = _run_hook(_write_payload("plugins/saga/.claude-plugin/plugin.json", broken))
    assert result.returncode == 2, (
        f"Expected exit 2 (block); got {result.returncode}, stderr={result.stderr!r}"
    )
    assert "plugin.json" in result.stderr, f"stderr must name the file; got: {result.stderr!r}"
    assert "line" in result.stderr, f"stderr must name the offending line; got: {result.stderr!r}"


def test_extra_closing_bracket_is_blocked() -> None:
    """The classic double-] corruption pattern → exit 2."""
    # Reproduce the known marketplace.json double-] bug
    broken = '{"plugins": []\n]\n}'
    result = _run_hook(_write_payload(".claude-plugin/marketplace.json", broken))
    assert result.returncode == 2, (
        f"Expected exit 2; got {result.returncode}, stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# Unrelated files → exit 0 (pass-through)
# ---------------------------------------------------------------------------


def test_unrelated_file_passes_regardless_of_content() -> None:
    """An Edit/Write on a non-JSON-target file is not blocked, even if content is garbage."""
    result = _run_hook(_write_payload("plugins/saga/skills/plan/SKILL.md", "}{broken}{"))
    assert result.returncode == 0, f"Expected pass-through; stderr={result.stderr!r}"


def test_unrelated_python_file_passes() -> None:
    """A .py file write is never blocked by this hook."""
    result = _run_hook(_write_payload("plugins/saga/scripts/saga.py", "def foo(): pass"))
    assert result.returncode == 0, f"Expected pass-through; stderr={result.stderr!r}"


def test_non_write_tool_passes() -> None:
    """A Bash tool call is never intercepted."""
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "echo hello"},
    }
    result = _run_hook(payload)
    assert result.returncode == 0, f"Expected pass-through; stderr={result.stderr!r}"


# ---------------------------------------------------------------------------
# Edit tool: simulate post-edit validation
# ---------------------------------------------------------------------------


def test_edit_producing_valid_json_passes(tmp_path: Path) -> None:
    """An Edit that results in valid JSON → exit 0."""
    target = tmp_path / "plugin.json"
    target.write_text('{"name": "saga", "version": "0.23.0"}')

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": '"0.23.0"',
            "new_string": '"0.24.0"',
        },
    }
    result = _run_hook(payload)
    assert result.returncode == 0, f"Expected pass; stderr={result.stderr!r}"


def test_edit_producing_invalid_json_is_blocked(tmp_path: Path) -> None:
    """An Edit that results in invalid JSON → exit 2."""
    target = tmp_path / "marketplace.json"
    target.write_text('{"plugins": []}')

    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(target),
            "old_string": "[]",
            "new_string": "[}",  # introduce imbalance
        },
    }
    result = _run_hook(payload)
    assert result.returncode == 2, (
        f"Expected block; got {result.returncode}, stderr={result.stderr!r}"
    )
    assert "marketplace.json" in result.stderr


# ---------------------------------------------------------------------------
# MultiEdit tool: post-edit validation over the on-disk file + edits list
# ---------------------------------------------------------------------------


def test_multiedit_producing_invalid_json_is_blocked(tmp_path: Path) -> None:
    """A MultiEdit whose applied edits yield invalid JSON → exit 2, offending line named.

    The hook reads the on-disk file and applies the ``edits`` list in-memory
    (validate_json_hook.py:81-93), so this drives the real MultiEdit branch with
    the stdin shape the hook parses (``tool_input.edits``).
    """
    target = tmp_path / "marketplace.json"
    target.write_text('{\n  "plugins": [],\n  "version": "3.0.0"\n}\n')

    payload = {
        "tool_name": "MultiEdit",
        "tool_input": {
            "file_path": str(target),
            "edits": [
                # First edit is fine on its own; the second introduces an extra
                # closer so the post-edit content no longer parses.
                {"old_string": '"3.0.0"', "new_string": '"3.1.0"'},
                {"old_string": '"plugins": []', "new_string": '"plugins": []]'},
            ],
        },
    }
    result = _run_hook(payload)
    assert result.returncode == 2, (
        f"Expected exit 2 (block); got {result.returncode}, stderr={result.stderr!r}"
    )
    assert "marketplace.json" in result.stderr, f"stderr must name the file; got: {result.stderr!r}"
    assert "line" in result.stderr, f"stderr must name the offending line; got: {result.stderr!r}"


# ---------------------------------------------------------------------------
# Offending-line helper unit tests
# ---------------------------------------------------------------------------


def _load_hook_module():
    """Import the hook module dynamically (no package install needed)."""
    spec = importlib.util.spec_from_file_location("validate_json_hook", HOOK_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_find_offending_line_extra_closer() -> None:
    """_find_offending_line returns the correct line for an extra ]."""
    mod = _load_hook_module()
    text = '{"plugins": []}\n]\n'
    lineno, line_text = mod._find_offending_line(text)
    assert lineno == 2, f"Expected line 2 (the extra ]); got {lineno}"
    assert "]" in line_text


def test_find_offending_line_unclosed() -> None:
    """_find_offending_line returns the last line for unclosed brackets."""
    mod = _load_hook_module()
    text = '{"name": "saga"'
    lineno, line_text = mod._find_offending_line(text)
    assert lineno == 1


def test_find_offending_line_valid_returns_last() -> None:
    """_find_offending_line on balanced JSON returns last line (depth stays 0)."""
    mod = _load_hook_module()
    text = '{"a": 1}\n'
    # No imbalance at all, returns last line
    lineno, _ = mod._find_offending_line(text)
    assert lineno >= 1
