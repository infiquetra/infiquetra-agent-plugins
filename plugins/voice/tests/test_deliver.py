"""Tests for the delivery path (R16, R17, R18, R19; KTD11).

Every external seam is injected per KTD12 — herdr invocations through U1's
subprocess seam, the audible refusal through the speak seam — so no test
runs the real herdr CLI, sends text to a real pane, or synthesizes speech.
The state directory points at a temp dir for the same reason.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import binding  # noqa: E402
import deliver  # noqa: E402
import providers  # noqa: E402

AGENT_NAME = "test-agent"
SESSION_ID = "test-session-id"
BOUND_PANE_ID = "wTEST:p1"  # the pane id stored in the binding at bind time
LIVE_PANE_ID = "wTEST:p9"  # the pane id herdr re-resolves at send time


def _agent_get_result(
    agent_status: str = "idle",
    pane_id: str = LIVE_PANE_ID,
    name: str = AGENT_NAME,
) -> subprocess.CompletedProcess:
    """One herdr agent get envelope, shaped like the installed CLI's output."""
    payload = {
        "id": "cli:agent:get",
        "result": {
            "agent": {
                "agent": "claude",
                "agent_session": {
                    "agent": "claude",
                    "kind": "id",
                    "source": "herdr:claude",
                    "value": SESSION_ID,
                },
                "agent_status": agent_status,
                "name": name,
                "pane_id": pane_id,
            },
            "type": "agent_info",
        },
    }
    return subprocess.CompletedProcess(
        args=None, returncode=0, stdout=json.dumps(payload), stderr=""
    )


def _send_text_result() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=None, returncode=0, stdout="", stderr="")


def _idle_delivery_seam(agent_status: str = "idle") -> "_HerdrSpawnSeam":
    """A resolution that succeeds, followed by the send it triggers."""
    return _HerdrSpawnSeam([_agent_get_result(agent_status=agent_status), _send_text_result()])


class _HerdrSpawnSeam:
    """Records herdr invocations instead of running the CLI (KTD12)."""

    def __init__(self, results) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._results = list(results)

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if not self._results:
            raise AssertionError(f"unexpected herdr invocation: {command!r}")
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if kwargs.get("check") and result.returncode:
            raise subprocess.CalledProcessError(
                result.returncode, command, result.stdout, result.stderr
            )
        return result


class DeliverTestBase(unittest.TestCase):
    """Shared fixture: a temp state dir and one bound agent (inert values)."""

    def setUp(self) -> None:
        state = tempfile.TemporaryDirectory()
        self.addCleanup(state.cleanup)
        self.state_dir = Path(state.name)
        env = mock.patch.dict(os.environ, {"VOICE_STATE_DIR": str(self.state_dir)})
        env.start()
        self.addCleanup(env.stop)
        binding.write_binding(AGENT_NAME, SESSION_ID, BOUND_PANE_ID)

    def _refused_path(self) -> Path:
        return self.state_dir / deliver.REFUSED_TRANSCRIPT_FILENAME

    def _write_hold(self, text: str) -> None:
        self._refused_path().write_text(text, encoding="utf-8")


class DeliveryPathTests(DeliverTestBase):
    """Delivery resolves through herdr agent get and sends with send-text."""

    def test_delivery_resolves_the_bound_agent_with_agent_get_then_sends(
        self,
    ) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(len(spawn.calls), 2)
        get_command, _ = spawn.calls[0]
        self.assertEqual(get_command, ["herdr", "agent", "get", AGENT_NAME])
        send_command, _ = spawn.calls[1]
        self.assertEqual(
            send_command,
            ["herdr", "pane", "send-text", LIVE_PANE_ID, "Hello there"],
        )

    def test_delivery_is_unsubmitted_literal_text_without_enter(self) -> None:
        # send-text sends literal text with no Enter appended, so the text
        # arrives unsubmitted and editable (R16); no newline survives to
        # reach the terminal as Enter.
        spawn = _idle_delivery_seam()
        deliver.deliver("Deploy the fix", spawn=spawn)
        send_command, _ = spawn.calls[1]
        self.assertEqual(send_command[:3], ["herdr", "pane", "send-text"])
        self.assertEqual(send_command[4], "Deploy the fix")
        self.assertNotIn("\n", send_command[4])

    def test_the_submitting_pane_verb_is_never_invoked(self) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        pane_verbs = [
            command[2]
            for command, _ in spawn.calls
            if command[:2] == ["herdr", "pane"]
        ]
        self.assertEqual(pane_verbs, ["send-text"])

    def test_delivery_targets_the_freshly_resolved_pane_not_the_stored_copy(
        self,
    ) -> None:
        # The binding stores one pane id; herdr agent get re-resolves another
        # at send time, and delivery follows the fresh resolution (KTD7).
        self.assertNotEqual(LIVE_PANE_ID, BOUND_PANE_ID)
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        send_command, _ = spawn.calls[1]
        self.assertEqual(send_command[3], LIVE_PANE_ID)

    def test_only_the_bound_agent_is_ever_targeted(self) -> None:
        # No broadcast, no fallback, no recency inference: exactly one
        # resolution and one send, both keyed to the bound agent (R17).
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        get_command, _ = spawn.calls[0]
        self.assertEqual(get_command[3], AGENT_NAME)
        self.assertEqual(len(spawn.calls), 2)

    def test_both_herdr_calls_carry_the_pinned_deadline_and_closed_stdin(
        self,
    ) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        for command, kwargs in spawn.calls:
            with self.subTest(command=command):
                self.assertEqual(kwargs["timeout"], deliver.HERDR_TIMEOUT_SECONDS)
                self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(deliver.HERDR_TIMEOUT_SECONDS, 10.0)

    def test_a_multi_line_transcript_is_delivered_as_one_line(self) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("line one\nline two\r\n  line three\twith tabs", spawn=spawn)
        send_command, _ = spawn.calls[1]
        self.assertEqual(send_command[4], "line one line two line three with tabs")

    def test_an_empty_transcript_is_refused_by_name_and_calls_no_herdr(
        self,
    ) -> None:
        for text in ("", "   ", "\n\t  "):
            with self.subTest(text=text):
                spawn = _HerdrSpawnSeam([])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver(text, spawn=spawn)
                self.assertEqual(spawn.calls, [])

    def test_delivery_with_no_binding_is_a_named_refusal_and_calls_no_herdr(
        self,
    ) -> None:
        (self.state_dir / binding.BINDING_FILENAME).unlink()
        spawn = _HerdrSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertIn("not bound", str(caught.exception))

    def test_delivery_with_a_corrupt_binding_is_a_named_refusal(self) -> None:
        (self.state_dir / binding.BINDING_FILENAME).write_text(
            "not json", encoding="utf-8"
        )
        spawn = _HerdrSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertIn("rebind", str(caught.exception))


class UnresolvableAgentTests(DeliverTestBase):
    """An unresolvable bound agent is a named error, never a fallback (R17)."""

    def test_an_unresolvable_bound_agent_sends_nothing_anywhere(self) -> None:
        failures = [
            subprocess.CalledProcessError(
                1, ["herdr", "agent", "get", AGENT_NAME], "", "no such agent"
            ),
            subprocess.TimeoutExpired(
                ["herdr", "agent", "get", AGENT_NAME],
                deliver.HERDR_TIMEOUT_SECONDS,
            ),
            FileNotFoundError("herdr not found"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                spawn = _HerdrSpawnSeam([failure])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver("Hello there", spawn=spawn)
                self.assertEqual(
                    len(spawn.calls),
                    1,
                    "the resolution failed; nothing was sent anywhere else",
                )

    def test_a_malformed_agent_get_response_is_a_named_error(self) -> None:
        payloads = [
            "not json",
            "[]",
            "{}",
            json.dumps({"result": {}}),
            json.dumps({"result": {"agent": None}}),
            json.dumps({"result": {"agent": {"pane_id": LIVE_PANE_ID}}}),
            json.dumps({"result": {"agent": {"agent_status": "idle"}}}),
            json.dumps(
                {"result": {"agent": {"pane_id": 42, "agent_status": "idle"}}}
            ),
            json.dumps(
                {"result": {"agent": {"pane_id": "  ", "agent_status": "idle"}}}
            ),
        ]
        for stdout in payloads:
            with self.subTest(stdout=stdout):
                result = subprocess.CompletedProcess(
                    args=None, returncode=0, stdout=stdout, stderr=""
                )
                spawn = _HerdrSpawnSeam([result])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver("Hello there", spawn=spawn)
                self.assertEqual(len(spawn.calls), 1)


class BlockedRefusalTests(DeliverTestBase):
    """A blocked agent receives nothing; the refusal is audible (R18)."""

    def test_a_blocked_agent_receives_no_text_and_the_refusal_is_spoken(
        self,
    ) -> None:
        spawn = _HerdrSpawnSeam([_agent_get_result(agent_status="blocked")])
        spoken: list[str] = []
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver(
                "Approve the deploy", spawn=spawn, speak_text=spoken.append
            )
        self.assertEqual(len(spawn.calls), 1, "a blocked agent is never sent text")
        get_command, _ = spawn.calls[0]
        self.assertEqual(get_command[:3], ["herdr", "agent", "get"])
        self.assertEqual(spoken, [deliver.BLOCKED_REFUSAL_PHRASE])
        self.assertIn("blocked", str(caught.exception))
        # The transcript is held for the operator's explicit use or discard.
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"),
            "Approve the deploy",
        )

    def test_a_second_blocked_refusal_replaces_the_hold_and_never_appends(
        self,
    ) -> None:
        # One current file, never appended, so the hold is not a transcript
        # log (KTD1): a second refusal replaces the first held transcript.
        spawn = _HerdrSpawnSeam(
            [
                _agent_get_result(agent_status="blocked"),
                _agent_get_result(agent_status="blocked"),
            ]
        )
        for text in ("first transcript", "second transcript"):
            with self.assertRaises(deliver.DeliveryRefusal):
                deliver.deliver(text, spawn=spawn, speak_text=lambda phrase: None)
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"),
            "second transcript",
        )

    def test_a_blocked_refusal_holds_the_transcript_even_when_speech_fails(
        self,
    ) -> None:
        spawn = _HerdrSpawnSeam([_agent_get_result(agent_status="blocked")])
        refusal = providers.ProviderRefusal(
            providers.VOICE_FORGE, "synthesis unreachable"
        )
        with self.assertRaises(providers.ProviderRefusal):
            deliver.deliver(
                "Approve the deploy",
                spawn=spawn,
                speak_text=mock.Mock(side_effect=refusal),
            )
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"),
            "Approve the deploy",
        )

    def test_states_other_than_blocked_still_deliver(self) -> None:
        # Only blocked withholds delivery; every other state in the closed
        # set delivers.
        for agent_status in ("idle", "working", "done", "unknown"):
            with self.subTest(agent_status=agent_status):
                spawn = _idle_delivery_seam(agent_status=agent_status)
                deliver.deliver("Hello there", spawn=spawn)
                self.assertEqual(len(spawn.calls), 2)
                self.assertFalse(self._refused_path().exists())


class RefusedHoldTests(DeliverTestBase):
    """The refused transcript is transient: explicit use or discard only (R19)."""

    def test_use_refused_delivers_once_and_clears_the_hold(self) -> None:
        self._write_hold("Approve the deploy")
        spawn = _idle_delivery_seam()
        deliver.use_refused(spawn=spawn)
        self.assertEqual(len(spawn.calls), 2)
        send_command, _ = spawn.calls[1]
        self.assertEqual(send_command[4], "Approve the deploy")
        self.assertFalse(self._refused_path().exists())

    def test_use_refused_with_no_hold_is_refused_by_name_and_calls_no_herdr(
        self,
    ) -> None:
        spawn = _HerdrSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn)
        self.assertEqual(spawn.calls, [])

    def test_use_refused_on_a_still_blocked_agent_refuses_and_holds_again(
        self,
    ) -> None:
        self._write_hold("Approve the deploy")
        spawn = _HerdrSpawnSeam([_agent_get_result(agent_status="blocked")])
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn, speak_text=lambda phrase: None)
        self.assertEqual(len(spawn.calls), 1, "a blocked agent is never sent text")
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"),
            "Approve the deploy",
        )

    def test_use_refused_keeps_the_hold_when_the_send_fails(self) -> None:
        # The hold is deleted only after a successful send: a send that
        # times out or fails after the read must not consume the only
        # remaining copy of the refused transcript (F02).
        text = "Approve the deploy"
        failures = [
            subprocess.TimeoutExpired(
                ["herdr", "pane", "send-text", LIVE_PANE_ID, text],
                deliver.HERDR_TIMEOUT_SECONDS,
            ),
            subprocess.CalledProcessError(
                1,
                ["herdr", "pane", "send-text", LIVE_PANE_ID, text],
                "",
                "pane gone",
            ),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self._write_hold(text)
                spawn = _HerdrSpawnSeam([_agent_get_result(), failure])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.use_refused(spawn=spawn)
                self.assertEqual(
                    self._refused_path().read_text(encoding="utf-8"),
                    text,
                )

    def test_use_refused_keeps_the_hold_when_the_binding_is_gone(self) -> None:
        # An unbound agent refuses the delivery before any herdr call; the
        # hold read just before must survive that refusal (F02).
        self._write_hold("Approve the deploy")
        (self.state_dir / binding.BINDING_FILENAME).unlink()
        spawn = _HerdrSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"),
            "Approve the deploy",
        )

    def test_discard_refused_deletes_the_hold_without_sending(self) -> None:
        self._write_hold("Approve the deploy")
        deliver.discard_refused()
        self.assertFalse(self._refused_path().exists())

    def test_discard_refused_with_no_hold_is_refused_by_name(self) -> None:
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.discard_refused()

    def test_a_held_transcript_is_never_auto_delivered_by_a_later_delivery(
        self,
    ) -> None:
        # A later delivery of a fresh transcript leaves the hold untouched:
        # never delivered automatically, never queued, never implicitly
        # discarded (R19).
        self._write_hold("Approve the deploy")
        spawn = _idle_delivery_seam()
        deliver.deliver("Something new", spawn=spawn)
        send_command, _ = spawn.calls[1]
        self.assertEqual(send_command[4], "Something new")
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"),
            "Approve the deploy",
        )


if __name__ == "__main__":
    unittest.main()
