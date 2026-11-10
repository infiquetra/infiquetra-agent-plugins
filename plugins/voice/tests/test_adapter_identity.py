"""Tests for the adapter identity resolver (KTD9; §5).

Exercises the Section 5 identity rule as voice now meets it through herdr
core: the happy path, environment failures, command failures and timeouts,
malformed records, a finished terminal, an address mismatch, and a missing
or empty session label. ``hc`` is never run: every call goes through the
injected ``run_process`` seam.
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

TERMINAL = "t42"
SESSION = "session-abc-123"


class _FakeCompletedProcess:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout


def _record_json(
    *,
    address: str = TERMINAL,
    session_id: str | None = SESSION,
    state: str = "live",
) -> str:
    labels = {} if session_id is None else {"voice.agent-session": session_id}
    return json.dumps(
        {
            "address": address,
            "state": state,
            "labels": labels,
            "status": {"state": "idle"},
        }
    )


def _env(**overrides: str) -> dict[str, str]:
    env = {settings.HC_TERMINAL_ID: TERMINAL, settings.HC_BIN: "/opt/example/hc"}
    env.update(overrides)
    return env


class AdapterIdentityTests(unittest.TestCase):
    """Happy path and structure tests for AdapterIdentity."""

    def test_happy_path_resolves_three_components_exactly(self) -> None:
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(_record_json()))
        with mock.patch.dict(os.environ, _env(), clear=True):
            identity = adapter_identity.resolve_adapter_identity(run_process=fake_run)

        self.assertEqual(identity.agent_session_id, SESSION)
        self.assertEqual(identity.pane_id, TERMINAL)
        self.assertEqual(identity.terminal_id, TERMINAL)
        self.assertEqual(
            identity.to_dict(),
            {
                "agent_session_id": SESSION,
                "pane_id": TERMINAL,
                "terminal_id": TERMINAL,
            },
        )
        fake_run.assert_called_once_with(
            ["/opt/example/hc", "get", TERMINAL, "--json"],
            timeout=adapter_identity.HC_TIMEOUT_SECONDS,
            check=True,
        )
        self.assertEqual(adapter_identity.HC_TIMEOUT_SECONDS, 2.0)

    def test_the_herdr_core_command_defaults_to_hc(self) -> None:
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(_record_json()))
        with mock.patch.dict(os.environ, {settings.HC_TERMINAL_ID: TERMINAL}, clear=True):
            adapter_identity.resolve_adapter_identity(run_process=fake_run)
        self.assertEqual(fake_run.call_args.args[0][0], "hc")

    def test_the_session_id_is_copied_byte_exact(self) -> None:
        # Bridge identifiers are never trimmed or normalized (§4.9).
        odd = " session-with-edges "
        fake_run = mock.Mock(
            return_value=_FakeCompletedProcess(_record_json(session_id=odd))
        )
        with mock.patch.dict(os.environ, _env(), clear=True):
            identity = adapter_identity.resolve_adapter_identity(run_process=fake_run)
        self.assertEqual(identity.agent_session_id, odd)

    def test_old_herdr_variables_are_never_read(self) -> None:
        fake_run = mock.Mock()
        env = {"HERDR_PANE_ID": "w1:p1", "HERDR_BIN_PATH": "/bin/herdr"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
        self.assertIn("HC_TERMINAL_ID", caught.exception.reason)
        fake_run.assert_not_called()

    def test_matches_session_verification(self) -> None:
        identity = adapter_identity.AdapterIdentity(
            agent_session_id="session-1",
            pane_id="t1",
            terminal_id="t1",
        )
        self.assertTrue(adapter_identity.matches_session(identity, "session-1"))
        self.assertFalse(adapter_identity.matches_session(identity, "session-2"))
        self.assertFalse(adapter_identity.matches_session(identity, 123))  # type: ignore[arg-type]


class IdentityRefusalTests(unittest.TestCase):
    """Named refusals on missing or corrupt environment, command, or record."""

    def _refuse(self, stdout: str | None = None, **env_overrides: str) -> str:
        fake_run = mock.Mock(return_value=_FakeCompletedProcess(stdout or _record_json()))
        with mock.patch.dict(os.environ, _env(**env_overrides), clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
        return caught.exception.reason

    def test_refusal_when_terminal_id_unset(self) -> None:
        with mock.patch.dict(os.environ, {settings.HC_BIN: "hc"}, clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=mock.Mock())
        self.assertIn("HC_TERMINAL_ID", caught.exception.reason)

    def test_refusal_when_terminal_id_or_command_empty(self) -> None:
        self.assertIn("HC_TERMINAL_ID", self._refuse(**{settings.HC_TERMINAL_ID: ""}))
        self.assertIn("VOICE_HC_BIN", self._refuse(**{settings.HC_BIN: "  "}))

    def test_refusal_when_command_fails_or_cannot_start(self) -> None:
        failures = [
            FileNotFoundError("no such file"),
            PermissionError("permission denied"),
            subprocess.CalledProcessError(
                3,
                ["hc"],
                output="",
                stderr=json.dumps({"error": {"kind": "not_found", "message": "no t42"}}),
            ),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                fake_run = mock.Mock(side_effect=failure)
                with mock.patch.dict(os.environ, _env(), clear=True):
                    with self.assertRaises(adapter_identity.IdentityRefusal):
                        adapter_identity.resolve_adapter_identity(run_process=fake_run)

    def test_refusal_when_command_times_out(self) -> None:
        fake_run = mock.Mock(side_effect=subprocess.TimeoutExpired(["hc"], 2.0))
        with mock.patch.dict(os.environ, _env(), clear=True):
            with self.assertRaises(adapter_identity.IdentityRefusal) as caught:
                adapter_identity.resolve_adapter_identity(run_process=fake_run)
        self.assertIn("deadline", caught.exception.reason)

    def test_refusal_when_output_is_not_a_terminal_record(self) -> None:
        for stdout in (
            "not json",
            "[]",
            json.dumps({"state": "live"}),
            json.dumps({"address": ""}),
        ):
            with self.subTest(stdout=stdout):
                self._refuse(stdout)

    def test_refusal_when_the_record_is_for_another_terminal(self) -> None:
        reason = self._refuse(_record_json(address="t43"))
        self.assertIn("t43", reason)

    def test_refusal_when_the_terminal_is_finished(self) -> None:
        reason = self._refuse(_record_json(state="finished"))
        self.assertIn("not live", reason)

    def test_refusal_when_the_session_label_is_missing_or_empty(self) -> None:
        for session_id in (None, "", "   "):
            with self.subTest(session_id=session_id):
                reason = self._refuse(_record_json(session_id=session_id))
                self.assertIn("voice.agent-session", reason)

    def test_refusal_never_falls_back_to_another_label(self) -> None:
        stdout = json.dumps(
            {
                "address": TERMINAL,
                "state": "live",
                "labels": {"herdr.agentSession": SESSION},
            }
        )
        self._refuse(stdout)


if __name__ == "__main__":
    unittest.main()
