from __future__ import annotations

from chronoscalp.orchestration.circuit_breaker import CircuitBreaker


def test_circuit_breaker_trips_after_max_errors():
    cb = CircuitBreaker(max_consecutive_errors=3)
    assert cb.record_failure("a") is False
    assert cb.record_failure("b") is False
    assert cb.record_failure("c") is True
    assert cb.is_tripped is True
    assert cb.tripped_at is not None


def test_circuit_breaker_resets_on_success():
    cb = CircuitBreaker(max_consecutive_errors=2)
    cb.record_failure("x")
    cb.record_success()
    assert cb.consecutive_errors == 0
    assert cb.record_failure("y") is False


def test_circuit_breaker_manual_reset():
    cb = CircuitBreaker(max_consecutive_errors=1)
    cb.record_failure("x")
    assert cb.is_tripped is True
    cb.reset()
    assert cb.is_tripped is False
    assert cb.consecutive_errors == 0
