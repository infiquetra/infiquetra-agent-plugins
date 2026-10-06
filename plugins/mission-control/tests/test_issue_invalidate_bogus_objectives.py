"""Tests for the #111 one-off verdict-log cleanup.

Nothing here touches the real log: the command takes a log directory, and every
test points it at a ``tmp_path`` seeded with raw JSON lines.
"""

# ruff: noqa: E402,I001

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

OBJECTIVE_DECISION = "mission-control/issue-prepare:objective"


def _verdict(verdict_hash: str, label: Any, decision: str = OBJECTIVE_DECISION) -> dict[str, Any]:
    return {
        "kind": "verdict",
        "decision_id": decision,
        "state_hash": "s",
        "questions_hash": "q",
        "answer": {"type": "choice", "choice": "x", "confidence": 0.9},
        "confidence": 0.9,
        "threshold": 0.6,
        "resolved_model": "jev-1.13.0",
        "label": label,
        "at": "2026-10-03T00:00:00Z",
        "verdict_hash": verdict_hash,
    }


def _override(verdict_hash: str, chosen: Any) -> dict[str, Any]:
    return {
        "kind": "override",
        "verdict_hash": verdict_hash,
        "chosen": chosen,
        "rationale": f"the author's prepare flag for objective named {chosen!r}",
        "at": "2026-10-03T00:00:01Z",
    }


def _seed(log_dir: Path, records: list) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "verdicts.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def _read(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_a_dry_run_reports_without_appending(tmp_path, capsys) -> None:
    path = _seed(
        tmp_path / "log",
        [_verdict("aaa", "docs/brainstorms/a-source.md"), _override("aaa", "docs/x.md")],
    )

    result = sdlc_manager.issue_invalidate_bogus_objectives(
        "text", log_dir=tmp_path / "log", dry_run=True
    )

    assert result["bogus_verdicts"] == 1
    assert result["linked_overrides"] == 1
    assert result["invalidated"] == ["aaa"]
    assert result["dry_run"] is True
    assert len(_read(path)) == 2
    assert "dry run" in capsys.readouterr().out


def test_a_run_appends_one_invalidation_per_bogus_verdict(tmp_path) -> None:
    path = _seed(
        tmp_path / "log",
        [
            _verdict("aaa", "docs/brainstorms/a-source.md"),
            _override("aaa", "docs/brainstorms/a-source.md"),
            _verdict("bbb", "improve-agent-plugins"),
            _verdict("ccc", "same", decision="staffing/tier-direction:r"),
        ],
    )

    result = sdlc_manager.issue_invalidate_bogus_objectives("text", log_dir=tmp_path / "log")

    assert result["bogus_verdicts"] == 1
    assert result["linked_overrides"] == 1
    assert result["invalidated"] == ["aaa"]
    records = _read(path)
    assert len(records) == 5
    # Append-only: the original four lines are byte-identical.
    assert [r["verdict_hash"] for r in records[:3] if r["kind"] == "verdict"] == ["aaa", "bbb"]
    marker = records[-1]
    assert marker["kind"] == "invalidation"
    assert marker["verdict_hash"] == "aaa"
    assert "no operator choice existed" in marker["reason"]


def test_a_rerun_appends_nothing(tmp_path) -> None:
    _seed(tmp_path / "log", [_verdict("aaa", "docs/brainstorms/a-source.md")])

    first = sdlc_manager.issue_invalidate_bogus_objectives("text", log_dir=tmp_path / "log")
    second = sdlc_manager.issue_invalidate_bogus_objectives("text", log_dir=tmp_path / "log")

    assert first["invalidated"] == ["aaa"]
    assert second["invalidated"] == []
    assert second["already_invalidated"] == 1
    assert len(_read(tmp_path / "log" / "verdicts.jsonl")) == 2


def test_a_bare_filename_label_is_caught_and_a_real_option_is_not(tmp_path) -> None:
    path = _seed(
        tmp_path / "log",
        [_verdict("aaa", "a-source.md"), _verdict("bbb", "The Norns: Next Horizon")],
    )

    result = sdlc_manager.issue_invalidate_bogus_objectives("text", log_dir=tmp_path / "log")

    assert result["bogus_verdicts"] == 1
    assert result["invalidated"] == ["aaa"]
    assert len(_read(path)) == 3


def test_a_missing_log_reports_zeros(tmp_path) -> None:
    result = sdlc_manager.issue_invalidate_bogus_objectives("text", log_dir=tmp_path / "log")

    assert result["bogus_verdicts"] == 0
    assert result["invalidated"] == []


def test_a_path_label_on_another_decision_is_left_alone(tmp_path) -> None:
    """Only the prepare-objective judgment misused the ref; nothing else is judged."""
    path = _seed(tmp_path / "log", [_verdict("aaa", "docs/x.md", decision="other:decision")])

    result = sdlc_manager.issue_invalidate_bogus_objectives("text", log_dir=tmp_path / "log")

    assert result["bogus_verdicts"] == 0
    assert len(_read(path)) == 1


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "sdlc_manager.py"


def test_the_subcommand_is_registered_with_its_flags() -> None:
    """No network: --help only, like the prepare flag-registration tests."""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and in-repo script path
        [sys.executable, str(SCRIPT), "issue", "invalidate-bogus-objectives", "--help"],
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0
    assert "--log-dir" in result.stdout
    assert "--dry-run" in result.stdout
