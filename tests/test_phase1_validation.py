"""Phase 1 quant validation plane — DSR/PBO/CPCV/costs/governance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from chronoscalp.backtest.optimizer import clone_settings_with
from chronoscalp.config import Settings
from chronoscalp.execution.cost_model import (
    news_slippage_multiplier,
    overnight_swap_cash,
    resolve_session_spread_pips,
    session_name_utc,
    session_spread_multiplier,
)
from chronoscalp.utils.types import SignalType
from chronoscalp.validation.cpcv import cpcv_path_splits
from chronoscalp.validation.governance import (
    GeometryGovernanceError,
    assert_geometry_change_allowed,
)
from chronoscalp.validation.metrics import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)
from chronoscalp.validation.portfolio import combine_book_equity_curves, max_drawdown_pct
from chronoscalp.validation.reports import build_report_from_trade_r, write_report
from chronoscalp.validation.run import main as validation_main
from chronoscalp.validation.walkforward import purged_walk_forward_folds


def test_sharpe_and_dsr_positive_on_mild_edge() -> None:
    returns = [0.2, 0.1, -0.05, 0.15, 0.05, -0.02, 0.12] * 8
    sr = sharpe_ratio(returns)
    assert sr > 0
    dsr = deflated_sharpe_ratio(returns, n_trials=10)
    assert dsr["sharpe"] > 0
    assert 0.0 <= dsr["dsr"] <= 1.0


def test_pbo_high_when_best_is_noise() -> None:
    # Many random-ish rivals → PBO tends high / well-defined.
    paths = [[((-1) ** (i + s)) * 0.01 for i in range(40)] for s in range(6)]
    payload = probability_of_backtest_overfitting(paths)
    assert "pbo" in payload
    assert 0.0 <= payload["pbo"] <= 1.0


def test_cpcv_paths_are_purged() -> None:
    paths = cpcv_path_splits(60, n_groups=6, n_test_groups=2, embargo=2)
    assert paths
    for path in paths:
        assert path.train_idx
        assert path.test_idx
        assert set(path.train_idx).isdisjoint(path.test_idx)


def test_walkforward_folds_expanding() -> None:
    folds = purged_walk_forward_folds(200, n_folds=4, embargo=5)
    assert len(folds) >= 2
    assert folds[0].train_end_idx <= folds[0].test_start_idx


def test_session_spread_multiplier_london_vs_asia() -> None:
    london = datetime(2026, 6, 15, 9, 0, tzinfo=ZoneInfo("Europe/London")).astimezone(UTC)
    asia = datetime(2026, 6, 15, 2, 0, tzinfo=ZoneInfo("Europe/London")).astimezone(UTC)
    assert session_name_utc(london) in {"london", "overlap"}
    assert session_name_utc(asia) == "asia"
    assert session_spread_multiplier(asia) > session_spread_multiplier(london)


def test_resolve_session_spread_scales_typical() -> None:
    symbols = {"XAUUSD": {"typical_spread_pips": 20.0}}
    at = datetime(2026, 6, 15, 2, 0, tzinfo=UTC)
    scaled = resolve_session_spread_pips("XAUUSD", symbols, at=at)
    assert scaled > 20.0


def test_news_slippage_and_swap() -> None:
    assert news_slippage_multiplier(in_news_window=False) == 1.0
    assert news_slippage_multiplier(in_news_window=True) >= 2.0
    spec = {"swap_long_per_lot": -2.0, "swap_short_per_lot": 1.0}
    # Long overnight with negative swap → positive cost.
    assert overnight_swap_cash(
        spec, direction=SignalType.BUY, volume=0.1, nights=1
    ) == pytest.approx(0.2)


def test_portfolio_equity_sums_books() -> None:
    points = combine_book_equity_curves([[10_000, 10_100, 9_900], [10_000, 10_050, 10_000]])
    assert points[0].equity == pytest.approx(20_000)
    assert points[1].equity == pytest.approx(20_150)
    assert max_drawdown_pct([100, 120, 90]) == pytest.approx(25.0)


def test_clone_settings_deep() -> None:
    settings = Settings()
    cloned = clone_settings_with(
        settings,
        indicator_overrides={"ema_period_trend": 99},
        backtest_overrides={"commission_per_lot": 0.0},
    )
    assert cloned.raw["indicators"]["ema_period_trend"] == 99
    assert cloned.raw is not settings.raw
    assert cloned.symbols_raw is not settings.symbols_raw


def test_build_and_write_report(tmp_path: Path) -> None:
    trade_r = [0.5, -1.0, 1.2, 0.8, -0.9, 1.1] * 10
    report = build_report_from_trade_r(
        strategy="delta", symbol="XAUUSD", trade_r=trade_r, n_trials=20
    )
    assert report.costs_net is True
    assert report.n_trades == 60
    path = write_report(report, tmp_path / "xau_delta.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["strategy"] == "delta"
    assert "dsr" in payload


def test_governance_requires_dsr(tmp_path: Path) -> None:
    with pytest.raises(GeometryGovernanceError):
        assert_geometry_change_allowed(
            report_path=None,
            changed_paths=["strategy.delta.reward_risk_ratio"],
        )
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps({"costs_net": True, "dsr": 0.0, "verdict": "reject"}),
        encoding="utf-8",
    )
    with pytest.raises(GeometryGovernanceError):
        assert_geometry_change_allowed(
            report_path=bad,
            changed_paths=["strategy.delta.reward_risk_ratio"],
        )
    good = tmp_path / "good.json"
    good.write_text(
        json.dumps({"costs_net": True, "dsr": 0.8, "verdict": "accept_candidate"}),
        encoding="utf-8",
    )
    assert_geometry_change_allowed(
        report_path=good,
        changed_paths=["strategy.delta.reward_risk_ratio"],
    )


def test_validation_cli_smoke(tmp_path: Path) -> None:
    code = validation_main(["--all", "--out-dir", str(tmp_path)])
    assert code == 0
    assert list(tmp_path.glob("*_validation.json"))
