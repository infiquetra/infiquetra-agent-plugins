"""Transcription path for the voice package: the declared relay, nothing kept.

Speech-to-text runs through the local Hermes relay, which resolves the
declared xAI profile (D2). The wire contract (KTD9), verified against the
live relay:

- The loopback session token is read from the dashboard root page —
  ``window.__HERMES_SESSION_TOKEN__`` — and held in process memory only. It
  is never written, never logged, and never placed in a command argument.
- The transcription POSTs JSON ``{"data_url": "data:audio/wav;base64,..."}``
  to ``/api/audio/transcribe?profile=<profile>`` with the
  ``X-Hermes-Session-Token`` header. The field name is ``data_url`` — the
  relay's request shape — never an invented ``audio``, ``file``, or
  ``content`` field; the data-URL header already carries the media type.
- On a 401 the token is refreshed from the root page once and the request is
  retried once — the token rotates when the relay restarts. A second 401
  fails by name. There is never a retry loop.
- The response fields ``transcript`` and ``provider`` are consumed (``ok``
  is ignored). The response provider is the authoritative resolution: a
  provider other than the expected one is a named refusal, never a silent
  substitution (R23). The one carve-out is the relay's own silence mapping:
  silence, no-speech, and hallucination-filtered audio answer
  ``{"ok": true, "transcript": "", "provider": null}`` — an empty
  transcript with no provider is refused as nothing to deliver, not as a
  substitution. Delivered content without the declared provider is still a
  substitution refusal; that boundary is intact.

Retention (D5): the audio file is deleted as soon as transcription returns —
success and failure alike, on every exit path including the exception paths
(R25). The transcript comes back in memory; this module writes no transcript
file anywhere (R26) and emits nothing about the call to anyone, anywhere
(R27).

The credential boundary is absolute: this module never reads the relay's own
credential store, never copies the relay's upstream OAuth token, never
requires an API-key setting of its own, never persists or logs the session
token, and never imports relay code. The boundary is plain HTTP built on
``urllib.request``, which keeps the provider replaceable (R31).
"""

from __future__ import annotations

import base64
import http.client
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import providers
import settings

__all__ = [
    "Transcription",
    "EXPECTED_PROVIDER",
    "TRANSCRIBE_PATH",
    "TOKEN_PAGE_TIMEOUT_SECONDS",
    "TRANSCRIBE_TIMEOUT_SECONDS",
    "transcribe",
]

#: The provider the declared profile resolves to. A different resolution in
#: the relay's response is a named refusal, never a substitution (R23).
EXPECTED_PROVIDER = "xai"

TRANSCRIBE_PATH = "/api/audio/transcribe"

#: Bounded socket deadlines. A hang is a named refusal (KTD3); the token page
#: is a loopback read, and the transcription call covers the relay's upstream
#: round trip.
TOKEN_PAGE_TIMEOUT_SECONDS = 10.0
TRANSCRIBE_TIMEOUT_SECONDS = 60.0

_TOKEN_HEADER = "X-Hermes-Session-Token"
_TOKEN_PATTERN = re.compile(
    r"window\.__HERMES_SESSION_TOKEN__\s*=\s*([\"'])([^\"']+)\1"
)


@dataclass(frozen=True)
class Transcription:
    """One consumed transcription result: the text and the resolving provider."""

    transcript: str
    provider: str


def _default_open(
    request: urllib.request.Request, *, timeout: float
) -> tuple[int, bytes]:
    """Open one request via ``urllib.request`` and answer status plus body.

    HTTP error statuses are returned, not raised, so the caller can honour
    the 401 refresh-and-retry contract; transport failures propagate for the
    caller to refuse by name.
    """
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def _fetch_token(base_url: str, *, open_url: Callable) -> str:
    """Read one session token from the dashboard root page, into memory only.

    Nothing about the token touches disk, logs, or command arguments; the
    page body itself is never repeated in a refusal, because it carries the
    token.
    """
    request = urllib.request.Request(base_url.rstrip("/") + "/", method="GET")
    status, body = open_url(request, timeout=TOKEN_PAGE_TIMEOUT_SECONDS)
    if not 200 <= status < 300:
        raise providers.ProviderRefusal(
            providers.HERMES_XAI,
            f"the relay root page answered HTTP {status} instead of serving "
            "the session token",
        )
    match = _TOKEN_PATTERN.search(body.decode("utf-8", errors="replace"))
    if match is None or not match.group(2):
        raise providers.ProviderRefusal(
            providers.HERMES_XAI,
            "the relay root page did not carry a session token",
        )
    return match.group(2)


def _post(
    base_url: str,
    profile: str,
    body: bytes,
    token: str,
    *,
    open_url: Callable,
) -> tuple[int, bytes]:
    """POST one transcription request with the in-memory session token header."""
    url = (
        base_url.rstrip("/")
        + TRANSCRIBE_PATH
        + "?profile="
        + urllib.parse.quote(profile, safe="")
    )
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            _TOKEN_HEADER: token,
        },
    )
    return open_url(request, timeout=TRANSCRIBE_TIMEOUT_SECONDS)


def transcribe(
    wav_path: Path | str, *, open_url: Callable = _default_open
) -> Transcription:
    """Transcribe one recorded wav through the declared relay, then delete it.

    The audio file is deleted as soon as transcription returns — success and
    failure alike, on every exit path including the exception paths (R25).
    The transcript is returned in memory; no transcript file is written
    anywhere (R26). The relay is the egress class ``named-remote-service``:
    audio leaves the machine, and an unavailable relay is a named refusal,
    never a substitution (R23).
    """
    path = Path(wav_path)
    try:
        return _transcribe(path, open_url=open_url)
    finally:
        path.unlink(missing_ok=True)


def _transcribe(path: Path, *, open_url: Callable) -> Transcription:
    if not path.is_file():
        raise providers.ProviderRefusal(
            providers.HERMES_XAI, f"the audio to transcribe is missing: {path}"
        )
    base_url = settings.hermes_base_url()
    profile = settings.hermes_profile()
    data_url = "data:audio/wav;base64," + base64.b64encode(
        path.read_bytes()
    ).decode("ascii")
    body = json.dumps({"data_url": data_url}).encode("utf-8")
    try:
        token = _fetch_token(base_url, open_url=open_url)
        status, payload = _post(base_url, profile, body, token, open_url=open_url)
        if status == 401:
            # Exactly one refresh and one retry: the token rotates when the
            # relay restarts. A loop is never a recovery.
            token = _fetch_token(base_url, open_url=open_url)
            status, payload = _post(
                base_url, profile, body, token, open_url=open_url
            )
    except (http.client.HTTPException, OSError) as exc:
        raise providers.ProviderRefusal(
            providers.HERMES_XAI,
            f"the relay is unreachable or dropped the connection: "
            f"{type(exc).__name__}",
        ) from exc
    if status == 401:
        raise providers.ProviderRefusal(
            providers.HERMES_XAI,
            "the relay rejected the session token again after one refresh "
            "and one retry; voice never retries in a loop",
        )
    if not 200 <= status < 300:
        raise providers.ProviderRefusal(
            providers.HERMES_XAI, f"the relay answered HTTP {status}"
        )
    try:
        result = json.loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise providers.ProviderRefusal(
            providers.HERMES_XAI, "the relay answered something that is not JSON"
        ) from exc
    if not isinstance(result, dict):
        raise providers.ProviderRefusal(
            providers.HERMES_XAI, "the relay answer is not a JSON object"
        )
    transcript = result.get("transcript")
    if not isinstance(transcript, str):
        raise providers.ProviderRefusal(
            providers.HERMES_XAI, "the relay answer carries no transcript"
        )
    provider = result.get("provider")
    if provider != EXPECTED_PROVIDER:
        if provider is None and not transcript.strip():
            # The relay maps silence, no-speech, and hallucination-filtered
            # audio to an empty transcript with no provider. That is nothing
            # to deliver — not a substitution for the declared provider.
            raise providers.ProviderRefusal(
                providers.HERMES_XAI,
                "the relay delivered an empty transcript with no provider: "
                "silence — there is nothing to deliver",
            )
        raise providers.ProviderRefusal(
            providers.HERMES_XAI,
            f"the relay resolved {provider!r}, not the expected "
            f"{EXPECTED_PROVIDER!r}; nothing substitutes for the declared "
            "provider",
        )
    # The response "ok" field is deliberately ignored: the transcript and the
    # provider are the consumed contract.
    return Transcription(transcript=transcript, provider=provider)
