"""Tests for the redis-channel Redis-connection helper.

Focus: URL building with password env injection. The redis-py URL parser
splits on ':' so unencoded passwords containing ':' (very common in
44-char base64-ish secrets) produce "Port could not be cast to integer"
errors — caught by integration test 2026-05-25; this is the regression
test.
"""

from __future__ import annotations

from urllib.parse import unquote, urlparse

import pytest

pytest.importorskip("redis")

from server import redis_client  # type: ignore[import-not-found]
from server.registry import Endpoint  # type: ignore[import-not-found]


def _endpoint(
    redis_password_env: str | None = None,
    redis_url: str = "redis://example.host:6379/0",
) -> Endpoint:
    return Endpoint(
        name="mimir",
        redis_url=redis_url,
        redis_password_env=redis_password_env,
        display_name="test",
    )


def test_no_password_returns_url_unchanged() -> None:
    ep = _endpoint(redis_password_env=None)
    assert redis_client.resolve_url_with_password(ep) == ep.redis_url


def test_password_env_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MISSING_PW", raising=False)
    ep = _endpoint(redis_password_env="MISSING_PW")
    with pytest.raises(RuntimeError, match="MISSING_PW"):
        redis_client.resolve_url_with_password(ep)


def test_password_env_empty_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMPTY_PW", "")
    ep = _endpoint(redis_password_env="EMPTY_PW")
    with pytest.raises(RuntimeError, match="EMPTY_PW"):
        redis_client.resolve_url_with_password(ep)


def test_simple_password_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PW", "simple")
    ep = _endpoint(redis_password_env="PW")
    url = redis_client.resolve_url_with_password(ep)
    parsed = urlparse(url)
    assert parsed.password == "simple"
    assert parsed.hostname == "example.host"
    assert parsed.port == 6379


def test_password_with_colon_is_url_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: a password containing ':' (URL delimiter for user:pass and
    host:port) MUST be percent-encoded, otherwise redis-py raises:
    'Port could not be cast to integer value as <suffix-of-password>'."""
    monkeypatch.setenv("PW", "abc:def:ghi")
    ep = _endpoint(redis_password_env="PW")
    url = redis_client.resolve_url_with_password(ep)
    # The percent-encoded form of ':' is %3A; assert the literal substring.
    assert "abc%3Adef%3Aghi" in url
    # Round-trip: urlparse must NOT misinterpret the host/port.
    parsed = urlparse(url)
    assert parsed.hostname == "example.host"
    assert parsed.port == 6379
    # urlparse keeps passwords percent-encoded; unquote to recover the
    # original. Redis-py applies its own unquote internally.
    assert unquote(parsed.password or "") == "abc:def:ghi"


def test_password_with_at_sign_is_url_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """'@' separates auth from host; must be percent-encoded in the password."""
    monkeypatch.setenv("PW", "weird@password")
    ep = _endpoint(redis_password_env="PW")
    url = redis_client.resolve_url_with_password(ep)
    assert "weird%40password" in url
    parsed = urlparse(url)
    assert parsed.hostname == "example.host"
    assert unquote(parsed.password or "") == "weird@password"


def test_password_with_slash_is_url_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """'/' separates auth segment from path; must be percent-encoded."""
    monkeypatch.setenv("PW", "with/slash/in/it")
    ep = _endpoint(redis_password_env="PW")
    url = redis_client.resolve_url_with_password(ep)
    assert "with%2Fslash%2Fin%2Fit" in url
    parsed = urlparse(url)
    assert unquote(parsed.password or "") == "with/slash/in/it"
    assert parsed.path == "/0"  # /0 db selector preserved


def test_base64ish_44char_password_round_trips(monkeypatch: pytest.MonkeyPatch) -> None:
    """The actual shape of a real Hermes Redis password: 44 chars, base64-ish
    with possible '/' '+' '=' chars."""
    pw = "YPPu3qQ0VkURKkkm1J81l4abcdef+/abcdef+/abcdef"  # synthetic, 44 chars
    monkeypatch.setenv("PW", pw)
    ep = _endpoint(redis_password_env="PW")
    url = redis_client.resolve_url_with_password(ep)
    parsed = urlparse(url)
    assert unquote(parsed.password or "") == pw
    assert parsed.hostname == "example.host"
    assert parsed.port == 6379
    assert parsed.path == "/0"


def test_db_index_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PW", "p")
    ep = _endpoint(redis_password_env="PW", redis_url="redis://h:6379/3")
    url = redis_client.resolve_url_with_password(ep)
    parsed = urlparse(url)
    assert parsed.path == "/3"
