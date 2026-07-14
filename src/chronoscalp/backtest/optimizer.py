"""Parameter grid-search and walk-forward optimization for backtests.

Results are returned as JSON-serializable reports — optimized parameters are
never written back into ``config/settings.yaml`` automatically (see
docs/ROADMAP.md Phase 5 overfitting warning).
"""

from __future__ import annotations

import copy
import itertools
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from chronoscalp.backtest.engine import BacktestResult, run_backtest
from chronoscalp.config import Settings
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.logging_setup import logger
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.utils.types import Timeframe

ScoreFn = Callable[[BacktestResult], float]


@dataclass(frozen=True)
class OptimizationCandidate:
    """One parameter combination and its backtest outcome."""

    params: dict[str, Any]
    score: float
    summary: dict[str, Any]


@dataclass
class GridSearchResult:
    symbol: str
    metric: str
    candidates: list[OptimizationCandidate] = field(default_factory=list)

    @property
    def best(self) -> OptimizationCandidate | None:
        if not self.candidates:
            return None
        return max(self.candidates, key=lambda c: c.score)


@dataclass(frozen=True)
class WalkForwardFoldResult:
    fold: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_params: dict[str, Any]
    in_sample_score: float
    out_of_sample_summary: dict[str, Any]


@dataclass
class WalkForwardResult:
    symbol: str
    metric: str
    folds: list[WalkForwardFoldResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        oos_returns = [f.out_of_sample_summary.get("return_pct", 0.0) for f in self.folds]
        return {
            "symbol": self.symbol,
            "metric": self.metric,
            "fold_count": len(self.folds),
            "avg_oos_return_pct": (
                round(sum(oos_returns) / len(oos_returns), 2) if oos_returns else 0.0
            ),
            "folds": [
                {
                    "fold": f.fold,
                    "train_start": f.train_start.isoformat(),
                    "train_end": f.train_end.isoformat(),
                    "test_start": f.test_start.isoformat(),
                    "test_end": f.test_end.isoformat(),
                    "best_params": f.best_params,
                    "in_sample_score": f.in_sample_score,
                    "out_of_sample": f.out_of_sample_summary,
                }
                for f in self.folds
            ],
        }


def clone_settings_with_indicators(
    settings: Settings, indicator_overrides: dict[str, Any]
) -> Settings:
    """Shallow clone of ``settings`` with overridden indicator parameters."""
    cloned = Settings.__new__(Settings)
    cloned.raw = copy.deepcopy(settings.raw)
    cloned.raw["indicators"] = {**settings.indicators, **indicator_overrides}
    cloned.symbols_raw = settings.symbols_raw
    cloned.secrets = settings.secrets
    return cloned


def enrich_data_by_timeframe(
    raw_by_tf: dict[Timeframe, pd.DataFrame],
    ind_cfg: dict[str, Any],
) -> dict[Timeframe, pd.DataFrame]:
    """Apply indicator + SMC enrichment using ``ind_cfg``."""
    result: dict[Timeframe, pd.DataFrame] = {}
    for tf, df in raw_by_tf.items():
        enriched = enrich_with_indicators(
            df,
            ema_period=ind_cfg.get("ema_period_trend", 50),
            rsi_period=ind_cfg.get("rsi_period", 14),
            bb_period=ind_cfg.get("bollinger_period", 20),
            bb_std=ind_cfg.get("bollinger_std_dev", 2.0),
            macd_fast=ind_cfg.get("macd_fast", 12),
            macd_slow=ind_cfg.get("macd_slow", 26),
            macd_signal=ind_cfg.get("macd_signal", 9),
            atr_period=ind_cfg.get("atr_period", 14),
        )
        result[tf] = enrich_with_smc(enriched)
    return result


def score_backtest(result: BacktestResult, metric: str) -> float:
    """Score a backtest for ranking parameter combinations."""
    if metric == "profit_factor":
        pf = result.profit_factor
        return pf if pf != float("inf") else 999.0
    if metric == "expectancy_r":
        return result.expectancy_r
    if metric == "return_pct":
        if not result.starting_equity:
            return 0.0
        return (result.final_equity / result.starting_equity - 1) * 100
    if metric == "win_rate":
        return result.win_rate
    raise ValueError(f"Unknown metric: {metric}")


def iter_param_combinations(grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
    """Expand a parameter grid into a list of override dicts."""
    if not grid:
        return [{}]
    keys = sorted(grid.keys())
    combos: list[dict[str, Any]] = []
    for values in itertools.product(*(grid[k] for k in keys)):
        combos.append(dict(zip(keys, values, strict=True)))
    return combos


def run_grid_search(
    symbol: str,
    raw_by_timeframe: dict[Timeframe, pd.DataFrame],
    settings: Settings,
    higher_timeframes: list[Timeframe],
    trigger_timeframe: Timeframe,
    param_grid: dict[str, list[Any]],
    metric: str = "profit_factor",
    start: datetime | None = None,
    end: datetime | None = None,
) -> GridSearchResult:
    """Exhaustive grid search over indicator parameters on one date range."""
    result = GridSearchResult(symbol=symbol, metric=metric)
    combos = iter_param_combinations(param_grid)

    for overrides in combos:
        tuned = clone_settings_with_indicators(settings, overrides)
        data = enrich_data_by_timeframe(raw_by_timeframe, tuned.indicators)
        bt = run_backtest(
            symbol=symbol,
            data_by_timeframe=data,
            higher_timeframes=higher_timeframes,
            trigger_timeframe=trigger_timeframe,
            settings=tuned,
            start=start,
            end=end,
        )
        score = score_backtest(bt, metric)
        result.candidates.append(
            OptimizationCandidate(params=overrides, score=round(score, 4), summary=bt.summary())
        )

    result.candidates.sort(key=lambda c: c.score, reverse=True)
    if result.best:
        logger.info(
            "Grid search best for {}: score={} params={}",
            symbol,
            result.best.score,
            result.best.params,
        )
    return result


def _fold_windows(
    index: pd.DatetimeIndex,
    n_folds: int,
    train_ratio: float,
) -> list[tuple[datetime, datetime, datetime, datetime]]:
    """Build rolling train/test windows over ``index``."""
    if n_folds < 1:
        raise ValueError("n_folds must be >= 1")
    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be between 0 and 1")

    start = index[0].to_pydatetime()
    end = index[-1].to_pydatetime()
    total = (end - start).total_seconds()
    fold_seconds = total / n_folds
    windows: list[tuple[datetime, datetime, datetime, datetime]] = []

    for i in range(n_folds):
        fold_start = start + timedelta(seconds=fold_seconds * i)
        fold_end = start + timedelta(seconds=fold_seconds * (i + 1))
        train_end = fold_start + timedelta(seconds=fold_seconds * train_ratio)
        if train_end >= fold_end:
            continue
        windows.append((fold_start, train_end, train_end, fold_end))
    return windows


def run_walk_forward(
    symbol: str,
    raw_by_timeframe: dict[Timeframe, pd.DataFrame],
    settings: Settings,
    higher_timeframes: list[Timeframe],
    trigger_timeframe: Timeframe,
    param_grid: dict[str, list[Any]],
    metric: str = "profit_factor",
    n_folds: int = 3,
    train_ratio: float = 0.7,
) -> WalkForwardResult:
    """Walk-forward optimization: fit on in-sample, validate on out-of-sample."""
    trigger_df = raw_by_timeframe[trigger_timeframe]
    windows = _fold_windows(trigger_df.index, n_folds=n_folds, train_ratio=train_ratio)
    wf = WalkForwardResult(symbol=symbol, metric=metric)

    for fold_idx, (train_start, train_end, test_start, test_end) in enumerate(windows, start=1):
        in_sample = run_grid_search(
            symbol=symbol,
            raw_by_timeframe=raw_by_timeframe,
            settings=settings,
            higher_timeframes=higher_timeframes,
            trigger_timeframe=trigger_timeframe,
            param_grid=param_grid,
            metric=metric,
            start=train_start,
            end=train_end,
        )
        best = in_sample.best
        if best is None:
            continue

        tuned = clone_settings_with_indicators(settings, best.params)
        data = enrich_data_by_timeframe(raw_by_timeframe, tuned.indicators)
        oos = run_backtest(
            symbol=symbol,
            data_by_timeframe=data,
            higher_timeframes=higher_timeframes,
            trigger_timeframe=trigger_timeframe,
            settings=tuned,
            start=test_start,
            end=test_end,
        )
        wf.folds.append(
            WalkForwardFoldResult(
                fold=fold_idx,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                best_params=best.params,
                in_sample_score=best.score,
                out_of_sample_summary=oos.summary(),
            )
        )

    logger.info("Walk-forward complete for {}: {} fold(s)", symbol, len(wf.folds))
    return wf
