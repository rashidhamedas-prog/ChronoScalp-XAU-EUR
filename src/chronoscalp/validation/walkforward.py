"""Purged walk-forward fold generator with embargo."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class WalkForwardFold:
    fold: int
    train_start_idx: int
    train_end_idx: int  # exclusive
    test_start_idx: int
    test_end_idx: int  # exclusive
    embargo: int


def purged_walk_forward_folds(
    n_samples: int,
    *,
    n_folds: int = 5,
    train_fraction: float = 0.7,
    embargo: int = 0,
    min_train: int = 30,
    min_test: int = 10,
) -> list[WalkForwardFold]:
    """Expanding purged walk-forward folds over a chronological index.

    Each fold grows the train window; the test window is the next contiguous
    block. ``embargo`` drops the last ``embargo`` train bars before the test
    start so overlapping label horizons cannot leak.
    """
    if n_samples < min_train + min_test:
        raise ValueError("Not enough samples for purged walk-forward")
    if n_folds < 1:
        raise ValueError("n_folds must be >= 1")
    if not 0.1 <= float(train_fraction) < 1.0:
        raise ValueError("train_fraction must be in [0.1, 1)")

    embargo_n = max(0, int(embargo))
    # Reserve the last (1 - train_fraction) * n as the total OOS pool, split
    # into n_folds contiguous test blocks.
    oos_pool = max(min_test * n_folds, int(round(n_samples * (1.0 - train_fraction))))
    oos_pool = min(oos_pool, n_samples - min_train)
    test_block = max(min_test, oos_pool // n_folds)
    folds: list[WalkForwardFold] = []
    for i in range(n_folds):
        test_start = n_samples - oos_pool + i * test_block
        test_end = n_samples if i == n_folds - 1 else test_start + test_block
        if test_end - test_start < min_test:
            continue
        train_end = max(min_train, test_start - embargo_n)
        if train_end < min_train:
            continue
        folds.append(
            WalkForwardFold(
                fold=i,
                train_start_idx=0,
                train_end_idx=train_end,
                test_start_idx=test_start,
                test_end_idx=test_end,
                embargo=embargo_n,
            )
        )
    if not folds:
        raise ValueError("Walk-forward produced no valid folds")
    return folds


def time_window_folds(
    timestamps: Sequence[datetime],
    *,
    train_days: int,
    test_days: int,
    step_days: int | None = None,
    embargo_bars: int = 0,
) -> list[WalkForwardFold]:
    """Index folds from calendar windows when a datetime index is available."""
    if len(timestamps) < 2:
        raise ValueError("Need timestamps for calendar walk-forward")
    step = timedelta(days=int(step_days if step_days is not None else test_days))
    train_td = timedelta(days=int(train_days))
    test_td = timedelta(days=int(test_days))
    start = timestamps[0]
    end = timestamps[-1]
    folds: list[WalkForwardFold] = []
    fold_i = 0
    cursor = start + train_td
    while cursor + test_td <= end:
        train_start_t = cursor - train_td
        test_end_t = cursor + test_td
        train_idx = [i for i, t in enumerate(timestamps) if train_start_t <= t < cursor]
        test_idx = [i for i, t in enumerate(timestamps) if cursor <= t < test_end_t]
        if len(train_idx) < 10 or len(test_idx) < 5:
            cursor += step
            continue
        train_end = max(train_idx) + 1 - max(0, int(embargo_bars))
        folds.append(
            WalkForwardFold(
                fold=fold_i,
                train_start_idx=min(train_idx),
                train_end_idx=max(train_end, min(train_idx) + 1),
                test_start_idx=min(test_idx),
                test_end_idx=max(test_idx) + 1,
                embargo=max(0, int(embargo_bars)),
            )
        )
        fold_i += 1
        cursor += step
    return folds
