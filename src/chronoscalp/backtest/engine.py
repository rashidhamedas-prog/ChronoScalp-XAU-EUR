"""Event-driven backtest engine.

Deliberately custom instead of Freqtrade/Jesse (both are CCXT/crypto-oriented
and don't model MT5-style spread/swap mechanics well — see README §3). Walks
the trigger timeframe bar-by-bar, feeding the strategy only data available up
to (and including) the current bar for every timeframe, using the same
strategy, sizing, session, news and spread code paths as live trading via
`PaperBroker`.

It does NOT model the additional entry guards the live loop applies — see
``LIVE_ONLY_GATES``. Backtest trade counts are therefore an upper bound on
live trade counts, and every summary carries that list so results are not
read as a live forecast.

Performance note: this is an O(n) bar-by-bar loop, not vectorized. Fine for
M5/M10 backtests spanning a few years; for multi-year M1 backtests, consider
narrowing the date range or optimizing `_as_of()` further before relying on
it for large parameter sweeps (see docs/ROADMAP.md Phase 5).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.execution.position_logic import (
    apply_breakeven_or_trailing,
    check_sl_tp_hit,
    exit_price_for_hit,
)
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.filters.spread_shield import RollingMedianSpread
from chronoscalp.logging_setup import logger
from chronoscalp.orchestration.comparison_books import ComparisonBooks
from chronoscalp.risk.institutional_guards import (
    SpreadMovingAverageGuard,
    ThreeStrikesGuard,
    volatility_decision,
)
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy, is_shadow_only
from chronoscalp.utils.strategy_tags import mt5_comment_for_strategy, resolve_strategy_tag
from chronoscalp.utils.types import (
    PendingOrderSide,
    Position,
    SignalType,
    Timeframe,
    TradeResult,
)

# Entry guards that main.py applies and this engine can never simulate, because
# they depend on live account/broker state or on cross-symbol context a
# single-symbol run does not have. Each one can only remove trades, so backtest
# counts still bound live counts from above.
LIVE_ONLY_GATES: tuple[str, ...] = (
    "circuit_breaker",
    "correlation_guard",
    "kill_switch",
    "mistake_memory",
    "mt5_netting_fail_closed",
    "portfolio_heat_live_shared",
    "stale_stops",
)

# Guards the engine *does* reproduce, but only while ``backtest.model_live_gates``
# is on. When it is off they fall back into the not-modelled list so a summary
# never claims parity it does not have.
PARITY_GATES: tuple[str, ...] = (
    "daily_loss_limit",
    "spread_ma_guard",
    "three_strikes",
    "volatility_guard",
)


@dataclass
class BacktestResult:
    symbol: str
    trades: list[TradeResult] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    starting_equity: float = 0.0
    final_equity: float = 0.0
    strategy_reports: dict[str, dict] = field(default_factory=dict)
    # Conservative defaults: a result built by hand has modelled nothing.
    unmodelled_gates: tuple[str, ...] = LIVE_ONLY_GATES + PARITY_GATES
    stop_management: str = "bar_close"

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
            "return_pct": (
                round((self.final_equity / self.starting_equity - 1) * 100, 2)
                if self.starting_equity
                else 0.0
            ),
            "live_only_gates_not_modelled": list(self.unmodelled_gates),
            "stop_management": self.stop_management,
            "strategy_reports": dict(self.strategy_reports),
        }


def _as_of(df: pd.DataFrame, t: pd.Timestamp) -> pd.DataFrame:
    """All bars with index <= t (no look-ahead on the trigger frame)."""
    idx = df.index.searchsorted(t, side="right")
    return df.iloc[:idx]


def _as_of_closed(
    df: pd.DataFrame,
    t: pd.Timestamp,
    tf: Timeframe,
    *,
    is_trigger: bool,
) -> pd.DataFrame:
    """Timeframe-aware slice: HTF bars must have fully closed before ``t``.

    Trigger bars include the current closed bar at ``t``. Higher timeframes
    exclude the forming bar whose open is still inside the current trigger bar.
    """
    if df is None or df.empty:
        return df
    if is_trigger:
        return _as_of(df, t)
    duration = pd.Timedelta(seconds=int(tf.seconds))
    close_at = df.index + duration
    return df.loc[close_at <= t]


def _intrabar_path(bar: pd.Series) -> tuple[float, ...]:
    """Waypoints price is assumed to visit while ``bar`` forms.

    Tick data is not available, so the true path is unknown. This uses the
    MT5 "OHLC on M1" convention: a bar that closed up is assumed to dip to its
    low before running to its high, a bar that closed down to pop to its high
    first. Both orderings are adverse-first, so the model never invents a
    favourable sequence the market may not have delivered.
    """
    open_ = float(bar["open"])
    high = float(bar["high"])
    low = float(bar["low"])
    close = float(bar["close"])
    if close >= open_:
        return (open_, low, high, close)
    return (open_, high, low, close)


def _stop_check_segments(
    bar: pd.Series, *, intrabar: bool
) -> tuple[tuple[float, float, float], ...]:
    """Return ``(high, low, end_price)`` legs to evaluate stops against.

    With ``intrabar`` the bar is split into monotonic legs along
    :func:`_intrabar_path`, and the stop is re-evaluated at the end of each
    leg. That is what makes a stop trailed up on the bar's high reachable by
    the pullback later in the *same* bar — live polls every few seconds, so it
    behaves this way, while the single bar-close model could only expose a
    trailed stop from the next bar onward and therefore under-reported
    stop-outs.

    Without ``intrabar`` this degrades to the legacy single leg spanning the
    whole bar with trailing evaluated at the close.
    """
    if not intrabar:
        return ((float(bar["high"]), float(bar["low"]), float(bar["close"])),)
    path = _intrabar_path(bar)
    return tuple(
        (max(start, end), min(start, end), end) for start, end in zip(path, path[1:], strict=False)
    )


def _volatility_allows(
    sliced: dict[Timeframe, pd.DataFrame],
    vol_tf: Timeframe,
    trigger_timeframe: Timeframe,
    vol_cfg: dict,
) -> bool:
    """Mirror main.py's regime guard: ATR/close on the configured timeframe.

    Falls back the same way live does (configured frame, then M5, then the
    trigger frame) so a missing higher timeframe does not silently skip the
    check.
    """
    for candidate_tf in (vol_tf, Timeframe.M5, trigger_timeframe):
        df = sliced.get(candidate_tf)
        if df is not None and not df.empty:
            break
    else:
        return True
    if df is None or df.empty:
        return True

    last = df.iloc[-1]
    try:
        atr_v = float(last.get("atr", 0) or 0.0)
    except (TypeError, ValueError):
        atr_v = 0.0
    try:
        close_v = float(last.get("close", 0) or 0.0)
    except (TypeError, ValueError):
        close_v = 0.0
    allowed, _reason, _ratio = volatility_decision(
        atr_v,
        close_v,
        min_ratio=float(vol_cfg.get("min_atr_close_ratio", 0.00005)),
        max_ratio=float(vol_cfg.get("max_atr_close_ratio", 0.05)),
    )
    return allowed


def _to_utc_timestamp(value: datetime | pd.Timestamp) -> pd.Timestamp:
    """Normalize a datetime-like bound to a UTC-aware Timestamp.

    Walk-forward / grid search pass timezone-aware ``datetime`` values from a
    UTC ``DatetimeIndex``. Calling ``pd.Timestamp(aware_dt, tz="UTC")`` raises
    ``ValueError``; convert aware values and only attach tz for naive ones.
    """
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return pd.Timestamp(ts, tz="UTC")
    return ts.tz_convert("UTC")


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
        trigger_df = trigger_df[trigger_df.index >= _to_utc_timestamp(start)]
    if end is not None:
        trigger_df = trigger_df[trigger_df.index <= _to_utc_timestamp(end)]

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
    strategy = MultiTimeframeStrategy(
        settings.strategy, settings.indicators, symbols_cfg=settings.symbols_raw
    )
    risk_manager = RiskManager(
        risk_cfg=settings.risk,
        spread_cfg=settings.spread_filter,
        symbols_cfg=settings.symbols_raw,
        starting_equity=starting_equity,
    )

    backtest_cfg = settings.backtest or {}
    intrabar = bool(backtest_cfg.get("intrabar_stop_management", True))
    model_gates = bool(backtest_cfg.get("model_live_gates", True))

    risk_cfg = settings.risk or {}
    spread_ma_cfg = risk_cfg.get("spread_ma_guard") or {}
    spread_ma_guard = SpreadMovingAverageGuard(
        window=int(spread_ma_cfg.get("window", 100)),
        multiplier=float(spread_ma_cfg.get("multiplier", 2.5)),
    )
    spread_ma_enabled = model_gates and bool(spread_ma_cfg.get("enabled", True))

    strikes_cfg = risk_cfg.get("three_strikes") or {}
    three_strikes = ThreeStrikesGuard(
        max_losses=int(strikes_cfg.get("max_losses", 3)),
        pause_hours=int(strikes_cfg.get("pause_hours", 12)),
    )
    three_strikes_enabled = model_gates and bool(strikes_cfg.get("enabled", True))

    vol_cfg = risk_cfg.get("volatility_guard") or {}
    vol_enabled = model_gates and bool(vol_cfg.get("enabled", True))
    try:
        vol_tf = Timeframe(str(vol_cfg.get("timeframe", "M5")))
    except ValueError:
        vol_tf = Timeframe.M5
    if not model_gates:
        # Legacy mode: the tracker used wall-clock "today" against bar-time
        # P&L, so it never actually fired. Disable it rather than pretend.
        risk_manager.daily_tracker.enabled = False

    result = BacktestResult(
        symbol=symbol,
        starting_equity=starting_equity,
        unmodelled_gates=LIVE_ONLY_GATES if model_gates else LIVE_ONLY_GATES + PARITY_GATES,
        stop_management="intrabar_ohlc_path" if intrabar else "bar_close",
    )
    warmup = max(50, settings.indicators.get("ema_period_trend", 50) + 5)

    books = ComparisonBooks(
        symbols_cfg=settings.symbols_raw,
        starting_balance=starting_equity,
        slippage_pips=float(settings.execution.get("slippage_pips", 0.5)),
    )
    open_tickets: dict[str, int] = {}
    spread_median = RollingMedianSpread()

    for i in range(warmup, len(trigger_df)):
        t = trigger_df.index[i]
        bar = trigger_df.iloc[i]
        moment = t.to_pydatetime()

        books.set_quote(symbol, float(bar["low"]), float(bar["high"]), moment)
        broker.set_quote(symbol, float(bar["low"]), float(bar["high"]), moment)

        # Live observes the spread every tick, before any session/news gate, so
        # the guard baselines see the same population here.
        spread_pips = broker.get_current_spread_pips(symbol)
        spread_ma_guard.observe(symbol, spread_pips)
        spread_median.observe(symbol, spread_pips)
        median = spread_median.median(symbol)

        for tag, ticket in list(open_tickets.items()):
            strat_broker = books.broker_for(tag)

            def _record_strike(trade: TradeResult, _tag: str = tag, _at: datetime = moment) -> None:
                if three_strikes_enabled:
                    three_strikes.record_result(symbol, trade.pnl, at=_at, strategy=_tag)

            remaining = _manage_open_position(
                strat_broker,
                risk_manager,
                ticket,
                bar,
                t,
                result,
                books,
                tag,
                intrabar=intrabar,
                on_trade_closed=_record_strike,
            )
            if remaining is None:
                open_tickets.pop(tag, None)

        for tag, book in list(books._books.items()):  # noqa: SLF001
            if tag in open_tickets:
                continue
            filled = book.broker.get_open_positions(symbol)
            if filled:
                open_tickets[tag] = filled[0].ticket
                book.mark_equity(moment)

        if not session_filter.is_within_session(moment):
            continue
        if three_strikes_enabled and three_strikes.is_paused(symbol, at=moment):
            continue
        if news_filter.is_blackout(moment):
            continue
        if spread_ma_enabled and not spread_ma_guard.allows(symbol, spread_pips):
            continue

        cap = None
        spread_map = settings.spread_filter.get("max_spread_pips") or {}
        if isinstance(spread_map, dict):
            cap = spread_map.get(symbol)

        sliced = {
            tf: _as_of_closed(df, t, tf, is_trigger=tf == trigger_timeframe)
            for tf, df in data_by_timeframe.items()
        }
        if vol_enabled and not _volatility_allows(sliced, vol_tf, trigger_timeframe, vol_cfg):
            continue
        candidates = strategy.evaluate_candidates(
            symbol=symbol,
            data_by_timeframe=sliced,
            higher_timeframes=higher_timeframes,
            trigger_timeframe=trigger_timeframe,
            spread_pips=spread_pips,
            median_spread_pips=median,
            broker_spread_cap_pips=float(cap) if cap is not None else None,
        )
        if strategy.xau_vwap_engine.working_stop(symbol) is None:
            xau_broker = books.broker_for("xau_vwap_pullback")
            prefix = mt5_comment_for_strategy("xau_vwap_pullback")
            for order in xau_broker.get_pending_orders(symbol, comment_prefix=prefix) or []:
                xau_broker.cancel_pending_order(order.ticket)

        for signal in candidates:
            if signal.signal_type == SignalType.NONE or not signal.is_actionable:
                continue
            tag = resolve_strategy_tag(
                explicit=getattr(signal, "strategy", "") or "", reason=signal.reason
            )
            if tag in open_tickets:
                continue
            if is_shadow_only(settings.strategy, tag):
                continue
            if three_strikes_enabled and three_strikes.is_paused(symbol, at=moment, strategy=tag):
                continue
            if not risk_manager.validate_signal(signal, spread_pips, at=moment):
                continue

            strat_broker = books.broker_for(tag)
            if strat_broker.get_pending_orders(
                symbol, comment_prefix=mt5_comment_for_strategy(tag)
            ):
                continue
            equity = strat_broker.get_balance()
            volume = risk_manager.position_size_for(signal, equity)
            if volume <= 0:
                continue

            if str(getattr(signal, "order_kind", "market") or "market") == "stop":
                side = (
                    PendingOrderSide.BUY_STOP
                    if signal.signal_type == SignalType.BUY
                    else PendingOrderSide.SELL_STOP
                )
                strat_broker.place_pending_stop(
                    symbol=symbol,
                    side=side,
                    volume=volume,
                    price=signal.entry_price,
                    stop_loss=signal.stop_loss,
                    take_profit=signal.take_profit,
                    comment=mt5_comment_for_strategy(tag),
                    strategy=tag,
                )
                continue

            position = strat_broker.place_order(signal, volume, fill_price=bar["close"])
            open_tickets[tag] = position.ticket
            books.for_strategy(tag).mark_equity(moment)
            result.equity_curve.append((moment, strat_broker.get_balance()))

    last_bar = trigger_df.iloc[-1]
    last_t = trigger_df.index[-1].to_pydatetime()
    for tag, ticket in list(open_tickets.items()):
        strat_broker = books.broker_for(tag)
        trade = strat_broker.close_position(
            ticket, exit_price=last_bar["close"], reason="backtest_end"
        )
        result.trades.append(trade)
        books.for_strategy(tag).record_close(trade, last_t)
        risk_manager.daily_tracker.record_trade_pnl(trade.pnl)
        open_tickets.pop(tag, None)

    reports = books.reports()
    result.strategy_reports = reports
    portfolio_eq = sum(book.broker.get_balance() for book in books._books.values())  # noqa: SLF001
    if books._books:  # noqa: SLF001
        result.final_equity = portfolio_eq / len(books._books)  # noqa: SLF001
    else:
        result.final_equity = starting_equity
    if not result.equity_curve:
        result.equity_curve.append((trigger_df.index[0].to_pydatetime(), starting_equity))
    result.equity_curve.append((trigger_df.index[-1].to_pydatetime(), result.final_equity))

    logger.info("Backtest complete for {}: {}", symbol, result.summary())
    logger.warning(
        "Backtest for {} ({} stop management) does not model live-only entry "
        "guards ({}); expect fewer trades live than the {} simulated here.",
        symbol,
        result.stop_management,
        ", ".join(result.unmodelled_gates),
        result.total_trades,
    )
    return result


# Breakeven can fire once and trailing converges on the next call, so two
# passes is enough; the third exists only to prove convergence.
_MAX_STOP_ADVANCES_PER_WAYPOINT = 3


def _advance_stop(
    broker: PaperBroker,
    risk_manager: RiskManager,
    position: Position,
    ticket: int,
    price: float,
    atr_value: float | None,
) -> None:
    """Apply breakeven and trailing at ``price``, mutating the position in place.

    ``apply_breakeven_or_trailing`` returns breakeven *or* a trail, whichever
    comes first, because live calls it once per poll and gets many polls per
    bar. A waypoint here stands for that whole run of polls, so keep applying
    it until the stop stops improving — otherwise the bar in which a trade
    first reaches 1R only ever moves to breakeven, and the trail lags a leg
    behind live.
    """
    for _ in range(_MAX_STOP_ADVANCES_PER_WAYPOINT):
        new_sl = apply_breakeven_or_trailing(risk_manager, position, price, atr_value)
        if new_sl is None:
            return
        broker.modify_sl_tp(ticket, new_sl, position.take_profit)
        if new_sl == position.entry_price:
            position.breakeven_moved = True
        position.stop_loss = new_sl


def _manage_open_position(
    broker: PaperBroker,
    risk_manager: RiskManager,
    ticket: int,
    bar: pd.Series,
    t: pd.Timestamp,
    result: BacktestResult,
    books: ComparisonBooks | None = None,
    tag: str = "",
    *,
    intrabar: bool = True,
    on_trade_closed: Callable[[TradeResult], None] | None = None,
) -> int | None:
    position = broker._positions.get(
        ticket
    )  # noqa: SLF001 - backtest engine is allowed intimate access to the paper broker
    if position is None:
        return None

    atr_value = float(bar["atr"]) if "atr" in bar and not pd.isna(bar["atr"]) else None
    moment = t.to_pydatetime()

    for seg_high, seg_low, seg_end in _stop_check_segments(bar, intrabar=intrabar):
        hit = check_sl_tp_hit(position, seg_high, seg_low)
        if hit.triggered:
            exit_price = exit_price_for_hit(position, hit)
            trade = broker.close_position(
                ticket, exit_price=exit_price, at=moment, reason=hit.exit_reason()
            )
            result.trades.append(trade)
            risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=moment)
            result.equity_curve.append((moment, broker.get_balance()))
            if books is not None and tag:
                books.for_strategy(tag).record_close(trade, moment)
            if on_trade_closed is not None:
                on_trade_closed(trade)
            return None
        _advance_stop(broker, risk_manager, position, ticket, seg_end, atr_value)

    return ticket
