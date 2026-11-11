"""A fake herdr core command for tests that run voice code as a real process.

``write_fake_hc`` writes an executable that answers ``hc get <t> --json``
with one terminal record, the shape herdr core prints, and exits 0 for any
other command. Tests point ``VOICE_HC_BIN`` at it and set ``HC_TERMINAL_ID``
to the record's address, so no test reaches the real herdr core.
"""

from __future__ import annotations

import io
import json
import os
import struct
from pathlib import Path

__all__ = [
    "AUTOMATIC_INPUT",
    "CLOSE",
    "CREDIT",
    "DATA",
    "FakeConversation",
    "attach_server",
    "frame",
    "terminal_record",
    "write_fake_hc",
]


def terminal_record(
    *,
    address: str,
    session_id: str | None,
    state: str = "live",
    status: str | None = "idle",
) -> dict:
    """One ``hc get --json`` record with inert example values."""
    labels = {} if session_id is None else {"voice.agent-session": session_id}
    return {
        "address": address,
        "name": "example-agent",
        "state": state,
        "labels": labels,
        "status": None if status is None else {"state": status},
        "argv": ["claude"],
        "cwd": "/tmp/example",
    }


def write_fake_hc(path: Path, record: dict) -> Path:
    """Write an executable fake ``hc`` that prints ``record`` for ``get``."""
    code = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if sys.argv[1:2] == ['get']:\n"
        f"    sys.stdout.write({json.dumps(json.dumps(record))} + '\\n')\n"
    )
    path.write_text(code, encoding="utf-8")
    os.chmod(path, 0o755)
    return path


# --- A scripted herdr core on the far side of `hc connect` -------------------

#: The frame header herdr core uses on a framed connection.
FRAME = struct.Struct("<IBI")
DATA, CREDIT, CLOSE, AUTOMATIC_INPUT = 0, 1, 2, 6


def frame(channel: int, kind: int, payload: bytes) -> bytes:
    return FRAME.pack(channel, kind, len(payload)) + payload


def attach_server(
    *,
    terminal: str = "t7",
    channel: int = 1,
    automatic_input: bool = True,
    status: str | None = "idle",
    turn: int = 3,
    msg: str | None = None,
    paint: bytes = b"\x1b[?2004l\x1b[H\x1b[2J\x1b[?2004h> ",
    hello: dict | None = None,
    attach_error: dict | None = None,
    close_echo: bool = True,
    echo: bytes = b"",
    stop_after: str | None = None,
) -> bytes:
    """Everything herdr core sends back for one paste, in order.

    ``stop_after`` cuts the script short ("hello", "reply" or "paint") to
    play a connection that ends there.
    """
    hello = hello or {
        "id": 0,
        "jsonrpc": "2.0",
        "result": {"framed": True, "features": ["framed", "attach", "automatic_input"]},
    }
    out = json.dumps(hello).encode() + b"\n"
    if stop_after == "hello":
        return out
    if attach_error is not None:
        reply = {"id": 1, "jsonrpc": "2.0", "error": attach_error}
    else:
        reported = None if status is None else {"state": status}
        if reported is not None and msg is not None:
            reported["msg"] = msg
        reply = {
            "id": 1,
            "jsonrpc": "2.0",
            "result": {
                "automatic_input": automatic_input,
                "channel": channel,
                "resize_notifications": False,
                "terminal": {"address": terminal, "status": reported, "turn": turn},
            },
        }
    # An unrelated frame first: the client must skip it.
    out += frame(7, DATA, b"other channel")
    out += frame(0, DATA, json.dumps(reply).encode())
    if stop_after == "reply" or attach_error is not None:
        return out
    out += frame(channel, DATA, paint)
    if stop_after == "paint":
        return out
    if echo:
        out += frame(channel, DATA, echo)
    if close_echo:
        out += frame(channel, CLOSE, b"")
    return out


class _Pipe(io.BytesIO):
    def close(self) -> None:  # keep the bytes readable after the client closes
        self.closed_by_client = True


class FakeConversation:
    """``process.converse`` in the shape voice uses, playing a script."""

    def __init__(self, server_bytes: bytes, *, expired: bool = False) -> None:
        self.stdin = _Pipe()
        self.stdout = io.BytesIO(server_bytes)
        self.expired = expired
        self.finished: float | None = None
        self.argv: list[str] | None = None
        self.timeout: float | None = None

    def __call__(self, argv, *, timeout):
        """Act as the ``converse`` seam: record the call, return itself."""
        self.argv = list(argv)
        self.timeout = timeout
        return self

    def finish(self, timeout: float) -> int:
        self.finished = timeout
        return 0

    @property
    def called(self) -> bool:
        return self.argv is not None

    def client_hello(self) -> dict:
        written = self.stdin.getvalue()
        return json.loads(written.split(b"\n", 1)[0])

    def client_frames(self) -> list[tuple[int, int, bytes]]:
        """Every frame the client wrote after its hello line."""
        written = self.stdin.getvalue()
        rest = written.split(b"\n", 1)[1] if b"\n" in written else b""
        frames = []
        while rest:
            channel, kind, length = FRAME.unpack(rest[: FRAME.size])
            payload = rest[FRAME.size : FRAME.size + length]
            frames.append((channel, kind, payload))
            rest = rest[FRAME.size + length :]
        return frames

    def pastes(self) -> list[bytes]:
        """The input payloads the client sent on the attach channel."""
        return [
            payload
            for channel, kind, payload in self.client_frames()
            if channel != 0 and kind in (DATA, AUTOMATIC_INPUT)
        ]
