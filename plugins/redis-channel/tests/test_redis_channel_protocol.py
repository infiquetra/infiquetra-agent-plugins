"""Tests for the redis-channel plugin's protocol pydantic models.

Pins the wire format; any change here means PROTOCOL.md must change (and the
matching change must land in a router that speaks the same protocol).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pydantic")

from server.protocol import (  # noqa: E402
    PROTOCOL_VERSION,
    Inbound,
    LifecycleEvent,
    Outbound,
    PermissionRequest,
    PermissionVerdict,
    RegistryEntry,
    is_destructive,
)


def test_protocol_version_is_1() -> None:
    assert PROTOCOL_VERSION == 1


def test_inbound_minimal_voice() -> None:
    msg = Inbound(
        router="hermes-claude-code-router",
        endpoint="mimir",
        source="voice",
        chat_id="vc-123",
        user_id="u-456",
        username="jeff",
        text="what's the status of pr 117",
        confidence=0.93,
        ts=1716567890.0,
    )
    assert msg.v == 1
    assert msg.source == "voice"


def test_inbound_rejects_unknown_source() -> None:
    with pytest.raises(ValueError):
        Inbound(
            router="x",
            endpoint="y",
            source="telegram",  # type: ignore[arg-type]
            chat_id="c",
            user_id="u",
            username="n",
            text="hi",
            ts=0.0,
        )


def test_outbound_defaults_voice_false() -> None:
    msg = Outbound(
        session_name="s",
        endpoint="mimir",
        chat_id="c",
        text="hi",
        ts=0.0,
    )
    assert msg.voice is False


def test_registry_entry_serializes_capabilities() -> None:
    entry = RegistryEntry(
        session_name="s",
        host="h",
        cwd="/tmp",
        pid=1,
        started_at=0.0,
        capabilities=["reply", "permission"],
    )
    dumped = entry.model_dump()
    assert "permission" in dumped["capabilities"]


def test_permission_request_destructive_field() -> None:
    pr = PermissionRequest(
        session_name="s",
        endpoint="mimir",
        request_id="abcde",
        tool_name="Bash",
        input_preview="git push --force",
        destructive=True,
        originating_chat_id="c",
        ts=0.0,
    )
    assert pr.destructive is True
    assert len(pr.request_id) == 5


def test_permission_verdict_echo_outcome_default() -> None:
    pv = PermissionVerdict(
        session_name="s",
        endpoint="mimir",
        request_id="abcde",
        verdict="allow",
        source="voice",
        ts=0.0,
    )
    assert pv.echo_confirm_outcome == "not_required"


def test_lifecycle_event_minimal() -> None:
    ev = LifecycleEvent(type="registered", session_name="s", ts=0.0)
    assert ev.type == "registered"


# ─── is_destructive classifier ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "tool,inp,expected",
    [
        ("Write", "anything", True),
        ("Edit", "anything", True),
        ("NotebookEdit", "anything", True),
        ("Read", "anything", False),
        ("Glob", "anything", False),
        ("Bash", "ls -la", False),
        ("Bash", "git status", False),
        ("Bash", "rm -rf /tmp/foo", True),
        ("Bash", "rm -fr /tmp/foo", True),
        ("Bash", "git push --force", True),
        ("Bash", "git push -f origin main", True),
        ("Bash", "git reset --hard HEAD~3", True),
        ("Bash", "git clean -fd", True),
        ("Bash", "git branch -D feature/x", True),
        ("Bash", "psql -c 'DROP TABLE users;'", True),
        ("Bash", "psql -c 'drop table users'", True),
        ("Bash", "psql -c 'DELETE FROM users WHERE 1=1'", True),
        ("Bash", "psql -c 'TRUNCATE TABLE users'", True),
        ("Bash", "dd if=/dev/zero of=/dev/disk0", True),
    ],
)
def test_is_destructive(tool: str, inp: str, expected: bool) -> None:
    assert is_destructive(tool, inp) is expected


# Additive producer adapter; keep the original model and classifier assertions.
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

_CONTRACT = Path(__file__).resolve().parents[1] / "contracts/protocol-v1.json"
_CONTRACT_SHA = "d06c671304cb3b4d46b99ea5cec26223d170b5ec89f7ed9f5ac071f1935f5278"
_IDS = (
    "model.registry", "model.inbound", "model.outbound", "model.request",
    "model.verdict", "model.lifecycle", "model.invalid-source", "wire.sorted",
    "wire.nested", "envelope.missing", "envelope.invalid-json", "envelope.non-object",
)
_MODELS = {c.__name__: c for c in (
    RegistryEntry, Inbound, Outbound, PermissionRequest, PermissionVerdict, LifecycleEvent,
)}


def _validate_vectors(doc):
    assert set(doc) == {"schema", "fixture_version", "protocol_version", "vectors"}
    assert doc["schema"] == "redis-channel.protocol-vectors"
    for key in ("fixture_version", "protocol_version"):
        assert type(doc[key]) is int and doc[key] == 1
    rows = doc["vectors"]
    assert type(rows) is list and tuple(r["id"] for r in rows) == _IDS
    kinds = ["model"] * 6 + ["invalid"] + ["wire"] * 2 + ["drop"] * 3
    fields = {"model": {"model", "input", "expected"}, "invalid": {"model", "input"},
              "wire": {"input", "wire"}, "drop": {"fields"}}
    for row, kind in zip(rows, kinds, strict=True):
        assert row["kind"] == kind
        assert set(row) == {"id", "kind"} | fields[kind]
    return rows


def _contract(raw=None):
    raw = _CONTRACT.read_bytes() if raw is None else raw
    assert hashlib.sha256(raw).hexdigest() == _CONTRACT_SHA
    return _validate_vectors(json.loads(raw))


@pytest.mark.parametrize("vector", _contract(), ids=lambda v: v["id"])
def test_producer_contract_vector(vector):
    kind = vector["kind"]
    if kind in ("model", "invalid"):
        model = _MODELS[vector["model"]]
        if kind == "invalid":
            with pytest.raises(ValueError):
                model.model_validate(vector["input"])
        else:
            assert model.model_validate(vector["input"]).model_dump(mode="json") == vector["expected"]
        return
    from server.redis_consumer import Consumer
    from server.redis_producer import publish_outbound

    client = Mock()
    received = []
    if kind == "wire":
        client.xadd.return_value = "1-0"
        assert publish_outbound(client, "fixture", vector["input"]) == "1-0"
        assert client.xadd.call_args.args[1] == {"payload": vector["wire"]}
        fields = {"payload": vector["wire"]}
    else:
        fields = vector["fields"]
    Consumer(client, "fixture", received.append)._dispatch("1-0", fields)
    expected = [dict(vector["input"], _msg_id="1-0")] if kind == "wire" else []
    assert received == expected
    client.xack.assert_called_once_with("cc-sessions:fixture:inbound", "cc:fixture", "1-0")


def test_contract_structure_and_digest_guards():
    _contract()
    original = json.loads(_CONTRACT.read_bytes())
    for fault in ("schema", "version", "missing", "duplicate", "shape"):
        doc = copy.deepcopy(original)
        if fault == "schema":
            doc["schema"] = "unknown"
        elif fault == "version":
            doc["fixture_version"] = 2
        elif fault == "missing":
            doc["vectors"].pop()
        elif fault == "duplicate":
            doc["vectors"][-1] = doc["vectors"][0]
        else:
            del doc["vectors"][0]["expected"]
        with pytest.raises(AssertionError):
            _validate_vectors(doc)
    with pytest.raises(AssertionError):
        _contract(_CONTRACT.read_bytes() + b" ")
