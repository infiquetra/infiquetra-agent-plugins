"""Standalone prepare and finish, with no lifecycle store and no second reviewer lane."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "plugins" / "reviews"
COMMAND = PACKAGE / "scripts" / "review_command.py"
PIN = "5550acf"
FORBIDDEN = (
    "plugins/saga",
    "plugins/orchestrate",
    "build_loop",
    "run_record",
    "external-reviewer",
    "engine-registry",
    "review-launch",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp: Path) -> tuple[Path, str, str]:
    repo = tmp / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review@example.com")
    _git(repo, "config", "user.name", "review")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("def changed():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "src" / "app.py").write_text("def changed():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "head")
    return repo, base, _git(repo, "rev-parse", "HEAD")


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(COMMAND), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def test_prepare_and_finish_without_saga_run_record(tmp_path: Path) -> None:
    repo, base, head = _repo(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"schema": "repository_profile.v1"}) + "\n", encoding="utf-8")
    builder = tmp_path / "builder.json"
    builder.write_text(
        json.dumps(
            {
                "kind": "builder_record",
                "schema": "review_records.v1",
                "unit": "U1",
                "acceptance_criteria": [
                    {"id": "AC-1", "text": "The changed line is reviewed.", "checks": ["line"]}
                ],
                "declarations": [],
                "reasons": [],
            }
        ),
        encoding="utf-8",
    )
    packet = tmp_path / ".reviews" / "range"
    prepared = _run(
        [
            "prepare",
            "--repo", str(repo),
            "--base", base,
            "--head", head,
            "--profile", str(profile),
            "--builder-record", str(builder),
            "--out", str(packet),
            "--home", str(home),
        ]
    )
    assert prepared.returncode == 0, prepared.stderr
    assert not (repo / ".claude").exists()
    assert not (home / ".claude").exists()
    assert (packet / "grades.json").is_file()
    assert (packet / "change.json").is_file()
    where = json.loads((packet / "where-to-look.json").read_text(encoding="utf-8"))
    assert isinstance(where, list)
    answer = {
        "schema": "targeted_reviewer_answer.v1",
        "items": [
            {
                "index": index,
                "file": (item.get("location") or {}).get("file"),
                "answer": {
                    "kind": "cleared",
                    "reason": "The packet item does not show a defect in this change.",
                },
            }
            for index, item in enumerate(where)
        ],
        "findings": [],
    }
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = {
        "session_id": "review-session",
        "vendor": "claude",
        "model": "opus",
        "effort": "high",
        "prompt_sha256": "a" * 64,
        "configuration": {"fingerprint": "b" * 64},
        "usage": {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0, "seconds": 1},
        "scratch": {"path": str(scratch), "changes": {"added": [], "modified": [], "deleted": []}},
    }
    answer_path = tmp_path / "answer.json"
    result_path = tmp_path / "result.json"
    answer_path.write_text(json.dumps(answer), encoding="utf-8")
    result_path.write_text(json.dumps(result), encoding="utf-8")
    finished = _run(
        [
            "finish",
            "--packet", str(packet),
            "--answer", str(answer_path),
            "--result", str(result_path),
            "--home", str(home),
        ]
    )
    assert finished.returncode == 0, finished.stderr
    run = json.loads((packet / "review-run.json").read_text(encoding="utf-8"))
    assert run["kind"] == "review_run"
    assert run["schema"] == "review_records.v1"
    assert run["base"] == base
    assert run["head"] == head
    scripts = str(PACKAGE / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import review_records

    assert review_records.validate(run) == []


def test_formula_and_schema_match_the_pinned_bytes() -> None:
    for relative in ("scripts/review_formula.py", "references/review-records.schema.json"):
        pinned = subprocess.check_output(
            ["git", "show", f"{PIN}:plugins/saga/{relative}"], cwd=ROOT
        )
        assert (PACKAGE / relative).read_bytes() == pinned


def test_no_orchestrate_or_secondary_external_reviewer_dependency() -> None:
    offenders: list[str] = []
    for folder in ("scripts", "skills"):
        for path in (PACKAGE / folder).rglob("*"):
            if path.suffix not in {".py", ".md"} or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN:
                if token in text:
                    offenders.append(f"{path.relative_to(PACKAGE)} contains {token}")
    assert offenders == []


def test_entrypoint_help_exits_zero() -> None:
    completed = subprocess.run(
        [sys.executable, str(COMMAND), "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "usage:" in completed.stdout.lower()
