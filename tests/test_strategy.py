from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.strategy.multi_timeframe import (
    determine_trend,
    generate_entry_signal,
    trends_aligned,
)
from chronoscalp.utils.types import SignalType, Timeframe, TrendDirection


def _trending_df(n: int = 120, direction: str = "up") -> pd.DataFrame:
    slope = 0.15 if direction == "up" else -0.15
    close = 100 + np.cumsum(np.full(n, slope))
    high = close + 0.1
    low = close - 0.1
    open_ = close - 0.02
    index = pd.date_range("2026-01-01", periods=n, freq="10min", tz="UTC")
    df = pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=index)
    return enrich_with_indicators(df, ema_period=50)


def test_determine_trend_bullish():
    df = _trending_df(direction="up")
    trend = determine_trend(df, ema_col="ema_50")
    assert trend == TrendDirection.BULLISH


def test_determine_trend_bearish():
    df = _trending_df(direction="down")
    trend = determine_trend(df, ema_col="ema_50")
    assert trend == TrendDirection.BEARISH


def test_determine_trend_neutral_on_insufficient_data():
    df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1]})
    assert determine_trend(df) == TrendDirection.NEUTRAL


def test_trends_aligned_requires_unanimous_agreement():
    assert (
        trends_aligned([TrendDirection.BULLISH, TrendDirection.BULLISH]) == TrendDirection.BULLISH
    )
    assert (
        trends_aligned([TrendDirection.BULLISH, TrendDirection.BEARISH]) == TrendDirection.NEUTRAL
    )
    assert (
        trends_aligned([TrendDirection.NEUTRAL, TrendDirection.NEUTRAL]) == TrendDirection.NEUTRAL
    )


def _macd_cross_up_frame() -> pd.DataFrame:
    """Minimal frame where last bar is a bullish MACD cross with BB/ATR filled."""
    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="min", tz="UTC")
    close = np.array([100.0, 100.1, 100.2, 100.3, 100.4])
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "macd": [-0.02, -0.01, 0.0, -0.01, 0.02],
            "signal": [0.0, 0.0, 0.0, 0.0, 0.0],
            "bb_lower": close - 1,
            "bb_upper": close + 1,
            "atr": np.full(n, 0.5),
            "rsi": np.full(n, 55.0),
            "histogram": [0.0] * n,
            "liquidity_sweep_low_vol": [False, False, False, False, True],
            "liquidity_sweep_high_vol": [False] * n,
        },
        index=index,
    )
    return df


def test_liquidity_volume_gate_blocks_without_vol_sweep():
    df = _macd_cross_up_frame()
    df.iloc[-1, df.columns.get_loc("liquidity_sweep_low_vol")] = False
    signal = generate_entry_signal(
        "EURJPY",
        df,
        TrendDirection.BULLISH,
        Timeframe.M1,
        use_smc_confluence=False,
        use_liquidity_volume=True,
    )
    assert signal.signal_type == SignalType.NONE


def test_liquidity_volume_gate_allows_vol_confirmed_sweep():
    df = _macd_cross_up_frame()
    signal = generate_entry_signal(
        "EURJPY",
        df,
        TrendDirection.BULLISH,
        Timeframe.M1,
        use_smc_confluence=False,
        use_liquidity_volume=True,
        atr_stop_multiple=1.5,
        atr_target_multiple=2.5,
    )
    assert signal.signal_type == SignalType.BUY
    assert "liquidity_volume" in signal.reason


def test_both_strategies_or_allows_smc_without_vol():
    """When SMC + liquidity are both enabled, either mode may confirm (OR)."""
    df = _macd_cross_up_frame()
    df.iloc[-1, df.columns.get_loc("liquidity_sweep_low_vol")] = False
    df["bullish_ob"] = False
    df["fvg_bullish"] = False
    df["liquidity_sweep_low"] = False
    df.iloc[-1, df.columns.get_loc("bullish_ob")] = True
    signal = generate_entry_signal(
        "USDJPY",
        df,
        TrendDirection.BULLISH,
        Timeframe.M1,
        use_smc_confluence=True,
        use_liquidity_volume=True,
    )
    assert signal.signal_type == SignalType.BUY
    assert "smc_confirmed" in signal.reason


def test_resolve_enabled_strategies_from_list():
    from chronoscalp.strategy.multi_timeframe import resolve_enabled_strategies

    smc, liq, scalp, news = resolve_enabled_strategies(
        {"enabled_strategies": ["smc_confluence", "liquidity_volume", "ultra_scalp"]}
    )
    assert smc and liq and scalp and not news
    smc2, liq2, scalp2, news2 = resolve_enabled_strategies({"enabled_strategies": []})
    assert not smc2 and not liq2 and not scalp2 and not news2


def test_ultra_scalp_impulse_buy():
    from chronoscalp.strategy.multi_timeframe import generate_ultra_scalp_signal

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    close = np.array([100.0, 100.1, 100.2, 100.3, 101.0])
    open_ = close - 0.4
    df = pd.DataFrame(
        {
            "open": open_,
            "high": close + 0.1,
            "low": open_ - 0.1,
            "close": close,
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 1.5),
            "rsi": np.full(n, 55.0),
            "macd": np.zeros(n),
            "histogram": np.zeros(n),
            "bb_upper": close + 2,
            "bb_lower": close - 2,
        },
        index=index,
    )
    signal = generate_ultra_scalp_signal(
        "XAUUSD",
        df,
        TrendDirection.BULLISH,
        Timeframe.S15,
        use_smc_confluence=False,
        use_liquidity_volume=False,
    )
    assert signal.signal_type == SignalType.BUY
    assert "ultra_scalp" in signal.reason
    assert signal.risk_reward_ratio >= 1.0


def test_ultra_scalp_allows_one_to_one_rr():
    from chronoscalp.strategy.multi_timeframe import generate_ultra_scalp_signal

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    close = np.array([100.0, 100.1, 100.2, 100.3, 101.0])
    open_ = close - 0.4
    df = pd.DataFrame(
        {
            "open": open_,
            "high": close + 0.1,
            "low": open_ - 0.1,
            "close": close,
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 1.5),
            "rsi": np.full(n, 55.0),
            "macd": np.zeros(n),
            "histogram": np.zeros(n),
            "bb_upper": close + 2,
            "bb_lower": close - 2,
        },
        index=index,
    )
    signal = generate_ultra_scalp_signal(
        "XAUUSD",
        df,
        TrendDirection.BULLISH,
        Timeframe.S15,
        use_smc_confluence=False,
        use_liquidity_volume=False,
        min_reward_risk_ratio=1.0,
        atr_stop_multiple=1.0,
        atr_target_multiple=1.0,
    )
    assert signal.signal_type == SignalType.BUY
    assert abs(signal.risk_reward_ratio - 1.0) < 1e-9


def test_ultra_scalp_trend_primary_allows_neutral_m1():
    from chronoscalp.strategy.multi_timeframe import ultra_scalp_trend

    assert (
        ultra_scalp_trend([TrendDirection.BULLISH, TrendDirection.NEUTRAL], mode="primary")
        == TrendDirection.BULLISH
    )
    assert (
        ultra_scalp_trend([TrendDirection.BULLISH, TrendDirection.BEARISH], mode="primary")
        == TrendDirection.NEUTRAL
    )
    assert (
        ultra_scalp_trend([TrendDirection.BULLISH, TrendDirection.NEUTRAL], mode="strict")
        == TrendDirection.NEUTRAL
    )


def test_ultra_scalp_skips_smc_when_confluence_not_required():
    """Regression: enabled SMC must not silently block every S15 impulse."""
    from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    close = np.array([100.0, 100.1, 100.2, 100.3, 101.0])
    open_ = close - 0.4
    trigger = pd.DataFrame(
        {
            "open": open_,
            "high": close + 0.1,
            "low": open_ - 0.1,
            "close": close,
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 1.2),
            "rsi": np.full(n, 55.0),
            "macd": np.zeros(n),
            "histogram": np.zeros(n),
            "bb_upper": close + 2,
            "bb_lower": close - 2,
            "bullish_ob": False,
            "fvg_bullish": False,
            "liquidity_sweep_low": False,
            "liquidity_sweep_low_vol": False,
        },
        index=index,
    )
    # Trending M5 (primary) + neutral-looking M1 is enough in primary mode.
    m5 = _trending_df(direction="up")
    # Force M1 last bars toward flat/neutral —
    # evaluate uses determine_trend; use a flat frame for M1.
    flat_close = np.full(80, 100.0)
    m1_flat = enrich_with_indicators(
        pd.DataFrame(
            {
                "open": flat_close,
                "high": flat_close + 0.05,
                "low": flat_close - 0.05,
                "close": flat_close,
            },
            index=pd.date_range("2026-01-01", periods=80, freq="min", tz="UTC"),
        ),
        ema_period=50,
    )
    strategy = MultiTimeframeStrategy(
        {
            "trend_engine": "ema_rsi",
            "enabled_strategies": ["smc_confluence", "liquidity_volume", "ultra_scalp"],
            "ultra_scalp": {
                "require_confluence": False,
                "trend_mode": "primary",
                "rvol_min": 1.05,
                "impulse_body_atr_multiple": 0.35,
                "min_reward_risk_ratio": 1.0,
                "atr_stop_multiple": 1.0,
                "atr_target_multiple": 1.0,
            },
            "min_signal_confidence": 0.0,
        },
        {"ema_period_trend": 50},
    )
    signal = strategy.evaluate(
        "BTCUSD",
        {Timeframe.M5: m5, Timeframe.M1: m1_flat, Timeframe.S15: trigger},
        higher_timeframes=[Timeframe.M5, Timeframe.M1],
        trigger_timeframe=Timeframe.S15,
        ignore_confidence_gate=True,
    )
    assert signal.signal_type == SignalType.BUY
    assert "ultra_scalp" in signal.reason


def test_ultra_scalp_reports_weak_impulse_reason():
    from chronoscalp.strategy.multi_timeframe import generate_ultra_scalp_signal

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    close = np.array([100.0, 100.1, 100.2, 100.3, 100.35])
    open_ = close - 0.01  # tiny body vs atr=0.5
    df = pd.DataFrame(
        {
            "open": open_,
            "high": close + 0.1,
            "low": open_ - 0.1,
            "close": close,
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 2.0),
        },
        index=index,
    )
    signal = generate_ultra_scalp_signal(
        "ETHUSD",
        df,
        TrendDirection.BULLISH,
        Timeframe.S15,
        impulse_body_atr_multiple=0.35,
    )
    assert signal.signal_type == SignalType.NONE
    assert signal.reason == "weak_impulse"


def test_ultra_scalp_v3_cost_aware_passes_risk_manager():
    """Regression: live BTC/EURJPY rejects from sub-spread + commission."""
    from chronoscalp.risk.position_sizing import RiskManager
    from chronoscalp.strategy.entry_trigger import generate_ultra_scalp_v3

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    # Strong impulse body vs ATR; close rising so candle_dir passes.
    close = np.array([64900.0, 64920.0, 64940.0, 64960.0, 65000.0])
    open_ = close - 30.0
    df = pd.DataFrame(
        {
            "open": open_,
            "high": close + 5.0,
            "low": open_ - 5.0,
            "close": close,
            "atr": np.full(n, 25.0),
            "rvol": np.full(n, 1.5),
        },
        index=index,
    )
    btc_spec = {
        "pip_size": 1.0,
        "contract_size": 1,
        "min_lot": 0.01,
        "lot_step": 0.01,
        "max_lot": 10,
        "pip_value_per_lot": 1.0,
        "typical_spread_pips": 20,
        "commission_pct_notional": 0.0012,
    }
    signal = generate_ultra_scalp_v3(
        "BTCUSD",
        df,
        TrendDirection.BULLISH,
        Timeframe.S15,
        atr_stop_multiple=1.0,
        atr_target_multiple=1.0,
        rvol_min=1.2,
        impulse_body_atr_multiple=0.35,
        symbol_spec=btc_spec,
        spread_pips=20.0,
        cost_aware_geometry=True,
    )
    assert signal.signal_type == SignalType.BUY
    assert abs(signal.entry_price - signal.stop_loss) >= 40.0
    rm = RiskManager(
        risk_cfg={
            "min_reward_risk_ratio": 1.5,
            "max_daily_loss_pct": 99,
            "active_risk_per_trade_pct": 1.0,
        },
        spread_cfg={"enabled": False},
        symbols_cfg={"BTCUSD": btc_spec},
        starting_equity=10_000,
    )
    assert rm.validate_signal(signal, current_spread_pips=20.0, min_reward_risk_ratio=1.0)


def test_ultra_scalp_v3_reports_uneconomic_when_caps_hit():
    from chronoscalp.strategy.entry_trigger import generate_ultra_scalp_v3

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    close = np.array([64900.0, 64920.0, 64940.0, 64960.0, 65000.0])
    open_ = close - 8.0
    df = pd.DataFrame(
        {
            "open": open_,
            "high": close + 1.0,
            "low": open_ - 1.0,
            "close": close,
            "atr": np.full(n, 5.0),
            "rvol": np.full(n, 2.0),
        },
        index=index,
    )
    signal = generate_ultra_scalp_v3(
        "BTCUSD",
        df,
        TrendDirection.BULLISH,
        Timeframe.S15,
        atr_stop_multiple=1.0,
        atr_target_multiple=1.0,
        impulse_body_atr_multiple=0.35,
        symbol_spec={
            "pip_size": 1.0,
            "contract_size": 1,
            "pip_value_per_lot": 1.0,
            "typical_spread_pips": 20,
            "commission_pct_notional": 0.0012,
        },
        max_stop_atr_multiple=2.0,
        max_target_atr_multiple=2.0,
    )
    assert signal.signal_type == SignalType.NONE
    assert signal.reason == "uneconomic_costs"


def test_strategies_run_independently_not_as_fallback(monkeypatch):
    """Scalp and institutional evaluate in parallel; best R:R wins (no chain)."""
    from chronoscalp.strategy import entry_trigger
    from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy, pick_best_signal
    from chronoscalp.utils.types import Signal

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    close = np.linspace(100.0, 100.4, n)
    scalp_df = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 2.0),
        },
        index=index,
    )
    m1 = enrich_with_indicators(
        pd.DataFrame(
            {
                "open": np.linspace(100, 101, 80),
                "high": np.linspace(100.2, 101.2, 80),
                "low": np.linspace(99.8, 100.8, 80),
                "close": np.linspace(100, 101, 80),
            },
            index=pd.date_range("2026-01-01", periods=80, freq="min", tz="UTC"),
        ),
        ema_period=50,
    )
    m5 = _trending_df(direction="up")

    def _fake_scalp(*_a, **_k):
        return Signal(
            symbol="EURUSD",
            signal_type=SignalType.BUY,
            timestamp=index[-1].to_pydatetime(),
            entry_price=101.0,
            stop_loss=100.5,  # R:R = 1.0
            take_profit=101.5,
            timeframe=Timeframe.S15,
            reason="ultra_scalp_v3,trend=bullish",
            confidence=0.7,
        )

    def _fake_inst(*_a, **_k):
        return Signal(
            symbol="EURUSD",
            signal_type=SignalType.BUY,
            timestamp=index[-1].to_pydatetime(),
            entry_price=101.0,
            stop_loss=100.0,  # R:R = 1.5 — should win
            take_profit=102.5,
            timeframe=Timeframe.M1,
            reason="institutional_entry,trend=bullish",
            confidence=0.6,
        )

    monkeypatch.setattr(entry_trigger, "generate_ultra_scalp_v3", _fake_scalp)
    monkeypatch.setattr(entry_trigger, "generate_institutional_entry", _fake_inst)

    strategy = MultiTimeframeStrategy(
        {
            "trend_engine": "ema_rsi",
            "entry_engine": "institutional",
            "enabled_strategies": ["smc_confluence", "liquidity_volume", "ultra_scalp"],
            "ultra_scalp": {"trend_mode": "primary", "rvol_min": 1.2},
            "min_signal_confidence": 0.0,
        },
        {"ema_period_trend": 50},
    )
    signal = strategy.evaluate(
        "EURUSD",
        {Timeframe.M5: m5, Timeframe.M1: m1, Timeframe.S15: scalp_df},
        higher_timeframes=[Timeframe.M5, Timeframe.M1],
        trigger_timeframe=Timeframe.S15,
        ignore_confidence_gate=True,
        run_scalp=True,
        run_institutional=True,
    )
    assert signal.signal_type == SignalType.BUY
    assert "institutional_entry" in signal.reason
    assert signal.risk_reward_ratio == pytest.approx(1.5)

    # Institutional alone still works when only its bar is due.
    only_inst = strategy.evaluate(
        "EURUSD",
        {Timeframe.M5: m5, Timeframe.M1: m1, Timeframe.S15: scalp_df},
        higher_timeframes=[Timeframe.M5, Timeframe.M1],
        trigger_timeframe=Timeframe.S15,
        ignore_confidence_gate=True,
        run_scalp=False,
        run_institutional=True,
    )
    assert "institutional_entry" in only_inst.reason

    # Scalp alone still works when only S15 bar is due.
    only_scalp = strategy.evaluate(
        "EURUSD",
        {Timeframe.M5: m5, Timeframe.M1: m1, Timeframe.S15: scalp_df},
        higher_timeframes=[Timeframe.M5, Timeframe.M1],
        trigger_timeframe=Timeframe.S15,
        ignore_confidence_gate=True,
        run_scalp=True,
        run_institutional=False,
    )
    assert "ultra_scalp" in only_scalp.reason

    chosen = pick_best_signal([_fake_scalp(), _fake_inst()])
    assert chosen is not None
    assert "institutional_entry" in chosen.reason


def test_institutional_still_runs_when_scalp_quiet(monkeypatch):
    """Quiet S15 must not prevent M1 institutional from being evaluated."""
    from chronoscalp.strategy import entry_trigger
    from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy
    from chronoscalp.utils.types import Signal

    n = 5
    index = pd.date_range("2026-01-01", periods=n, freq="15s", tz="UTC")
    close = np.linspace(100.0, 100.4, n)
    scalp_df = pd.DataFrame(
        {
            "open": close - 0.01,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "atr": np.full(n, 0.5),
            "rvol": np.full(n, 0.5),
        },
        index=index,
    )
    m1 = enrich_with_indicators(
        pd.DataFrame(
            {
                "open": np.linspace(100, 101, 80),
                "high": np.linspace(100.2, 101.2, 80),
                "low": np.linspace(99.8, 100.8, 80),
                "close": np.linspace(100, 101, 80),
            },
            index=pd.date_range("2026-01-01", periods=80, freq="min", tz="UTC"),
        ),
        ema_period=50,
    )
    m5 = _trending_df(direction="up")
    scalp_calls = {"n": 0}
    inst_calls = {"n": 0}

    def _fake_scalp(*_a, **_k):
        scalp_calls["n"] += 1
        return Signal(
            symbol="EURUSD",
            signal_type=SignalType.NONE,
            timestamp=index[-1].to_pydatetime(),
            entry_price=0.0,
            stop_loss=0.0,
            take_profit=0.0,
            timeframe=Timeframe.S15,
            reason="low_rvol",
        )

    def _fake_inst(*_a, **_k):
        inst_calls["n"] += 1
        return Signal(
            symbol="EURUSD",
            signal_type=SignalType.BUY,
            timestamp=index[-1].to_pydatetime(),
            entry_price=101.0,
            stop_loss=100.0,
            take_profit=102.5,
            timeframe=Timeframe.M1,
            reason="institutional_entry,trend=bullish",
            confidence=0.9,
        )

    monkeypatch.setattr(entry_trigger, "generate_ultra_scalp_v3", _fake_scalp)
    monkeypatch.setattr(entry_trigger, "generate_institutional_entry", _fake_inst)

    strategy = MultiTimeframeStrategy(
        {
            "trend_engine": "ema_rsi",
            "entry_engine": "institutional",
            "enabled_strategies": ["smc_confluence", "liquidity_volume", "ultra_scalp"],
            "ultra_scalp": {"trend_mode": "primary"},
            "min_signal_confidence": 0.0,
        },
        {"ema_period_trend": 50},
    )
    signal = strategy.evaluate(
        "EURUSD",
        {Timeframe.M5: m5, Timeframe.M1: m1, Timeframe.S15: scalp_df},
        higher_timeframes=[Timeframe.M5, Timeframe.M1],
        trigger_timeframe=Timeframe.S15,
        ignore_confidence_gate=True,
    )
    assert scalp_calls["n"] == 1 and inst_calls["n"] == 1
    assert signal.signal_type == SignalType.BUY
    assert "institutional_entry" in signal.reason
