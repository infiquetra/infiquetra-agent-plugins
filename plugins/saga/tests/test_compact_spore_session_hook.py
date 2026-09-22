"""
Tests for the Compact spore session hook.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "compact_spore_session_hook.py"
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
def repo_with_spore(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)

    session_id = "sess-123"
    saga_id = "test-saga"

    sys.path.insert(0, str(SAGA_SCRIPTS))
    try:
        import saga_spore

        spore_data = {
            "provenance": {
                "schema": saga_spore.SCHEMA,
                "session_id": session_id,
                "repo_root": str(repo),
                "saga_id": saga_id,
                "generated_at": "2026-06-30T14:00:00Z",
            },
            "saga_box": {
                "saga_id": saga_id,
                "lifecycle_phase": "plan",
                "phase_status": "in_progress",
                "status": "active",
                "next_step": "test",
            },
            "pointers": {},
        }

        common_dir = saga_spore.run_record._resolve_common_dir(repo)
        out_path = saga_spore.spore_path(common_dir, session_id)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(saga_spore.dump(spore_data), encoding="utf-8")

    finally:
        sys.path.remove(str(SAGA_SCRIPTS))

    return repo, session_id, saga_id


def test_happy_path(repo_with_spore: tuple[Path, str, str]) -> None:
    """Happy path: spore present for <session_id> -> emits valid SessionStart JSON"""
    repo, session_id, saga_id = repo_with_spore

    payload = {
        "source": "compact",
        "session_id": session_id,
        "cwd": str(repo),
    }

    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert res.stdout
    assert not res.stderr

    output = json.loads(res.stdout)
    hso = output.get("hookSpecificOutput", {})
    assert hso.get("hookEventName") == "SessionStart"
    assert "additionalContext" in hso

    ctx = hso["additionalContext"]
    assert "AUTHORITATIVE" in ctx
    assert saga_id in ctx

    # Verify unlink-before-emit
    sys.path.insert(0, str(SAGA_SCRIPTS))
    try:
        import saga_spore

        common_dir = saga_spore.run_record._resolve_common_dir(repo)
        spore_file = saga_spore.spore_path(common_dir, session_id)
        assert not spore_file.exists()
    finally:
        sys.path.remove(str(SAGA_SCRIPTS))


def test_no_double_inject(repo_with_spore: tuple[Path, str, str]) -> None:
    """Unlink-before-emit / no double-inject (R8)"""
    repo, session_id, _ = repo_with_spore

    payload = {
        "source": "compact",
        "session_id": session_id,
        "cwd": str(repo),
    }

    # First run succeeds
    res1 = _run_hook(repo, payload)
    assert res1.returncode == 0
    assert res1.stdout

    # Second run should emit nothing
    res2 = _run_hook(repo, payload)
    assert res2.returncode == 0
    assert not res2.stdout


def test_unlink_before_emit_crash(repo_with_spore: tuple[Path, str, str], tmp_path: Path) -> None:
    """A print crash after unlink still consumes the spore (no stranded re-injectable file).

    NOTE: this proves "unlink survives an emit failure", not the literal unlink-before-emit
    ORDERING (the two suppress blocks are independent, so a reversed order would still pass here).
    Consume-once ordering is proven by test_no_double_inject.
    """
    repo, session_id, _ = repo_with_spore

    shim = tmp_path / "shim.py"
    shim.write_text(
        f'''
import sys
from unittest.mock import patch

sys.path.insert(0, "{HOOK_SCRIPT.parent}")
import compact_spore_session_hook

def crashing_print(*args, **kwargs):
    raise RuntimeError("Crash during print")

@patch("builtins.print", side_effect=crashing_print)
def run(mock_print):
    try:
        compact_spore_session_hook.main()
    except SystemExit as e:
        sys.exit(e.code)

if __name__ == "__main__":
    run()
'''
    )

    payload = {
        "source": "compact",
        "session_id": session_id,
        "cwd": str(repo),
    }

    res = subprocess.run(
        [sys.executable, str(shim)],
        input=json.dumps(payload).encode("utf-8"),
        cwd=str(repo),
        capture_output=True,
    )
    assert res.returncode == 0
    assert not res.stdout

    # Spore should be unlinked despite the crash during emit
    sys.path.insert(0, str(SAGA_SCRIPTS))
    try:
        import saga_spore

        common_dir = saga_spore.run_record._resolve_common_dir(repo)
        spore_file = saga_spore.spore_path(common_dir, session_id)
        assert not spore_file.exists()
    finally:
        sys.path.remove(str(SAGA_SCRIPTS))


def test_mismatch(repo_with_spore: tuple[Path, str, str], tmp_path: Path) -> None:
    """Mismatch (R9): a spore whose saga_id or repo_root does not match -> no injection, exit 0, spore file STILL PRESENT"""
    repo, session_id, _ = repo_with_spore

    # We create a new repo, so the repo_root won't match the one in the spore
    repo2 = tmp_path / "repo2"
    repo2.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo2)

    # But we copy the spore into repo2's common_dir so the hook finds it
    sys.path.insert(0, str(SAGA_SCRIPTS))
    try:
        import saga_spore

        common_dir1 = saga_spore.run_record._resolve_common_dir(repo)
        spore_file1 = saga_spore.spore_path(common_dir1, session_id)

        common_dir2 = saga_spore.run_record._resolve_common_dir(repo2)
        spore_file2 = saga_spore.spore_path(common_dir2, session_id)
        spore_file2.parent.mkdir(parents=True, exist_ok=True)
        spore_file2.write_bytes(spore_file1.read_bytes())
    finally:
        sys.path.remove(str(SAGA_SCRIPTS))

    payload = {
        "source": "compact",
        "session_id": session_id,
        "cwd": str(repo2),
    }

    res = _run_hook(repo2, payload)
    assert res.returncode == 0
    assert not res.stdout

    # Assert spore file still exists
    assert spore_file2.exists()


def test_no_spore(tmp_path: Path) -> None:
    """No spore: missing file -> exit 0, no stdout"""
    repo = tmp_path / "repo-no-spore"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)

    payload = {
        "source": "compact",
        "session_id": "sess-empty",
        "cwd": str(repo),
    }

    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert not res.stdout


def test_wrong_source(repo_with_spore: tuple[Path, str, str]) -> None:
    """Wrong source: source="startup" -> exit 0 silent, no read/unlink"""
    repo, session_id, _ = repo_with_spore

    payload = {
        "source": "startup",
        "session_id": session_id,
        "cwd": str(repo),
    }

    res = _run_hook(repo, payload)
    assert res.returncode == 0
    assert not res.stdout

    # Spore should not be read or unlinked
    sys.path.insert(0, str(SAGA_SCRIPTS))
    try:
        import saga_spore

        common_dir = saga_spore.run_record._resolve_common_dir(repo)
        spore_file = saga_spore.spore_path(common_dir, session_id)
        assert spore_file.exists()
    finally:
        sys.path.remove(str(SAGA_SCRIPTS))


def test_malformed_stdin(repo_with_spore: tuple[Path, str, str]) -> None:
    """Error paths: malformed stdin -> exit 0, no stdout, no raise"""
    repo, session_id, _ = repo_with_spore
    res = _run_hook(repo, b"not json")
    assert res.returncode == 0
    assert not res.stdout
    assert not res.stderr

    sys.path.insert(0, str(SAGA_SCRIPTS))
    try:
        import saga_spore

        common_dir = saga_spore.run_record._resolve_common_dir(repo)
        spore_file = saga_spore.spore_path(common_dir, session_id)
        assert spore_file.exists()
    finally:
        sys.path.remove(str(SAGA_SCRIPTS))


def test_cwd_not_a_repo(tmp_path: Path) -> None:
    """Error paths: cwd not a repo -> exit 0, no stdout, no raise"""
    payload = {
        "source": "compact",
        "session_id": "sess-none",
        "cwd": str(tmp_path),
    }
    res = _run_hook(tmp_path, payload)
    assert res.returncode == 0
    assert not res.stdout
    assert not res.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
