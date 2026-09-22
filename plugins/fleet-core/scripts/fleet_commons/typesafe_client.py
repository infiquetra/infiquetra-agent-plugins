"""Client for the TypeSafe System One evaluation endpoint (plan U2 + U3).

One calling interface, two transports.  The official ``typesafe-sdk`` package is
used where it can be imported; a dependency-free ``urllib.request`` transport
serves hooks and scripts that run outside this project's environment.  Both
produce the same :class:`AskResult`, so a caller cannot tell them apart.

Three properties this module exists to guarantee:

* **The key never leaks.**  It is read through the injected environment reader at
  request-build time and placed only in the ``Authorization`` header.  It is not
  a field of any result, is never logged, and is never interpolated into an
  exception message.
* **State is redacted before any transport sees it.**  ``prepare_state`` is the
  only way to build the payload a transport accepts, and a transport refuses
  state that does not carry its marker.  The data rule is a mechanism, not a
  convention (``plugins/fleet-core/references/typesafe.md``).
* **Failure is never mistaken for success.**  Every outcome maps onto the closed
  vocabulary ``ok`` / ``error`` / ``timeout`` / ``malformed``, mirroring
  ``plugins/saga/scripts/engine_bridge_http.py``.

Loaded the house way::

    typesafe_client = fleet_commons_shim.load("typesafe_client")
"""

from __future__ import annotations

import json
import math
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any


def _load_sibling(name: str):
    """Load ``<this file's directory>/<name>.py``.

    Portable stand-in for ``fleet_commons_shim.load``. The shim's resolution
    ladder is specific to a Claude Code plugin install. This catalog bundles
    modules at build time, and a module is always read from the directory that
    holds this file, so the same source works in ``fleet_commons/`` and in any
    generated ``_bundled/`` copy.
    """
    import importlib.util
    import sys
    from pathlib import Path

    sibling_dir = Path(__file__).resolve().parent
    cache_key = f"_fleet_commons_{name}@{sibling_dir}"
    cached = sys.modules.get(cache_key)
    if cached is not None:
        return cached
    module_path = sibling_dir / f"{name}.py"
    if not module_path.is_file():
        raise RuntimeError(f"fleet-commons: module {name!r} not found at {module_path}")
    spec = importlib.util.spec_from_file_location(cache_key, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib internal failure
        raise RuntimeError(f"fleet-commons: importlib could not load {module_path}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[cache_key] = loaded
    try:
        spec.loader.exec_module(loaded)
    except BaseException:
        sys.modules.pop(cache_key, None)
        raise
    return loaded

_retry_backoff = _load_sibling("retry_backoff")

retry_with_backoff = _retry_backoff.retry_with_backoff
parse_retry_after = _retry_backoff.parse_retry_after

# --------------------------------------------------------------------------- #
# The closed status vocabulary.  Mirrors engine_bridge_http.py:47-50 so a
# reviewer who knows one knows the other.  An HTTP error, a timeout, or an
# unparseable body NEVER reports ok.
# --------------------------------------------------------------------------- #
STATUS_OK = "ok"
STATUS_ERROR = "error"
STATUS_TIMEOUT = "timeout"
STATUS_MALFORMED = "malformed"

DEFAULT_BASE_URL = "https://api.typesafe.ai"
SYSTEM_ONE_PATH = "/v1/systemone"
KEY_ENV = "TYPESAFE_API_KEY"
BASE_URL_ENV = "TYPESAFE_BASE_URL"
TRANSPORT_ENV = "INFIQUETRA_TYPESAFE_TRANSPORT"
DEFAULT_MODEL = "jev-latest"

TRANSPORT_SDK = "sdk"
TRANSPORT_URLLIB = "urllib"
TRANSPORTS = (TRANSPORT_SDK, TRANSPORT_URLLIB)

# Retry only these.  400/401/422 are the caller's fault and retrying them just
# burns quota; 529 is the vendor's documented overload signal.
RETRYABLE_STATUSES = frozenset({429, 529})
MAX_ATTEMPTS = 3
TOTAL_DEADLINE_SECONDS = 30.0
REQUEST_TIMEOUT_SECONDS = 60.0

# Documented budgets: 64k tokens for state plus every question, 32k for state
# plus the single longest question.
TOTAL_TOKEN_BUDGET = 64_000
STATE_TOKEN_BUDGET = 32_000

# Deliberately conservative: three characters per token over-counts for ordinary
# English, so the ladder cuts earlier than strictly necessary.  A named constant
# because R9's determinism promise is only meaningful if the divisor is written
# down rather than chosen at the keyboard.
CHARS_PER_TOKEN = 3

REDACTION_PLACEHOLDER = "[REDACTED]"  # noqa: S105 - a placeholder, not a credential
ELISION_MARKER = "[... elided ...]"

# The token prepare_state stamps onto its output.  It is a private module-level
# object, not a string constant: a string default on the dataclass field is
# forgeable -- anyone can construct PreparedRequest(state=<raw secret>) and the
# check passes -- which made the "no path skips redaction" claim false. Identity
# against this object cannot be reproduced from outside the module.
_PREPARED_TOKEN = object()

# Minimum run length and Shannon entropy for the high-entropy rule.  Without a
# stated threshold this rule either misses secrets or shreds ordinary diffs:
# lock files are dense with long base64 integrity hashes, so the hash-form guard
# below keeps them intact.
ENTROPY_MIN_RUN = 40
ENTROPY_MIN_BITS = 4.0

# nosec B105 - a regex alternation naming credential words, not a credential
_SECRET_WORD = r"(?:api[_-]?key|secret|token|password|passwd|access[_-]?key)"  # nosec B105

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"),
    # A named assignment.  The optional quote before the separator matters: a
    # JSON-shaped line ("api_key": "...") is the commonest way a credential
    # appears inside a diff or a pasted config, and requiring the separator to
    # follow the word directly misses every one of them.
    # The leading boundary and the bounded repeat are load-bearing, not style:
    # an unanchored `[A-Z0-9_-]*` prefix backtracks over the whole string at
    # every position, which turned a 500 kB state into a quadratic scan that
    # never returned.
    re.compile(
        rf"(?i)\b[A-Z0-9_\-]{{0,32}}{_SECRET_WORD}[A-Z0-9_\-]{{0,32}}"
        rf"['\"]?\s*[=:]\s*['\"]?[^\s'\",;}}]{{6,}}"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    # Credentials embedded in a connection string or a basic-auth URL.
    re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:[^/\s@]+@"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}\b"),
    # A JSON Web Token: three base64url segments separated by dots.
    re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"),
)

# A run that is itself a content hash -- a lock-file integrity value, a commit
# identifier -- is high-entropy and entirely ordinary.  The exemption is tested
# against the CANDIDATE RUN, never the surrounding line: a line-wide test means
# one commit identifier anywhere on a line switches redaction off for every
# other token on it, which is exactly what a diff or a changelog entry looks
# like.  The word "integrity" is not evidence about the run beside it, so it is
# not part of this test at all.
_HASH_RUN = re.compile(r"(?i)\A(?:(?:sha\d{3}|md5|sha)[-:])?[0-9a-f]{32,}=*\Z")
# `/` is deliberately absent from the alphabet: a long repository path is
# high-entropy by this measure, and the data rule explicitly permits sending
# file paths, so including it shredded exactly the content the tool is for.
_ENTROPY_RUN = re.compile(rf"[A-Za-z0-9+=_\-]{{{ENTROPY_MIN_RUN},}}")

# A mapping key whose value is a credential by virtue of what the key is called.
# Structured state has no "key=value" text for the patterns above to match.
# Anchored to whole segments so `input_tokens` and `token_count` -- this API's
# own usage vocabulary -- are not mistaken for credentials.
_SECRET_KEY_NAME = re.compile(
    r"(?i)\A(?:[a-z0-9]+[_\-])*"
    r"(?:api[_-]?key|secret|token|password|passwd|credential|private[_-]?key|authorization)"
    r"(?:[_\-][a-z0-9]+)*\Z"
)
# Keys that match the shape above but name a count or a tool, not a credential.
_SECRET_KEY_EXEMPT = re.compile(r"(?i)\A[a-z0-9_\-]*token(?:s|_count|izer|ize|izing)\Z")


class TypeSafeClientError(RuntimeError):
    """A client-side failure whose message this repository composes.

    Vendor exceptions are re-raised as this type so no vendor-authored string --
    which may quote request details -- reaches a log or a caller unexamined.
    """


class _StatusError(Exception):
    """Carries an HTTP status through the retry helper.

    ``retry_with_backoff`` retries on a *raised* error, while the
    ``engine_bridge_http`` pattern catches and returns.  The boundary is
    explicit: transports raise this, and the mapping onto the four status
    constants happens outside the retry.
    """

    def __init__(self, status: int, note: str, retry_after: str | None = None) -> None:
        super().__init__(note)
        self.status_code = status
        self.note = note
        self.retry_after = retry_after


class _TimeoutError(Exception):
    """A transport-level timeout, distinct from an HTTP error."""


class _DeadlineError(_TimeoutError):
    """The wall-clock retry deadline elapsed.  A timeout, not a generic error."""


@dataclass(frozen=True)
class AskResult:
    """The single shape both transports return.

    A frozen dataclass rather than a dict so a typo in a field name fails at the
    call site instead of silently reading ``None``, and so the two transports
    cannot drift apart unnoticed.  It carries no field that could hold the key.
    """

    status: str
    answers: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    transport: str = ""
    truncation: tuple[str, ...] = ()
    usage: dict[str, int] = field(default_factory=dict)
    latency_ms: int = 0
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answers": self.answers,
            "model": self.model,
            "transport": self.transport,
            "truncation": list(self.truncation),
            "usage": self.usage,
            "latency_ms": self.latency_ms,
            "note": self.note,
        }


# --------------------------------------------------------------------------- #
# Redaction
# --------------------------------------------------------------------------- #


def _shannon_bits(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for char in text:
        counts[char] = counts.get(char, 0) + 1
    length = len(text)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def redact_text(text: str) -> str:
    """Replace credential-shaped and high-entropy substrings with a placeholder."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTION_PLACEHOLDER, text)

    def _maybe_redact(match: re.Match[str]) -> str:
        run = match.group(0)
        # The exemption is about THIS run, not the line it sits on.  A commit
        # identifier elsewhere on the line says nothing about whether this run
        # is a secret.
        if _HASH_RUN.match(run):
            return run
        if _shannon_bits(run) >= ENTROPY_MIN_BITS:
            return REDACTION_PLACEHOLDER
        return run

    return _ENTROPY_RUN.sub(_maybe_redact, text)


def names_a_secret(key: Any) -> bool:
    """Does this mapping key announce that its value is a credential?

    Structured state carries secrets differently from free text: there is no
    ``key=value`` for a pattern to match, just a field named ``api_key`` whose
    value is the secret itself.  The text patterns cannot see that shape, so the
    key name is checked separately.

    Matched on whole underscore- or hyphen-separated segments, and exempting the
    count and tool shapes, so this API's own ``input_tokens`` and
    ``output_tokens`` are not mistaken for credentials -- a previous result is a
    natural thing to pass back in as state.
    """
    name = str(key)
    if _SECRET_KEY_EXEMPT.match(name):
        return False
    return bool(_SECRET_KEY_NAME.match(name))


def redact(value: Any) -> Any:
    """Redact recursively, at every depth, for strings, mappings and sequences."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {
            key: (REDACTION_PLACEHOLDER if names_a_secret(key) and item else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


# --------------------------------------------------------------------------- #
# Truncation ladder
# --------------------------------------------------------------------------- #


def _estimate_tokens(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, default=str)) // CHARS_PER_TOKEN


def _longest_question_tokens(questions: Mapping[str, Any]) -> int:
    if not questions:
        return 0
    return max(_estimate_tokens(question) for question in questions.values())


def _abridge(text: str, keep: int) -> str:
    if len(text) <= keep:
        return text
    head = keep // 2
    tail = keep - head
    return f"{text[:head]}{ELISION_MARKER}{text[-tail:] if tail else ''}"


def _drop_tool_outputs(state: Any) -> Any:
    """Drop tool-output fields at every depth.

    Filtering only the top level meant the stage that exists to remove tool
    output missed it wherever it actually sits, which is nested.
    """
    if isinstance(state, Mapping):
        return {
            key: _drop_tool_outputs(value)
            for key, value in state.items()
            if "tool_output" not in str(key)
        }
    if isinstance(state, (list, tuple)):
        return [_drop_tool_outputs(item) for item in state]
    return state


def _abridge_long_strings(state: Any, keep: int) -> Any:
    if isinstance(state, str):
        return _abridge(state, keep)
    if isinstance(state, Mapping):
        return {key: _abridge_long_strings(value, keep) for key, value in state.items()}
    if isinstance(state, (list, tuple)):
        return [_abridge_long_strings(item, keep) for item in state]
    return state


COLLAPSE_MAPPING_KEYS = 50


def _collapse_collections(state: Any) -> Any:
    """Collapse lists, and mappings past a key-count threshold, to counts.

    Recursing through every mapping without ever collapsing one meant a large
    flat mapping could not be reduced at all, so the ladder refused rather than
    truncating it.
    """
    if isinstance(state, Mapping):
        if len(state) > COLLAPSE_MAPPING_KEYS:
            return f"[{len(state)} keys elided]"
        return {key: _collapse_collections(value) for key, value in state.items()}
    if isinstance(state, (list, tuple)):
        return f"[{len(state)} items elided]"
    return state


def _within_budget(state: Any, questions: Mapping[str, Any]) -> bool:
    state_tokens = _estimate_tokens(state)
    if state_tokens + _longest_question_tokens(questions) > STATE_TOKEN_BUDGET:
        return False
    return state_tokens + _estimate_tokens(questions) <= TOTAL_TOKEN_BUDGET


@dataclass(frozen=True)
class PreparedRequest:
    """Redacted, within-budget state plus the ladder stages that fired."""

    state: Any
    questions: dict[str, Any]
    truncation: tuple[str, ...]
    # Defaults to None on purpose: only prepare_state passes the real token, so
    # a hand-constructed PreparedRequest is refused by every transport.
    token: Any = None


def _prepared(state: Any, questions: dict[str, Any], stages: tuple[str, ...]) -> PreparedRequest:
    """The only construction that stamps the private token."""
    return PreparedRequest(
        state=state, questions=questions, truncation=stages, token=_PREPARED_TOKEN
    )


def prepare_state(state: Any, questions: Mapping[str, Any]) -> PreparedRequest:
    """Redact, then truncate, then hand back something a transport will accept.

    The order matters: redacting after truncation would let a secret survive in
    a segment the ladder kept.  Nothing here consults a clock, a random source,
    or the environment, so the same input prepares identically on every machine.
    """
    # Questions are redacted as well as state.  A question's free text is
    # operator-supplied -- the command-line tool takes it straight from
    # --noul/--choice/--score -- so it is exactly as capable of carrying a
    # credential as the state is, and it goes to the vendor either way.
    questions = redact(dict(questions))
    if _estimate_tokens(questions) > TOTAL_TOKEN_BUDGET:
        raise TypeSafeClientError(
            "the question set alone exceeds the request budget; the state ladder "
            "cannot rescue it -- shorten the questions"
        )

    working = redact(state)
    stages: list[str] = []

    if _within_budget(working, questions):
        return _prepared(working, questions, ())

    reduced = _drop_tool_outputs(working)
    if reduced != working:
        stages.append("drop_tool_outputs")
    working = reduced
    if _within_budget(working, questions):
        return _prepared(working, questions, tuple(stages))

    for keep in (4000, 1000, 250):
        reduced = _abridge_long_strings(working, keep)
        if reduced != working and "abridge_long_strings" not in stages:
            stages.append("abridge_long_strings")
        working = reduced
        if _within_budget(working, questions):
            return _prepared(working, questions, tuple(stages))

    reduced = _collapse_collections(working)
    if reduced != working:
        stages.append("collapse_collections")
    working = reduced
    if _within_budget(working, questions):
        return _prepared(working, questions, tuple(stages))

    raise TypeSafeClientError(
        "state remains over the request budget after every truncation stage "
        f"({', '.join(stages)}); refusing to send an oversized request"
    )


# --------------------------------------------------------------------------- #
# Transport selection
# --------------------------------------------------------------------------- #


def sdk_available() -> bool:
    try:
        import typesafe_sdk  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure means "not usable here"
        return False
    return True


def resolve_transport(
    explicit: str | None = None,
    *,
    getenv: Callable[[str], str | None] | None = None,
) -> str:
    """Pick a transport: explicit argument, then environment, then availability.

    An unrecognized or unsatisfiable override fails loudly.  The two transports
    differ in how the key is handled, so a silent fall-through would be a
    behavior change the operator cannot see.
    """
    read = getenv if getenv is not None else os.environ.get
    if explicit is not None:
        if explicit not in TRANSPORTS:
            raise TypeSafeClientError(
                f"unknown transport {explicit!r}; expected one of {', '.join(TRANSPORTS)}"
            )
        if explicit == TRANSPORT_SDK and not sdk_available():
            raise TypeSafeClientError(
                "transport 'sdk' was requested but the typesafe-sdk package is not importable"
            )
        return explicit

    override = read(TRANSPORT_ENV)
    if override:
        if override not in TRANSPORTS:
            raise TypeSafeClientError(
                f"{TRANSPORT_ENV} is set to {override!r}; expected one of {', '.join(TRANSPORTS)}"
            )
        if override == TRANSPORT_SDK and not sdk_available():
            raise TypeSafeClientError(
                f"{TRANSPORT_ENV} requests the 'sdk' transport but the typesafe-sdk "
                "package is not importable"
            )
        return override

    return TRANSPORT_SDK if sdk_available() else TRANSPORT_URLLIB


# --------------------------------------------------------------------------- #
# Request building
# --------------------------------------------------------------------------- #


def _require_prepared(prepared: Any) -> None:
    """Refuse anything prepare_state did not build.

    Called by ``build_body`` *and* by both transports.  Keeping the check only
    in ``build_body`` left two other doors open, because a transport takes a
    plain dictionary and ``ask`` is not the only way to reach one.
    """
    if getattr(prepared, "token", None) is not _PREPARED_TOKEN:
        raise TypeSafeClientError(
            "state was not prepared; call prepare_state() so redaction cannot be bypassed"
        )


def build_body(prepared: PreparedRequest, model: str) -> dict[str, Any]:
    """The request body, which is also exactly what ``--dry-run`` prints.

    No key is present here, by construction: the credential lives only in the
    header, which is why the dry run is safe to print.
    """
    _require_prepared(prepared)
    return {"state": prepared.state, "model": model, "questions": prepared.questions}


def _resolve_key(getenv: Callable[[str], str | None]) -> str:
    # SECRET BOUNDARY -- the value below is resolved once, placed only in the
    # Authorization header, and never stored on a result, a log record, or an
    # exception message.  Do not widen its reach.
    key = getenv(KEY_ENV)
    if not key:
        raise TypeSafeClientError(
            f"{KEY_ENV} is not set in the environment; no request was attempted"
        )
    return key


def _base_url(getenv: Callable[[str], str | None]) -> str:
    """Resolve the endpoint base, refusing a scheme that would expose the key.

    The base is environment-controlled, so it is not a fixed endpoint and cannot
    be treated as one: an ``http://`` override would put the bearer credential
    on the wire in cleartext.
    """
    base = (getenv(BASE_URL_ENV) or DEFAULT_BASE_URL).rstrip("/")
    parsed = urllib.parse.urlsplit(base)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https":
        return base
    if parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}:
        return base
    raise TypeSafeClientError(
        f"{BASE_URL_ENV} must use https (or http on localhost); refusing to send the "
        f"credential over {parsed.scheme or 'an unknown scheme'}"
    )


class _NoCrossHostAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Drop the Authorization header when a redirect changes host.

    Python's default redirect handler copies every header but content-length and
    content-type onto the new request, so a 302 to another host would forward
    the bearer credential there.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        if urllib.parse.urlsplit(newurl).netloc != urllib.parse.urlsplit(req.full_url).netloc:
            for name in list(new.headers):
                if name.lower() == "authorization":
                    del new.headers[name]
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def _default_urlopen(request: Any, timeout: float | None = None) -> Any:
    """The real opener, with the redirect handler above installed."""
    opener = urllib.request.build_opener(_NoCrossHostAuthRedirect)
    return opener.open(request, timeout=timeout)


# --------------------------------------------------------------------------- #
# The urllib transport
# --------------------------------------------------------------------------- #


def _urllib_call(
    body: dict[str, Any],
    *,
    prepared: Any,
    urlopen: Callable[..., Any],
    getenv: Callable[[str], str | None],
    timeout: float,
) -> dict[str, Any]:
    # The guard lives here, in the transport, not only in build_body: this is
    # the last point before the bytes leave the machine.
    _require_prepared(prepared)
    key = _resolve_key(getenv)
    payload = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - scheme validated by _base_url
        f"{_base_url(getenv)}{SYSTEM_ONE_PATH}",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        hint = None
        try:
            hint = exc.headers.get("Retry-After") if exc.headers is not None else None
        except Exception:  # noqa: BLE001 - a header bag we cannot read is simply no hint
            hint = None
        raise _StatusError(
            exc.code, f"HTTP {exc.code} from the evaluation endpoint", hint
        ) from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise _TimeoutError("the request timed out") from None
        raise _StatusError(0, "the endpoint could not be reached") from None
    except TimeoutError:
        raise _TimeoutError("the request timed out") from None

    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001 - any parse failure is a malformed body
        raise _MalformedBodyError("the response body is not valid JSON") from None
    if not isinstance(parsed, dict) or "answers" not in parsed:
        raise _MalformedBodyError("the response body has no 'answers' mapping")
    return parsed


class _MalformedBodyError(Exception):
    """A 200 whose body cannot be believed."""


# --------------------------------------------------------------------------- #
# The SDK transport
# --------------------------------------------------------------------------- #


def _sdk_call(
    body: dict[str, Any],
    *,
    prepared: Any,
    getenv: Callable[[str], str | None],
    timeout: float,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Call through the vendor package, normalized onto the raw response shape.

    The key is passed explicitly rather than letting the package read the
    environment itself, so the credential's path stays observable from here and
    the vendor's own exception text never reaches a caller unexamined.
    """
    # Refuse an unprepared body before importing the vendor package. The guard is
    # the transport's own, and an injected client factory must be reachable in a
    # tree that does not install typesafe-sdk.
    _require_prepared(prepared)
    key = _resolve_key(getenv)
    if client_factory is not None:
        factory = client_factory
    else:
        import typesafe_sdk

        factory = typesafe_sdk.TypeSafeClient
    base_url = _base_url(getenv)

    # Disable the vendor's own retry policy.  Its defaults are 2 retries over
    # {408, 429, 5xx} plus timeouts, which would nest inside this client's loop:
    # up to nine requests where MAX_ATTEMPTS promises three, 5xx retried though
    # RETRYABLE_STATUSES deliberately excludes it, and a single attempt able to
    # outlast the whole wall-clock deadline.  This client owns retry on both
    # transports or the two are not interchangeable.
    retry_kwargs: dict[str, Any] = {}
    no_retry = _sdk_no_retry_policy()
    if no_retry is not None:
        retry_kwargs["retry"] = no_retry

    try:
        client = factory(api_key=key, base_url=base_url, timeout=timeout, **retry_kwargs)
    except Exception as exc:  # noqa: BLE001 - normalized below
        raise _StatusError(
            0, f"the SDK client could not be constructed ({type(exc).__name__})"
        ) from None

    try:
        with client as session:
            response = session.system_one(body["state"], body["questions"], model=body["model"])
    except Exception as exc:  # noqa: BLE001 - normalized onto our vocabulary below
        raise _from_sdk_exception(exc) from None

    return _normalize_sdk_response(response)


def _sdk_no_retry_policy() -> Any:
    """A vendor RetryPolicy with retries disabled, or None if unavailable."""
    try:
        import typesafe_sdk

        return typesafe_sdk.RetryPolicy(max_retries=0)
    except Exception:  # noqa: BLE001 - an older or newer SDK may not expose it
        return None


def _sdk_retry_after(exc: BaseException) -> str | None:
    """Pull a Retry-After hint off a vendor exception's response, if it has one."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
    except Exception:  # noqa: BLE001 - a header bag we cannot read is simply no hint
        return None
    return str(value) if value is not None else None


def _from_sdk_exception(exc: BaseException) -> Exception:
    """Map a vendor exception onto our own, composing our own message text."""
    name = type(exc).__name__
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    hint = _sdk_retry_after(exc)
    if "Timeout" in name:
        return _TimeoutError("the request timed out")
    if "Connection" in name:
        return _StatusError(0, "the endpoint could not be reached")
    if "ResponseValidation" in name:
        return _MalformedBodyError("the response body did not validate against the SDK schema")
    if isinstance(status, int) and status:
        return _StatusError(status, f"HTTP {status} from the evaluation endpoint", hint)
    if "RateLimit" in name:
        return _StatusError(429, "HTTP 429 from the evaluation endpoint", hint)
    if "Authentication" in name:
        return _StatusError(401, "HTTP 401 from the evaluation endpoint")
    if "UnprocessableEntity" in name:
        return _StatusError(422, "HTTP 422 from the evaluation endpoint")
    if "BadRequest" in name:
        return _StatusError(400, "HTTP 400 from the evaluation endpoint")
    return _StatusError(0, f"the SDK reported a failure ({name})")


def _normalize_sdk_response(response: Any) -> dict[str, Any]:
    """Reduce the SDK's typed response to the raw ``{answers, model, usage}`` shape.

    The package exposes per-type buckets (``response.nouls`` and friends) but
    also carries the same ``answers`` mapping the endpoint returns, so the
    normalization is a field copy rather than a reconstruction.
    """
    answers_obj = getattr(response, "answers", None)
    if answers_obj is None:
        raise _MalformedBodyError("the SDK response carries no answers")

    answers: dict[str, Any] = {}
    for key, answer in dict(answers_obj).items():
        if hasattr(answer, "model_dump"):
            answers[key] = answer.model_dump()
        elif isinstance(answer, Mapping):
            answers[key] = dict(answer)
        else:  # pragma: no cover - defensive
            answers[key] = answer

    usage_obj = getattr(response, "usage", None)
    usage: dict[str, int] = {}
    if usage_obj is not None:
        if hasattr(usage_obj, "model_dump"):
            usage = {k: v for k, v in usage_obj.model_dump().items() if isinstance(v, int)}
        elif isinstance(usage_obj, Mapping):
            usage = {k: v for k, v in usage_obj.items() if isinstance(v, int)}

    return {
        "answers": answers,
        "model": getattr(response, "model", "") or "",
        "usage": usage,
    }


# --------------------------------------------------------------------------- #
# The public entry point
# --------------------------------------------------------------------------- #


def _load_log_module() -> Any:
    """Load the verdict-log module from this file's directory."""
    return _load_sibling("jev_log")


def _is_retryable(exc: BaseException) -> bool:
    # The helper's default predicate covers 429 only; 529 is the vendor's
    # overload signal and must be named explicitly or it falls straight through.
    return isinstance(exc, _StatusError) and exc.status_code in RETRYABLE_STATUSES


def _retry_after_of(exc: BaseException) -> float | str | None:
    return getattr(exc, "retry_after", None)


def ask(
    state: Any,
    questions: Mapping[str, Any],
    *,
    model: str = DEFAULT_MODEL,
    transport: str | None = None,
    urlopen: Callable[..., Any] = _default_urlopen,
    getenv: Callable[[str], str | None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
    max_attempts: int = MAX_ATTEMPTS,
    total_deadline: float = TOTAL_DEADLINE_SECONDS,
    sdk_client_factory: Callable[..., Any] | None = None,
    cache_dir: Any = None,
) -> AskResult:
    """Ask the model a set of typed questions about ``state``.

    ``urlopen`` / ``getenv`` / ``clock`` / ``sleep`` are injection seams: tests
    pass fakes so no live network or real environment is touched.  ``getenv``
    defaults to ``os.environ.get``, bound at call time so the seam stays honest
    for tests that monkeypatch the environment.
    """
    read = getenv if getenv is not None else os.environ.get

    try:
        chosen = resolve_transport(transport, getenv=read)
        prepared = prepare_state(state, questions)
        body = build_body(prepared, model)
    except TypeSafeClientError as exc:
        return AskResult(status=STATUS_ERROR, transport=transport or "", note=str(exc))

    # The cache, when the caller asks for one.  Keyed on the REQUESTED alias,
    # because the resolved version only arrives with the response while a lookup
    # necessarily happens before the call.  Loaded lazily so the import graph
    # stays clean for callers that do not cache.
    store = _load_log_module() if cache_dir is not None else None
    key = None
    if store is not None:
        key = store.cache_key(prepared.state, prepared.questions, model)
        hit = store.cache_lookup(key, directory=cache_dir)
        if hit is not None:
            cached = dict(hit)
            cached["transport"] = "cache"
            return AskResult(
                status=str(cached.get("status", STATUS_OK)),
                answers=dict(cached.get("answers") or {}),
                model=str(cached.get("model") or ""),
                transport="cache",
                truncation=prepared.truncation,
                usage=dict(cached.get("usage") or {}),
                latency_ms=0,
            )

    started = clock()
    deadline = started + total_deadline

    def _attempt() -> dict[str, Any]:
        remaining = deadline - clock()
        if remaining <= 0:
            raise _DeadlineError("the total retry deadline elapsed")
        # Bound the single request by whatever is left of the deadline, not by
        # the standalone request timeout: a per-request timeout larger than the
        # deadline means one hanging attempt sails straight past it.
        attempt_timeout = min(timeout, remaining)
        if chosen == TRANSPORT_SDK:
            return _sdk_call(
                body,
                prepared=prepared,
                getenv=read,
                timeout=attempt_timeout,
                client_factory=sdk_client_factory,
            )
        return _urllib_call(
            body, prepared=prepared, urlopen=urlopen, getenv=read, timeout=attempt_timeout
        )

    def _finish(status: str, note: str) -> AskResult:
        return AskResult(
            status=status,
            transport=chosen,
            truncation=prepared.truncation,
            latency_ms=int((clock() - started) * 1000),
            note=note,
        )

    try:
        parsed = retry_with_backoff(
            _attempt,
            max_attempts=max_attempts,
            is_retryable=_is_retryable,
            retry_after=_retry_after_of,
            sleep=sleep,
        )
    except _TimeoutError as exc:
        return _finish(STATUS_TIMEOUT, str(exc))
    except _MalformedBodyError as exc:
        return _finish(STATUS_MALFORMED, str(exc))
    except _StatusError as exc:
        return _finish(STATUS_ERROR, exc.note)
    except TypeSafeClientError as exc:
        return _finish(STATUS_ERROR, str(exc))
    except Exception as exc:  # noqa: BLE001 - never leak an unexamined vendor string
        return _finish(STATUS_ERROR, f"the request failed ({type(exc).__name__})")

    answers = parsed.get("answers")
    if not isinstance(answers, dict):
        return _finish(STATUS_MALFORMED, "the response body has no 'answers' mapping")

    resolved = str(parsed.get("model") or "")
    result = AskResult(
        status=STATUS_OK,
        answers=answers,
        model=resolved,
        transport=chosen,
        truncation=prepared.truncation,
        usage=dict(parsed.get("usage") or {}),
        latency_ms=int((clock() - started) * 1000),
    )

    if store is not None and key is not None:
        # This is the moment the alias's resolution becomes knowable.  If it
        # moved since the pin, every answer cached under the alias was produced
        # by a different model: drop the bucket before storing the new one.
        pinned = store.read_pins(cache_dir).get(model)
        if pinned is not None and resolved and pinned != resolved:
            store.invalidate_alias(model, cache_dir)
        store.cache_store(key, result.to_dict(), resolved_model=resolved, directory=cache_dir)

    return result


def answer_confidence(answer: Mapping[str, Any]) -> float | None:
    """The confidence to band an answer by, or ``None`` when there is none.

    A yes/no answer carries a probability and no confidence field, verified
    against the live endpoint, so its distance from 0.5 stands in.  Choice and
    score answers report their own confidence.
    """
    kind = answer.get("type")
    if kind == "noul":
        probability = answer.get("noul")
        if isinstance(probability, (int, float)):
            return abs(float(probability) - 0.5) * 2.0
        return None
    value = answer.get("confidence")
    return float(value) if isinstance(value, (int, float)) else None


def answer_value(answer: Mapping[str, Any]) -> Any:
    """The comparable value of an answer, whatever its type."""
    kind = answer.get("type")
    if kind == "noul":
        return answer.get("noul")
    if kind == "choice":
        return answer.get("choice")
    if kind == "score":
        return answer.get("score")
    return None


__all__: Sequence[str] = (
    "AskResult",
    "PreparedRequest",
    "TypeSafeClientError",
    "STATUS_ERROR",
    "STATUS_MALFORMED",
    "STATUS_OK",
    "STATUS_TIMEOUT",
    "answer_confidence",
    "answer_value",
    "ask",
    "build_body",
    "prepare_state",
    "redact",
    "names_a_secret",
    "redact_text",
    "resolve_transport",
    "sdk_available",
)
