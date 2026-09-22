#!/usr/bin/env python3
"""
PreToolUse hook: validate marketplace.json / plugin.json on edit.

JSON-parses the file being written and asserts balanced brackets.  Exits
with code 2 (blocking) when the file is invalid, printing the offending
line to stderr.  All other files pass through silently (exit 0).
"""

from __future__ import annotations

import json
import sys

_TARGET_SUFFIXES = ("marketplace.json", "plugin.json")


def _find_offending_line(text: str) -> tuple[int, str]:
    """
    Return the (1-indexed) line number and text of the first bracket
    imbalance, or the last line if a generic JSONDecodeError gives no
    position.
    """
    depth = 0
    for lineno, line in enumerate(text.splitlines(), start=1):
        for ch in line:
            if ch in "{[":
                depth += 1
            elif ch in "}]":
                depth -= 1
                if depth < 0:
                    return lineno, line.rstrip()
    # depth > 0 means unclosed — report the last line
    lines = text.splitlines()
    if lines:
        return len(lines), lines[-1].rstrip()
    return 1, ""


def main() -> None:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Cannot parse the hook envelope itself — pass through, don't block.
        sys.exit(0)

    tool_name: str = payload.get("tool_name", "")
    tool_input: dict = payload.get("tool_input", {})

    # Only intercept file-write tools.
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    file_path: str = tool_input.get("file_path", "")

    if not any(file_path.endswith(suffix) for suffix in _TARGET_SUFFIXES):
        sys.exit(0)

    # Determine the post-edit content to validate.
    if tool_name == "Write":
        content = tool_input.get("content", "")
    elif tool_name == "Edit":
        # For Edit we only have the snippet being replaced, not the full file.
        # Read the full current file, apply the replacement in-memory, then
        # validate.  If we cannot read the file (new file or race) fall
        # through — don't block a legitimate first write.
        try:
            with open(file_path, encoding="utf-8") as fh:
                existing = fh.read()
        except OSError:
            sys.exit(0)

        old_string: str = tool_input.get("old_string", "")
        new_string: str = tool_input.get("new_string", "")
        replace_all: bool = tool_input.get("replace_all", False)
        if replace_all:
            content = existing.replace(old_string, new_string)
        else:
            content = existing.replace(old_string, new_string, 1)
    elif tool_name == "MultiEdit":
        try:
            with open(file_path, encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            sys.exit(0)

        for edit in tool_input.get("edits", []):
            old = edit.get("old_string", "")
            new = edit.get("new_string", "")
            replace_all = edit.get("replace_all", False)
            content = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    else:
        sys.exit(0)

    # Validate JSON.
    try:
        json.loads(content)
    except json.JSONDecodeError:
        lineno, line_text = _find_offending_line(content)
        print(
            f"[saga/validate-json] {file_path}: invalid JSON after edit — "
            f"first bracket imbalance or parse error near line {lineno}:\n  {line_text}",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
