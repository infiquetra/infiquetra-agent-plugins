"""Presence tracking for redis-channel sessions.

Implements the registry contract from PROTOCOL.md:

    HSET   cc-sessions:registry <name> <metadata JSON>     # static
    SET    cc-sessions:hb:<name> <ts> EX 60                # per-beat
    PUBLISH cc-sessions:events:<name> <lifecycle JSON>     # transitions

Heartbeat runs on a background daemon thread that wakes every
`heartbeat_seconds` (default 10) and refreshes the hb key with the
configured TTL (default 60). Stop is graceful via an Event; the
thread also unregisters on its own way out if the main process is
exiting cleanly.

Stale-entry GC: callers that read the registry should filter by
`is_live()` and may opt to HDEL stale entries. This is lazy on
purpose — there is no central GC, only "everyone cleans up after
themselves on read".
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .redis_client import RedisLike

log = logging.getLogger(__name__)

REGISTRY_KEY = "cc-sessions:registry"
HB_KEY_PREFIX = "cc-sessions:hb:"
EVENTS_CHANNEL_PREFIX = "cc-sessions:events:"


def hb_key(session_name: str) -> str:
    return f"{HB_KEY_PREFIX}{session_name}"


def events_channel(session_name: str) -> str:
    return f"{EVENTS_CHANNEL_PREFIX}{session_name}"


def disambiguate_if_collision(
    client: RedisLike,
    base_name: str,
    *,
    host: str,
    pid: int,
) -> str:
    """Return a session name that won't collide with a live entry.

    Same-cwd same-host CC sessions auto-name themselves identically (because
    the auto-name is `sha256(cwd + host)[:8]`). Without this, two background
    sessions in the same repo race for the same registry key, hb key, and
    consumer-group consumer name. This helper appends a 4-hex-of-pid suffix
    on collision.

    Returns base_name unchanged if any of:
      - no live presence at base_name (hb key absent → either never claimed
        or stale + about to be GC'd)
      - the live presence belongs to us (same host AND pid → reconnect from
        the same process; channel layer handles the local reconnect)
      - the registry entry is missing or corrupt (best-effort; we'll
        overwrite it cleanly)

    Disambiguates by appending `-<pid_hex_4>` when a different live process
    on the same host (or a different host) already owns base_name. PIDs
    don't actually collide within a single host at the same time, so the
    suffix is unique enough; across hosts the underlying auto-name already
    differs (host is in the hash input).
    """
    if not client.exists(hb_key(base_name)):
        return base_name
    raw = client.hget(REGISTRY_KEY, base_name)
    if raw is None:
        return base_name
    try:
        existing = SessionMetadata.from_json(raw)
    except (ValueError, KeyError, json.JSONDecodeError):
        return base_name
    if existing.host == host and existing.pid == pid:
        return base_name
    suffix = f"{pid:x}"[-4:].rjust(4, "0")
    return f"{base_name}-{suffix}"


@dataclass(frozen=True, slots=True)
class SessionMetadata:
    """Static registry payload for a CC session.

    Written once on register, refreshed on rename. The `last_heartbeat`
    field is informational only — the authoritative liveness signal is
    the existence of the hb:<name> key.
    """

    session_name: str
    host: str
    cwd: str
    git_branch: str | None
    started_at: float
    pid: int
    endpoint: str
    extras: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, raw: str) -> SessionMetadata:
        data = json.loads(raw)
        return cls(
            session_name=data["session_name"],
            host=data["host"],
            cwd=data["cwd"],
            git_branch=data.get("git_branch"),
            started_at=float(data["started_at"]),
            pid=int(data["pid"]),
            endpoint=data.get("endpoint", "unknown"),
            extras=dict(data.get("extras") or {}),
        )


def detect_git_branch(cwd: str) -> str | None:
    """Return the current git branch for `cwd`, or None if not a git repo / git
    is unavailable / detection fails for any reason.

    Best-effort: a 1s subprocess timeout caps the cost in case the cwd is on a
    slow/unresponsive filesystem (e.g. stale NFS mount). Returns None for
    detached HEAD ("HEAD" is filtered to None) so the router has a clean
    "no branch context" signal.
    """
    import subprocess  # noqa: PLC0415  (local import — keeps presence import-light)

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=1.0,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # git not installed, cwd doesn't exist, slow FS, or other transient
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        # Empty result or detached-HEAD state
        return None
    return branch


def build_metadata(
    *,
    session_name: str,
    endpoint: str,
    cwd: str | None = None,
    host: str | None = None,
    git_branch: str | None = None,
    started_at: float | None = None,
    extras: dict[str, str] | None = None,
) -> SessionMetadata:
    resolved_cwd = cwd or os.getcwd()
    # Auto-detect git_branch when not explicitly supplied. Pass git_branch=""
    # or an explicit value to override; the sentinel for "no detection" is
    # `git_branch=""` which is stored verbatim (and routers can treat empty
    # string as "no branch info").
    if git_branch is None:
        git_branch = detect_git_branch(resolved_cwd)
    return SessionMetadata(
        session_name=session_name,
        host=host or socket.gethostname(),
        cwd=resolved_cwd,
        git_branch=git_branch,
        started_at=started_at if started_at is not None else time.time(),
        pid=os.getpid(),
        endpoint=endpoint,
        extras=dict(extras or {}),
    )


def is_live(client: RedisLike, session_name: str) -> bool:
    """True iff the per-session heartbeat key exists."""
    return bool(client.exists(hb_key(session_name)))


def session_stream_keys(session_name: str) -> list[str]:
    """All session-scoped key names belonging to one session.

    Currently: inbound stream + outbound stream + hb key. Single source of
    truth for what gets deleted in graceful disconnect and stale-entry GC.
    The channel-events pub/sub doesn't persist a key (publishes are
    ephemeral), so it's not included.
    """
    return [
        f"cc-sessions:{session_name}:inbound",
        f"cc-sessions:{session_name}:outbound",
        hb_key(session_name),
    ]


def list_live_sessions(client: RedisLike, *, gc_stale: bool = False) -> dict[str, SessionMetadata]:
    """Return live sessions from the registry, filtered by hb key existence.

    With `gc_stale=True`, also HDEL the registry entries whose hb key has
    expired AND DEL their per-session streams (so abandoned sessions don't
    accumulate stream keys in Redis forever). Returned dict is keyed by
    session_name.
    """
    raw = client.hgetall(REGISTRY_KEY)
    live: dict[str, SessionMetadata] = {}
    stale: list[str] = []
    for name, body in raw.items():
        try:
            meta = SessionMetadata.from_json(body)
        except (ValueError, KeyError, json.JSONDecodeError):
            log.warning("registry entry %r is corrupt; treating as stale", name)
            stale.append(name)
            continue
        if is_live(client, name):
            live[name] = meta
        else:
            stale.append(name)
    if gc_stale and stale:
        client.hdel(REGISTRY_KEY, *stale)
        # Also DEL the per-session streams. These don't auto-expire, so
        # without this cleanup the registry HDEL would succeed but
        # `cc-sessions:<n>:{inbound,outbound}` would accumulate one pair
        # per ever-disconnected session.
        stream_keys: list[str] = []
        for name in stale:
            stream_keys.extend(session_stream_keys(name))
        if stream_keys:
            client.delete(*stream_keys)
        log.info(
            "GC'd %d stale registry entries (+ %d stream keys): %s",
            len(stale),
            len(stream_keys),
            stale,
        )
    return live


class Presence:
    """Manages registration + heartbeat for one CC session.

    Lifecycle:
        p = Presence(client, metadata, heartbeat_seconds=10, ttl_seconds=60)
        p.start()        # registers + spawns heartbeat thread
        ...
        p.stop()         # graceful unregister
    """

    def __init__(
        self,
        client: RedisLike,
        metadata: SessionMetadata,
        *,
        heartbeat_seconds: int = 10,
        ttl_seconds: int = 60,
    ) -> None:
        if ttl_seconds <= heartbeat_seconds:
            raise ValueError(
                f"ttl_seconds ({ttl_seconds}) must exceed heartbeat_seconds "
                f"({heartbeat_seconds}); otherwise the key can expire between beats"
            )
        self._client = client
        self._metadata = metadata
        self._heartbeat_seconds = heartbeat_seconds
        self._ttl_seconds = ttl_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._started = False

    @property
    def session_name(self) -> str:
        return self._metadata.session_name

    @property
    def metadata(self) -> SessionMetadata:
        return self._metadata

    def start(self) -> None:
        """Register in Redis and spawn the heartbeat thread."""
        if self._started:
            raise RuntimeError(f"Presence({self.session_name}) already started")
        self._client.hset(REGISTRY_KEY, self.session_name, self._metadata.to_json())
        self._beat_once()
        self._publish_lifecycle("registered")
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"redis-channel-hb-{self.session_name}",
            daemon=True,
        )
        self._thread.start()
        self._started = True
        log.info(
            "registered session %s (heartbeat every %ds, ttl %ds)",
            self.session_name,
            self._heartbeat_seconds,
            self._ttl_seconds,
        )

    def stop(self, *, reason: str = "graceful") -> None:
        """Stop heartbeat, unregister, and publish lifecycle event.

        Graceful disconnect intent: the session is done, so we also DEL the
        per-session inbound/outbound stream keys (alongside the existing
        registry HDEL + hb DEL). Without this, every disconnected session
        leaks an orphan stream pair in Redis. Stream deletion is best-effort
        and swallowed.
        """
        if not self._started:
            return
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self._heartbeat_seconds + 2)
            self._thread = None
        # Best-effort cleanup; swallow errors so __exit__ never raises.
        try:
            self._client.delete(*session_stream_keys(self.session_name))
            self._client.hdel(REGISTRY_KEY, self.session_name)
            self._publish_lifecycle("unregistered", extra={"reason": reason})
        except Exception:  # noqa: BLE001
            log.exception("cleanup failed for session %s", self.session_name)
        self._started = False
        log.info("unregistered session %s (reason=%s)", self.session_name, reason)

    def __enter__(self) -> Presence:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop(reason="graceful" if exc_type is None else "exception")

    def _loop(self) -> None:
        while not self._stop_event.wait(self._heartbeat_seconds):
            try:
                self._beat_once()
            except Exception:  # noqa: BLE001
                log.exception("heartbeat failed for session %s", self.session_name)
                # Don't exit on transient errors; the next tick may recover.

    def _beat_once(self) -> None:
        self._client.set(
            hb_key(self.session_name),
            str(time.time()),
            ex=self._ttl_seconds,
        )

    def _publish_lifecycle(self, event_type: str, extra: dict | None = None) -> None:
        payload = {
            "v": 1,
            "type": event_type,
            "session_name": self.session_name,
            "ts": time.time(),
        }
        if extra:
            payload.update(extra)
        try:
            # redis-py's publish() accepts the channel via the client; we use
            # the same client interface here. RedisLike doesn't declare it,
            # so guard for fakeredis/test doubles that may omit it.
            publish = getattr(self._client, "publish", None)
            if publish is None:
                return
            publish(events_channel(self.session_name), json.dumps(payload))
        except Exception:  # noqa: BLE001
            log.exception("publish lifecycle event %s failed", event_type)
