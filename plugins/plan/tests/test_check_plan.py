"""Checker contract for skills/plan/scripts/check_plan.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECK_PLAN = Path(__file__).resolve().parents[1] / "skills" / "plan" / "scripts" / "check_plan.py"

COMPLETE_HEAD = """# Widget

## Summary

Add a local reader.

## Non-Goals

- No network calls.

## Key Decisions

- **Read from disk:** the input is already a local file.

## Units

"""

COMPLETE_TAIL = """
## Verification

Run the unit test named in the unit.
"""


def _run(root: Path, plan: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECK_PLAN), "--root", str(root), str(plan)],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_plan_passes_exit_zero(tmp_path: Path) -> None:
    help_run = subprocess.run(
        [sys.executable, str(CHECK_PLAN), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert help_run.returncode == 0
    assert "usage:" in help_run.stdout.lower()

    _write(tmp_path, "pkg/reader.py", "reader\n")
    plan = _write(
        tmp_path,
        "docs/plans/2026-11-19-widget-plan.md",
        COMPLETE_HEAD
        + "- **Files:** `pkg/reader.py`, `pkg/widget.py` (new)\n"
        + "- **Tests:** empty input returns an empty list.\n"
        + "- **Verify:** `python3 -m unittest pkg/test_reader.py`\n"
        + COMPLETE_TAIL,
    )
    completed = _run(tmp_path, plan)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_flags_nonexistent_existing_file_reference_and_allows_new_marker(tmp_path: Path) -> None:
    _write(tmp_path, "pkg/reader.py", "reader\n")
    plan = _write(
        tmp_path,
        "docs/plans/2026-11-19-paths-plan.md",
        COMPLETE_HEAD
        + "- **Files:** `pkg/reader.py`, `pkg/missing.py`, `pkg/added.py` (new), "
        + "`ghost/file.py` (new)\n"
        + "- **Directory:** `nested/` (new), `nested/leaf.py` (new)\n"
        + "- **Create:** create `pkg/created.py`\n"
        + COMPLETE_TAIL,
    )
    completed = _run(tmp_path, plan)
    output = completed.stdout
    assert completed.returncode == 1, output
    assert "unmarked path does not exist: pkg/missing.py" in output
    assert "new path has no existing or planned parent: ghost/file.py" in output
    assert "pkg/reader.py" not in output
    assert "pkg/added.py" not in output
    assert "pkg/created.py" not in output
    assert "nested/leaf.py" not in output
    assert "nested/" not in output


def test_flags_missing_core_sections_and_vague_placeholders(tmp_path: Path) -> None:
    plan = _write(
        tmp_path,
        "docs/plans/2026-11-19-incomplete-plan.md",
        "# Draft\n\nDo this later. TBD. TODO. It edits \"several files\".\n",
    )
    completed = _run(tmp_path, plan)
    output = completed.stdout
    assert completed.returncode == 1, output
    for section in (
        "Summary",
        "Non-Goals or Scope",
        "Key Decisions",
        "Units or Steps",
        "Verification or Tests",
    ):
        assert f"missing section: {section}" in output
    assert 'placeholder TBD' in output
    assert "placeholder TODO" in output
    assert 'placeholder "several files"' in output
