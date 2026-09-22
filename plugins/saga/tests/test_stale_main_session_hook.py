"""
Tests for the generalized self-contained stale-main SessionStart hook.

The hook (`plugins/saga/com.infiquetra.claude/hooks/stale_main_session_hook.py`) runs in ANY git repo
with an ``origin`` remote: it detects the default branch generically, and if the
local default branch is behind ``origin/<default>`` it auto-fast-forwards (only
when you are cleanly ON the default branch) or warns, surfacing the result as
SessionStart ``additionalContext``. It no longer depends on
``tools/stale_main_guard.py``.

These tests build REAL throwaway git repos under ``tmp_path`` (a bare "origin",
a clone of it, and commits advanced on origin so the clone falls behind) so the
actual git logic is exercised end-to-end — no mocking of git. The hook is driven
as a real subprocess with a SessionStart payload on stdin. Nothing lands under
the repo-root ``.claude/``.

Cases:
  (a) not a git repo -> silent exit 0.
  (b) git repo with NO origin remote -> silent exit 0.
  (c) up to date -> silent exit 0.
  (d) behind + on default branch + clean -> AUTO-FF moved the branch + a
      confirmation in additionalContext.
  (e) behind + on a feature branch -> WARN only, branch NOT moved, warning in
      additionalContext.
  (f) default branch named ``master`` (not main) -> detected and handled.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "stale_main_session_hook.py"


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd`` (deterministic identity, no global config leak)."""
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
    return subprocess.run(
        env_args,
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, filename: str, content: str) -> None:
    (repo / filename).write_text(content, encoding="utf-8")
    _git("add", filename, cwd=repo)
    _git("commit", "-q", "-m", f"add {filename}", cwd=repo)


def _make_origin_and_clone(tmp_path: Path, default_branch: str = "main") -> tuple[Path, Path]:
    """
    Build a bare ``origin`` repo (with one commit on ``default_branch`` set as
    HEAD) and a clone of it. Returns ``(origin_bare, clone)``.
    """
    seed = tmp_path / "seed"
    seed.mkdir()
    _git("init", "-q", "-b", default_branch, cwd=seed)
    _commit(seed, "README.md", "seed\n")

    origin = tmp_path / "origin.git"
    _git("clone", "-q", "--bare", str(seed), str(origin), cwd=tmp_path)
    # Ensure origin/HEAD points at the default branch (so symbolic-ref resolves).
    _git("symbolic-ref", "HEAD", f"refs/heads/{default_branch}", cwd=origin)

    clone = tmp_path / "clone"
    _git("clone", "-q", str(origin), str(clone), cwd=tmp_path)
    return origin, clone


def _advance_origin(origin: Path, clone: Path, default_branch: str = "main") -> None:
    """
    Push a new commit to ``origin/<default_branch>`` from a SEPARATE working tree
    so ``clone`` falls one commit behind without itself being updated.
    """
    pusher = clone.parent / "pusher"
    _git("clone", "-q", str(origin), str(pusher), cwd=clone.parent)
    _commit(pusher, "NEW.md", "advance\n")
    _git("push", "-q", "origin", default_branch, cwd=pusher)


def _run_hook(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the hook from ``cwd`` with a SessionStart payload on stdin."""
    payload = {
        "session_id": "test-session",
        "transcript_path": "/tmp/transcript.jsonl",
        "cwd": str(cwd),
        "hook_event_name": "SessionStart",
        "source": "startup",
    }
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(payload),
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )


def _head_sha(repo: Path, ref: str = "HEAD") -> str:
    return _git("rev-parse", ref, cwd=repo).stdout.strip()


def test_not_a_git_repo_is_silent(tmp_path: Path) -> None:
    """(a) not a git repo -> exit 0, no output."""
    plain = tmp_path / "plain-dir"
    plain.mkdir()

    result = _run_hook(plain)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_git_repo_without_origin_is_silent(tmp_path: Path) -> None:
    """(b) git repo with NO origin remote -> exit 0, no output."""
    repo = tmp_path / "no-origin"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _commit(repo, "README.md", "x\n")

    result = _run_hook(repo)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_up_to_date_is_silent(tmp_path: Path) -> None:
    """(c) clone level with origin -> exit 0, no output."""
    _origin, clone = _make_origin_and_clone(tmp_path)

    result = _run_hook(clone)

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_behind_on_default_branch_clean_auto_ffs(tmp_path: Path) -> None:
    """(d) behind + on default branch + clean -> AUTO-FF moves branch + confirms."""
    origin, clone = _make_origin_and_clone(tmp_path)
    before = _head_sha(clone)
    _advance_origin(origin, clone)

    result = _run_hook(clone)

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    hso = parsed["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    assert "Auto-fast-forwarded" in ctx
    assert "main" in ctx
    # The local default branch actually moved to match origin.
    after = _head_sha(clone)
    assert after != before
    assert after == _head_sha(clone, "origin/main")


def test_behind_on_feature_branch_warns_only(tmp_path: Path) -> None:
    """(e) behind + on a feature branch -> WARN only, default branch NOT moved."""
    origin, clone = _make_origin_and_clone(tmp_path)
    # Switch to a feature branch so we are NOT on the default branch.
    _git("checkout", "-q", "-b", "feature/x", cwd=clone)
    main_before = _head_sha(clone, "main")
    _advance_origin(origin, clone)

    result = _run_hook(clone)

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    hso = parsed["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    ctx = hso["additionalContext"]
    assert "WARNING" in ctx
    assert "behind origin/main" in ctx
    # The local default branch must NOT have been mutated.
    assert _head_sha(clone, "main") == main_before


def test_default_branch_master_is_detected(tmp_path: Path) -> None:
    """(f) default branch named 'master' -> detected + auto-FF'd when clean."""
    origin, clone = _make_origin_and_clone(tmp_path, default_branch="master")
    before = _head_sha(clone)
    _advance_origin(origin, clone, default_branch="master")

    result = _run_hook(clone)

    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    ctx = parsed["hookSpecificOutput"]["additionalContext"]
    assert "Auto-fast-forwarded" in ctx
    assert "master" in ctx
    after = _head_sha(clone)
    assert after != before
    assert after == _head_sha(clone, "origin/master")


def test_hook_script_exists() -> None:
    """Sanity: the hook script is present at the wired path."""
    assert HOOK_SCRIPT.is_file()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
