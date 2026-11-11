"""Tests for the herdr core client (portable core).

Every ``hc`` call goes through an injected ``run_process`` seam, so no test
runs the real herdr core, reads a real terminal, or types into one.
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

import herdr_core  # noqa: E402
import settings  # noqa: E402
from hc_stub import (  # noqa: E402
    AUTOMATIC_INPUT,
    CLOSE,
    CREDIT,
    DATA,
    FakeConversation,
    attach_server,
)


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=None, returncode=returncode, stdout=stdout, stderr=stderr
    )


class _RunSeam:
    """Records hc invocations in ``process.run``'s shape instead of running hc."""

    def __init__(self, *results) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self._results = list(results)

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if not self._results:
            raise AssertionError(f"unexpected hc invocation: {command!r}")
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _record(**fields) -> str:
    payload = {"address": "t7", "state": "live", "labels": {}, "status": None}
    payload.update(fields)
    return json.dumps(payload)


class GetTerminalTests(unittest.TestCase):
    def test_get_runs_hc_get_json_with_the_deadline(self) -> None:
        run = _RunSeam(_completed(_record()))
        with mock.patch.dict(os.environ, {}, clear=True):
            record = herdr_core.get_terminal("review", timeout=2.0, run_process=run)
        self.assertEqual(record["address"], "t7")
        self.assertEqual(
            run.calls, [(["hc", "get", "review", "--json"], {"timeout": 2.0, "check": True})]
        )

    def test_the_herdr_core_command_comes_from_the_setting(self) -> None:
        run = _RunSeam(_completed(_record()))
        env = {settings.HC_BIN: "/opt/example/bin/hc"}
        with mock.patch.dict(os.environ, env, clear=True):
            herdr_core.get_terminal("t7", timeout=2.0, run_process=run)
        self.assertEqual(run.calls[0][0][0], "/opt/example/bin/hc")

    def test_an_empty_herdr_core_setting_is_a_named_refusal_and_runs_nothing(
        self,
    ) -> None:
        run = _RunSeam()
        with mock.patch.dict(os.environ, {settings.HC_BIN: ""}, clear=True):
            with self.assertRaises(herdr_core.CoreRefusal) as caught:
                herdr_core.get_terminal("t7", timeout=2.0, run_process=run)
        self.assertIn("VOICE_HC_BIN", caught.exception.reason)
        self.assertEqual(run.calls, [])

    def test_a_wrapped_record_is_unwrapped(self) -> None:
        wrapped = json.dumps({"terminal": json.loads(_record(address="t9"))})
        run = _RunSeam(_completed(wrapped))
        record = herdr_core.get_terminal("t9", timeout=2.0, run_process=run, hc="hc")
        self.assertEqual(record["address"], "t9")

    def test_output_that_is_not_one_terminal_record_is_a_named_refusal(self) -> None:
        for stdout in (
            "not json",
            "[]",
            "null",
            json.dumps({"state": "live"}),
            json.dumps({"address": ""}),
            json.dumps({"address": 7}),
        ):
            with self.subTest(stdout=stdout):
                run = _RunSeam(_completed(stdout))
                with self.assertRaises(herdr_core.CoreRefusal):
                    herdr_core.get_terminal("t7", timeout=2.0, run_process=run, hc="hc")

    def test_herdr_core_errors_are_carried_into_the_refusal(self) -> None:
        stderr = json.dumps(
            {"error": {"kind": "not_found", "message": "no terminal named review"}}
        )
        run = _RunSeam(
            subprocess.CalledProcessError(3, ["hc"], output="", stderr=stderr)
        )
        with self.assertRaises(herdr_core.CoreRefusal) as caught:
            herdr_core.get_terminal("review", timeout=2.0, run_process=run, hc="hc")
        self.assertIn("status 3", caught.exception.reason)
        self.assertIn("no terminal named review", caught.exception.reason)

    def test_timeouts_and_start_failures_are_named_refusals(self) -> None:
        for failure, expected in (
            (subprocess.TimeoutExpired(["hc"], 2.0), "deadline"),
            (FileNotFoundError("hc not found"), "cannot start"),
        ):
            with self.subTest(failure=type(failure).__name__):
                run = _RunSeam(failure)
                with self.assertRaises(herdr_core.CoreRefusal) as caught:
                    herdr_core.get_terminal("t7", timeout=2.0, run_process=run, hc="hc")
                self.assertIn(expected, caught.exception.reason)


class LabelTests(unittest.TestCase):
    def test_label_session_writes_the_voice_session_label(self) -> None:
        run = _RunSeam(_completed())
        herdr_core.label_session(
            "t21", "session-abc", timeout=2.0, run_process=run, hc="hc"
        )
        self.assertEqual(
            run.calls[0][0], ["hc", "label", "t21", "voice.agent-session=session-abc"]
        )


#: Every character hc keys rejected or mistyped on herdr core 0.1.20, plus
#: text outside ASCII. The paste must carry all of them intact.
_HARD_TEXT = 'Is it? Yes! "q" a:b (c) @me #1 $2 50% & * + _ ~ ^ {x} |y| <z> A é 漢字 😀'


class PasteTests(unittest.TestCase):
    """A paste through `hc connect` and an attach, against a scripted core."""

    def _paste(self, line: str = "Hello there", **server):
        talk = FakeConversation(attach_server(**server))
        record = herdr_core.paste_text(
            "t7", line, cols=100, rows=30, timeout=10.0, converse=talk, hc="hc"
        )
        return talk, record

    def test_a_paste_is_one_bracketed_input_frame_and_a_clean_detach(self) -> None:
        talk, record = self._paste()
        self.assertEqual(talk.argv, ["hc", "connect"])
        self.assertEqual(talk.timeout, 10.0)
        self.assertEqual(
            talk.client_hello(),
            {"jsonrpc": "2.0", "id": 0, "method": "hello", "params": {"framed": True}},
        )
        frames = talk.client_frames()
        attach = json.loads(frames[0][2])
        self.assertEqual(frames[0][:2], (0, DATA))
        self.assertEqual(attach["method"], "terminal.attach")
        self.assertEqual(
            attach["params"],
            {
                "caller": None,
                "cols": 100,
                "rows": 30,
                "history": 0,
                "observe": False,
                "terminal": "t7",
            },
        )
        # The first paint is credited back, as `hc attach` does.
        self.assertEqual(frames[1][:2], (1, CREDIT))
        self.assertGreater(int.from_bytes(frames[1][2], "little"), 0)
        self.assertEqual(
            frames[2], (1, AUTOMATIC_INPUT, b"\x1b[200~Hello there\x1b[201~")
        )
        self.assertEqual(frames[3], (1, CLOSE, b""))
        self.assertEqual(len(frames), 4)
        self.assertIsNotNone(talk.finished)
        self.assertEqual(record["address"], "t7")

    def test_every_character_keys_could_not_type_arrives_intact(self) -> None:
        talk, _ = self._paste(_HARD_TEXT)
        self.assertEqual(
            talk.pastes(),
            [b"\x1b[200~" + _HARD_TEXT.encode("utf-8") + b"\x1b[201~"],
        )

    def test_the_paste_never_carries_enter_escape_or_a_planted_end_marker(self) -> None:
        talk, _ = self._paste("a\x1b[201~b\rc\nd\x9be\x00f\x7fg")
        (payload,) = talk.pastes()
        self.assertEqual(payload, b"\x1b[200~a[201~bcdefg\x1b[201~")
        self.assertEqual(payload.count(b"\x1b"), 2)
        self.assertNotIn(b"\r", payload)
        self.assertNotIn(b"\n", payload)

    def test_the_echo_of_the_paste_is_credited_before_the_close(self) -> None:
        talk, _ = self._paste(echo=b"Hello there")
        kinds = [kind for _, kind, _ in talk.client_frames()]
        self.assertEqual(kinds, [DATA, CREDIT, AUTOMATIC_INPUT, CLOSE, CREDIT])

    def test_plain_data_is_used_when_automatic_input_is_not_offered(self) -> None:
        talk, _ = self._paste(automatic_input=False)
        self.assertIn((1, DATA, b"\x1b[200~Hello there\x1b[201~"), talk.client_frames())

    def test_a_program_without_bracketed_paste_gets_nothing(self) -> None:
        talk = FakeConversation(attach_server(paint=b"\x1b[?2004h\x1b[?2004l> "))
        with self.assertRaises(herdr_core.PasteRefusal) as caught:
            herdr_core.paste_text("t7", "hi", cols=100, rows=30, timeout=10.0, converse=talk)
        self.assertIn("bracketed paste", caught.exception.reason)
        self.assertEqual(talk.pastes(), [])
        self.assertEqual(talk.client_frames()[-1], (1, CLOSE, b""))
        self.assertIsNotNone(talk.finished)

    def test_a_refused_attach_is_named_and_cleaned_for_display(self) -> None:
        talk = FakeConversation(
            attach_server(attach_error={"code": -32000, "message": "not_found\x1b[2J"})
        )
        with self.assertRaises(herdr_core.PasteRefusal) as caught:
            herdr_core.paste_text("t7", "hi", cols=100, rows=30, timeout=10.0, converse=talk)
        self.assertIn("not_found", caught.exception.reason)
        self.assertNotIn("\x1b", caught.exception.reason)
        self.assertEqual(talk.pastes(), [])

    def test_a_core_without_framed_attach_gets_nothing_but_hello(self) -> None:
        talk = FakeConversation(
            attach_server(hello={"id": 0, "result": {"framed": False, "features": []}})
        )
        with self.assertRaises(herdr_core.PasteRefusal):
            herdr_core.paste_text("t7", "hi", cols=100, rows=30, timeout=10.0, converse=talk)
        self.assertEqual(talk.client_frames(), [])

    def test_an_attach_to_another_terminal_gets_nothing(self) -> None:
        talk = FakeConversation(attach_server(terminal="t8"))
        with self.assertRaises(herdr_core.PasteRefusal):
            herdr_core.paste_text("t7", "hi", cols=100, rows=30, timeout=10.0, converse=talk)
        self.assertEqual(talk.pastes(), [])

    def test_a_connection_that_ends_before_the_paste_is_a_refusal(self) -> None:
        for stop_after in ("hello", "reply", None):
            with self.subTest(stop_after=stop_after):
                script = attach_server(stop_after=stop_after) if stop_after else b""
                talk = FakeConversation(script)
                with self.assertRaises(herdr_core.PasteRefusal):
                    herdr_core.paste_text(
                        "t7", "hi", cols=100, rows=30, timeout=10.0, converse=talk
                    )
                self.assertEqual(talk.pastes(), [])

    def test_a_connection_that_ends_after_the_paste_is_uncertain(self) -> None:
        talk = FakeConversation(attach_server(close_echo=False))
        with self.assertRaises(herdr_core.PasteUncertain) as caught:
            herdr_core.paste_text("t7", "hi", cols=100, rows=30, timeout=10.0, converse=talk)
        self.assertIn("did not close cleanly", caught.exception.reason)
        self.assertEqual(len(talk.pastes()), 1)

    def test_a_passed_deadline_is_named(self) -> None:
        talk = FakeConversation(attach_server(stop_after="hello"), expired=True)
        with self.assertRaises(herdr_core.PasteRefusal) as caught:
            herdr_core.paste_text("t7", "hi", cols=100, rows=30, timeout=10.0, converse=talk)
        self.assertIn("10-second deadline", caught.exception.reason)

    def test_nothing_left_to_paste_never_starts_hc(self) -> None:
        talk = FakeConversation(attach_server())
        with self.assertRaises(herdr_core.PasteRefusal):
            herdr_core.paste_text("t7", "\x1b\x07", cols=100, rows=30, timeout=10.0, converse=talk)
        self.assertFalse(talk.called)

    def test_bracketed_paste_mode_is_the_last_word_in_the_paint(self) -> None:
        on, off = b"\x1b[?2004h", b"\x1b[?2004l"
        self.assertTrue(herdr_core.bracketed_paste_on(off + b"x" + on))
        self.assertFalse(herdr_core.bracketed_paste_on(on + b"x" + off))
        self.assertFalse(herdr_core.bracketed_paste_on(b"no modes at all"))

    def test_paste_safe_keeps_text_and_spacing_but_drops_controls(self) -> None:
        self.assertEqual(herdr_core.paste_safe("  a  b é 😀 "), "  a  b é 😀 ")
        self.assertEqual(herdr_core.paste_safe("a\tb\x1bc\x85d"), "abcd")


#: Every character a terminal acts on: C0 controls (ESC, BEL, NUL ...), DEL
#: and the C1 range, which includes the single-byte CSI and OSC introducers.
_CONTROLS = [chr(code) for code in (*range(0x20), 0x7F, *range(0x80, 0xA0))]


class PrintableTests(unittest.TestCase):
    """Program-supplied text never reaches the operator's terminal raw."""

    def test_every_control_character_is_removed(self) -> None:
        cleaned = herdr_core.printable("a" + "".join(_CONTROLS) + "b")
        self.assertEqual(cleaned, "a b")
        for character in _CONTROLS:
            self.assertNotIn(character, cleaned)

    def test_escape_sequences_lose_their_introducers(self) -> None:
        planted = "Allow\x1b]52;c;ZXZpbA==\x07 Bash \x9b2J\x1b[2Jrm?"
        cleaned = herdr_core.printable(planted)
        self.assertNotIn("\x1b", cleaned)
        self.assertNotIn("\x07", cleaned)
        self.assertNotIn("\x9b", cleaned)
        self.assertTrue(cleaned.startswith("Allow"))

    def test_ordinary_text_and_non_ascii_letters_are_kept(self) -> None:
        self.assertEqual(herdr_core.printable("  Allow  café\tbuild?\n"), "Allow café build?")

    def test_long_text_is_capped_with_an_ellipsis(self) -> None:
        cleaned = herdr_core.printable("x" * 500)
        self.assertEqual(len(cleaned), herdr_core.DISPLAY_LIMIT)
        self.assertTrue(cleaned.endswith("…"))
        self.assertEqual(herdr_core.DISPLAY_LIMIT, 120)

    def test_herdr_core_error_messages_are_cleaned(self) -> None:
        for stderr in (
            json.dumps({"error": {"kind": "x", "message": "bad\x1b[2J" + "y" * 300}}),
            "plain failure\x1b]0;title\x07",
        ):
            with self.subTest(stderr=stderr[:30]):
                run = _RunSeam(subprocess.CalledProcessError(1, ["hc"], "", stderr))
                with self.assertRaises(herdr_core.CoreRefusal) as caught:
                    herdr_core.get_terminal("t7", timeout=2.0, run_process=run, hc="hc")
                reason = caught.exception.reason
                for character in _CONTROLS:
                    self.assertNotIn(character, reason)
                self.assertLess(len(reason), herdr_core.DISPLAY_LIMIT + 60)


class RecordReadingTests(unittest.TestCase):
    def test_status_word_reads_the_reported_state(self) -> None:
        self.assertEqual(
            herdr_core.status_word({"status": {"state": "blocked", "msg": "Allow?"}}),
            "blocked",
        )
        for record in ({}, {"status": None}, {"status": "idle"}, {"status": {"state": ""}}):
            with self.subTest(record=record):
                self.assertIsNone(herdr_core.status_word(record))

    def test_turn_of_reads_an_integer_turn_only(self) -> None:
        self.assertEqual(herdr_core.turn_of({"turn": 4}), 4)
        for record in ({}, {"turn": None}, {"turn": "4"}, {"turn": True}):
            with self.subTest(record=record):
                self.assertIsNone(herdr_core.turn_of(record))

    def test_session_of_reads_only_the_voice_label(self) -> None:
        self.assertEqual(
            herdr_core.session_of({"labels": {"voice.agent-session": "s-1"}}), "s-1"
        )
        for record in (
            {},
            {"labels": None},
            {"labels": {"herdr.agentSession": "s-1"}},
            {"labels": {"voice.agent-session": "  "}},
        ):
            with self.subTest(record=record):
                self.assertIsNone(herdr_core.session_of(record))

    def test_liveness_and_machine(self) -> None:
        self.assertTrue(herdr_core.is_live({"state": "live"}))
        self.assertFalse(herdr_core.is_live({"state": "finished"}))
        self.assertFalse(herdr_core.is_live({}))
        self.assertFalse(herdr_core.is_other_machine("t7"))
        self.assertTrue(herdr_core.is_other_machine("mini/t7"))


if __name__ == "__main__":
    unittest.main()
