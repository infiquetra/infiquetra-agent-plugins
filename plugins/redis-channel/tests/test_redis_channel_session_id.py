"""Tests for redis-channel session_id auto-naming + override validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from server import session_id  # type: ignore[import-not-found]


def test_auto_session_name_is_stable_across_calls(tmp_path: Path) -> None:
    name1 = session_id.auto_session_name(cwd=tmp_path, host="example.local")
    name2 = session_id.auto_session_name(cwd=tmp_path, host="example.local")
    assert name1 == name2


def test_auto_session_name_differs_per_host(tmp_path: Path) -> None:
    a = session_id.auto_session_name(cwd=tmp_path, host="hostA")
    b = session_id.auto_session_name(cwd=tmp_path, host="hostB")
    assert a != b
    assert a.split("-")[0] == b.split("-")[0]  # basename matches


def test_auto_session_name_differs_per_cwd(tmp_path: Path) -> None:
    p1 = tmp_path / "project-one"
    p2 = tmp_path / "project-two"
    p1.mkdir()
    p2.mkdir()
    a = session_id.auto_session_name(cwd=p1, host="h")
    b = session_id.auto_session_name(cwd=p2, host="h")
    assert a != b


def test_auto_session_name_format(tmp_path: Path) -> None:
    """Format: <slug>-<8 hex chars>."""
    proj = tmp_path / "Hello World!"
    proj.mkdir()
    name = session_id.auto_session_name(cwd=proj, host="h")
    assert session_id.is_valid_session_name(name)
    slug, _, suffix = name.rpartition("-")
    assert slug == "hello-world"
    assert len(suffix) == 8
    assert all(c in "0123456789abcdef" for c in suffix)


def test_auto_session_name_handles_empty_basename(tmp_path: Path) -> None:
    name = session_id.auto_session_name(cwd="/", host="h")
    assert name.startswith("session-")


def test_resolve_uses_explicit_override(tmp_path: Path) -> None:
    out = session_id.resolve_session_name(override="my-name", cwd=tmp_path, host="h")
    assert out == "my-name"


def test_resolve_uses_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("CLAUDE_SESSION_NAME", "via-env")
    out = session_id.resolve_session_name(cwd=tmp_path, host="h")
    assert out == "via-env"


def test_resolve_falls_back_to_auto(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CLAUDE_SESSION_NAME", raising=False)
    out = session_id.resolve_session_name(cwd=tmp_path, host="h")
    assert "-" in out


def test_resolve_rejects_invalid_override(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid session name"):
        session_id.resolve_session_name(override="Has Spaces", cwd=tmp_path, host="h")


def test_resolve_rejects_uppercase_override(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        session_id.resolve_session_name(override="UPPER", cwd=tmp_path, host="h")


def test_resolve_rejects_overlong_override(tmp_path: Path) -> None:
    long_name = "a" * 65
    with pytest.raises(ValueError):
        session_id.resolve_session_name(override=long_name, cwd=tmp_path, host="h")


def test_is_valid_session_name() -> None:
    assert session_id.is_valid_session_name("foo")
    assert session_id.is_valid_session_name("foo-bar-123")
    assert session_id.is_valid_session_name("foo_bar")
    assert session_id.is_valid_session_name("a")
    assert not session_id.is_valid_session_name("")
    assert not session_id.is_valid_session_name("-leading-hyphen")
    assert not session_id.is_valid_session_name("Has-Upper")
    assert not session_id.is_valid_session_name("has space")
    assert not session_id.is_valid_session_name("has/slash")
