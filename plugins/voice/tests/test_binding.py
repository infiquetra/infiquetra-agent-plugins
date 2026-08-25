"""Tests for the sticky single-speaker binding store (R2; KTD1, KTD7, KTD12).

The state directory seam is injected through ``VOICE_STATE_DIR`` per test,
so every scenario runs against a fresh temporary directory and nothing
touches the machine-local state of the host running the suite.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import binding  # noqa: E402

AGENT = "example-agent"
SESSION_ID = "example-session-one"
PANE_ID = "example-pane-one"
BOUND_AT = "2026-08-25T00:00:00+00:00"

OTHER_AGENT = "example-agent-other"
OTHER_SESSION_ID = "example-session-two"
OTHER_PANE_ID = "example-pane-two"
OTHER_BOUND_AT = "2026-08-25T01:00:00+00:00"


class BindingStoreTestCase(unittest.TestCase):
    """Common fixture: one fresh state directory per test."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.state_dir = Path(temporary.name)
        environment = patch.dict(
            os.environ, {"VOICE_STATE_DIR": str(self.state_dir)}
        )
        environment.start()
        self.addCleanup(environment.stop)

    def binding_path(self) -> Path:
        return self.state_dir / binding.BINDING_FILENAME

    def write_example(self) -> binding.Binding:
        return binding.write_binding(
            AGENT, SESSION_ID, PANE_ID, bound_at=BOUND_AT
        )


class WriteAndReadTests(BindingStoreTestCase):
    """A written record round-trips through the one state file."""

    def test_a_written_binding_round_trips(self) -> None:
        written = self.write_example()
        record = binding.read_binding()
        self.assertIsNotNone(record)
        self.assertEqual(record, written)
        self.assertEqual(record.agent, AGENT)
        self.assertEqual(record.session_id, SESSION_ID)
        self.assertEqual(record.pane_id, PANE_ID)
        self.assertEqual(record.bound_at, BOUND_AT)

    def test_a_write_creates_a_missing_state_directory(self) -> None:
        nested = self.state_dir / "deeper" / "state"
        with patch.dict(os.environ, {"VOICE_STATE_DIR": str(nested)}):
            binding.write_binding(AGENT, SESSION_ID, PANE_ID, bound_at=BOUND_AT)
            self.assertIsNotNone(binding.read_binding())

    def test_bound_at_defaults_to_a_current_utc_timestamp(self) -> None:
        record = binding.write_binding(AGENT, SESSION_ID, PANE_ID)
        parsed = datetime.fromisoformat(record.bound_at)
        self.assertIsNotNone(parsed.tzinfo)

    def test_empty_or_blank_fields_are_rejected_by_name(self) -> None:
        cases = [
            ("", SESSION_ID, PANE_ID),
            ("   ", SESSION_ID, PANE_ID),
            (AGENT, "", PANE_ID),
            (AGENT, SESSION_ID, " "),
        ]
        for agent, session_id, pane_id in cases:
            with self.subTest(agent=agent, session_id=session_id, pane_id=pane_id):
                with self.assertRaises(ValueError):
                    binding.write_binding(
                        agent, session_id, pane_id, bound_at=BOUND_AT
                    )
        self.assertFalse(
            self.binding_path().exists(),
            "a rejected write must leave no binding behind",
        )

    def test_a_write_is_atomic_and_leaves_no_litter(self) -> None:
        self.write_example()
        contents = [path.name for path in self.state_dir.iterdir()]
        self.assertEqual(contents, [binding.BINDING_FILENAME])
        payload = json.loads(self.binding_path().read_text(encoding="utf-8"))
        self.assertEqual(
            payload,
            {
                "agent": AGENT,
                "session_id": SESSION_ID,
                "pane_id": PANE_ID,
                "bound_at": BOUND_AT,
            },
        )


class SingleValuedStickyTests(BindingStoreTestCase):
    """Exactly one binding exists at a time, until explicitly changed (R2)."""

    def test_exactly_one_binding_exists_at_a_time(self) -> None:
        self.write_example()
        binding.write_binding(
            OTHER_AGENT, OTHER_SESSION_ID, OTHER_PANE_ID, bound_at=OTHER_BOUND_AT
        )
        files = sorted(path.name for path in self.state_dir.iterdir())
        self.assertEqual(files, [binding.BINDING_FILENAME])

    def test_rebinding_replaces_the_previous_binding(self) -> None:
        self.write_example()
        binding.write_binding(
            OTHER_AGENT, OTHER_SESSION_ID, OTHER_PANE_ID, bound_at=OTHER_BOUND_AT
        )
        record = binding.read_binding()
        self.assertIsNotNone(record)
        self.assertEqual(record.agent, OTHER_AGENT)
        self.assertEqual(record.session_id, OTHER_SESSION_ID)
        self.assertEqual(record.pane_id, OTHER_PANE_ID)
        self.assertEqual(record.bound_at, OTHER_BOUND_AT)

    def test_the_binding_persists_until_explicitly_changed(self) -> None:
        written = self.write_example()
        before = self.binding_path().read_bytes()
        for _ in range(3):
            self.assertEqual(binding.read_binding(), written)
        self.assertEqual(
            self.binding_path().read_bytes(),
            before,
            "reading the binding never changes it",
        )

    def test_nothing_infers_a_target_from_focus_or_recency(self) -> None:
        self.write_example()
        # Other voice state files — recorder, playback, a speak payload
        # naming a different session — carry no authority over the binding.
        (self.state_dir / "recording.json").write_text(
            json.dumps({"pid": 1234}), encoding="utf-8"
        )
        (self.state_dir / "playback.json").write_text(
            json.dumps({"pid": 5678}), encoding="utf-8"
        )
        (self.state_dir / "speak-00000000.json").write_text(
            json.dumps({"text": "example text"}), encoding="utf-8"
        )
        record = binding.read_binding()
        self.assertIsNotNone(record)
        self.assertEqual(record.session_id, SESSION_ID)
        # With no binding written at all, surrounding state implies nothing.
        self.binding_path().unlink()
        self.assertIsNone(binding.read_binding())


class UnboundReadTests(BindingStoreTestCase):
    """Absent and corrupt files both read as unbound, reportably distinct."""

    def test_an_absent_file_reads_as_unbound(self) -> None:
        self.assertIsNone(binding.read_binding())
        report = binding.read_binding_report()
        self.assertIsNone(report.binding)
        self.assertEqual(report.status, binding.STATUS_ABSENT)

    def test_a_corrupt_file_reads_as_unbound(self) -> None:
        cases = {
            "not json": "this is not json {",
            "not an object": json.dumps([SESSION_ID]),
            "missing fields": json.dumps({"agent": AGENT}),
            "empty session id": json.dumps(
                {
                    "agent": AGENT,
                    "session_id": "",
                    "pane_id": PANE_ID,
                    "bound_at": BOUND_AT,
                }
            ),
            "wrong field type": json.dumps(
                {
                    "agent": AGENT,
                    "session_id": 42,
                    "pane_id": PANE_ID,
                    "bound_at": BOUND_AT,
                }
            ),
        }
        for name, contents in cases.items():
            with self.subTest(name=name):
                self.binding_path().write_text(contents, encoding="utf-8")
                self.assertIsNone(binding.read_binding())
                report = binding.read_binding_report()
                self.assertIsNone(report.binding)
                self.assertEqual(report.status, binding.STATUS_CORRUPT)

    def test_the_absent_and_corrupt_states_are_reportable_and_distinct(self) -> None:
        absent = binding.read_binding_report()
        self.binding_path().write_text("not json {", encoding="utf-8")
        corrupt = binding.read_binding_report()
        self.assertIsNone(absent.binding)
        self.assertIsNone(corrupt.binding)
        self.assertNotEqual(absent.status, corrupt.status)
        self.assertEqual(absent.status, binding.STATUS_ABSENT)
        self.assertEqual(corrupt.status, binding.STATUS_CORRUPT)

    def test_a_bound_report_carries_the_record(self) -> None:
        written = self.write_example()
        report = binding.read_binding_report()
        self.assertEqual(report.status, binding.STATUS_BOUND)
        self.assertEqual(report.binding, written)


if __name__ == "__main__":
    unittest.main()
