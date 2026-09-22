#!/usr/bin/env python3
"""A newline-delimited JSON client for herdr's event socket.

Salvaged from the previous orchestrate implementation, trimmed to the one thing this plugin needs:
being told when a pane's agent changes state, instead of asking over and over.

Two pieces of hard-won protocol knowledge came with it and are the reason this is not rewritten
from the schema each time:

- **Subscriptions use herdr's dotted vocabulary** (``pane.agent_status_changed``). The general
  broadcast events use a separate underscored vocabulary, and those names are rejected by
  ``events.subscribe``.
- **The subscription is confirmed before any event arrives.** The first line back is
  ``{"result": {"type": "subscription_started"}}``; treating it as an event loses the handshake and
  desynchronises everything after it.

Dropped in the salvage: reconnect-with-catch-up, threading, and connection accounting. A caller
here waits for minutes, not days, and re-running the wait is a cheaper recovery than carrying a
supervisor around.
"""

from __future__ import annotations

import json
import socket
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_SOCKET_PATH = Path("~/.config/herdr/herdr.sock").expanduser()

AGENT_STATUS_CHANGED = "pane.agent_status_changed"


class HerdrEventError(RuntimeError):
    """The socket could not be used, or said something this client did not expect."""


@dataclass(frozen=True)
class AgentStatusEvent:
    """One pane's agent changing state."""

    pane_id: str
    workspace_id: str
    agent_status: str
    agent: str | None = None
    title: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> AgentStatusEvent | None:
        """Build from one event line, or ``None`` if it is not an agent-status change."""
        if payload.get("event") != AGENT_STATUS_CHANGED:
            return None
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return None
        try:
            return cls(
                pane_id=str(data["pane_id"]),
                workspace_id=str(data["workspace_id"]),
                agent_status=str(data["agent_status"]),
                agent=data.get("agent"),
                title=data.get("title"),
            )
        except KeyError:
            return None


def _connect(socket_path: Path) -> socket.socket:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(socket_path))
    except OSError as exc:
        sock.close()
        raise HerdrEventError(
            f"cannot reach the herdr event socket at {socket_path}: {exc}; "
            "check the server with `herdr status server`"
        ) from exc
    return sock


def agent_status_events(
    pane_ids: Sequence[str],
    *,
    socket_path: Path = DEFAULT_SOCKET_PATH,
    timeout: float | None = None,
) -> Iterator[AgentStatusEvent]:
    """Yield agent-status changes for these panes, until the peer closes or time runs out.

    Subscriptions are **per pane** -- ``pane_id`` is required, and omitting it is rejected with
    ``missing field `pane_id```. There is no global agent-status feed, so the caller passes the
    panes it cares about. An optional ``agent_status`` on each subscription would narrow it further;
    that is left off so a unit going ``blocked`` is seen as well as one going ``idle``.

    Nothing is polled: the read blocks in the kernel until herdr writes a line.
    """
    if not pane_ids:
        return
    with _connect(socket_path) as sock:
        if timeout is not None:
            sock.settimeout(timeout)
        with sock.makefile("rwb") as stream:
            request = {
                "id": "orchestrate-wait",
                "method": "events.subscribe",
                "params": {
                    "subscriptions": [
                        {"type": AGENT_STATUS_CHANGED, "pane_id": p} for p in pane_ids
                    ]
                },
            }
            stream.write(json.dumps(request).encode() + b"\n")
            stream.flush()

            first = stream.readline()
            if not first:
                raise HerdrEventError("herdr closed the socket before confirming the subscription")
            confirmed = json.loads(first)
            if confirmed.get("result") != {"type": "subscription_started"}:
                raise HerdrEventError(
                    f"events.subscribe was not confirmed; herdr replied {confirmed!r}"
                )

            try:
                while line := stream.readline():
                    event = AgentStatusEvent.from_payload(json.loads(line))
                    if event is not None:
                        yield event
            except TimeoutError:
                return
            except json.JSONDecodeError as exc:
                raise HerdrEventError(f"herdr sent a line that is not JSON: {exc}") from exc
