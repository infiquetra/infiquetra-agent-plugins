"""Tests for the Langfuse client: key names, key handling, redaction and the visibility rule.

No test here touches the network. Requests go to a fake ``urlopen`` and addresses come
from a fake resolver. The keys are sentinels that cannot match the ``(sk|pk)-lf-<8 hex>``
shape, and the Langfuse key shapes the redaction test needs are joined at run time, so
the tree never holds one.
"""

from __future__ import annotations

import ast
import base64
import email.message
import importlib.util
import io
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/langfuse_client.py"

PUBLIC = "pk-lf-SENTINEL-public"
SECRET = "sk-lf-SENTINEL-secret"  # noqa: S105 - a test fixture, not a credential
HOST = "https://langfuse.example.test"
PLAIN = "http://langfuse.example.test"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("langfuse_client_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lc = _load()


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a test reached the network")

    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


def _env(**values: str) -> Any:
    def getenv(name: str) -> str | None:
        return values.get(name)

    return getenv


SAGA_ENV = {
    "SAGA_LANGFUSE_PUBLIC_KEY": PUBLIC,
    "SAGA_LANGFUSE_SECRET_KEY": SECRET,
    "SAGA_LANGFUSE_HOST": HOST,
}


class _Response:
    def __init__(self, body: bytes = b"{}", status: int = 200) -> None:
        self._body = body
        self.status = status

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


class _Opener:
    def __init__(self, result: Any = None) -> None:
        self.requests: list[urllib.request.Request] = []
        self.result = result if result is not None else _Response()

    def __call__(self, request: urllib.request.Request, timeout: float | None = None) -> Any:
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _private(*_args: Any, **_kwargs: Any) -> list[Any]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 80))]


def _global(*_args: Any, **_kwargs: Any) -> list[Any]:
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))]


def _http_error(code: int, body: str = "") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        HOST + "/x", code, "error", email.message.Message(), io.BytesIO(body.encode())
    )


def _send(body: Any = None, *, kind: str = "otel-traces", visibility: Any = "private",
          env: dict[str, str] | None = None, opener: _Opener | None = None,
          resolve: Any = _private) -> tuple[Any, _Opener]:
    opener = opener or _Opener()
    prepared = lc.prepare_payload(kind, body if body is not None else {"resourceSpans": []})
    result = lc.send(
        prepared, visibility=visibility, getenv=_env(**(env or SAGA_ENV)),
        urlopen=opener, resolve=resolve,
    )
    return result, opener


def test_https_post_sends_basic_auth_header() -> None:
    result, opener = _send()
    assert result.outcome == "sent"
    [request] = opener.requests
    assert request.get_method() == "POST"
    assert request.full_url == HOST + "/api/public/otel/v1/traces"
    expected = base64.b64encode(f"{PUBLIC}:{SECRET}".encode()).decode()
    assert request.get_header("Authorization") == f"Basic {expected}"
    assert request.get_header("X-langfuse-ingestion-version") == "4"


def test_https_uses_default_certificate_check() -> None:
    opener = lc.default_opener()
    [handler] = [h for h in opener.handlers if isinstance(h, urllib.request.HTTPSHandler)]
    context = handler._context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True


def test_env_names_standard_langfuse_alone_sends_nothing() -> None:
    standard = {
        "LANGFUSE_PUBLIC_KEY": PUBLIC,
        "LANGFUSE_SECRET_KEY": SECRET,
        "LANGFUSE_HOST": HOST,
    }
    result, opener = _send(env=standard)
    assert (result.outcome, result.reason) == ("refused", "missing-keys")
    assert opener.requests == []


def test_env_names_only_saga_variables_are_read() -> None:
    asked: list[str] = []

    def getenv(name: str) -> str | None:
        asked.append(name)
        return SAGA_ENV.get(name)

    opener = _Opener()
    lc.send(lc.prepare_payload("scores", {"name": "x"}), visibility="private",
            getenv=getenv, urlopen=opener)
    assert asked and set(asked) <= set(SAGA_ENV)


def test_visibility_private_on_http_refused_naming_x3() -> None:
    for visibility in ("private", None):
        result, opener = _send(visibility=visibility, env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": PLAIN})
        assert (result.outcome, result.reason) == ("refused", "plain-http-private")
        assert "X3" in result.detail
        assert opener.requests == []


def test_visibility_unknown_value_counts_as_private() -> None:
    result, _ = _send(visibility="internal", env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": PLAIN})
    assert result.reason == "plain-http-private"


def test_visibility_private_and_unrecorded_on_https_send() -> None:
    for visibility in ("private", None):
        result, opener = _send(visibility=visibility)
        assert result.outcome == "sent"
        assert len(opener.requests) == 1


def test_visibility_public_on_http_sends() -> None:
    result, opener = _send(visibility="public", env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": PLAIN})
    assert result.outcome == "sent"
    assert opener.requests[0].full_url.startswith(PLAIN)


def test_visibility_public_on_http_to_public_address_refused() -> None:
    result, opener = _send(
        visibility="public", env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": PLAIN}, resolve=_global,
    )
    assert (result.outcome, result.reason) == ("refused", "plain-http-public-address")
    assert opener.requests == []


def test_visibility_public_on_http_to_metadata_address_refused() -> None:
    def resolving(*addresses: str) -> Any:
        return lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 80)) for a in addresses]

    for addresses in (("169.254.169.254",), ("fe80::1%en0",), ("::ffff:169.254.169.254",),
                      ("10.1.2.3", "169.254.169.254")):
        result, opener = _send(
            visibility="public", env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": PLAIN},
            resolve=resolving(*addresses),
        )
        assert (result.outcome, result.reason) == ("refused", "plain-http-public-address"), addresses
        assert opener.requests == []
    for addresses in (("127.0.0.1",), ("::1",), ("192.168.1.20", "fd00::5")):
        result, _ = _send(
            visibility="public", env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": PLAIN},
            resolve=resolving(*addresses),
        )
        assert result.outcome == "sent", addresses


def test_visibility_public_on_http_lookup_failure_refused() -> None:
    def raises(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("no such host")

    for resolver in (raises, lambda *_a, **_k: []):
        result, opener = _send(
            visibility="public", env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": PLAIN}, resolve=resolver,
        )
        assert (result.outcome, result.reason) == ("refused", "address-lookup-failed")
        assert opener.requests == []


def test_other_scheme_and_missing_host_refused() -> None:
    result, _ = _send(env={**SAGA_ENV, "SAGA_LANGFUSE_HOST": "ftp://langfuse.example.test"})
    assert result.reason == "bad-scheme"
    env = dict(SAGA_ENV)
    del env["SAGA_LANGFUSE_HOST"]
    result, _ = _send(env=env)
    assert result.reason == "missing-host"


def _leaks(text: str) -> bool:
    return any(needle in text for needle in (PUBLIC, SECRET, "langfuse.example.test",
                                             base64.b64encode(f"{PUBLIC}:{SECRET}".encode()).decode()))


def test_sentinel_key_never_shows(capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture) -> None:
    echo = f"bad key {PUBLIC} {SECRET} at {HOST}"
    cases: list[Any] = [
        _Response(),
        _http_error(401, echo),
        _http_error(500, echo),
        urllib.error.URLError(f"cannot reach {HOST}"),
        TimeoutError(f"timed out talking to {HOST}"),
        _Response(b"not json"),
        _http_error(302, echo),
    ]
    for case in cases:
        kind = "projects" if isinstance(case, _Response) and case.read() == b"not json" else "otel-traces"
        result, _ = _send(kind=kind, opener=_Opener(case))
        assert not _leaks(repr(result)), case
        assert not _leaks(str(result.detail)), case
    out = capsys.readouterr()
    assert not _leaks(out.out + out.err)
    assert not _leaks(caplog.text)
    with pytest.raises(lc.LangfuseClientError) as raised:
        lc.prepare_payload("delete-everything", {})
    assert not _leaks(str(raised.value))


def test_unprepared_payload_refused() -> None:
    opener = _Opener()
    for payload in (lc.PreparedPayload(kind="scores", body={"x": 1}), {"x": 1}):
        result = lc.send(payload, visibility="public", getenv=_env(**SAGA_ENV), urlopen=opener)
        assert (result.outcome, result.reason) == ("refused", "unprepared")
    assert opener.requests == []


def test_secret_shapes_become_redacted() -> None:
    marker = "PRIVATE" + " KEY-----"
    pem = f"-----BEGIN RSA {marker}\nMIIEow\n-----END RSA {marker}"
    originals = ["Bearer abcdefgh12345678", "hunter2hunter2", "AKIA" + "ABCDEFGHIJKLMNOP", "MIIEow"]
    body = {"statement": f"Authorization: {originals[0]} password=hunter2hunter2 {originals[2]}\n{pem}"}
    _, opener = _send(body, kind="scores")
    sent = opener.requests[0].data.decode()
    assert "[REDACTED]" in sent
    for original in originals:
        assert original not in sent


def test_langfuse_key_shapes_become_redacted(tmp_path: Path) -> None:
    hexes = "0123456789abcdef" * 2
    keys = ["sk-lf-" + hexes, "pk-lf-" + hexes, "sk-lf-" + "12345678"]
    body = {"excerpt": "\n".join(f"KEY = '{key}'" for key in keys), "keys": {"k": keys}}
    _, opener = _send(body, kind="scores")
    sent = opener.requests[0].data.decode()
    for key in keys:
        assert key not in sent
    prepared = lc.prepare_payload("scores", body)
    stored = tmp_path / "queued.json"
    stored.write_text(json.dumps(prepared.body))
    for key in keys:
        assert key not in stored.read_text()


def test_redirect_is_not_followed() -> None:
    result, opener = _send(opener=_Opener(_http_error(302)))
    assert (result.outcome, result.reason) == ("rejected", "redirect")
    assert len(opener.requests) == 1


def test_redirect_handler_refuses() -> None:
    handler = lc._NoRedirect()
    request = urllib.request.Request(HOST + "/x", data=b"{}", method="POST")
    assert handler.redirect_request(request, None, 307, "moved", {}, PLAIN + "/x") is None


def test_unreachable_and_timeout_outcomes() -> None:
    result, _ = _send(opener=_Opener(urllib.error.URLError("refused")))
    assert (result.outcome, result.reason) == ("unreachable", "unreachable")
    result, _ = _send(opener=_Opener(urllib.error.URLError(TimeoutError())))
    assert result.outcome == "timeout"
    result, _ = _send(opener=_Opener(_http_error(400)))
    assert (result.outcome, result.reason, result.status) == ("rejected", "http-400", 400)


def test_get_reads_json_with_query() -> None:
    opener = _Opener(_Response(b'{"data": [{"name": "Saga Reviews"}]}'))
    result = lc.get("metrics", {"query": {"view": "scores-boolean"}}, visibility="private",
                    getenv=_env(**SAGA_ENV), urlopen=opener)
    assert result.outcome == "sent"
    assert result.body == {"data": [{"name": "Saga Reviews"}]}
    [request] = opener.requests
    assert request.get_method() == "GET"
    assert "/api/public/v2/metrics?query=" in request.full_url
    with pytest.raises(lc.LangfuseClientError):
        lc.get("scores")


def test_no_delete_method() -> None:
    assert {method for method, _ in lc.ENDPOINTS.values()} <= {"GET", "POST"}
    source = MODULE_PATH.read_text(encoding="utf-8")
    for verb in ("DELETE", "PUT", "PATCH"):
        assert f'"{verb}"' not in source
    opener = _Opener()
    with pytest.raises(ValueError):
        lc.prepare_payload("dataset-delete", {})
    assert opener.requests == []


def test_stdlib_only() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported: set[str] = set()
    siblings: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_load_sibling":
            siblings.add(ast.literal_eval(node.args[0]))
    assert siblings == {"typesafe_client"}
    assert imported <= set(sys.stdlib_module_names)
