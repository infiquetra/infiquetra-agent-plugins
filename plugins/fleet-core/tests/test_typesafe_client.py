"""Tests for the TypeSafe client, its transports, redaction and truncation.

No test here touches the network.  The ``urllib`` transport is driven through a
fake ``urlopen`` in the shape ``tests/test_engine_bridge_http.py`` established;
the SDK transport is driven through a fake client factory.  The key is always a
recognizable sentinel so every failure path can assert it did not leak.
"""

from __future__ import annotations

import email.message
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = REPO_ROOT / "plugins/fleet-core/scripts/fleet_commons/typesafe_client.py"

SENTINEL_KEY = "SENTINEL-do-not-leak-4f9a2b7c"  # noqa: S105 - a test fixture, not a credential


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("typesafe_client_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tc = _load()

QUESTIONS = {
    "greeting": {"type": "noul", "instructions": "Is `x` a greeting?"},
    "tone": {
        "type": "choice",
        "instructions": "Tone of `x`?",
        "criteria": {"warm": "friendly", "cold": "distant"},
    },
}

RECORDED_BODY = {
    "answers": {
        "greeting": {"type": "noul", "noul": 0.97},
        "tone": {
            "type": "choice",
            "choice": "warm",
            "confidence": 0.99,
            "probabilities": {"warm": 1.0, "cold": 0.0},
        },
        "risk": {"type": "score", "score": 1.2, "confidence": 0.8},
    },
    "model": "jev-1.13.0",
    "usage": {"input_tokens": 331, "output_tokens": 49},
}


def _env(**overrides: str | None):
    values: dict[str, str | None] = {tc.KEY_ENV: SENTINEL_KEY}
    values.update(overrides)
    return values.get


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _capturing_urlopen(body: dict[str, Any] | bytes = RECORDED_BODY, calls: list | None = None):
    """A fake ``urlopen`` that records the request and returns a recorded body."""
    payload = body if isinstance(body, bytes) else json.dumps(body).encode()

    def _urlopen(request, timeout=None):  # noqa: ANN001
        if calls is not None:
            calls.append(
                {
                    "url": request.full_url,
                    "headers": dict(request.headers),
                    "method": request.get_method(),
                    "data": request.data,
                    "timeout": timeout,
                }
            )
        return _FakeResponse(payload)

    return _urlopen


def _raising_urlopen(*errors: BaseException, then: dict[str, Any] | None = None):
    """Raise each error in turn, then return ``then`` (or keep raising the last)."""
    queue = list(errors)

    def _urlopen(request, timeout=None):  # noqa: ANN001
        if queue:
            raise queue.pop(0)
        if then is None:
            raise errors[-1]
        return _FakeResponse(json.dumps(then).encode())

    return _urlopen


def _http_error(status: int, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = email.message.Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://api.typesafe.ai/v1/systemone", status, "err", headers, None
    )


def _recording_sleep() -> tuple[list[float], Any]:
    delays: list[float] = []
    return delays, delays.append


def _ask(**kwargs: Any):
    defaults: dict[str, Any] = {
        "transport": "urllib",
        "getenv": _env(),
        "urlopen": _capturing_urlopen(),
        "sleep": lambda _seconds: None,
    }
    defaults.update(kwargs)
    return tc.ask({"x": "hello"}, QUESTIONS, **defaults)


# --------------------------------------------------------------------------- #
# Happy paths and request shape
# --------------------------------------------------------------------------- #


def test_urllib_transport_returns_ok_with_the_resolved_model() -> None:
    result = _ask()
    assert result.status == tc.STATUS_OK
    assert result.transport == "urllib"
    # The alias was requested; the version that answered is what is recorded.
    assert result.model == "jev-1.13.0"
    assert result.answers["greeting"]["noul"] == 0.97
    assert result.usage == {"input_tokens": 331, "output_tokens": 49}


def test_request_shape_and_endpoint() -> None:
    calls: list[dict[str, Any]] = []
    _ask(urlopen=_capturing_urlopen(calls=calls))
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://api.typesafe.ai/v1/systemone"
    assert call["method"] == "POST"
    body = json.loads(call["data"])
    assert set(body) == {"state", "model", "questions"}
    assert isinstance(body["questions"], dict)
    assert set(body["questions"]) == {"greeting", "tone"}
    assert body["model"] == "jev-latest"


def test_the_key_appears_only_in_the_authorization_header() -> None:
    calls: list[dict[str, Any]] = []
    _ask(urlopen=_capturing_urlopen(calls=calls))
    headers = calls[0]["headers"]
    authorization = headers.get("Authorization") or headers.get("authorization")
    assert authorization == f"Bearer {SENTINEL_KEY}"
    assert SENTINEL_KEY not in calls[0]["data"].decode()
    assert SENTINEL_KEY not in calls[0]["url"]


def test_answer_shapes_all_three_types_parse() -> None:
    result = _ask()
    assert tc.answer_value(result.answers["greeting"]) == 0.97
    assert tc.answer_value(result.answers["tone"]) == "warm"
    assert tc.answer_value(result.answers["risk"]) == 1.2
    # A yes/no answer carries no confidence field; its distance from 0.5 stands in.
    assert "confidence" not in result.answers["greeting"]
    assert tc.answer_confidence(result.answers["greeting"]) == pytest.approx(0.94)
    assert tc.answer_confidence(result.answers["tone"]) == 0.99


def test_called_twice_sends_byte_identical_bodies() -> None:
    calls: list[dict[str, Any]] = []
    urlopen = _capturing_urlopen(calls=calls)
    _ask(urlopen=urlopen)
    _ask(urlopen=urlopen)
    assert len(calls) == 2
    assert calls[0]["data"] == calls[1]["data"]


# --------------------------------------------------------------------------- #
# The SDK transport, and transport equivalence
# --------------------------------------------------------------------------- #


class _FakeSdkAnswer:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, Any]:
        return dict(self._payload)


class _FakeSdkUsage:
    def __init__(self, payload: dict[str, int]) -> None:
        self._payload = payload

    def model_dump(self) -> dict[str, int]:
        return dict(self._payload)


class _FakeSdkResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.answers = {k: _FakeSdkAnswer(v) for k, v in body["answers"].items()}
        self.model = body["model"]
        self.usage = _FakeSdkUsage(body["usage"])


class _FakeSdkClient:
    def __init__(self, calls: list[dict[str, Any]], body: dict[str, Any], **kwargs: Any) -> None:
        self._calls = calls
        self._body = body
        self._kwargs = kwargs

    def __enter__(self) -> _FakeSdkClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def system_one(self, state, questions, *, model=None):  # noqa: ANN001
        self._calls.append(
            {"state": state, "questions": questions, "model": model, "init": self._kwargs}
        )
        return _FakeSdkResponse(self._body)


def _sdk_factory(calls: list[dict[str, Any]], body: dict[str, Any] = RECORDED_BODY):
    def _factory(**kwargs: Any) -> _FakeSdkClient:
        return _FakeSdkClient(calls, body, **kwargs)

    return _factory


# --------------------------------------------------------------------------- #
# Error paths
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("status", [400, 401, 422])
def test_client_errors_are_not_retried(status: int) -> None:
    calls: list[int] = []

    def _urlopen(request, timeout=None):  # noqa: ANN001
        calls.append(1)
        raise _http_error(status)

    result = _ask(urlopen=_urlopen)
    assert result.status == tc.STATUS_ERROR
    assert str(status) in result.note
    assert len(calls) == 1, "a 4xx must not be retried"


@pytest.mark.parametrize("status", [429, 529])
def test_rate_limit_and_overload_are_retried_then_succeed(status: int) -> None:
    """529 is mandatory here: the shared helper's default predicate covers 429 only."""
    delays, sleep = _recording_sleep()
    urlopen = _raising_urlopen(_http_error(status), _http_error(status), then=RECORDED_BODY)
    result = _ask(urlopen=urlopen, sleep=sleep)
    assert result.status == tc.STATUS_OK
    assert len(delays) == 2, "two failures should produce two backoff waits"
    assert delays[1] > delays[0], "backoff should grow between attempts"


def test_retry_after_header_is_honored() -> None:
    delays, sleep = _recording_sleep()
    urlopen = _raising_urlopen(_http_error(429, retry_after="2"), then=RECORDED_BODY)
    result = _ask(urlopen=urlopen, sleep=sleep)
    assert result.status == tc.STATUS_OK
    assert delays[0] >= 2.0, "a Retry-After hint of two seconds must be waited out"


def test_missing_retry_after_still_retries_on_the_plain_schedule() -> None:
    delays, sleep = _recording_sleep()
    urlopen = _raising_urlopen(_http_error(429), then=RECORDED_BODY)
    result = _ask(urlopen=urlopen, sleep=sleep)
    assert result.status == tc.STATUS_OK
    assert len(delays) == 1 and delays[0] > 0


def test_retry_exhaustion_is_bounded() -> None:
    attempts: list[int] = []

    def _urlopen(request, timeout=None):  # noqa: ANN001
        attempts.append(1)
        raise _http_error(429)

    result = _ask(urlopen=_urlopen, max_attempts=3)
    assert result.status == tc.STATUS_ERROR
    assert len(attempts) == 3, "the loop must be bounded by max_attempts"


def test_timeout_is_distinct_from_error() -> None:
    result = _ask(urlopen=_raising_urlopen(TimeoutError("slow")))
    assert result.status == tc.STATUS_TIMEOUT
    assert result.status != tc.STATUS_ERROR


def test_url_error_wrapping_a_timeout_maps_to_timeout() -> None:
    result = _ask(urlopen=_raising_urlopen(urllib.error.URLError(TimeoutError())))
    assert result.status == tc.STATUS_TIMEOUT


def test_unreachable_endpoint_is_an_error() -> None:
    result = _ask(urlopen=_raising_urlopen(urllib.error.URLError("no route")))
    assert result.status == tc.STATUS_ERROR


@pytest.mark.parametrize(
    "payload", [b"this is not json", json.dumps({"model": "jev-1.13.0"}).encode()]
)
def test_malformed_bodies_never_report_ok(payload: bytes) -> None:
    result = _ask(urlopen=_capturing_urlopen(body=payload))
    assert result.status == tc.STATUS_MALFORMED
    assert result.status != tc.STATUS_OK


def test_missing_key_reports_by_name_and_makes_no_call() -> None:
    calls: list[int] = []

    def _urlopen(request, timeout=None):  # noqa: ANN001
        calls.append(1)
        return _FakeResponse(b"{}")

    result = _ask(getenv=lambda _name: None, urlopen=_urlopen)
    assert result.status == tc.STATUS_ERROR
    assert tc.KEY_ENV in result.note
    assert calls == [], "no request may be attempted without a key"


def test_no_failure_path_leaks_the_key() -> None:
    """The containment sweep, across every failure this module can produce."""
    cases = [
        _raising_urlopen(_http_error(400)),
        _raising_urlopen(_http_error(429)),
        _raising_urlopen(_http_error(529)),
        _raising_urlopen(TimeoutError()),
        _raising_urlopen(urllib.error.URLError("no route")),
        _capturing_urlopen(body=b"not json"),
    ]
    for urlopen in cases:
        result = _ask(urlopen=urlopen, max_attempts=2)
        rendered = json.dumps(result.to_dict(), default=str)
        assert SENTINEL_KEY not in rendered
        assert SENTINEL_KEY not in repr(result)


# --------------------------------------------------------------------------- #
# Transport selection
# --------------------------------------------------------------------------- #


def test_transport_selection_prefers_the_sdk_when_available(monkeypatch) -> None:
    monkeypatch.setattr(tc, "sdk_available", lambda: True)
    assert tc.resolve_transport(getenv=lambda _n: None) == "sdk"


def test_transport_selection_falls_back_to_urllib_without_the_sdk(monkeypatch) -> None:
    monkeypatch.setattr(tc, "sdk_available", lambda: False)
    assert tc.resolve_transport(getenv=lambda _n: None) == "urllib"


def test_environment_override_selects_urllib(monkeypatch) -> None:
    monkeypatch.setattr(tc, "sdk_available", lambda: True)
    assert tc.resolve_transport(getenv=_env(**{tc.TRANSPORT_ENV: "urllib"})) == "urllib"


def test_unrecognized_override_fails_loudly() -> None:
    with pytest.raises(tc.TypeSafeClientError, match=tc.TRANSPORT_ENV):
        tc.resolve_transport(getenv=_env(**{tc.TRANSPORT_ENV: "grpc"}))


def test_unsatisfiable_sdk_override_fails_loudly(monkeypatch) -> None:
    """A silent substitution would change key handling invisibly."""
    monkeypatch.setattr(tc, "sdk_available", lambda: False)
    with pytest.raises(tc.TypeSafeClientError, match="not importable"):
        tc.resolve_transport(getenv=_env(**{tc.TRANSPORT_ENV: "sdk"}))


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #


def test_redacts_credential_shapes() -> None:
    text = (
        "Authorization: Bearer abcdefghijklmnop\n"
        "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIKEXAMPLEKEY\n"
        "token: ghp_0123456789abcdefghijklmnopqrstuvwx\n"
    )
    redacted = tc.redact_text(text)
    assert "abcdefghijklmnop" not in redacted
    assert "wJalrXUtnFEMIKEXAMPLEKEY" not in redacted
    assert "ghp_0123456789abcdefghijklmnopqrstuvwx" not in redacted
    assert tc.REDACTION_PLACEHOLDER in redacted


def test_redacts_a_private_key_block() -> None:
    # Two spaces after BEGIN. The repository credential scan matches a
    # single-spaced PEM header; the client's redactor matches both. The
    # fixture has to be one the scan allows and the redactor still catches.
    block = "-----BEGIN  PRIVATE KEY-----\nMIIabc123\n-----END  PRIVATE KEY-----"
    assert "MIIabc123" not in tc.redact_text(block)


def test_redacts_at_every_depth() -> None:
    state = {
        "outer": {"inner": {"api_key": "supersecretvalue123"}},
        "items": [{"token": "anothersecretvalue456"}],
    }
    redacted = json.dumps(tc.redact(state))
    assert "supersecretvalue123" not in redacted
    assert "anothersecretvalue456" not in redacted


def test_ordinary_prose_and_a_diff_pass_through_untouched() -> None:
    prose = "The endpoint returns 500 because the role cannot write to the table."
    diff = "@@ -1,3 +1,4 @@\n-old line\n+new line\n context\n"
    assert tc.redact_text(prose) == prose
    assert tc.redact_text(diff) == diff


SECRET_RUN = "zK9mQ2vX7pL4nR8sT1wY6bC3dF5gH0jKaEuI9oPqZ"


@pytest.mark.parametrize(
    "line",
    [
        f"the data integrity report: {SECRET_RUN}",
        f"sha256-abc: {SECRET_RUN}",
        f"rec 2044c363aabbccddeeff00112233445566778899 tok {SECRET_RUN}",
    ],
)
def test_a_hash_elsewhere_on_the_line_does_not_switch_redaction_off(line: str) -> None:
    """The exemption is about the candidate run, never the line it sits on.

    A commit identifier beside a token is what a diff or a changelog entry looks
    like, so a line-wide exemption let real secrets ride through.
    """
    assert SECRET_RUN not in tc.redact_text(line)


@pytest.mark.parametrize(
    "line",
    [
        '  "api_key": "AKIAsupersecretvalue1234567890abcd",',
        '{"token": "hunter2secretvalue"}',
        # Passwords are two characters. The repository scan requires three
        # before it treats a URL userinfo pair as a credential; the client
        # redacts any non-empty password.
        "postgres://admin:pw@db.internal:5432/app",
        "https://user:ab@example.com/path",
    ],
)
def test_quoted_and_embedded_credentials_are_redacted(line: str) -> None:
    """A JSON-shaped assignment is the commonest way a key appears in a diff."""
    redacted = tc.redact_text(line)
    assert tc.REDACTION_PLACEHOLDER in redacted
    for secret in (
        "AKIAsupersecret",
        "hunter2secretvalue",
        "admin:pw@",
        "user:ab@",
    ):
        assert secret not in redacted


def test_a_json_web_token_is_redacted() -> None:
    # Each segment is eight characters after the eyJ prefix. The repository
    # scan requires ten; the client redacts eight.
    token = "eyJabcdefgh.eyJijklmnop.qrstuvwx"
    assert token not in tc.redact_text(f"cookie: {token}")


@pytest.mark.parametrize(
    "path",
    [
        "plugins/fleet-core/scripts/fleet_commons/typesafe_client.py",
        "docs/analysis/2026-09-18-typesafe-jev-research-inputs/tier_probe.py.txt",
        "tests/test_typesafe_reference_drift.py",
    ],
)
def test_a_long_repository_path_survives_redaction(path: str) -> None:
    """The data rule explicitly permits sending file paths.

    With the path separator in the entropy alphabet a long path scored above the
    threshold and was replaced, silently destroying exactly the content the tool
    exists to reason about.
    """
    assert tc.redact_text(path) == path
    assert tc.redact_text(f"see {path} for the seam") == f"see {path} for the seam"


@pytest.mark.parametrize(
    "key", ["input_tokens", "output_tokens", "max_tokens", "token_count", "tokenizer"]
)
def test_usage_vocabulary_is_not_mistaken_for_a_credential(key: str) -> None:
    """A previous result is a natural state to pass back in."""
    assert not tc.names_a_secret(key)
    assert tc.redact({key: 331})[key] == 331


@pytest.mark.parametrize("key", ["api_key", "secret", "auth_token", "db_password", "private_key"])
def test_genuine_secret_key_names_are_still_caught(key: str) -> None:
    assert tc.names_a_secret(key)
    assert tc.redact({key: "supersecretvalue"})[key] == tc.REDACTION_PLACEHOLDER


def test_redaction_of_a_large_state_completes_promptly() -> None:
    """A guard against catastrophic backtracking in the credential patterns.

    An unanchored prefix repeat in the named-assignment pattern backtracked over
    the whole string at every position, turning a half-megabyte state into a
    scan that never returned.  The bound is generous: the point is to catch a
    quadratic blow-up, not to measure performance.
    """
    import time as _time

    payload = {"a": "q" * 500_000, "b": ["r" * 900 for _ in range(2000)]}
    started = _time.monotonic()
    tc.redact(payload)
    assert _time.monotonic() - started < 10.0


def test_redaction_is_on_the_only_path_to_a_transport() -> None:
    calls: list[dict[str, Any]] = []
    tc.ask(
        {"note": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIKEXAMPLEKEY"},
        QUESTIONS,
        transport="urllib",
        getenv=_env(),
        urlopen=_capturing_urlopen(calls=calls),
        sleep=lambda _s: None,
    )
    sent = calls[0]["data"].decode()
    assert "wJalrXUtnFEMIKEXAMPLEKEY" not in sent
    assert tc.REDACTION_PLACEHOLDER in sent


def test_build_body_refuses_unprepared_state() -> None:
    class _NotPrepared:
        state = {"x": "hello"}
        questions: dict[str, Any] = {}
        token = None

    with pytest.raises(tc.TypeSafeClientError, match="not prepared"):
        tc.build_body(_NotPrepared(), "jev-latest")


def test_the_prepared_token_cannot_be_forged_from_outside() -> None:
    """A string default on the dataclass made the whole guarantee bypassable."""
    forged = tc.PreparedRequest(
        state={"note": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIKEXAMPLEKEY"},
        questions={},
        truncation=(),
    )
    with pytest.raises(tc.TypeSafeClientError, match="not prepared"):
        tc.build_body(forged, "jev-latest")


def test_both_transports_refuse_unprepared_state_themselves() -> None:
    """The guard must live in the transports, not only in build_body.

    A transport takes a plain dictionary and ``ask`` is not the only way to
    reach one, so checking in ``build_body`` alone left two doors open.
    """
    raw_body = {"state": {"note": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIKEXAMPLEKEY"}, "model": "m"}
    forged = tc.PreparedRequest(state=raw_body["state"], questions={}, truncation=())

    calls: list[dict[str, Any]] = []
    with pytest.raises(tc.TypeSafeClientError, match="not prepared"):
        tc._urllib_call(
            raw_body,
            prepared=forged,
            urlopen=_capturing_urlopen(calls=calls),
            getenv=_env(),
            timeout=5,
        )
    assert calls == [], "the urllib transport sent bytes despite refusing the state"

    sdk_calls: list[dict[str, Any]] = []
    with pytest.raises(tc.TypeSafeClientError, match="not prepared"):
        tc._sdk_call(
            raw_body,
            prepared=forged,
            getenv=_env(),
            timeout=5,
            client_factory=_sdk_factory(sdk_calls),
        )
    assert sdk_calls == [], "the SDK transport called out despite refusing the state"


def test_a_secret_in_a_question_is_redacted_too() -> None:
    """Question text is operator-supplied and goes to the vendor like state does."""
    calls: list[dict[str, Any]] = []
    tc.ask(
        {"x": "hello"},
        {"q": {"type": "noul", "instructions": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMIKEXAMPLEKEY"}},
        transport="urllib",
        getenv=_env(),
        urlopen=_capturing_urlopen(calls=calls),
        sleep=lambda _s: None,
    )
    sent = calls[0]["data"].decode()
    assert "wJalrXUtnFEMIKEXAMPLEKEY" not in sent
    assert tc.REDACTION_PLACEHOLDER in sent


# --------------------------------------------------------------------------- #
# Truncation ladder
# --------------------------------------------------------------------------- #


def test_small_state_fires_no_ladder_stage() -> None:
    prepared = tc.prepare_state({"x": "hello"}, QUESTIONS)
    assert prepared.truncation == ()


def test_stage_one_drops_tool_outputs() -> None:
    state = {"keep": "short", "tool_output": "x" * (tc.STATE_TOKEN_BUDGET * 4)}
    prepared = tc.prepare_state(state, QUESTIONS)
    assert "drop_tool_outputs" in prepared.truncation
    assert "tool_output" not in prepared.state
    assert prepared.state["keep"] == "short"


def test_stage_two_abridges_long_strings() -> None:
    state = {"body": "y" * (tc.STATE_TOKEN_BUDGET * 4)}
    prepared = tc.prepare_state(state, QUESTIONS)
    assert "abridge_long_strings" in prepared.truncation
    assert tc.ELISION_MARKER in prepared.state["body"]


def test_stage_three_collapses_collections() -> None:
    state = {"items": ["z" * 400 for _ in range(4000)]}
    prepared = tc.prepare_state(state, QUESTIONS)
    assert "collapse_collections" in prepared.truncation


def test_truncation_is_deterministic() -> None:
    state = {"body": "y" * (tc.STATE_TOKEN_BUDGET * 4), "items": list(range(5000))}
    first = tc.prepare_state(state, QUESTIONS)
    for _ in range(25):
        again = tc.prepare_state(state, QUESTIONS)
        assert again.state == first.state
        assert again.truncation == first.truncation


@pytest.mark.parametrize("state", [{}, "", [], {"a": None}])
def test_empty_states_prepare_without_raising(state: Any) -> None:
    assert tc.prepare_state(state, QUESTIONS).state is not None


def test_empty_question_set_prepares() -> None:
    assert tc.prepare_state({"x": "hello"}, {}).truncation == ()


def test_oversized_questions_refuse_rather_than_truncate_state() -> None:
    huge = {"q": {"type": "noul", "instructions": "w" * (tc.TOTAL_TOKEN_BUDGET * 4)}}
    with pytest.raises(tc.TypeSafeClientError, match="question set"):
        tc.prepare_state({"x": "hello"}, huge)


def test_a_huge_state_terminates_within_budget() -> None:
    state = {"a": "q" * 500_000, "b": ["r" * 900 for _ in range(3000)]}
    prepared = tc.prepare_state(state, QUESTIONS)
    assert tc._within_budget(prepared.state, QUESTIONS)
