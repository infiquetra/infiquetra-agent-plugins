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

import herdr_core  # noqa: E402
import settings  # noqa: E402


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


class LabelAndKeysTests(unittest.TestCase):
    def test_label_session_writes_the_voice_session_label(self) -> None:
        run = _RunSeam(_completed())
        herdr_core.label_session(
            "t21", "session-abc", timeout=2.0, run_process=run, hc="hc"
        )
        self.assertEqual(
            run.calls[0][0], ["hc", "label", "t21", "voice.agent-session=session-abc"]
        )

    def test_type_text_presses_one_key_per_character_and_never_enter(self) -> None:
        run = _RunSeam(_completed())
        herdr_core.type_text("t7", "Hi, you.", timeout=10.0, run_process=run, hc="hc")
        command, kwargs = run.calls[0]
        self.assertEqual(
            command,
            ["hc", "keys", "t7", "shift+h", "i", ",", "space", "y", "o", "u", "."],
        )
        self.assertNotIn("enter", command)
        self.assertEqual(kwargs, {"timeout": 10.0, "check": True})

    def test_type_text_never_uses_hc_send(self) -> None:
        run = _RunSeam(_completed())
        herdr_core.type_text("t7", "Deploy it", timeout=10.0, run_process=run, hc="hc")
        self.assertNotIn("send", run.calls[0][0])

    def test_type_text_with_nothing_to_type_is_refused_and_runs_nothing(self) -> None:
        run = _RunSeam()
        with self.assertRaises(herdr_core.CoreRefusal):
            herdr_core.type_text("t7", "", timeout=10.0, run_process=run, hc="hc")
        self.assertEqual(run.calls, [])

    def test_a_rejected_key_name_is_carried_into_the_refusal(self) -> None:
        stderr = json.dumps(
            {"error": {"kind": "invalid_params", "message": "unknown key ~"}}
        )
        run = _RunSeam(
            subprocess.CalledProcessError(1, ["hc"], output="", stderr=stderr)
        )
        with self.assertRaises(herdr_core.CoreRefusal) as caught:
            herdr_core.type_text("t7", "a-b", timeout=10.0, run_process=run, hc="hc")
        self.assertIn("unknown key ~", caught.exception.reason)

    def test_untypable_text_is_refused_before_any_hc_call(self) -> None:
        run = _RunSeam()
        with self.assertRaises(herdr_core.UntypableText):
            herdr_core.type_text("t7", "Why?", timeout=10.0, run_process=run, hc="hc")
        self.assertEqual(run.calls, [])


class KeyNameTests(unittest.TestCase):
    """Only characters herdr core 0.1.20 was seen to type exactly are mapped."""

    def test_letters_digits_spaces_and_plain_punctuation_map(self) -> None:
        self.assertEqual(
            herdr_core.key_names("ab 09 .,'-;/=`[]"),
            ["a", "b", "space", "0", "9", "space",
             ".", ",", "'", "-", ";", "/", "=", "`", "[", "]"],
        )

    def test_a_capital_letter_is_shift_plus_its_lowercase(self) -> None:
        # A bare "A" types "a" in hc keys; only shift+a types "A".
        self.assertEqual(herdr_core.key_names("AZ"), ["shift+a", "shift+z"])

    def test_untypable_characters_refuse_the_whole_line(self) -> None:
        with self.assertRaises(herdr_core.UntypableText) as caught:
            herdr_core.key_names("Is it ready? Yes! Is it? é")
        self.assertEqual(caught.exception.characters, ["?", "!", "é"])
        self.assertIn("'?'", caught.exception.reason)

    def test_every_character_hc_keys_rejected_or_mistyped_is_untypable(self) -> None:
        # Rejected by herdr core 0.1.20, or typed as something else (a
        # backslash is left out on purpose: before Enter it means new line).
        for character in '?!":()@#$%&*+_~^{}|<>\\\t\né€':
            with self.subTest(character=character):
                with self.assertRaises(herdr_core.UntypableText):
                    herdr_core.key_names(f"a{character}b")

    def test_no_key_name_ever_submits(self) -> None:
        keys = herdr_core.key_names("Send it now, please.")
        for name in ("enter", "return", "\n", "\r"):
            self.assertNotIn(name, keys)


class RecordReadingTests(unittest.TestCase):
    def test_status_word_reads_the_reported_state(self) -> None:
        self.assertEqual(
            herdr_core.status_word({"status": {"state": "blocked", "msg": "Allow?"}}),
            "blocked",
        )
        for record in ({}, {"status": None}, {"status": "idle"}, {"status": {"state": ""}}):
            with self.subTest(record=record):
                self.assertIsNone(herdr_core.status_word(record))

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
