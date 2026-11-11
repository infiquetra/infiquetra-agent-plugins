"""Tests for the delivery path (R16, R17, R18, R19; KTD11).

Every external seam is injected per KTD12 — hc invocations through U1's
subprocess seam, the audible refusal through the speak seam — so no test
runs the real herdr core, types into a real terminal, or synthesizes speech.
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
TERMINAL = "t7"  # the herdr core address stored in the binding at bind time

HELLO_KEYS = ["shift+h", "e", "l", "l", "o", "space", "t", "h", "e", "r", "e"]


def _keys(text: str) -> list[str]:
    """The key names delivery uses for a typable line."""
    return [
        "space"
        if character == " "
        else f"shift+{character.lower()}"
        if character.isupper()
        else character
        for character in text
    ]


def _hc_get_result(
    status: str | None = "idle",
    *,
    address: str = TERMINAL,
    state: str = "live",
) -> subprocess.CompletedProcess:
    """One hc get --json record, shaped like herdr core's output."""
    payload = {
        "address": address,
        "name": AGENT_NAME,
        "state": state,
        "status": None if status is None else {"state": status, "app": "claude"},
        "labels": {"voice.agent-session": SESSION_ID},
        "argv": ["claude"],
    }
    return subprocess.CompletedProcess(
        args=None, returncode=0, stdout=json.dumps(payload), stderr=""
    )


def _keys_result() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=None, returncode=0, stdout=json.dumps({"turn": 3, "status": "idle"}), stderr=""
    )


def _idle_delivery_seam(status: str | None = "idle") -> "_HcSpawnSeam":
    """A read that succeeds, followed by the keys it triggers."""
    return _HcSpawnSeam([_hc_get_result(status), _keys_result()])


class _HcSpawnSeam:
    """Records hc invocations instead of running the CLI (KTD12)."""

    def __init__(self, results) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._results = list(results)

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if not self._results:
            raise AssertionError(f"unexpected hc invocation: {command!r}")
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
        env = mock.patch.dict(
            os.environ,
            {"VOICE_STATE_DIR": str(self.state_dir), "VOICE_HC_BIN": "hc"},
        )
        env.start()
        self.addCleanup(env.stop)
        binding.write_binding(AGENT_NAME, SESSION_ID, TERMINAL)

    def _refused_path(self) -> Path:
        return self.state_dir / deliver.REFUSED_TRANSCRIPT_FILENAME

    def _write_hold(self, text: str) -> None:
        self._refused_path().write_text(text, encoding="utf-8")


class DeliveryPathTests(DeliverTestBase):
    """Delivery re-reads the terminal with hc get and types it with hc keys."""

    def test_delivery_reads_the_bound_terminal_then_types_into_it(self) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(len(spawn.calls), 2)
        get_command, _ = spawn.calls[0]
        self.assertEqual(get_command, ["hc", "get", TERMINAL, "--json"])
        keys_command, _ = spawn.calls[1]
        self.assertEqual(keys_command, ["hc", "keys", TERMINAL, *HELLO_KEYS])

    def test_delivery_is_unsubmitted_literal_text_without_enter(self) -> None:
        # One key per character and no Enter, so the text arrives
        # unsubmitted and editable (R16); no newline survives to reach the
        # terminal as Enter.
        spawn = _idle_delivery_seam()
        deliver.deliver("Deploy the fix", spawn=spawn)
        keys_command, _ = spawn.calls[1]
        self.assertEqual(keys_command[:3], ["hc", "keys", TERMINAL])
        self.assertEqual(keys_command[3:], _keys("Deploy the fix"))
        for name in ("enter", "return", "\n", "\r"):
            self.assertNotIn(name, keys_command)

    def test_the_submitting_send_verb_is_never_invoked(self) -> None:
        # hc send presses Enter and tags text sent from inside a terminal.
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        verbs = [command[1] for command, _ in spawn.calls]
        self.assertEqual(verbs, ["get", "keys"])

    def test_delivery_targets_the_bound_terminal_address_not_the_agent_name(
        self,
    ) -> None:
        # Names can be reused by a later terminal; the address never is.
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        for command, _ in spawn.calls:
            with self.subTest(command=command):
                self.assertEqual(command[2], TERMINAL)
                self.assertNotIn(AGENT_NAME, command)

    def test_only_the_bound_agent_is_ever_targeted(self) -> None:
        # No broadcast, no fallback, no recency inference: exactly one
        # read and one keys call, both keyed to the bound terminal (R17).
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(len(spawn.calls), 2)

    def test_both_hc_calls_carry_the_pinned_deadline_and_closed_stdin(
        self,
    ) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("Hello there", spawn=spawn)
        for command, kwargs in spawn.calls:
            with self.subTest(command=command):
                self.assertEqual(kwargs["timeout"], deliver.HC_TIMEOUT_SECONDS)
                self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(deliver.HC_TIMEOUT_SECONDS, 10.0)

    def test_a_multi_line_transcript_is_delivered_as_one_line(self) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("line one\nline two\r\n  line three\twith tabs", spawn=spawn)
        keys_command, _ = spawn.calls[1]
        self.assertEqual(keys_command[3:], _keys("line one line two line three with tabs"))

    def test_an_empty_transcript_is_refused_by_name_and_calls_no_hc(
        self,
    ) -> None:
        for text in ("", "   ", "\n\t  "):
            with self.subTest(text=text):
                spawn = _HcSpawnSeam([])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver(text, spawn=spawn)
                self.assertEqual(spawn.calls, [])

    def test_delivery_with_no_binding_is_a_named_refusal_and_calls_no_hc(
        self,
    ) -> None:
        (self.state_dir / binding.BINDING_FILENAME).unlink()
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertIn("not bound", str(caught.exception))

    def test_delivery_with_a_corrupt_binding_is_a_named_refusal(self) -> None:
        (self.state_dir / binding.BINDING_FILENAME).write_text(
            "not json", encoding="utf-8"
        )
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertIn("rebind", str(caught.exception))


class UnresolvableAgentTests(DeliverTestBase):
    """An unresolvable bound terminal is a named error, never a fallback (R17)."""

    def test_an_unresolvable_bound_terminal_sends_nothing_anywhere(self) -> None:
        failures = [
            subprocess.CalledProcessError(
                3,
                ["hc", "get", TERMINAL, "--json"],
                "",
                json.dumps({"error": {"kind": "not_found", "message": "no t7"}}),
            ),
            subprocess.TimeoutExpired(
                ["hc", "get", TERMINAL, "--json"],
                deliver.HC_TIMEOUT_SECONDS,
            ),
            FileNotFoundError("hc not found"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                spawn = _HcSpawnSeam([failure])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver("Hello there", spawn=spawn)
                self.assertEqual(
                    len(spawn.calls),
                    1,
                    "the read failed; nothing was typed anywhere else",
                )

    def test_a_malformed_hc_get_response_is_a_named_error(self) -> None:
        payloads = [
            "not json",
            "[]",
            "{}",
            json.dumps({"address": ""}),
            json.dumps({"address": 7, "state": "live"}),
        ]
        for stdout in payloads:
            with self.subTest(stdout=stdout):
                result = subprocess.CompletedProcess(
                    args=None, returncode=0, stdout=stdout, stderr=""
                )
                spawn = _HcSpawnSeam([result])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver("Hello there", spawn=spawn)
                self.assertEqual(len(spawn.calls), 1)

    def test_a_record_for_another_terminal_types_nothing(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result(address="t8")])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(len(spawn.calls), 1)
        self.assertIn("t8", str(caught.exception))

    def test_a_finished_terminal_types_nothing_and_asks_for_a_rebind(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result(state="finished", status=None)])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(len(spawn.calls), 1)
        self.assertIn("finished", str(caught.exception))
        self.assertIn("rebind", str(caught.exception))

    def test_a_failed_keys_call_is_named_and_holds_the_transcript(self) -> None:
        # herdr core's own message rides the refusal, and the transcript is
        # held, so a failed call never loses what the operator said.
        rejected = subprocess.CompletedProcess(
            args=None,
            returncode=6,
            stdout="",
            stderr=json.dumps(
                {"error": {"kind": "invalid_params", "message": "unknown key x"}}
            ),
        )
        spawn = _HcSpawnSeam([_hc_get_result(), rejected])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("ab", spawn=spawn)
        self.assertIn("delivery failed", str(caught.exception))
        self.assertIn("unknown key x", str(caught.exception))
        self.assertEqual(self._refused_path().read_text(encoding="utf-8"), "ab")


class UntypableTranscriptTests(DeliverTestBase):
    """A transcript hc keys cannot type exactly is held whole, never typed."""

    def test_a_question_is_held_spoken_and_never_typed(self) -> None:
        spawn = _HcSpawnSeam([])
        spoken: list[str] = []
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Can you check it?", spawn=spawn, speak_text=spoken.append)
        self.assertEqual(spawn.calls, [], "nothing reaches hc, not even hc get")
        self.assertEqual(spoken, [deliver.UNTYPABLE_REFUSAL_PHRASE])
        self.assertIn("'?'", str(caught.exception))
        self.assertIn("held", str(caught.exception))
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"), "Can you check it?"
        )

    def test_every_untypable_character_is_named_once(self) -> None:
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver(
                "Wow! Really? Yes! café", spawn=spawn, speak_text=lambda phrase: None
            )
        message = str(caught.exception)
        for character in ("'!'", "'?'", "'é'"):
            self.assertEqual(message.count(character), 1, character)

    def test_a_leading_slash_is_held_because_it_opens_the_command_menu(self) -> None:
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("/clear the cache", spawn=spawn, speak_text=lambda phrase: None)
        self.assertEqual(spawn.calls, [])
        self.assertIn("command menu", str(caught.exception))
        self.assertTrue(self._refused_path().exists())

    def test_a_slash_inside_the_transcript_is_typed(self) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("and/or", spawn=spawn)
        keys_command, _ = spawn.calls[1]
        self.assertEqual(keys_command[3:], ["a", "n", "d", "/", "o", "r"])

    def test_capitals_are_typed_with_shift(self) -> None:
        spawn = _idle_delivery_seam()
        deliver.deliver("I am OK", spawn=spawn)
        keys_command, _ = spawn.calls[1]
        self.assertEqual(
            keys_command[3:],
            ["shift+i", "space", "a", "m", "space", "shift+o", "shift+k"],
        )

    def test_the_hold_survives_when_speech_fails(self) -> None:
        refusal = providers.ProviderRefusal(providers.VOICE_FORGE, "synthesis unreachable")
        with self.assertRaises(providers.ProviderRefusal):
            deliver.deliver(
                "Ready?",
                spawn=_HcSpawnSeam([]),
                speak_text=mock.Mock(side_effect=refusal),
            )
        self.assertEqual(self._refused_path().read_text(encoding="utf-8"), "Ready?")

    def test_use_refused_on_an_untypable_hold_keeps_it(self) -> None:
        self._write_hold("Ready?")
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn, speak_text=lambda phrase: None)
        self.assertEqual(spawn.calls, [])
        self.assertEqual(self._refused_path().read_text(encoding="utf-8"), "Ready?")


class BlockedRefusalTests(DeliverTestBase):
    """A blocked agent receives nothing; the refusal is audible (R18)."""

    def test_a_blocked_agent_receives_no_text_and_the_refusal_is_spoken(
        self,
    ) -> None:
        spawn = _HcSpawnSeam([_hc_get_result("blocked")])
        spoken: list[str] = []
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver(
                "Approve the deploy", spawn=spawn, speak_text=spoken.append
            )
        self.assertEqual(len(spawn.calls), 1, "a blocked agent is never sent text")
        get_command, _ = spawn.calls[0]
        self.assertEqual(get_command[:2], ["hc", "get"])
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
        spawn = _HcSpawnSeam(
            [
                _hc_get_result("blocked"),
                _hc_get_result("blocked"),
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
        spawn = _HcSpawnSeam([_hc_get_result("blocked")])
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
        # Only blocked withholds delivery; every other status word herdr
        # core reports, and no status at all, delivers.
        for agent_status in ("idle", "working", "done", "error", None):
            with self.subTest(agent_status=agent_status):
                spawn = _idle_delivery_seam(agent_status)
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
        keys_command, _ = spawn.calls[1]
        self.assertEqual(keys_command[3:], _keys("Approve the deploy"))
        self.assertFalse(self._refused_path().exists())

    def test_use_refused_with_no_hold_is_refused_by_name_and_calls_no_hc(
        self,
    ) -> None:
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn)
        self.assertEqual(spawn.calls, [])

    def test_use_refused_on_a_still_blocked_agent_refuses_and_holds_again(
        self,
    ) -> None:
        self._write_hold("Approve the deploy")
        spawn = _HcSpawnSeam([_hc_get_result("blocked")])
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
                ["hc", "keys", TERMINAL, *_keys(text)],
                deliver.HC_TIMEOUT_SECONDS,
            ),
            subprocess.CalledProcessError(
                11,
                ["hc", "keys", TERMINAL, *_keys(text)],
                "",
                json.dumps({"error": {"kind": "finished", "message": "t7 finished"}}),
            ),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                self._write_hold(text)
                spawn = _HcSpawnSeam([_hc_get_result(), failure])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.use_refused(spawn=spawn)
                self.assertEqual(
                    self._refused_path().read_text(encoding="utf-8"),
                    text,
                )

    def test_use_refused_keeps_the_hold_when_the_binding_is_gone(self) -> None:
        # An unbound agent refuses the delivery before any hc call; the
        # hold read just before must survive that refusal (F02).
        self._write_hold("Approve the deploy")
        (self.state_dir / binding.BINDING_FILENAME).unlink()
        spawn = _HcSpawnSeam([])
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
        keys_command, _ = spawn.calls[1]
        self.assertEqual(keys_command[3:], _keys("Something new"))
        self.assertEqual(
            self._refused_path().read_text(encoding="utf-8"),
            "Approve the deploy",
        )


if __name__ == "__main__":
    unittest.main()
