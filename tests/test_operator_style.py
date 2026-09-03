from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy
from chronoscalp.strategy.operator_style import (
    evaluate_operator_style,
    generate_operator_style_signal,
    in_operator_session,
)
from chronoscalp.utils.types import SignalType, Timeframe, TrendDirection

_GEO = {
    "require_session": False,
    "min_adx": 25.0,
    "fade_rsi": 70.0,
    "fade_stoch": 80.0,
    "fade_require_both": True,
    "pullback_stoch": 25.0,
    "stop_atr_source": "htf",
    "stop_atr_htf_index": 0,
    "stop_buffer_atr": 0.20,
    "min_stop_atr": 0.80,
    "max_stop_atr": 2.00,
    "min_stop_spread_multiple": 2.0,
    "max_cost_fraction_of_risk": 0.15,
    "reward_risk_ratio": 1.50,
}


def _tape(
    *,
    adx: float,
    stoch_k: float,
    rsi: float,
    close: float = 2000.0,
    ema20: float = 1990.0,
    atr: float = 4.0,
    range_size: float = 2.0,
    n: int = 40,
    freq: str = "5min",
    start: str = "2026-09-01 09:30",
) -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    price = np.full(n, close)
    return pd.DataFrame(
        {
            "open": price,
            "high": price + range_size,
            "low": price - range_size,
            "close": price,
            "adx": np.full(n, adx),
            "stoch_k": np.full(n, stoch_k),
            "rsi": np.full(n, rsi),
            "ema_20": np.full(n, ema20),
            "atr": np.full(n, atr),
        },
        index=index,
    )


def _bullish_last(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    last = out.index[-1]
    out.loc[last, "open"] = float(out.loc[last, "close"]) - 0.5
    return out


def test_weak_adx_is_a_hard_skip() -> None:
    verdict = evaluate_operator_style(
        _tape(adx=12.0, stoch_k=85.0, rsi=75.0),
        _tape(adx=12.0, stoch_k=85.0, rsi=75.0),
    )
    assert verdict.allow is False
    assert verdict.reason == "weak_adx"


def test_high_stoch_and_rsi_on_strong_adx_is_a_sell_fade() -> None:
    m15 = _tape(adx=40.0, stoch_k=60.0, rsi=72.0, close=4485.0, ema20=4446.0)
    m5 = _tape(adx=40.0, stoch_k=86.0, rsi=78.0, close=4485.0, ema20=4465.0)
    verdict = evaluate_operator_style(m15, m5)
    assert verdict.allow is True
    assert verdict.setup == "fade_extension"
    assert verdict.direction == TrendDirection.BEARISH


def test_gold_fade_requires_stoch_and_rsi() -> None:
    m15 = _tape(adx=40.0, stoch_k=60.0, rsi=55.0, close=4485.0, ema20=4446.0)
    m5 = _tape(adx=40.0, stoch_k=86.0, rsi=55.0, close=4485.0, ema20=4465.0)
    verdict = evaluate_operator_style(m15, m5, config={"fade_require_both": True})
    assert verdict.allow is False
    assert verdict.reason == "no_style_setup"


def test_oversold_stoch_under_htf_ema_is_a_buy_pullback() -> None:
    m15 = _tape(adx=32.0, stoch_k=40.0, rsi=55.0, close=4469.0, ema20=4455.0)
    m5 = _tape(adx=28.0, stoch_k=21.0, rsi=49.0, close=4465.0, ema20=4469.0)
    verdict = evaluate_operator_style(m15, m5)
    assert verdict.allow is True
    assert verdict.setup == "htf_pullback"
    assert verdict.direction == TrendDirection.BULLISH


def test_strong_adx_without_extreme_or_pullback_is_not_a_setup() -> None:
    tape = _tape(adx=35.0, stoch_k=50.0, rsi=55.0, close=2000.0, ema20=1998.0)
    verdict = evaluate_operator_style(tape, tape)
    assert verdict.allow is False
    assert verdict.reason == "no_style_setup"


def test_eur_fade_allows_stoch_without_rsi_extreme() -> None:
    m15 = _tape(
        adx=22.0,
        stoch_k=88.0,
        rsi=62.0,
        close=1.16,
        ema20=1.159,
        atr=0.0002,
        range_size=0.0004,
    )
    m5 = _tape(
        adx=18.0,
        stoch_k=92.0,
        rsi=66.0,
        close=1.16,
        ema20=1.159,
        atr=0.0002,
        range_size=0.0004,
    )
    verdict = evaluate_operator_style(
        m15,
        m5,
        config={
            "min_adx": 20.0,
            "fade_require_both": False,
            "allowed_setups": ["fade_extension", "htf_pullback"],
        },
    )
    assert verdict.setup == "fade_extension"
    assert verdict.direction == TrendDirection.BEARISH


def test_rollover_sells_when_m15_is_stretched_and_m5_has_dumped() -> None:
    m15 = _tape(adx=38.0, stoch_k=82.0, rsi=72.0, close=4485.0, ema20=4446.0)
    m5 = _tape(adx=36.0, stoch_k=11.0, rsi=48.0, close=4470.0, ema20=4465.0)
    verdict = evaluate_operator_style(m15, m5)
    assert verdict.allow is True
    assert verdict.setup == "fade_rollover"
    assert verdict.direction == TrendDirection.BEARISH


def test_iran_afternoon_session_window() -> None:
    cfg = {
        "require_session": True,
        "session_timezone": "Asia/Tehran",
        "session_start": "13:00",
        "session_end": "18:30",
    }
    inside = datetime(2026, 9, 1, 9, 30, tzinfo=UTC)  # 13:00 Tehran
    outside = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)  # 11:30 Tehran
    assert in_operator_session(inside, cfg) is True
    assert in_operator_session(outside, cfg) is False


def test_generate_fade_sell_has_cost_aware_geometry() -> None:
    m15 = _tape(adx=40.0, stoch_k=60.0, rsi=72.0, close=4485.0, ema20=4446.0)
    m5 = _tape(adx=40.0, stoch_k=86.0, rsi=78.0, close=4485.0, ema20=4465.0)
    signal = generate_operator_style_signal(
        "XAUUSD",
        m5,
        [m15],
        config=_GEO,
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert signal.signal_type == SignalType.SELL
    assert signal.strategy == "operator_style"
    assert "fade_extension" in signal.reason
    assert signal.risk_reward_ratio >= 1.5
    assert signal.stop_loss > signal.entry_price
    assert signal.take_profit < signal.entry_price


def test_generate_skips_outside_iran_session() -> None:
    m15 = _tape(
        adx=40.0,
        stoch_k=60.0,
        rsi=72.0,
        close=4485.0,
        ema20=4446.0,
        start="2026-09-01 06:00",
    )
    m5 = _tape(
        adx=40.0,
        stoch_k=86.0,
        rsi=78.0,
        close=4485.0,
        ema20=4465.0,
        start="2026-09-01 06:00",
    )
    cfg = dict(_GEO)
    cfg["require_session"] = True
    signal = generate_operator_style_signal("XAUUSD", m5, [m15], config=cfg)
    assert signal.signal_type == SignalType.NONE
    assert signal.reason == "operator_style:outside_session"


def test_generate_pullback_requires_a_bounce_candle() -> None:
    m15 = _tape(adx=32.0, stoch_k=40.0, rsi=55.0, close=4469.0, ema20=4455.0)
    m5 = _tape(adx=28.0, stoch_k=21.0, rsi=49.0, close=4465.0, ema20=4469.0)
    rejected = generate_operator_style_signal("XAUUSD", m5, [m15], config=_GEO)
    assert rejected.signal_type == SignalType.NONE
    assert rejected.reason == "operator_style:no_confirmation"
    accepted = generate_operator_style_signal(
        "XAUUSD",
        _bullish_last(m5),
        [m15],
        config=_GEO,
        symbol_spec={"pip_size": 0.01, "typical_spread_pips": 20},
        spread_pips=20,
    )
    assert accepted.signal_type == SignalType.BUY
    assert "htf_pullback" in accepted.reason
    assert accepted.risk_reward_ratio >= 1.5


def test_generate_eur_stoch_fade_with_loose_rsi() -> None:
    m15 = _tape(
        adx=22.0,
        stoch_k=88.0,
        rsi=62.0,
        close=1.16,
        ema20=1.159,
        atr=0.0020,
        range_size=0.0015,
    )
    m5 = _tape(
        adx=18.0,
        stoch_k=92.0,
        rsi=62.0,
        close=1.16,
        ema20=1.159,
        atr=0.0020,
        range_size=0.0015,
    )
    cfg = dict(_GEO)
    cfg.update(
        {
            "min_adx": 20.0,
            "fade_require_both": False,
            "min_stop_atr": 1.50,
            "max_stop_atr": 3.50,
        }
    )
    signal = generate_operator_style_signal(
        "EURUSD",
        m5,
        [m15],
        config=cfg,
        symbol_spec={"pip_size": 0.0001, "typical_spread_pips": 1.0},
        spread_pips=1.0,
    )
    assert signal.signal_type == SignalType.SELL
    assert signal.risk_reward_ratio >= 1.5


def test_operator_style_only_does_not_fire_legacy_institutional() -> None:
    strategy = MultiTimeframeStrategy(
        {
            "enabled_strategies": ["operator_style"],
            "operator_style": {**_GEO, "min_adx": 99.0},
            "min_signal_confidence": 0,
        },
        {"XAUUSD": {"pip_size": 0.01, "typical_spread_pips": 20}},
    )
    tape = _tape(adx=40.0, stoch_k=86.0, rsi=78.0)
    candidates, skips = strategy._collect_candidates(
        "XAUUSD",
        {Timeframe.M15: tape, Timeframe.M5: tape, Timeframe.M1: tape},
        [Timeframe.M15, Timeframe.M5],
        Timeframe.M1,
        ignore_confidence_gate=True,
        spread_pips=20,
        run_scalp=False,
        run_institutional=True,
    )
    assert candidates == []
    assert any("weak_adx" in item for item in skips)
    assert not any(
        item.startswith("institutional") or item.startswith("smc_confluence") for item in skips
    )


def test_collect_emits_an_operator_style_fade() -> None:
    strategy = MultiTimeframeStrategy(
        {
            "enabled_strategies": ["operator_style"],
            "operator_style": _GEO,
            "min_signal_confidence": 0,
        },
        {"XAUUSD": {"pip_size": 0.01, "typical_spread_pips": 20}},
    )
    m15 = _tape(adx=40.0, stoch_k=60.0, rsi=72.0, close=4485.0, ema20=4446.0)
    m5 = _tape(adx=40.0, stoch_k=86.0, rsi=78.0, close=4485.0, ema20=4465.0)
    candidates, _skips = strategy._collect_candidates(
        "XAUUSD",
        {Timeframe.M15: m15, Timeframe.M5: m5, Timeframe.M1: m5},
        [Timeframe.M15, Timeframe.M5],
        Timeframe.M1,
        ignore_confidence_gate=True,
        spread_pips=20,
        run_scalp=False,
        run_institutional=True,
    )
    assert len(candidates) == 1
    assert candidates[0].strategy == "operator_style"
    assert candidates[0].signal_type == SignalType.SELL
