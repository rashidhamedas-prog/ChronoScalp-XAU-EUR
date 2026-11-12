"""Combinatorial Purged Cross-Validation path generator.

Splits a chronological index into ``n_groups`` contiguous groups, then yields
every combination of ``n_test_groups`` groups as the test set. Training groups
are purged by ``embargo`` bars on each side of every test block.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class CpcvPath:
    """One CPCV train/test index path."""

    path_id: int
    train_idx: tuple[int, ...]
    test_idx: tuple[int, ...]
    test_groups: tuple[int, ...]


def cpcv_path_splits(
    n_samples: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo: int = 0,
) -> list[CpcvPath]:
    """Return all combinatorial purged CV paths for ``n_samples`` rows."""
    return list(
        iter_cpcv_paths(
            n_samples,
            n_groups=n_groups,
            n_test_groups=n_test_groups,
            embargo=embargo,
        )
    )


def iter_cpcv_paths(
    n_samples: int,
    *,
    n_groups: int = 6,
    n_test_groups: int = 2,
    embargo: int = 0,
) -> Iterator[CpcvPath]:
    if n_samples < 4:
        raise ValueError("CPCV needs at least 4 samples")
    if n_groups < 2:
        raise ValueError("n_groups must be >= 2")
    if not 1 <= n_test_groups < n_groups:
        raise ValueError("n_test_groups must be in [1, n_groups)")
    groups = _contiguous_groups(n_samples, n_groups)
    embargo_n = max(0, int(embargo))
    path_id = 0
    for test_groups in combinations(range(n_groups), n_test_groups):
        test_idx: list[int] = []
        for g in test_groups:
            test_idx.extend(groups[g])
        test_set = set(test_idx)
        # Purge + embargo around each contiguous test block.
        blocked = set(test_set)
        for idx in sorted(test_set):
            for d in range(1, embargo_n + 1):
                blocked.add(idx - d)
                blocked.add(idx + d)
        train_idx = tuple(i for i in range(n_samples) if i not in blocked)
        if not train_idx or not test_idx:
            continue
        yield CpcvPath(
            path_id=path_id,
            train_idx=train_idx,
            test_idx=tuple(sorted(test_set)),
            test_groups=tuple(test_groups),
        )
        path_id += 1


def _contiguous_groups(n_samples: int, n_groups: int) -> list[list[int]]:
    base = n_samples // n_groups
    rem = n_samples % n_groups
    groups: list[list[int]] = []
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < rem else 0)
        groups.append(list(range(start, start + size)))
        start += size
    return groups


def summarize_cpcv_sharpes(
    path_oos_returns: Sequence[Sequence[float]],
) -> dict[str, float]:
    """Aggregate mean/median OOS Sharpe across CPCV paths."""
    from chronoscalp.validation.metrics import sharpe_ratio

    sharpes = [sharpe_ratio(path) for path in path_oos_returns if len(path) >= 2]
    if not sharpes:
        return {"mean_oos_sharpe": 0.0, "median_oos_sharpe": 0.0, "n_paths": 0.0}
    ordered = sorted(sharpes)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 == 1 else 0.5 * (ordered[mid - 1] + ordered[mid])
    return {
        "mean_oos_sharpe": float(sum(sharpes) / len(sharpes)),
        "median_oos_sharpe": float(median),
        "n_paths": float(len(sharpes)),
        "min_oos_sharpe": float(min(sharpes)),
        "max_oos_sharpe": float(max(sharpes)),
    }
