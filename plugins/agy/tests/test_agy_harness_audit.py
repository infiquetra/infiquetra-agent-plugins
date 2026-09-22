"""Tests for agy live-harness transcript auditing."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "audit_harness_transcript.py"
FIXTURES = ROOT / "tests" / "fixtures" / "agy" / "harness"


def _make_bundle(root: Path, name: str, *, status: str = "success") -> Path:
    bundle = root / ".claude" / "agy" / "runs" / name
    bundle.mkdir(parents=True)
    (bundle / "result.json").write_text(
        json.dumps(
            {
                "schema": "agy.result.v1",
                "status": status,
                "agy_launched": True,
            }
        ),
        encoding="utf-8",
    )
    return bundle


def _rewrite_fixture_paths(tmp_path: Path, fixture_name: str, bundle: Path) -> Path:
    fixture = FIXTURES / fixture_name
    rewritten = tmp_path / fixture_name
    text = fixture.read_text(encoding="utf-8")
    old_bundle = (
        f"/tmp/agy-harness/{'reviewer' if 'reviewer' in fixture_name else 'coder'}"
        f"/.claude/agy/runs/{'live-reviewer' if 'reviewer' in fixture_name else 'live-coder'}"
    )
    rewritten.write_text(text.replace(old_bundle, str(bundle)), encoding="utf-8")
    return rewritten


def _run_audit(*paths: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *(str(path) for path in paths)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_real_reviewer_and_coder_fixtures_pass_when_bundles_exist(tmp_path: Path) -> None:
    reviewer_bundle = _make_bundle(tmp_path / "reviewer", "live-reviewer")
    # This fixture is a harness provenance proof, not a live-write proof.  Applied results need
    # a broker-owned settlement close, which is covered by the wrapper integration tests.
    coder_bundle = _make_bundle(tmp_path / "coder", "live-coder", status="success")
    reviewer = _rewrite_fixture_paths(tmp_path, "real-reviewer.jsonl", reviewer_bundle)
    coder = _rewrite_fixture_paths(tmp_path, "real-coder.jsonl", coder_bundle)

    completed = _run_audit(reviewer, coder)
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert payload["passed"] is True
    assert [audit["classification"]["classification"] for audit in payload["audits"]] == [
        "real",
        "real",
    ]
    assert [audit["result_statuses"] for audit in payload["audits"]] == [["success"], ["success"]]


def test_applied_result_without_accepted_canonical_close_fails(tmp_path: Path) -> None:
    bundle = _make_bundle(tmp_path / "coder", "live-coder", status="applied")
    transcript = _rewrite_fixture_paths(tmp_path, "real-coder.jsonl", bundle)

    completed = _run_audit(transcript)
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["passed"] is False


def test_clone_fallback_fixture_fails_closed() -> None:
    completed = _run_audit(FIXTURES / "claude-clone.jsonl")
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["passed"] is False
    audit = payload["audits"][0]
    assert audit["classification"]["classification"] == "fallback_suspected"
    assert audit["classification"]["claude_file_tool_seen"] is True
    assert audit["agy_result_count"] == 0


def test_real_transcript_with_failed_wrapper_status_fails(tmp_path: Path) -> None:
    reviewer_bundle = _make_bundle(tmp_path / "reviewer", "live-reviewer", status="no_output")
    reviewer = _rewrite_fixture_paths(tmp_path, "real-reviewer.jsonl", reviewer_bundle)

    completed = _run_audit(reviewer)
    payload = json.loads(completed.stdout)

    assert completed.returncode == 1
    assert payload["passed"] is False
    assert payload["audits"][0]["classification"]["classification"] == "real"
    assert payload["audits"][0]["result_statuses"] == ["no_output"]


def test_audit_can_write_output_file(tmp_path: Path) -> None:
    output = tmp_path / "audit.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(FIXTURES / "claude-clone.jsonl"),
            "--output",
            str(output),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert output.exists()
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is False
