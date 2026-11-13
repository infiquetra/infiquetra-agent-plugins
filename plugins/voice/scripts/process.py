"""Subprocess discipline for the voice package.

Every subprocess voice starts runs with a deadline attached, and none
ever reads the operator's terminal. Three entry points cover the three
shapes:

- :func:`run` — one bounded helper call. The deadline is a required
  keyword-only argument, so a call without one is impossible by signature.
- :func:`spawn_detached` — one fully detached child in its own session.
  The parent never waits for it and never polls it, so the child carries
  its deadlines internally; the spawner gives it closed standard input and
  devnull output streams.
- :func:`converse` — one child voice talks to over pipes (``hc connect``,
  which speaks herdr core's protocol on its standard input and output).
  Its standard input is a pipe voice writes, never the operator's
  terminal, and a watchdog kills it when its deadline passes.

Both take an injectable spawn seam so tests never touch a real platform
binary, and neither ever runs a shell: argv is a list of argument strings,
and a shell string is rejected by type.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Sequence

__all__ = ["Conversation", "converse", "run", "spawn_detached"]


def _validate_argv(argv: object) -> list[str]:
    """Validate an argv list; reject shell strings and anything not a string."""
    if isinstance(argv, (str, bytes)):
        raise TypeError(
            "argv must be a list of argument strings; voice never runs a "
            "shell, so a shell string is rejected by type"
        )
    if not isinstance(argv, Sequence):
        raise TypeError(
            f"argv must be a sequence of argument strings, not {type(argv).__name__}"
        )
    command = list(argv)
    if not command:
        raise ValueError("argv is empty; a subprocess must name a program")
    for element in command:
        if not isinstance(element, str):
            raise TypeError(
                f"argv elements must be strings, not {type(element).__name__}"
            )
    return command


def _validate_timeout(timeout: object) -> float:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError(
            f"the deadline must be a number of seconds, not {type(timeout).__name__}"
        )
    if timeout <= 0:
        raise ValueError(f"the deadline must be positive seconds, got {timeout!r}")
    return timeout


def run(
    argv: Sequence[str],
    *,
    timeout: float,
    check: bool = True,
    spawn: Callable = subprocess.run,
) -> subprocess.CompletedProcess:
    """Run one bounded helper call under a deadline and return its result.

    The argv list is the only invocation shape. Standard input is closed —
    the child reads end-of-file, never the caller's terminal — and both
    output streams are captured as text. ``timeout`` is the deadline every
    subprocess carries; it is required.

    ``subprocess.TimeoutExpired`` propagates when the deadline passes and,
    with ``check`` on, ``subprocess.CalledProcessError`` when the child
    exits non-zero. Both are named failures for the caller to refuse by
    name; this helper never substitutes a result for them.
    """
    command = _validate_argv(argv)
    seconds = _validate_timeout(timeout)
    return spawn(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=seconds,
        check=check,
    )


def spawn_detached(argv: Sequence[str], *, spawn: Callable = subprocess.Popen) -> int:
    """Start one fully detached child and return its pid without waiting.

    The child runs in its own session, so it survives its parent and is
    never swept up in the parent's process group. Its standard input is
    closed and both output streams go to devnull. The caller never waits
    for the returned pid and this helper never does either: a detached
    child carries its deadlines internally, because nothing outside it can
    enforce one.
    """
    command = _validate_argv(argv)
    child = spawn(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return child.pid


class Conversation:
    """A child voice talks to over pipes, killed by a watchdog at its deadline."""

    def __init__(self, child, deadline: float) -> None:
        self.child = child
        self._expired = threading.Event()
        self._timer = threading.Timer(deadline, self._expire)
        self._timer.daemon = True
        self._timer.start()

    @property
    def stdin(self):
        return self.child.stdin

    @property
    def stdout(self):
        return self.child.stdout

    @property
    def expired(self) -> bool:
        """Whether the watchdog ended the child because its deadline passed."""
        return self._expired.is_set()

    def _expire(self) -> None:
        self._expired.set()
        try:
            self.child.kill()
        except OSError:
            pass

    def finish(self, timeout: float) -> int | None:
        """Close the child's input, wait for it, and stop the watchdog.

        A child that does not exit within ``timeout`` is killed. Returns its
        exit code, or ``None`` when it had to be killed.
        """
        try:
            self.child.stdin.close()
        except OSError:
            pass
        try:
            code = self.child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._expire()
            self.child.wait()
            code = None
        self._timer.cancel()
        return code


def converse(
    argv: Sequence[str],
    *,
    timeout: float,
    spawn: Callable = subprocess.Popen,
) -> Conversation:
    """Start one child to talk to over pipes, under a deadline.

    Standard input and output are binary pipes the caller writes and reads;
    standard error is captured. ``timeout`` is required: a watchdog kills
    the child when it passes, which ends any read the caller is blocked in.
    The caller ends the conversation with :meth:`Conversation.finish`.
    """
    command = _validate_argv(argv)
    seconds = _validate_timeout(timeout)
    child = spawn(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return Conversation(child, seconds)
