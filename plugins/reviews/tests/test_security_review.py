"""security_scan.py runs against a committed tree and leaves that tree alone."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCAN = ROOT / "plugins" / "reviews" / "scripts" / "security_scan.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def test_scan_uses_a_disposable_snapshot_and_preserves_exit_codes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "scan@example.com"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "scan"], cwd=repo, check=True, capture_output=True
    )
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    before = _git(repo, "rev-parse", "HEAD")
    before_status = _git(repo, "status", "--porcelain")
    output = tmp_path / "scan-out"
    completed = subprocess.run(
        [sys.executable, str(SCAN), "--repo", str(repo), "--output", str(output)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert completed.returncode in {0, 1, 2}, completed.stderr
    assert _git(repo, "rev-parse", "HEAD") == before
    assert _git(repo, "status", "--porcelain") == before_status
    assert (repo / "app.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["exit_code"] == completed.returncode
    assert "rows" in summary
    text = (output / "summary.md").read_text(encoding="utf-8")
    assert "Deterministic" in text or "exit" in text.lower() or text.strip()


def test_security_review_skill_separates_scanner_results_from_reasoned_findings() -> None:
    skill = (ROOT / "plugins" / "reviews" / "skills" / "security-review" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Deterministic Scanner Results" in skill
    assert "Reasoned Security Findings" in skill
    assert "exit `2`" in skill
