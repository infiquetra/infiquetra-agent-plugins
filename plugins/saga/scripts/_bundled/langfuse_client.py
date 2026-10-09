# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.33.2
# source-commit: authored
# source-path: scripts/fleet_commons/langfuse_client.py
# source-sha256: 473a108a5ad1aec3834f11e04eeffdc2888f58ce6f442a1d1eb894dfdb9e0981
# output-sha256: 473a108a5ad1aec3834f11e04eeffdc2888f58ce6f442a1d1eb894dfdb9e0981
# --- end generated bundle stamp ---
"""Client for saga's own Langfuse project (issue 166, card C15).

Standard library only.  It prepares a payload, refuses to send one that skipped
preparation, applies the visibility rule, and sends to one of a fixed list of
endpoints.  It never deletes anything: the endpoint list holds only ``GET`` and
``POST`` routes, and a caller cannot name a path.

Four properties this module exists to guarantee, mirroring ``typesafe_client``:

* **Saga's keys, never the tracing plugin's.**  Only ``SAGA_LANGFUSE_PUBLIC_KEY``,
  ``SAGA_LANGFUSE_SECRET_KEY`` and ``SAGA_LANGFUSE_HOST`` are read.  The standard
  ``LANGFUSE_*`` names belong to another project, so with only those set nothing
  is sent.
* **The key pair never leaks.**  It is read when the request is built and placed
  only in the ``Authorization`` header.  No result, message or exception carries
  a key or the host address.
* **Redaction is on the only path out.**  ``prepare_payload`` removes Langfuse key
  shapes, then runs TypeSafe's redaction, then stamps its output; ``send`` refuses
  anything without the stamp.
* **Private code never goes in clear.**  A private repository, or one whose
  visibility is not recorded, sends only over ``https``.  A public one may use
  plain ``http`` only to a host whose every address is loopback or private.

The full rule is ``plugins/fleet-core/references/langfuse.md``.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


def _load_sibling(name: str):
    """Load ``<this file's directory>/<name>.py``, as ``typesafe_client`` does."""
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


_typesafe = _load_sibling("typesafe_client")

#: TypeSafe's redaction, reused so the two clients share one pattern list.
redact = _typesafe.redact
redact_text = _typesafe.redact_text
REDACTION_PLACEHOLDER = _typesafe.REDACTION_PLACEHOLDER

PUBLIC_KEY_ENV = "SAGA_LANGFUSE_PUBLIC_KEY"
SECRET_KEY_ENV = "SAGA_LANGFUSE_SECRET_KEY"  # noqa: S105 - a variable name, not a credential
HOST_ENV = "SAGA_LANGFUSE_HOST"

#: Every route this client can reach. No DELETE, PUT or PATCH exists here.
ENDPOINTS: dict[str, tuple[str, str]] = {
    "otel-traces": ("POST", "/api/public/otel/v1/traces"),
    "scores": ("POST", "/api/public/scores"),
    "datasets": ("POST", "/api/public/v2/datasets"),
    "dataset-items": ("POST", "/api/public/dataset-items"),
    "projects": ("GET", "/api/public/projects"),
    "metrics": ("GET", "/api/public/v2/metrics"),
    "traces": ("GET", "/api/public/traces"),
    "scores-list": ("GET", "/api/public/v2/scores"),
}

SENT = "sent"
REFUSED = "refused"
UNREACHABLE = "unreachable"
TIMEOUT = "timeout"
REJECTED = "rejected"
OUTCOMES = (SENT, REFUSED, UNREACHABLE, TIMEOUT, REJECTED)

VISIBILITIES = ("public", "private")
REQUEST_TIMEOUT_SECONDS = 10.0
DETAIL_LIMIT = 200

X3_MESSAGE = (
    "a private or unrecorded repository posts only over https; "
    "see X3 (Langfuse over HTTPS)"
)

# A Langfuse key: the sk-lf- or pk-lf- prefix and at least eight key characters.
# TypeSafe's patterns miss both (its sk- form wants twenty letters or digits
# straight after the dash, and it has no pk- form), so this runs first.
_LANGFUSE_KEY = re.compile(r"\b(?:sk|pk)-lf-[A-Za-z0-9_\-]{8,}")

_PREPARED_TOKEN = object()


class LangfuseClientError(ValueError):
    """A caller error: an unknown endpoint kind. Never carries a key or the host."""


@dataclass(frozen=True)
class PreparedPayload:
    """A redacted payload for one endpoint. Only ``prepare_payload`` stamps ``token``."""

    kind: str
    body: Any
    token: Any = None


@dataclass(frozen=True)
class SendResult:
    """What happened. It holds no key and no host address, by construction."""

    outcome: str
    reason: str = ""
    status: int | None = None
    detail: str = ""
    body: Any = None

    @property
    def sent(self) -> bool:
        return self.outcome == SENT


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _LANGFUSE_KEY.sub(REDACTION_PLACEHOLDER, value)
    if isinstance(value, Mapping):
        return {_scrub(key) if isinstance(key, str) else key: _scrub(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(item) for item in value]
    return value


def prepare_payload(kind: str, body: Any) -> PreparedPayload:
    """Remove Langfuse key shapes, redact with TypeSafe's rules, and stamp the result."""
    if kind not in ENDPOINTS:
        raise LangfuseClientError(f"unknown Langfuse endpoint kind {kind!r}")
    return PreparedPayload(kind=kind, body=redact(_scrub(body)), token=_PREPARED_TOKEN)


def is_prepared(payload: Any) -> bool:
    return isinstance(payload, PreparedPayload) and payload.token is _PREPARED_TOKEN


def _resolve_keys(getenv: Callable[[str], str | None]) -> tuple[str, str] | None:
    # SECRET BOUNDARY -- the pair below is returned only to the line that writes
    # the Authorization header. It is never stored on a result, logged, or put
    # into a message. Do not widen its reach.
    public = getenv(PUBLIC_KEY_ENV)
    secret = getenv(SECRET_KEY_ENV)
    if not public or not secret:
        return None
    return public, secret


def _plain_http_refused(address: str) -> bool:
    """True unless ``address`` is loopback or private and not link-local.

    Python marks link-local addresses private too, and 169.254.169.254 is the cloud metadata
    address, so the link-local refusal comes first.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip.is_link_local:
        return True
    return not (ip.is_loopback or ip.is_private)


def gate(
    host: str | None,
    visibility: str | None,
    *,
    resolve: Callable[..., Any] = socket.getaddrinfo,
) -> tuple[str, str] | None:
    """The visibility rule. ``None`` when sending is allowed, else ``(reason, detail)``.

    ``visibility`` other than ``public`` or ``private`` counts as private.
    """
    if not host:
        return "missing-host", f"{HOST_ENV} is not set; nothing was sent"
    parsed = urllib.parse.urlsplit(host)
    if not parsed.hostname:
        return "bad-scheme", f"{HOST_ENV} has no host name; nothing was sent"
    if parsed.scheme == "https":
        return None
    if parsed.scheme != "http":
        return "bad-scheme", f"{HOST_ENV} must use https or http; nothing was sent"
    if visibility != "public":
        return "plain-http-private", X3_MESSAGE
    try:
        found = resolve(parsed.hostname, parsed.port or 80, 0, socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        found = []
    addresses = [entry[4][0] for entry in found or [] if entry and entry[4]]
    if not addresses:
        return "address-lookup-failed", "the host's address could not be looked up; nothing was sent"
    if any(_plain_http_refused(str(address)) for address in addresses):
        return (
            "plain-http-public-address",
            "plain http is allowed only to a loopback or private, non-link-local address; nothing was sent",
        )
    return None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Follow no redirect: an https to http downgrade would put the key pair in clear."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def default_opener() -> urllib.request.OpenerDirector:
    """The real opener: the default certificate check, and no redirects."""
    return urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        _NoRedirect,
    )


def _detail(text: str, secrets: tuple[str, ...]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTION_PLACEHOLDER)
    return redact_text(_LANGFUSE_KEY.sub(REDACTION_PLACEHOLDER, text))[:DETAIL_LIMIT]


def send(
    prepared: Any,
    *,
    visibility: str | None,
    getenv: Callable[[str], str | None] = os.environ.get,
    urlopen: Callable[..., Any] | None = None,
    resolve: Callable[..., Any] = socket.getaddrinfo,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> SendResult:
    """Send one prepared payload. Never raises for a network or server problem."""
    if not is_prepared(prepared):
        return SendResult(REFUSED, "unprepared", detail="the payload skipped prepare_payload")
    method, path = ENDPOINTS[prepared.kind]
    keys = _resolve_keys(getenv)
    if keys is None:
        return SendResult(
            REFUSED,
            "missing-keys",
            detail=f"{PUBLIC_KEY_ENV} and {SECRET_KEY_ENV} must both be set; nothing was sent",
        )
    host = getenv(HOST_ENV) or ""
    refusal = gate(host, visibility, resolve=resolve)
    if refusal is not None:
        return SendResult(REFUSED, refusal[0], detail=refusal[1])
    url = host.rstrip("/") + path
    data = None
    headers = {"Accept": "application/json"}
    if method == "GET":
        query = prepared.body if isinstance(prepared.body, Mapping) else {}
        if query:
            url += "?" + urllib.parse.urlencode(
                {key: value if isinstance(value, str) else json.dumps(value) for key, value in query.items()}
            )
    else:
        data = json.dumps(prepared.body, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
        if prepared.kind == "otel-traces":
            headers["x-langfuse-ingestion-version"] = "4"
    credential = base64.b64encode(f"{keys[0]}:{keys[1]}".encode()).decode("ascii")
    headers["Authorization"] = f"Basic {credential}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)  # noqa: S310
    opener = urlopen or default_opener().open
    secrets = (keys[0], keys[1], credential, host.rstrip("/"))
    try:
        with opener(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or response.getcode() or 200)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        try:
            text = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - an unreadable error body is just empty
            text = ""
        reason = "redirect" if 300 <= exc.code < 400 else f"http-{exc.code}"
        return SendResult(REJECTED, reason, status=exc.code, detail=_detail(text, secrets))
    except TimeoutError:
        return SendResult(TIMEOUT, "timeout", detail="the request timed out")
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return SendResult(TIMEOUT, "timeout", detail="the request timed out")
        return SendResult(UNREACHABLE, "unreachable", detail="the host could not be reached")
    except OSError:
        return SendResult(UNREACHABLE, "unreachable", detail="the host could not be reached")
    if not 200 <= status < 300:
        return SendResult(REJECTED, f"http-{status}", status=status)
    body = None
    if method == "GET":
        try:
            body = json.loads(raw.decode("utf-8") or "null")
        except (UnicodeDecodeError, json.JSONDecodeError):
            return SendResult(REJECTED, "malformed-response", status=status)
    return SendResult(SENT, status=status, body=body)


def get(kind: str, query: Mapping[str, Any] | None = None, **kwargs: Any) -> SendResult:
    """The read path for ``projects``, ``metrics``, ``traces`` and ``scores-list``.

    The visibility rule still applies. The v3 reads live while the self-hosted server stays
    on its v3 generation; the v4 replacements are a later migration, not a third kind here.
    """
    if ENDPOINTS.get(kind, ("", ""))[0] != "GET":
        raise LangfuseClientError(f"{kind!r} is not a read endpoint")
    return send(prepare_payload(kind, dict(query or {})), **kwargs)
