from __future__ import annotations

import pytest

from chronoscalp.backtest.optimizer import (
    clone_settings_with_indicators,
    iter_param_combinations,
    score_backtest,
)


def test_iter_param_combinations_expands_grid():
    combos = iter_param_combinations({"a": [1, 2], "b": [10]})
    assert combos == [{"a": 1, "b": 10}, {"a": 2, "b": 10}]


def test_clone_settings_overrides_indicators():
    from chronoscalp.config import Settings

    settings = Settings()
    original_ema = settings.indicators["ema_period_trend"]
    cloned = clone_settings_with_indicators(settings, {"ema_period_trend": 99})
    assert cloned.indicators["ema_period_trend"] == 99
    assert settings.indicators["ema_period_trend"] == original_ema


def test_score_backtest_profit_factor_handles_inf():
    from chronoscalp.backtest.engine import BacktestResult

    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000, final_equity=11_000)
    # No losing trades -> inf profit factor
    assert score_backtest(result, "profit_factor") == 999.0


def test_score_backtest_return_pct():
    from chronoscalp.backtest.engine import BacktestResult

    result = BacktestResult(symbol="XAUUSD", starting_equity=10_000, final_equity=10_500)
    assert score_backtest(result, "return_pct") == pytest.approx(5.0)
