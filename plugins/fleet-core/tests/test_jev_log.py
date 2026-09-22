"""Tests for the verdict log, the answer cache and the alias pin (plan U4)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/jev_log.py"

SENTINEL = "SENTINEL-log-do-not-leak-7a2e"  # noqa: S105 - a test fixture


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("jev_log_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


log = _load()

STATE = {"task": "rename a variable across twelve files"}
QUESTIONS = {"model": {"type": "choice", "instructions": "which tier?"}}
ANSWER = {"type": "choice", "choice": "haiku", "confidence": 0.93}


def test_the_default_log_directory_is_outside_the_repository() -> None:
    """A repo-rooted log would die with the worktree, taking the evidence."""
    default = log.log_dir(getenv=lambda _name: None)
    assert not str(default).startswith(str(REPO_ROOT))
    assert default == Path.home() / ".claude" / "typesafe"


def test_the_log_directory_is_overridable(tmp_path) -> None:
    assert log.log_dir(getenv={log.LOG_DIR_ENV: str(tmp_path)}.get) == tmp_path


def test_a_verdict_appends_one_line_with_the_full_record_contract(tmp_path) -> None:
    record = log.record_verdict(
        decision_id="tier:model",
        state=STATE,
        questions=QUESTIONS,
        answer=ANSWER,
        confidence=0.93,
        threshold=0.6,
        resolved_model="jev-1.13.0",
        directory=tmp_path,
    )
    lines = (tmp_path / log.VERDICT_FILENAME).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert set(parsed) == {
        "kind",
        "decision_id",
        "state_hash",
        "questions_hash",
        "answer",
        "confidence",
        "threshold",
        "resolved_model",
        "label",
        "at",
        "verdict_hash",
    }
    assert parsed["resolved_model"] == "jev-1.13.0"
    assert parsed["verdict_hash"] == record["verdict_hash"]


def test_a_yes_no_verdict_records_a_null_confidence(tmp_path) -> None:
    log.record_verdict(
        decision_id="d",
        state=STATE,
        questions=QUESTIONS,
        answer={"type": "noul", "noul": 0.97},
        confidence=None,
        threshold=None,
        resolved_model="jev-1.13.0",
        directory=tmp_path,
    )
    records, _ = log.read_verdicts(tmp_path)
    assert records[0]["confidence"] is None


def test_an_override_links_to_its_verdict_by_hash(tmp_path) -> None:
    verdict = log.record_verdict(
        decision_id="d",
        state=STATE,
        questions=QUESTIONS,
        answer=ANSWER,
        confidence=0.93,
        threshold=0.6,
        resolved_model="jev-1.13.0",
        directory=tmp_path,
    )
    log.record_override(
        verdict_hash=verdict["verdict_hash"],
        chosen="sonnet",
        rationale="the survey was wider than it looked",
        directory=tmp_path,
    )
    records, _ = log.read_verdicts(tmp_path)
    assert len(records) == 2
    assert records[1]["kind"] == "override"
    assert records[1]["verdict_hash"] == verdict["verdict_hash"]


def test_the_log_stores_hashes_not_raw_state(tmp_path) -> None:
    log.record_verdict(
        decision_id="d",
        state={"prompt": f"a secret {SENTINEL} lives here"},
        questions=QUESTIONS,
        answer=ANSWER,
        confidence=0.9,
        threshold=0.6,
        resolved_model="jev-1.13.0",
        directory=tmp_path,
    )
    written = (tmp_path / log.VERDICT_FILENAME).read_text(encoding="utf-8")
    assert SENTINEL not in written


def test_appending_the_same_verdict_twice_yields_two_lines(tmp_path) -> None:
    for _ in range(2):
        log.record_verdict(
            decision_id="d",
            state=STATE,
            questions=QUESTIONS,
            answer=ANSWER,
            confidence=0.9,
            threshold=0.6,
            resolved_model="jev-1.13.0",
            directory=tmp_path,
        )
    records, _ = log.read_verdicts(tmp_path)
    assert len(records) == 2, "the log appends; it never rewrites or deduplicates"


def test_a_truncated_final_line_is_reported_not_fatal(tmp_path) -> None:
    path = tmp_path / log.VERDICT_FILENAME
    path.write_text('{"kind":"verdict","decision_id":"a"}\n{"kind":"ver', encoding="utf-8")
    records, skipped = log.read_verdicts(tmp_path)
    assert len(records) == 1
    assert skipped == 1


def test_an_unwritable_directory_fails_loudly(tmp_path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    with pytest.raises(RuntimeError, match="could not append"):
        log.record_verdict(
            decision_id="d",
            state=STATE,
            questions=QUESTIONS,
            answer=ANSWER,
            confidence=0.9,
            threshold=0.6,
            resolved_model="jev-1.13.0",
            directory=blocker,
        )


# --------------------------------------------------------------------------- #
# Hashing and the cache key
# --------------------------------------------------------------------------- #


def test_key_order_cannot_change_a_hash() -> None:
    assert log.digest({"a": 1, "b": 2}) == log.digest({"b": 2, "a": 1})


def test_the_cache_key_uses_the_requested_alias_not_the_resolved_version() -> None:
    key = log.cache_key(STATE, QUESTIONS, "jev-latest")
    assert key.requested_model == "jev-latest"
    assert "jev-1.13.0" not in key.as_str()


def test_a_cached_answer_is_returned_without_a_transport_call(tmp_path) -> None:
    key = log.cache_key(STATE, QUESTIONS, "jev-latest")
    log.cache_store(key, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    assert log.cache_lookup(key, directory=tmp_path) == {"status": "ok"}


def test_two_calls_for_the_same_alias_share_a_cache_entry(tmp_path) -> None:
    first = log.cache_key(STATE, QUESTIONS, "jev-latest")
    second = log.cache_key(dict(STATE), dict(QUESTIONS), "jev-latest")
    log.cache_store(first, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    assert log.cache_lookup(second, directory=tmp_path) is not None


def test_a_changed_state_misses(tmp_path) -> None:
    key = log.cache_key(STATE, QUESTIONS, "jev-latest")
    log.cache_store(key, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    changed = log.cache_key(
        {"task": "rename a variable across twelve file"}, QUESTIONS, "jev-latest"
    )
    assert log.cache_lookup(changed, directory=tmp_path) is None


def test_a_changed_question_misses(tmp_path) -> None:
    key = log.cache_key(STATE, QUESTIONS, "jev-latest")
    log.cache_store(key, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    other = log.cache_key(STATE, {"model": {"type": "choice", "instructions": "x"}}, "jev-latest")
    assert log.cache_lookup(other, directory=tmp_path) is None


def test_an_explicit_version_does_not_hit_an_alias_entry(tmp_path) -> None:
    alias = log.cache_key(STATE, QUESTIONS, "jev-latest")
    log.cache_store(alias, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    exact = log.cache_key(STATE, QUESTIONS, "jev-1.13.0")
    assert log.cache_lookup(exact, directory=tmp_path) is None


def test_a_moved_alias_invalidates_rather_than_serving_a_stale_answer(tmp_path) -> None:
    """The scenario the alias pin exists for."""
    key = log.cache_key(STATE, QUESTIONS, "jev-latest")
    log.cache_store(key, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    assert (
        log.cache_lookup(key, directory=tmp_path, current_resolved_model="jev-1.13.0") is not None
    )
    # The alias now points somewhere else: the bucket must not be served.
    assert log.cache_lookup(key, directory=tmp_path, current_resolved_model="jev-1.14.0") is None


def test_invalidating_an_alias_drops_its_entries(tmp_path) -> None:
    key = log.cache_key(STATE, QUESTIONS, "jev-latest")
    log.cache_store(key, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    assert log.invalidate_alias("jev-latest", tmp_path) == 1
    assert log.cache_lookup(key, directory=tmp_path) is None


def test_the_pin_records_what_the_alias_resolved_to(tmp_path) -> None:
    key = log.cache_key(STATE, QUESTIONS, "jev-latest")
    log.cache_store(key, {"status": "ok"}, resolved_model="jev-1.13.0", directory=tmp_path)
    assert log.read_pins(tmp_path)["jev-latest"] == "jev-1.13.0"


def test_a_corrupt_pin_file_reads_as_empty_rather_than_raising(tmp_path) -> None:
    (tmp_path / log.PIN_FILENAME).write_text("{not json", encoding="utf-8")
    assert log.read_pins(tmp_path) == {}
