"""Outbound Redis stream producer for redis-channel.

XADDs JSON-encoded payloads onto `cc-sessions:<session_name>:outbound`.
Stream length is capped via MAXLEN ~ to avoid unbounded growth on a
session whose consumer is slow or absent.
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

OUTBOUND_STREAM_FMT = "cc-sessions:{session_name}:outbound"
DEFAULT_MAXLEN = 10_000


def outbound_stream(session_name: str) -> str:
    return OUTBOUND_STREAM_FMT.format(session_name=session_name)


def publish_outbound(
    client: Any,
    session_name: str,
    payload: dict[str, Any],
    *,
    maxlen: int = DEFAULT_MAXLEN,
) -> str:
    """XADD a payload to the outbound stream. Returns the assigned message ID.

    The full payload is JSON-encoded into a single `payload` field. We
    intentionally do NOT spread the payload across multiple Redis fields:
    keeping it as one opaque blob mirrors the inbound contract and means
    consumers don't have to special-case field-set differences.
    """
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    raw_id = client.xadd(
        outbound_stream(session_name),
        {"payload": body},
        maxlen=maxlen,
        approximate=True,
    )
    msg_id = str(raw_id)
    log.debug(
        "published outbound msg %s on session=%s len=%d",
        msg_id,
        session_name,
        len(body),
    )
    return msg_id
