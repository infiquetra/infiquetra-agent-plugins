"""Inbound Redis stream consumer for redis-channel.

Reads `cc-sessions:<session_name>:inbound` via XREADGROUP and invokes a
caller-supplied callback for each message. The callback is responsible
for emitting the matching `notifications/claude/channel` MCP event;
this module knows nothing about MCP.

Threading model
---------------

`Consumer` runs on a dedicated daemon thread. The thread blocks on
`XREADGROUP ... BLOCK 1000` so stop signals (via threading.Event) can
flip the next iteration off without waiting indefinitely. Acks happen
after the callback returns; a callback that raises does NOT ack — the
message is re-delivered after the consumer group's pel-idle timeout
(default redis: 1ms; in our flow, on the next iteration if we're alone).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

import redis.exceptions

log = logging.getLogger(__name__)

INBOUND_STREAM_FMT = "cc-sessions:{session_name}:inbound"
GROUP_NAME_FMT = "cc:{session_name}"
CONSUMER_NAME_DEFAULT = "consumer-1"


def inbound_stream(session_name: str) -> str:
    return INBOUND_STREAM_FMT.format(session_name=session_name)


def consumer_group(session_name: str) -> str:
    return GROUP_NAME_FMT.format(session_name=session_name)


# Callback type: receives the decoded payload dict (validated upstream
# against Inbound pydantic model by the channel layer).
MessageCallback = Callable[[dict[str, Any]], None]


def ensure_group(client: Any, *, stream: str, group: str, start: str = "$") -> bool:
    """Create the consumer group if absent. Returns True if newly created.

    Idempotent: BUSYGROUP errors are treated as success. `start="$"` means
    "only deliver new messages from now on" — what we want; messages already
    in the stream before we attach were either delivered to a prior consumer
    or are stale.
    """
    try:
        client.xgroup_create(name=stream, groupname=group, id=start, mkstream=True)
        return True
    except redis.exceptions.ResponseError as e:
        if "BUSYGROUP" in str(e):
            return False
        raise


class Consumer:
    """Reads inbound Redis stream messages, dispatches to a callback.

    Lifecycle:
        c = Consumer(client, "my-session", on_message)
        c.start()
        ...
        c.stop()
    """

    def __init__(
        self,
        client: Any,
        session_name: str,
        on_message: MessageCallback,
        *,
        consumer_name: str = CONSUMER_NAME_DEFAULT,
        block_ms: int = 1000,
        batch_count: int = 16,
    ) -> None:
        self._client = client
        self._session_name = session_name
        self._on_message = on_message
        self._consumer_name = consumer_name
        self._block_ms = block_ms
        self._batch_count = batch_count
        self._stream = inbound_stream(session_name)
        self._group = consumer_group(session_name)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    @property
    def session_name(self) -> str:
        return self._session_name

    def start(self) -> None:
        if self._started:
            raise RuntimeError(f"Consumer({self._session_name}) already started")
        ensure_group(self._client, stream=self._stream, group=self._group)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"redis-channel-consumer-{self._session_name}",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        log.info(
            "consumer started for session=%s stream=%s group=%s",
            self._session_name,
            self._stream,
            self._group,
        )

    def stop(self, *, timeout: float = 5.0) -> None:
        if not self._started:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._started = False
        log.info("consumer stopped for session=%s", self._session_name)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._read_once()
            except redis.exceptions.ConnectionError:
                # Transient. Sleep briefly via the Event so stop() is responsive.
                log.warning("consumer: redis connection error; retrying")
                if self._stop_event.wait(1.0):
                    return
            except Exception:  # noqa: BLE001
                log.exception("consumer loop iteration failed; continuing")
                if self._stop_event.wait(1.0):
                    return

    def _read_once(self) -> None:
        resp = self._client.xreadgroup(
            groupname=self._group,
            consumername=self._consumer_name,
            streams={self._stream: ">"},
            count=self._batch_count,
            block=self._block_ms,
        )
        if not resp:
            return
        for _stream_name, entries in resp:
            for msg_id, fields in entries:
                self._dispatch(msg_id, fields)

    def _dispatch(self, msg_id: str, fields: dict[str, str]) -> None:
        payload_raw = fields.get("payload")
        if payload_raw is None:
            log.warning(
                "consumer: dropping malformed message %s on %s (no payload)",
                msg_id,
                self._stream,
            )
            self._ack(msg_id)
            return
        try:
            payload = json.loads(payload_raw)
        except json.JSONDecodeError:
            log.warning(
                "consumer: dropping un-decodable JSON message %s on %s",
                msg_id,
                self._stream,
            )
            self._ack(msg_id)
            return
        if not isinstance(payload, dict):
            log.warning("consumer: dropping non-object payload in message %s", msg_id)
            self._ack(msg_id)
            return
        # Tag the message-id so the callback can store it for reply correlation.
        payload.setdefault("_msg_id", msg_id)
        try:
            self._on_message(payload)
        except Exception:  # noqa: BLE001
            # Callback failed. Don't ack; leave message in PEL for re-delivery.
            log.exception(
                "consumer: on_message callback failed for %s; leaving unacked",
                msg_id,
            )
            return
        self._ack(msg_id)

    def _ack(self, msg_id: str) -> None:
        try:
            self._client.xack(self._stream, self._group, msg_id)
        except Exception:  # noqa: BLE001
            log.exception("consumer: xack failed for %s", msg_id)
