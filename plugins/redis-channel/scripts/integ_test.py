#!/usr/bin/env python3
"""Headless integration test for redis-channel against a live Redis.

Drives `python -m server` (the MCP stdio server) via JSON-RPC + observes the
real Redis side-effects. Exercises:

  1. MCP initialize handshake.
  2. redis_channel_connect tool → presence + heartbeat + consumer attached.
  3. Direct XADD onto cc-sessions:<name>:inbound from a side Redis client.
  4. notifications/claude/channel notification frame on server stdout.
  5. reply tool → outbound XADD verified by reading the stream back.
  6. redis_channel_disconnect → registry + hb key gone.
  7. (separate run) SIGKILL → hb key expires within 60s, registry GC'd on
     next list from a fresh connect.

Exits 0 on full pass; nonzero on any failure. Prints a step-by-step trace
to stderr so we can see what happened either way.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

# ─── Configuration ───────────────────────────────────────────────────────────

# Plugin root = parent of scripts/ dir. Works regardless of worktree location.
PLUGIN_DIR = Path(__file__).resolve().parent.parent
# Filled by load_integration_config(). Importing this module does not read a
# password and does not contact Redis. The live run skips until both
# REDIS_CHANNEL_INTEG_HOST and REDIS_CHANNEL_INTEG_PASSWORD are set.
REDIS_HOST = ""
REDIS_PORT = 6379
REDIS_PASSWORD = ""
TEST_SESSION_NAME = "integ-test-headless"
NOTIFICATION_WAIT_S = 5.0
SHUTDOWN_WAIT_S = 5.0

REGISTRY_KEY = "cc-sessions:registry"
HB_KEY = f"cc-sessions:hb:{TEST_SESSION_NAME}"
INBOUND = f"cc-sessions:{TEST_SESSION_NAME}:inbound"
OUTBOUND = f"cc-sessions:{TEST_SESSION_NAME}:outbound"

CHANNEL_METHOD = "notifications/claude/channel"


def trace(msg: str) -> None:
    print(f"[harness] {msg}", file=sys.stderr, flush=True)


# ─── MCP stdio client ───────────────────────────────────────────────────────


class MCPClient:
    """Minimal MCP stdio client. Owns subprocess + reader thread + correlator."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self._next_id = 1
        self._lock = threading.Lock()
        self._responses: dict[int, dict[str, Any]] = {}
        self._notifications: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stop = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._stderr_loop, daemon=True)
        self._stderr_reader.start()

    @property
    def proc(self) -> subprocess.Popen:
        return self._proc

    def _read_loop(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            if self._stop.is_set():
                return
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                trace(f"NON-JSON stdout: {line[:200]!r}")
                continue
            if "id" in msg and ("result" in msg or "error" in msg):
                with self._lock:
                    self._responses[msg["id"]] = msg
            elif "method" in msg:
                trace(f"server NOTIF: {msg.get('method')} params={msg.get('params')}")
                self._notifications.put(msg)
            else:
                trace(f"unrecognized frame: {msg}")

    def _stderr_loop(self) -> None:
        """Mirror server stderr so we can see logs."""
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            if self._stop.is_set():
                return
            sys.stderr.write(f"[server] {line}")
            sys.stderr.flush()

    def send_notification(self, method: str, params: dict | None = None) -> None:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def call(
        self, method: str, params: dict | None = None, timeout: float = 10.0
    ) -> dict[str, Any]:
        with self._lock:
            req_id = self._next_id
            self._next_id += 1
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)
        deadline = time.time() + timeout
        while time.time() < deadline:
            with self._lock:
                resp = self._responses.pop(req_id, None)
            if resp is not None:
                return resp
            time.sleep(0.05)
        raise TimeoutError(f"no response to {method} (id={req_id}) within {timeout}s")

    def pop_notification(
        self, method_filter: str | None = None, timeout: float = 5.0
    ) -> dict[str, Any] | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                remaining = max(0.0, deadline - time.time())
                msg = self._notifications.get(timeout=remaining)
            except queue.Empty:
                return None
            if method_filter is None or msg.get("method") == method_filter:
                return msg
            trace(
                f"discarding notification {msg.get('method')!r} while waiting for {method_filter!r}"
            )
        return None

    def drain_notifications(self) -> Iterator[dict[str, Any]]:
        while True:
            try:
                yield self._notifications.get_nowait()
            except queue.Empty:
                return

    def _write(self, msg: dict[str, Any]) -> None:
        line = json.dumps(msg, separators=(",", ":")) + "\n"
        assert self._proc.stdin is not None
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

    def shutdown(self, *, force: bool = False) -> int | None:
        self._stop.set()
        if force:
            self._proc.kill()
        else:
            self._proc.terminate()
        try:
            return self._proc.wait(timeout=SHUTDOWN_WAIT_S)
        except subprocess.TimeoutExpired:
            trace("server didn't exit on terminate; SIGKILL")
            self._proc.kill()
            return self._proc.wait(timeout=2)


# ─── Helpers ────────────────────────────────────────────────────────────────


def load_integration_config() -> bool:
    """Read the live-Redis settings. False means the run should skip."""
    global REDIS_HOST, REDIS_PORT, REDIS_PASSWORD
    host = os.environ.get("REDIS_CHANNEL_INTEG_HOST", "").strip()
    password = os.environ.get("REDIS_CHANNEL_INTEG_PASSWORD", "")
    if not host or not password:
        return False
    REDIS_HOST = host
    REDIS_PORT = int(os.environ.get("REDIS_CHANNEL_INTEG_PORT", "6379"))
    REDIS_PASSWORD = password
    return True


def spawn_server() -> MCPClient:
    env = os.environ.copy()
    # The server reads the password from the env var named by the deployment
    # registry's redis_password_env field. REDIS_CHANNEL_INTEG_VAR names that
    # variable. The default is REDIS_CHANNEL_INTEG_PASSWORD, which is also
    # where this harness reads the password from.
    password_var = os.environ.get("REDIS_CHANNEL_INTEG_VAR", "REDIS_CHANNEL_INTEG_PASSWORD")
    env[password_var] = REDIS_PASSWORD
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(PLUGIN_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    trace(f"spawning: {sys.executable} -m server")
    proc = subprocess.Popen(
        [sys.executable, "-m", "server"],
        cwd=str(PLUGIN_DIR),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        bufsize=1,
    )
    return MCPClient(proc)


def new_redis():  # noqa: ANN201 - redis is imported only for a live run
    import redis

    return redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        password=REDIS_PASSWORD,
        decode_responses=True,
        socket_timeout=5,
    )


def cleanup_test_keys(r) -> None:  # noqa: ANN001 - redis client, imported only for a live run
    """Best-effort scrub of anything from a previous run."""
    r.hdel(REGISTRY_KEY, TEST_SESSION_NAME)
    r.delete(HB_KEY, INBOUND, OUTBOUND)


def assert_ok(label: str, result: dict[str, Any]) -> dict[str, Any]:
    if "error" in result:
        raise AssertionError(f"{label}: JSON-RPC error: {result['error']}")
    inner = result.get("result", {})
    # FastMCP returns tool results inside structuredContent (or content[0].text).
    structured = inner.get("structuredContent") or inner.get("structured_content")
    if structured is not None:
        return structured
    # Fallback: parse the text content
    contents = inner.get("content", [])
    for item in contents:
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except (KeyError, json.JSONDecodeError):
                continue
    raise AssertionError(f"{label}: couldn't extract structured result from {inner!r}")


# ─── Test phases ────────────────────────────────────────────────────────────


def phase_a_clean_connect_and_inbound(client: MCPClient, r: redis.Redis) -> None:
    trace("=== Phase A: initialize + connect + inbound notification ===")

    # Initialize handshake
    init_resp = client.call(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "integ-test", "version": "0.1"},
        },
    )
    if "error" in init_resp:
        raise AssertionError(f"initialize errored: {init_resp['error']}")
    trace(f"server capabilities: {init_resp['result'].get('capabilities')}")
    client.send_notification("notifications/initialized")

    # Connect
    cn = assert_ok(
        "connect",
        client.call(
            "tools/call",
            {
                "name": "redis_channel_connect",
                "arguments": {
                    "endpoint": "mimir",
                    "session_name": TEST_SESSION_NAME,
                },
            },
            timeout=10,
        ),
    )
    assert cn.get("ok") is True, f"connect ok=false: {cn}"
    assert cn["session_name"] == TEST_SESSION_NAME
    assert cn["consumer_attached"] is True
    assert cn["notifier_kind"] == "AsyncNotifier"
    trace(f"connect: ok session={cn['session_name']} notifier={cn['notifier_kind']}")

    # Verify Redis side: registry entry + hb key
    raw = r.hget(REGISTRY_KEY, TEST_SESSION_NAME)
    if raw is None:
        raise AssertionError("Redis: registry entry missing after connect")
    meta = json.loads(raw)
    assert meta["session_name"] == TEST_SESSION_NAME
    assert meta["endpoint"] == "mimir"
    trace(f"redis: registry has entry pid={meta['pid']} host={meta['host']}")
    if not r.exists(HB_KEY):
        raise AssertionError("Redis: hb key missing after connect")
    ttl = r.ttl(HB_KEY)
    assert 1 <= ttl <= 60, f"hb TTL out of range: {ttl}"
    trace(f"redis: hb TTL={ttl}s")

    # XADD an inbound message — verify it reaches us as a notification
    payload = {
        "v": 1,
        "router": "integ-test",
        "endpoint": "mimir",
        "source": "dm",
        "chat_id": "test-chat",
        "user_id": "u-test",
        "username": "tester",
        "text": "hello from headless harness",
        "ts": time.time(),
    }
    inbound_msg_id = r.xadd(INBOUND, {"payload": json.dumps(payload)})
    trace(f"redis: XADD inbound → msg_id={inbound_msg_id}")

    notif = client.pop_notification(CHANNEL_METHOD, timeout=NOTIFICATION_WAIT_S)
    if notif is None:
        raise AssertionError(
            f"server never emitted {CHANNEL_METHOD!r} within {NOTIFICATION_WAIT_S}s"
        )
    params = notif.get("params", {})
    assert params.get("text") == "hello from headless harness"
    assert params.get("chat_id") == "test-chat"
    assert params.get("_msg_id") == inbound_msg_id
    trace(f"notification arrived: chat_id={params['chat_id']} msg_id={params['_msg_id']}")


def phase_b_reply(client: MCPClient, r: redis.Redis) -> None:
    trace("=== Phase B: reply tool round-trip ===")

    rep = assert_ok(
        "reply",
        client.call(
            "tools/call",
            {
                "name": "reply",
                "arguments": {
                    "chat_id": "test-chat",
                    "text": "ack from CC side",
                    "voice": False,
                    "in_reply_to": "test-msg-id",
                },
            },
            timeout=5,
        ),
    )
    assert rep.get("ok") is True, f"reply ok=false: {rep}"
    out_msg_id = rep["msg_id"]
    trace(f"reply: ok msg_id={out_msg_id}")

    entries = r.xrange(OUTBOUND)
    if not entries:
        raise AssertionError("Redis: outbound stream empty after reply")
    last_id, fields = entries[-1]
    if last_id != out_msg_id:
        raise AssertionError(
            f"Redis: outbound last id={last_id} doesn't match tool result {out_msg_id}"
        )
    out = json.loads(fields["payload"])
    assert out["text"] == "ack from CC side"
    assert out["chat_id"] == "test-chat"
    assert out["session_name"] == TEST_SESSION_NAME
    assert out["endpoint"] == "mimir"
    assert out["in_reply_to"] == "test-msg-id"
    trace(f"redis: outbound has matching payload, in_reply_to={out['in_reply_to']}")


def phase_c_disconnect(client: MCPClient, r: redis.Redis) -> None:
    trace("=== Phase C: graceful disconnect ===")
    dc = assert_ok(
        "disconnect",
        client.call(
            "tools/call",
            {"name": "redis_channel_disconnect", "arguments": {}},
            timeout=5,
        ),
    )
    assert dc.get("ok") is True, f"disconnect ok=false: {dc}"
    assert dc.get("was_connected") is True
    # Confirm Redis state cleared
    assert r.hget(REGISTRY_KEY, TEST_SESSION_NAME) is None, "registry entry not deleted"
    assert not r.exists(HB_KEY), "hb key not deleted"
    trace("redis: registry + hb cleared")


def phase_d_sigkill_gc(r: redis.Redis) -> None:
    """Phase D — separate run. Spawn server, connect, SIGKILL, wait, verify
    the hb key TTL has expired and a fresh connect/list reaps the entry."""
    trace("=== Phase D: SIGKILL + GC ===")
    client = spawn_server()
    try:
        client.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "integ-test-d", "version": "0.1"},
            },
        )
        client.send_notification("notifications/initialized")
        cn = assert_ok(
            "connect-d",
            client.call(
                "tools/call",
                {
                    "name": "redis_channel_connect",
                    "arguments": {
                        "endpoint": "mimir",
                        "session_name": TEST_SESSION_NAME + "-sigkill",
                    },
                },
                timeout=10,
            ),
        )
        sk_name = cn["session_name"]
        sk_hb = f"cc-sessions:hb:{sk_name}"
        if not r.exists(sk_hb):
            raise AssertionError("sigkill phase: hb key missing after connect")
        trace(f"sigkill phase: registered {sk_name}; killing pid={client.proc.pid}")
        # SIGKILL — no graceful unregister
        client.proc.send_signal(signal.SIGKILL)
        client.proc.wait(timeout=2)
        # Registry entry will be stale: hash still there, but hb TTL counting down.
        # ttl_seconds default in registry.json = 60.
        # Heartbeat was set ~moment ago with ex=60.
        # We DON'T want to wait 60s in this test. Verify the *eventual* GC
        # mechanism by simulating ttl expiry: just DEL the hb key and
        # check that a fresh `list` from a new connect reaps it.
        r.delete(sk_hb)
        trace("sigkill phase: hb key deleted (simulates 60s expiry)")
    finally:
        if client.proc.poll() is None:
            client.shutdown(force=True)

    # Spawn a fresh server, connect under a different name, list — should
    # GC the stale entry.
    client2 = spawn_server()
    try:
        client2.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "integ-test-d2", "version": "0.1"},
            },
        )
        client2.send_notification("notifications/initialized")
        assert_ok(
            "connect-d2",
            client2.call(
                "tools/call",
                {
                    "name": "redis_channel_connect",
                    "arguments": {
                        "endpoint": "mimir",
                        "session_name": TEST_SESSION_NAME + "-gc-driver",
                    },
                },
                timeout=10,
            ),
        )
        lst = assert_ok(
            "list",
            client2.call(
                "tools/call",
                {"name": "redis_channel_list", "arguments": {}},
                timeout=5,
            ),
        )
        assert lst.get("ok") is True
        names = {s["session_name"] for s in lst["sessions"]}
        sk_name = TEST_SESSION_NAME + "-sigkill"
        if sk_name in names:
            raise AssertionError(f"GC failed: sigkilled session {sk_name!r} still in list output")
        if r.hexists(REGISTRY_KEY, sk_name):
            raise AssertionError(f"GC failed: sigkilled session {sk_name!r} still in registry hash")
        trace("sigkill phase: GC confirmed via list call")
    finally:
        # Best effort: disconnect, then shutdown
        with contextlib.suppress(Exception):
            client2.call(
                "tools/call",
                {"name": "redis_channel_disconnect", "arguments": {}},
                timeout=5,
            )
        client2.shutdown()


# ─── Driver ─────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    import argparse

    argparse.ArgumentParser(
        prog="integ_test.py",
        description=(
            "Drive the redis-channel MCP server against a live Redis. "
            "Skips unless REDIS_CHANNEL_INTEG_HOST and "
            "REDIS_CHANNEL_INTEG_PASSWORD are set. "
            "REDIS_CHANNEL_INTEG_PORT defaults to 6379."
        ),
    ).parse_args(argv)
    if not load_integration_config():
        print(
            "skip: set REDIS_CHANNEL_INTEG_HOST and REDIS_CHANNEL_INTEG_PASSWORD "
            "to run the live Redis integration",
            file=sys.stderr,
        )
        return 0
    try:
        import redis  # noqa: F401
    except ModuleNotFoundError:
        print(
            "redis-channel integ: install the redis package to run the live integration",
            file=sys.stderr,
        )
        return 1
    r = new_redis()
    if not r.ping():
        trace("FAIL: redis ping failed")
        return 2
    trace(f"redis OK: {REDIS_HOST}:{REDIS_PORT}")
    cleanup_test_keys(r)
    # Also cleanup any sigkill-phase leftovers
    sigkill_name = TEST_SESSION_NAME + "-sigkill"
    gc_driver_name = TEST_SESSION_NAME + "-gc-driver"
    for n in (sigkill_name, gc_driver_name):
        r.hdel(REGISTRY_KEY, n)
        r.delete(f"cc-sessions:hb:{n}")
        r.delete(f"cc-sessions:{n}:inbound")
        r.delete(f"cc-sessions:{n}:outbound")

    def run_phase(name: str, fn, *args) -> bool:
        trace("")
        trace(f">>> Phase {name} START")
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            import traceback

            trace(f"<<< Phase {name} FAILED: {type(e).__name__}: {e}")
            trace("    traceback:")
            for line in traceback.format_exc().splitlines():
                trace(f"    {line}")
            failures.append(f"{name}: {type(e).__name__}: {e}")
            return False
        trace(f"<<< Phase {name} PASSED")
        return True

    client = spawn_server()
    failures: list[str] = []
    try:
        run_phase("A", phase_a_clean_connect_and_inbound, client, r)
        run_phase("B", phase_b_reply, client, r)
        run_phase("C", phase_c_disconnect, client, r)
    finally:
        client.shutdown()

    run_phase("D", phase_d_sigkill_gc, r)

    cleanup_test_keys(r)
    for n in (sigkill_name, gc_driver_name):
        r.hdel(REGISTRY_KEY, n)
        r.delete(f"cc-sessions:hb:{n}")
        r.delete(f"cc-sessions:{n}:inbound")
        r.delete(f"cc-sessions:{n}:outbound")

    if failures:
        trace("=" * 60)
        trace("FAILURES:")
        for f in failures:
            trace(f"  ✗ {f}")
        return 1
    trace("=" * 60)
    trace("ALL PHASES PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
