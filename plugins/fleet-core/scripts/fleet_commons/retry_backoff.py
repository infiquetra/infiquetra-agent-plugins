#!/usr/bin/env python3
"""Shared 429 retry/backoff primitive — the fleet's one rate-limit response (issue #348).

Lives in fleet-commons (issue #463 / DECISIONS ``{#fleet-commons-mechanism-463}``) so every plugin that
can hit a 429 imports ONE implementation instead of re-writing a bespoke handler. Consumers load it via
their vendored ``fleet_commons_shim``: ``fleet_commons_shim.load("retry_backoff")``.

Two entry points:

* ``retry_with_backoff(fn, *, on_status=429, ...)`` — jittered exponential backoff, attempt cap,
  non-retryable pass-through. A non-429 error propagates immediately; a 429 is retried (honoring a
  ``Retry-After`` hint when supplied) up to ``max_attempts``.
* ``bridge_call(fn, *, breaker, ...)`` — wraps ``retry_with_backoff`` and drives a ``CircuitBreaker``
  (OPEN on a run of rate-limit failures, cooldown, HALF-OPEN probe, CLOSE on success) so a provider
  bridge stops hammering a rate-limited endpoint.

stdlib-only, pure over injected ``sleep``/``rng``/``clock`` seams (deterministic tests). Content changes
here are additive-only within fleet-core 0.x — a consumer never breaks because fleet-core updated.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import Any


class CircuitOpenError(RuntimeError):
    """Raised by ``bridge_call`` when the breaker is OPEN and a call is short-circuited."""


def _status_of(exc: BaseException) -> Any:
    """Best-effort HTTP status extraction from a raised error (``status_code`` or ``status``)."""
    return getattr(exc, "status_code", getattr(exc, "status", None))


def _computed_delay(attempt: int, base_delay: float, max_delay: float, rng: random.Random) -> float:
    delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
    return float(delay * (0.5 + rng.random() * 0.5))  # 50–100% jitter


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
    retry_after: Callable[[BaseException], float | None] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> Any:
    """Call ``fn()`` with jittered exponential backoff, retrying a rate-limit failure.

    ``is_retryable`` defaults to "the raised error carries ``on_status``" (429). A non-retryable error
    propagates immediately (no wasted retry). On the final attempt the last error re-raises. ``retry_after``
    may extract a server ``Retry-After`` hint (seconds) from the error to override the computed delay.

    Positive ``Retry-After`` hints are honored up to ``max_delay``; non-positive hints fall back to
    computed backoff so they cannot create tight retry loops. Without a positive hint, the delay is
    ``min(max_delay, base_delay * 2**(attempt-1))`` scaled by 50–100% jitter (full-ish jitter, so
    concurrent callers do not re-collide). ``sleep``/``rng`` are injected for deterministic tests.
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
            hint = retry_after(exc) if retry_after is not None else None
            delay = _retry_delay(
                attempt=attempt,
                base_delay=base_delay,
                max_delay=max_delay,
                hint=hint,
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
