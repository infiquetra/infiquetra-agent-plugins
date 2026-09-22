"""The session-start hook that announces the run's next step, and stays quiet (issue #1029).

The card's third acceptance criterion is a live observation — "starting a new session in a
repository with an active run prints the run's `next_step`, and none for a closed run". These
tests are the same observation, made by invoking the hook script exactly as the harness does: a
JSON payload on standard input, the process's own exit code and standard output read back.

Every case runs against a temporary repository and a temporary record store. Nothing here touches
the primary checkout's live `.claude/saga/runs` directory.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOK_SCRIPT = ROOT / "plugins" / "saga" / "com.infiquetra.claude" / "hooks" / "next_step_session_hook.py"
SAGA_SCRIPTS = ROOT / "plugins" / "saga" / "scripts"

sys.path.insert(0, str(SAGA_SCRIPTS))

import run_record  # noqa: E402


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _run_hook(cwd: Path, payload: dict | bytes) -> subprocess.CompletedProcess[bytes]:
    raw = json.dumps(payload).encode("utf-8") if isinstance(payload, dict) else payload
    return subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=raw,
        cwd=str(cwd),
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository on `issue/1029` whose git common directory holds the record store."""
    path = tmp_path / "repo"
    path.mkdir()
    _git("init", "-q", "-b", "issue/1029", cwd=path)
    return path


def _store(repo: Path) -> Path:
    """The store the hook itself will resolve — `<repo>/.claude/saga/runs`."""
    path = repo / ".claude" / "saga" / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _context(result: subprocess.CompletedProcess[bytes]) -> str:
    payload = json.loads(result.stdout.decode("utf-8"))
    return str(payload["hookSpecificOutput"]["additionalContext"])


# --------------------------------------------------------------------------------------------
# The announcement.
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["startup", "resume"])
def test_an_active_run_is_announced(repo: Path, source: str) -> None:
    run_record.set_next_step(_store(repo), 1029, "run /work on the plan")
    result = _run_hook(repo, {"source": source, "cwd": str(repo), "session_id": "s1"})
    assert result.returncode == 0
    context = _context(result)
    assert "run /work on the plan" in context
    assert "1029" in context


# --------------------------------------------------------------------------------------------
# The three silences the card names, plus the ones every hook here owes.
# --------------------------------------------------------------------------------------------


def test_a_done_step_announces_nothing(repo: Path) -> None:
    """The card's motivating case: the record says the step is done, so the hook says nothing."""
    store = _store(repo)
    run_record.set_next_step(store, 1029, "run /work on the plan")
    run_record.set_next_step(store, 1029, "")
    result = _run_hook(repo, {"source": "startup", "cwd": str(repo), "session_id": "s1"})
    assert result.returncode == 0
    assert result.stdout == b""


def test_no_record_announces_nothing(repo: Path) -> None:
    _store(repo)
    result = _run_hook(repo, {"source": "startup", "cwd": str(repo), "session_id": "s1"})
    assert result.returncode == 0
    assert result.stdout == b""


def test_a_cwd_outside_a_repository_announces_nothing(tmp_path: Path) -> None:
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    result = _run_hook(plain, {"source": "startup", "cwd": str(plain), "session_id": "s1"})
    assert result.returncode == 0
    assert result.stdout == b""


def test_the_compact_source_is_left_to_the_spore_hook(repo: Path) -> None:
    """`compact` belongs to `compact_spore_session_hook.py`, which carries the record already."""
    run_record.set_next_step(_store(repo), 1029, "run /work on the plan")
    result = _run_hook(repo, {"source": "compact", "cwd": str(repo), "session_id": "s1"})
    assert result.returncode == 0
    assert result.stdout == b""


@pytest.mark.parametrize(
    "payload",
    [b"", b"not json at all", b"[]", b'{"source": "startup"}'],
    ids=["empty", "malformed", "not-an-object", "no-cwd"],
)
def test_a_payload_the_hook_cannot_use_announces_nothing(repo: Path, payload: bytes) -> None:
    run_record.set_next_step(_store(repo), 1029, "run /work on the plan")
    result = _run_hook(repo, payload)
    assert result.returncode == 0
    assert result.stdout == b""


def test_the_hook_exits_zero_even_when_the_record_is_corrupt(repo: Path) -> None:
    """A hook that raised here would cost the operator a turn over a file it only reads."""
    store = _store(repo)
    run_record.record_path(store, 1029).write_text("{ not json", encoding="utf-8")
    result = _run_hook(repo, {"source": "startup", "cwd": str(repo), "session_id": "s1"})
    assert result.returncode == 0
    assert result.stdout == b""
