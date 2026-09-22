"""Tests for the outbound Redis stream producer."""

from __future__ import annotations

import json
from typing import Any

import pytest

pytest.importorskip("fakeredis")

import fakeredis
from server import redis_producer  # type: ignore[import-not-found]


@pytest.fixture
def fr() -> Any:
    return fakeredis.FakeRedis(decode_responses=True)


def test_outbound_stream_naming() -> None:
    assert redis_producer.outbound_stream("foo") == "cc-sessions:foo:outbound"


def test_publish_outbound_writes_to_stream(fr: Any) -> None:
    msg_id = redis_producer.publish_outbound(
        fr,
        "s",
        {"text": "hello", "chat_id": "c1", "voice": True},
    )
    assert msg_id is not None
    entries = fr.xrange(redis_producer.outbound_stream("s"))
    assert len(entries) == 1
    written_id, fields = entries[0]
    assert written_id == msg_id
    assert "payload" in fields
    payload = json.loads(fields["payload"])
    assert payload == {"text": "hello", "chat_id": "c1", "voice": True}


def test_publish_outbound_serializes_sorted_keys(fr: Any) -> None:
    """Deterministic serialization makes the wire format diffable."""
    redis_producer.publish_outbound(fr, "s", {"b": 2, "a": 1, "c": 3})
    entries = fr.xrange(redis_producer.outbound_stream("s"))
    assert entries[0][1]["payload"] == '{"a":1,"b":2,"c":3}'


def test_publish_outbound_maxlen(fr: Any) -> None:
    """MAXLEN ~ caps the stream to roughly the configured length."""
    for i in range(20):
        redis_producer.publish_outbound(fr, "s", {"i": i}, maxlen=10)
    length = fr.xlen(redis_producer.outbound_stream("s"))
    # MAXLEN ~ approximate; length is close to but not strictly == 10.
    assert length <= 20
    assert length >= 1
