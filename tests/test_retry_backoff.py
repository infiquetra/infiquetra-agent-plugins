"""Tests for the shared fleet-commons retry/backoff primitive (#348 U1).

Deterministic: injected ``sleep``/``rng``/``clock``/``now`` seams — no real time passes, no real
randomness.

Ported into this repository from ``infiquetra-claude-plugins`` at commit
``ed72f439ba01f2e20d94be074e5612c5641c0c8e`` (Fleet Core 0.25.1). The eighteen test
functions below are byte-identical to their upstream originals. The one
deviation is the guarded ``pytest`` import directly beneath this docstring, and
it is recorded in ``plugins/fleet-core/PROVENANCE.json`` as deterministic
transform ``guard-pytest-import`` version 2.

The guard exists because this repository runs two test jobs over the same
directory. The hermetic baseline job runs ``python3 -m unittest discover -s
tests`` with no dependencies installed, and it imports every ``test*.py`` it
finds; the ported plugin job runs ``python -m pytest tests`` with pytest
installed. Without the guard the baseline job fails on an import for tests it
never runs.

Version 2 raises ``unittest.SkipTest`` where version 1 bound ``pytest`` to
``None``. Fleet Core 0.25.1 brought two tests carrying
``@pytest.mark.parametrize``, and a decorator runs when the module is imported:
against ``None`` it raises ``AttributeError``, so the baseline job would fail on
a module it never meant to run. ``unittest`` catches ``SkipTest`` raised during
import and records the module as one skipped test, so the baseline job stays
green and says out loud why it collected nothing here, while the plugin job --
where pytest is installed -- runs every test unchanged.
"""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path
from types import ModuleType
from typing import Any

try:  # pragma: no cover - import guard, not behavior under test
    import pytest
except ModuleNotFoundError as exc:  # pragma: no cover - hermetic baseline has no pytest
    import unittest

    raise unittest.SkipTest(
        "pytest is not installed; the ported Fleet Core suite runs in the plugin test job"
    ) from exc

ROOT = Path(__file__).parent.parent
MOD_PATH = ROOT / "plugins" / "fleet-core" / "scripts" / "fleet_commons" / "retry_backoff.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("retry_backoff", MOD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RB = _load()


class RateError(Exception):
    status_code = 429


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _recorder() -> tuple[list[float], Any]:
    delays: list[float] = []
    return delays, delays.append


# --------------------------------------------------------------------------- retry_with_backoff


def test_retry_then_success() -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateError("rate limited")
        return "ok"

    delays, sleep = _recorder()
    import random

    result = RB.retry_with_backoff(fn, sleep=sleep, rng=random.Random(0))
    assert result == "ok"
    assert calls["n"] == 2
    assert len(delays) == 1  # one backoff between the two attempts


def test_non_retryable_propagates_immediately() -> None:
    calls = {"n": 0}

    def fn() -> None:
        calls["n"] += 1
        raise ValueError("not a 429")

    delays, sleep = _recorder()
    with pytest.raises(ValueError):
        RB.retry_with_backoff(fn, sleep=sleep)
    assert calls["n"] == 1  # no retry
    assert delays == []


def test_attempt_cap_honored() -> None:
    calls = {"n": 0}

    def fn() -> None:
        calls["n"] += 1
        raise RateError("always")

    delays, sleep = _recorder()
    import random

    with pytest.raises(RateError):
        RB.retry_with_backoff(fn, max_attempts=3, sleep=sleep, rng=random.Random(0))
    assert calls["n"] == 3
    assert len(delays) == 2  # backoff between attempts 1->2 and 2->3, none after the last


def test_jitter_within_bounds() -> None:
    import random

    def fn() -> None:
        raise RateError("x")

    delays, sleep = _recorder()
    with pytest.raises(RateError):
        RB.retry_with_backoff(fn, max_attempts=2, base_delay=1.0, sleep=sleep, rng=random.Random(0))
    assert len(delays) == 1
    assert 0.5 <= delays[0] <= 1.0  # attempt-1 delay = 1.0 * (0.5..1.0)


def test_retry_after_hint_overrides_backoff() -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateError("rate limited")
        return "ok"

    delays, sleep = _recorder()
    RB.retry_with_backoff(fn, retry_after=lambda _exc: 5.0, sleep=sleep)
    assert delays == [5.0]


def test_retry_after_hint_is_clamped_to_max_delay() -> None:
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateError("rate limited")
        return "ok"

    delays, sleep = _recorder()
    RB.retry_with_backoff(fn, retry_after=lambda _exc: 999999.0, max_delay=7.0, sleep=sleep)
    assert delays == [7.0]


def test_zero_retry_after_hint_uses_computed_backoff() -> None:
    import random

    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateError("rate limited")
        return "ok"

    delays, sleep = _recorder()
    RB.retry_with_backoff(
        fn,
        retry_after=lambda _exc: 0.0,
        base_delay=2.0,
        sleep=sleep,
        rng=random.Random(0),
    )
    assert len(delays) == 1
    assert 1.0 <= delays[0] <= 2.0


def test_negative_retry_after_hint_uses_computed_backoff() -> None:
    import random

    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateError("rate limited")
        return "ok"

    delays, sleep = _recorder()
    RB.retry_with_backoff(
        fn,
        retry_after=lambda _exc: -5.0,
        base_delay=2.0,
        sleep=sleep,
        rng=random.Random(0),
    )
    assert len(delays) == 1
    assert 1.0 <= delays[0] <= 2.0


# ------------------------------------------------------- Retry-After: both RFC 7231 forms (O3)

# A frozen wall clock, so every HTTP-date fixture below resolves to the same delay on every run.
# This is the `now` seam, distinct from the breaker's monotonic `clock` seam.
NOW = 1700000000.0  # Tue, 14 Nov 2023 22:13:20 GMT
FUTURE_DATE = "Tue, 14 Nov 2023 22:14:05 GMT"  # NOW + 45s
PAST_DATE = "Tue, 14 Nov 2023 22:12:20 GMT"  # NOW - 60s
EXCESSIVE_DATE = "Fri, 31 Dec 2100 23:59:59 GMT"  # ~77 years past NOW
SECONDS_TO_EXCESSIVE_DATE = 2433980799.0


def _now() -> float:
    return NOW


class RawHeaderRateError(Exception):
    """A 429 carrying the raw ``Retry-After`` header text, exactly as a controller sent it."""

    status_code = 429

    def __init__(self, retry_after: Any) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


def _delays_for(header_value: Any, **kwargs: Any) -> list[float]:
    """Run one 429-then-success cycle whose error carries ``header_value``; return the slept delays."""
    calls = {"n": 0}

    def fn() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RawHeaderRateError(header_value)
        return "ok"

    delays, sleep = _recorder()
    kwargs.setdefault("rng", random.Random(0))
    result = RB.retry_with_backoff(
        fn,
        retry_after=lambda exc: getattr(exc, "retry_after", None),
        sleep=sleep,
        now=_now,
        **kwargs,
    )
    assert result == "ok"
    return delays


def test_delta_seconds_hint_is_unchanged_numeric_and_string() -> None:
    # The delta-seconds form is what the primitive already honored; both the pre-parsed number and
    # the raw header text must still produce exactly that delay.
    assert _delays_for(30) == [30.0]
    assert _delays_for("30") == [30.0]


def test_future_http_date_is_honored_as_the_seconds_remaining() -> None:
    assert RB.parse_retry_after(FUTURE_DATE, now=_now) == 45.0
    assert _delays_for(FUTURE_DATE) == [45.0]


def test_past_http_date_means_retry_now_never_a_negative_delay() -> None:
    # "Retry now" is 0.0, not a negative delay. The existing non-positive rule (fleet-core 0.8.1)
    # then answers with computed jittered backoff, so a stale date cannot become a zero-sleep loop.
    assert RB.parse_retry_after(PAST_DATE, now=_now) == 0.0
    delays = _delays_for(PAST_DATE, base_delay=2.0)
    assert len(delays) == 1
    assert 1.0 <= delays[0] <= 2.0


def test_unparseable_retry_after_falls_back_to_computed_backoff() -> None:
    assert RB.parse_retry_after("next Tuesday-ish", now=_now) is None
    delays = _delays_for("next Tuesday-ish", base_delay=2.0)
    assert len(delays) == 1
    assert 1.0 <= delays[0] <= 2.0


def test_excessive_http_date_is_clamped_to_max_delay() -> None:
    # The parse is honest about the enormous gap; the clamp is what bounds the sleep, exactly as it
    # already bounds an enormous numeric hint.
    assert RB.parse_retry_after(EXCESSIVE_DATE, now=_now) == SECONDS_TO_EXCESSIVE_DATE
    assert _delays_for(EXCESSIVE_DATE, max_delay=7.0) == [7.0]


@pytest.mark.parametrize(
    "header",
    [
        "Tue, 14 Nov 2023 22:14:05 GMT",  # IMF-fixdate, the RFC 7231 preferred form
        "Tuesday, 14-Nov-23 22:14:05 GMT",  # obsolete RFC 850 form
        "Tue Nov 14 22:14:05 2023",  # obsolete asctime form, no zone, read as GMT
    ],
)
def test_all_three_http_date_forms_parse(header: str) -> None:
    assert RB.parse_retry_after(header, now=_now) == 45.0


@pytest.mark.parametrize("value", [None, "", "   ", True, False, object()])
def test_values_that_are_not_a_delay_parse_to_none(value: Any) -> None:
    assert RB.parse_retry_after(value, now=_now) is None


def test_a_caller_that_pre_parses_with_int_still_loses_the_retry() -> None:
    """Pins the boundary of this repair: the primitive fixes the hint it is handed.

    A call site that converts the header with ``int()`` before raising turns a 429 into a
    ``ValueError``, which carries no status and so is not retryable — one request, no backoff.
    Call sites must hand the raw header to ``retry_after`` (or pre-parse with ``parse_retry_after``).
    """
    calls = {"n": 0}

    def fn() -> None:
        calls["n"] += 1
        int(FUTURE_DATE)  # what a call site that pre-parses the header with int() does

    delays, sleep = _recorder()
    with pytest.raises(ValueError):
        RB.retry_with_backoff(fn, sleep=sleep, now=_now)
    assert calls["n"] == 1  # no retry: the ValueError never looked like a 429
    assert delays == []


# --------------------------------------------------------------------------- CircuitBreaker / bridge_call


def test_breaker_opens_short_circuits_then_half_opens_and_closes() -> None:
    clock = _Clock()
    breaker = RB.CircuitBreaker(fail_threshold=2, cooldown=10.0, clock=clock)

    def always_429() -> None:
        raise RateError("429")

    # Two failures (each bridge_call = one failure with max_attempts=1) -> OPEN.
    for _ in range(2):
        with pytest.raises(RateError):
            RB.bridge_call(always_429, breaker=breaker, max_attempts=1)
    assert breaker.state == "OPEN"

    # While OPEN (before cooldown), calls short-circuit without invoking fn.
    with pytest.raises(RB.CircuitOpenError):
        RB.bridge_call(always_429, breaker=breaker, max_attempts=1)

    # After cooldown -> HALF_OPEN; a success closes it.
    clock.t = 20.0
    assert breaker.state == "HALF_OPEN"
    assert RB.bridge_call(lambda: "ok", breaker=breaker, max_attempts=1) == "ok"
    assert breaker.state == "CLOSED"


def test_non_rate_limit_error_does_not_trip_breaker() -> None:
    breaker = RB.CircuitBreaker(fail_threshold=1)

    def boom() -> None:
        raise ValueError("bug, not rate limit")

    with pytest.raises(ValueError):
        RB.bridge_call(boom, breaker=breaker, max_attempts=1)
    assert breaker.state == "CLOSED"  # correctness bugs must not open the rate-limit breaker
