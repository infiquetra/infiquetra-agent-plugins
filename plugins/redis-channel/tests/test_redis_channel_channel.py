"""Tests for the redis-channel MCP server's ServerState (connect/disconnect/list).

We test the ServerState class directly rather than going through FastMCP —
that exercises every real component (registry loading, redis client wrapper,
Presence lifecycle, stale-GC) while keeping the test surface simple. The
FastMCP wrapper is mostly glue and is exercised manually via the build_app
smoke check.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fakeredis")
pytest.importorskip("mcp.server.fastmcp")
pytest.importorskip("redis")

import fakeredis
from server import channel, presence  # type: ignore[import-not-found]


@pytest.fixture
def fr() -> Any:
    # Returns the real fakeredis client; typed as Any so redis-py's
    # Awaitable[X] | X return types don't propagate into the tests.
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def registry_file(tmp_path: Path) -> Path:
    p = tmp_path / "registry.json"
    p.write_text(
        json.dumps(
            {
                "endpoints": {
                    "mimir": {
                        "redis_url": "redis://test:6379/0",
                        "redis_password_env": None,
                        "display_name": "Mimir (test)",
                    }
                },
                "defaults": {
                    "heartbeat_seconds": 1,
                    "registry_ttl_seconds": 10,
                },
            }
        ),
        encoding="utf-8",
    )
    return p


@pytest.fixture
def patched_state(
    monkeypatch: pytest.MonkeyPatch,
    fr: Any,
    registry_file: Path,
) -> channel.ServerState:
    """Build a ServerState whose Redis connect returns the fakeredis instance,
    and whose load_registry reads from our temp file."""

    def fake_load_registry() -> Any:
        from server import registry as registry_mod  # type: ignore[import-not-found]

        return registry_mod.load_registry(registry_file)

    def fake_connect(_endpoint: Any) -> Any:
        return fr

    monkeypatch.setattr(channel, "load_registry", fake_load_registry)
    monkeypatch.setattr(channel, "redis_connect", fake_connect)
    return channel.ServerState()


def test_connect_registers_and_starts_heartbeat(
    patched_state: channel.ServerState, fr: Any
) -> None:
    out = patched_state.connect(endpoint="mimir", session_name="my-session")
    try:
        assert out["ok"] is True
        assert out["session_name"] == "my-session"
        assert out["endpoint"] == "mimir"
        assert out["endpoint_display"] == "Mimir (test)"
        assert out["heartbeat_seconds"] == 1
        assert out["registry_ttl_seconds"] == 10
        # debug defaults to false; surfaced in response for slash command / coach
        assert out["debug"] is False
        # registry should have the entry
        raw = fr.hget(presence.REGISTRY_KEY, "my-session")
        assert raw is not None
        # hb key must exist
        assert fr.exists(presence.hb_key("my-session")) == 1
    finally:
        patched_state.disconnect()


def test_connect_debug_flag_propagates(patched_state: channel.ServerState, fr: Any) -> None:
    """debug=true must round-trip through connect response and ServerState."""
    out = patched_state.connect(endpoint="mimir", session_name="dbg", debug=True)
    try:
        assert out["debug"] is True
        assert patched_state.debug is True
    finally:
        patched_state.disconnect()
    # After disconnect, debug resets so a subsequent connect starts quiet.
    assert patched_state.debug is False


def test_connect_debug_flag_default_quiet(patched_state: channel.ServerState, fr: Any) -> None:
    """Omitting debug (default) must keep ServerState.debug == False."""
    out = patched_state.connect(endpoint="mimir", session_name="quiet")
    try:
        assert out["debug"] is False
        assert patched_state.debug is False
    finally:
        patched_state.disconnect()


def test_connect_uses_auto_name_when_omitted(patched_state: channel.ServerState, fr: Any) -> None:
    out = patched_state.connect(endpoint="mimir", session_name=None)
    try:
        assert out["ok"] is True
        # Auto-name format: <slug>-<8 hex>
        assert "-" in out["session_name"]
        suffix = out["session_name"].rsplit("-", 1)[1]
        assert len(suffix) == 8
    finally:
        patched_state.disconnect()


def test_disconnect_clears_state(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="bye")
    assert patched_state.is_connected
    out = patched_state.disconnect()
    assert out == {"ok": True, "was_connected": True, "session_name": "bye"}
    assert not patched_state.is_connected
    assert fr.hget(presence.REGISTRY_KEY, "bye") is None
    assert fr.exists(presence.hb_key("bye")) == 0


def test_disconnect_when_not_connected_is_idempotent(
    patched_state: channel.ServerState,
) -> None:
    out = patched_state.disconnect()
    assert out == {"ok": True, "was_connected": False}


def test_second_connect_replaces_first(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="first")
    patched_state.connect(endpoint="mimir", session_name="second")
    try:
        assert fr.hget(presence.REGISTRY_KEY, "first") is None
        assert fr.exists(presence.hb_key("first")) == 0
        assert fr.hget(presence.REGISTRY_KEY, "second") is not None
    finally:
        patched_state.disconnect()


def test_auto_name_disambiguates_on_collision(patched_state: channel.ServerState, fr: Any) -> None:
    """Two processes in the same cwd → second auto-name gets a pid suffix."""
    import os
    import socket
    import time as _time

    # Simulate another live CC session on this host at the same auto-name.
    other_pid = os.getpid() + 1
    other_name_components = [
        ("session_name", "example-project-9f3e2c1a"),
        ("host", socket.gethostname()),
        ("cwd", "/home/operator/example-project"),
        ("git_branch", "main"),
        ("started_at", 1.0),
        ("pid", other_pid),
        ("endpoint", "mimir"),
        ("extras", {}),
    ]
    other_payload = json.dumps(dict(other_name_components))
    fr.hset(presence.REGISTRY_KEY, "example-project-9f3e2c1a", other_payload)
    fr.set(
        presence.hb_key("example-project-9f3e2c1a"),
        str(_time.time()),
        ex=60,
    )

    # Monkey-patch resolve_session_name to return the SAME base name the seeded
    # entry uses — this simulates the cwd-hash collision deterministically.
    import server.session_id as session_id_mod  # type: ignore[import-not-found]

    real_resolve = session_id_mod.resolve_session_name

    def fake_resolve(override=None, **kw):  # noqa: ANN001
        if override is not None:
            return real_resolve(override, **kw)
        return "example-project-9f3e2c1a"

    import server.channel as channel_mod  # type: ignore[import-not-found]

    monkey_target = channel_mod  # connect() imports resolve_session_name into channel
    original = monkey_target.resolve_session_name
    monkey_target.resolve_session_name = fake_resolve  # type: ignore[assignment]
    try:
        out = patched_state.connect(endpoint="mimir", session_name=None)
        try:
            assert out["ok"] is True, out
            # Our session_name must NOT equal the seeded base — should be disambiguated
            assert out["session_name"] != "example-project-9f3e2c1a"
            assert out["session_name"].startswith("example-project-9f3e2c1a-")
            suffix = out["session_name"].rsplit("-", 1)[1]
            # Suffix is 4 hex chars of our pid
            assert len(suffix) == 4
            assert all(c in "0123456789abcdef" for c in suffix)
        finally:
            patched_state.disconnect()
    finally:
        monkey_target.resolve_session_name = original  # type: ignore[assignment]


def test_explicit_name_does_not_disambiguate(patched_state: channel.ServerState, fr: Any) -> None:
    """Explicit session_name = user intent → no disambiguation, replace semantics."""
    import socket
    import time as _time

    seeded_name = "explicit-name"
    other_payload = json.dumps(
        {
            "session_name": seeded_name,
            "host": socket.gethostname(),
            "cwd": "/whatever",
            "git_branch": None,
            "started_at": 1.0,
            "pid": 99999,
            "endpoint": "mimir",
            "extras": {},
        }
    )
    fr.hset(presence.REGISTRY_KEY, seeded_name, other_payload)
    fr.set(presence.hb_key(seeded_name), str(_time.time()), ex=60)

    out = patched_state.connect(endpoint="mimir", session_name=seeded_name)
    try:
        assert out["session_name"] == seeded_name  # exact match — no suffix
    finally:
        patched_state.disconnect()


def test_list_requires_connection(patched_state: channel.ServerState) -> None:
    out = patched_state.list_sessions()
    assert out["ok"] is False
    assert "not connected" in out["error"]


def test_list_returns_self(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="solo")
    try:
        out = patched_state.list_sessions()
        assert out["ok"] is True
        assert out["count"] == 1
        assert out["sessions"][0]["session_name"] == "solo"
        assert out["sessions"][0]["is_self"] is True
        assert out["endpoint"] == "mimir"
    finally:
        patched_state.disconnect()


def test_list_returns_other_live_sessions(patched_state: channel.ServerState, fr: Any) -> None:
    """Simulate another CC session by writing to the registry directly."""
    other_meta = presence.build_metadata(
        session_name="other-session",
        endpoint="mimir",
        cwd="/elsewhere",
        host="other-host",
        started_at=500.0,
    )
    fr.hset(presence.REGISTRY_KEY, "other-session", other_meta.to_json())
    fr.set(presence.hb_key("other-session"), "now", ex=60)

    patched_state.connect(endpoint="mimir", session_name="mine")
    try:
        out = patched_state.list_sessions()
        assert out["ok"] is True
        assert out["count"] == 2
        names = {s["session_name"] for s in out["sessions"]}
        assert names == {"mine", "other-session"}
        self_flags = {s["session_name"]: s["is_self"] for s in out["sessions"]}
        assert self_flags == {"mine": True, "other-session": False}
        # ordered by started_at ascending (other was 500.0)
        assert out["sessions"][0]["session_name"] == "other-session"
    finally:
        patched_state.disconnect()


def test_list_gcs_stale_entries(patched_state: channel.ServerState, fr: Any) -> None:
    stale_meta = presence.build_metadata(
        session_name="ghost",
        endpoint="mimir",
        cwd="/gone",
        host="gone-host",
    )
    fr.hset(presence.REGISTRY_KEY, "ghost", stale_meta.to_json())
    # No hb key → stale.

    patched_state.connect(endpoint="mimir", session_name="alive")
    try:
        out = patched_state.list_sessions()
        assert {s["session_name"] for s in out["sessions"]} == {"alive"}
        # GC happened
        assert fr.hget(presence.REGISTRY_KEY, "ghost") is None
    finally:
        patched_state.disconnect()


def test_connect_with_missing_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When registry.json doesn't exist, connect returns a structured error."""

    def fake_load_registry() -> Any:
        from server import registry as registry_mod  # type: ignore[import-not-found]

        return registry_mod.load_registry(tmp_path / "absent.json")

    monkeypatch.setattr(channel, "load_registry", fake_load_registry)
    state = channel.ServerState()
    out = state.connect(endpoint="mimir", session_name=None)
    assert out["ok"] is False
    assert out["error"] == "registry not configured"
    assert "registry config not found" in out["detail"]
    assert "hint" in out


def test_connect_with_unknown_endpoint(patched_state: channel.ServerState) -> None:
    out = patched_state.connect(endpoint="nope", session_name=None)
    assert out["ok"] is False
    assert out["error"] == "endpoint not found"


def test_connect_with_invalid_session_name(
    patched_state: channel.ServerState,
) -> None:
    out = patched_state.connect(endpoint="mimir", session_name="UPPER CASE")
    assert out["ok"] is False
    assert out["error"] == "invalid argument"


def test_shutdown_disconnects_active_session(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="atexit-test")
    patched_state.shutdown()
    assert not patched_state.is_connected
    assert fr.hget(presence.REGISTRY_KEY, "atexit-test") is None


def test_build_app_smoke() -> None:
    """Verify FastMCP wiring constructs cleanly + registers all expected tools."""
    app = channel.build_app()
    # FastMCP exposes registered tools via a _tool_manager or tools attribute,
    # depending on version. Try both; if neither exists we just ensure the
    # call didn't raise.
    tool_names: set[str] = set()
    tm = getattr(app, "_tool_manager", None)
    if tm is not None:
        tool_names = set(getattr(tm, "_tools", {}).keys())
    elif hasattr(app, "tools"):
        tool_names = {t.name for t in app.tools}
    if tool_names:
        expected = {
            "redis_channel_connect",
            "redis_channel_disconnect",
            "redis_channel_list",
            "reply",
        }
        assert expected <= tool_names


# ─── Phase 2 additions: consumer + reply ────────────────────────────────────


import threading  # noqa: E402
import time as _time  # noqa: E402

from server import notifier as notifier_mod  # noqa: E402, type: ignore[import-not-found]
from server import redis_consumer, redis_producer  # noqa: E402, type: ignore[import-not-found]


def test_connect_attaches_inbound_consumer(patched_state: channel.ServerState, fr: Any) -> None:
    """A message XADD'd to inbound after connect reaches the notifier."""
    rec = notifier_mod.RecordingNotifier()
    out = patched_state.connect(endpoint="mimir", session_name="with-consumer", notifier=rec)
    try:
        assert out["ok"] is True
        assert out["consumer_attached"] is True
        assert out["notifier_kind"] == "RecordingNotifier"

        # Simulate the router writing an inbound message
        stream = redis_consumer.inbound_stream("with-consumer")
        msg_id = fr.xadd(
            stream, {"payload": json.dumps({"text": "hi from router", "chat_id": "c1"})}
        )

        # Wait for the consumer thread to dispatch
        for _ in range(30):
            if rec.emitted:
                break
            _time.sleep(0.1)
        assert len(rec.emitted) == 1
        # RecordingNotifier records the post-translation channel-notification
        # shape: {content: <text>, meta: {<identifier-safe fields...>}}
        params = rec.emitted[0]
        assert params["content"] == "hi from router"
        assert params["meta"]["chat_id"] == "c1"
        assert params["meta"]["_msg_id"] == msg_id
    finally:
        patched_state.disconnect()


def test_disconnect_stops_consumer(patched_state: channel.ServerState, fr: Any) -> None:
    rec = notifier_mod.RecordingNotifier()
    patched_state.connect(endpoint="mimir", session_name="stop-test", notifier=rec)
    patched_state.disconnect()

    # Find any thread named redis-channel-consumer-stop-test — should be gone
    matches = [t for t in threading.enumerate() if "consumer-stop-test" in t.name]
    assert matches == [] or not any(t.is_alive() for t in matches)


def test_second_connect_replaces_consumer(patched_state: channel.ServerState, fr: Any) -> None:
    rec1 = notifier_mod.RecordingNotifier()
    patched_state.connect(endpoint="mimir", session_name="first", notifier=rec1)
    rec2 = notifier_mod.RecordingNotifier()
    patched_state.connect(endpoint="mimir", session_name="second", notifier=rec2)
    try:
        # Write to second's inbound — only rec2 sees it
        stream = redis_consumer.inbound_stream("second")
        fr.xadd(stream, {"payload": json.dumps({"text": "for second"})})
        for _ in range(30):
            if rec2.emitted:
                break
            _time.sleep(0.1)
        # rec emits in channel-notification shape: {content, meta}
        assert any(p["content"] == "for second" for p in rec2.emitted)
        assert rec1.emitted == []
    finally:
        patched_state.disconnect()


def test_reply_xadds_to_outbound(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="reply-test")
    try:
        out = patched_state.reply(
            chat_id="c-discord-123",
            text="hello back",
            voice=False,
        )
        assert out["ok"] is True
        assert out["session_name"] == "reply-test"
        assert out["chat_id"] == "c-discord-123"
        msg_id = out["msg_id"]
        # Now read the outbound stream to verify
        entries = fr.xrange(redis_producer.outbound_stream("reply-test"))
        assert len(entries) == 1
        written_id, fields = entries[0]
        assert written_id == msg_id
        payload = json.loads(fields["payload"])
        assert payload["session_name"] == "reply-test"
        assert payload["endpoint"] == "mimir"
        assert payload["chat_id"] == "c-discord-123"
        assert payload["text"] == "hello back"
        assert payload["voice"] is False
    finally:
        patched_state.disconnect()


def test_reply_propagates_voice_flag(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="voice-reply")
    try:
        patched_state.reply(chat_id="vc-1", text="speak this", voice=True)
        entries = fr.xrange(redis_producer.outbound_stream("voice-reply"))
        payload = json.loads(entries[0][1]["payload"])
        assert payload["voice"] is True
    finally:
        patched_state.disconnect()


def test_reply_in_reply_to(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="thread-reply")
    try:
        patched_state.reply(
            chat_id="c1",
            text="answer",
            in_reply_to="1716000000000-0",
        )
        entries = fr.xrange(redis_producer.outbound_stream("thread-reply"))
        payload = json.loads(entries[0][1]["payload"])
        assert payload["in_reply_to"] == "1716000000000-0"
    finally:
        patched_state.disconnect()


def test_reply_when_not_connected(patched_state: channel.ServerState) -> None:
    out = patched_state.reply(chat_id="c1", text="hi")
    assert out["ok"] is False
    assert "not connected" in out["error"]


def test_reply_validates_empty_text(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="validate-empty")
    try:
        out = patched_state.reply(chat_id="c1", text="")
        assert out["ok"] is False
        assert out["error"] == "invalid argument"
        assert "text" in out["detail"]
        # Whitespace-only also rejected
        out2 = patched_state.reply(chat_id="c1", text="   \n  ")
        assert out2["ok"] is False
    finally:
        patched_state.disconnect()


def test_reply_validates_empty_chat_id(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="validate-chat")
    try:
        out = patched_state.reply(chat_id="", text="hi")
        assert out["ok"] is False
        assert out["error"] == "invalid argument"
        assert "chat_id" in out["detail"]
    finally:
        patched_state.disconnect()


# ─── Phase 2.5: auto-connect at MCP startup ─────────────────────────────────


def test_startup_register_eager_no_consumer(patched_state: channel.ServerState, fr: Any) -> None:
    """startup_register publishes presence + creates consumer group but
    does NOT start consumer thread (no MCP ctx yet at startup time)."""
    out = patched_state.startup_register(endpoint="mimir")
    try:
        assert out["ok"] is True
        assert out["consumer_attached"] is False
        assert out["notifier_kind"] is None
        # Presence (hb key) should be live
        assert fr.exists(presence.hb_key(out["session_name"])) == 1
        # Internal state: consumer is None until ensure_consumer_attached
        assert patched_state._consumer is None  # noqa: SLF001
        assert patched_state._notifier is None  # noqa: SLF001
        # Consumer group should already exist on the inbound stream so
        # XREADGROUP > later picks up anything XADD'd in the gap.
        from server.redis_consumer import (  # type: ignore[import-not-found]
            consumer_group,
            inbound_stream,
        )

        groups = fr.xinfo_groups(inbound_stream(out["session_name"]))
        group_names = {g["name"] for g in groups}
        assert consumer_group(out["session_name"]) in group_names
    finally:
        patched_state.disconnect()


def test_startup_register_idempotent_when_already_connected(
    patched_state: channel.ServerState, fr: Any
) -> None:
    """Calling startup_register a second time while connected is a no-op."""
    patched_state.connect(endpoint="mimir", session_name="sr-idem")
    try:
        out = patched_state.startup_register(endpoint="mimir")
        assert out["ok"] is True
        assert out.get("was_already_connected") is True
    finally:
        patched_state.disconnect()


def test_ensure_consumer_attached_lazy_starts_thread(
    patched_state: channel.ServerState, fr: Any
) -> None:
    """After startup_register, calling ensure_consumer_attached with a real
    notifier starts the consumer thread and wires the notifier in."""
    from server.notifier import NoopNotifier  # type: ignore[import-not-found]

    out = patched_state.startup_register(endpoint="mimir")
    try:
        assert patched_state._consumer is None  # noqa: SLF001
        attached = patched_state.ensure_consumer_attached(NoopNotifier())
        assert attached is True
        assert patched_state._consumer is not None  # noqa: SLF001
        # Second call is a no-op
        attached2 = patched_state.ensure_consumer_attached(NoopNotifier())
        assert attached2 is False
    finally:
        patched_state.disconnect()
        _ = out


def test_ensure_consumer_attached_noop_when_no_presence(
    patched_state: channel.ServerState,
) -> None:
    """ensure_consumer_attached without prior startup_register/connect is a
    no-op (returns False), not an error."""
    from server.notifier import NoopNotifier  # type: ignore[import-not-found]

    attached = patched_state.ensure_consumer_attached(NoopNotifier())
    assert attached is False
    assert patched_state._consumer is None  # noqa: SLF001


def test_maybe_auto_connect_gate_strict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_maybe_auto_connect only fires on literal '1'. 'true', 'yes', '0',
    empty, missing — all treated as off."""
    calls: list[str] = []

    def fake_startup_register(*, endpoint: str) -> dict[str, Any]:
        calls.append(endpoint)
        return {"ok": True, "session_name": "x"}

    monkeypatch.setattr(channel._STATE, "startup_register", fake_startup_register)
    monkeypatch.delenv("CLAUDE_CHANNEL_AUTO_CONNECT", raising=False)
    monkeypatch.delenv("CLAUDE_CHANNEL_ENDPOINT", raising=False)

    # missing → no call
    channel._maybe_auto_connect()
    assert calls == []

    # empty → no call
    monkeypatch.setenv("CLAUDE_CHANNEL_AUTO_CONNECT", "")
    channel._maybe_auto_connect()
    assert calls == []

    # "0" → no call
    monkeypatch.setenv("CLAUDE_CHANNEL_AUTO_CONNECT", "0")
    channel._maybe_auto_connect()
    assert calls == []

    # "true" → no call (strict; only "1")
    monkeypatch.setenv("CLAUDE_CHANNEL_AUTO_CONNECT", "true")
    channel._maybe_auto_connect()
    assert calls == []

    # "1" + endpoint via env → call
    monkeypatch.setenv("CLAUDE_CHANNEL_AUTO_CONNECT", "1")
    monkeypatch.setenv("CLAUDE_CHANNEL_ENDPOINT", "mimir")
    channel._maybe_auto_connect()
    assert calls == ["mimir"]


def test_maybe_auto_connect_no_endpoint_resolvable_continues(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When AUTO_CONNECT=1 but no endpoint resolvable (env unset, registry
    missing auto_connect_endpoint), log warning and continue without raising."""

    def fake_load_registry() -> Any:
        from server import registry as registry_mod  # type: ignore[import-not-found]

        return registry_mod.Registry(
            endpoints={},
            defaults=registry_mod.Defaults(),  # auto_connect_endpoint=None
            source=Path("/dev/null"),
        )

    monkeypatch.setattr(channel, "load_registry", fake_load_registry)
    monkeypatch.setenv("CLAUDE_CHANNEL_AUTO_CONNECT", "1")
    monkeypatch.delenv("CLAUDE_CHANNEL_ENDPOINT", raising=False)
    with caplog.at_level("WARNING", logger="redis_channel.channel"):
        channel._maybe_auto_connect()  # should not raise
    assert any("no endpoint resolvable" in r.message for r in caplog.records)


def test_maybe_auto_connect_registry_missing_continues(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """When AUTO_CONNECT=1, endpoint not in env, AND registry file missing,
    log warning and continue (don't crash the MCP server)."""
    from server import registry as registry_mod  # type: ignore[import-not-found]

    def raising_load() -> Any:
        raise registry_mod.RegistryNotFoundError("test-no-file")

    monkeypatch.setattr(channel, "load_registry", raising_load)
    monkeypatch.setenv("CLAUDE_CHANNEL_AUTO_CONNECT", "1")
    monkeypatch.delenv("CLAUDE_CHANNEL_ENDPOINT", raising=False)
    with caplog.at_level("WARNING", logger="redis_channel.channel"):
        channel._maybe_auto_connect()  # should not raise
    assert any("registry error" in r.message for r in caplog.records)


def test_maybe_auto_connect_falls_back_to_single_endpoint_convenience(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When AUTO_CONNECT=1 but neither env nor auto_connect_endpoint is set,
    and the registry has exactly ONE configured endpoint, fall through to
    resolve_default_endpoint's single-endpoint convenience and auto-connect
    to that endpoint. This is the common 'just works' path for solo setups
    where the user hasn't set auto_connect_endpoint explicitly."""
    from server import registry as registry_mod  # type: ignore[import-not-found]

    fake_endpoint = registry_mod.Endpoint(
        name="sole-endpoint",
        redis_url="redis://h:6379/0",
        redis_password_env=None,
        display_name="Sole",
    )
    fake_registry = registry_mod.Registry(
        endpoints={"sole-endpoint": fake_endpoint},
        defaults=registry_mod.Defaults(),  # default_endpoint="default"; auto_connect_endpoint=None
        source=Path("/dev/null"),
    )
    monkeypatch.setattr(channel, "load_registry", lambda: fake_registry)
    monkeypatch.setenv("CLAUDE_CHANNEL_AUTO_CONNECT", "1")
    monkeypatch.delenv("CLAUDE_CHANNEL_ENDPOINT", raising=False)

    calls: list[str] = []

    def fake_startup_register(*, endpoint: str) -> dict[str, Any]:
        calls.append(endpoint)
        return {"ok": True, "session_name": "x"}

    monkeypatch.setattr(channel._STATE, "startup_register", fake_startup_register)
    channel._maybe_auto_connect()
    assert calls == ["sole-endpoint"]


# ─── Phase 2.5: /redis-channel-status ───────────────────────────────────────


def test_status_disconnected(patched_state: channel.ServerState) -> None:
    out = patched_state.status()
    assert out == {"ok": True, "connected": False}


def test_status_connected_shape(patched_state: channel.ServerState, fr: Any) -> None:
    patched_state.connect(endpoint="mimir", session_name="status-test")
    try:
        out = patched_state.status()
        assert out["ok"] is True
        assert out["connected"] is True
        assert out["session_name"] == "status-test"
        assert out["endpoint"] == "mimir"
        assert "host" in out
        assert isinstance(out["uptime_seconds"], int)
        assert out["uptime_seconds"] >= 0
        assert out["consumer_attached"] is True
        # No inbound XADD'd yet → pending_inbound == 0
        assert out["pending_inbound"] == 0
    finally:
        patched_state.disconnect()


def test_status_after_startup_register_consumer_not_attached(
    patched_state: channel.ServerState, fr: Any
) -> None:
    """When auto-connect ran but no tool dispatch has happened, status
    should report consumer_attached=False."""
    out = patched_state.startup_register(endpoint="mimir")
    try:
        s = patched_state.status()
        assert s["connected"] is True
        assert s["consumer_attached"] is False
        assert s["session_name"] == out["session_name"]
    finally:
        patched_state.disconnect()


# ─── Phase 2.5 follow-up: /redis-channel-setup ──────────────────────────────


@pytest.fixture
def fake_plugin_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a fake plugin install layout in tmp_path with the scripts +
    docs files the setup tool reads from."""
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "docs").mkdir(parents=True)
    wrapper = plugin / "scripts" / "claude-channel.sh"
    wrapper.write_text("#!/bin/sh\necho fake\n")
    wrapper.chmod(0o755)
    (plugin / "docs" / "source-env.example.sh").write_text("#!/bin/sh\nexport FOO=bar\n")
    (plugin / "docs" / "registry.example.json").write_text('{"endpoints":{}}\n')
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin))
    return plugin


@pytest.fixture
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect HOME-relative paths used by setup to a temp dir so tests
    don't touch the user's real ~/bin or ~/.claude."""
    home = tmp_path / "home"
    home.mkdir()
    bin_dir = home / "bin"
    cfg_dir = home / ".claude" / "channels" / "redis-channel"
    monkeypatch.setattr(channel, "BIN_DIR", bin_dir)
    monkeypatch.setattr(channel, "WRAPPER_SYMLINK", bin_dir / "claude-channel")
    monkeypatch.setattr(channel, "CHANNEL_CONFIG_DIR", cfg_dir)
    return home


def test_setup_fresh_creates_symlink_and_configs(fake_plugin_root: Path, fake_home: Path) -> None:
    """First-time setup: symlink absent, configs absent → both created."""
    result = channel._do_setup(link_wrapper=True, scaffold_configs=True)
    assert result["ok"] is True

    symlink = fake_home / "bin" / "claude-channel"
    assert symlink.is_symlink()
    assert symlink.resolve() == (fake_plugin_root / "scripts" / "claude-channel.sh").resolve()

    cfg = fake_home / ".claude" / "channels" / "redis-channel"
    assert (cfg / "source-env.sh").exists()
    assert (cfg / "registry.json").exists()

    # State should now report all_ready
    assert result["state"]["all_ready"] is True

    statuses = [a["status"] for a in result["actions"]]
    assert "linked" in statuses
    assert statuses.count("created_from_example") == 2


def test_setup_preserves_existing_user_config(fake_plugin_root: Path, fake_home: Path) -> None:
    """Re-running setup must NOT overwrite an existing source-env.sh / registry."""
    cfg = fake_home / ".claude" / "channels" / "redis-channel"
    cfg.mkdir(parents=True)
    user_source = cfg / "source-env.sh"
    user_source.write_text("#!/bin/sh\n# user-customized\nexport MY_PWD=secret\n")
    user_registry = cfg / "registry.json"
    user_registry.write_text('{"endpoints":{"my":{"redis_url":"redis://r"}}}\n')
    user_source_content = user_source.read_text()
    user_registry_content = user_registry.read_text()

    result = channel._do_setup(link_wrapper=True, scaffold_configs=True)

    # User content untouched
    assert user_source.read_text() == user_source_content
    assert user_registry.read_text() == user_registry_content

    # Reported as exists (not overwritten)
    config_actions = [
        a
        for a in result["actions"]
        if "source-env" in a.get("target", "") or "registry" in a.get("target", "")
    ]
    for a in config_actions:
        assert a["status"] == "exists"


def test_setup_refreshes_stale_symlink(
    fake_plugin_root: Path, fake_home: Path, tmp_path: Path
) -> None:
    """If ~/bin/claude-channel points at an old cached version, setup
    overwrites it to point at the current plugin root."""
    symlink = fake_home / "bin" / "claude-channel"
    symlink.parent.mkdir(parents=True)
    stale_target = tmp_path / "old-cache" / "claude-channel.sh"
    stale_target.parent.mkdir(parents=True)
    stale_target.write_text("#!/bin/sh\necho stale\n")
    stale_target.chmod(0o755)
    symlink.symlink_to(stale_target)
    assert symlink.resolve() == stale_target.resolve()

    channel._do_setup(link_wrapper=True, scaffold_configs=False)

    # Symlink now points at the current plugin's wrapper
    assert symlink.is_symlink()
    assert symlink.resolve() == (fake_plugin_root / "scripts" / "claude-channel.sh").resolve()


def test_check_setup_reports_all_ready_only_when_complete(
    fake_plugin_root: Path, fake_home: Path
) -> None:
    """Sanity-check the state report drives the startup nag correctly."""
    # Nothing set up yet
    state = channel._check_setup()
    assert state["all_ready"] is False
    assert state["wrapper_symlink_status"] == "missing"

    # After full setup
    channel._do_setup(link_wrapper=True, scaffold_configs=True)
    state = channel._check_setup()
    assert state["all_ready"] is True
    assert state["wrapper_symlink_status"] == "current"
    assert state["source_env_exists"] is True
    assert state["registry_exists"] is True


def test_setup_skips_link_when_wrapper_not_in_plugin_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defensive: if CLAUDE_PLUGIN_ROOT points somewhere with no
    scripts/claude-channel.sh, the link action is skipped with a clear reason
    (don't link to a broken target)."""
    bogus_root = tmp_path / "bogus"
    bogus_root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(bogus_root))
    bin_dir = tmp_path / "bin"
    monkeypatch.setattr(channel, "BIN_DIR", bin_dir)
    monkeypatch.setattr(channel, "WRAPPER_SYMLINK", bin_dir / "claude-channel")

    result = channel._do_setup(link_wrapper=True, scaffold_configs=False)
    link_actions = [a for a in result["actions"] if "claude-channel" in a.get("target", "")]
    assert len(link_actions) == 1
    assert link_actions[0]["status"] == "skipped"
    assert (bin_dir / "claude-channel").is_symlink() is False


def test_setup_nag_logs_when_state_incomplete(
    fake_home: Path,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """_log_setup_nag emits a WARNING when setup is incomplete."""
    # No plugin root, no symlink, no configs
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.setattr(
        channel,
        "_check_setup",
        lambda: {
            "all_ready": False,
            "wrapper_symlink_status": "missing",
            "wrapper_symlink_expected_target": "/x",
            "source_env_path": "/y",
            "source_env_exists": False,
            "registry_path": "/z",
            "registry_exists": False,
        },
    )
    with caplog.at_level("WARNING", logger="redis_channel.channel"):
        channel._log_setup_nag()
    assert any("/redis-channel-setup" in r.message for r in caplog.records)


def test_setup_nag_silent_when_state_ready(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """_log_setup_nag stays quiet when everything is in order."""
    monkeypatch.setattr(channel, "_check_setup", lambda: {"all_ready": True})
    with caplog.at_level("WARNING", logger="redis_channel.channel"):
        channel._log_setup_nag()
    assert not any("/redis-channel-setup" in r.message for r in caplog.records)


# ─── Phase 6: auto-refresh stale symlink (extends v0.4.14 startup nag) ────


def test_auto_refresh_skips_when_no_symlink(
    fake_home: Path,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No symlink → don't auto-create; nag still fires via _log_setup_nag."""
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    result = channel._auto_refresh_stale_symlink()
    assert result is None


def test_auto_refresh_skips_when_symlink_current(fake_plugin_root: Path, fake_home: Path) -> None:
    """If symlink already points at the running version's wrapper → no-op."""
    channel._do_setup(link_wrapper=True, scaffold_configs=False)
    symlink = fake_home / "bin" / "claude-channel"
    assert symlink.is_symlink()
    # Pre-condition: current.
    pre_state = channel._check_setup()
    assert pre_state["wrapper_symlink_status"] == "current"

    result = channel._auto_refresh_stale_symlink()
    assert result is None  # already current, nothing to do


def test_auto_refresh_fixes_stale_symlink_into_our_cache(
    fake_plugin_root: Path,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """If symlink points at an OLDER version under our plugin cache,
    refresh it to point at the running version's wrapper."""
    # Create a fake "old cached version" inside our cache marker path so it
    # passes the _is_our_plugin_cache_target check.
    cache_marker = tmp_path / "home" / ".claude/plugins/cache/infiquetra-plugins/redis-channel"
    old_version_dir = cache_marker / "0.4.5" / "scripts"
    old_version_dir.mkdir(parents=True)
    old_wrapper = old_version_dir / "claude-channel.sh"
    old_wrapper.write_text("#!/bin/sh\necho old\n")
    old_wrapper.chmod(0o755)
    # Patch Path.home() so _is_our_plugin_cache_target compares against
    # tmp_path/home, where our fake cache lives.
    monkeypatch.setattr(channel.Path, "home", lambda: tmp_path / "home")

    symlink = fake_home / "bin" / "claude-channel"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(old_wrapper)
    assert symlink.resolve() == old_wrapper.resolve()

    refreshed = channel._auto_refresh_stale_symlink()
    assert refreshed is not None
    new_target = fake_plugin_root / "scripts" / "claude-channel.sh"
    assert symlink.resolve() == new_target.resolve()


def test_auto_refresh_fixes_stale_symlink_into_agent_plugins_cache(
    fake_plugin_root: Path,
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The same refresh accepts the catalog's current marketplace name.

    ``infiquetra-plugins`` is the marketplace this package was imported from.
    ``infiquetra-agent-plugins`` is the marketplace Claude installs from here.
    """
    cache_marker = (
        tmp_path / "home" / ".claude/plugins/cache/infiquetra-agent-plugins/redis-channel"
    )
    old_version_dir = cache_marker / "0.5.2" / "scripts"
    old_version_dir.mkdir(parents=True)
    old_wrapper = old_version_dir / "claude-channel.sh"
    old_wrapper.write_text("#!/bin/sh\necho old\n")
    old_wrapper.chmod(0o755)
    monkeypatch.setattr(channel.Path, "home", lambda: tmp_path / "home")

    symlink = fake_home / "bin" / "claude-channel"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(old_wrapper)

    refreshed = channel._auto_refresh_stale_symlink()
    assert refreshed is not None
    new_target = fake_plugin_root / "scripts" / "claude-channel.sh"
    assert symlink.resolve() == new_target.resolve()


def test_auto_refresh_leaves_external_symlink_alone(
    fake_plugin_root: Path,
    fake_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If symlink points OUTSIDE our plugin cache (user customization,
    dev checkout, alternate install), don't touch it. The nag still fires
    via _log_setup_nag for the user to investigate."""
    monkeypatch.setattr(channel.Path, "home", lambda: tmp_path / "home")
    # External target outside our cache
    external = tmp_path / "elsewhere" / "claude-channel-custom.sh"
    external.parent.mkdir(parents=True)
    external.write_text("#!/bin/sh\necho custom\n")
    external.chmod(0o755)

    symlink = fake_home / "bin" / "claude-channel"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(external)

    result = channel._auto_refresh_stale_symlink()
    assert result is None
    # Symlink unchanged
    assert symlink.resolve() == external.resolve()


def test_auto_refresh_leaves_non_symlink_alone(
    fake_plugin_root: Path,  # noqa: ARG001
    fake_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If something is at ~/bin/claude-channel but isn't a symlink (user
    installed a real script there), leave it alone."""
    monkeypatch.setattr(channel.Path, "home", lambda: fake_home)
    bin_dir = fake_home / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    real_file = bin_dir / "claude-channel"
    real_file.write_text("#!/bin/sh\necho real_script\n")
    real_file.chmod(0o755)
    assert not real_file.is_symlink()

    result = channel._auto_refresh_stale_symlink()
    assert result is None
    # Still a real file, not a symlink
    assert not real_file.is_symlink()
    assert real_file.read_text() == "#!/bin/sh\necho real_script\n"


def test_log_setup_nag_auto_refreshes_and_logs_info(
    fake_plugin_root: Path,
    fake_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end: stale symlink into our cache → nag auto-refreshes +
    logs INFO; the WARNING about stale symlink does NOT fire afterward
    (state becomes 'current')."""
    cache_marker = tmp_path / "home" / ".claude/plugins/cache/infiquetra-plugins/redis-channel"
    old_version_dir = cache_marker / "0.4.5" / "scripts"
    old_version_dir.mkdir(parents=True)
    old_wrapper = old_version_dir / "claude-channel.sh"
    old_wrapper.write_text("#!/bin/sh\necho old\n")
    old_wrapper.chmod(0o755)
    monkeypatch.setattr(channel.Path, "home", lambda: tmp_path / "home")

    symlink = fake_home / "bin" / "claude-channel"
    symlink.parent.mkdir(parents=True, exist_ok=True)
    symlink.symlink_to(old_wrapper)

    # Also scaffold configs so source-env.sh + registry.json are present,
    # leaving symlink staleness as the ONLY issue.
    channel._do_setup(link_wrapper=False, scaffold_configs=True)

    with caplog.at_level("INFO", logger="redis_channel.channel"):
        channel._log_setup_nag()

    # Auto-refresh fired
    assert any("auto-refreshed" in r.message for r in caplog.records)
    # No "setup is incomplete" warning (state was fixed in-place)
    assert not any("setup is incomplete" in r.message for r in caplog.records)


# ─── Phase 6: /redis-channel-configure ─────────────────────────────────────


def test_configure_creates_fresh_registry(
    fake_home: Path,  # noqa: ARG001
) -> None:
    """Fresh: no existing registry.json → create it with the new endpoint."""
    result = channel._configure_endpoint(
        endpoint_name="default",
        redis_url="redis://host.example.com:6379/0",
        redis_password_env="MY_REDIS_PASSWORD",
        display_name="Default endpoint",
        set_default=True,
    )
    assert result["ok"] is True
    assert result["action"] == "created"
    assert result["endpoint_count"] == 1
    assert result["default_endpoint"] == "default"
    cfg_path = Path(result["written"])
    assert cfg_path.exists()
    data = json.loads(cfg_path.read_text())
    assert "default" in data["endpoints"]
    ep = data["endpoints"]["default"]
    assert ep["redis_url"] == "redis://host.example.com:6379/0"
    assert ep["redis_password_env"] == "MY_REDIS_PASSWORD"
    assert ep["display_name"] == "Default endpoint"
    assert data["defaults"]["default_endpoint"] == "default"


def test_configure_adds_second_endpoint_preserves_first(
    fake_home: Path,  # noqa: ARG001
) -> None:
    """Adding a second endpoint preserves the first + defaults."""
    channel._configure_endpoint(
        endpoint_name="prod",
        redis_url="redis://prod:6379/0",
        redis_password_env="PROD_PWD",
        set_default=True,
    )
    result = channel._configure_endpoint(
        endpoint_name="staging",
        redis_url="redis://staging:6379/0",
        redis_password_env="STAGING_PWD",
    )
    assert result["ok"] is True
    assert result["action"] == "created"
    assert result["endpoint_count"] == 2
    # Default still 'prod'
    assert result["default_endpoint"] == "prod"

    data = json.loads(Path(result["written"]).read_text())
    assert set(data["endpoints"]) == {"prod", "staging"}
    assert data["endpoints"]["prod"]["redis_url"] == "redis://prod:6379/0"
    assert data["endpoints"]["staging"]["redis_url"] == "redis://staging:6379/0"


def test_configure_updates_existing_endpoint(
    fake_home: Path,  # noqa: ARG001
) -> None:
    """Re-running configure for the same name overwrites + reports 'updated'."""
    channel._configure_endpoint(
        endpoint_name="default",
        redis_url="redis://old:6379/0",
        redis_password_env="OLD_PWD",
    )
    result = channel._configure_endpoint(
        endpoint_name="default",
        redis_url="redis://new:6379/0",
        redis_password_env="NEW_PWD",
        display_name="Renamed",
    )
    assert result["ok"] is True
    assert result["action"] == "updated"
    assert result["endpoint_count"] == 1
    data = json.loads(Path(result["written"]).read_text())
    assert data["endpoints"]["default"]["redis_url"] == "redis://new:6379/0"
    assert data["endpoints"]["default"]["redis_password_env"] == "NEW_PWD"
    assert data["endpoints"]["default"]["display_name"] == "Renamed"


def test_configure_rejects_invalid_endpoint_name(
    fake_home: Path,  # noqa: ARG001
) -> None:
    for bad in ["BadCaps", "-leading-dash", "spaces here", "", "_underscore_start"]:
        result = channel._configure_endpoint(
            endpoint_name=bad,
            redis_url="redis://h:6379/0",
        )
        assert result["ok"] is False, bad
        assert "invalid endpoint_name" in result["error"], bad


def test_configure_rejects_invalid_redis_url(
    fake_home: Path,  # noqa: ARG001
) -> None:
    for bad in ["http://h:6379", "h:6379/0", "", "ftp://h"]:
        result = channel._configure_endpoint(
            endpoint_name="x",
            redis_url=bad,
        )
        assert result["ok"] is False, bad
        assert "invalid redis_url" in result["error"], bad


def test_configure_normalizes_empty_password_env_to_none(
    fake_home: Path,  # noqa: ARG001
) -> None:
    """Empty string redis_password_env → omitted from the written entry."""
    result = channel._configure_endpoint(
        endpoint_name="noauth",
        redis_url="redis://h:6379/0",
        redis_password_env="   ",  # whitespace
    )
    assert result["ok"] is True
    data = json.loads(Path(result["written"]).read_text())
    assert "redis_password_env" not in data["endpoints"]["noauth"]


def test_configure_atomic_write_doesnt_leave_tmp(
    fake_home: Path,  # noqa: ARG001
) -> None:
    """No .tmp file should remain after a successful write."""
    result = channel._configure_endpoint(
        endpoint_name="x",
        redis_url="redis://h:6379/0",
    )
    cfg_path = Path(result["written"])
    tmp = cfg_path.with_suffix(".json.tmp")
    assert not tmp.exists()


def test_configure_rejects_malformed_existing_registry(
    fake_home: Path,  # noqa: ARG001
) -> None:
    """If existing registry.json is not valid JSON, surface a parse error +
    don't clobber it."""
    cfg_path = channel.CHANNEL_CONFIG_DIR / "registry.json"
    channel.CHANNEL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text("{ this is not json")
    before = cfg_path.read_text()

    result = channel._configure_endpoint(
        endpoint_name="x",
        redis_url="redis://h:6379/0",
    )
    assert result["ok"] is False
    assert "parse error" in result["error"]
    # Original content untouched
    assert cfg_path.read_text() == before
