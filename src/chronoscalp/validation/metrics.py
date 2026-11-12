"""Core research metrics: Sharpe, Deflated Sharpe (DSR), and PBO via CSCV.

Formulas follow López de Prado (Advances in Financial Machine Learning).
Inputs are **net-of-cost** period returns (or trade R-multiples treated as
returns). Never feed gross PnL into these helpers.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import combinations

import numpy as np


def sharpe_ratio(
    returns: Sequence[float],
    *,
    periods_per_year: float = 252.0,
    risk_free: float = 0.0,
) -> float:
    """Annualized Sharpe of ``returns`` (sample std, ddof=1)."""
    arr = np.asarray(list(returns), dtype=float)
    if arr.size < 2:
        return 0.0
    excess = arr - float(risk_free) / float(periods_per_year)
    mu = float(np.mean(excess))
    sigma = float(np.std(excess, ddof=1))
    if sigma <= 0.0 or not math.isfinite(sigma):
        return 0.0
    return (mu / sigma) * math.sqrt(float(periods_per_year))


def _psr(
    sharpe: float,
    *,
    n: int,
    skew: float,
    kurt: float,
    benchmark: float = 0.0,
) -> float:
    """Probabilistic Sharpe Ratio Φ(z) for observed Sharpe vs benchmark."""
    if n < 2:
        return 0.0
    # Bailey & López de Prado PSR
    num = (sharpe - benchmark) * math.sqrt(n - 1)
    den_sq = 1.0 - skew * sharpe + ((kurt - 1.0) / 4.0) * sharpe**2
    if den_sq <= 0.0:
        return 0.0
    z = num / math.sqrt(den_sq)
    # Standard normal CDF
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    n_trials: int,
    periods_per_year: float = 252.0,
    risk_free: float = 0.0,
) -> dict[str, float]:
    """Deflated Sharpe Ratio adjusting for multiple testing (``n_trials``).

    Returns a dict with ``sharpe``, ``dsr``, ``psr``, ``skew``, ``kurtosis``.
    ``dsr`` is the Probabilistic Sharpe vs the expected max Sharpe under
    ``n_trials`` independent trials (Bailey & López de Prado).
    """
    arr = np.asarray(list(returns), dtype=float)
    n = int(arr.size)
    sr = sharpe_ratio(arr, periods_per_year=periods_per_year, risk_free=risk_free)
    if n < 3:
        return {"sharpe": sr, "dsr": 0.0, "psr": 0.0, "skew": 0.0, "kurtosis": 3.0}

    excess = arr - float(risk_free) / float(periods_per_year)
    # Per-period Sharpe (non-annualized) for moment adjustments.
    sigma = float(np.std(excess, ddof=1))
    sr_period = float(np.mean(excess) / sigma) if sigma > 0 else 0.0
    skew = float(_skew(excess))
    kurt = float(_kurtosis(excess))  # Pearson; normal == 3

    trials = max(1, int(n_trials))
    # Expected maximum Sharpe under null (approx).
    e_max = (1.0 - np.euler_gamma) * _norm_ppf(1.0 - 1.0 / trials) + np.euler_gamma * _norm_ppf(
        1.0 - 1.0 / (trials * math.e)
    )
    # Convert expected max to same units as annualized SR for reporting,
    # but PSR uses period SR vs period-scale benchmark.
    benchmark_period = float(e_max) / math.sqrt(float(periods_per_year))
    psr = _psr(sr_period, n=n, skew=skew, kurt=kurt, benchmark=benchmark_period)
    return {
        "sharpe": float(sr),
        "dsr": float(psr),  # DSR ≡ PSR(SR*, benchmark=E[max SR])
        "psr": float(_psr(sr_period, n=n, skew=skew, kurt=kurt, benchmark=0.0)),
        "skew": skew,
        "kurtosis": kurt,
        "n": float(n),
        "n_trials": float(trials),
        "expected_max_sharpe": float(e_max),
    }


def probability_of_backtest_overfitting(
    strategy_returns: Sequence[Sequence[float]],
) -> dict[str, float]:
    """Probability of Backtest Overfitting via Combinatorial Symmetric CV.

    ``strategy_returns`` is a matrix-like sequence: each inner sequence is the
    period-return path of one strategy/trial on the same aligned periods.
    With S strategies and T periods, CSCV splits periods into two equal halves
    over all combinations and counts how often the IS-best strategy underperforms
    OOS relative to the median.
    """
    matrix = [list(map(float, row)) for row in strategy_returns]
    if not matrix:
        return {"pbo": 1.0, "n_strategies": 0.0, "n_combinations": 0.0}
    n_strat = len(matrix)
    n_periods = min(len(r) for r in matrix)
    if n_strat < 2 or n_periods < 4:
        return {"pbo": 1.0, "n_strategies": float(n_strat), "n_combinations": 0.0}

    truncated = np.asarray([row[:n_periods] for row in matrix], dtype=float)
    half = n_periods // 2
    idxs = list(range(n_periods))
    overfit = 0
    total = 0
    for combo in combinations(idxs, half):
        is_idx = list(combo)
        oos_idx = [i for i in idxs if i not in combo]
        if len(oos_idx) < 2:
            continue
        is_sharpes = [_path_sharpe(truncated[s, is_idx]) for s in range(n_strat)]
        best = int(np.argmax(is_sharpes))
        oos_sharpes = [_path_sharpe(truncated[s, oos_idx]) for s in range(n_strat)]
        rank = sorted(oos_sharpes)
        # Relative rank of the IS-best in OOS (0 = worst, 1 = best).
        best_oos = oos_sharpes[best]
        # PBO: fraction of combinations where IS-best lands in the lower OOS half.
        median = rank[len(rank) // 2]
        if best_oos < median:
            overfit += 1
        total += 1
        # Cap combinations for CI runtime when periods grow.
        if total >= 2000:
            break

    pbo = (overfit / total) if total else 1.0
    return {
        "pbo": float(pbo),
        "n_strategies": float(n_strat),
        "n_combinations": float(total),
        "overfit_count": float(overfit),
    }


def _path_sharpe(path: np.ndarray) -> float:
    if path.size < 2:
        return 0.0
    mu = float(np.mean(path))
    sigma = float(np.std(path, ddof=1))
    if sigma <= 0.0:
        return 0.0
    return mu / sigma


def _skew(arr: np.ndarray) -> float:
    n = arr.size
    if n < 3:
        return 0.0
    m = float(np.mean(arr))
    m2 = float(np.mean((arr - m) ** 2))
    m3 = float(np.mean((arr - m) ** 3))
    if m2 <= 0.0:
        return 0.0
    return m3 / (m2**1.5)


def _kurtosis(arr: np.ndarray) -> float:
    """Pearson kurtosis (normal == 3)."""
    n = arr.size
    if n < 4:
        return 3.0
    m = float(np.mean(arr))
    m2 = float(np.mean((arr - m) ** 2))
    m4 = float(np.mean((arr - m) ** 4))
    if m2 <= 0.0:
        return 3.0
    return m4 / (m2**2)


def _norm_ppf(p: float) -> float:
    """Approximate inverse CDF of standard normal (Acklam)."""
    p = min(max(float(p), 1e-12), 1.0 - 1e-12)
    # Rational approximation coefficients
    a = [
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614736e01,
        2.506628277459239e00,
    ]
    b = [
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    ]
    c = [
        -7.784894002430293e-03,
        -3.223726362721393e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    ]
    d = [
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    ]
    plow = 0.02425
    phigh = 1.0 - plow
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    if p > phigh:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
            / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        )
    q = p - 0.5
    r = q * q
    return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
    )
