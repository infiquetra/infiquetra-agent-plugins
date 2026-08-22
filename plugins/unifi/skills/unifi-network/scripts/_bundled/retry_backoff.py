# --- generated bundle stamp: do not edit ---
# generated-by: scripts/bundle_fleet_module.py
# source-version: 0.25.1
# source-commit: ed72f439ba01f2e20d94be074e5612c5641c0c8e
# source-path: scripts/fleet_commons/retry_backoff.py
# source-sha256: 5aea3be13ac444aba2610442f76846a16a0e9537befe39090da173cb1fede975
# output-sha256: 5aea3be13ac444aba2610442f76846a16a0e9537befe39090da173cb1fede975
# --- end generated bundle stamp ---
#!/usr/bin/env python3
"""Shared 429 retry/backoff primitive — the fleet's one rate-limit response (issue #348).

Lives in fleet-commons (issue #463 / DECISIONS ``{#fleet-commons-mechanism-463}``) so every plugin that
can hit a 429 imports ONE implementation instead of re-writing a bespoke handler. Consumers load it via
their vendored ``fleet_commons_shim``: ``fleet_commons_shim.load("retry_backoff")``.

Three entry points:

* ``retry_with_backoff(fn, *, on_status=429, ...)`` — jittered exponential backoff, attempt cap,
  non-retryable pass-through. A non-429 error propagates immediately; a 429 is retried (honoring a
  ``Retry-After`` hint when supplied) up to ``max_attempts``.
* ``bridge_call(fn, *, breaker, ...)`` — wraps ``retry_with_backoff`` and drives a ``CircuitBreaker``
  (OPEN on a run of rate-limit failures, cooldown, HALF-OPEN probe, CLOSE on success) so a provider
  bridge stops hammering a rate-limited endpoint.
* ``parse_retry_after(value, *, now=time.time)`` — both RFC 7231 ``Retry-After`` forms (delta-seconds
  and HTTP-date) reduced to a non-negative delay in seconds, or ``None`` when there is no usable hint.

stdlib-only, pure over injected ``sleep``/``rng``/``clock``/``now`` seams (deterministic tests). Content
changes here are additive-only within fleet-core 0.x — a consumer never breaks because fleet-core updated.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any


class CircuitOpenError(RuntimeError):
    """Raised by ``bridge_call`` when the breaker is OPEN and a call is short-circuited."""


def _status_of(exc: BaseException) -> Any:
    """Best-effort HTTP status extraction from a raised error (``status_code`` or ``status``)."""
    return getattr(exc, "status_code", getattr(exc, "status", None))


def _computed_delay(attempt: int, base_delay: float, max_delay: float, rng: random.Random) -> float:
    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
    return float(delay * (0.5 + rng.random() * 0.5))  # 50–100% jitter


def parse_retry_after(
    value: Any,
    *,
    now: Callable[[], float] = time.time,
) -> float | None:
    """Reduce a ``Retry-After`` value to a non-negative delay in seconds (RFC 7231 section 7.1.3).

    Both forms the specification allows are accepted:

    * **delta-seconds** — a count of seconds (``Retry-After: 120``). An already-numeric hint is
      accepted unchanged, so a caller that pre-parses the header keeps its current behaviour.
    * **HTTP-date** — an absolute instant (``Retry-After: Fri, 31 Dec 2100 23:59:59 GMT``), converted
      to the seconds remaining until it. Real controllers send this form; a caller that ran the raw
      header through ``int()`` raised ``ValueError`` instead of backing off, and the raised
      ``ValueError`` carries no 429 status, so the rate-limit retry was skipped entirely.

    A date already in the past yields ``0.0`` — retry now, never a negative delay. An absent, empty,
    or unparseable value yields ``None``, which the caller reads as "the server gave no usable hint"
    and answers with computed jittered backoff. Clamping to ``max_delay`` stays with the caller
    (``_retry_delay``), so a numeric hint and a date hint are bounded identically.

    ``now`` returns epoch seconds and is injected for deterministic tests (the breaker's ``clock``
    seam is monotonic and is a different clock; an HTTP-date needs wall time).
    """
    if value is None or isinstance(value, bool):  # bool is an int subclass; a flag is not a delay
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return float(text)  # delta-seconds
    except ValueError:
        pass
    try:
        deadline = parsedate_to_datetime(text)  # HTTP-date: IMF-fixdate, RFC 850, or asctime
    except (TypeError, ValueError):
        return None
    if deadline.tzinfo is None:  # the asctime form carries no zone; RFC 7231 dates are GMT
        deadline = deadline.replace(tzinfo=UTC)
    return max(0.0, deadline.timestamp() - now())


def _retry_delay(
    *,
    attempt: int,
    base_delay: float,
    max_delay: float,
    hint: float | None,
    rng: random.Random,
) -> float:
    if hint is not None:
        hint_delay = float(hint)
        if hint_delay > 0:
            return min(max_delay, hint_delay)
    return _computed_delay(attempt, base_delay, max_delay, rng)


def retry_with_backoff(
    fn: Callable[[], Any],
    *,
    on_status: int = 429,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    is_retryable: Callable[[BaseException], bool] | None = None,
    retry_after: Callable[[BaseException], float | str | None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    now: Callable[[], float] = time.time,
) -> Any:
    """Call ``fn()`` with jittered exponential backoff, retrying a rate-limit failure.

    ``is_retryable`` defaults to "the raised error carries ``on_status``" (429). A non-retryable error
    propagates immediately (no wasted retry). On the final attempt the last error re-raises. ``retry_after``
    may extract a server ``Retry-After`` hint from the error to override the computed delay; it may return
    either RFC 7231 form — a delta-seconds number or the raw HTTP-date string — and
    ``parse_retry_after`` reduces it to seconds. An unparseable hint is treated as no hint at all.

    Positive ``Retry-After`` hints are honored up to ``max_delay``; non-positive hints (a zero or
    negative delta, and an HTTP-date already in the past, which parses to ``0.0``) fall back to
    computed backoff so they cannot create tight retry loops. Without a positive hint, the delay is
    ``min(max_delay, base_delay * 2**(attempt-1))`` scaled by 50–100% jitter (full-ish jitter, so
    concurrent callers do not re-collide). ``sleep``/``rng``/``now`` are injected for deterministic tests.
    """
    _rng = rng if rng is not None else random.Random()  # nosec B311 - jitter, not security
    retryable = (
        is_retryable if is_retryable is not None else (lambda exc: _status_of(exc) == on_status)
    )

    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised below unless a retryable 429
            if attempt >= max_attempts or not retryable(exc):
                raise
            raw_hint = retry_after(exc) if retry_after is not None else None
            delay = _retry_delay(
                attempt=attempt,
                base_delay=base_delay,
                max_delay=max_delay,
                hint=parse_retry_after(raw_hint, now=now),
                rng=_rng,
            )
            sleep(delay)


class CircuitBreaker:
    """A minimal CLOSED -> OPEN -> HALF_OPEN -> CLOSED breaker over an injected monotonic clock.

    ``fail_threshold`` consecutive failures OPEN the breaker; after ``cooldown`` seconds it reports
    HALF_OPEN (one probe allowed); a success CLOSES it and resets the count; a failure while HALF_OPEN
    re-OPENs it.
    """

    def __init__(
        self,
        *,
        fail_threshold: int = 5,
        cooldown: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.fail_threshold = fail_threshold
        self.cooldown = cooldown
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None
        self._state = "CLOSED"

    @property
    def state(self) -> str:
        if (
            self._state == "OPEN"
            and self._opened_at is not None
            and self._clock() - self._opened_at >= self.cooldown
        ):
            self._state = "HALF_OPEN"
        return self._state

    def on_success(self) -> None:
        self._failures = 0
        self._opened_at = None
        self._state = "CLOSED"

    def on_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.fail_threshold:
            self._state = "OPEN"
            self._opened_at = self._clock()


def bridge_call(
    fn: Callable[[], Any],
    *,
    breaker: CircuitBreaker,
    on_status: int = 429,
    is_retryable: Callable[[BaseException], bool] | None = None,
    **retry_kwargs: Any,
) -> Any:
    """Drive ``fn`` through ``retry_with_backoff`` under a circuit breaker (for provider bridges, #348).

    Short-circuits with ``CircuitOpenError`` while the breaker is OPEN (during cooldown). A rate-limit
    failure that survives retry trips the breaker; any success closes it. Non-rate-limit errors propagate
    but do NOT trip the breaker (the breaker guards rate-limiting, not correctness bugs).
    """
    retryable = (
        is_retryable if is_retryable is not None else (lambda exc: _status_of(exc) == on_status)
    )

    if breaker.state == "OPEN":
        raise CircuitOpenError("circuit breaker is OPEN; call short-circuited during cooldown")

    try:
        result = retry_with_backoff(fn, on_status=on_status, is_retryable=retryable, **retry_kwargs)
    except Exception as exc:  # noqa: BLE001
        if retryable(exc):
            breaker.on_failure()
        raise
    breaker.on_success()
    return result
