"""Tests for the adapter identity resolver (KTD9; §5).

Exercises the Section 5 identity discovery rule across happy paths, env var
failures, executable failures, timeouts, envelope malformations, zero/multiple
pane matches, and component-level corruptions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import adapter_identity  # noqa: E402
import settings  # noqa: E402


class _FakeCompletedProcess:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _valid_herdr_envelope(
    *,
    pane_id: str = "w1:p1",
    terminal_id: str = "term-1",
    session_id: str = "session-abc-123",
) -> str:
    return json.dumps(
        {
            "type": "agent_list",
            "agents": [
                {
                    "pane_id": pane_id,
                    "terminal_id": terminal_id,
                    "agent_session": {"value": session_id},
                }
            ],
        }
    )


class AdapterIdentityTests(unittest.TestCase):
    """Happy path and structure tests for AdapterIdentity."""

    def test_happy_path_resolves_three_components_exactly(self) -> None:
        raw_json = _valid_herdr_envelope(
            pane_id="w1:p2",
            terminal_id="t-99",
            session_id="session-xyz-789",
        )
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(raw_json))
        env = {
            settings.HERDR_PANE_ID: "w1:p2",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            identity = adapter_identity.resolve_adapter_identity(run_process=fake_run)

        self.assertEqual(identity.agent_session_id, "session-xyz-789")
        self.assertEqual(identity.pane_id, "w1:p2")
        self.assertEqual(identity.terminal_id, "t-99")
        self.assertEqual(
            identity.to_dict(),
            {
                "agent_session_id": "session-xyz-789",
                "pane_id": "w1:p2",
                "terminal_id": "t-99",
            },
        )
        fake_run.assert_called_once_with(
            ["/bin/herdr", "agent", "list"],
            timeout=adapter_identity.HERDR_TIMEOUT_SECONDS,
            check=True,
        )

    def test_matches_session_verification(self) -> None:
        identity = adapter_identity.AdapterIdentity(
            agent_session_id="session-1",
            pane_id="p1",
            terminal_id="t1",
        )
        self.assertTrue(adapter_identity.matches_session(identity, "session-1"))
        self.assertFalse(adapter_identity.matches_session(identity, "session-2"))
        self.assertFalse(adapter_identity.matches_session(identity, 123))  # type: ignore[arg-type]


class IdentityRefusalTests(unittest.TestCase):
    """Named refusals on missing/corrupt environment or command failure."""

    def test_refusal_when_pane_id_unset(self) -> None:
        env = {settings.HERDR_BIN_PATH: "/bin/herdr"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity()
            self.assertIn("HERDR_PANE_ID", caught.exception.reason)

    def test_refusal_when_bin_path_unset(self) -> None:
        env = {settings.HERDR_PANE_ID: "w1:p1"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity()
            self.assertIn("HERDR_BIN_PATH", caught.exception.reason)

    def test_refusal_when_bin_path_empty(self) -> None:
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity()
            self.assertIn("HERDR_BIN_PATH", caught.exception.reason)

    def test_refusal_when_executable_not_found_or_fails(self) -> None:
        fake_run = mock.Mock(side_effect=FileNotFoundError("no such file"))
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/nonexistent",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("Herdr command failed", caught.exception.reason)

    def test_refusal_when_command_times_out(self) -> None:
        fake_run = mock.Mock(
            side_effect=subprocess.TimeoutExpired(
                cmd=["/bin/herdr", "agent", "list"], timeout=2.0
            )
        )
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("timed out", caught.exception.reason)

    def test_refusal_when_output_is_not_json(self) -> None:
        fake_run = mock.Mock(return_value=_FakeCompletedProcess("not json at all"))
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("not valid JSON", caught.exception.reason)

    def test_refusal_when_output_is_not_dict(self) -> None:
        fake_run = mock.Mock(return_value=_FakeCompletedProcess('["agent_list"]'))
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("not a JSON object", caught.exception.reason)

    def test_refusal_when_envelope_type_is_wrong(self) -> None:
        payload = json.dumps({"type": "other_list", "agents": []})
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(payload))
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("expected 'agent_list'", caught.exception.reason)

    def test_refusal_when_agents_is_not_list(self) -> None:
        payload = json.dumps({"type": "agent_list", "agents": {}})
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(payload))
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("'agents' is not a list", caught.exception.reason)

    def test_refusal_when_zero_pane_matches(self) -> None:
        payload = json.dumps(
            {
                "type": "agent_list",
                "agents": [
                    {
                        "pane_id": "other_pane",
                        "terminal_id": "t1",
                        "agent_session": {"value": "s1"},
                    }
                ],
            }
        )
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(payload))
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("no agent matching pane_id 'w1:p1'", caught.exception.reason)

    def test_refusal_when_multiple_pane_matches(self) -> None:
        payload = json.dumps(
            {
                "type": "agent_list",
                "agents": [
                    {
                        "pane_id": "w1:p1",
                        "terminal_id": "t1",
                        "agent_session": {"value": "s1"},
                    },
                    {
                        "pane_id": "w1:p1",
                        "terminal_id": "t2",
                        "agent_session": {"value": "s2"},
                    },
                ],
            }
        )
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(payload))
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
            self.assertIn("multiple (2) agents matching pane_id", caught.exception.reason)

    def test_refusal_when_component_is_missing_or_empty(self) -> None:
        corrupted_cases = [
            ("agent_session is missing", {"pane_id": "w1:p1", "terminal_id": "t1"}),
            ("agent_session is not dict", {"pane_id": "w1:p1", "terminal_id": "t1", "agent_session": "s1"}),
            ("agent_session value is missing", {"pane_id": "w1:p1", "terminal_id": "t1", "agent_session": {}}),
            ("agent_session value is empty", {"pane_id": "w1:p1", "terminal_id": "t1", "agent_session": {"value": ""}}),
            ("terminal_id is missing", {"pane_id": "w1:p1", "agent_session": {"value": "s1"}}),
            ("terminal_id is empty", {"pane_id": "w1:p1", "terminal_id": "   ", "agent_session": {"value": "s1"}}),
            ("pane_id is empty in record", {"pane_id": "", "terminal_id": "t1", "agent_session": {"value": "s1"}}),
        ]
        env = {
            settings.HERDR_PANE_ID: "w1:p1",
            settings.HERDR_BIN_PATH: "/bin/herdr",
        }
        for desc, record in corrupted_cases:
            with self.subTest(case=desc):
                # When pane_id is empty in record, test target_pane_id="" matching
                test_env = dict(env)
                if record.get("pane_id") == "":
                    test_env[settings.HERDR_PANE_ID] = ""
                    # Handled by settings refusal or empty component
                    with mock.patch.dict(os.environ, test_env, clear=True):
                        with self.assertRaises(adapter_identity.IdentityRefusal):
                            adapter_identity.resolve_adapter_identity()
                    continue

                payload = json.dumps({"type": "agent_list", "agents": [record]})
                fake_run = mock.Mock(return_value=_FakeCompletedProcess(payload))
                with mock.patch.dict(os.environ, test_env, clear=True):
                    with self.assertRaises(adapter_identity.IdentityRefusal):
                        adapter_identity.resolve_adapter_identity(run_process=fake_run)


if __name__ == "__main__":
    unittest.main()
