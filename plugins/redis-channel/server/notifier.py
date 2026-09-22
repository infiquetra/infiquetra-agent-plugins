"""Channel-notification emission.

The Consumer thread needs to push `notifications/claude/channel` events
out through the MCP `ServerSession`. `send_notification` is an async
method that must run on the asyncio loop that owns the session — but
the Consumer runs on a plain `threading.Thread`. This module bridges
the two.

`AsyncNotifier` is the production implementation: it captures both
references at connect-time and uses `asyncio.run_coroutine_threadsafe`
to schedule the send. `RecordingNotifier` is the test seam — it records
emitted payloads without touching asyncio at all.

Wire-format translation
-----------------------

Claude Code's channel reference (https://code.claude.com/docs/en/channels-reference)
specifies the notification params as ``{content: str, meta: dict[str, str]}``.
`content` becomes the body of a ``<channel source="..." attr="val">…</channel>``
tag in Claude's context; each `meta` entry becomes a tag attribute. Meta keys
must be Python-identifier-shaped (letters/digits/underscores only); keys with
hyphens or other characters are silently dropped by Claude Code.

Our Redis-side `Inbound` payload schema (router → CC) carries more structure
(`router`, `endpoint`, `source`, `chat_id`, `user_id`, `username`, `text`,
`confidence`, `ts`, `metadata`) plus the consumer-injected `_msg_id`. We
translate that to the channel-notification shape here at the emission
boundary: `content` = `text`, `meta` = the other fields stringified and
filtered to identifier-safe keys. Wire format on Redis stays unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Protocol

from mcp.types import Notification

log = logging.getLogger(__name__)

CHANNEL_NOTIFICATION_METHOD = "notifications/claude/channel"

# Identifier rule from the channel docs: letters, digits, underscores; must
# start with letter or underscore. Keys that don't match get dropped.
_META_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def inbound_to_channel_params(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate an Inbound-shaped payload to Claude Code's channel-notification
    params (``{content, meta}``).

    - `content` is taken from the `text` field (empty string if absent).
    - `meta` is built from every other scalar field whose key matches the
      identifier rule. Non-scalar values (dicts, lists) are dropped — `meta`
      is a flat string map per the protocol. `None` values are dropped.
    - The protocol `v` field is dropped from `meta`: it's an internal
      versioning marker, not useful as a tag attribute.
    """
    text = str(payload.get("text", ""))
    meta: dict[str, str] = {}
    for key, value in payload.items():
        if key in ("text", "v"):
            continue
        if value is None:
            continue
        if not _META_KEY_RE.match(key):
            continue
        if isinstance(value, (dict, list)):
            continue
        meta[key] = str(value)
    return {"content": text, "meta": meta}


class ChannelNotifier(Protocol):
    """Thread-safe notification emitter consumed by `Consumer.on_message`."""

    def emit(self, payload: dict[str, Any]) -> None: ...


class AsyncNotifier:
    """Sends notifications/claude/channel to the connected MCP client.

    Constructed inside an MCP tool handler so the asyncio loop + session
    are available. The emit() method is called from the consumer thread.
    """

    def __init__(self, session: Any, loop: asyncio.AbstractEventLoop) -> None:
        self._session = session
        self._loop = loop

    def emit(self, payload: dict[str, Any]) -> None:
        # The generic Notification[dict, str] form lets us emit non-standard
        # method names that aren't in the MCP SDK's ServerNotification union.
        # FastMCP/ServerSession serializes the payload by Pydantic dump, so
        # the runtime accepts this even though static types reject it.
        if self._loop.is_closed():
            # Don't even create the coroutine — that would leak un-awaited.
            log.debug("AsyncNotifier: loop closed, dropping payload")
            return
        params = inbound_to_channel_params(payload)
        notif = Notification[dict, str](
            method=CHANNEL_NOTIFICATION_METHOD,
            params=params,
        )
        coro = self._session.send_notification(notif)  # type: ignore[arg-type]
        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except RuntimeError:
            # Loop transitioned to closed between the check and the schedule.
            # Close the coroutine explicitly so we don't leak.
            coro.close()
            log.debug("AsyncNotifier: loop closed mid-emit, dropping payload")


class RecordingNotifier:
    """Test-only notifier: appends *channel-shaped* params to a list. Threadsafe.

    Returns the same ``{content, meta}`` shape the AsyncNotifier sends on the
    wire, so tests can assert on the post-translation form.
    """

    def __init__(self) -> None:
        import threading

        self._lock = threading.Lock()
        self.emitted: list[dict[str, Any]] = []

    def emit(self, payload: dict[str, Any]) -> None:
        params = inbound_to_channel_params(payload)
        with self._lock:
            self.emitted.append(params)


class NoopNotifier:
    """No-op notifier used when no MCP session is attached (e.g. early
    Phase 1 tests). Drops every emit silently."""

    def emit(self, payload: dict[str, Any]) -> None:
        log.debug("NoopNotifier dropping payload (no session attached)")
