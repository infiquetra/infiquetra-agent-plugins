"""Redis connection helper for redis-channel.

Centralizes URL parsing + password injection from env so the rest of the
server doesn't have to think about how the password gets in. Connection
pooling lives in the redis library; we just hand back a Redis client.
"""

from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote, urlparse, urlunparse

import redis

from .registry import Endpoint

# The actual `redis.Redis` and `fakeredis.FakeRedis` types are wide unions
# (sync vs async, multiple return shapes). We type the surface as Any to
# avoid leaking that complexity into call sites; the runtime duck-typing
# works for both clients without further constraint.
RedisLike = Any


def resolve_url_with_password(endpoint: Endpoint) -> str:
    """Return the Redis URL with the password substituted from env, if any.

    If `redis_password_env` is set, the named env var must be present and
    non-empty. We refuse to fall back to a passwordless connect when a
    password was specified — that masks a misconfiguration and lets the
    plugin silently talk to the wrong Redis.
    """
    if not endpoint.redis_password_env:
        return endpoint.redis_url
    password = os.environ.get(endpoint.redis_password_env)
    if not password:
        raise RuntimeError(
            f"endpoint {endpoint.name!r} requires password env var "
            f"{endpoint.redis_password_env!r} but it is unset or empty"
        )
    parsed = urlparse(endpoint.redis_url)
    # Build netloc with password injected; keep username if present (rare).
    # URL-encode both user and password so chars like ':', '@', '/', '#', '?'
    # in real Redis passwords (e.g. base64-style 44-char strings) don't break
    # redis-py's URL parser ("port could not be cast to integer" on the next
    # ':' it finds). `safe=""` quotes everything that's not unreserved.
    raw_user = parsed.username or ""
    user = quote(raw_user, safe="")
    encoded_password = quote(password, safe="")
    host = parsed.hostname or ""
    port_suffix = f":{parsed.port}" if parsed.port else ""
    auth_prefix = f"{user}:{encoded_password}@" if user else f":{encoded_password}@"
    netloc = f"{auth_prefix}{host}{port_suffix}"
    return urlunparse(parsed._replace(netloc=netloc))


def connect(endpoint: Endpoint, *, socket_timeout: float = 5.0) -> redis.Redis:
    """Open and ping a Redis client. Raises on auth/network failure."""
    url = resolve_url_with_password(endpoint)
    client = redis.Redis.from_url(
        url,
        decode_responses=True,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_timeout,
    )
    client.ping()
    return client
