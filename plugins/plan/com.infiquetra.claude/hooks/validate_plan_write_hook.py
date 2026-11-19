#!/usr/bin/env python3
"""Advisory Claude Code hook for writes under ``docs/plans/*.md``.

The hook reads one JSON payload from stdin. It exits 0 with empty stdout for
missing or malformed JSON, for tools other than Write, Edit, and MultiEdit, and
for every path that is not a markdown file directly inside ``docs/plans/``.
When that file is incomplete, it prints non-blocking ``additionalContext`` and
still exits 0. It never denies the write.

``Path(__file__).parents[2]`` is the installed package root. The checker lives
in the portable skill so this hook can run it from the copy the install shipped.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
CHECK_PLAN = PACKAGE_ROOT / "skills" / "plan" / "scripts" / "check_plan.py"
PLAN_TOOLS = frozenset({"Write", "Edit", "MultiEdit"})
ADVISORY_PREFIX = "Plan check is advisory; the write was kept."


def main() -> int:
    """Run the plan check when the payload names a plan file. Fail open otherwise."""
    try:
        return _run()
    except Exception:
        return 0


def _run() -> int:
    try:
        raw = sys.stdin.read()
    except OSError:
        return 0
    if not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    tool_name = payload.get("tool_name", payload.get("toolName"))
    if tool_name not in PLAN_TOOLS:
        return 0
    file_path = _file_path(payload)
    if file_path is None:
        return 0
    # Classify the resolved file. A lexical ``docs/plans`` path can be a symlink
    # to something else, and a path outside that spelling can be an alias for it.
    # ``resolve(strict=False)`` follows existing parents and keeps a missing leaf.
    canonical = _canonicalize(file_path, _payload_cwd(payload))
    if not _is_plan_markdown(canonical):
        return 0
    if not canonical.is_file():
        _emit(f"{ADVISORY_PREFIX}\nplan file not found: {canonical}")
        return 0
    if not CHECK_PLAN.is_file():
        _emit(f"{ADVISORY_PREFIX}\nplan checker is missing: {CHECK_PLAN}")
        return 0
    root = _resolve_root(payload, canonical)
    try:
        completed = subprocess.run(
            [sys.executable, str(CHECK_PLAN), "--root", str(root), str(canonical)],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            cwd=str(root),
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if completed.returncode == 0:
        return 0
    detail = (completed.stdout or completed.stderr).strip() or "plan check reported problems"
    _emit(f"{ADVISORY_PREFIX}\n{detail}")
    return 0


def _file_path(payload: dict[str, Any]) -> Path | None:
    tool_input = payload.get("tool_input", payload.get("toolInput"))
    if not isinstance(tool_input, dict):
        tool_input = {}
    raw = tool_input.get("file_path", tool_input.get("filePath", tool_input.get("path")))
    if not isinstance(raw, str) or not raw.strip():
        response = payload.get("tool_response", payload.get("toolResponse"))
        if isinstance(response, dict):
            raw = response.get("filePath", response.get("file_path", response.get("path")))
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw)


def _is_plan_markdown(path: Path) -> bool:
    """True for ``<anything>/docs/plans/<file>.md`` and not for a nested directory."""
    if path.suffix != ".md":
        return False
    parts = path.parts
    return len(parts) >= 3 and parts[-3] == "docs" and parts[-2] == "plans"


def _payload_cwd(payload: dict[str, Any]) -> Path | None:
    cwd_value = payload.get("cwd")
    if isinstance(cwd_value, str) and cwd_value.strip() and Path(cwd_value).is_dir():
        return Path(cwd_value)
    return None


def _canonicalize(path: Path, cwd: Path | None) -> Path:
    """Resolve symlinks, including when the final component does not exist yet."""
    candidate = path if path.is_absolute() else (cwd or Path.cwd()) / path
    return candidate.resolve(strict=False)


def _resolve_root(payload: dict[str, Any], plan: Path) -> Path:
    cwd_value = payload.get("cwd")
    if isinstance(cwd_value, str) and cwd_value.strip() and Path(cwd_value).is_dir():
        start = Path(cwd_value).resolve()
    else:
        start = plan.resolve().parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def _emit(message: str) -> None:
    body = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message,
        }
    }
    sys.stdout.write(json.dumps(body, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
