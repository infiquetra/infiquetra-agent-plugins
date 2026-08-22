"""Tests for the shared fleet-commons retry/backoff primitive (#348 U1).

Deterministic: injected ``sleep``/``rng``/``clock`` seams — no real time passes, no real randomness.

Ported into this repository from ``infiquetra-claude-plugins`` at commit
``13b02343369fdd19ec3ce3a036009bd1023962ad`` (Fleet Core 0.25.0). The ten test
functions below are byte-identical to their upstream originals. The one
deviation is the guarded ``pytest`` import directly beneath this docstring, and
it is recorded in ``plugins/fleet-core/PROVENANCE.json`` as deterministic
transform ``guard-pytest-import`` version 1.

The guard exists because this repository runs two test jobs over the same
directory. The hermetic baseline job runs ``python3 -m unittest discover -s
tests`` with no dependencies installed, and it imports every ``test*.py`` it
finds; the ported plugin job runs ``python -m pytest tests`` with pytest
installed. Without the guard the baseline job fails on an import for tests it
never runs. With it, unittest imports this module, collects nothing from it
because it defines no ``TestCase``, and pytest runs all ten tests unchanged.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

try:  # pragma: no cover - import guard, not behavior under test
    import pytest
except ModuleNotFoundError:  # pragma: no cover - hermetic baseline has no pytest
    pytest = None  # type: ignore[assignment]

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
