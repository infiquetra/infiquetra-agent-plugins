"""Tests for the Claude ``SessionStart`` hook that labels the terminal.

The in-process tests inject the ``run_process`` seam; the end-to-end test
runs the hook file the way Claude runs it, against a fake ``hc`` that only
records its arguments. No test reaches the real herdr core.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PACKAGE / "scripts"))
sys.path.insert(0, str(_PACKAGE / "com.infiquetra.claude" / "hooks"))

import session_start_hook  # noqa: E402
import settings  # noqa: E402

HOOK = _PACKAGE / "com.infiquetra.claude" / "hooks" / "session_start_hook.py"
SESSION = "example-session-start"


class _RunSeam:
    def __init__(self, result=None) -> None:
        self.calls: list[list[str]] = []
        self._result = result

    def __call__(self, command, **kwargs):
        self.calls.append(list(command))
        if isinstance(self._result, BaseException):
            raise self._result
        return subprocess.CompletedProcess(command, 0, "", "")


class SessionStartHookTests(unittest.TestCase):
    def _run(self, payload, env, run=None) -> tuple[int, _RunSeam]:
        run = run or _RunSeam()
        stdin = io.StringIO(payload if isinstance(payload, str) else json.dumps(payload))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            sys, "stdin", stdin
        ):
            code = session_start_hook.main(run_process=run)
        return code, run

    def test_labels_its_own_terminal_with_the_session_id(self) -> None:
        code, run = self._run(
            {"hook_event_name": "SessionStart", "session_id": SESSION, "source": "clear"},
            {settings.HC_TERMINAL_ID: "t21"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            run.calls, [["hc", "label", "t21", f"voice.agent-session={SESSION}"]]
        )

    def test_does_nothing_outside_herdr_core(self) -> None:
        code, run = self._run({"session_id": SESSION}, {})
        self.assertEqual(code, 0)
        self.assertEqual(run.calls, [])

    def test_skips_a_subagent_start(self) -> None:
        code, run = self._run(
            {"session_id": SESSION, "agent_id": "agent-1"},
            {settings.HC_TERMINAL_ID: "t21"},
        )
        self.assertEqual(code, 0)
        self.assertEqual(run.calls, [])

    def test_skips_a_payload_without_a_session_id(self) -> None:
        for payload in ("not json", "[]", {}, {"session_id": ""}, {"session_id": 7}):
            with self.subTest(payload=payload):
                code, run = self._run(payload, {settings.HC_TERMINAL_ID: "t21"})
                self.assertEqual(code, 0)
                self.assertEqual(run.calls, [])

    def test_a_failed_label_never_breaks_the_session(self) -> None:
        for failure in (
            subprocess.TimeoutExpired(["hc"], 2.0),
            subprocess.CalledProcessError(1, ["hc"], "", "boom"),
            FileNotFoundError("hc"),
        ):
            with self.subTest(failure=type(failure).__name__):
                code, _ = self._run(
                    {"session_id": SESSION},
                    {settings.HC_TERMINAL_ID: "t21"},
                    run=_RunSeam(failure),
                )
                self.assertEqual(code, 0)


class SessionStartRegistrationTests(unittest.TestCase):
    """The hook runs on every SessionStart source, briefly, and cannot block."""

    def test_registered_for_every_source_with_a_short_timeout(self) -> None:
        hooks = json.loads(
            (_PACKAGE / "com.infiquetra.claude" / "hooks" / "hooks.json").read_text(
                encoding="utf-8"
            )
        )["hooks"]["SessionStart"]
        self.assertEqual(len(hooks), 1)
        # No matcher: startup, resume, clear and compact all run it, because
        # /clear starts a new session id.
        self.assertNotIn("matcher", hooks[0])
        (command,) = hooks[0]["hooks"]
        self.assertIn("session_start_hook.py", command["command"])
        self.assertLessEqual(command["timeout"], 5)
        self.assertEqual(session_start_hook.HC_TIMEOUT_SECONDS, 2.0)


class SessionStartHookProcessTests(unittest.TestCase):
    """Runs the hook file as Claude does: ``python3 <hook>`` with the payload on stdin."""

    def test_the_hook_file_labels_through_the_configured_hc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "calls.jsonl"
            fake_hc = root / "fake_hc"
            fake_hc.write_text(
                "#!/usr/bin/env python3\n"
                "import json, sys\n"
                f"with open({str(log)!r}, 'a') as f:\n"
                "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n",
                encoding="utf-8",
            )
            os.chmod(fake_hc, 0o755)
            env = {
                "PATH": os.environ.get("PATH", ""),
                settings.HC_TERMINAL_ID: "t21",
                settings.HC_BIN: str(fake_hc),
            }
            completed = subprocess.run(
                [sys.executable, str(HOOK)],
                input=json.dumps({"session_id": SESSION, "source": "startup"}),
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, "")
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(
                calls, [["label", "t21", f"voice.agent-session={SESSION}"]]
            )


if __name__ == "__main__":
    unittest.main()
