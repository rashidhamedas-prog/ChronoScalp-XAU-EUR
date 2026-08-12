#!/usr/bin/env python3
"""Broker-native baseline backtest + 1.5x cost stress (research only).

Does not enable live trading or loosen 1%/3% risk ceilings.
Writes JSON under data/reports/ (gitignored).
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.backtest.engine import run_backtest  # noqa: E402
from chronoscalp.config import Settings, get_settings  # noqa: E402
from chronoscalp.data.mt5_connector import load_history_csv  # noqa: E402
from chronoscalp.indicators.technical import enrich_with_indicators  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.smc.structure import enrich_with_smc  # noqa: E402
from chronoscalp.utils.types import Timeframe  # noqa: E402


def _load_enriched(symbol: str, data_dir: str, settings) -> dict[Timeframe, object] | None:
    higher = [Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]]
    trigger_list = [Timeframe(tf) for tf in settings.raw["timeframes"]["entry_trigger"]]
    needed = sorted(set(higher + trigger_list), key=lambda t: t.minutes)
    ind = settings.indicators
    data: dict[Timeframe, object] = {}
    for tf in needed:
        try:
            df = load_history_csv(data_dir, symbol, tf)
        except FileNotFoundError as exc:
            logger.error("{}", exc)
            return None
        df = enrich_with_indicators(
            df,
            ema_period=ind.get("ema_period_trend", 50),
            rsi_period=ind.get("rsi_period", 14),
            bb_period=ind.get("bollinger_period", 20),
            bb_std=ind.get("bollinger_std_dev", 2.0),
            macd_fast=ind.get("macd_fast", 12),
            macd_slow=ind.get("macd_slow", 26),
            macd_signal=ind.get("macd_signal", 9),
            atr_period=ind.get("atr_period", 14),
            rvol_period=ind.get("rvol_period", 20),
        )
        df = enrich_with_smc(
            df, rvol_min=float(settings.strategy.get("liquidity_rvol_min", 1.5))
        )
        data[tf] = df
    return data


def _stress_settings(settings, factor: float = 1.5):
    """Return a Settings-like object with 1.5x execution/backtest costs in ``raw``."""
    stressed = Settings.__new__(Settings)
    stressed.raw = deepcopy(settings.raw)
    stressed.symbols_raw = settings.symbols_raw
    stressed.secrets = settings.secrets
    execution = dict(stressed.raw.get("execution") or {})
    execution["slippage_pips"] = float(execution.get("slippage_pips", 0.5)) * factor
    stressed.raw["execution"] = execution
    bt = dict(stressed.raw.get("backtest") or {})
    spreads = dict(bt.get("default_spread_pips") or {})
    for key, value in list(spreads.items()):
        try:
            spreads[key] = float(value) * factor
        except (TypeError, ValueError):
            continue
    bt["default_spread_pips"] = spreads
    bt["commission_per_lot"] = float(bt.get("commission_per_lot", 7.0)) * factor
    stressed.raw["backtest"] = bt
    return stressed


def main() -> int:
    settings = get_settings()
    data_dir = str(settings.backtest.get("data_dir", "data/history"))
    higher = [Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]]
    trigger = Timeframe(settings.raw["timeframes"]["entry_trigger"][-1])
    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_all: dict[str, object] = {}
    for symbol in ("XAUUSD_o", "EURUSD_o"):
        data = _load_enriched(symbol, data_dir, settings)
        if data is None:
            summary_all[symbol] = {"error": "missing_history"}
            continue
        baseline = run_backtest(
            symbol=symbol,
            data_by_timeframe=data,
            higher_timeframes=higher,
            trigger_timeframe=trigger,
            settings=settings,
        ).summary()
        stressed = run_backtest(
            symbol=symbol,
            data_by_timeframe=data,
            higher_timeframes=higher,
            trigger_timeframe=trigger,
            settings=_stress_settings(settings, 1.5),
        ).summary()
        payload = {"baseline": baseline, "cost_stress_1p5x": stressed}
        path = out_dir / f"validate_{symbol}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        summary_all[symbol] = payload
        logger.info(
            "{} baseline trades={} pf={} | stress trades={} pf={}",
            symbol,
            baseline.get("total_trades"),
            baseline.get("profit_factor"),
            stressed.get("total_trades"),
            stressed.get("profit_factor"),
        )

    (out_dir / "cost_stress_1p5x_summary.json").write_text(
        json.dumps(summary_all, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(summary_all, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
