#!/usr/bin/env python3
"""Offline debug healthcheck for ChronoScalp.

Runs without MT5/OANDA: validates config, risk floors, circuit breaker recovery,
breakeven tighten-only, bar-close gate alignment, and logging sinks. Writes a
report to ``logs/debug_healthcheck_*.log`` via the standard loguru setup.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from chronoscalp.config import get_settings  # noqa: E402
from chronoscalp.execution.position_logic import apply_breakeven_or_trailing  # noqa: E402
from chronoscalp.logging_setup import logger, setup_logging  # noqa: E402
from chronoscalp.orchestration.bar_scheduler import (  # noqa: E402
    BarCloseGate,
    last_completed_bar_time,
)
from chronoscalp.orchestration.circuit_breaker import CircuitBreaker  # noqa: E402
from chronoscalp.risk.position_sizing import RiskManager  # noqa: E402
from chronoscalp.utils.types import Position, SignalType  # noqa: E402


def _ok(name: str) -> None:
    logger.info("[PASS] {}", name)


def _fail(name: str, detail: str) -> None:
    logger.error("[FAIL] {} — {}", name, detail)


def main() -> int:
    setup_logging(log_level="INFO", log_dir="logs")
    logger.info("=== ChronoScalp debug healthcheck @ {} ===", datetime.now(tz=UTC).isoformat())
    failures = 0

    # 1) Config + hard risk floors
    try:
        settings = get_settings()
        max_risk = float(settings.risk.get("max_risk_per_trade_pct", 0))
        min_rr = float(settings.risk.get("min_reward_risk_ratio", 0))
        assert max_risk <= 1.0 + 1e-9, f"max_risk={max_risk}"
        assert min_rr >= 1.5 - 1e-9, f"min_rr={min_rr}"
        _ok(f"risk floors (max_risk={max_risk}% min_rr={min_rr})")
        logger.info(
            "symbols={} strategies={} hours={}",
            settings.symbols,
            (settings.strategy.get("enabled_strategies") or settings.strategy.get("enabled")),
            (settings.sessions or {}).get("trading_hours_mode"),
        )
    except Exception as exc:  # noqa: BLE001
        failures += 1
        _fail("config/risk floors", str(exc))

    # 2) Circuit breaker recovers after success
    try:
        cb = CircuitBreaker(max_consecutive_errors=2)
        cb.record_failure("a")
        cb.record_failure("b")
        assert cb.is_tripped
        cb.record_success()
        assert not cb.is_tripped
        _ok("circuit breaker untrips on success")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        _fail("circuit breaker", str(exc))

    # 3) Breakeven never widens after trail
    try:
        rm = RiskManager(
            risk_cfg={"breakeven_at_r_multiple": 1.0, "trailing_stop_atr_multiple": 1.5},
            spread_cfg={"enabled": False},
            symbols_cfg={},
            starting_equity=10_000,
        )
        pos = Position(
            ticket=1,
            symbol="XAUUSD",
            direction=SignalType.BUY,
            volume=0.1,
            entry_price=2000.0,
            stop_loss=2010.0,
            take_profit=2030.0,
            open_time=datetime.now(tz=UTC),
            initial_stop_loss=1990.0,
        )
        assert rm.breakeven_stop(pos, 2020.0) is None
        new_sl = apply_breakeven_or_trailing(rm, pos, 2020.0, atr_value=5.0)
        assert new_sl is None or new_sl > pos.stop_loss
        _ok("breakeven never widens after ATR trail")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        _fail("breakeven tighten-only", str(exc))

    # 4) Bar-close gate aligns with strategy iloc[-1] on completed-only frames
    try:
        index = pd.date_range("2026-01-01", periods=5, freq="1min", tz="UTC")
        df = pd.DataFrame({"close": range(5)}, index=index)
        bar_t = last_completed_bar_time(df)
        assert bar_t == index[-1].to_pydatetime()
        gate = BarCloseGate()
        assert gate.is_new_bar("XAUUSD:inst", bar_t)
        gate.mark_evaluated("XAUUSD:inst", bar_t)
        assert not gate.is_new_bar("XAUUSD:inst", bar_t)
        _ok("bar-close gate matches completed bar index[-1]")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        _fail("bar-close gate", str(exc))

    # 5) Logging sinks present
    try:
        log_dir = Path("logs")
        assert log_dir.is_dir()
        today = log_dir / f"chronoscalp_{datetime.now(tz=UTC).strftime('%Y-%m-%d')}.log"
        logger.info("Writing probe line for healthcheck sink verification")
        assert today.exists() or any(log_dir.glob("chronoscalp_*.log"))
        _ok(f"logging sinks under {log_dir.resolve()}")
    except Exception as exc:  # noqa: BLE001
        failures += 1
        _fail("logging", str(exc))

    if failures:
        logger.error("Healthcheck FAILED with {} issue(s)", failures)
        return 1
    logger.info("Healthcheck PASSED — core debug paths look healthy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
