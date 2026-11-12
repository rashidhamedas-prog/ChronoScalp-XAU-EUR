from datetime import UTC, datetime, timedelta

from chronoscalp.orchestration.circuit_breaker import CircuitBreaker


def test_circuit_breaker_trips_after_threshold():
    cb = CircuitBreaker(max_consecutive_errors=3, min_trip_seconds=0, success_threshold=1)
    assert cb.record_failure("a") is False
    assert cb.record_failure("b") is False
    assert cb.record_failure("c") is True
    assert cb.is_tripped


def test_circuit_breaker_success_resets_error_streak_when_closed():
    cb = CircuitBreaker(max_consecutive_errors=2, min_trip_seconds=0, success_threshold=1)
    cb.record_failure("a")
    cb.record_success()
    assert cb.consecutive_errors == 0
    assert not cb.is_tripped


def test_circuit_breaker_untrips_after_min_duration_and_successes():
    cb = CircuitBreaker(max_consecutive_errors=2, min_trip_seconds=10, success_threshold=2)
    t0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    cb.record_failure("a", now=t0)
    cb.record_failure("b", now=t0)
    assert cb.is_tripped
    cb.record_success(now=t0 + timedelta(seconds=1))
    assert cb.is_tripped
    cb.record_success(now=t0 + timedelta(seconds=11))
    assert cb.is_half_open
    cb.record_success(now=t0 + timedelta(seconds=12))
    assert not cb.is_tripped


def test_circuit_breaker_reset():
    cb = CircuitBreaker(max_consecutive_errors=1, min_trip_seconds=0, success_threshold=1)
    cb.record_failure("x")
    assert cb.is_tripped
    cb.reset()
    assert not cb.is_tripped
    assert cb.consecutive_errors == 0
