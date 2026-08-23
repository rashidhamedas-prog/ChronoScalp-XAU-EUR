from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from chronoscalp.backtest.engine import (
    LIVE_ONLY_GATES,
    _as_of_closed,
    _to_utc_timestamp,
    run_backtest,
)
from chronoscalp.config import Settings
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.utils.types import Timeframe


def _synthetic_ohlcv(
    n: int = 200,
    freq: str = "1min",
    *,
    start: str = "2026-01-01",
) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    close = 2000 + np.cumsum(rng.normal(0, 0.2, n))
    high = close + rng.uniform(0.05, 0.3, n)
    low = close - rng.uniform(0.05, 0.3, n)
    open_ = close + rng.normal(0, 0.05, n)
    index = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)


def _enriched_by_tf(start: str = "2026-01-01") -> dict[Timeframe, pd.DataFrame]:
    base = _synthetic_ohlcv(start=start)
    result = {}
    for tf in (Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M10):
        if tf == Timeframe.M1:
            df = base
        else:
            df = (
                base.resample(f"{tf.minutes}min")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
                .dropna()
            )
        df = enrich_with_indicators(df)
        result[tf] = enrich_with_smc(df)
    return result


def test_run_backtest_returns_summary_without_error():
    """Smoke: engine completes on synthetic XAU data.

    The default fixture starts at 2026-01-01 00:00 UTC. With
    ``trading_hours_mode: london_ny`` (London 08:00–11:00, NY 13:30–16:30 GMT),
    those bars are outside every session window, so the session filter vetoes
    entries and ``total_trades`` may be 0. That is expected fixture behaviour,
    not an engine crash.
    """
    settings = Settings()
    data = _enriched_by_tf(start="2026-01-01")
    result = run_backtest(
        symbol="XAUUSD",
        data_by_timeframe=data,
        higher_timeframes=[Timeframe.M10, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        settings=settings,
    )
    summary = result.summary()
    assert summary["symbol"] == "XAUUSD"
    assert "total_trades" in summary
    # Backtest counts bound live counts from above; the summary must say so.
    assert summary["live_only_gates_not_modelled"] == list(LIVE_ONLY_GATES)
    assert "mistake_memory" in summary["live_only_gates_not_modelled"]
    assert result.starting_equity == float(settings.backtest.get("initial_balance", 10_000))
    # Document the known zero-trade cause for this fixture window.
    session = SessionFilter.from_config(settings.sessions)
    first_bar = data[Timeframe.M1].index[0].to_pydatetime()
    assert not session.is_within_session(first_bar, "XAUUSD")
    # Off-session synthetic start → zero trades under london_ny (not an engine bug).
    assert summary["total_trades"] == 0
    assert "strategy_reports" in summary
    assert isinstance(summary["strategy_reports"], dict)


def test_run_backtest_in_session_fixture_completes():
    """Bars starting 2026-01-05 08:00 UTC fall inside the London window.

    Strategy sparsity may still yield zero trades; this test only requires a
    clean run and that the session filter would allow the first bar. Do not
    require ``total_trades > 0`` without a forced-entry path.
    """
    settings = Settings()
    data = _enriched_by_tf(start="2026-01-05 08:00")
    session = SessionFilter.from_config(settings.sessions)
    first_bar = data[Timeframe.M1].index[0].to_pydatetime()
    assert session.is_within_session(first_bar, "XAUUSD")

    result = run_backtest(
        symbol="XAUUSD",
        data_by_timeframe=data,
        higher_timeframes=[Timeframe.M10, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        settings=settings,
    )
    summary = result.summary()
    assert summary["symbol"] == "XAUUSD"
    assert "total_trades" in summary
    assert isinstance(summary["total_trades"], int)
    assert summary["total_trades"] >= 0


def test_to_utc_timestamp_accepts_aware_and_naive():
    """Aware bounds must convert; naive bounds localize — never Timestamp(..., tz=)."""
    aware = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    naive = datetime(2026, 1, 5, 8, 0)
    aware_ts = _to_utc_timestamp(aware)
    naive_ts = _to_utc_timestamp(naive)
    assert aware_ts.tzinfo is not None
    assert naive_ts.tzinfo is not None
    assert aware_ts == pd.Timestamp("2026-01-05 08:00", tz="UTC")
    assert naive_ts == pd.Timestamp("2026-01-05 08:00", tz="UTC")


def test_run_backtest_accepts_timezone_aware_start_end():
    """Regression: walk-forward passes tz-aware fold bounds into run_backtest.

    Previously ``pd.Timestamp(aware_dt, tz="UTC")`` raised ValueError.
    """
    settings = Settings()
    data = _enriched_by_tf(start="2026-01-05 08:00")
    start = datetime(2026, 1, 5, 8, 0, tzinfo=UTC)
    end = datetime(2026, 1, 5, 10, 0, tzinfo=UTC)

    result = run_backtest(
        symbol="XAUUSD",
        data_by_timeframe=data,
        higher_timeframes=[Timeframe.M10, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        settings=settings,
        start=start,
        end=end,
    )
    summary = result.summary()
    assert summary["symbol"] == "XAUUSD"
    assert isinstance(summary["total_trades"], int)
    assert summary["total_trades"] >= 0


def test_htf_as_of_excludes_forming_bar():
    """M5 bar that is still forming at an M1 timestamp must not be visible."""
    m5 = pd.DataFrame(
        {
            "open": [0.0, 1.0, 2.0],
            "high": [0.1, 1.1, 2.1],
            "low": [-0.1, 0.9, 1.9],
            "close": [0.05, 1.05, 2.05],
        },
        index=pd.DatetimeIndex(
            ["2026-01-05 07:55", "2026-01-05 08:00", "2026-01-05 08:05"],
            tz="UTC",
        ),
    )
    t = pd.Timestamp("2026-01-05 08:04", tz="UTC")
    closed = _as_of_closed(m5, t, Timeframe.M5, is_trigger=False)
    assert len(closed) == 1
    assert closed.index[-1] == pd.Timestamp("2026-01-05 07:55", tz="UTC")
    trigger = _as_of_closed(m5, t, Timeframe.M5, is_trigger=True)
    assert list(trigger.index.astype(str))[-1].startswith("2026-01-05 08:00")
