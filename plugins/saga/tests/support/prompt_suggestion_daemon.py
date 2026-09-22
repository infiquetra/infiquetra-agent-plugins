#!/usr/bin/env python3
"""The resident process issue 1038 measures a hook against.

A prototype, not a product. It exists to be timed and is started and stopped by
`tools/prompt_suggestion_latency.py`; nothing installs it and nothing starts it on boot.

It listens on a Unix domain socket rather than a localhost port. That is the stricter
reading of the card's constraint: no port number, unreachable from any network stack, and
access governed by filesystem permissions. Those permissions are load-bearing rather than
decorative -- this process holds a live API credential in memory and answers whatever
connects to it, so a socket any local account could open would let any process on the
machine spend the operator's key. The socket is owner-only inside an owner-only directory
and the process refuses to start when either is wider.

Four request shapes, matching the plan's warm shapes:

* ``s2`` -- the full cookbook pattern: rank the roster, then verify the shortlist.
* ``s3`` -- the wide pass alone, trading the verification pass for one fewer round trip.
* ``s4`` -- served from the client's own answer cache; no network call at all.
* ``s5`` -- answers from the *previous* prompt and computes this one in the background, so
  nothing blocks on the network. The suggestion is one prompt stale by construction.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import stat
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import prompt_suggestion_latency as harness  # noqa: E402

BACKLOG = 64
# One definition, imported rather than restated: the reader that waits for this line lives
# in the harness, and two copies of the same literal drift silently.
READY_PREFIX = harness.READY_PREFIX


class Daemon:
    """Holds the client, roster and questions resident across requests."""

    def __init__(
        self,
        socket_path: Path,
        commands_dir: Path,
        cache_dir: Path,
        transport: str = "",
    ) -> None:
        self.socket_path = Path(socket_path)
        self.cache_dir = Path(cache_dir)
        self.transport = transport or None
        self.started_at = time.monotonic()
        self.client = harness._load_client()
        self.roster = harness.load_roster(commands_dir)
        self.questions = harness.load_questions()
        self._previous: harness.Suggestion | None = None
        # Every request this process sends, including the ones a background thread sends
        # for the stale shape and the ones spent priming the cache. The harness cannot
        # count these from the outside -- a primed or backgrounded call never appears in
        # any timed hook's output -- so an outside-only tally under-reports the spend.
        self._calls = 0
        self._usage: dict[str, int] = {}
        self._lock = threading.Lock()
        self._pending: threading.Thread | None = None
        self._stop = threading.Event()

    # -- the four warm shapes ------------------------------------------------ #

    def handle(self, shape: str, prompt: str) -> dict[str, Any]:
        if shape == "stats":
            return self.stats()
        if shape == "s5":
            return self._stale(prompt)
        result = self._compute(shape, prompt)
        return self._envelope(result)

    def stats(self) -> dict[str, Any]:
        """Everything this process spent, for the run's budget report."""
        with self._lock:
            return {
                "calls": self._calls,
                "usage": dict(self._usage),
                "pid": os.getpid(),
                "uptime_s": round(time.monotonic() - self.started_at, 3),
            }

    def _compute(self, shape: str, prompt: str) -> harness.Suggestion:
        cache_dir = self.cache_dir if shape == "s4" else None

        def ask(state: Any, asked: Mapping[str, Any]) -> Any:
            return self.client.ask(state, asked, transport=self.transport, cache_dir=cache_dir)

        result = harness.suggest(
            prompt,
            self.roster,
            self.questions,
            ask,
            self.client,
            deep_check=(shape == "s2"),
        )
        with self._lock:
            self._calls += result.live_calls
            for key, value in result.usage.items():
                self._usage[key] = self._usage.get(key, 0) + value
        return result

    def _stale(self, prompt: str) -> dict[str, Any]:
        """Answer from the previous prompt; compute this one behind the response.

        The first request of a run therefore carries no suggestion, which is the defining
        property of the shape and not a bug to paper over.
        """
        with self._lock:
            previous = self._previous
        worker = threading.Thread(target=self._precompute, args=(prompt,), daemon=True)
        worker.start()
        self._pending = worker
        if previous is None:
            return self._envelope(harness.Suggestion(), stale=True)
        return self._envelope(previous, stale=True)

    def _precompute(self, prompt: str) -> None:
        try:
            result = self._compute("s3", prompt)
        except Exception:  # noqa: BLE001 - a background failure must not kill the process
            return
        with self._lock:
            self._previous = result

    def _envelope(self, result: harness.Suggestion, *, stale: bool = False) -> dict[str, Any]:
        return {
            "command": result.command,
            "calls": result.calls,
            "usage": dict(result.usage),
            "statuses": list(result.statuses),
            "stale": stale,
            "pid": os.getpid(),
            "uptime_s": round(time.monotonic() - self.started_at, 3),
        }

    # -- the socket ---------------------------------------------------------- #

    def _bind(self) -> socket.socket:
        directory = self.socket_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, harness.SOCKET_DIR_MODE)
        if stat.S_IMODE(directory.stat().st_mode) != harness.SOCKET_DIR_MODE:
            raise harness.HarnessError(
                f"{directory} is not owner-only; refusing to hold a credential behind it"
            )
        if self.socket_path.exists():
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, harness.SOCKET_MODE)
        if stat.S_IMODE(self.socket_path.stat().st_mode) != harness.SOCKET_MODE:
            raise harness.HarnessError(f"{self.socket_path} is not owner-only; refusing to serve")
        server.listen(BACKLOG)
        return server

    def serve(self) -> None:
        server = self._bind()
        print(f"{READY_PREFIX}{os.getpid()} {self.socket_path}", flush=True)
        server.settimeout(0.5)
        try:
            while not self._stop.is_set():
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                with connection:
                    self._serve_one(connection)
        finally:
            server.close()
            self.socket_path.unlink(missing_ok=True)

    def _serve_one(self, connection: socket.socket) -> None:
        try:
            chunks = []
            while not chunks or not chunks[-1].endswith(b"\n"):
                chunk = connection.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            request = json.loads(b"".join(chunks).decode("utf-8") or "{}")
            answer = self.handle(str(request.get("shape", "")), str(request.get("prompt", "")))
        except Exception as exc:  # noqa: BLE001 - never let one request kill the process
            answer = {"error": type(exc).__name__}
        try:
            connection.sendall(json.dumps(answer).encode("utf-8") + b"\n")
        except OSError:
            return

    def stop(self) -> None:
        self._stop.set()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--transport", default="")
    parser.add_argument(
        "--commands-dir", default=str(harness.SAGA_COMMANDS)
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    daemon = Daemon(
        socket_path=Path(args.socket),
        commands_dir=Path(args.commands_dir),
        cache_dir=Path(args.cache_dir),
        transport=args.transport,
    )
    signal.signal(signal.SIGTERM, lambda *_: daemon.stop())
    signal.signal(signal.SIGINT, lambda *_: daemon.stop())
    try:
        daemon.serve()
    except harness.HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
