"""Per-turn state and mutation record (R23, R122; KTD11).

This module manages the single current-turn JSON state file under the state
directory (``turn_record.json``).

Four processes mutate this record:
1. UserPromptSubmit hook creates it at turn origin;
2. MCP server appends submitted renderings and dispositions;
3. PreToolUse hook appends tool-use observations;
4. Stop hook settles the final outcome ('authored' vs 'fallback').

To prevent lost updates, all mutations are serialized through the single
`mutate(fn)` entrypoint (KTD11):
- An exclusive advisory lock via fcntl.flock on a sidecar lock file
  (``turn_record.json.lock``);
- Acquisition deadline of 500 ms (monotonic clock) retried at 10 ms intervals;
- An expired deadline raises TurnRecordBusy ('turn_record_busy'), never a
  blind write;
- The entire read-modify-replace sequence is executed inside the lock;
- Atomic replace (write temp and os.replace) provides the torn-write defense
  for concurrent readers.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

import settings

__all__ = [
    "TurnRecord",
    "TurnRecordReport",
    "TurnRecordBusy",
    "TurnRecordSessionMismatch",
    "TURN_RECORD_FILENAME",
    "TURN_RECORD_LOCK_FILENAME",
    "STATUS_RECORD",
    "STATUS_ABSENT",
    "STATUS_CORRUPT",
    "OUTCOME_AUTHORED",
    "OUTCOME_FALLBACK",
    "ORIGIN_AURALIS",
    "ORIGIN_NOT_ORIGINATED",
    "read_turn_record",
    "read_turn_record_report",
    "mutate",
    "init_turn",
    "record_submission",
    "record_tool_observation",
    "settle_outcome",
]

TURN_RECORD_FILENAME = "turn_record.json"
TURN_RECORD_LOCK_FILENAME = "turn_record.json.lock"

STATUS_RECORD = "record"
STATUS_ABSENT = "absent"
STATUS_CORRUPT = "corrupt"

OUTCOME_AUTHORED = "authored"
OUTCOME_FALLBACK = "fallback"

ORIGIN_AURALIS = "auralis"
ORIGIN_NOT_ORIGINATED = "not_originated"


class TurnRecordBusy(Exception):
    """Raised when lock acquisition exceeds the 500 ms deadline."""


class TurnRecordSessionMismatch(Exception):
    """Raised when a mutation is attempted on a record with a different session_id."""


@dataclass(frozen=True)
class TurnRecord:
    """The state of the current voice turn."""

    session_id: str
    binding_id: str | None = None
    turn_id: str | None = None
    origin: str = ORIGIN_AURALIS
    submissions: list[dict[str, object]] = field(default_factory=list)
    tool_observations: list[dict[str, object]] = field(default_factory=list)
    outcome: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_payload(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "binding_id": self.binding_id,
            "turn_id": self.turn_id,
            "origin": self.origin,
            "submissions": self.submissions,
            "tool_observations": self.tool_observations,
            "outcome": self.outcome,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> TurnRecord:
        session_id = payload["session_id"]
        if not isinstance(session_id, str):
            raise ValueError("session_id must be a string")
        binding_id = payload.get("binding_id")
        if binding_id is not None and not isinstance(binding_id, str):
            raise ValueError("binding_id must be a string or None")
        turn_id = payload.get("turn_id")
        if turn_id is not None and not isinstance(turn_id, str):
            raise ValueError("turn_id must be a string or None")
        origin = payload.get("origin", ORIGIN_AURALIS)
        if not isinstance(origin, str):
            raise ValueError("origin must be a string")
        submissions = payload.get("submissions", [])
        if not isinstance(submissions, list):
            raise ValueError("submissions must be a list")
        tool_observations = payload.get("tool_observations", [])
        if not isinstance(tool_observations, list):
            raise ValueError("tool_observations must be a list")
        outcome = payload.get("outcome")
        if outcome is not None and not isinstance(outcome, str):
            raise ValueError("outcome must be a string or None")
        created_at = payload.get("created_at", "")
        if not isinstance(created_at, str):
            created_at = datetime.now(UTC).isoformat()
        updated_at = payload.get("updated_at", "")
        if not isinstance(updated_at, str):
            updated_at = datetime.now(UTC).isoformat()

        return cls(
            session_id=session_id,
            binding_id=binding_id,
            turn_id=turn_id,
            origin=origin,
            submissions=submissions,
            tool_observations=tool_observations,
            outcome=outcome,
            created_at=created_at,
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class TurnRecordReport:
    """The result of reading the turn record state."""

    record: TurnRecord | None
    status: str


def _turn_record_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return settings.state_dir() / TURN_RECORD_FILENAME


def _lock_path(lock_path: Path | None, record_path: Path) -> Path:
    if lock_path is not None:
        return lock_path
    return record_path.parent / (record_path.name + ".lock")


def _read_record_from_path(target: Path) -> TurnRecord | None:
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        return TurnRecord.from_payload(payload)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def read_turn_record_report(path: Path | None = None) -> TurnRecordReport:
    """Read the turn record once, reporting status as record, absent, or corrupt."""
    target = _turn_record_path(path)
    if not target.exists():
        return TurnRecordReport(record=None, status=STATUS_ABSENT)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return TurnRecordReport(record=None, status=STATUS_CORRUPT)
        record = TurnRecord.from_payload(payload)
        return TurnRecordReport(record=record, status=STATUS_RECORD)
    except (OSError, ValueError, TypeError, KeyError):
        return TurnRecordReport(record=None, status=STATUS_CORRUPT)


def read_turn_record(path: Path | None = None) -> TurnRecord | None:
    """Return the current turn record, or None if absent or corrupt."""
    return read_turn_record_report(path).record


def mutate(
    fn: Callable[[TurnRecord | None], TurnRecord | None],
    *,
    path: Path | None = None,
    lock_path: Path | None = None,
    timeout_seconds: float = 0.5,
    retry_interval: float = 0.01,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> TurnRecord | None:
    """Execute a mutation on the turn record inside an exclusive flock transaction (KTD11).

    Acquires an exclusive advisory lock on the sidecar lock file within
    timeout_seconds (default 500 ms). If lock acquisition fails, raises
    TurnRecordBusy ('turn_record_busy'). Inside the critical section, reads the
    current record, applies fn(current), and if the result is not None, writes
    it atomically via temporary file and os.replace.
    """
    target = _turn_record_path(path)
    lock_file = _lock_path(lock_path, target)
    target.parent.mkdir(parents=True, exist_ok=True)

    lock_fd = os.open(lock_file, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    start_time = clock()
    deadline = start_time + timeout_seconds

    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except (BlockingIOError, OSError):
                if clock() >= deadline:
                    break
                sleep(retry_interval)

        if not acquired:
            raise TurnRecordBusy(
                f"turn_record_busy: lock acquisition exceeded {timeout_seconds:.3f}s budget"
            )

        current = _read_record_from_path(target)
        new_record = fn(current)

        if new_record is not None:
            fd, temporary = tempfile.mkstemp(
                dir=target.parent, prefix=".turn_record-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(new_record.to_payload(), indent=2, sort_keys=True)
                    )
                    handle.write("\n")
                os.replace(temporary, target)
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
        return new_record
    finally:
        if acquired:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(lock_fd)
        except OSError:
            pass


def init_turn(
    session_id: str,
    binding_id: str | None = None,
    turn_id: str | None = None,
    origin: str = ORIGIN_AURALIS,
    *,
    path: Path | None = None,
    lock_path: Path | None = None,
    **kwargs,
) -> TurnRecord:
    """Initialize a new turn record, replacing any previous turn's record."""
    now = datetime.now(UTC).isoformat()

    def _init(_current: TurnRecord | None) -> TurnRecord:
        return TurnRecord(
            session_id=session_id,
            binding_id=binding_id,
            turn_id=turn_id,
            origin=origin,
            submissions=[],
            tool_observations=[],
            outcome=None,
            created_at=now,
            updated_at=now,
        )

    result = mutate(_init, path=path, lock_path=lock_path, **kwargs)
    assert result is not None
    return result


def record_submission(
    session_id: str,
    text: str,
    disposition: str,
    reason: str | None = None,
    detail: dict[str, object] | None = None,
    *,
    path: Path | None = None,
    lock_path: Path | None = None,
    **kwargs,
) -> TurnRecord:
    """Append a rendering submission and disposition to the current turn record."""
    now = datetime.now(UTC).isoformat()

    def _append(current: TurnRecord | None) -> TurnRecord:
        if current is None:
            raise TurnRecordSessionMismatch("no active turn record")
        if current.session_id != session_id:
            raise TurnRecordSessionMismatch(
                f"session_id mismatch: current is {current.session_id!r}, caller is {session_id!r}"
            )
        sub: dict[str, object] = {
            "text": text,
            "disposition": disposition,
            "reason": reason,
            "detail": detail,
            "timestamp": now,
        }
        new_subs = list(current.submissions)
        new_subs.append(sub)
        return TurnRecord(
            session_id=current.session_id,
            binding_id=current.binding_id,
            turn_id=current.turn_id,
            origin=current.origin,
            submissions=new_subs,
            tool_observations=current.tool_observations,
            outcome=current.outcome,
            created_at=current.created_at,
            updated_at=now,
        )

    result = mutate(_append, path=path, lock_path=lock_path, **kwargs)
    assert result is not None
    return result


def record_tool_observation(
    session_id: str,
    tool_name: str,
    tool_input: object,
    tool_use_id: str,
    *,
    path: Path | None = None,
    lock_path: Path | None = None,
    **kwargs,
) -> TurnRecord:
    """Append a tool-use observation to the current turn record."""
    now = datetime.now(UTC).isoformat()

    def _append(current: TurnRecord | None) -> TurnRecord:
        if current is None:
            raise TurnRecordSessionMismatch("no active turn record")
        if current.session_id != session_id:
            raise TurnRecordSessionMismatch(
                f"session_id mismatch: current is {current.session_id!r}, caller is {session_id!r}"
            )
        obs: dict[str, object] = {
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_use_id": tool_use_id,
            "timestamp": now,
        }
        new_obs = list(current.tool_observations)
        new_obs.append(obs)
        return TurnRecord(
            session_id=current.session_id,
            binding_id=current.binding_id,
            turn_id=current.turn_id,
            origin=current.origin,
            submissions=current.submissions,
            tool_observations=new_obs,
            outcome=current.outcome,
            created_at=current.created_at,
            updated_at=now,
        )

    result = mutate(_append, path=path, lock_path=lock_path, **kwargs)
    assert result is not None
    return result


def settle_outcome(
    session_id: str,
    outcome: str,
    *,
    path: Path | None = None,
    lock_path: Path | None = None,
    **kwargs,
) -> TurnRecord:
    """Settle the outcome of the turn ('authored' or 'fallback'). Settles once."""
    now = datetime.now(UTC).isoformat()

    def _settle(current: TurnRecord | None) -> TurnRecord:
        if current is None:
            raise TurnRecordSessionMismatch("no active turn record")
        if current.session_id != session_id:
            raise TurnRecordSessionMismatch(
                f"session_id mismatch: current is {current.session_id!r}, caller is {session_id!r}"
            )
        if current.outcome is not None:
            return current
        return TurnRecord(
            session_id=current.session_id,
            binding_id=current.binding_id,
            turn_id=current.turn_id,
            origin=current.origin,
            submissions=current.submissions,
            tool_observations=current.tool_observations,
            outcome=outcome,
            created_at=current.created_at,
            updated_at=now,
        )

    result = mutate(_settle, path=path, lock_path=lock_path, **kwargs)
    assert result is not None
    return result
