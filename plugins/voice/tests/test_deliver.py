"""Tests for the delivery path (R16, R17, R18, R19; KTD11).

Every external seam is injected per KTD12 — ``hc get`` through U1's
subprocess seam, the paste through a scripted ``hc connect`` conversation,
the audible refusal through the speak seam — so no test runs the real herdr
core, pastes into a real terminal, or synthesizes speech. The state
directory points at a temp dir for the same reason.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

import binding  # noqa: E402
import deliver  # noqa: E402
import providers  # noqa: E402
from hc_stub import FakeConversation, attach_server  # noqa: E402

AGENT_NAME = "test-agent"
SESSION_ID = "test-session-id"
TERMINAL = "t7"  # the herdr core address stored in the binding at bind time


def _pasted(text: str) -> bytes:
    """The one input payload a delivery of ``text`` sends."""
    return b"\x1b[200~" + text.encode("utf-8") + b"\x1b[201~"


def _hc_get_result(
    status: str | None = "idle",
    *,
    address: str = TERMINAL,
    state: str = "live",
    turn: int = 3,
    msg: str | None = None,
    cols: int | None = 160,
    rows: int | None = 48,
) -> subprocess.CompletedProcess:
    """One hc get --json record, shaped like herdr core's output."""
    reported = None if status is None else {"state": status, "app": "claude"}
    if reported is not None and msg is not None:
        reported["msg"] = msg
    payload = {
        "address": address,
        "name": AGENT_NAME,
        "state": state,
        "status": reported,
        "turn": turn,
        "labels": {"voice.agent-session": SESSION_ID},
        "argv": ["claude"],
    }
    if cols is not None:
        payload["cols"] = cols
    if rows is not None:
        payload["rows"] = rows
    return subprocess.CompletedProcess(
        args=None, returncode=0, stdout=json.dumps(payload), stderr=""
    )


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


def _settled_seams(
    before=None, after=None, **server
) -> tuple[_HcSpawnSeam, FakeConversation]:
    """A settled read, a paste the scripted core accepts, and a settled read back."""
    spawn = _HcSpawnSeam([before or _hc_get_result(), after or _hc_get_result()])
    return spawn, FakeConversation(attach_server(terminal=TERMINAL, **server))


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

    def _held(self) -> str | None:
        path = self._refused_path()
        return path.read_text(encoding="utf-8") if path.exists() else None


class DeliveryPathTests(DeliverTestBase):
    """Read, paste through an attach, read back; never submit."""

    def test_delivery_reads_pastes_and_reads_back(self) -> None:
        spawn, talk = _settled_seams()
        deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertEqual(
            [command for command, _ in spawn.calls],
            [["hc", "get", TERMINAL, "--json"], ["hc", "get", TERMINAL, "--json"]],
        )
        self.assertEqual(talk.argv, ["hc", "connect"])
        self.assertEqual(talk.pastes(), [_pasted("Hello there")])

    def test_the_attach_uses_the_size_hc_get_reported(self) -> None:
        # Attaching at any other size would resize the operator's terminal.
        spawn, talk = _settled_seams(before=_hc_get_result(cols=211, rows=57))
        deliver.deliver("Hello there", spawn=spawn, converse=talk)
        params = json.loads(talk.client_frames()[0][2])["params"]
        self.assertEqual((params["cols"], params["rows"]), (211, 57))
        self.assertIs(params["observe"], False)

    def test_a_missing_size_holds_the_transcript_and_attaches_nothing(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result(cols=None)])
        talk = FakeConversation(attach_server())
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertNotIsInstance(caught.exception, deliver.DeliveryUncertain)
        self.assertFalse(talk.called)
        self.assertEqual(self._held(), "Hello there")

    def test_a_spoken_question_is_delivered_intact(self) -> None:
        # The reason for the paste: hc keys could type none of these.
        text = 'Can you check it? Yes! Use "main": 50% (not 40%) & café 漢字'
        spawn, talk = _settled_seams()
        deliver.deliver(text, spawn=spawn, converse=talk)
        self.assertEqual(talk.pastes(), [_pasted(text)])

    def test_delivery_is_unsubmitted_and_never_uses_send_or_keys(self) -> None:
        spawn, talk = _settled_seams()
        deliver.deliver("Deploy the fix", spawn=spawn, converse=talk)
        (payload,) = talk.pastes()
        self.assertNotIn(b"\r", payload)
        self.assertNotIn(b"\n", payload)
        verbs = [command[1] for command, _ in spawn.calls] + [talk.argv[1]]
        self.assertEqual(verbs, ["get", "get", "connect"])

    def test_a_multi_line_transcript_is_delivered_as_one_line(self) -> None:
        spawn, talk = _settled_seams()
        deliver.deliver(
            "line one\nline two\r\n  line three\twith tabs", spawn=spawn, converse=talk
        )
        self.assertEqual(talk.pastes(), [_pasted("line one line two line three with tabs")])

    def test_control_characters_never_reach_the_paste(self) -> None:
        spawn, talk = _settled_seams()
        deliver.deliver("stop\x1b[201~ here\x07\x9b", spawn=spawn, converse=talk)
        self.assertEqual(talk.pastes(), [_pasted("stop[201~ here")])

    def test_delivery_targets_the_bound_terminal_address_not_the_agent_name(
        self,
    ) -> None:
        # Names can be reused by a later terminal; the address never is.
        spawn, talk = _settled_seams()
        deliver.deliver("Hello there", spawn=spawn, converse=talk)
        for command, _ in spawn.calls:
            self.assertEqual(command[2], TERMINAL)
        self.assertEqual(json.loads(talk.client_frames()[0][2])["params"]["terminal"], TERMINAL)

    def test_every_hc_call_carries_the_pinned_deadline(self) -> None:
        spawn, talk = _settled_seams()
        deliver.deliver("Hello there", spawn=spawn, converse=talk)
        for command, kwargs in spawn.calls:
            with self.subTest(command=command):
                self.assertEqual(kwargs["timeout"], deliver.HC_TIMEOUT_SECONDS)
                self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(talk.timeout, deliver.HC_TIMEOUT_SECONDS)
        self.assertEqual(deliver.HC_TIMEOUT_SECONDS, 10.0)

    def test_an_empty_transcript_is_refused_by_name_and_calls_no_hc(self) -> None:
        for text in ("", "   ", "\n\t  ", "\x1b\x07"):
            with self.subTest(text=text):
                spawn = _HcSpawnSeam([])
                talk = FakeConversation(b"")
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver(text, spawn=spawn, converse=talk)
                self.assertEqual(spawn.calls, [])
                self.assertFalse(talk.called)

    def test_delivery_with_no_binding_is_a_named_refusal_and_calls_no_hc(self) -> None:
        (self.state_dir / binding.BINDING_FILENAME).unlink()
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertIn("not bound", str(caught.exception))

    def test_delivery_with_a_corrupt_binding_is_a_named_refusal(self) -> None:
        (self.state_dir / binding.BINDING_FILENAME).write_text("not json", encoding="utf-8")
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertIn("rebind", str(caught.exception))


class CommandPrefixTests(DeliverTestBase):
    """A transcript Claude Code would run as a command is held, never pasted."""

    def test_a_leading_slash_or_bang_is_held_and_spoken(self) -> None:
        for text in ("/clear the cache", "!rm -rf build"):
            with self.subTest(text=text):
                spawn = _HcSpawnSeam([])
                talk = FakeConversation(attach_server())
                spoken: list[str] = []
                with self.assertRaises(deliver.DeliveryRefusal) as caught:
                    deliver.deliver(text, spawn=spawn, converse=talk, speak_text=spoken.append)
                self.assertEqual(spawn.calls, [])
                self.assertFalse(talk.called)
                self.assertEqual(spoken, [deliver.COMMAND_REFUSAL_PHRASE])
                self.assertIn("command", str(caught.exception))
                self.assertEqual(self._held(), text)

    def test_a_slash_or_bang_inside_the_transcript_is_pasted(self) -> None:
        spawn, talk = _settled_seams()
        deliver.deliver("and/or, really!", spawn=spawn, converse=talk)
        self.assertEqual(talk.pastes(), [_pasted("and/or, really!")])


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
            subprocess.TimeoutExpired(["hc", "get", TERMINAL, "--json"], deliver.HC_TIMEOUT_SECONDS),
            FileNotFoundError("hc not found"),
        ]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                spawn = _HcSpawnSeam([failure])
                talk = FakeConversation(attach_server())
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver("Hello there", spawn=spawn, converse=talk)
                self.assertEqual(len(spawn.calls), 1)
                self.assertFalse(talk.called, "nothing was pasted anywhere else")

    def test_a_malformed_hc_get_response_is_a_named_error(self) -> None:
        for stdout in ("not json", "[]", "{}", json.dumps({"address": ""})):
            with self.subTest(stdout=stdout):
                result = subprocess.CompletedProcess(args=None, returncode=0, stdout=stdout, stderr="")
                spawn = _HcSpawnSeam([result])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.deliver("Hello there", spawn=spawn, converse=FakeConversation(b""))
                self.assertEqual(len(spawn.calls), 1)

    def test_a_record_for_another_terminal_pastes_nothing(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result(address="t8")])
        talk = FakeConversation(attach_server())
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertFalse(talk.called)
        self.assertIn("t8", str(caught.exception))

    def test_a_finished_terminal_pastes_nothing_and_asks_for_a_rebind(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result(state="finished", status=None)])
        talk = FakeConversation(attach_server())
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertFalse(talk.called)
        self.assertIn("rebind", str(caught.exception))


class PasteFailureTests(DeliverTestBase):
    """A paste that was not sent holds the transcript; one that was is reported."""

    def test_a_program_without_bracketed_paste_holds_the_transcript(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result()])
        talk = FakeConversation(attach_server(paint=b"\x1b[?2004l> "))
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertNotIsInstance(caught.exception, deliver.DeliveryUncertain)
        self.assertIn("bracketed paste", str(caught.exception))
        self.assertEqual(talk.pastes(), [])
        self.assertEqual(self._held(), "Hello there")

    def test_a_refused_attach_holds_the_transcript(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result()])
        talk = FakeConversation(attach_server(attach_error={"message": "finished"}))
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertIn("nothing was pasted", str(caught.exception))
        self.assertEqual(self._held(), "Hello there")

    def test_a_paste_that_was_sent_but_not_closed_is_reported_not_held(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result()])
        talk = FakeConversation(attach_server(close_echo=False))
        spoken: list[str] = []
        with self.assertRaises(deliver.DeliveryUncertain) as caught:
            deliver.deliver("Hello there", spawn=spawn, converse=talk, speak_text=spoken.append)
        self.assertIn("may have reached a prompt", str(caught.exception))
        self.assertEqual(spoken, [deliver.UNCERTAIN_DELIVERY_PHRASE])
        self.assertIsNone(self._held(), "a sent paste is never held, so never sent twice")


class AfterPasteTests(DeliverTestBase):
    """A change around the paste is reported; Enter is never pressed."""

    def _uncertain(self, spawn, talk) -> tuple[str, list[str]]:
        spoken: list[str] = []
        with self.assertRaises(deliver.DeliveryUncertain) as caught:
            deliver.deliver("yes 1", spawn=spawn, converse=talk, speak_text=spoken.append)
        for payload in talk.pastes():
            self.assertNotIn(b"\r", payload)
        return str(caught.exception), spoken

    def test_a_dialog_seen_when_the_paste_attached_is_reported(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result()])
        talk = FakeConversation(attach_server(status="blocked", msg="Allow Bash?"))
        message, spoken = self._uncertain(spawn, talk)
        self.assertIn("'blocked' when the paste attached (Allow Bash?)", message)
        self.assertEqual(spoken, [deliver.UNCERTAIN_DELIVERY_PHRASE])
        self.assertEqual(len(spawn.calls), 1, "the attach reply already showed it")

    def test_a_dialog_seen_on_the_read_back_names_its_question(self) -> None:
        spawn, talk = _settled_seams(
            after=_hc_get_result("blocked", msg="Allow Bash: rm -rf build?")
        )
        message, _ = self._uncertain(spawn, talk)
        self.assertIn("may have reached a prompt", message)
        self.assertIn("Allow Bash: rm -rf build?", message)

    def test_a_planted_escape_sequence_in_the_question_is_stripped(self) -> None:
        planted = "Allow?\x1b]52;c;ZXZpbA==\x07\x1b[2J\x9b1;1H" + "z" * 400
        spawn, talk = _settled_seams(after=_hc_get_result("blocked", msg=planted))
        message, _ = self._uncertain(spawn, talk)
        for character in ("\x1b", "\x07", "\x9b"):
            self.assertNotIn(character, message)
        self.assertIn("(Allow?", message)
        self.assertNotIn("z" * 200, message, "the question is capped")

    def test_a_turn_that_moved_is_reported(self) -> None:
        for spawn, talk in (
            (_HcSpawnSeam([_hc_get_result(turn=3)]), FakeConversation(attach_server(turn=4))),
            _settled_seams(before=_hc_get_result(turn=3), after=_hc_get_result(turn=4)),
        ):
            with self.subTest():
                message, _ = self._uncertain(spawn, talk)
                self.assertIn("turn had moved", message)

    def test_a_read_back_that_fails_is_reported(self) -> None:
        spawn, talk = _settled_seams(
            after=subprocess.TimeoutExpired(["hc", "get"], deliver.HC_TIMEOUT_SECONDS)
        )
        message, _ = self._uncertain(spawn, talk)
        self.assertIn("could not be read again", message)

    def test_a_done_agent_that_turns_idle_is_not_a_change(self) -> None:
        spawn, talk = _settled_seams(
            before=_hc_get_result("done"), after=_hc_get_result("idle"), status="done"
        )
        deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertEqual(talk.pastes(), [_pasted("Hello there")])

    def test_a_failed_spoken_warning_still_reports_the_possible_prompt(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result()])
        talk = FakeConversation(attach_server(status="blocked"))
        refusal = providers.ProviderRefusal(providers.VOICE_FORGE, "synthesis unreachable")
        with self.assertRaises(deliver.DeliveryUncertain) as caught:
            deliver.deliver(
                "yes 1", spawn=spawn, converse=talk, speak_text=mock.Mock(side_effect=refusal)
            )
        self.assertIn("spoken warning failed", str(caught.exception))


class BlockedRefusalTests(DeliverTestBase):
    """A blocked or busy agent receives nothing; the refusal is audible (R18)."""

    def test_a_blocked_agent_receives_no_text_and_the_refusal_is_spoken(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result("blocked")])
        talk = FakeConversation(attach_server())
        spoken: list[str] = []
        with self.assertRaises(deliver.DeliveryRefusal) as caught:
            deliver.deliver(
                "Approve the deploy", spawn=spawn, converse=talk, speak_text=spoken.append
            )
        self.assertEqual(len(spawn.calls), 1)
        self.assertFalse(talk.called, "a blocked agent is never sent text")
        self.assertEqual(spoken, [deliver.BLOCKED_REFUSAL_PHRASE])
        self.assertIn("blocked", str(caught.exception))
        self.assertEqual(self._held(), "Approve the deploy")

    def test_a_second_blocked_refusal_replaces_the_hold_and_never_appends(self) -> None:
        # One current file, never appended, so the hold is not a transcript
        # log (KTD1): a second refusal replaces the first held transcript.
        spawn = _HcSpawnSeam([_hc_get_result("blocked"), _hc_get_result("blocked")])
        for text in ("first transcript", "second transcript"):
            with self.assertRaises(deliver.DeliveryRefusal):
                deliver.deliver(text, spawn=spawn, speak_text=lambda phrase: None)
        self.assertEqual(self._held(), "second transcript")

    def test_a_blocked_refusal_holds_the_transcript_even_when_speech_fails(self) -> None:
        spawn = _HcSpawnSeam([_hc_get_result("blocked")])
        refusal = providers.ProviderRefusal(providers.VOICE_FORGE, "synthesis unreachable")
        with self.assertRaises(providers.ProviderRefusal):
            deliver.deliver(
                "Approve the deploy", spawn=spawn, speak_text=mock.Mock(side_effect=refusal)
            )
        self.assertEqual(self._held(), "Approve the deploy")

    def test_only_a_settled_agent_is_pasted_into(self) -> None:
        # Every status other than idle or done, and no status at all, holds
        # the transcript: a settled agent raises no dialog on its own.
        for agent_status in ("working", "error", "unknown", "thinking", None):
            with self.subTest(agent_status=agent_status):
                self._refused_path().unlink(missing_ok=True)
                spawn = _HcSpawnSeam([_hc_get_result(agent_status)])
                talk = FakeConversation(attach_server())
                spoken: list[str] = []
                with self.assertRaises(deliver.DeliveryRefusal) as caught:
                    deliver.deliver(
                        "Hello there", spawn=spawn, converse=talk, speak_text=spoken.append
                    )
                self.assertNotIsInstance(caught.exception, deliver.DeliveryUncertain)
                self.assertFalse(talk.called, "nothing was pasted")
                self.assertEqual(spoken, [deliver.BUSY_REFUSAL_PHRASE])
                self.assertIn("not idle or done", str(caught.exception))
                self.assertEqual(self._held(), "Hello there")
        self.assertEqual(deliver.TYPABLE_STATUSES, ("idle", "done"))

    def test_a_done_agent_is_pasted_into(self) -> None:
        # done is a turn that finished while nobody watched: as settled as
        # idle, and the usual state when the operator answers by voice.
        spawn, talk = _settled_seams(before=_hc_get_result("done"), status="done")
        deliver.deliver("Hello there", spawn=spawn, converse=talk)
        self.assertEqual(talk.pastes(), [_pasted("Hello there")])
        self.assertIsNone(self._held())


class RefusedHoldTests(DeliverTestBase):
    """The refused transcript is transient: explicit use or discard only (R19)."""

    def test_use_refused_delivers_once_and_clears_the_hold(self) -> None:
        self._write_hold("Approve the deploy")
        spawn, talk = _settled_seams()
        deliver.use_refused(spawn=spawn, converse=talk)
        self.assertEqual(talk.pastes(), [_pasted("Approve the deploy")])
        self.assertIsNone(self._held())

    def test_use_refused_with_no_hold_is_refused_by_name_and_calls_no_hc(self) -> None:
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn)
        self.assertEqual(spawn.calls, [])

    def test_use_refused_on_a_still_blocked_agent_refuses_and_holds_again(self) -> None:
        self._write_hold("Approve the deploy")
        spawn = _HcSpawnSeam([_hc_get_result("blocked")])
        talk = FakeConversation(attach_server())
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn, converse=talk, speak_text=lambda phrase: None)
        self.assertFalse(talk.called, "a blocked agent is never sent text")
        self.assertEqual(self._held(), "Approve the deploy")

    def test_use_refused_keeps_the_hold_when_the_paste_is_not_sent(self) -> None:
        # The hold is deleted only after a sent paste: a paste that fails
        # before sending must not consume the only remaining copy (F02).
        for script in (
            attach_server(attach_error={"message": "finished"}),
            attach_server(paint=b"\x1b[?2004l"),
            b"",
        ):
            with self.subTest(script=script[:20]):
                self._write_hold("Approve the deploy")
                spawn = _HcSpawnSeam([_hc_get_result()])
                with self.assertRaises(deliver.DeliveryRefusal):
                    deliver.use_refused(spawn=spawn, converse=FakeConversation(script))
                self.assertEqual(self._held(), "Approve the deploy")

    def test_use_refused_clears_a_hold_whose_paste_was_sent(self) -> None:
        self._write_hold("yes 1")
        spawn = _HcSpawnSeam([_hc_get_result()])
        talk = FakeConversation(attach_server(status="blocked"))
        with self.assertRaises(deliver.DeliveryUncertain):
            deliver.use_refused(spawn=spawn, converse=talk, speak_text=lambda phrase: None)
        self.assertIsNone(self._held())

    def test_use_refused_keeps_the_hold_when_the_binding_is_gone(self) -> None:
        # An unbound agent refuses the delivery before any hc call; the
        # hold read just before must survive that refusal (F02).
        self._write_hold("Approve the deploy")
        (self.state_dir / binding.BINDING_FILENAME).unlink()
        spawn = _HcSpawnSeam([])
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.use_refused(spawn=spawn)
        self.assertEqual(spawn.calls, [])
        self.assertEqual(self._held(), "Approve the deploy")

    def test_discard_refused_deletes_the_hold_without_sending(self) -> None:
        self._write_hold("Approve the deploy")
        deliver.discard_refused()
        self.assertIsNone(self._held())

    def test_discard_refused_with_no_hold_is_refused_by_name(self) -> None:
        with self.assertRaises(deliver.DeliveryRefusal):
            deliver.discard_refused()

    def test_a_held_transcript_is_never_auto_delivered_by_a_later_delivery(self) -> None:
        # A later delivery of a fresh transcript leaves the hold untouched:
        # never delivered automatically, never queued, never implicitly
        # discarded (R19).
        self._write_hold("Approve the deploy")
        spawn, talk = _settled_seams()
        deliver.deliver("Something new", spawn=spawn, converse=talk)
        self.assertEqual(talk.pastes(), [_pasted("Something new")])
        self.assertEqual(self._held(), "Approve the deploy")


if __name__ == "__main__":
    unittest.main()
