from __future__ import annotations

import numpy as np
import pandas as pd

from chronoscalp.strategy.operator_style import evaluate_operator_style
from chronoscalp.utils.types import TrendDirection


def _tape(
    *,
    adx: float,
    stoch_k: float,
    rsi: float,
    close: float = 2000.0,
    ema20: float = 1990.0,
    n: int = 40,
) -> pd.DataFrame:
    index = pd.date_range("2026-09-01", periods=n, freq="15min", tz="UTC")
    price = np.full(n, close)
    return pd.DataFrame(
        {
            "open": price,
            "high": price + 1.0,
            "low": price - 1.0,
            "close": price,
            "adx": np.full(n, adx),
            "stoch_k": np.full(n, stoch_k),
            "rsi": np.full(n, rsi),
            "ema_20": np.full(n, ema20),
        },
        index=index,
    )


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


def test_oversold_stoch_under_htf_ema_is_a_buy_pullback() -> None:
    m15 = _tape(adx=32.0, stoch_k=40.0, rsi=55.0, close=4469.0, ema20=4455.0)
    m5 = _tape(adx=28.0, stoch_k=21.0, rsi=49.0, close=4465.0, ema20=4469.0)
    verdict = evaluate_operator_style(m15, m5)
    assert verdict.allow is True
    assert verdict.setup == "htf_pullback"
    assert verdict.direction == TrendDirection.BULLISH


def test_strong_adx_without_extreme_or_pullback_leaves_sweep_path_open() -> None:
    tape = _tape(adx=35.0, stoch_k=50.0, rsi=55.0, close=2000.0, ema20=1998.0)
    verdict = evaluate_operator_style(tape, tape)
    assert verdict.allow is False
    assert verdict.reason == "no_style_setup"


def test_eur_fade_only_config_ignores_sweep_names() -> None:
    m15 = _tape(adx=22.0, stoch_k=88.0, rsi=62.0, close=1.16, ema20=1.159)
    m5 = _tape(adx=18.0, stoch_k=92.0, rsi=66.0, close=1.16, ema20=1.159)
    verdict = evaluate_operator_style(
        m15,
        m5,
        config={"min_adx": 20.0, "allowed_setups": ["fade_extension", "htf_pullback"]},
    )
    assert verdict.setup == "fade_extension"
    assert verdict.direction == TrendDirection.BEARISH
