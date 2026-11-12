"""Quant validation: walk-forward, CPCV, DSR, and PBO reports.

All headline metrics are **net of costs**. Do not publish gross-of-cost claims.
"""

from __future__ import annotations

from chronoscalp.validation.cpcv import cpcv_path_splits
from chronoscalp.validation.metrics import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)
from chronoscalp.validation.reports import StrategyValidationReport, write_report
from chronoscalp.validation.walkforward import purged_walk_forward_folds

__all__ = [
    "StrategyValidationReport",
    "cpcv_path_splits",
    "deflated_sharpe_ratio",
    "probability_of_backtest_overfitting",
    "purged_walk_forward_folds",
    "sharpe_ratio",
    "write_report",
]
