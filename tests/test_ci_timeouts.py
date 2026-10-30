"""Finite Linux controls for the actual CI installer timeout boundaries.

No installer or sudo runs. Only the timeout prefix from each production command
is exercised, with a shorter duration and an owned Python parent/child pair.
The child never detaches and has its own two-second lifetime.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts.ci import provision_ctags


ROOT = Path(__file__).resolve().parents[1]


def installer_boundaries(workflow: str) -> list[tuple[str, list[str]]]:
    boundaries = []
    for line in workflow.splitlines():
        if not line.strip().startswith("timeout "):
            continue
        tokens = shlex.shlex(line.strip(), posix=True)
        tokens.whitespace_split = True
        prefix = []
        for token in tokens:
            prefix.append(token)
            if re.fullmatch(r"\d+s", token):
                break
        boundaries.append((f"workflow installer {len(boundaries) + 1}", prefix))
    # Capture actual constructed apt commands without executing sudo/apt.
    with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(
        provision_ctags, "probe", side_effect=[False, True]
    ), mock.patch.object(provision_ctags.subprocess, "run") as run:
        if provision_ctags.main() != 0:
            raise AssertionError("could not capture apt installer commands")
    for call in run.call_args_list:
        command = call.args[0]
        boundaries.append((f"apt {command[-1]}", command[command.index("timeout"):command.index("apt-get")]))
    return boundaries


def observe_timeout(prefix: list[str]) -> dict:
    """Run a handshaken, TERM-resistant child within one owned process group."""
    with tempfile.TemporaryDirectory(prefix="ci-timeout-control-") as temporary:
        folder = Path(temporary)
        child = folder / "child.py"
        child.write_text('''import json, os, signal, sys, time
from pathlib import Path
started = time.monotonic()
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(json.dumps({"pid": os.getpid(), "group": os.getpgrp(),
    "started": started, "ignores_term": signal.getsignal(signal.SIGTERM) == signal.SIG_IGN}))
time.sleep(max(0, started + 1.2 - time.monotonic()))
Path(sys.argv[2]).write_text("child ran after the deadline")
time.sleep(max(0, started + 2.0 - time.monotonic()))
''', encoding="utf-8")
        parent = folder / "parent.py"
        parent.write_text('''import subprocess, sys
# Default SIGTERM behavior: the parent exits while its child ignores TERM.
subprocess.run([sys.executable, *sys.argv[1:]], check=True, timeout=3)
''', encoding="utf-8")
        ready, late = folder / "ready.json", folder / "late.txt"
        # Scale durations only; retain every actual supervision flag. In
        # particular, reverting production to TERM/kill-after must fail here.
        scaled = ["0.6s" if re.fullmatch(r"\d+s", arg) else
                  "--kill-after=0.2s" if arg.startswith("--kill-after=") else arg for arg in prefix]
        command = [*scaled, sys.executable, str(parent), str(child), str(ready), str(late)]
        process = subprocess.Popen(command, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # Per-control outer watchdog is four seconds, including startup.
            code = process.wait(timeout=4)
            handshake = json.loads(ready.read_text(encoding="utf-8"))
            if handshake["group"] != process.pid or not handshake["ignores_term"]:
                raise AssertionError("child did not acknowledge the owned group and TERM handler")
            try:
                state = Path(f"/proc/{handshake['pid']}/stat").read_text().split(")", 1)[1].split()[0]
            except FileNotFoundError:
                state = "absent"
            # Observe beyond both scaled TERM/grace deadlines and the child's
            # mandatory late-write point. A zombie is no longer executing.
            time.sleep(max(0, handshake["started"] + 1.4 - time.monotonic()))
            return {"source_prefix": prefix, "scaled_prefix": scaled, "exit": code,
                    "child_handshake": True, "child_state_at_return": state,
                    "late_marker": late.exists()}
        finally:
            # The only signalled group is the session created by this Popen.
            # This also cleans up the intentionally broken TERM counterexample.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=2)


@unittest.skipUnless(sys.platform == "linux", "CI GNU timeout/process-group contract is Linux-only")
class InstallerTimeoutControls(unittest.TestCase):
    def test_actual_installer_boundaries_stop_term_ignoring_descendants(self):
        boundaries = installer_boundaries((ROOT / ".github/workflows/ci.yml").read_text())
        self.assertEqual(len(boundaries), 5)
        self.assertEqual([prefix[-1] for _, prefix in boundaries], ["240s", "270s", "270s", "90s", "90s"])
        for name, prefix in boundaries:
            with self.subTest(boundary=name):
                observation = observe_timeout(prefix)
                print(json.dumps({"boundary": name, **observation}), flush=True)
                self.assertNotEqual(observation["exit"], 0, observation)
                self.assertIn(observation["child_state_at_return"], ("absent", "Z", "X"), observation)
                self.assertFalse(observation["late_marker"], observation)


if __name__ == "__main__":
    unittest.main()
