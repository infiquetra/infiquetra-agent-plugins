"""Tests for the channel-notification emitters + inbound→channel translation."""

from __future__ import annotations

import asyncio
import threading

import pytest

pytest.importorskip("mcp.types")

from server import notifier  # type: ignore[import-not-found]

# ─── inbound_to_channel_params translation ─────────────────────────────────


def test_translate_minimal_text_only() -> None:
    out = notifier.inbound_to_channel_params({"text": "hi"})
    assert out == {"content": "hi", "meta": {}}


def test_translate_full_inbound_payload() -> None:
    payload = {
        "v": 1,
        "router": "test-router",
        "endpoint": "mimir",
        "source": "dm",
        "chat_id": "c-1",
        "user_id": "u-1",
        "username": "jeff",
        "text": "hello",
        "ts": 1234.5,
        "_msg_id": "1234567890-0",
    }
    out = notifier.inbound_to_channel_params(payload)
    assert out["content"] == "hello"
    # `v` and `text` are dropped from meta
    assert "v" not in out["meta"]
    assert "text" not in out["meta"]
    # Other fields stringified
    assert out["meta"]["router"] == "test-router"
    assert out["meta"]["endpoint"] == "mimir"
    assert out["meta"]["source"] == "dm"
    assert out["meta"]["chat_id"] == "c-1"
    assert out["meta"]["user_id"] == "u-1"
    assert out["meta"]["username"] == "jeff"
    assert out["meta"]["ts"] == "1234.5"
    assert out["meta"]["_msg_id"] == "1234567890-0"


def test_translate_drops_none_values() -> None:
    out = notifier.inbound_to_channel_params({"text": "x", "chat_id": "c", "confidence": None})
    assert out["meta"] == {"chat_id": "c"}


def test_translate_drops_nested_values() -> None:
    """meta is a flat string map; dicts and lists must not be flattened in."""
    out = notifier.inbound_to_channel_params(
        {"text": "x", "metadata": {"deep": "value"}, "tags": ["a", "b"]}
    )
    assert out["meta"] == {}


def test_translate_drops_non_identifier_keys() -> None:
    """Per the channel docs, keys with hyphens/other chars are silently dropped."""
    out = notifier.inbound_to_channel_params(
        {"text": "x", "user-id": "skipped", "user.foo": "skipped", "user_id": "kept"}
    )
    assert out["meta"] == {"user_id": "kept"}


def test_translate_handles_missing_text() -> None:
    out = notifier.inbound_to_channel_params({"chat_id": "c"})
    assert out["content"] == ""
    assert out["meta"] == {"chat_id": "c"}


def test_translate_numeric_values_stringified() -> None:
    out = notifier.inbound_to_channel_params(
        {"text": "x", "confidence": 0.92, "ts": 1779741709.123}
    )
    assert out["meta"]["confidence"] == "0.92"
    assert out["meta"]["ts"] == "1779741709.123"


def test_translate_bool_values_stringified() -> None:
    out = notifier.inbound_to_channel_params({"text": "x", "voice": True})
    assert out["meta"]["voice"] == "True"


# ─── notifiers ─────────────────────────────────────────────────────────────


def test_recording_notifier_translates() -> None:
    """RecordingNotifier should record the post-translation channel params,
    so tests assert on the same shape AsyncNotifier sends on the wire."""
    n = notifier.RecordingNotifier()
    n.emit({"text": "hi", "chat_id": "c1"})
    assert n.emitted == [{"content": "hi", "meta": {"chat_id": "c1"}}]


def test_recording_notifier_threadsafe() -> None:
    n = notifier.RecordingNotifier()

    def _hammer() -> None:
        for i in range(50):
            n.emit({"text": str(i), "chat_id": "c"})

    threads = [threading.Thread(target=_hammer) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(n.emitted) == 500


def test_noop_notifier_drops_silently() -> None:
    n = notifier.NoopNotifier()
    n.emit({"any": "payload"})  # no exception, no observable effect


def test_async_notifier_schedules_coroutine() -> None:
    """AsyncNotifier.emit() translates + schedules send_notification."""

    sent: list = []

    class StubSession:
        async def send_notification(self, notif):  # noqa: ANN001
            sent.append(notif)

    loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=loop.run_forever, daemon=True)
    loop_thread.start()
    try:
        n = notifier.AsyncNotifier(StubSession(), loop)
        n.emit({"text": "hello", "chat_id": "c1", "source": "dm"})
        # Give the loop a tick to process
        for _ in range(50):
            if sent:
                break
            import time

            time.sleep(0.02)
        assert len(sent) == 1
        notif = sent[0]
        assert notif.method == notifier.CHANNEL_NOTIFICATION_METHOD
        # Post-translation shape: {content, meta}
        assert notif.params == {
            "content": "hello",
            "meta": {"chat_id": "c1", "source": "dm"},
        }
    finally:
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2.0)
        loop.close()


def test_async_notifier_swallows_loop_errors() -> None:
    """If the loop is closed at emit time, emit() must not raise."""
    loop = asyncio.new_event_loop()
    loop.close()  # close before emit so run_coroutine_threadsafe raises

    class StubSession:
        async def send_notification(self, notif):  # noqa: ANN001
            pass

    n = notifier.AsyncNotifier(StubSession(), loop)
    # Should not raise
    n.emit({"text": "should be dropped"})


def test_channel_method_constant() -> None:
    assert notifier.CHANNEL_NOTIFICATION_METHOD == "notifications/claude/channel"
