#!/usr/bin/env python3
"""
SessionStart hook (compact): re-inject the saga spore after compaction.
"""

import contextlib
import json
import subprocess
import sys
from pathlib import Path

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import saga_spore
except Exception:
    sys.exit(0)


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        sys.exit(0)

    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    source = payload.get("source")
    cwd = payload.get("cwd")
    session_id = payload.get("session_id")

    if source != "compact":
        sys.exit(0)

    if not session_id or not cwd:
        sys.exit(0)

    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=1,
        )
        if res.returncode != 0 or not res.stdout:
            sys.exit(0)
        repo_root = Path(res.stdout.strip())
    except Exception:
        sys.exit(0)

    try:
        common_dir = saga_spore.run_record._resolve_common_dir(repo_root)
        path = saga_spore.spore_path(common_dir, session_id)
        if not path.is_file():
            sys.exit(0)
        text = path.read_text(encoding="utf-8")
    except Exception:
        sys.exit(0)

    try:
        block = saga_spore.load_and_validate(text, session_id, str(repo_root))
    except Exception:
        sys.exit(0)

    if block is None:
        sys.exit(0)

    # R8/KTD6: Build full payload string, THEN unlink, THEN print
    output = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": block,
            }
        }
    )

    with contextlib.suppress(Exception):
        path.unlink(missing_ok=True)

    with contextlib.suppress(Exception):
        print(output)

    sys.exit(0)


if __name__ == "__main__":
    main()
