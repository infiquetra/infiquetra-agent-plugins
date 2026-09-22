"""
Tests for the PreCompact spore hook.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "precompact_spore_hook.py"
SAGA_SCRIPTS = ROOT / "plugins" / "saga" / "scripts"


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env_args = [
        "git",
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "-c",
        "commit.gpgsign=false",
        *args,
    ]
    return subprocess.run(env_args, cwd=str(cwd), check=True, capture_output=True, text=True)


def _run_hook(cwd: Path, payload: dict | bytes) -> subprocess.CompletedProcess[bytes]:
    payload_bytes = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=payload_bytes,
        cwd=str(cwd),
        capture_output=True,
    )


@pytest.fixture
def repo_with_saga(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)

    sys.path.insert(0, str(SAGA_SCRIPTS))
    try:
        import saga

        s = saga.Saga(
            saga_id="test-saga",
            kind="task",
            id="test",
            lifecycle_phase="plan",
            phase_status="in_progress",
            next_step="test",
        )
        saga.save(repo, s)

        state_path = repo / saga.STATE_DIR / "state.json"
        state_path.write_text(json.dumps({"active_saga_id": "test-saga"}))
    finally:
        sys.path.remove(str(SAGA_SCRIPTS))

    return repo, "test-saga"


def test_happy_path_auto(repo_with_saga: tuple[Path, str]) -> None:
    """T1. Happy path (trigger=auto)"""
    repo, saga_id = repo_with_saga
    session_id = "sess-123"

    payload = {
        "session_id": session_id,
        "cwd": str(repo),
        "trigger": "auto",
    }

    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert not res.stdout
    assert not res.stderr

    common_dir = Path(_git("rev-parse", "--git-common-dir", cwd=repo).stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir

    spore_file = common_dir / "saga-spores" / f"{session_id}.json"
    assert spore_file.is_file()

    data = json.loads(spore_file.read_text())
    assert data["schema"] == "saga.spore.v1"
    assert data["saga_id"] == saga_id


def test_manual_trigger(repo_with_saga: tuple[Path, str]) -> None:
    """T2. Manual trigger"""
    repo, saga_id = repo_with_saga
    session_id = "sess-456"

    payload = {
        "session_id": session_id,
        "cwd": str(repo),
        "trigger": "manual",
    }

    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert not res.stdout

    common_dir = Path(_git("rev-parse", "--git-common-dir", cwd=repo).stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    spore_file = common_dir / "saga-spores" / f"{session_id}.json"
    assert spore_file.is_file()


def test_no_active_saga(tmp_path: Path) -> None:
    """T3. No active saga"""
    repo = tmp_path / "repo-no-saga"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)

    payload = {
        "session_id": "sess-empty",
        "cwd": str(repo),
        "trigger": "auto",
    }

    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert not res.stdout

    common_dir = Path(_git("rev-parse", "--git-common-dir", cwd=repo).stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    spore_dir = common_dir / "saga-spores"
    assert not spore_dir.exists() or not list(spore_dir.glob("*.json"))


def test_deadline_exceeded(repo_with_saga: tuple[Path, str], tmp_path: Path) -> None:
    """T4. Deadline exceeded"""
    repo, _ = repo_with_saga
    session_id = "sess-slow"

    shim = tmp_path / "shim.py"
    shim.write_text(
        f"""
import sys
import time
from unittest.mock import patch

sys.path.insert(0, "{HOOK_SCRIPT.parent}")
import precompact_spore_hook

def slow_build_spore(*args, **kwargs):
    time.sleep(3)
    return {{}}

@patch("precompact_spore_hook.saga_spore.build_spore", side_effect=slow_build_spore)
def run(mock_build):
    try:
        precompact_spore_hook.main()
    except SystemExit as e:
        sys.exit(e.code)

if __name__ == "__main__":
    run()
"""
    )

    payload = {
        "session_id": session_id,
        "cwd": str(repo),
        "trigger": "auto",
    }

    t0 = time.time()
    res = subprocess.run(
        [sys.executable, str(shim)],
        input=json.dumps(payload).encode("utf-8"),
        cwd=str(repo),
        capture_output=True,
    )
    t1 = time.time()

    assert res.returncode == 0
    assert not res.stdout
    assert t1 - t0 < 2.0  # Deadline is 1.5s + margin

    common_dir = Path(_git("rev-parse", "--git-common-dir", cwd=repo).stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    spore_file = common_dir / "saga-spores" / f"{session_id}.json"
    assert not spore_file.exists()


def test_orphan_sweep(repo_with_saga: tuple[Path, str], tmp_path: Path) -> None:
    """T5. Orphan sweep"""
    repo, saga_id = repo_with_saga
    session_id = "sess-sweep"

    common_dir = Path(_git("rev-parse", "--git-common-dir", cwd=repo).stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir

    spore_dir = common_dir / "saga-spores"
    spore_dir.mkdir(parents=True, exist_ok=True)

    old_spore = spore_dir / "old.json"
    old_spore.write_text('{{"schema": "saga.spore.v1"}}')
    eight_days_ago = time.time() - (8 * 86400)
    os.utime(old_spore, (eight_days_ago, eight_days_ago))

    payload = {
        "session_id": session_id,
        "cwd": str(repo),
        "trigger": "auto",
    }

    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert not res.stdout

    assert not old_spore.exists()

    new_spore = spore_dir / f"{session_id}.json"
    assert new_spore.is_file()


def test_malformed_stdin(repo_with_saga: tuple[Path, str]) -> None:
    """T6. Malformed stdin"""
    repo, _ = repo_with_saga
    res = _run_hook(repo, b"not json")
    assert res.returncode == 0
    assert not res.stdout
    assert not res.stderr

    common_dir = Path(_git("rev-parse", "--git-common-dir", cwd=repo).stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    spore_dir = common_dir / "saga-spores"
    assert not spore_dir.exists() or not list(spore_dir.glob("*.json"))


def test_cwd_not_a_repo(tmp_path: Path) -> None:
    """T7. CWD not a repo"""
    payload = {
        "session_id": "sess-none",
        "cwd": str(tmp_path),
        "trigger": "auto",
    }
    res = _run_hook(tmp_path, payload)
    assert res.returncode == 0
    assert not res.stdout
    assert not res.stderr


def test_never_blocks(repo_with_saga: tuple[Path, str]) -> None:
    """T8. Never blocks"""
    # Asserted across all tests via `assert not res.stdout`.
    # Just to be explicit:
    repo, _ = repo_with_saga
    payload = {
        "session_id": "sess-noblock",
        "cwd": str(repo),
        "trigger": "auto",
    }
    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert b"decision" not in res.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
