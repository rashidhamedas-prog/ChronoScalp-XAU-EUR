#!/usr/bin/env python3
"""Broker-native baseline backtest + 1.5x cost stress (research only).

Does not enable live trading or loosen 1%/3% risk ceilings.
Writes JSON under data/reports/ (gitignored).
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chronoscalp.backtest.engine import run_backtest  # noqa: E402
from chronoscalp.config import Settings, get_settings  # noqa: E402
from chronoscalp.data.mt5_connector import load_history_csv  # noqa: E402
from chronoscalp.indicators.technical import enrich_with_indicators  # noqa: E402
from chronoscalp.logging_setup import logger  # noqa: E402
from chronoscalp.smc.structure import enrich_with_smc  # noqa: E402
from chronoscalp.utils.types import Timeframe  # noqa: E402

# Extra bars before the analysis window so EMA/ATR/SMC warm up.
_WARMUP_BARS = 300


def _window_bounds_from_raw(
    raw_by_tf: dict[Timeframe, pd.DataFrame],
    date_from: str | None,
    date_to: str | None,
    last_days: int | None,
) -> tuple[datetime | None, datetime | None, dict[str, str]]:
    """Resolve analysis start/end from raw (unenriched) frames."""
    meta: dict[str, str] = {}
    start = datetime.fromisoformat(date_from) if date_from else None
    end = datetime.fromisoformat(date_to) if date_to else None
    if last_days is not None and last_days > 0:
        ends: list[pd.Timestamp] = []
        for df in raw_by_tf.values():
            if df is None or df.empty:
                continue
            ends.append(pd.Timestamp(df.index.max()))
        if ends:
            end_ts = max(ends)
            start_ts = end_ts - pd.Timedelta(days=int(last_days))
            start = start_ts.to_pydatetime()
            end = end_ts.to_pydatetime()
            meta["window"] = "last_days"
            meta["last_days"] = str(last_days)
    if start is not None:
        meta["from"] = pd.Timestamp(start).isoformat()
    if end is not None:
        meta["to"] = pd.Timestamp(end).isoformat()
    return start, end, meta


def _slice_with_warmup(
    df: pd.DataFrame, start: datetime | None, end: datetime | None
) -> pd.DataFrame:
    """Keep analysis window plus preceding warmup bars for indicator stability."""
    if df.empty:
        return df
    if start is None and end is None:
        return df
    start_ts = pd.Timestamp(start) if start is not None else None
    end_ts = pd.Timestamp(end) if end is not None else None
    if start_ts is not None:
        before = df[df.index < start_ts]
        warmup = before.tail(_WARMUP_BARS)
        body = df[df.index >= start_ts]
        df = pd.concat([warmup, body])
    if end_ts is not None:
        df = df[df.index <= end_ts]
    return df


def _load_enriched(
    symbol: str,
    data_dir: str,
    settings,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[Timeframe, object] | None:
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
        before = len(df)
        df = _slice_with_warmup(df, start, end)
        logger.info(
            "cost_stress slice symbol={} tf={} bars_in={} bars_out={}",
            symbol,
            tf.value,
            before,
            len(df),
        )
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Baseline + 1.5x cost-stress backtests")
    parser.add_argument(
        "--symbols",
        nargs="+",
        default=["XAUUSD_o", "EURUSD_o"],
        help="Broker-native symbols to validate (default LiteFinance _o names)",
    )
    parser.add_argument("--from", dest="date_from", type=str, default=None)
    parser.add_argument("--to", dest="date_to", type=str, default=None)
    parser.add_argument(
        "--last-days",
        type=int,
        default=None,
        help="If set, backtest only the last N calendar days of available history",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    data_dir = str(settings.backtest.get("data_dir", "data/history"))
    higher = [Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]]
    trigger = Timeframe(settings.raw["timeframes"]["entry_trigger"][-1])
    out_dir = Path("data/reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_all: dict[str, object] = {}
    for symbol in args.symbols:
        logger.info("cost_stress load_raw_begin symbol={}", symbol)
        # Probe raw CSVs only to resolve last-days bounds, then slice+enrich.
        raw: dict[Timeframe, pd.DataFrame] = {}
        needed = sorted(
            set(
                [Timeframe(tf) for tf in settings.raw["timeframes"]["higher_trend"]]
                + [Timeframe(tf) for tf in settings.raw["timeframes"]["entry_trigger"]]
            ),
            key=lambda t: t.minutes,
        )
        missing = False
        for tf in needed:
            try:
                raw[tf] = load_history_csv(data_dir, symbol, tf)
            except FileNotFoundError as exc:
                logger.error("{}", exc)
                missing = True
                break
        if missing:
            summary_all[symbol] = {"error": "missing_history"}
            continue

        start, end, window_meta = _window_bounds_from_raw(
            raw, args.date_from, args.date_to, args.last_days
        )
        logger.info(
            "cost_stress enrich_begin symbol={} from={} to={}",
            symbol,
            window_meta.get("from"),
            window_meta.get("to"),
        )
        data = _load_enriched(symbol, data_dir, settings, start=start, end=end)
        if data is None:
            summary_all[symbol] = {"error": "missing_history"}
            continue
        logger.info("cost_stress run_begin symbol={}", symbol)
        baseline = run_backtest(
            symbol=symbol,
            data_by_timeframe=data,
            higher_timeframes=higher,
            trigger_timeframe=trigger,
            settings=settings,
            start=start,
            end=end,
        ).summary()
        stressed = run_backtest(
            symbol=symbol,
            data_by_timeframe=data,
            higher_timeframes=higher,
            trigger_timeframe=trigger,
            settings=_stress_settings(settings, 1.5),
            start=start,
            end=end,
        ).summary()
        payload = {
            "window": window_meta,
            "baseline": baseline,
            "cost_stress_1p5x": stressed,
        }
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
