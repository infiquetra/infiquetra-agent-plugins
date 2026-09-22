"""Tests for redis-channel presence (registry HSET + heartbeat thread).

Uses fakeredis to model the Redis backend so tests run without a server.
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

pytest.importorskip("fakeredis")

import fakeredis
from server import presence  # type: ignore[import-not-found]


# Return type is Any (not fakeredis.FakeRedis) so redis-py's wide
# Awaitable[X] | X union return types don't poison every call site.
# Runtime is the real fakeredis client; only typing is loosened.
@pytest.fixture
def fr() -> Any:
    return fakeredis.FakeRedis(decode_responses=True)


def make_meta(name: str = "test-abc") -> presence.SessionMetadata:
    return presence.build_metadata(
        session_name=name,
        endpoint="mimir",
        cwd="/tmp/proj",
        host="testhost",
        git_branch="main",
        started_at=1000.0,
    )


def test_session_metadata_round_trip() -> None:
    meta = make_meta()
    body = meta.to_json()
    restored = presence.SessionMetadata.from_json(body)
    assert restored == meta


def test_build_metadata_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "time", lambda: 1234.5)
    meta = presence.build_metadata(session_name="x", endpoint="mimir")
    assert meta.session_name == "x"
    assert meta.endpoint == "mimir"
    assert meta.started_at == 1234.5
    assert meta.pid > 0
    assert meta.host  # non-empty
    assert meta.cwd  # non-empty


# ─── git_branch auto-detection ──────────────────────────────────────────────


def test_detect_git_branch_non_git_dir_returns_none(tmp_path) -> None:
    assert presence.detect_git_branch(str(tmp_path)) is None


def test_detect_git_branch_missing_cwd_returns_none(tmp_path) -> None:
    assert presence.detect_git_branch(str(tmp_path / "does-not-exist")) is None


def test_detect_git_branch_real_repo(tmp_path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
    )
    assert presence.detect_git_branch(str(tmp_path)) == "main"


def test_detect_git_branch_feature_branch(tmp_path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "checkout", "-q", "-b", "feature/x"], cwd=tmp_path, check=True)
    assert presence.detect_git_branch(str(tmp_path)) == "feature/x"


def test_detect_git_branch_detached_head_returns_none(tmp_path) -> None:
    """Detached HEAD ("HEAD" string) is mapped to None — no branch context."""
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
    )
    # Detach HEAD by checking out the commit SHA
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "--detach", sha], cwd=tmp_path, check=True)
    assert presence.detect_git_branch(str(tmp_path)) is None


def test_build_metadata_auto_detects_git_branch(tmp_path) -> None:
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "auth-feature"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "initial",
        ],
        cwd=tmp_path,
        check=True,
    )
    meta = presence.build_metadata(session_name="s", endpoint="mimir", cwd=str(tmp_path))
    assert meta.git_branch == "auth-feature"


def test_build_metadata_explicit_git_branch_overrides_detection(tmp_path) -> None:
    """Caller-supplied git_branch wins over detection (useful for tests + the
    rare case where an external runner already knows the branch)."""
    import subprocess

    subprocess.run(["git", "init", "-q", "-b", "actually-on-this"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "i",
        ],
        cwd=tmp_path,
        check=True,
    )
    meta = presence.build_metadata(
        session_name="s",
        endpoint="mimir",
        cwd=str(tmp_path),
        git_branch="overridden",
    )
    assert meta.git_branch == "overridden"


# ─── disambiguation for same-cwd collisions ─────────────────────────────────


def _seed_other_session(
    fr: Any, name: str, *, host: str = "other-host", pid: int = 999, ttl: int = 60
) -> None:
    """Helper: write a presence entry for some *other* session at `name`."""
    other = presence.build_metadata(
        session_name=name,
        endpoint="mimir",
        cwd="/somewhere",
        host=host,
        git_branch="other-branch",
        started_at=500.0,
    )
    # build_metadata sets pid=os.getpid(); we want to fake a different pid
    raw = json.loads(other.to_json())
    raw["pid"] = pid
    fr.hset(presence.REGISTRY_KEY, name, json.dumps(raw))
    fr.set(presence.hb_key(name), str(time.time()), ex=ttl)


def test_disambiguate_no_existing_entry(fr: Any) -> None:
    name = presence.disambiguate_if_collision(fr, "myrepo-abc12345", host="h", pid=1234)
    assert name == "myrepo-abc12345"


def test_disambiguate_same_pid_same_host_returns_base(fr: Any) -> None:
    """Reconnect scenario: same process re-registering should keep the same name."""
    _seed_other_session(fr, "myrepo-abc12345", host="same-host", pid=1234)
    name = presence.disambiguate_if_collision(fr, "myrepo-abc12345", host="same-host", pid=1234)
    assert name == "myrepo-abc12345"


def test_disambiguate_different_pid_same_host_appends_suffix(fr: Any) -> None:
    """Same cwd, same host, different process — must disambiguate."""
    _seed_other_session(fr, "myrepo-abc12345", host="same-host", pid=999)
    name = presence.disambiguate_if_collision(fr, "myrepo-abc12345", host="same-host", pid=0x4321)
    assert name == "myrepo-abc12345-4321"


def test_disambiguate_different_host_also_appends_suffix(fr: Any) -> None:
    """If host differs, the base auto-name shouldn't have collided in the first
    place (host is in the hash). But if it does (manual config), still disambiguate."""
    _seed_other_session(fr, "myrepo-abc12345", host="host-a", pid=999)
    name = presence.disambiguate_if_collision(fr, "myrepo-abc12345", host="host-b", pid=0xABCD)
    assert name == "myrepo-abc12345-abcd"


def test_disambiguate_short_pid_zero_pads(fr: Any) -> None:
    _seed_other_session(fr, "n", host="h", pid=1)
    name = presence.disambiguate_if_collision(fr, "n", host="h", pid=0x12)
    assert name == "n-0012"


def test_disambiguate_stale_entry_returns_base(fr: Any) -> None:
    """Registry has an entry but hb key expired → not a live collision."""
    other = presence.build_metadata(
        session_name="ghost",
        endpoint="mimir",
        cwd="/gone",
        host="h",
        started_at=1.0,
    )
    fr.hset(presence.REGISTRY_KEY, "ghost", other.to_json())
    # no hb key
    name = presence.disambiguate_if_collision(fr, "ghost", host="h", pid=1)
    assert name == "ghost"


def test_disambiguate_missing_registry_entry_returns_base(fr: Any) -> None:
    """Half-state: hb key exists but registry HSET is missing. Take the name."""
    fr.set(presence.hb_key("orphan-hb"), "12345", ex=60)
    name = presence.disambiguate_if_collision(fr, "orphan-hb", host="h", pid=1)
    assert name == "orphan-hb"


def test_disambiguate_corrupt_registry_entry_returns_base(fr: Any) -> None:
    fr.hset(presence.REGISTRY_KEY, "broken", "{ not valid json")
    fr.set(presence.hb_key("broken"), "12345", ex=60)
    name = presence.disambiguate_if_collision(fr, "broken", host="h", pid=1)
    assert name == "broken"


def test_presence_start_writes_registry_and_hb(fr: Any) -> None:
    meta = make_meta()
    p = presence.Presence(fr, meta, heartbeat_seconds=1, ttl_seconds=10)
    p.start()
    try:
        raw = fr.hget(presence.REGISTRY_KEY, meta.session_name)
        assert raw is not None
        assert presence.SessionMetadata.from_json(raw) == meta
        assert fr.exists(presence.hb_key(meta.session_name)) == 1
        # TTL should be roughly the configured value.
        assert 1 <= fr.ttl(presence.hb_key(meta.session_name)) <= 10
    finally:
        p.stop()


def test_presence_stop_cleans_up(fr: Any) -> None:
    meta = make_meta()
    p = presence.Presence(fr, meta, heartbeat_seconds=1, ttl_seconds=10)
    p.start()
    p.stop()
    assert fr.hget(presence.REGISTRY_KEY, meta.session_name) is None
    assert fr.exists(presence.hb_key(meta.session_name)) == 0


def test_presence_stop_drops_session_streams(fr: Any) -> None:
    """Graceful disconnect must DEL inbound + outbound streams so they don't
    accumulate one pair per ever-disconnected session."""
    meta = make_meta("with-streams")
    p = presence.Presence(fr, meta, heartbeat_seconds=1, ttl_seconds=10)
    p.start()
    fr.xadd("cc-sessions:with-streams:inbound", {"payload": "{}"})
    fr.xadd("cc-sessions:with-streams:outbound", {"payload": "{}"})
    assert fr.exists("cc-sessions:with-streams:inbound") == 1
    assert fr.exists("cc-sessions:with-streams:outbound") == 1
    p.stop()
    assert fr.exists("cc-sessions:with-streams:inbound") == 0
    assert fr.exists("cc-sessions:with-streams:outbound") == 0


def test_session_stream_keys_layout() -> None:
    """The session_stream_keys helper enumerates all per-session keys we GC."""
    assert presence.session_stream_keys("foo") == [
        "cc-sessions:foo:inbound",
        "cc-sessions:foo:outbound",
        "cc-sessions:hb:foo",
    ]


def test_presence_is_idempotent_on_double_stop(fr: Any) -> None:
    meta = make_meta()
    p = presence.Presence(fr, meta, heartbeat_seconds=1, ttl_seconds=10)
    p.start()
    p.stop()
    p.stop()  # must not raise


def test_presence_rejects_double_start(fr: Any) -> None:
    p = presence.Presence(fr, make_meta(), heartbeat_seconds=1, ttl_seconds=10)
    p.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            p.start()
    finally:
        p.stop()


def test_presence_rejects_ttl_le_heartbeat(fr: Any) -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        presence.Presence(fr, make_meta(), heartbeat_seconds=10, ttl_seconds=10)
    with pytest.raises(ValueError):
        presence.Presence(fr, make_meta(), heartbeat_seconds=10, ttl_seconds=5)


def test_presence_context_manager(fr: Any) -> None:
    meta = make_meta()
    with presence.Presence(fr, meta, heartbeat_seconds=1, ttl_seconds=10):
        assert fr.exists(presence.hb_key(meta.session_name)) == 1
    assert fr.exists(presence.hb_key(meta.session_name)) == 0


def test_heartbeat_refreshes_ttl(fr: Any) -> None:
    """After more than one heartbeat tick, the hb key must still exist
    (heartbeat re-set it before the previous expiry)."""
    meta = make_meta()
    # ttl just barely above heartbeat to force the test to depend on refresh
    p = presence.Presence(fr, meta, heartbeat_seconds=1, ttl_seconds=2)
    p.start()
    try:
        time.sleep(1.3)
        assert fr.exists(presence.hb_key(meta.session_name)) == 1
        time.sleep(1.3)
        assert fr.exists(presence.hb_key(meta.session_name)) == 1
    finally:
        p.stop()


def test_list_live_sessions_filters_by_hb(fr: Any) -> None:
    meta1 = make_meta("live-1")
    meta2 = make_meta("live-2")
    p1 = presence.Presence(fr, meta1, heartbeat_seconds=1, ttl_seconds=10)
    p2 = presence.Presence(fr, meta2, heartbeat_seconds=1, ttl_seconds=10)
    p1.start()
    p2.start()
    try:
        live = presence.list_live_sessions(fr)
        assert set(live) == {"live-1", "live-2"}
    finally:
        p1.stop()
        p2.stop()


def test_list_live_sessions_skips_stale(fr: Any) -> None:
    meta_live = make_meta("live")
    meta_stale = make_meta("stale")
    fr.hset(presence.REGISTRY_KEY, "live", meta_live.to_json())
    fr.hset(presence.REGISTRY_KEY, "stale", meta_stale.to_json())
    fr.set(presence.hb_key("live"), str(time.time()), ex=60)
    # no hb key for "stale"
    live = presence.list_live_sessions(fr)
    assert set(live) == {"live"}


def test_list_live_sessions_gc_stale(fr: Any) -> None:
    meta_live = make_meta("live")
    meta_stale = make_meta("stale")
    fr.hset(presence.REGISTRY_KEY, "live", meta_live.to_json())
    fr.hset(presence.REGISTRY_KEY, "stale", meta_stale.to_json())
    fr.set(presence.hb_key("live"), str(time.time()), ex=60)
    presence.list_live_sessions(fr, gc_stale=True)
    assert fr.hget(presence.REGISTRY_KEY, "stale") is None
    assert fr.hget(presence.REGISTRY_KEY, "live") is not None


def test_list_live_sessions_gc_drops_stale_streams(fr: Any) -> None:
    """Stale-entry GC must also DEL the per-session inbound/outbound streams
    that a crashed-mid-session would otherwise leave behind."""
    fr.hset(presence.REGISTRY_KEY, "ghost", make_meta("ghost").to_json())
    fr.xadd("cc-sessions:ghost:inbound", {"payload": "{}"})
    fr.xadd("cc-sessions:ghost:outbound", {"payload": "{}"})
    # no hb key for ghost → it's stale

    fr.hset(presence.REGISTRY_KEY, "live", make_meta("live").to_json())
    fr.set(presence.hb_key("live"), str(time.time()), ex=60)
    fr.xadd("cc-sessions:live:inbound", {"payload": "{}"})

    presence.list_live_sessions(fr, gc_stale=True)
    # stale: registry entry + both streams gone
    assert fr.hget(presence.REGISTRY_KEY, "ghost") is None
    assert fr.exists("cc-sessions:ghost:inbound") == 0
    assert fr.exists("cc-sessions:ghost:outbound") == 0
    # live: untouched
    assert fr.hget(presence.REGISTRY_KEY, "live") is not None
    assert fr.exists("cc-sessions:live:inbound") == 1


def test_list_live_sessions_no_gc_when_disabled(fr: Any) -> None:
    """Default gc_stale=False must NOT touch streams (or registry)."""
    fr.hset(presence.REGISTRY_KEY, "ghost", make_meta("ghost").to_json())
    fr.xadd("cc-sessions:ghost:inbound", {"payload": "{}"})
    presence.list_live_sessions(fr)  # gc_stale defaults to False
    assert fr.hget(presence.REGISTRY_KEY, "ghost") is not None
    assert fr.exists("cc-sessions:ghost:inbound") == 1


def test_list_live_sessions_handles_corrupt_entry(fr: Any) -> None:
    fr.hset(presence.REGISTRY_KEY, "broken", "{not valid json}")
    fr.set(presence.hb_key("broken"), str(time.time()), ex=60)
    live = presence.list_live_sessions(fr)
    assert live == {}


def test_lifecycle_events_published(fr: Any) -> None:
    meta = make_meta("pub-test")
    pubsub = fr.pubsub()
    pubsub.subscribe(presence.events_channel(meta.session_name))
    pubsub.get_message(timeout=0.1)  # subscribe ack
    p = presence.Presence(fr, meta, heartbeat_seconds=1, ttl_seconds=10)
    p.start()
    p.stop(reason="test")
    msgs = []
    while True:
        m = pubsub.get_message(timeout=0.1)
        if m is None:
            break
        if m.get("type") == "message":
            msgs.append(m)
    pubsub.close()
    types_seen = []
    for m in msgs:
        import json as _json

        payload = _json.loads(m["data"])
        types_seen.append(payload["type"])
        assert payload["session_name"] == meta.session_name
        assert payload["v"] == 1
    assert "registered" in types_seen
    assert "unregistered" in types_seen
