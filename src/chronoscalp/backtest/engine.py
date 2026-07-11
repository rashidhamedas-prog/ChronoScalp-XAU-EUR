"""Event-driven backtest engine.

Deliberately custom instead of Freqtrade/Jesse (both are CCXT/crypto-oriented
and don't model MT5-style spread/swap mechanics well — see README §3). Walks
the trigger timeframe bar-by-bar, feeding the strategy only data available up
to (and including) the current bar for every timeframe, using the same
strategy/risk/filter code paths as live trading (main.py) via `PaperBroker`.

Performance note: this is an O(n) bar-by-bar loop, not vectorized. Fine for
M5/M10 backtests spanning a few years; for multi-year M1 backtests, consider
narrowing the date range or optimizing `_as_of()` further before relying on
it for large parameter sweeps (see docs/ROADMAP.md Phase 5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.logging_setup import logger
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy
from chronoscalp.utils.types import SignalType, Timeframe, TradeResult


@dataclass
class BacktestResult:
    symbol: str
    trades: list[TradeResult] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    starting_equity: float = 0.0
    final_equity: float = 0.0

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return round(wins / len(self.trades), 4)

    @property
    def profit_factor(self) -> float:
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return round(gross_profit / gross_loss, 3) if gross_loss > 0 else float("inf")

    @property
    def expectancy_r(self) -> float:
        r_values = [t.r_multiple for t in self.trades]
        return round(sum(r_values) / len(r_values), 3) if r_values else 0.0

    @property
    def max_drawdown_pct(self) -> float:
        if not self.equity_curve:
            return 0.0
        peak = self.equity_curve[0][1]
        max_dd = 0.0
        for _, equity in self.equity_curve:
            peak = max(peak, equity)
            dd = (peak - equity) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)
        return round(max_dd * 100, 3)

    def summary(self) -> dict:
        return {
            "symbol": self.symbol,
            "total_trades": self.total_trades,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "profit_factor": self.profit_factor,
            "expectancy_r": self.expectancy_r,
            "max_drawdown_pct": self.max_drawdown_pct,
            "starting_equity": self.starting_equity,
            "final_equity": round(self.final_equity, 2),
            "return_pct": round((self.final_equity / self.starting_equity - 1) * 100, 2)
            if self.starting_equity
            else 0.0,
        }


def _as_of(df: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """All bars with index <= t (no look-ahead)."""
    idx = df.index.searchsorted(t, side="right")
    return df.iloc[:idx]


def run_backtest(
    symbol: str,
    data_by_timeframe: dict[Timeframe, pd.DataFrame],
    higher_timeframes: list[Timeframe],
    trigger_timeframe: Timeframe,
    settings,
    start: datetime | None = None,
    end: datetime | None = None,
) -> BacktestResult:
    """Run a full backtest for one symbol.

    `data_by_timeframe` values must already be indicator- and SMC-enriched
    (see indicators.technical.enrich_with_indicators / smc.structure.enrich_with_smc)
    and indexed by UTC timestamp.
    """
    trigger_df = data_by_timeframe[trigger_timeframe]
    if start is not None:
        trigger_df = trigger_df[trigger_df.index >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        trigger_df = trigger_df[trigger_df.index <= pd.Timestamp(end, tz="UTC")]

    starting_equity = float(settings.backtest.get("initial_balance", 10_000))
    broker = PaperBroker(
        symbols_cfg=settings.symbols_raw,
        starting_balance=starting_equity,
        slippage_pips=float(settings.execution.get("slippage_pips", 0.5)),
    )
    session_filter = SessionFilter.from_config(settings.sessions)
    from chronoscalp.config import CONFIG_DIR

    news_filter = NewsFilter.from_config(
        settings.news_filter, CONFIG_DIR / "news_events.yaml", settings.secrets.news_api_key
    )
    strategy = MultiTimeframeStrategy(settings.strategy, settings.indicators)
    risk_manager = RiskManager(
        risk_cfg=settings.risk,
        spread_cfg=settings.spread_filter,
        symbols_cfg=settings.symbols_raw,
        starting_equity=starting_equity,
    )

    result = BacktestResult(symbol=symbol, starting_equity=starting_equity)
    warmup = max(50, settings.indicators.get("ema_period_trend", 50) + 5)

    open_ticket: int | None = None

    for i in range(warmup, len(trigger_df)):
        t = trigger_df.index[i]
        bar = trigger_df.iloc[i]

        # --- manage any open position first: did SL/TP get hit on this bar? ---
        if open_ticket is not None:
            open_ticket = _manage_open_position(
                broker, risk_manager, open_ticket, bar, t, result
            )

        if open_ticket is not None:
            continue  # only one position at a time in this simplified engine

        if not session_filter.is_within_session(t.to_pydatetime()):
            continue
        if news_filter.is_blackout(t.to_pydatetime()):
            continue

        sliced = {
            tf: _as_of(df, t) for tf, df in data_by_timeframe.items()
        }
        signal = strategy.evaluate(
            symbol=symbol,
            data_by_timeframe=sliced,
            higher_timeframes=higher_timeframes,
            trigger_timeframe=trigger_timeframe,
        )
        if signal.signal_type == SignalType.NONE:
            continue

        spread_pips = broker.get_current_spread_pips(symbol)
        if not risk_manager.validate_signal(signal, spread_pips):
            continue

        equity = broker.get_balance()
        volume = risk_manager.position_size_for(signal, equity)
        if volume <= 0:
            continue

        position = broker.place_order(signal, volume, fill_price=bar["close"])
        open_ticket = position.ticket
        result.equity_curve.append((t.to_pydatetime(), broker.get_balance()))

    if open_ticket is not None:
        last_bar = trigger_df.iloc[-1]
        trade = broker.close_position(open_ticket, exit_price=last_bar["close"], reason="backtest_end")
        result.trades.append(trade)
        risk_manager.daily_tracker.record_trade_pnl(trade.pnl)

    result.final_equity = broker.get_balance()
    if not result.equity_curve:
        result.equity_curve.append((trigger_df.index[0].to_pydatetime(), starting_equity))
    result.equity_curve.append((trigger_df.index[-1].to_pydatetime(), result.final_equity))

    logger.info("Backtest complete for {}: {}", symbol, result.summary())
    return result


def _manage_open_position(broker: PaperBroker, risk_manager: RiskManager, ticket: int, bar: pd.Series, t: pd.Timestamp, result: BacktestResult) -> int | None:
    position = broker._positions.get(ticket)  # noqa: SLF001 - backtest engine is allowed intimate access to the paper broker
    if position is None:
        return None

    hit_sl = (
        bar["low"] <= position.stop_loss
        if position.direction == SignalType.BUY
        else bar["high"] >= position.stop_loss
    )
    hit_tp = (
        bar["high"] >= position.take_profit
        if position.direction == SignalType.BUY
        else bar["low"] <= position.take_profit
    )

    if hit_sl or hit_tp:
        exit_price = position.stop_loss if hit_sl else position.take_profit
        trade = broker.close_position(
            ticket, exit_price=exit_price, at=t.to_pydatetime(), reason="stop_loss" if hit_sl else "take_profit"
        )
        result.trades.append(trade)
        risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=t.to_pydatetime())
        result.equity_curve.append((t.to_pydatetime(), broker.get_balance()))
        return None

    # breakeven / trailing stop management
    new_sl = risk_manager.breakeven_stop(position, bar["close"])
    if new_sl is not None:
        broker.modify_sl_tp(ticket, new_sl, position.take_profit)
        position.breakeven_moved = True
    elif "atr" in bar and not pd.isna(bar["atr"]):
        trailing_sl = risk_manager.trailing_stop(position, bar["close"], bar["atr"])
        if trailing_sl is not None:
            broker.modify_sl_tp(ticket, trailing_sl, position.take_profit)

    return ticket
