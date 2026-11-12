"""Machine-readable strategy validation reports (net of costs)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chronoscalp.validation.cpcv import cpcv_path_splits, summarize_cpcv_sharpes
from chronoscalp.validation.metrics import (
    deflated_sharpe_ratio,
    probability_of_backtest_overfitting,
    sharpe_ratio,
)
from chronoscalp.validation.walkforward import purged_walk_forward_folds

MIN_TRADES_VERDICT = 30
MIN_TRADES_HEADLINE = 100


@dataclass
class StrategyValidationReport:
    """One strategy's quant verdict under the Phase 1 cost-real plane."""

    strategy: str
    symbol: str
    generated_at: str
    n_trades: int
    net_expectancy_r: float
    net_profit_factor: float
    sharpe: float
    dsr: float
    pbo: float
    cpcv: dict[str, float] = field(default_factory=dict)
    walkforward: dict[str, Any] = field(default_factory=dict)
    costs_net: bool = True
    min_trades_ok: bool = False
    headline_ok: bool = False
    verdict: str = "reject"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_report_from_trade_r(
    *,
    strategy: str,
    symbol: str,
    trade_r: Sequence[float],
    rival_paths: Sequence[Sequence[float]] | None = None,
    n_trials: int | None = None,
    embargo: int = 5,
) -> StrategyValidationReport:
    """Build a validation report from a chronological series of net R multiples."""
    returns = [float(x) for x in trade_r]
    n = len(returns)
    sum(1 for r in returns if r > 0)
    sum(1 for r in returns if r <= 0)
    gross_win = sum(r for r in returns if r > 0)
    gross_loss = abs(sum(r for r in returns if r <= 0))
    expectancy = (sum(returns) / n) if n else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)

    trials = int(n_trials if n_trials is not None else max(1, n))
    dsr_payload = deflated_sharpe_ratio(returns, n_trials=trials)
    sr = float(dsr_payload["sharpe"])
    dsr = float(dsr_payload["dsr"])

    rivals = list(rival_paths) if rival_paths else []
    if returns and not rivals:
        # Synthetic rivals: shuffle-like sign flips for a minimum PBO matrix.
        rivals = [
            returns,
            [-r for r in returns],
            [r * 0.5 for r in returns],
            [(-r if i % 2 else r) for i, r in enumerate(returns)],
        ]
    pbo_payload = probability_of_backtest_overfitting(rivals)
    pbo = float(pbo_payload["pbo"])

    cpcv_summary: dict[str, float] = {}
    wf_summary: dict[str, Any] = {}
    notes: list[str] = []
    if n >= 12:
        paths = cpcv_path_splits(
            n, n_groups=min(6, max(3, n // 4)), n_test_groups=1, embargo=embargo
        )
        oos_paths = [[returns[i] for i in path.test_idx] for path in paths]
        cpcv_summary = summarize_cpcv_sharpes(oos_paths)
        try:
            folds = purged_walk_forward_folds(n, n_folds=min(5, max(2, n // 20)), embargo=embargo)
            oos_sharpes = []
            for fold in folds:
                chunk = returns[fold.test_start_idx : fold.test_end_idx]
                oos_sharpes.append(sharpe_ratio(chunk))
            wf_summary = {
                "n_folds": len(folds),
                "mean_oos_sharpe": (
                    float(sum(oos_sharpes) / len(oos_sharpes)) if oos_sharpes else 0.0
                ),
            }
        except ValueError as exc:
            notes.append(f"walkforward_skipped:{exc}")
    else:
        notes.append("insufficient_samples_for_cpcv")

    min_ok = n >= MIN_TRADES_VERDICT
    headline_ok = n >= MIN_TRADES_HEADLINE
    verdict = "reject"
    if min_ok and dsr > 0.0 and pbo < 0.5:
        verdict = "accept_candidate"
    if headline_ok and dsr > 0.0 and pbo < 0.5 and expectancy > 0.0:
        verdict = "headline_eligible"
    if not min_ok:
        notes.append(f"need_ge_{MIN_TRADES_VERDICT}_trades_for_verdict")
    if dsr <= 0.0:
        notes.append("dsr_not_positive")
    if pbo >= 0.5:
        notes.append("pbo_ge_50pct")

    return StrategyValidationReport(
        strategy=strategy,
        symbol=symbol,
        generated_at=datetime.now(tz=UTC).isoformat(),
        n_trades=n,
        net_expectancy_r=round(expectancy, 4),
        net_profit_factor=round(float(pf) if pf != float("inf") else 999.0, 4),
        sharpe=round(sr, 4),
        dsr=round(dsr, 4),
        pbo=round(pbo, 4),
        cpcv=cpcv_summary,
        walkforward=wf_summary,
        costs_net=True,
        min_trades_ok=min_ok,
        headline_ok=headline_ok,
        verdict=verdict,
        notes=notes,
    )


def write_report(report: StrategyValidationReport, path: str | Path) -> Path:
    """Write ``report`` as JSON (atomic-ish replace)."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out)
    return out
