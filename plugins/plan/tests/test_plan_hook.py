"""Advisory hook contract for docs/plans/*.md writes."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

HOOK = (
    Path(__file__).resolve().parents[1]
    / "com.infiquetra.claude"
    / "hooks"
    / "validate_plan_write_hook.py"
)


def _invoke(payload: object | None, raw: str | None = None) -> subprocess.CompletedProcess[str]:
    if raw is None:
        raw = "" if payload is None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _assert_silent(completed: subprocess.CompletedProcess[str]) -> None:
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_ignores_non_plan_writes_fast_and_silent(tmp_path: Path) -> None:
    plan = tmp_path / "docs" / "plans" / "2026-11-19-incomplete-plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Draft\n\nTBD\n", encoding="utf-8")
    payloads: list[object | None] = [
        None,
        {},
        [],
        {"tool_name": "Bash", "tool_input": {"file_path": str(plan)}, "cwd": str(tmp_path)},
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / "src" / "app.py")},
            "cwd": str(tmp_path),
        },
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": str(tmp_path / "README.md")},
            "cwd": str(tmp_path),
        },
        {
            "tool_name": "MultiEdit",
            "tool_input": {"file_path": str(tmp_path / "docs" / "plans" / "notes.txt")},
            "cwd": str(tmp_path),
        },
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / "docs" / "notes" / "foo.md")},
            "cwd": str(tmp_path),
        },
        {
            "tool_name": "Write",
            "tool_input": {"file_path": str(tmp_path / "docs" / "plans" / "nested" / "foo.md")},
            "cwd": str(tmp_path),
        },
        {"tool_name": "Write", "tool_input": {}},
        {"tool_name": "Write"},
    ]
    raw_payloads = ["", "not json", "{", "null", "\"docs/plans/foo.md\""]
    started = time.monotonic()
    for payload in payloads:
        _assert_silent(_invoke(payload))
    for raw in raw_payloads:
        _assert_silent(_invoke(None, raw=raw))
    assert time.monotonic() - started < 2


def test_emits_advisory_suggestions_on_incomplete_docs_plans_write(tmp_path: Path) -> None:
    plan = tmp_path / "docs" / "plans" / "2026-11-19-incomplete-plan.md"
    plan.parent.mkdir(parents=True)
    original = "# Draft\n\nDo this later. TBD. TODO. It edits \"several files\".\n"
    plan.write_text(original, encoding="utf-8")
    for tool_name in ("Write", "Edit", "MultiEdit"):
        completed = _invoke(
            {
                "tool_name": tool_name,
                "cwd": str(tmp_path),
                "tool_input": {"file_path": str(plan)},
            }
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stderr == ""
        body = json.loads(completed.stdout)
        context = body["hookSpecificOutput"]["additionalContext"]
        assert body["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
        assert "advisory" in context
        assert "deny" not in completed.stdout.lower()
        assert "missing section: Summary" in context
        assert "placeholder TBD" in context
        assert "placeholder TODO" in context
        assert 'placeholder "several files"' in context
        assert plan.read_text(encoding="utf-8") == original
