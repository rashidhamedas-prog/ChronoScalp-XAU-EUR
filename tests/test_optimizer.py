from __future__ import annotations

from datetime import UTC

import pandas as pd

from chronoscalp.backtest.optimizer import _fold_windows


def test_fold_windows_preserve_utc_aware_bounds():
    """UTC DatetimeIndex folds must yield tz-aware bounds for run_backtest."""
    index = pd.date_range("2026-01-01", periods=100, freq="1h", tz="UTC")
    windows = _fold_windows(index, n_folds=2, train_ratio=0.7)
    assert windows
    for train_start, train_end, test_start, test_end in windows:
        for bound in (train_start, train_end, test_start, test_end):
            assert bound.tzinfo is not None
            assert bound.tzinfo.utcoffset(bound) == UTC.utcoffset(bound)
