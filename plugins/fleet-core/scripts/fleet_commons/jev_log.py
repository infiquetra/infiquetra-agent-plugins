"""The verdict log and the answer cache (plan U4).

Every judgment this fleet asks for is recorded outside any model's context, so
the evaluation harness has something real to score later and so an operator can
audit what was asked and what came back.

Two design points worth knowing before reading the code.

**The log lives in the home directory, not the repository.**  Agents here run in
git worktrees under ``.claude/``, which is git-ignored, so a repository-rooted
log would be per-worktree and would vanish with the worktree -- taking the
accumulated evidence with it.  The default is ``~/.claude/typesafe/`` for the
same reason ``audit_store.py`` defaults to ``~/.claude/delegation-audit``.

**The cache is keyed on the model alias that was requested, not the version that
came back.**  The resolved version is only known *from* the response, while a
cache lookup necessarily happens before the call, so keying on it would mean a
cache that can never hit.  Keying on the alias alone would serve a stale answer
after the alias moves to a new model, so a pin file records what each alias last
resolved to and the bucket is invalidated when that changes.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LOG_DIR_ENV = "INFIQUETRA_TYPESAFE_LOG_DIR"
DEFAULT_LOG_DIRNAME = Path(".claude") / "typesafe"
VERDICT_FILENAME = "verdicts.jsonl"
CACHE_FILENAME = "cache.jsonl"
PIN_FILENAME = "model-pins.json"


def log_dir(getenv: Callable[[str], str | None] | None = None) -> Path:
    """Where durable state lives.  Outside the repository tree by default."""
    read = getenv if getenv is not None else os.environ.get
    override = read(LOG_DIR_ENV)
    if override:
        return Path(override)
    return Path.home() / DEFAULT_LOG_DIRNAME


def _canonical(value: Any) -> str:
    """A stable serialization, so key order can never change a hash."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheKey:
    """(state, questions, requested model alias) -- never the resolved version."""

    state_hash: str
    questions_hash: str
    requested_model: str

    def as_str(self) -> str:
        return f"{self.state_hash}:{self.questions_hash}:{self.requested_model}"


def cache_key(state: Any, questions: Mapping[str, Any], requested_model: str) -> CacheKey:
    return CacheKey(
        state_hash=digest(state),
        questions_hash=digest(dict(questions)),
        requested_model=requested_model,
    )


def _append(path: Path, record: Mapping[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical(record) + "\n")
    except OSError as exc:
        # Loud, not swallowed: a log that silently stops recording is worse than
        # one that fails, because the harness would score an incomplete history.
        raise RuntimeError(f"could not append to the verdict log at {path}: {exc}") from None


def _read_lines(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Read JSON Lines, tolerating a truncated final line.

    Returns the intact records and the number of unreadable ones, because a
    partially written last line is a normal consequence of a killed process and
    should not make the whole history unreadable.
    """
    if not path.is_file():
        return [], 0
    records: list[dict[str, Any]] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
        else:
            skipped += 1
    return records, skipped


# --------------------------------------------------------------------------- #
# The verdict log
# --------------------------------------------------------------------------- #


def record_verdict(
    *,
    decision_id: str,
    state: Any,
    questions: Mapping[str, Any],
    answer: Mapping[str, Any],
    confidence: float | None,
    threshold: float | None,
    resolved_model: str,
    label: Any = None,
    directory: Path | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Append one verdict.  Stores hashes and the answer, never the raw state.

    ``confidence`` is ``None`` for a yes/no answer, which carries a probability
    and no confidence field -- verified against the live endpoint.
    """
    record = {
        "kind": "verdict",
        "decision_id": decision_id,
        "state_hash": digest(state),
        "questions_hash": digest(dict(questions)),
        "answer": dict(answer),
        "confidence": confidence,
        "threshold": threshold,
        "resolved_model": resolved_model,
        # The known-correct value, when one is known at write time.  Without it
        # the evaluation harness cannot score accumulated history at all: it
        # joins answers to labels on this record's decision_id and finds none.
        "label": label,
        "at": _timestamp(clock),
    }
    record["verdict_hash"] = digest(
        {k: record[k] for k in ("decision_id", "state_hash", "questions_hash", "at")}
    )
    _append((directory or log_dir()) / VERDICT_FILENAME, record)
    return record


def record_override(
    *,
    verdict_hash: str,
    chosen: Any,
    rationale: str = "",
    directory: Path | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Append an operator override, linked to the verdict it overrode by hash."""
    record = {
        "kind": "override",
        "verdict_hash": verdict_hash,
        "chosen": chosen,
        "rationale": rationale,
        "at": _timestamp(clock),
    }
    _append((directory or log_dir()) / VERDICT_FILENAME, record)
    return record


def read_verdicts(directory: Path | None = None) -> tuple[list[dict[str, Any]], int]:
    return _read_lines((directory or log_dir()) / VERDICT_FILENAME)


def _timestamp(clock: Callable[[], float]) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(clock()))


# --------------------------------------------------------------------------- #
# The alias pin
# --------------------------------------------------------------------------- #


def read_pins(directory: Path | None = None) -> dict[str, str]:
    path = (directory or log_dir()) / PIN_FILENAME
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def write_pin(alias: str, resolved: str, directory: Path | None = None) -> dict[str, str]:
    base = directory or log_dir()
    pins = read_pins(base)
    pins[alias] = resolved
    base.mkdir(parents=True, exist_ok=True)
    (base / PIN_FILENAME).write_text(json.dumps(pins, indent=2, sort_keys=True), encoding="utf-8")
    return pins


# --------------------------------------------------------------------------- #
# The cache
# --------------------------------------------------------------------------- #


def cache_store(
    key: CacheKey,
    result: Mapping[str, Any],
    *,
    resolved_model: str,
    directory: Path | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    base = directory or log_dir()
    record = {
        "kind": "cache",
        "key": key.as_str(),
        "requested_model": key.requested_model,
        "resolved_model": resolved_model,
        "result": dict(result),
        "at": _timestamp(clock),
    }
    _append(base / CACHE_FILENAME, record)
    write_pin(key.requested_model, resolved_model, base)
    return record


def cache_lookup(
    key: CacheKey,
    *,
    directory: Path | None = None,
    current_resolved_model: str | None = None,
) -> dict[str, Any] | None:
    """Return a cached result, or ``None``.

    When ``current_resolved_model`` is supplied and differs from what the alias
    was pinned to, the whole bucket for that alias is treated as invalid -- this
    is what stops a stale answer being replayed after the alias moves.
    """
    base = directory or log_dir()
    if current_resolved_model is not None:
        pinned = read_pins(base).get(key.requested_model)
        if pinned is not None and pinned != current_resolved_model:
            return None

    records, _ = _read_lines(base / CACHE_FILENAME)
    wanted = key.as_str()
    for record in reversed(records):
        if record.get("key") == wanted:
            result = record.get("result")
            return dict(result) if isinstance(result, dict) else None
    return None


def invalidate_alias(alias: str, directory: Path | None = None) -> int:
    """Drop every cached entry recorded under ``alias``.  Returns the count."""
    base = directory or log_dir()
    path = base / CACHE_FILENAME
    records, _ = _read_lines(path)
    kept = [r for r in records if r.get("requested_model") != alias]
    dropped = len(records) - len(kept)
    if dropped:
        path.write_text("".join(_canonical(record) + "\n" for record in kept), encoding="utf-8")
    return dropped


__all__: Sequence[str] = (
    "CACHE_FILENAME",
    "CacheKey",
    "PIN_FILENAME",
    "VERDICT_FILENAME",
    "cache_key",
    "cache_lookup",
    "cache_store",
    "digest",
    "invalidate_alias",
    "log_dir",
    "read_pins",
    "read_verdicts",
    "record_override",
    "record_verdict",
    "write_pin",
)
