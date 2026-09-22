"""Tests for U3 agy supervised process leases and provenance classification."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
REPO = Path(__file__).resolve().parents[3]
WRAPPER = ROOT / "skills" / "agy-delegate" / "scripts" / "agy_delegate.py"
FAKE_AGY = ROOT / "tests" / "fixtures" / "agy" / "fake_agy.py"
TRANSCRIPTS = ROOT / "tests" / "fixtures" / "agy" / "transcripts"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("agy_delegate", WRAPPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["agy_delegate"] = module
    spec.loader.exec_module(module)
    return module


def _payload(task: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "agy.delegation.v1",
        "role": "coder",
        "mode": "patch-only",
        "task": task,
        "model": "flash",
        "review_lens": None,
        "write_set": ["plugins/agy/scripts/agy_delegate.py"],
        "apply_policy": "preserve-patch",
        "evidence": "summary",
        "verification": {
            "commands": [],
            "required": False,
            "run_scope": "clone",
        },
        "timeout_seconds": 3,
        "no_output_seconds": 2,
        "provenance_required": True,
    }
    payload.update(overrides)
    return payload


def _init_repo(repo: Path) -> None:
    if (repo / ".git").exists():
        return
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_wrapper(
    tmp_path: Path, payload: dict[str, object], run_id: str
) -> subprocess.CompletedProcess[str]:
    _init_repo(tmp_path)
    envelope_path = tmp_path / f"{run_id}.json"
    envelope_path.write_text(json.dumps(payload), encoding="utf-8")

    return subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            run_id,
            "--envelope",
            str(envelope_path),
            "--launch-agy",
            "--agy-bin",
            str(FAKE_AGY),
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def _bundle(tmp_path: Path, run_id: str) -> Path:
    return tmp_path / ".claude" / "agy" / "runs" / run_id


def _json(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def test_fake_agy_success_writes_run_lease_and_logs(tmp_path: Path) -> None:
    completed = _run_wrapper(tmp_path, _payload("FAKE_AGY_MODE=success"), "success-run")
    bundle = _bundle(tmp_path, "success-run")
    result = _json(bundle / "result.json")
    lease = _json(bundle / "run-lease.json")
    command = _json(bundle / "command.json")

    assert completed.returncode == 0
    assert result["status"] == "success"
    assert result["agy_launched"] is True
    assert result["resolved_agy"] == str(FAKE_AGY)
    assert result["stdout_path"] == str(bundle / "stdout.log")
    assert result["stderr_path"] == str(bundle / "stderr.log")
    assert lease["process_id"] is not None
    assert lease["return_code"] == 0
    assert lease["shutdown"] == "exited"
    assert lease["real_agy_verdict"] == "real"
    assert command["resolved_agy"] == str(FAKE_AGY)
    assert "--add-dir" in command["agy_argv"]
    assert "--dangerously-skip-permissions" in command["agy_argv"]
    assert "<prompt:prompt.txt>" in command["agy_argv"]
    assert "fake agy success" in (bundle / "stdout.log").read_text(encoding="utf-8")
    assert "fake agy stderr note" in (bundle / "stderr.log").read_text(encoding="utf-8")


def test_total_timeout_is_first_class_status(tmp_path: Path) -> None:
    completed = _run_wrapper(
        tmp_path,
        _payload(
            "FAKE_AGY_MODE=timeout",
            timeout_seconds=1,
            no_output_seconds=1,
        ),
        "timeout-run",
    )
    bundle = _bundle(tmp_path, "timeout-run")
    result = _json(bundle / "result.json")
    lease = _json(bundle / "run-lease.json")

    assert completed.returncode == 1
    assert result["status"] == "timeout"
    assert lease["timeout_class"] == "timeout"
    assert lease["shutdown"] in {"terminated", "killed"}
    assert "fake agy still working" in (bundle / "stdout.log").read_text(encoding="utf-8")


def test_no_output_timeout_is_first_class_status(tmp_path: Path) -> None:
    completed = _run_wrapper(
        tmp_path,
        _payload(
            "FAKE_AGY_MODE=no_output",
            timeout_seconds=5,
            no_output_seconds=1,
        ),
        "no-output-run",
    )
    bundle = _bundle(tmp_path, "no-output-run")
    result = _json(bundle / "result.json")
    lease = _json(bundle / "run-lease.json")

    assert completed.returncode == 1
    assert result["status"] == "no_output"
    assert lease["timeout_class"] == "no_output"
    assert lease["stdout_bytes"] == 0


def test_nonzero_exit_is_error_not_success(tmp_path: Path) -> None:
    completed = _run_wrapper(tmp_path, _payload("FAKE_AGY_MODE=nonzero"), "nonzero-run")
    bundle = _bundle(tmp_path, "nonzero-run")
    result = _json(bundle / "result.json")
    lease = _json(bundle / "run-lease.json")

    assert completed.returncode == 1
    assert result["status"] == "error"
    assert lease["return_code"] == 7
    assert "nonzero stderr" in (bundle / "stderr.log").read_text(encoding="utf-8")


def test_command_json_sanitizes_wrapper_and_agy_argv(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(WRAPPER),
            "--repo-root",
            str(tmp_path),
            "--run-id",
            "sanitize-run",
            "--role",
            "coder",
            "--task",
            "FAKE_AGY_MODE=success token=super-secret",
            "--launch-agy",
            "--agy-bin",
            str(FAKE_AGY),
            "--audit-store",
            str(tmp_path / "audit-store"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    command_text = (_bundle(tmp_path, "sanitize-run") / "command.json").read_text(encoding="utf-8")
    command = json.loads(command_text)

    assert completed.returncode == 0
    assert "super-secret" not in command_text
    assert "<redacted>" in command["wrapper_argv"]
    assert "<prompt:prompt.txt>" in command["agy_argv"]


def test_classify_transcript_real_and_fallback_suspected() -> None:
    agy_delegate = _load_module()

    real = agy_delegate.classify_transcript(TRANSCRIPTS / "real-agy.jsonl")
    fallback = agy_delegate.classify_transcript(TRANSCRIPTS / "claude-clone.jsonl")

    assert real.classification == "real"
    assert real.agy_command_seen is True
    assert real.claude_file_tool_seen is False
    assert fallback.classification == "fallback_suspected"
    assert fallback.agy_command_seen is False
    assert fallback.claude_file_tool_seen is True


def test_fake_agy_fixture_is_executable() -> None:
    assert os.access(FAKE_AGY, os.X_OK)


def test_reviewer_no_write_uses_agy_sandbox(tmp_path: Path) -> None:
    completed = _run_wrapper(
        tmp_path,
        _payload(
            "FAKE_AGY_MODE=success",
            role="reviewer",
            mode="no-write",
            write_set=[],
            apply_policy="preserve-patch",
        ),
        "reviewer-sandbox-run",
    )
    command = _json(_bundle(tmp_path, "reviewer-sandbox-run") / "command.json")

    assert completed.returncode == 0
    assert "--sandbox" in command["agy_argv"]
    assert "--dangerously-skip-permissions" not in command["agy_argv"]
