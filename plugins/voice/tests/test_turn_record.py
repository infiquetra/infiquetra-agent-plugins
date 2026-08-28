"""Tests for the per-turn state and mutation record (R23, R122; KTD11).

Covers:
- Turn initialization replacing previous turn's record;
- Submissions and tool observations appending;
- Outcome settling once ('authored' vs 'fallback');
- Session mismatch refusal;
- Absent and corrupt store states;
- Deterministic concurrency / interleaving proof (KTD11 flock transactions);
- 500 ms acquisition deadline timeout raising TurnRecordBusy.
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import turn_record  # noqa: E402

SESSION_ONE = "claude-session-001"
SESSION_TWO = "claude-session-002"
BINDING_ID = "00000000-0000-4000-8000-000000000001"
TURN_ID = "00000000-0000-4000-8000-000000000002"


class TurnRecordTestCase(unittest.TestCase):
    """Common fixture: one fresh temporary state directory per test."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_dir = Path(temporary.name)
        environment = patch.dict(
            os.environ, {"VOICE_STATE_DIR": str(self.state_dir)}
        )
        environment.start()
        self.addCleanup(environment.stop)

    def record_path(self) -> Path:
        return self.state_dir / turn_record.TURN_RECORD_FILENAME

    def lock_path(self) -> Path:
        return self.state_dir / turn_record.TURN_RECORD_LOCK_FILENAME


class TurnLifecycleTests(TurnRecordTestCase):
    """Basic lifecycle: init, submit, observe tools, settle outcome."""

    def test_init_turn_creates_record_and_replaces_previous(self) -> None:
        record1 = turn_record.init_turn(
            session_id=SESSION_ONE,
            binding_id=BINDING_ID,
            turn_id=TURN_ID,
            origin=turn_record.ORIGIN_AURALIS,
        )
        self.assertEqual(record1.session_id, SESSION_ONE)
        self.assertEqual(record1.binding_id, BINDING_ID)
        self.assertEqual(record1.turn_id, TURN_ID)
        self.assertEqual(record1.origin, turn_record.ORIGIN_AURALIS)
        self.assertEqual(record1.submissions, [])
        self.assertEqual(record1.tool_observations, [])
        self.assertIsNone(record1.outcome)

        # Initializing a new turn replaces the record
        new_turn_id = "00000000-0000-4000-8000-000000000003"
        record2 = turn_record.init_turn(
            session_id=SESSION_ONE,
            binding_id=BINDING_ID,
            turn_id=new_turn_id,
        )
        self.assertEqual(record2.turn_id, new_turn_id)
        current = turn_record.read_turn_record()
        self.assertIsNotNone(current)
        self.assertEqual(current.turn_id, new_turn_id)

    def test_record_submission_appends(self) -> None:
        turn_record.init_turn(SESSION_ONE, BINDING_ID, TURN_ID)

        turn_record.record_submission(
            session_id=SESSION_ONE,
            text="First rejected submission *markdown*",
            disposition="rejected_content",
            reason="markdown_formatting",
            detail={"detected_classes": ["emphasis_strong"], "first_offending_line": 1},
        )

        turn_record.record_submission(
            session_id=SESSION_ONE,
            text="Second clean plain submission.",
            disposition="accepted",
            reason=None,
            detail=None,
        )

        current = turn_record.read_turn_record()
        self.assertIsNotNone(current)
        self.assertEqual(len(current.submissions), 2)
        self.assertEqual(current.submissions[0]["disposition"], "rejected_content")
        self.assertEqual(current.submissions[0]["reason"], "markdown_formatting")
        self.assertEqual(current.submissions[1]["disposition"], "accepted")
        self.assertIsNone(current.submissions[1]["reason"])

    def test_record_tool_observation_appends(self) -> None:
        turn_record.init_turn(SESSION_ONE, BINDING_ID, TURN_ID)

        turn_record.record_tool_observation(
            session_id=SESSION_ONE,
            tool_name="read_file",
            tool_input={"path": "main.py"},
            tool_use_id="toolu_01",
        )

        turn_record.record_tool_observation(
            session_id=SESSION_ONE,
            tool_name="grep_search",
            tool_input={"query": "hello"},
            tool_use_id="toolu_02",
        )

        current = turn_record.read_turn_record()
        self.assertIsNotNone(current)
        self.assertEqual(len(current.tool_observations), 2)
        self.assertEqual(current.tool_observations[0]["tool_name"], "read_file")
        self.assertEqual(current.tool_observations[1]["tool_name"], "grep_search")

    def test_settle_outcome_settles_once(self) -> None:
        turn_record.init_turn(SESSION_ONE, BINDING_ID, TURN_ID)
        self.assertIsNone(turn_record.read_turn_record().outcome)

        settled = turn_record.settle_outcome(SESSION_ONE, turn_record.OUTCOME_AUTHORED)
        self.assertEqual(settled.outcome, turn_record.OUTCOME_AUTHORED)

        # Attempting to settle again does not overwrite first outcome
        settled_again = turn_record.settle_outcome(
            SESSION_ONE, turn_record.OUTCOME_FALLBACK
        )
        self.assertEqual(settled_again.outcome, turn_record.OUTCOME_AUTHORED)
        self.assertEqual(
            turn_record.read_turn_record().outcome, turn_record.OUTCOME_AUTHORED
        )

    def test_session_mismatch_refused_by_name(self) -> None:
        turn_record.init_turn(SESSION_ONE, BINDING_ID, TURN_ID)

        with self.assertRaises(turn_record.TurnRecordSessionMismatch):
            turn_record.record_submission(
                session_id=SESSION_TWO,
                text="text",
                disposition="accepted",
            )

        with self.assertRaises(turn_record.TurnRecordSessionMismatch):
            turn_record.record_tool_observation(
                session_id=SESSION_TWO,
                tool_name="read_file",
                tool_input={},
                tool_use_id="id",
            )

        with self.assertRaises(turn_record.TurnRecordSessionMismatch):
            turn_record.settle_outcome(
                session_id=SESSION_TWO,
                outcome=turn_record.OUTCOME_AUTHORED,
            )


class TurnRecordStoreStateTests(TurnRecordTestCase):
    """Store read, absent, and corrupt state behaviors."""

    def test_absent_store_reports_absent(self) -> None:
        report = turn_record.read_turn_record_report()
        self.assertEqual(report.status, turn_record.STATUS_ABSENT)
        self.assertIsNone(report.record)
        self.assertIsNone(turn_record.read_turn_record())

    def test_corrupt_store_reports_corrupt(self) -> None:
        cases = {
            "invalid json": "not json {",
            "not dict": json.dumps(["not", "an", "object"]),
            "session_id not string": json.dumps({"session_id": 123}),
            "submissions not list": json.dumps(
                {"session_id": SESSION_ONE, "submissions": "bad"}
            ),
            "tool_observations not list": json.dumps(
                {"session_id": SESSION_ONE, "tool_observations": "bad"}
            ),
        }
        for name, contents in cases.items():
            with self.subTest(name=name):
                self.record_path().write_text(contents, encoding="utf-8")
                report = turn_record.read_turn_record_report()
                self.assertEqual(report.status, turn_record.STATUS_CORRUPT)
                self.assertIsNone(report.record)
                self.assertIsNone(turn_record.read_turn_record())


class ConcurrencyAndInterleavingTests(TurnRecordTestCase):
    """KTD11 flock concurrency proofs: deterministic serialization and timeout budget."""

    def test_deterministic_interleaving_prevents_lost_updates(self) -> None:
        """Two concurrent mutate calls from separate threads with event-controlled pauses.

        Writer 1 enters critical section and waits on writer2_retry_attempted.
        Writer 2 begins mutate() in another thread. When writer 2's flock acquisition
        fails because writer 1 holds the lock, writer 2's sleep hook sets
        writer2_retry_attempted, deterministically proving exclusion.
        Writer 1 then unblocks, completes mutation, releases the lock, and sets
        writer1_finished.
        Writer 2 then acquires the lock and enters writer2_fn, verifying that
        writer 1 has finished. Writer 2 reads writer 1's write, resulting in
        both updates persisting with no lost updates.
        """
        turn_record.init_turn(SESSION_ONE, BINDING_ID, TURN_ID)

        writer1_in_critical = threading.Event()
        writer2_retry_attempted = threading.Event()
        writer1_finished = threading.Event()
        writer2_in_critical = threading.Event()

        def writer1_fn(current: turn_record.TurnRecord | None) -> turn_record.TurnRecord:
            writer1_in_critical.set()
            self.assertTrue(
                writer2_retry_attempted.wait(timeout=5.0),
                "writer 2 must attempt lock and fail while writer 1 holds it",
            )
            assert current is not None
            sub = {
                "text": "writer1",
                "disposition": "rejected_content",
                "timestamp": "2026-08-27T00:00:00",
            }
            return turn_record.TurnRecord(
                session_id=current.session_id,
                binding_id=current.binding_id,
                turn_id=current.turn_id,
                origin=current.origin,
                submissions=current.submissions + [sub],
                tool_observations=current.tool_observations,
                outcome=current.outcome,
                created_at=current.created_at,
                updated_at="2026-08-27T00:00:00",
            )

        def writer2_fn(current: turn_record.TurnRecord | None) -> turn_record.TurnRecord:
            self.assertTrue(
                writer1_finished.is_set(),
                "writer 2 must not enter critical section until writer 1 has finished",
            )
            writer2_in_critical.set()
            assert current is not None
            sub = {
                "text": "writer2",
                "disposition": "accepted",
                "timestamp": "2026-08-27T00:00:01",
            }
            return turn_record.TurnRecord(
                session_id=current.session_id,
                binding_id=current.binding_id,
                turn_id=current.turn_id,
                origin=current.origin,
                submissions=current.submissions + [sub],
                tool_observations=current.tool_observations,
                outcome=current.outcome,
                created_at=current.created_at,
                updated_at="2026-08-27T00:00:01",
            )

        def writer2_sleep(_interval: float) -> None:
            writer2_retry_attempted.set()
            time.sleep(0.001)

        t1_error: list[Exception] = []
        t2_error: list[Exception] = []

        def run_writer1() -> None:
            try:
                turn_record.mutate(writer1_fn)
                writer1_finished.set()
            except Exception as e:
                t1_error.append(e)

        def run_writer2() -> None:
            try:
                turn_record.mutate(
                    writer2_fn,
                    sleep=writer2_sleep,
                    timeout_seconds=5.0,
                )
            except Exception as e:
                t2_error.append(e)

        t1 = threading.Thread(target=run_writer1)
        t2 = threading.Thread(target=run_writer2)

        t1.start()
        self.assertTrue(writer1_in_critical.wait(timeout=5.0))

        t2.start()

        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        self.assertEqual(t1_error, [])
        self.assertEqual(t2_error, [])
        self.assertTrue(writer2_in_critical.is_set())

        final_record = turn_record.read_turn_record()
        self.assertIsNotNone(final_record)
        # BOTH updates must be present!
        sub_texts = [s["text"] for s in final_record.submissions]
        self.assertEqual(sub_texts, ["writer1", "writer2"])

    def test_lock_acquisition_timeout_raises_turn_record_busy(self) -> None:
        """Holding the lock past acquisition budget raises TurnRecordBusy without writing."""
        turn_record.init_turn(SESSION_ONE, BINDING_ID, TURN_ID)

        # Hold the lock file exclusively with a separate file descriptor
        lock_fd = os.open(self.lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        mutation_ran = False

        def failing_fn(current: turn_record.TurnRecord | None) -> turn_record.TurnRecord | None:
            nonlocal mutation_ran
            mutation_ran = True
            return current

        current_time = 0.0

        def stub_clock() -> float:
            nonlocal current_time
            current_time += 0.2
            return current_time

        try:
            with self.assertRaises(turn_record.TurnRecordBusy):
                turn_record.mutate(
                    failing_fn,
                    timeout_seconds=0.5,
                    retry_interval=0.01,
                    clock=stub_clock,
                    sleep=lambda _: None,
                )
            self.assertFalse(
                mutation_ran,
                "mutation function must not run if lock is not acquired",
            )
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    def test_stubbed_clock_acquisition_budget_refusal(self) -> None:
        """Clock advances past budget immediately, proving named turn_record_busy refusal."""
        turn_record.init_turn(SESSION_ONE, BINDING_ID, TURN_ID)

        lock_fd = os.open(self.lock_path(), os.O_RDWR | os.O_CREAT, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)

        current_time = 1000.0

        def stub_clock() -> float:
            nonlocal current_time
            # Advance clock past budget on subsequent check
            current_time += 1.0
            return current_time

        try:
            with self.assertRaises(turn_record.TurnRecordBusy) as ctx:
                turn_record.mutate(
                    lambda r: r,
                    timeout_seconds=0.5,
                    retry_interval=0.01,
                    clock=stub_clock,
                    sleep=lambda _: None,
                )
            self.assertIn("turn_record_busy", str(ctx.exception))
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)


if __name__ == "__main__":
    unittest.main()
