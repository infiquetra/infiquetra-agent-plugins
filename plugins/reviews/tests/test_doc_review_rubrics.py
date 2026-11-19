"""lifecycle_review.py lists and reads idea, spec, and issue rubrics on its own."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "plugins" / "reviews" / "scripts" / "lifecycle_review.py"
PHASES = ("idea", "spec", "issue")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_lifecycle_review_lists_and_reads_all_phases_standalone(tmp_path: Path) -> None:
    for phase in PHASES:
        listed = _run("rubrics", "list-cores", "--phase", phase, "--json")
        assert listed.returncode == 0, listed.stderr
        slugs = json.loads(listed.stdout)
        assert slugs, phase
        read = _run("rubrics", "read", "--phase", phase, "--slug", slugs[0])
        assert read.returncode == 0, read.stderr
        assert read.stdout.startswith("---\n")
        assert len(read.stdout.strip()) > 20
        extras = _run("rubrics", "list-extras", "--phase", phase, "--json")
        assert extras.returncode == 0, extras.stderr
        assert isinstance(json.loads(extras.stdout), list)
    assert not (tmp_path / ".claude").exists()
    skill = (ROOT / "plugins" / "reviews" / "skills" / "doc-review" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "does not continue into implementation" in skill
