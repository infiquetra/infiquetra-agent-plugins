"""Machine-specific values are unanswered where-to-look items (issue 155)."""

from __future__ import annotations

import importlib.util
import json
import socket
from pathlib import Path
from typing import Any

import pytest


def _harness() -> Any:
    path = Path(__file__).resolve().parent / "review_check_harness.py"
    spec = importlib.util.spec_from_file_location("review_check_harness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


H = _harness()

ROW = "architecture-maintainability.machine-specific-value"
KINDS = {
    "unix-path", "windows-path", "unc", "home", "url", "account-id", "user", "host",
}
SECRETS = (
    "/var/log/example-app",
    "C:\\Program",
    "fileserver",
    "build-agent",
    "builder.example.test",
    "123456789012",
    "fixture-user",
    "fixture-host",
    "example-app",
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sockets stay refused. The host name is patched on socket.gethostname."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("scripted check tests must make no network call")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def _identity(monkeypatch: pytest.MonkeyPatch, user: str, host: str) -> None:
    monkeypatch.setattr("getpass.getuser", lambda: user)
    monkeypatch.setattr(socket, "gethostname", lambda: host)


def _sample(user: str, host: str) -> str:
    home = "/home/" + "build-agent" + "/work"
    text = " ".join((
        "/var/log/example-app",
        "C:\\Program Files\\Example\\app.exe",
        "\\\\fileserver\\share\\data",
        home,
        "https://builder.example.test/hook",
        "123456789012",
        user,
        host,
    ))
    return 'note = "' + text + '"\n'


def _kinds(items: list[dict[str, Any]]) -> set[str]:
    return {str(item["location"]["anchor"]).split(":")[1] for item in items}


def _omits(items: list[dict[str, Any]]) -> None:
    raw = json.dumps(items)
    for secret in SECRETS:
        assert secret not in raw
        assert json.dumps(secret)[1:-1] not in raw


def test_each_kind_is_an_unanswered_item(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity(monkeypatch, "fixture-user", "fixture-host")
    code, output, *_rest = H.one(
        tmp_path,
        {"readme.txt": "a\n"},
        {"readme.txt": "a\n", "sample.py": _sample("fixture-user", "fixture-host")},
        "machine-values",
        "echo ok",
    )
    assert code == 0
    items = H.read(output, "where-to-look.json")
    assert _kinds(items) == KINDS
    _omits(items)
    for item in items:
        assert "answer" not in item
        assert item["location"]["function"] is None
        assert item["location"]["file"] == "sample.py"
        assert item["language"] == "python"
        stored = dict(item)
        stored["answer"] = {"kind": "cleared", "reason": "The reviewer cleared this hit."}
        assert H.R.validate(stored) == []
    assert all(item["rule"]["row"] != ROW for item in H.read(output, "findings.json"))


def test_an_unchanged_line_yields_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity(monkeypatch, "fixture-user", "fixture-host")
    kept = "keep = '/var/log/example-app'\nvalue = 1\n"
    code, output, *_rest = H.one(
        tmp_path,
        {"sample.py": kept},
        {"sample.py": "keep = '/var/log/example-app'\nvalue = 2\n"},
        "machine-values",
        "echo ok",
    )
    assert code == 0
    assert H.read(output, "where-to-look.json") == []


def test_inert_values_yield_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _identity(monkeypatch, "ab", "example.com")
    text = "note = '/home/operator/work https://example.com/status 1234567890123'\n"
    code, output, *_rest = H.one(
        tmp_path,
        {"readme.txt": "a\n"},
        {"readme.txt": "a\n", "sample.py": text},
        "machine-values",
        "echo ok",
    )
    assert code == 0
    assert H.read(output, "where-to-look.json") == []


def test_a_confirmed_hit_stays_fix_later_when_the_relocated_run_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _identity(monkeypatch, "fixture-user", "fixture-host")
    command = 'python3 -c "import sys; sys.exit(1)"'
    code, output, *_rest = H.one(
        tmp_path,
        {"readme.txt": "a\n"},
        {"readme.txt": "b\n"},
        "machine-values",
        command,
        framework=True,
    )
    assert code == 0
    relocated = [
        item for item in H.read(output, "outcomes.json")["findings"]
        if item["rule"]["row"] == "architecture-maintainability.relocated-run-fails"
    ]
    assert len(relocated) == 1
    assert relocated[0]["severity"] == "blocks"
    assert all(item["rule"]["row"] != ROW for item in H.read(output, "findings.json"))
    machine = {
        "id": "rf:" + ("ab" * 16),
        "lens": "architecture-maintainability",
        "rule": {"row": ROW, "ref": "confirmed"},
        "source": {"kind": "tool", "name": "review-checks", "version": "1.0.0"},
        "language": "python",
        "consequence": None,
        "trigger": None,
        "evidence": "tool-result",
        "degraded": False,
        "consequence_jev": None,
        "unconfirmed": False,
    }
    findings = [
        {key: value for key, value in item.items() if key not in H.F.COMPUTED_FINDING_KEYS}
        for item in H.read(output, "findings.json")
    ]
    computed = H.F.compute({
        "findings": [*findings, machine],
        "measurements": [],
        "builder_records": [],
        "degraded_inputs": [],
    })
    matched = [item for item in computed["findings"] if item["id"] == machine["id"]]
    assert len(matched) == 1
    assert matched[0]["severity"] == "fix-later"
