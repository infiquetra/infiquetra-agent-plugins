"""Tests for the subprocess discipline (R32; KTD3, KTD12).

The contract seams are injected for the shape assertions, so no test spawns
a platform binary. Two scenarios run a real child through ``sys.executable``
because stdin-closure and deadline expiry are exactly the behaviours the
contract promises, and they are cheap and hermetic: the interpreter is the
test's own runtime, not a platform binary.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import process  # noqa: E402


class _RunSeam:
    """Records the bounded-runner call instead of spawning a child."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class _SpawnSeam:
    """Records the detached-spawn call instead of spawning a child."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.waited = False

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        return _FakeChild(self)


class _FakeChild:
    pid = 4242

    def __init__(self, seam: _SpawnSeam) -> None:
        self._seam = seam

    def wait(self, *args, **kwargs) -> int:
        self._seam.waited = True
        return 0

    def poll(self):
        self._seam.waited = True
        return None


class BoundedRunnerContractTests(unittest.TestCase):
    """The runner closes stdin and attaches the caller's deadline."""

    def test_stdin_is_closed_and_the_deadline_is_attached(self) -> None:
        seam = _RunSeam()
        process.run(
            ["herdr", "agent", "get", "example-agent"], timeout=10, spawn=seam
        )
        ((command, kwargs),) = seam.calls
        self.assertEqual(command, ["herdr", "agent", "get", "example-agent"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual(kwargs["timeout"], 10)

    def test_a_missing_deadline_is_impossible_by_signature(self) -> None:
        with self.assertRaises(TypeError):
            process.run(["example-program"])

    def test_a_non_positive_deadline_is_rejected(self) -> None:
        for deadline in (0, -1):
            with self.subTest(deadline=deadline):
                with self.assertRaises(ValueError):
                    process.run(["example-program"], timeout=deadline)

    def test_a_non_numeric_deadline_is_rejected(self) -> None:
        with self.assertRaises(TypeError):
            process.run(["example-program"], timeout=True)

    def test_a_shell_string_is_rejected_by_type(self) -> None:
        with self.assertRaises(TypeError):
            process.run("herdr agent get example-agent", timeout=10)
        with self.assertRaises(TypeError):
            process.spawn_detached("voice stop")

    def test_non_string_argv_elements_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            process.run(["example-program", 42], timeout=10)

    def test_an_empty_argv_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            process.run([], timeout=10)
        with self.assertRaises(ValueError):
            process.spawn_detached([])


class DetachedSpawnContractTests(unittest.TestCase):
    """The detached spawner starts a new session, closes streams, never waits."""

    def test_the_child_starts_a_new_session_with_closed_streams(self) -> None:
        seam = _SpawnSeam()
        pid = process.spawn_detached(
            ["example-program", "example-argument"], spawn=seam
        )
        self.assertEqual(pid, _FakeChild.pid)
        ((command, kwargs),) = seam.calls
        self.assertEqual(command, ["example-program", "example-argument"])
        self.assertTrue(kwargs["start_new_session"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertIs(kwargs["stdout"], subprocess.DEVNULL)
        self.assertIs(kwargs["stderr"], subprocess.DEVNULL)
        self.assertFalse(seam.waited, "a detached spawn never waits on the child")


class RealSubprocessTests(unittest.TestCase):
    """The contract proven against a real child of the test's own runtime."""

    def test_a_real_child_reads_end_of_file_on_stdin(self) -> None:
        script = "import sys; print(len(sys.stdin.read()))"
        result = process.run([sys.executable, "-c", script], timeout=30)
        self.assertEqual(result.stdout.strip(), "0")

    def test_a_real_deadline_expires(self) -> None:
        script = "import time; time.sleep(30)"
        with self.assertRaises(subprocess.TimeoutExpired):
            process.run([sys.executable, "-c", script], timeout=0.25)

    def test_a_real_detached_child_returns_its_pid_without_waiting(self) -> None:
        pid = process.spawn_detached([sys.executable, "-c", "pass"])
        self.assertIsInstance(pid, int)
        self.assertGreater(pid, 0)


if __name__ == "__main__":
    unittest.main()
