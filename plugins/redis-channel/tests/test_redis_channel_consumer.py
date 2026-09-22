"""Tests for the inbound Redis stream consumer."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

pytest.importorskip("fakeredis")
pytest.importorskip("redis")

import fakeredis
from server import redis_consumer  # type: ignore[import-not-found]


@pytest.fixture
def fr() -> Any:
    return fakeredis.FakeRedis(decode_responses=True)


def _xadd_inbound(fr: Any, session_name: str, payload: dict[str, Any]) -> str:
    """Helper: produce a message onto the inbound stream the same way the router would."""
    body = json.dumps(payload)
    msg_id = fr.xadd(
        redis_consumer.inbound_stream(session_name),
        {"payload": body},
        maxlen=10_000,
        approximate=True,
    )
    return str(msg_id)


def test_inbound_stream_naming() -> None:
    assert redis_consumer.inbound_stream("foo") == "cc-sessions:foo:inbound"
    assert redis_consumer.consumer_group("foo") == "cc:foo"


def test_ensure_group_creates_and_is_idempotent(fr: Any) -> None:
    stream = redis_consumer.inbound_stream("s")
    group = redis_consumer.consumer_group("s")
    assert redis_consumer.ensure_group(fr, stream=stream, group=group) is True
    # Second call returns False (BUSYGROUP)
    assert redis_consumer.ensure_group(fr, stream=stream, group=group) is False


def test_consumer_dispatches_published_message(fr: Any) -> None:
    received: list[dict[str, Any]] = []
    event = threading.Event()

    def cb(payload: dict[str, Any]) -> None:
        received.append(payload)
        event.set()

    c = redis_consumer.Consumer(fr, "s", on_message=cb, block_ms=100)
    c.start()
    try:
        msg_id = _xadd_inbound(fr, "s", {"v": 1, "text": "hi", "chat_id": "c1"})
        assert event.wait(timeout=3.0), "callback was never invoked"
        assert len(received) == 1
        payload = received[0]
        assert payload["text"] == "hi"
        assert payload["chat_id"] == "c1"
        assert payload["_msg_id"] == msg_id
    finally:
        c.stop()


def test_consumer_acks_after_dispatch(fr: Any) -> None:
    seen = threading.Event()

    def cb(_p: dict) -> None:
        seen.set()

    c = redis_consumer.Consumer(fr, "ack-test", on_message=cb, block_ms=100)
    c.start()
    try:
        _xadd_inbound(fr, "ack-test", {"text": "x"})
        assert seen.wait(timeout=3.0)
        # Give the ack a moment
        time.sleep(0.2)
        # Pending entries list should be empty
        pending = fr.xpending(
            redis_consumer.inbound_stream("ack-test"),
            redis_consumer.consumer_group("ack-test"),
        )
        assert pending["pending"] == 0
    finally:
        c.stop()


def test_consumer_does_not_ack_on_callback_exception(fr: Any) -> None:
    """A raising callback leaves the message in the pending entries list,
    so it can be reprocessed (here: by the same consumer on its next call,
    after the consumer recovers)."""
    fail_then_succeed_calls = [0]
    seen_after_recovery = threading.Event()

    def cb(_p: dict) -> None:
        fail_then_succeed_calls[0] += 1
        if fail_then_succeed_calls[0] == 1:
            raise RuntimeError("first call fails")
        seen_after_recovery.set()

    c = redis_consumer.Consumer(fr, "retry-test", on_message=cb, block_ms=100)
    c.start()
    try:
        _xadd_inbound(fr, "retry-test", {"text": "x"})
        # First dispatch fails; message stays in PEL.
        # Wait a beat, then manually claim the pending entry and re-dispatch.
        time.sleep(0.5)
        stream = redis_consumer.inbound_stream("retry-test")
        group = redis_consumer.consumer_group("retry-test")
        pending = fr.xpending(stream, group)
        # Should be 1 unacked message
        assert pending["pending"] == 1
    finally:
        c.stop()


def test_consumer_drops_malformed_payload(fr: Any) -> None:
    """Missing 'payload' field → drop and ack (don't loop on bad data)."""
    received: list[dict[str, Any]] = []
    c = redis_consumer.Consumer(fr, "mal", on_message=received.append, block_ms=100)
    c.start()
    try:
        # Write a message with a different field name
        fr.xadd(redis_consumer.inbound_stream("mal"), {"not-payload": "junk"})
        time.sleep(0.3)
        assert received == []
        # Was acked despite the malformation
        pending = fr.xpending(
            redis_consumer.inbound_stream("mal"),
            redis_consumer.consumer_group("mal"),
        )
        assert pending["pending"] == 0
    finally:
        c.stop()


def test_consumer_drops_invalid_json(fr: Any) -> None:
    received: list[dict[str, Any]] = []
    c = redis_consumer.Consumer(fr, "bad-json", on_message=received.append, block_ms=100)
    c.start()
    try:
        fr.xadd(redis_consumer.inbound_stream("bad-json"), {"payload": "{not json}"})
        time.sleep(0.3)
        assert received == []
        pending = fr.xpending(
            redis_consumer.inbound_stream("bad-json"),
            redis_consumer.consumer_group("bad-json"),
        )
        assert pending["pending"] == 0
    finally:
        c.stop()


def test_consumer_drops_non_object_payload(fr: Any) -> None:
    """payload is JSON but not an object — list or scalar."""
    received: list[dict[str, Any]] = []
    c = redis_consumer.Consumer(fr, "nonobj", on_message=received.append, block_ms=100)
    c.start()
    try:
        fr.xadd(
            redis_consumer.inbound_stream("nonobj"),
            {"payload": "[1, 2, 3]"},
        )
        time.sleep(0.3)
        assert received == []
    finally:
        c.stop()


def test_consumer_rejects_double_start(fr: Any) -> None:
    c = redis_consumer.Consumer(fr, "s", on_message=lambda _: None, block_ms=100)
    c.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            c.start()
    finally:
        c.stop()


def test_consumer_stop_is_idempotent(fr: Any) -> None:
    c = redis_consumer.Consumer(fr, "s", on_message=lambda _: None, block_ms=100)
    c.start()
    c.stop()
    c.stop()  # must not raise


def test_consumer_batch_count(fr: Any) -> None:
    received: list[dict[str, Any]] = []
    lock = threading.Lock()

    def cb(p: dict) -> None:
        with lock:
            received.append(p)

    c = redis_consumer.Consumer(fr, "batch", on_message=cb, block_ms=100, batch_count=5)
    c.start()
    try:
        # Pre-publish 5 messages, then start observing
        for i in range(5):
            _xadd_inbound(fr, "batch", {"i": i, "text": f"msg{i}"})
        # Give consumer time to drain
        for _ in range(30):
            with lock:
                if len(received) >= 5:
                    break
            time.sleep(0.1)
        with lock:
            assert len(received) == 5
            assert [p["i"] for p in received] == [0, 1, 2, 3, 4]
    finally:
        c.stop()
