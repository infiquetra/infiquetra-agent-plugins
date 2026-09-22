"""MCP server (stdio) for redis-channel.

Phase 1 tools:
    - redis_channel_connect(endpoint=..., session_name=...)
    - redis_channel_disconnect()
    - redis_channel_list()

Phase 2 additions:
    - reply(chat_id, text, voice=False, source_msg_id=None)
    - On connect: spawn a consumer thread that XREADGROUPs the inbound
      stream and emits each message as a `notifications/claude/channel`
      MCP notification on the session.

Single-session per process: at most one active Presence+Consumer pair
at a time. A second `connect` call replaces the previous one.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import json
import logging
import os
import re
import shutil
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

from . import __version__
from .notifier import AsyncNotifier, ChannelNotifier, NoopNotifier
from .presence import (
    Presence,
    build_metadata,
    disambiguate_if_collision,
    list_live_sessions,
)
from .protocol import Outbound
from .redis_client import connect as redis_connect
from .redis_consumer import Consumer, consumer_group, ensure_group, inbound_stream
from .redis_producer import publish_outbound
from .registry import (
    DEFAULT_CONFIG_PATH,
    EndpointNotFoundError,
    RegistryError,
    RegistryNotFoundError,
    load_registry,
)
from .session_id import resolve_session_name

log = logging.getLogger("redis_channel.channel")


class ServerState:
    """Single-active-session state for the channel server.

    Wrapped in a lock so heartbeat thread (Presence), consumer thread,
    and tool-handler threads (FastMCP can dispatch concurrently) don't
    race on lifecycle.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._presence: Presence | None = None
        self._consumer: Consumer | None = None
        self._notifier: ChannelNotifier | None = None
        self._client: Any | None = None
        self._endpoint_name: str | None = None
        self._consumer_block_ms: int = 1000
        self._connected_at: float | None = None
        # `debug` controls how chatty Claude should be in the terminal after
        # replying. Default off (quiet). Set via the connect tool's `debug`
        # arg; surfaced in connect's response so the slash-command markdown
        # + agent coach can steer Claude's reply-narration behavior.
        self._debug: bool = False

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._presence is not None

    @property
    def debug(self) -> bool:
        with self._lock:
            return self._debug

    def connect(
        self,
        *,
        endpoint: str | None,
        session_name: str | None,
        notifier: ChannelNotifier | None = None,
        debug: bool = False,
    ) -> dict[str, Any]:
        """Open the channel: register presence, start consumer.

        `notifier` is the surface to which inbound stream messages are
        forwarded. In production it's the AsyncNotifier built from the
        MCP session + loop; in tests it's a RecordingNotifier or NoopNotifier.

        When `endpoint` is None, resolves to `registry.defaults.default_endpoint`
        with a single-endpoint convenience fallback (see
        `Registry.resolve_default_endpoint`).
        """
        try:
            with self._lock:
                if self._presence is not None:
                    self._disconnect_locked(reason="reconnect")
                result = self._register_locked(
                    endpoint=endpoint, session_name=session_name, debug=debug
                )
                resolved_notifier: ChannelNotifier = notifier or NoopNotifier()
                self._attach_consumer_locked(resolved_notifier)
                result["consumer_attached"] = True
                result["notifier_kind"] = type(resolved_notifier).__name__
                return result
        except RegistryError as e:
            return _format_registry_error(e)
        except ValueError as e:
            return {"ok": False, "error": "invalid argument", "detail": str(e)}
        except RuntimeError as e:
            return {"ok": False, "error": "runtime error", "detail": str(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("connect failed")
            return {"ok": False, "error": type(e).__name__, "detail": str(e)}

    def startup_register(self, *, endpoint: str | None) -> dict[str, Any]:
        """Eager-only auto-connect path: open client, create consumer group,
        start presence — but do NOT start the consumer thread yet.

        Called from `run()` at MCP startup when CLAUDE_CHANNEL_AUTO_CONNECT=1.
        At that point there's no MCP Context to build an AsyncNotifier from,
        so we defer the consumer thread until the first tool dispatch (when
        a ctx is available). The consumer group IS created eagerly so
        XREADGROUP `>` later picks up anything XADD'd between presence
        publish and consumer-thread start — no silent drop.
        """
        try:
            with self._lock:
                if self._presence is not None:
                    return {"ok": True, "was_already_connected": True}
                result = self._register_locked(endpoint=endpoint, session_name=None, debug=False)
                result["consumer_attached"] = False
                result["notifier_kind"] = None
                return result
        except RegistryError as e:
            return _format_registry_error(e)
        except Exception as e:  # noqa: BLE001
            log.exception("startup_register failed")
            return {"ok": False, "error": type(e).__name__, "detail": str(e)}

    def ensure_consumer_attached(self, notifier: ChannelNotifier) -> bool:
        """Idempotently start the consumer thread + wire notifier.

        Called from MCP tool handlers to finish the auto-connect setup
        on first use. Returns True if the consumer was just attached;
        False if no attachment needed (already attached or no presence).
        """
        with self._lock:
            if self._presence is None or self._client is None:
                return False
            if self._consumer is not None:
                return False
            self._attach_consumer_locked(notifier)
            return True

    def _register_locked(
        self,
        *,
        endpoint: str | None,
        session_name: str | None,
        debug: bool,
    ) -> dict[str, Any]:
        """Caller holds self._lock. Resolves endpoint, opens client, creates
        consumer group, starts presence. Does NOT start consumer thread."""
        registry = load_registry()
        if endpoint is None:
            ep = registry.resolve_default_endpoint()
            endpoint = ep.name
        else:
            ep = registry.get(endpoint)
        resolved_name = resolve_session_name(session_name)
        client = redis_connect(ep)
        # Auto-disambiguate only when the user didn't supply an explicit name.
        # An explicit name is treated as intent — let the regular
        # reconnect/replace semantics handle it.
        if session_name is None:
            resolved_name = disambiguate_if_collision(
                client,
                resolved_name,
                host=socket.gethostname(),
                pid=os.getpid(),
            )
        # Create the consumer group BEFORE presence publishes so XREADGROUP `>`
        # on first tool dispatch (or `connect`'s own consumer start) picks up
        # any messages XADD'd in the gap. ensure_group is idempotent
        # (BUSYGROUP = success).
        ensure_group(
            client,
            stream=inbound_stream(resolved_name),
            group=consumer_group(resolved_name),
        )
        metadata = build_metadata(session_name=resolved_name, endpoint=endpoint)
        presence = Presence(
            client,
            metadata,
            heartbeat_seconds=registry.defaults.heartbeat_seconds,
            ttl_seconds=registry.defaults.registry_ttl_seconds,
        )
        presence.start()

        self._presence = presence
        self._client = client
        self._endpoint_name = endpoint
        self._consumer_block_ms = registry.defaults.consumer_block_ms
        self._connected_at = time.time()
        self._debug = bool(debug)
        return {
            "ok": True,
            "session_name": metadata.session_name,
            "endpoint": endpoint,
            "endpoint_display": ep.display_name,
            "debug": self._debug,
            "host": metadata.host,
            "cwd": metadata.cwd,
            "heartbeat_seconds": registry.defaults.heartbeat_seconds,
            "registry_ttl_seconds": registry.defaults.registry_ttl_seconds,
        }

    def _attach_consumer_locked(self, notifier: ChannelNotifier) -> None:
        """Caller holds self._lock. Starts consumer thread with the given
        notifier; requires presence + client to already be set."""
        if self._presence is None or self._client is None:
            raise RuntimeError(
                "cannot attach consumer: presence not started; call connect "
                "or startup_register first"
            )
        if self._consumer is not None:
            return  # idempotent
        consumer = Consumer(
            self._client,
            self._presence.session_name,
            on_message=notifier.emit,
            block_ms=self._consumer_block_ms,
        )
        consumer.start()
        self._consumer = consumer
        self._notifier = notifier

    def disconnect(self) -> dict[str, Any]:
        try:
            with self._lock:
                if self._presence is None:
                    return {"ok": True, "was_connected": False}
                session_name = self._presence.session_name
                self._disconnect_locked(reason="user")
                return {"ok": True, "was_connected": True, "session_name": session_name}
        except Exception as e:  # noqa: BLE001
            log.exception("disconnect failed")
            return {"ok": False, "error": type(e).__name__, "detail": str(e)}

    def list_sessions(self) -> dict[str, Any]:
        try:
            with self._lock:
                if self._client is None:
                    return {
                        "ok": False,
                        "error": "not connected — call redis_channel_connect first",
                    }
                sessions = list_live_sessions(self._client, gc_stale=True)
                return {
                    "ok": True,
                    "endpoint": self._endpoint_name,
                    "count": len(sessions),
                    "sessions": [
                        {
                            "session_name": m.session_name,
                            "host": m.host,
                            "cwd": m.cwd,
                            "git_branch": m.git_branch,
                            "started_at": m.started_at,
                            "pid": m.pid,
                            "is_self": (
                                self._presence is not None
                                and m.session_name == self._presence.session_name
                            ),
                        }
                        for m in sorted(sessions.values(), key=lambda meta: meta.started_at)
                    ],
                }
        except Exception as e:  # noqa: BLE001
            log.exception("list failed")
            return {"ok": False, "error": type(e).__name__, "detail": str(e)}

    def reply(
        self,
        *,
        chat_id: str,
        text: str,
        voice: bool = False,
        in_reply_to: str | None = None,
    ) -> dict[str, Any]:
        """XADD an Outbound payload to the active session's outbound stream."""
        try:
            if not chat_id or not chat_id.strip():
                raise ValueError("chat_id must be non-empty")
            if not text or not text.strip():
                raise ValueError("text must be non-empty")
            with self._lock:
                if self._presence is None or self._client is None:
                    return {
                        "ok": False,
                        "error": "not connected — call redis_channel_connect first",
                    }
                session_name = self._presence.session_name
                endpoint = self._endpoint_name or ""
                client = self._client

            # Validate via Pydantic; rejects empty text, malformed chat_id, etc.
            payload = Outbound(
                session_name=session_name,
                endpoint=endpoint,
                chat_id=chat_id,
                text=text,
                voice=voice,
                in_reply_to=in_reply_to,
                ts=time.time(),
            )
            msg_id = publish_outbound(
                client,
                session_name,
                payload.model_dump(mode="json", exclude_none=True),
            )
            return {
                "ok": True,
                "session_name": session_name,
                "chat_id": chat_id,
                "msg_id": msg_id,
            }
        except ValueError as e:
            return {"ok": False, "error": "invalid argument", "detail": str(e)}
        except Exception as e:  # noqa: BLE001
            log.exception("reply failed")
            return {"ok": False, "error": type(e).__name__, "detail": str(e)}

    def status(self) -> dict[str, Any]:
        """Snapshot of current connection state. Used by /redis-channel-status."""
        with self._lock:
            if self._presence is None:
                return {
                    "ok": True,
                    "connected": False,
                }
            session_name = self._presence.session_name
            uptime = (
                int(time.time() - self._connected_at) if self._connected_at is not None else None
            )
            # Count pending inbound messages on the consumer group via XLEN-
            # like introspection. XPENDING gives unacked count for the group;
            # XLEN gives total. We want "messages waiting to be processed,"
            # which is approximately XLEN minus already-acked. Cheapest
            # approximation: XLEN of the stream. Good enough for "is there
            # backlog?" UX.
            pending: int | None = None
            try:
                if self._client is not None:
                    pending = int(self._client.xlen(inbound_stream(session_name)))
            except Exception:  # noqa: BLE001
                pending = None
            return {
                "ok": True,
                "connected": True,
                "session_name": session_name,
                "endpoint": self._endpoint_name,
                "host": self._presence.metadata.host,
                "uptime_seconds": uptime,
                "consumer_attached": self._consumer is not None,
                "pending_inbound": pending,
            }

    def shutdown(self) -> None:
        """Best-effort cleanup on process exit."""
        with self._lock:
            if self._presence is not None:
                self._disconnect_locked(reason="shutdown")

    def _disconnect_locked(self, *, reason: str) -> None:
        # Order: stop consumer first (so it doesn't try to ack on a stale
        # client), then presence, then close the client.
        if self._consumer is not None:
            try:
                self._consumer.stop()
            except Exception:  # noqa: BLE001
                log.exception("consumer.stop raised during disconnect")
            self._consumer = None
        if self._presence is not None:
            try:
                self._presence.stop(reason=reason)
            except Exception:  # noqa: BLE001
                log.exception("presence.stop raised during disconnect")
            self._presence = None
        if self._client is not None:
            try:
                close = getattr(self._client, "close", None)
                if callable(close):
                    close()
            except Exception:  # noqa: BLE001
                log.exception("redis client close raised during disconnect")
            self._client = None
        self._endpoint_name = None
        self._notifier = None
        self._debug = False


_STATE = ServerState()


# ─── Setup / first-run scaffolding ──────────────────────────────────────────


CHANNEL_CONFIG_DIR = Path("~/.claude/channels/redis-channel").expanduser()
BIN_DIR = Path("~/bin").expanduser()
WRAPPER_SYMLINK = BIN_DIR / "claude-channel"


def _plugin_root() -> Path | None:
    """Resolve the plugin's installed cache dir.

    Claude Code sets `CLAUDE_PLUGIN_ROOT` when launching MCP servers from
    plugin dirs. Fall back to deriving from this module's __file__ if the
    env var isn't set (e.g., in tests).
    """
    env = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if env:
        return Path(env)
    # `server/channel.py` lives at <plugin_root>/server/channel.py
    return Path(__file__).resolve().parent.parent


def _expected_wrapper_path() -> Path | None:
    """Where the symlink should point: <plugin_root>/scripts/claude-channel.sh."""
    root = _plugin_root()
    if root is None:
        return None
    return root / "scripts" / "claude-channel.sh"


def _check_setup() -> dict[str, Any]:
    """Return a structured report of which setup artifacts are present / current.

    Used by both the setup tool (to decide what work to do) and the startup
    nag (to decide whether to log a "run /redis-channel-setup" hint).
    """
    wrapper_target = _expected_wrapper_path()
    symlink_status: str
    if not WRAPPER_SYMLINK.exists() and not WRAPPER_SYMLINK.is_symlink():
        symlink_status = "missing"
    elif not WRAPPER_SYMLINK.is_symlink():
        symlink_status = "exists_not_symlink"
    else:
        try:
            actual = WRAPPER_SYMLINK.resolve()
            if wrapper_target is not None and actual == wrapper_target.resolve():
                symlink_status = "current"
            else:
                symlink_status = "stale"
        except (OSError, RuntimeError):
            symlink_status = "broken"

    source_env = CHANNEL_CONFIG_DIR / "source-env.sh"
    registry_json = CHANNEL_CONFIG_DIR / "registry.json"

    return {
        "plugin_root": str(_plugin_root()) if _plugin_root() else None,
        "wrapper_symlink_path": str(WRAPPER_SYMLINK),
        "wrapper_symlink_expected_target": (str(wrapper_target) if wrapper_target else None),
        "wrapper_symlink_status": symlink_status,
        "source_env_path": str(source_env),
        "source_env_exists": source_env.exists(),
        "registry_path": str(registry_json),
        "registry_exists": registry_json.exists(),
        "all_ready": (
            symlink_status == "current" and source_env.exists() and registry_json.exists()
        ),
    }


_ENDPOINT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _configure_endpoint(
    *,
    endpoint_name: str,
    redis_url: str,
    redis_password_env: str | None = None,
    display_name: str | None = None,
    set_default: bool = False,
) -> dict[str, Any]:
    """Add or update an endpoint in `~/.claude/channels/redis-channel/registry.json`.

    Idempotent: if the endpoint already exists, its fields are overwritten
    with the new values. Other endpoints + defaults are left intact. Writes
    atomically via a .tmp + replace.

    Does NOT create source-env.sh — that's `/redis-channel-setup`'s job.
    """
    if not _ENDPOINT_NAME_RE.match(endpoint_name):
        return {
            "ok": False,
            "error": "invalid endpoint_name",
            "detail": f"must match {_ENDPOINT_NAME_RE.pattern}; got {endpoint_name!r}",
        }
    if not (redis_url.startswith("redis://") or redis_url.startswith("rediss://")):
        return {
            "ok": False,
            "error": "invalid redis_url",
            "detail": "must start with redis:// or rediss://",
        }
    if redis_password_env is not None and not redis_password_env.strip():
        # Empty string → treat as None (no password env)
        redis_password_env = None

    cfg_path = CHANNEL_CONFIG_DIR / "registry.json"
    try:
        CHANNEL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"ok": False, "error": "mkdir failed", "detail": str(e)}

    if cfg_path.exists():
        try:
            existing = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return {
                "ok": False,
                "error": "registry parse error",
                "detail": f"existing {cfg_path}: {e}",
            }
        if not isinstance(existing, dict):
            return {
                "ok": False,
                "error": "registry shape error",
                "detail": f"existing {cfg_path} top-level must be object",
            }
    else:
        existing = {}

    endpoints = existing.setdefault("endpoints", {})
    if not isinstance(endpoints, dict):
        return {
            "ok": False,
            "error": "registry shape error",
            "detail": "endpoints must be object",
        }
    endpoint_entry: dict[str, Any] = {"redis_url": redis_url}
    if redis_password_env is not None:
        endpoint_entry["redis_password_env"] = redis_password_env
    if display_name is not None and display_name.strip():
        endpoint_entry["display_name"] = display_name.strip()
    is_update = endpoint_name in endpoints
    endpoints[endpoint_name] = endpoint_entry

    if set_default:
        defaults = existing.setdefault("defaults", {})
        if not isinstance(defaults, dict):
            return {
                "ok": False,
                "error": "registry shape error",
                "detail": "defaults must be object",
            }
        defaults["default_endpoint"] = endpoint_name

    tmp = cfg_path.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        tmp.replace(cfg_path)
    except OSError as e:
        return {"ok": False, "error": "write failed", "detail": str(e)}

    return {
        "ok": True,
        "written": str(cfg_path),
        "endpoint_name": endpoint_name,
        "action": "updated" if is_update else "created",
        "endpoint_count": len(endpoints),
        "default_endpoint": existing.get("defaults", {}).get("default_endpoint"),
    }


def _do_setup(*, link_wrapper: bool, scaffold_configs: bool) -> dict[str, Any]:
    """Do the install actions. Idempotent — safe to re-run.

    `link_wrapper`: create/update the ~/bin/claude-channel symlink.
    `scaffold_configs`: copy source-env.example.sh + registry.example.json
      into the channel config dir if those files don't exist yet.

    Never overwrites existing user config files. The wrapper symlink IS
    overwritten on each call so plugin updates are picked up.
    """
    actions: list[dict[str, Any]] = []

    if link_wrapper:
        target = _expected_wrapper_path()
        if target is None or not target.exists():
            actions.append(
                {
                    "target": str(WRAPPER_SYMLINK),
                    "status": "skipped",
                    "reason": (
                        f"plugin's claude-channel.sh not found at "
                        f"{target} — is the plugin installed?"
                    ),
                }
            )
        else:
            try:
                BIN_DIR.mkdir(parents=True, exist_ok=True)
                # Remove existing symlink/file first; ln -sf semantics in Python.
                if WRAPPER_SYMLINK.is_symlink() or WRAPPER_SYMLINK.exists():
                    WRAPPER_SYMLINK.unlink()
                WRAPPER_SYMLINK.symlink_to(target)
                actions.append(
                    {
                        "target": str(WRAPPER_SYMLINK),
                        "status": "linked",
                        "to": str(target),
                    }
                )
            except OSError as e:
                actions.append(
                    {
                        "target": str(WRAPPER_SYMLINK),
                        "status": "error",
                        "detail": str(e),
                    }
                )

    if scaffold_configs:
        root = _plugin_root()
        docs = root / "docs" if root else None
        CHANNEL_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        for filename, example_name in [
            ("source-env.sh", "source-env.example.sh"),
            ("registry.json", "registry.example.json"),
        ]:
            dest = CHANNEL_CONFIG_DIR / filename
            example = docs / example_name if docs else None
            if dest.exists():
                actions.append(
                    {
                        "target": str(dest),
                        "status": "exists",
                        "note": "left as-is (will not overwrite user config)",
                    }
                )
                continue
            if example is None or not example.exists():
                actions.append(
                    {
                        "target": str(dest),
                        "status": "skipped",
                        "reason": (f"example not found at {example} — is the plugin installed?"),
                    }
                )
                continue
            try:
                shutil.copy2(example, dest)
                # source-env.sh needs to be executable for safety
                # (it's not exec'd via sh dot-source, but a future change
                # might switch to exec; defense in depth).
                if filename.endswith(".sh"):
                    dest.chmod(0o755)
                actions.append(
                    {
                        "target": str(dest),
                        "status": "created_from_example",
                        "example": str(example),
                        "next_step": (
                            "edit this file with your real values"
                            if filename == "registry.json"
                            else "edit if your env-var or keychain item name differs"
                        ),
                    }
                )
            except OSError as e:
                actions.append(
                    {
                        "target": str(dest),
                        "status": "error",
                        "detail": str(e),
                    }
                )

    return {
        "ok": True,
        "actions": actions,
        "state": _check_setup(),
    }


def _format_registry_error(err: RegistryError) -> dict[str, Any]:
    if isinstance(err, RegistryNotFoundError):
        return {
            "ok": False,
            "error": "registry not configured",
            "detail": str(err),
            "hint": (
                "Create ~/.claude/channels/redis-channel/registry.json or run "
                "/redis-channel-configure"
            ),
        }
    if isinstance(err, EndpointNotFoundError):
        return {"ok": False, "error": "endpoint not found", "detail": str(err)}
    return {"ok": False, "error": "registry parse error", "detail": str(err)}


def _build_async_notifier(ctx: Context | None) -> ChannelNotifier:
    """If we have an MCP session + running loop, build a real notifier.

    Falls back to NoopNotifier if Context isn't injected (test code paths
    that call ServerState.connect directly should pass their own notifier).
    """
    if ctx is None:
        return NoopNotifier()
    try:
        session = ctx.session
        loop = asyncio.get_running_loop()
    except Exception:  # noqa: BLE001
        return NoopNotifier()
    return AsyncNotifier(session, loop)


def build_app() -> FastMCP:
    """Construct the FastMCP app with all redis-channel tools registered."""
    app = FastMCP(
        name=f"redis-channel v{__version__}",
        instructions=(
            "Generic Redis-streams bridge for Claude Code sessions. Pair "
            "with any router that speaks the protocol on the consumer "
            "side.\n"
            "\n"
            "When a redis-channel session is active (after "
            "/redis-channel-connect), external user messages arrive as "
            '`<channel source="..." chat_id="..." _msg_id="..." '
            'endpoint="..." user_id="..." username="..." ...>...</channel>` '
            "notifications. The body inside the tag is the user's text "
            "(or speech transcript for voice).\n"
            "\n"
            "TWO USERS see your turn:\n"
            "  1. The LOCAL terminal user (developer at the CLI). Sees "
            "your assistant text. Does NOT see MCP tool calls or their "
            "result content — those render collapsed as "
            "'Called plugin:...'.\n"
            "  2. The CHANNEL user (Discord/voice/etc. via the router). "
            "Sees only what you put in `reply()`'s `text` argument. Does "
            "NOT see your assistant text.\n"
            "\n"
            "Both users want your answer. Two surfaces, one answer:\n"
            "  - Write your answer as your normal assistant text. That's "
            "how the local user reads it. It IS the answer for that "
            "audience — not narration, not commentary.\n"
            "  - Also call `reply(chat_id=<from inbound>, "
            "text=<same answer>, voice=<per source>, "
            "in_reply_to=<_msg_id>)`. That's how the channel user reads it.\n"
            "\n"
            "Source-mode formatting for the `text` arg (and the matching "
            "assistant text):\n"
            "  voice → TTS speaks aloud. Short. NO markdown, NO code, NO "
            "bare URLs (TTS reads them letter by letter). Speakable prose. "
            "Don't reference visual elements.\n"
            "  dm / channel / thread → markdown, code blocks, links all "
            "render. Normal formatting.\n"
            "  (any other) → default to dm-style.\n"
            "\n"
            "Pass `voice=true` only when source=voice. Pass "
            "`in_reply_to=<_msg_id from inbound>` for channel/thread "
            "sources to thread the reply (router may ignore for "
            "voice/dm).\n"
            "\n"
            "Do NOT call AskUserQuestion during a channel session — "
            "inline the choices in your `text` instead "
            '("Which? A) ... B) ... C) ..."). Phase 4 will deterministically '
            "intercept any AskUserQuestion you do emit; until then, just "
            "inline.\n"
            "\n"
            "Voice round-trip latency is 6-10s typical; keep voice "
            "replies tight."
        ),
    )
    # FastMCP 1.x does not take a version. Leaving the low-level server's
    # version unset makes initialize report the mcp library's version as
    # serverInfo.version. The package version is the one the manifests state.
    app._mcp_server.version = __version__  # noqa: SLF001

    @app.tool(
        name="redis_channel_connect",
        description=(
            "Connect this Claude Code session to a redis-channel endpoint "
            "(a configured router target from your registry). Registers in "
            "the shared Redis registry, starts a 10s heartbeat, and attaches "
            "an inbound consumer that emits notifications/claude/channel for "
            "each XADD'd inbound message. Returns the resolved session_name "
            "+ metadata. If `endpoint` is omitted, resolves to "
            "registry.defaults.default_endpoint (falling back to the sole "
            "configured endpoint when only one exists). Pass debug=true to "
            "opt into verbose reply narration in the local terminal (useful "
            "for dev/test); default false = quiet."
        ),
    )
    async def redis_channel_connect(
        endpoint: str | None = None,
        session_name: str | None = None,
        debug: bool = False,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        notifier = _build_async_notifier(ctx)
        return _STATE.connect(
            endpoint=endpoint,
            session_name=session_name,
            notifier=notifier,
            debug=debug,
        )

    @app.tool(
        name="redis_channel_disconnect",
        description=(
            "Gracefully disconnect from the redis-channel endpoint: stops "
            "heartbeat + consumer, removes the session from the registry, "
            "and emits an 'unregistered' lifecycle event."
        ),
    )
    async def redis_channel_disconnect() -> dict[str, Any]:
        return _STATE.disconnect()

    @app.tool(
        name="redis_channel_list",
        description=(
            "List all live Claude Code sessions registered at the connected "
            "endpoint. Filters out sessions whose heartbeat has expired and "
            "lazily GCs them from the registry. Requires a prior connect."
        ),
    )
    async def redis_channel_list(ctx: Context | None = None) -> dict[str, Any]:
        # If auto-connect ran at startup, the consumer thread is still
        # deferred — attach it now that we have a live MCP context.
        _STATE.ensure_consumer_attached(_build_async_notifier(ctx))
        return _STATE.list_sessions()

    @app.tool(
        name="redis_channel_status",
        description=(
            "Report this session's current redis-channel state: "
            "connected/not, session_name, endpoint, host, uptime in "
            "seconds, whether the consumer thread is attached, and the "
            "approximate count of messages on the inbound stream. Useful "
            "for humans asking 'am I still connected?' and as a probe "
            "before sending inbound (though hb-key existence is the "
            "canonical readiness signal for external callers)."
        ),
    )
    async def redis_channel_status(ctx: Context | None = None) -> dict[str, Any]:
        _STATE.ensure_consumer_attached(_build_async_notifier(ctx))
        return _STATE.status()

    @app.tool(
        name="redis_channel_setup",
        description=(
            "Idempotent first-run setup. Symlinks ~/bin/claude-channel to "
            "this plugin's wrapper script (so the symlink follows plugin "
            "updates) and scaffolds ~/.claude/channels/redis-channel/"
            "source-env.sh + registry.json from the bundled examples if "
            "they don't already exist. Never overwrites existing config — "
            "safe to re-run after every plugin update. Returns a per-"
            "action status report so the slash command can render which "
            "files were linked/created/skipped and where to edit next."
        ),
    )
    async def redis_channel_setup(
        link_wrapper: bool = True, scaffold_configs: bool = True
    ) -> dict[str, Any]:
        return _do_setup(link_wrapper=link_wrapper, scaffold_configs=scaffold_configs)

    @app.tool(
        name="redis_channel_configure",
        description=(
            "Add or update an endpoint in the local registry file "
            "(~/.claude/channels/redis-channel/registry.json). Idempotent + "
            "atomic. Other endpoints + defaults are preserved. Pass "
            "set_default=true to make this the connect-without-args "
            "default. Does NOT create source-env.sh — use /redis-channel-"
            "setup for that. Endpoint name must match "
            "^[a-z0-9][a-z0-9_-]*$. redis_url must start with redis:// or "
            "rediss://. redis_password_env names the env var that will "
            "hold the password at runtime — populate it via source-env.sh."
        ),
    )
    async def redis_channel_configure(
        endpoint_name: str,
        redis_url: str,
        redis_password_env: str | None = None,
        display_name: str | None = None,
        set_default: bool = False,
    ) -> dict[str, Any]:
        return _configure_endpoint(
            endpoint_name=endpoint_name,
            redis_url=redis_url,
            redis_password_env=redis_password_env,
            display_name=display_name,
            set_default=set_default,
        )

    @app.tool(
        name="reply",
        description=(
            "Send a reply to the originating chat surface. The router on the "
            "other side of the redis-channel listens to outbound messages and "
            "writes them to the corresponding Discord channel/DM/thread/voice. "
            "Set voice=True to request TTS playback in the originating voice "
            "channel (router may ignore if the source wasn't voice). chat_id "
            "must match the value provided on the inbound notification. "
            "Optionally pass in_reply_to=<original message_id from the "
            "inbound notification's _msg_id field> to thread the reply. "
            "The `text` argument IS the user-facing message — it's what the "
            "recipient reads or hears via TTS. Do NOT put internal reasoning, "
            "tool-call narration, or terminal-only commentary in `text`."
        ),
    )
    async def reply(
        chat_id: str,
        text: str,
        voice: bool = False,
        in_reply_to: str | None = None,
        ctx: Context | None = None,
    ) -> CallToolResult:
        # If auto-connect ran at startup, the consumer thread is still
        # deferred — attach it now that we have a live MCP context.
        _STATE.ensure_consumer_attached(_build_async_notifier(ctx))
        result = _STATE.reply(
            chat_id=chat_id,
            text=text,
            voice=voice,
            in_reply_to=in_reply_to,
        )
        if not result.get("ok"):
            # Error path: surface the structured error as JSON text content so
            # Claude can read it and the user can see what went wrong.
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result))],
                structuredContent=result,
                isError=True,
            )
        # Success: return ONLY structuredContent — no TextContent echo. The
        # v0.4.4 echo was intended to make the terminal render the sent text,
        # but Claude Code does not render MCP TextContent as chat output
        # (debug log: "Tool ... not found in render-time tools"). Worse, the
        # echo signals to Claude that the text was "already delivered as
        # user-visible content," which appears to suppress text_block emission
        # alongside the tool call — leaving only "Called plugin:..." in the
        # terminal. Removing the echo eliminates that false signal; the
        # text_block in Claude's assistant turn is now the only path to making
        # the answer visible locally.
        return CallToolResult(
            content=[],
            structuredContent=result,
            isError=False,
        )

    return app


def _install_signal_handlers() -> None:
    def _handle(signum, _frame) -> None:  # noqa: ANN001
        log.info("received signal %s — shutting down", signum)
        _STATE.shutdown()
        sys.exit(0)

    # Signal handlers can only be installed in the main thread; if we're
    # not, FastMCP / atexit will still cover cleanup.
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(ValueError):
            signal.signal(sig, _handle)


def _enable_channel_capability(app: FastMCP) -> None:
    """Declare the `claude/channel` experimental capability in the initialize
    response so Claude Code accepts our `notifications/claude/channel` events.

    Without this, Claude Code logs: "Channel notifications skipped: server did
    not declare claude/channel capability" and silently drops every channel
    notification we emit — which makes Phase 2's text bridge a no-op from
    Claude Code's perspective.

    FastMCP doesn't expose a constructor param for experimental_capabilities,
    so we patch the underlying server's create_initialization_options to inject
    the capability whenever it's called (which happens once per `app.run()`).
    """
    server = app._mcp_server  # noqa: SLF001
    original = server.create_initialization_options

    def patched(notification_options=None, experimental_capabilities=None):  # noqa: ANN001, ANN202
        experimental_capabilities = dict(experimental_capabilities or {})
        experimental_capabilities.setdefault("claude/channel", {})
        return original(notification_options, experimental_capabilities)

    server.create_initialization_options = patched  # type: ignore[method-assign]


_AUTO_CONNECT_ENV = "CLAUDE_CHANNEL_AUTO_CONNECT"
_AUTO_CONNECT_ENDPOINT_ENV = "CLAUDE_CHANNEL_ENDPOINT"


def _maybe_auto_connect() -> None:
    """If CLAUDE_CHANNEL_AUTO_CONNECT=1, eager-register at startup.

    The gate is strict: only the literal value "1" enables. Empty, unset,
    "0", "true" — all treated as off. This avoids accidental enable from
    a leaky env or "auto_connect=true" string-typo.

    Endpoint resolution: CLAUDE_CHANNEL_ENDPOINT env var if set, else
    registry's `defaults.auto_connect_endpoint`. If both unset, no
    auto-connect happens (log warning, continue running so the user can
    still `/redis-channel-connect` manually).

    Failure modes (registry missing, endpoint not in registry, Redis
    unreachable) are caught and logged — the MCP server keeps running so
    the user can investigate from the live session.

    The consumer thread is NOT started here (no MCP Context yet for
    AsyncNotifier). The consumer group IS created (via _register_locked's
    ensure_group) so messages XADD'd between presence-publish and
    first-tool-dispatch are not lost — XREADGROUP `>` will pick them up.
    """
    gate = os.environ.get(_AUTO_CONNECT_ENV)
    if gate != "1":
        return
    # Resolution order:
    #   1. CLAUDE_CHANNEL_ENDPOINT env var (explicit, per-invocation)
    #   2. registry.defaults.auto_connect_endpoint (explicit, registry-wide)
    #   3. registry.defaults.default_endpoint via resolve_default_endpoint
    #      (which also has single-endpoint convenience fallback)
    # Steps 1 and 2 let the user PIN auto-connect to a specific endpoint
    # even when multiple are configured. Step 3 is the "just works" case
    # for users with one configured endpoint who haven't customized the
    # auto-connect field. Each step that fails to resolve falls through;
    # only fail loudly when ALL three come up empty AND we're a multi-
    # endpoint registry (single-endpoint failures already have a clear
    # error message inside resolve_default_endpoint).
    endpoint: str | None = os.environ.get(_AUTO_CONNECT_ENDPOINT_ENV)
    if not endpoint:
        try:
            registry = load_registry()
        except RegistryError as e:
            log.warning(
                "auto-connect skipped: registry error (%s). Set "
                "CLAUDE_CHANNEL_ENDPOINT or fix %s — server continuing.",
                e,
                DEFAULT_CONFIG_PATH,
            )
            return
        endpoint = registry.defaults.auto_connect_endpoint
        if not endpoint:
            # Step 3: try resolve_default_endpoint (single-endpoint
            # convenience or registry.defaults.default_endpoint).
            try:
                ep_obj = registry.resolve_default_endpoint()
                endpoint = ep_obj.name
            except EndpointNotFoundError as e:
                log.warning(
                    "auto-connect requested via %s=1 but no endpoint "
                    "resolvable: %s. Set %s, or "
                    "registry.defaults.auto_connect_endpoint, or "
                    "registry.defaults.default_endpoint. Server "
                    "continuing; use /redis-channel-connect manually.",
                    _AUTO_CONNECT_ENV,
                    e,
                    _AUTO_CONNECT_ENDPOINT_ENV,
                )
                return
    log.info("auto-connect: registering at endpoint=%s", endpoint)
    result = _STATE.startup_register(endpoint=endpoint)
    if result.get("ok"):
        log.info(
            "auto-connect: session_name=%s presence registered (consumer "
            "deferred to first tool dispatch)",
            result.get("session_name"),
        )
    else:
        log.warning(
            "auto-connect failed: %s. Server continuing; use /redis-channel-connect manually.",
            result,
        )


# Claude caches an install at ~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/.
# infiquetra-agent-plugins is this catalog. infiquetra-plugins is the marketplace
# name of the repository this package was imported from; symlinks created before
# cutover still point there and keep self-healing.
PLUGIN_CACHE_MARKETPLACES = (
    "infiquetra-agent-plugins",
    "infiquetra-plugins",
)


def _plugin_cache_markers() -> tuple[Path, ...]:
    base = Path.home() / ".claude" / "plugins" / "cache"
    return tuple(base / name / "redis-channel" for name in PLUGIN_CACHE_MARKETPLACES)


def _is_our_plugin_cache_target(symlink_target: Path) -> bool:
    """True if `symlink_target` points into our plugin's cache dir hierarchy.

    Used to bound the auto-refresh: only refresh symlinks whose target lives
    under one of ``_plugin_cache_markers()``. Symlinks pointing elsewhere
    (user-customized, dev checkouts, etc.) are left alone — we don't
    second-guess user intent.
    """
    try:
        resolved = symlink_target.resolve()
    except (OSError, RuntimeError):
        return False
    for cache_marker in _plugin_cache_markers():
        try:
            resolved.relative_to(cache_marker)
        except ValueError:
            continue
        return True
    return False


def _auto_refresh_stale_symlink() -> str | None:
    """If `~/bin/claude-channel` is a stale symlink into OUR plugin cache,
    refresh it to point at the running version's wrapper. Self-heal after
    plugin updates.

    Scope: only refresh self-managed symlinks (target inside our cache dir
    hierarchy). Don't touch:
      - missing symlinks (user hasn't run /redis-channel-setup yet — nag
        them via the existing path instead)
      - non-symlink files at the path (user installed a real script there)
      - symlinks pointing outside our cache (user customization, dev checkout)
      - broken symlinks (target doesn't exist; can't safely guess intent)

    Returns the new target string if a refresh happened, else None.
    """
    if not WRAPPER_SYMLINK.is_symlink():
        return None
    new_target = _expected_wrapper_path()
    if new_target is None or not new_target.exists():
        return None
    try:
        old_target = WRAPPER_SYMLINK.resolve()
    except (OSError, RuntimeError):
        return None
    if old_target == new_target.resolve():
        return None  # already current
    if not _is_our_plugin_cache_target(WRAPPER_SYMLINK):
        return None  # external target — don't touch
    try:
        WRAPPER_SYMLINK.unlink()
        WRAPPER_SYMLINK.symlink_to(new_target)
    except OSError as e:
        log.warning("auto-refresh symlink failed: %s", e)
        return None
    return str(new_target)


def _log_setup_nag() -> None:
    """One-shot startup check: if setup is incomplete, log a hint suggesting
    the user run /redis-channel-setup. Passive — never blocks user-facing
    work.

    Self-healing for plugin updates: if the only issue is a stale symlink
    AND that symlink already points into our plugin cache (i.e., user has
    run /redis-channel-setup before but a plugin update made their symlink
    point at the old version), auto-refresh it in-place + log INFO. The
    user doesn't need to re-run /redis-channel-setup after every plugin
    update for this common case.

    For other issues (missing symlink, missing source-env.sh, missing
    registry.json, external symlink target), keep the existing nag — those
    need user intent (the user must decide whether to set up at all, OR
    edit user config that we should never auto-create)."""
    try:
        refreshed = _auto_refresh_stale_symlink()
        if refreshed is not None:
            log.info("auto-refreshed ~/bin/claude-channel → %s", refreshed)
        state = _check_setup()
    except Exception:  # noqa: BLE001
        return  # never let the nag break the server
    if state.get("all_ready"):
        return
    issues = []
    if state.get("wrapper_symlink_status") != "current":
        issues.append(
            f"~/bin/claude-channel: {state.get('wrapper_symlink_status')} "
            f"(expected target: {state.get('wrapper_symlink_expected_target')})"
        )
    if not state.get("source_env_exists"):
        issues.append(f"missing: {state.get('source_env_path')}")
    if not state.get("registry_exists"):
        issues.append(f"missing: {state.get('registry_path')}")
    if issues:
        log.warning(
            "redis-channel setup is incomplete — run /redis-channel-setup. Issues: %s",
            "; ".join(issues),
        )


def run() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    log.info("redis-channel v%s starting (stdio)", __version__)
    atexit.register(_STATE.shutdown)
    _install_signal_handlers()
    app = build_app()
    _enable_channel_capability(app)
    _log_setup_nag()
    _maybe_auto_connect()
    app.run()  # blocks until stdio closes
    return 0
