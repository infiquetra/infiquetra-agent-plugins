"""security_scan.py runs against a committed tree and leaves that tree alone."""

from __future__ import annotations

import importlib.util
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


def _load(name: str):
    key = f"infiquetra_reviews.{name}"
    path = ROOT / "plugins" / "reviews" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(key, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    spec.loader.exec_module(module)
    return module


def test_rule_home_stages_the_reviews_cache_ahead_of_the_legacy_cache(tmp_path: Path) -> None:
    security_scan = _load("security_scan")
    review_tools = _load("review_tools")
    machine = tmp_path / "machine-home"
    pack = "p/example"
    reviews_digest = "ab" * 32
    legacy_digest = "cd" * 32
    reviews_cache = machine / ".config" / "infiquetra" / "reviews" / "semgrep-rules" / "p--example"
    reviews_cache.mkdir(parents=True)
    (reviews_cache / "rule.yaml").write_text("rules: []\n", encoding="utf-8")
    reviews_record = machine / ".config" / "infiquetra" / "reviews" / "machine.json"
    reviews_record.write_text(
        json.dumps({"rule_caches": {pack: reviews_digest}}), encoding="utf-8"
    )
    legacy_cache = machine / ".saga" / "semgrep-rules" / "p--example"
    legacy_cache.mkdir(parents=True)
    (legacy_cache / "old.yaml").write_text("rules: []\n", encoding="utf-8")
    (machine / ".saga" / "machine.json").write_text(
        json.dumps({"rule_caches": {pack: legacy_digest}}), encoding="utf-8"
    )
    staged = tmp_path / "staged"
    staged.mkdir()
    security_scan._rule_home(staged, machine)
    assert review_tools.machine_rule_digest(staged, pack) == reviews_digest
    resolved = review_tools.semgrep_cache(staged, pack)
    assert (resolved / "rule.yaml").is_file()
    assert not (resolved / "old.yaml").exists()
    assert "reviews" in resolved.parts


def test_security_review_skill_separates_scanner_results_from_reasoned_findings() -> None:
    skill = (ROOT / "plugins" / "reviews" / "skills" / "security-review" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Deterministic Scanner Results" in skill
    assert "Reasoned Security Findings" in skill
    assert "exit `2`" in skill
