"""Live/paper trading orchestration loop.

Deployment targets:
- **Windows + MT5** — ``execution.broker: mt5``, ``data_source: mt5`` (or auto)
- **Linux VPS (e.g. Netherlands)** — ``execution.broker: oanda``, ``data_source: oanda``
  See docs/DEPLOY_NL_VPS.md. No MetaTrader5 terminal required.
- **Paper on any OS** — ``execution.broker: paper`` with ``data_source: oanda`` or ``mt5``

``--mode live`` requires CHRONOSCALP_CONFIRM_LIVE=yes in .env — see CLAUDE.md rule #2.
"""

from __future__ import annotations

import contextlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from chronoscalp.config import Settings, get_settings
from chronoscalp.config_overrides import unenforced_override_keys
from chronoscalp.data.spread_sampler import SpreadSampler
from chronoscalp.execution.account_mode import (
    AccountMarginMode,
    independent_same_symbol_allowed,
)
from chronoscalp.execution.mt5_broker import MT5Broker
from chronoscalp.execution.mt5_utils import StaleStopsError
from chronoscalp.execution.oanda_broker import OANDABroker
from chronoscalp.execution.position_logic import (
    apply_breakeven_or_trailing,
    check_sl_tp_hit,
    exit_price_for_hit,
)
from chronoscalp.execution.trade_manager import manage_open_position
from chronoscalp.filters.news_calendar import NewsCalendarManager
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.filters.session_filter import SessionFilter
from chronoscalp.filters.spread_shield import RollingMedianSpread
from chronoscalp.indicators.technical import enrich_with_indicators
from chronoscalp.logging_setup import logger
from chronoscalp.ml.scorer import configure_scorer
from chronoscalp.orchestration.alerts import AlertLevel, AlertNotifier
from chronoscalp.orchestration.bar_scheduler import (
    BarCloseGate,
    SignalDeduper,
    last_completed_bar_time,
    signal_dedup_key,
)
from chronoscalp.orchestration.bootstrap import (
    connector_label,
    create_broker,
    create_data_connector,
    resolve_data_source,
)
from chronoscalp.orchestration.circuit_breaker import CircuitBreaker
from chronoscalp.orchestration.comparison_books import ComparisonBooks
from chronoscalp.orchestration.kill_switch import KillSwitch
from chronoscalp.orchestration.position_keys import parse_position_key, position_key
from chronoscalp.orchestration.state_store import TradingStateStore
from chronoscalp.orchestration.strategy_attribution import AttributionLedger
from chronoscalp.orchestration.trade_journal import (
    TradeJournal,
    journal_path_for,
    load_daily_reset_marker,
    sum_closed_pnl_today,
)
from chronoscalp.risk.institutional_guards import (
    DailyDrawdownGuard,
    SpreadMovingAverageGuard,
    ThreeStrikesGuard,
    correlation_blocks,
    correlation_guard_enabled,
    effective_max_concurrent_positions,
    volatility_decision,
)
from chronoscalp.risk.mistake_memory import MistakeMemory
from chronoscalp.risk.portfolio_heat import (
    allocate_batch_risk_pct,
    open_heat_from_dollar_risks,
    reconstruct_dollar_risk,
    resolve_max_portfolio_heat_pct,
)
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.smc.structure import enrich_with_smc
from chronoscalp.strategy.live_gates import blocks_real_live_orders, unvalidated_live_symbols
from chronoscalp.strategy.multi_timeframe import (
    MultiTimeframeStrategy,
    is_shadow_only,
    resolve_enabled_strategies,
)
from chronoscalp.strategy.news_skip_reasons import NewsSkipReason
from chronoscalp.strategy.news_straddle_engine import (
    COMMENT_PREFIX as NEWS_COMMENT_PREFIX,
)
from chronoscalp.strategy.news_straddle_engine import (
    DynamicNewsStraddleEngine,
    StraddlePhase,
    StraddleSession,
)
from chronoscalp.utils.strategy_tags import (
    STRATEGY_UNKNOWN,
    mt5_comment_for_strategy,
    resolve_strategy_tag,
)
from chronoscalp.utils.types import PendingOrderSide, SignalType, Timeframe

STANDARD_TIMEFRAMES = [Timeframe.M1, Timeframe.M3, Timeframe.M5, Timeframe.M10, Timeframe.M15]


class TradingBot:
    def __init__(self, settings: Settings, mode: str) -> None:
        if mode not in ("paper", "live"):
            raise ValueError("mode must be 'paper' or 'live'")
        if mode == "live" and not settings.secrets.live_trading_confirmed:
            raise RuntimeError(
                "Refusing to start --mode live: set CHRONOSCALP_CONFIRM_LIVE=yes "
                "in .env only once you have validated the strategy in backtest "
                "and paper mode. See docs/RISK_DISCLAIMER.md."
            )

        self.settings = settings
        self.mode = mode
        enabled = resolve_enabled_strategies(settings.strategy)
        use_ultra_scalp = enabled.ultra_scalp
        use_news_straddle = enabled.news_straddle
        self.use_ultra_scalp = use_ultra_scalp
        self.use_news_straddle = use_news_straddle
        scalp_tf = (settings.raw.get("timeframes") or {}).get("ultra_scalp") or {}
        if use_ultra_scalp:
            higher_raw = settings.higher_trend_names(ultra_scalp=True)
            trigger_raw = scalp_tf.get("entry_trigger") or ["S15"]
            self.higher_timeframes = [Timeframe(tf) for tf in higher_raw]
            self.trigger_timeframe = Timeframe(trigger_raw[-1])
            self.poll_interval = int(
                scalp_tf.get(
                    "poll_interval_seconds",
                    settings.execution.get("poll_interval_seconds", 2),
                )
            )
            self.fetch_timeframes = list(
                dict.fromkeys([*self.higher_timeframes, self.trigger_timeframe, Timeframe.M1])
            )
            logger.info(
                "Ultra-scalp mode ON: higher={} trigger={} poll={}s",
                [t.value for t in self.higher_timeframes],
                self.trigger_timeframe.value,
                self.poll_interval,
            )
        else:
            self.higher_timeframes = [Timeframe(tf) for tf in settings.higher_trend_names()]
            self.trigger_timeframe = Timeframe(settings.raw["timeframes"]["entry_trigger"][-1])
            self.poll_interval = int(settings.execution.get("poll_interval_seconds", 5))
            self.fetch_timeframes = list(STANDARD_TIMEFRAMES)

        self.trade_on_bar_close = bool(settings.execution.get("trade_on_bar_close_only", True))
        self.independent_symbol_entries = bool(
            settings.risk.get("independent_symbol_entries", False)
        )
        self.max_concurrent = effective_max_concurrent_positions(
            settings.risk, len(settings.symbols)
        )
        self.state_dir = Path(settings.execution.get("state_dir", "data/state"))
        self.data_source = resolve_data_source(settings)

        self.connector = create_data_connector(settings)
        self.broker = create_broker(settings, mode=mode, connector=self.connector)

        self.session_filter = SessionFilter.from_config(settings.sessions)
        self.news_filter = NewsFilter.from_config(
            settings.news_filter,
            settings_config_dir() / "news_events.yaml",
            settings.secrets.news_api_key,
        )
        self.news_calendar = NewsCalendarManager.from_news_filter(self.news_filter)
        self.strategy = MultiTimeframeStrategy(
            settings.strategy, settings.indicators, symbols_cfg=settings.symbols_raw
        )
        self.risk_manager = RiskManager(
            risk_cfg=settings.risk,
            spread_cfg=settings.spread_filter,
            symbols_cfg=settings.symbols_raw,
            starting_equity=float(settings.backtest.get("initial_balance", 10_000)),
        )
        news_straddle_cfg = dict(settings.strategy.get("news_straddle") or {})
        self.news_straddle = DynamicNewsStraddleEngine(
            calendar=self.news_calendar,
            risk_manager=self.risk_manager,
            cfg=news_straddle_cfg,
        )
        if self.use_news_straddle:
            logger.info(
                "News straddle ON: place={}s before, pause={}m, expiry={}s, max_spread={} pips",
                news_straddle_cfg.get("place_seconds_before", 30),
                news_straddle_cfg.get("pause_minutes_before", 2),
                news_straddle_cfg.get("expiry_seconds", 120),
                news_straddle_cfg.get("max_spread_pips", 2.0),
            )

        risk_cfg = settings.risk
        strikes_cfg = risk_cfg.get("three_strikes") or {}
        self.three_strikes = ThreeStrikesGuard(
            max_losses=int(strikes_cfg.get("max_losses", 3)),
            pause_hours=int(strikes_cfg.get("pause_hours", 12)),
        )
        self.three_strikes_enabled = bool(strikes_cfg.get("enabled", True))
        self.mistake_memory = MistakeMemory.from_settings(
            risk_cfg, state_dir=self.state_dir, mode=self.mode
        )
        spread_ma_cfg = risk_cfg.get("spread_ma_guard") or {}
        self.spread_ma_guard = SpreadMovingAverageGuard(
            window=int(spread_ma_cfg.get("window", 100)),
            multiplier=float(spread_ma_cfg.get("multiplier", 2.5)),
        )
        self.spread_ma_enabled = bool(spread_ma_cfg.get("enabled", True))
        self.corr_cfg = risk_cfg.get("correlation") or {}
        self.vol_cfg = risk_cfg.get("volatility_guard") or {}
        self.partial_cfg = risk_cfg.get("partial_tp") or {}
        self.chandelier_cfg = risk_cfg.get("chandelier") or {}
        self.daily_loss_limit_enabled = bool(risk_cfg.get("daily_loss_limit_enabled", True))
        self.daily_dd_guard = DailyDrawdownGuard(
            max_daily_loss_pct=float(risk_cfg.get("max_daily_loss_pct", 3.0)),
            starting_equity=float(settings.backtest.get("initial_balance", 10_000)),
            enabled=self.daily_loss_limit_enabled,
        )
        self.daily_dd_close_all = bool(risk_cfg.get("daily_drawdown_close_all", True))
        self._book_dd_guards: dict[str, DailyDrawdownGuard] = {}
        self._book_dd_blocked: set[str] = set()
        self._position_meta: dict[int | str, dict] = {}

        state_path = self.state_dir / f"trading_state_{mode}.json"
        self.state_store = TradingStateStore(state_path)
        self.state_store.load()
        for ticket_key, meta in (self.state_store.state.position_meta or {}).items():
            payload = dict(meta)
            try:
                as_int = int(ticket_key)
            except (TypeError, ValueError):
                self._position_meta[str(ticket_key)] = payload
            else:
                self._position_meta[as_int] = payload
            symbol = str(payload.get("symbol") or "")
            strategy = str(payload.get("strategy") or "")
            if symbol and strategy:
                self._position_meta[self._meta_key(symbol, strategy)] = payload

        self.trade_journal = TradeJournal(
            journal_path_for(self.state_dir, mode),
            mode=mode,
            symbols_cfg=settings.symbols_raw,
        )
        self.trade_journal.load()

        # Re-seed today's realized P&L so restarts can't bypass the daily stop.
        # An explicit operator marker (scripts/reset_daily_tracker.py) excludes
        # trades closed before the reset.
        reset_marker = load_daily_reset_marker(self.state_dir, mode)
        today_pnl = sum_closed_pnl_today(self.trade_journal.closed_trades, since=reset_marker)
        if today_pnl:
            self.risk_manager.daily_tracker.record_trade_pnl(today_pnl)
            logger.info(
                "Daily tracker seeded from journal: realized_today={:+.2f} (reset_marker={})",
                today_pnl,
                reset_marker.isoformat() if reset_marker else "none",
            )

        resilience_cfg = settings.resilience
        self.kill_switch = KillSwitch(
            state_dir=self.state_dir,
            env_stop=settings.secrets.chronoscalp_stop_trading,
        )
        self.circuit_breaker = CircuitBreaker(
            max_consecutive_errors=int(resilience_cfg.get("max_consecutive_errors", 5)),
        )
        self.alerts = AlertNotifier.from_settings(settings.alerting, settings.secrets)
        self._alert_on_daily_loss = bool(resilience_cfg.get("alert_on_daily_loss_limit", True))
        self._alert_on_connection_loss = bool(resilience_cfg.get("alert_on_connection_loss", True))
        self._reconcile_interval = int(resilience_cfg.get("reconcile_interval_seconds", 60))
        self._last_reconcile_at: datetime | None = None
        self._daily_loss_alerted = False
        self._connection_loss_alerted = False
        self._kill_switch_alerted = False
        self._skip_counts: dict[str, int] = {}
        self._last_skip_log_at: datetime | None = None
        self._data_starvation_alerted = False
        self._last_trade_opened_at: datetime | None = None
        self._started_at: datetime | None = None
        self._skip_heartbeat_seconds = int(resilience_cfg.get("skip_heartbeat_seconds", 300))
        self._data_starvation_alert_seconds = int(
            resilience_cfg.get("data_starvation_alert_seconds", 300)
        )

        self.open_tickets: dict[str, int] = dict(self.state_store.state.open_tickets)
        self.attribution = AttributionLedger()
        self.spread_median = RollingMedianSpread()
        exec_cfg = settings.execution if isinstance(settings.execution, dict) else {}
        default_mode = "comparison" if mode == "paper" else "live"
        self.multi_strategy_mode = (
            str(exec_cfg.get("multi_strategy_mode", default_mode)).strip().lower()
        )
        if self.multi_strategy_mode not in ("comparison", "live"):
            self.multi_strategy_mode = default_mode
        self.comparison_books: ComparisonBooks | None = None
        if mode == "paper" and self.multi_strategy_mode == "comparison":
            self.comparison_books = ComparisonBooks(
                symbols_cfg=settings.symbols_raw,
                starting_balance=float(settings.backtest.get("initial_balance", 10_000)),
                slippage_pips=float(settings.execution.get("slippage_pips", 0.5)),
            )
        self._heat_reservations: dict[str, dict] = {}
        self._heat_unknown = False
        self._pending_restore_failed = False
        try:
            self._account_mode = self.broker.account_margin_mode()
        except Exception:  # noqa: BLE001
            self._account_mode = AccountMarginMode.UNKNOWN
        logger.info(
            "Multi-strategy mode={} account_margin_mode={}",
            self.multi_strategy_mode,
            self._account_mode.value,
        )
        self.bar_gate = BarCloseGate()
        for symbol, bar_iso in self.state_store.state.last_evaluated_bars.items():
            try:
                self.bar_gate.load_last_bar(symbol, datetime.fromisoformat(bar_iso))
            except ValueError:
                logger.warning("Skipping invalid last_evaluated_bar for {}: {}", symbol, bar_iso)

        self.signal_deduper = SignalDeduper(set(self.state_store.state.processed_signals))

        ml_cfg = settings.ml
        if ml_cfg.get("enabled"):
            configure_scorer(ml_cfg.get("model_path"))

        spread_cfg = settings.spread_filter
        self.spread_sampler = SpreadSampler(
            directory=spread_cfg.get("spread_history_dir", "data/spread_history"),
            enabled=bool(spread_cfg.get("sample_live_spread", False)),
        )

    def _news_currency(self, symbol: str) -> str | None:
        spec = self.settings.symbols_raw.get(symbol, {})
        return spec.get("news_currency")

    def _is_comparison_book(self) -> bool:
        """Independent virtual books: paper comparison mode only.

        Live trading always shares the 3% heat ceiling. Paper can opt into
        shared heat with ``execution.multi_strategy_mode: live``.
        """
        if self.mode == "live":
            return False
        return self.multi_strategy_mode != "live"

    def _open_key(self, symbol: str, strategy: str) -> str:
        return position_key(symbol, strategy)

    def _has_open_strategy(self, symbol: str, strategy: str) -> bool:
        return self._open_key(symbol, strategy) in self.open_tickets

    def _symbol_open_count(self, symbol: str) -> int:
        return sum(1 for key in self.open_tickets if parse_position_key(key)[0] == symbol)

    def _keys_for_symbol(self, symbol: str) -> list[str]:
        return [key for key in self.open_tickets if parse_position_key(key)[0] == symbol]

    def _register_open(self, symbol: str, strategy: str, ticket: int) -> None:
        self.open_tickets[self._open_key(symbol, strategy)] = ticket

    def _drop_ticket(
        self, ticket: int, *, symbol: str | None = None, strategy: str | None = None
    ) -> None:
        if symbol is not None and strategy is not None:
            self.open_tickets.pop(self._open_key(symbol, strategy), None)
            return
        for key, value in list(self.open_tickets.items()):
            if value != ticket:
                continue
            key_symbol, key_strategy = parse_position_key(key)
            if symbol is not None and key_symbol != symbol:
                continue
            if strategy is not None and key_strategy != strategy:
                continue
            self.open_tickets.pop(key, None)

    def _meta_key(self, symbol: str, strategy: str) -> str:
        return self._open_key(symbol, strategy)

    def _lookup_meta(self, symbol: str, strategy: str, ticket: int | None = None) -> dict:
        meta = self._position_meta.get(self._meta_key(symbol, strategy))
        if meta is None and ticket is not None:
            meta = self._position_meta.get(ticket) or self._position_meta.get(str(ticket))
        return dict(meta) if isinstance(meta, dict) else {}

    def _store_meta(
        self, symbol: str, strategy: str, meta: dict, ticket: int | None = None
    ) -> None:
        payload = dict(meta)
        payload["symbol"] = symbol
        payload["strategy"] = strategy
        if ticket is not None:
            payload["ticket"] = int(ticket)
        self._position_meta[self._meta_key(symbol, strategy)] = payload
        if ticket is None:
            return
        prior = self._position_meta.get(ticket)
        prior_strategy = str((prior or {}).get("strategy") or "")
        if prior is None or prior_strategy in {"", strategy}:
            self._position_meta[ticket] = payload

    def _clear_meta(self, symbol: str, strategy: str, ticket: int | None = None) -> None:
        self._position_meta.pop(self._meta_key(symbol, strategy), None)
        if ticket is None:
            return
        prior = self._position_meta.get(ticket)
        if prior is None or str(prior.get("strategy") or "") in {"", strategy}:
            self._position_meta.pop(ticket, None)
            self._position_meta.pop(str(ticket), None)

    def _position_matching(self, symbol: str, strategy: str, ticket: int):
        tagged: list = []
        untagged: list = []
        for pos in self._all_open_positions():
            if str(getattr(pos, "symbol", "")) != symbol or int(pos.ticket) != int(ticket):
                continue
            pos_strategy = resolve_strategy_tag(explicit=getattr(pos, "strategy", "") or "")
            if pos_strategy == strategy:
                tagged.append(pos)
            elif not pos_strategy:
                untagged.append(pos)
        if len(tagged) == 1:
            return tagged[0]
        if len(untagged) == 1 and not tagged:
            return untagged[0]
        return tagged[0] if tagged else None

    def _open_dollar_risks(self) -> list[float]:
        risks: list[float] = []
        complete = True
        for key, ticket in self.open_tickets.items():
            symbol, strategy = parse_position_key(key)
            meta = self._lookup_meta(symbol, strategy, ticket)
            stored = meta.get("dollar_risk")
            if stored is not None:
                try:
                    risks.append(float(stored))
                    continue
                except (TypeError, ValueError):
                    pass
            rebuilt = self._reconstruct_ticket_risk(
                symbol, ticket, meta, self._position_matching(symbol, strategy, ticket)
            )
            if rebuilt is None:
                complete = False
                logger.error(
                    "Heat metadata incomplete for {} ticket={} — blocking new entries",
                    key,
                    ticket,
                )
                continue
            meta["dollar_risk"] = rebuilt
            self._store_meta(symbol, strategy, meta, ticket)
            risks.append(rebuilt)
        for key, reservation in self._heat_reservations.items():
            if key in self.open_tickets and not self._reservation_has_live_pendings(reservation):
                continue
            try:
                value = float(reservation.get("dollar_risk") or 0.0)
            except (TypeError, ValueError):
                complete = False
                continue
            if value <= 0:
                complete = False
                continue
            risks.append(value)
        self._heat_unknown = (not complete) or self._pending_restore_failed
        return risks

    def _all_open_positions(self) -> list:
        found: list = []
        with contextlib.suppress(Exception):
            found.extend(self.broker.get_open_positions() or [])
        if self.comparison_books is not None:
            for book in self.comparison_books._books.values():  # noqa: SLF001
                found.extend(book.broker.get_open_positions() or [])
        return found

    def _reconstruct_ticket_risk(
        self,
        symbol: str,
        ticket: int,
        meta: dict,
        position: object | None,
    ) -> float | None:
        spec = self.settings.symbols_raw.get(symbol) or {}
        pip_size = float(spec.get("pip_size", 0.0) or 0.0)
        pip_value = float(spec.get("pip_value_per_lot", 0.0) or 0.0)
        entry = meta.get("entry_price")
        stop = meta.get("initial_stop_loss")
        volume = meta.get("initial_volume")
        if position is not None:
            entry = entry if entry is not None else getattr(position, "entry_price", None)
            stop = (
                stop
                if stop is not None
                else getattr(position, "initial_stop_loss", None)
                or getattr(position, "stop_loss", None)
            )
            volume = volume if volume is not None else getattr(position, "volume", None)
        rebuilt = reconstruct_dollar_risk(
            entry=entry,
            stop=stop,
            volume=volume,
            pip_size=pip_size,
            pip_value=pip_value,
        )
        if rebuilt is not None and position is not None:
            meta.setdefault("entry_price", float(getattr(position, "entry_price", 0) or 0))
            meta.setdefault(
                "initial_stop_loss",
                float(
                    getattr(position, "initial_stop_loss", None)
                    or getattr(position, "stop_loss", 0)
                    or 0
                ),
            )
            meta.setdefault("initial_volume", float(getattr(position, "volume", 0) or 0))
        return rebuilt

    def _broker_for(self, strategy: str):
        if self._is_comparison_book() and self.comparison_books is not None:
            return self.comparison_books.broker_for(strategy)
        return self.broker

    def _occupied_count(self, strategy: str | None = None) -> int:
        keys = set(self.open_tickets)
        keys.update(self._heat_reservations)
        if strategy is None or not self._is_comparison_book():
            return len(keys)
        return sum(1 for key in keys if parse_position_key(key)[1] == strategy)

    def _at_capacity(self, strategy: str | None = None) -> bool:
        return self._occupied_count(strategy) >= self.max_concurrent

    def _strategy_pendings(self, symbol: str, strategy: str) -> list | None:
        """List live pendings for a strategy. ``None`` means the list failed (fail-closed)."""
        broker = self._broker_for(strategy)
        prefix = mt5_comment_for_strategy(strategy)
        try:
            try:
                orders = broker.get_pending_orders(symbol, comment_prefix=prefix) or []
            except TypeError:
                orders = broker.get_pending_orders(symbol) or []
        except Exception:  # noqa: BLE001
            logger.exception("Failed listing {} pendings on {}", strategy, symbol)
            return None
        matched: list = []
        for order in orders:
            tag = self._strategy_for_pending(order)
            comment = str(getattr(order, "comment", "") or "")
            if tag == strategy or comment.startswith(prefix):
                matched.append(order)
        return matched

    def _reservation_has_live_pendings(self, reservation: dict) -> bool:
        symbol = str(reservation.get("symbol") or "")
        strategy = str(reservation.get("strategy") or "")
        if not symbol or not strategy:
            return True
        leftover = self._strategy_pendings(symbol, strategy)
        if leftover is None:
            return True
        reserved_tickets = {int(t) for t in reservation.get("tickets") or []}
        if not reserved_tickets:
            return bool(leftover)
        return any(int(order.ticket) in reserved_tickets for order in leftover)

    def _sync_heat_after_fill(self, symbol: str, strategy: str, prior: dict | None) -> None:
        leftover = self._strategy_pendings(symbol, strategy)
        if leftover is None:
            if prior:
                self._heat_reservations[self._open_key(symbol, strategy)] = dict(prior)
            self._heat_unknown = True
            self._pending_restore_failed = True
            return
        if not leftover:
            self._release_heat(symbol, strategy)
            return
        tickets = [int(order.ticket) for order in leftover]
        spec = self.settings.symbols_raw.get(symbol) or {}
        risks: list[float] = []
        for order in leftover:
            rebuilt = reconstruct_dollar_risk(
                entry=getattr(order, "price", None),
                stop=getattr(order, "stop_loss", None),
                volume=getattr(order, "volume", None),
                pip_size=float(spec.get("pip_size", 0.0) or 0.0),
                pip_value=float(spec.get("pip_value_per_lot", 0.0) or 0.0),
            )
            if rebuilt is not None and rebuilt > 0:
                risks.append(rebuilt)
        risk = max(risks) if risks else 0.0
        if risk <= 0 and prior:
            try:
                risk = float(prior.get("dollar_risk") or 0.0)
            except (TypeError, ValueError):
                risk = 0.0
        if risk <= 0:
            self._heat_unknown = True
            self._pending_restore_failed = True
            if prior:
                self._reserve_heat(
                    symbol, strategy, float(prior.get("dollar_risk") or 0.0), tickets
                )
            return
        self._reserve_heat(symbol, strategy, risk, tickets)

    def _harvest_all_reserved_fills(self, now: datetime) -> None:
        symbols = {parse_position_key(key)[0] for key in list(self._heat_reservations)}
        for symbol in symbols:
            self._harvest_pending_fills(symbol, now)

    def _daily_dd_guard_for(self, strategy: str) -> DailyDrawdownGuard:
        guard = self._book_dd_guards.get(strategy)
        if guard is None:
            try:
                starting = float(self._broker_for(strategy).get_balance())
            except Exception:  # noqa: BLE001
                starting = float(self.daily_dd_guard.starting_equity or 0.0)
            guard = DailyDrawdownGuard(
                max_daily_loss_pct=float(self.daily_dd_guard.max_daily_loss_pct),
                starting_equity=starting,
                enabled=self.daily_loss_limit_enabled,
            )
            self._book_dd_guards[strategy] = guard
        return guard

    def _book_realized_today(self, strategy: str, now: datetime) -> float:
        if self.comparison_books is None:
            return 0.0
        book = self.comparison_books.for_strategy(strategy)
        day = now.astimezone(UTC).date() if now.tzinfo else now.date()
        total = 0.0
        for trade in book.trades:
            close_at = getattr(trade, "close_time", None)
            if close_at is None:
                total += float(getattr(trade, "pnl", 0.0) or 0.0)
                continue
            close_day = (
                close_at.astimezone(UTC).date()
                if getattr(close_at, "tzinfo", None)
                else close_at.date()
            )
            if close_day == day:
                total += float(getattr(trade, "pnl", 0.0) or 0.0)
        return total

    def _close_strategy_positions(self, now: datetime, strategy: str, *, reason: str) -> None:
        for key, ticket in list(self.open_tickets.items()):
            symbol, tag = parse_position_key(key)
            if tag != strategy:
                continue
            try:
                trade = self._broker_for(tag).close_position(ticket)
                self.risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=now)
                if self.three_strikes_enabled:
                    self.three_strikes.record_result(symbol, trade.pnl, at=now, strategy=tag)
                closed = self.trade_journal.record_close(trade, ticket=ticket)
                self._record_mistake_memory(closed, at=now)
                self._clear_meta(symbol, tag, ticket)
                self.open_tickets.pop(key, None)
                self.attribution.for_strategy(tag).closed += 1
                if self.comparison_books is not None:
                    self.comparison_books.for_strategy(tag).record_close(trade, now)
                logger.warning(
                    "Force-closed {} ticket={} strategy={} reason={}",
                    symbol,
                    ticket,
                    tag,
                    reason,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed force-close {} ticket={}", symbol, ticket)
        self._persist_state()

    def _apply_comparison_book_guards(self, now: datetime) -> None:
        if not self._is_comparison_book() or self.comparison_books is None:
            return
        blocked: set[str] = set()
        names = set(self.comparison_books._books)  # noqa: SLF001
        names.update(parse_position_key(key)[1] for key in self.open_tickets)
        names.update(parse_position_key(key)[1] for key in self._heat_reservations)
        for strategy in names:
            if not strategy:
                continue
            guard = self._daily_dd_guard_for(strategy)
            try:
                equity = float(self._broker_for(strategy).get_balance())
            except Exception:  # noqa: BLE001
                equity = float(guard.starting_equity or 0.0)
            realized = self._book_realized_today(strategy, now)
            unrealized = self._estimate_unrealized_pnl(strategy=strategy)
            if guard.check(equity, realized, unrealized, at=now):
                blocked.add(strategy)
                if self.daily_dd_close_all:
                    self._close_strategy_positions(
                        now, strategy, reason=f"daily_drawdown:{strategy}"
                    )
        self._book_dd_blocked = blocked

    def _recover_news_oco_from_broker(self) -> None:
        """Rebuild News OCO state after restart, or fail-closed cancel leftovers."""
        broker = self._broker_for("news_straddle")
        prefix = NEWS_COMMENT_PREFIX
        try:
            prefix = str(self.news_straddle.comment_prefix or NEWS_COMMENT_PREFIX)
        except Exception:  # noqa: BLE001
            prefix = NEWS_COMMENT_PREFIX
        try:
            try:
                pendings = list(broker.get_pending_orders(comment_prefix=prefix) or [])
            except TypeError:
                pendings = [
                    order
                    for order in (broker.get_pending_orders() or [])
                    if str(getattr(order, "comment", "") or "").startswith(prefix)
                ]
            positions = list(broker.get_open_positions() or [])
        except Exception:  # noqa: BLE001
            logger.exception("Failed listing news OCO state after restart")
            self._heat_unknown = True
            self._pending_restore_failed = True
            return

        def _is_news_position(pos: object) -> bool:
            tag = resolve_strategy_tag(explicit=str(getattr(pos, "strategy", "") or ""))
            comment = str(getattr(pos, "comment", "") or "")
            return tag == "news_straddle" or comment.startswith(prefix)

        news_positions = [pos for pos in positions if _is_news_position(pos)]
        symbols = {str(getattr(order, "symbol", "") or "") for order in pendings}
        symbols.update(str(getattr(pos, "symbol", "") or "") for pos in news_positions)
        symbols.discard("")
        now = datetime.now(tz=UTC)
        for symbol in symbols:
            symbol_pendings = [
                order for order in pendings if str(getattr(order, "symbol", "") or "") == symbol
            ]
            symbol_positions = [
                pos for pos in news_positions if str(getattr(pos, "symbol", "") or "") == symbol
            ]
            session = self.news_straddle.sessions.get(symbol)
            if symbol_positions and symbol_pendings:
                leftover_tickets = [int(order.ticket) for order in symbol_pendings]
                for ticket in leftover_tickets:
                    try:
                        broker.cancel_pending_order(ticket)
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "Failed cancelling leftover news pending ticket={} on {}",
                            ticket,
                            symbol,
                        )
                try:
                    try:
                        still = broker.get_pending_orders(symbol, comment_prefix=prefix) or []
                    except TypeError:
                        still = [
                            order
                            for order in (broker.get_pending_orders(symbol) or [])
                            if str(getattr(order, "comment", "") or "").startswith(prefix)
                        ]
                except Exception:  # noqa: BLE001
                    logger.exception("Failed verifying news leftover cancel on {}", symbol)
                    self._heat_unknown = True
                    self._pending_restore_failed = True
                    still = symbol_pendings
                if still:
                    logger.error(
                        "News leftover pending remains on {} after cancel — fail-closed heat",
                        symbol,
                    )
                    self._heat_unknown = True
                    self._pending_restore_failed = True
                    prior = self._heat_reservations.get(self._open_key(symbol, "news_straddle"))
                    self._sync_heat_after_fill(symbol, "news_straddle", prior)
                filled = symbol_positions[0]
                self.news_straddle.sessions[symbol] = StraddleSession(
                    symbol=symbol,
                    event_title=getattr(session, "event_title", "") if session else "recovered",
                    event_time=getattr(session, "event_time", now) if session else now,
                    phase=StraddlePhase.FILLED,
                    buy_ticket=None if not still else getattr(session, "buy_ticket", None),
                    sell_ticket=None if not still else getattr(session, "sell_ticket", None),
                    filled_position_ticket=int(filled.ticket),
                    volume=float(getattr(filled, "volume", 0.0) or 0.0),
                    dollar_risk=float(
                        self._lookup_meta(symbol, "news_straddle", int(filled.ticket)).get(
                            "dollar_risk"
                        )
                        or 0.0
                    ),
                )
                continue
            if symbol_pendings and not symbol_positions:
                buy_ticket = None
                sell_ticket = None
                for order in symbol_pendings:
                    comment = str(getattr(order, "comment", "") or "")
                    side = getattr(order, "side", None)
                    is_buy = "News_B" in comment or side in (
                        PendingOrderSide.BUY_STOP,
                        getattr(PendingOrderSide, "BUY", None),
                    )
                    if is_buy:
                        buy_ticket = int(order.ticket)
                    else:
                        sell_ticket = int(order.ticket)
                self.news_straddle.sessions[symbol] = StraddleSession(
                    symbol=symbol,
                    event_title=getattr(session, "event_title", "") if session else "recovered",
                    event_time=getattr(session, "event_time", now) if session else now,
                    phase=StraddlePhase.PENDING,
                    buy_ticket=buy_ticket,
                    sell_ticket=sell_ticket,
                    volume=float(getattr(symbol_pendings[0], "volume", 0.0) or 0.0),
                )
                continue
            if symbol_positions and not symbol_pendings:
                filled = symbol_positions[0]
                self.news_straddle.sessions[symbol] = StraddleSession(
                    symbol=symbol,
                    event_title=getattr(session, "event_title", "") if session else "recovered",
                    event_time=getattr(session, "event_time", now) if session else now,
                    phase=StraddlePhase.FILLED,
                    filled_position_ticket=int(filled.ticket),
                    volume=float(getattr(filled, "volume", 0.0) or 0.0),
                )

    def _place_deferred_news(
        self,
        symbol: str,
        now: datetime,
        *,
        spread_pips: float,
        currency: str | None,
        risk_pct: float,
    ) -> None:
        """Place a news bracket after the same-tick fair batch has been allocated."""
        news_broker = self._broker_for("news_straddle")
        news_already = self._has_open_strategy(symbol, "news_straddle")
        m1_for_straddle = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=40)
        if m1_for_straddle is None or getattr(m1_for_straddle, "empty", True):
            m1_for_straddle = pd.DataFrame()
        else:
            atr_period = int(
                (self.settings.strategy.get("news_straddle") or {}).get("atr_period", 14)
            )
            m1_for_straddle = enrich_with_indicators(m1_for_straddle, atr_period=atr_period)
        news_key = self._open_key(symbol, "news_straddle")
        allocated = float(news_broker.get_balance()) * float(risk_pct) / 100.0
        if news_key not in self._heat_reservations:
            self._reserve_heat(symbol, "news_straddle", allocated, [])
        straddle_res = self.news_straddle.tick(
            news_broker,
            symbol=symbol,
            moment=now,
            m1_df=m1_for_straddle,
            spread_pips=spread_pips,
            currency=currency,
            already_open=news_already,
            allow_place=True,
            abort_pending=False,
            placement_block_reason=None,
            risk_pct=risk_pct,
        )
        if straddle_res.action == "placed" and straddle_res.session is not None:
            sess = straddle_res.session
            tickets = [t for t in (sess.buy_ticket, sess.sell_ticket) if t is not None]
            reserved = self._heat_reservations.get(news_key) or {}
            cap = float(reserved.get("dollar_risk") or allocated)
            risk = float(sess.dollar_risk or cap)
            if cap > 0 and risk > cap + 1e-9:
                risk = cap
            self._reserve_heat(symbol, "news_straddle", risk, tickets)
        elif straddle_res.action in ("expired", "aborted"):
            self._release_heat(symbol, "news_straddle")
        if straddle_res.opened_position is not None:
            position = straddle_res.opened_position
            already = (
                self.open_tickets.get(self._open_key(symbol, "news_straddle")) == position.ticket
            )
            if not already:
                reserved = dict(self._heat_reservations.get(news_key) or {})
                dollar_risk = float(reserved.get("dollar_risk") or 0.0)
                if dollar_risk <= 0 and straddle_res.session is not None:
                    dollar_risk = float(straddle_res.session.dollar_risk or 0.0)
                self._register_open(symbol, "news_straddle", position.ticket)
                self._store_meta(
                    symbol,
                    "news_straddle",
                    {
                        "symbol": symbol,
                        "initial_volume": position.volume,
                        "initial_stop_loss": position.stop_loss,
                        "entry_price": position.entry_price,
                        "dollar_risk": dollar_risk,
                        "partial_taken": False,
                        "breakeven_moved": False,
                        "strategy": "news_straddle",
                        "reason": "news_straddle",
                    },
                    position.ticket,
                )
                self._sync_heat_after_fill(symbol, "news_straddle", reserved)

    def _committed_heat_pct(self, equity: float) -> float:
        return open_heat_from_dollar_risks(self._open_dollar_risks(), equity)

    def _reserve_heat(
        self,
        symbol: str,
        strategy: str,
        dollar_risk: float,
        tickets: list[int],
    ) -> None:
        self._heat_reservations[self._open_key(symbol, strategy)] = {
            "symbol": symbol,
            "strategy": strategy,
            "dollar_risk": float(dollar_risk),
            "tickets": [int(t) for t in tickets],
        }

    def _release_heat(self, symbol: str, strategy: str) -> dict | None:
        return self._heat_reservations.pop(self._open_key(symbol, strategy), None)

    def _execution_brokers(self) -> list:
        brokers = [self.broker]
        if self.comparison_books is not None:
            for book in self.comparison_books._books.values():  # noqa: SLF001
                brokers.append(book.broker)
        unique: list = []
        seen: set[int] = set()
        for broker in brokers:
            marker = id(broker)
            if marker in seen:
                continue
            seen.add(marker)
            unique.append(broker)
        return unique

    def _strategy_for_pending(self, order: object) -> str | None:
        """Return a canonical strategy, empty string to skip, or None to fail-closed."""
        explicit = str(getattr(order, "strategy", "") or "")
        comment = str(getattr(order, "comment", "") or "")
        tag = resolve_strategy_tag(explicit=explicit, comment=comment, reason=comment)
        if tag != STRATEGY_UNKNOWN:
            return tag
        if comment.upper().startswith("CS_"):
            return None
        return ""

    def _restore_pending_heat_reservations(self) -> None:
        """Rebuild in-memory heat from broker pendings after restart/reconcile.

        Harvest fills *before* overwriting reservations so a fill between
        reconciles cannot drop heat. Fail-closed: listing failure keeps prior
        reservations and blocks new entries.
        """
        prior = {key: dict(value) for key, value in self._heat_reservations.items()}
        now = datetime.now(tz=UTC)
        self._harvest_all_reserved_fills(now)
        prior_after_harvest = {key: dict(value) for key, value in self._heat_reservations.items()}
        grouped: dict[str, list] = {}
        complete = True
        try:
            pending: list = []
            for broker in self._execution_brokers():
                pending.extend(broker.get_pending_orders() or [])
        except Exception:  # noqa: BLE001
            logger.exception("Failed listing pending orders while restoring heat")
            self._pending_restore_failed = True
            self._heat_unknown = True
            if not self._heat_reservations and prior:
                self._heat_reservations = prior
            return

        for order in pending:
            strategy = self._strategy_for_pending(order)
            if strategy is None:
                logger.error(
                    "Managed pending ticket={} comment={!r} has no strategy — blocking new entries",
                    getattr(order, "ticket", "?"),
                    getattr(order, "comment", ""),
                )
                complete = False
                continue
            if not strategy:
                continue
            symbol = str(getattr(order, "symbol", "") or "")
            if not symbol:
                complete = False
                continue
            key = self._open_key(symbol, strategy)
            grouped.setdefault(key, []).append(order)

        rebuilt: dict[str, dict] = {}
        for key, orders in grouped.items():
            symbol, strategy = parse_position_key(key)
            tickets = [int(order.ticket) for order in orders]
            risks: list[float] = []
            for order in orders:
                rebuilt_risk = reconstruct_dollar_risk(
                    entry=getattr(order, "price", None),
                    stop=getattr(order, "stop_loss", None),
                    volume=getattr(order, "volume", None),
                    pip_size=float(
                        (self.settings.symbols_raw.get(symbol) or {}).get("pip_size", 0.0) or 0.0
                    ),
                    pip_value=float(
                        (self.settings.symbols_raw.get(symbol) or {}).get("pip_value_per_lot", 0.0)
                        or 0.0
                    ),
                )
                if rebuilt_risk is None or rebuilt_risk <= 0:
                    logger.error(
                        "Pending heat geometry unusable for {} ticket={} — blocking new entries",
                        key,
                        getattr(order, "ticket", "?"),
                    )
                    complete = False
                    continue
                risks.append(rebuilt_risk)
            # News OCO places two legs; only one fills, so reserve the larger leg
            # until the leftover is cancelled. Leftover + open is counted in
            # ``_open_dollar_risks``.
            dollar_risk = max(risks) if risks else 0.0
            rebuilt[key] = {
                "symbol": symbol,
                "strategy": strategy,
                "dollar_risk": float(dollar_risk),
                "tickets": tickets,
            }

        merged: dict[str, dict] = dict(rebuilt)
        for key, reservation in prior_after_harvest.items():
            if key in merged:
                with contextlib.suppress(TypeError, ValueError):
                    merged[key]["dollar_risk"] = max(
                        float(merged[key].get("dollar_risk") or 0.0),
                        float(reservation.get("dollar_risk") or 0.0),
                    )
                continue
            if key in self.open_tickets:
                if self._reservation_has_live_pendings(reservation):
                    merged[key] = reservation
                continue
            # Pending vanished and no open yet — fill in flight. Never drop heat.
            merged[key] = reservation
        self._heat_reservations = merged
        if not complete:
            self._pending_restore_failed = True
            self._heat_unknown = True
        else:
            self._pending_restore_failed = False
            if rebuilt:
                logger.info(
                    "Restored heat reservations from {} pending group(s)",
                    len(rebuilt),
                )
        self._recover_news_oco_from_broker()

    def _sync_quote(self, symbol: str, bid: float, ask: float, at: datetime) -> None:
        if hasattr(self.broker, "set_quote"):
            self.broker.set_quote(symbol, bid, ask, at)
        if self.comparison_books is not None:
            self.comparison_books.set_quote(symbol, bid, ask, at)

    def _publish_last_bar_quote(self, symbol: str, spread_pips: float, now: datetime) -> None:
        """Push last M1 mid as bid/ask so paper stop-pendings can fill on a real cross."""
        if not hasattr(self.broker, "set_quote") and self.comparison_books is None:
            return
        try:
            m1 = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=3)
        except Exception:  # noqa: BLE001
            return
        if m1 is None or m1.empty:
            return
        mid = float(m1["close"].iloc[-1])
        pip_size = float(self.settings.symbols_raw.get(symbol, {}).get("pip_size", 0.01) or 0.01)
        half = max(spread_pips, 0.0) * pip_size / 2.0
        self._sync_quote(symbol, mid - half, mid + half, now)

    def _same_symbol_netting_blocked(self, symbol: str, strategy: str) -> bool:
        if self._is_comparison_book():
            return False
        occupied = self._symbol_open_count(symbol)
        reserved = sum(
            1
            for key in self._heat_reservations
            if parse_position_key(key)[0] == symbol and parse_position_key(key)[1] != strategy
        )
        if occupied + reserved <= 0:
            return False
        return not independent_same_symbol_allowed(self._account_mode)

    def _positions_for_reconcile(self) -> list:
        """Open positions that own live/paper state, including comparison books."""
        if self.mode == "live" and isinstance(self.broker, MT5Broker):
            try:
                return list(self.broker.get_managed_positions() or [])
            except Exception:  # noqa: BLE001
                logger.exception("Failed listing managed live positions for reconcile")
        found: list = []
        for broker in self._execution_brokers():
            with contextlib.suppress(Exception):
                found.extend(broker.get_open_positions() or [])
        return found

    def _cancel_strategy_pendings(self, symbol: str, strategy: str) -> None:
        """Cancel working stops; keep heat reserved until the broker no longer holds them."""
        key = self._open_key(symbol, strategy)
        reservation = self._heat_reservations.get(key)
        tickets = [int(t) for t in (reservation or {}).get("tickets") or []]
        broker = self._broker_for(strategy)
        prefix = mt5_comment_for_strategy(strategy)
        try:
            for order in broker.get_pending_orders(symbol, comment_prefix=prefix) or []:
                tickets.append(int(order.ticket))
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed listing {} pendings on {} — keeping heat reserved",
                strategy,
                symbol,
            )
            return
        for ticket in dict.fromkeys(tickets):
            try:
                broker.cancel_pending_order(int(ticket))
            except Exception:  # noqa: BLE001
                logger.warning("Failed cancelling {} pending ticket={}", strategy, ticket)
        try:
            leftover = broker.get_pending_orders(symbol, comment_prefix=prefix) or []
        except Exception:  # noqa: BLE001
            logger.exception(
                "Failed re-listing {} pendings on {} after cancel — keeping heat reserved",
                strategy,
                symbol,
            )
            self._heat_unknown = True
            self._pending_restore_failed = True
            return
        if leftover:
            if reservation is not None:
                reservation["tickets"] = [int(order.ticket) for order in leftover]
            return
        self._harvest_pending_fills(symbol, datetime.now(tz=UTC))
        if key not in self.open_tickets:
            self._release_heat(symbol, strategy)

    def _harvest_pending_fills(self, symbol: str, now: datetime) -> None:
        """Promote filled stop orders into open tickets and drop their heat reservation."""
        for key, reservation in list(self._heat_reservations.items()):
            res_symbol, strategy = parse_position_key(key)
            if res_symbol != symbol:
                continue
            if key in self.open_tickets:
                continue
            broker = self._broker_for(strategy)
            try:
                positions = broker.get_open_positions(symbol) or []
            except Exception:  # noqa: BLE001
                continue
            pending_tickets = {int(t) for t in reservation.get("tickets") or []}
            filled = None
            for pos in positions:
                if str(getattr(pos, "strategy", "") or "") == strategy:
                    filled = pos
                    break
                if int(pos.ticket) in pending_tickets:
                    filled = pos
                    break
            if filled is None:
                continue
            self._register_open(symbol, strategy, filled.ticket)
            dollar_risk = float(reservation.get("dollar_risk") or 0.0)
            self._store_meta(
                symbol,
                strategy,
                {
                    "symbol": symbol,
                    "initial_volume": filled.volume,
                    "initial_stop_loss": filled.stop_loss,
                    "entry_price": filled.entry_price,
                    "dollar_risk": dollar_risk,
                    "partial_taken": False,
                    "breakeven_moved": False,
                    "strategy": strategy,
                    "reason": strategy,
                },
                filled.ticket,
            )
            if not getattr(filled, "strategy", ""):
                filled.strategy = strategy
            self.attribution.for_strategy(strategy).filled += 1
            self.trade_journal.record_open(filled, strategy=strategy, reason=strategy)
            self._last_trade_opened_at = now
            self._sync_heat_after_fill(symbol, strategy, reservation)
            if self.comparison_books is not None:
                self.comparison_books.for_strategy(strategy).mark_equity(now)
            self._persist_state()

    def start(self) -> None:
        if not self.connector.connect():
            raise RuntimeError(
                f"Failed to connect to {connector_label(self.connector)} for market data. "
                "Check credentials in .env and docs/DEPLOY_NL_VPS.md for OANDA setup."
            )
        if not self.broker.connect():
            raise RuntimeError("Failed to connect broker")

        self._reconcile_state_with_broker()
        self._last_reconcile_at = datetime.now(tz=UTC)
        self._started_at = self._last_reconcile_at
        self._seed_daily_equity_from_broker()

        poll_seconds = int(self.poll_interval)
        logger.info(
            "ChronoScalp started in {} mode (data={}, broker={}), polling every {}s (bar_close_only={})",
            self.mode,
            self.data_source,
            self.settings.execution.get("broker", "paper"),
            poll_seconds,
            self.trade_on_bar_close,
        )
        self._log_entry_gate_profile()
        if self.alerts.is_configured:
            self.alerts.notify(
                "Bot started",
                f"mode={self.mode}, symbols={','.join(self.settings.symbols)}",
                AlertLevel.INFO,
            )
        if self.kill_switch.is_active():
            logger.warning("Kill switch active at startup — new entries disabled")

        try:
            while True:
                if self.kill_switch.check_and_log():
                    prev = self._kill_switch_alerted
                    if not prev:
                        self.alerts.notify(
                            "Kill switch active",
                            self.kill_switch.reason() or "unknown",
                            AlertLevel.CRITICAL,
                        )
                    self._kill_switch_alerted = True
                else:
                    self._kill_switch_alerted = False
                self.tick()
                time.sleep(poll_seconds)
        except KeyboardInterrupt:
            logger.info("Shutdown requested, stopping.")
        finally:
            self._persist_state()
            self.connector.shutdown()

    def _reconcile_state_with_broker(self, *, alert_on_change: bool = False) -> None:
        previous = dict(self.open_tickets)
        managed = self._positions_for_reconcile()
        now = datetime.now(tz=UTC)
        broker_map: dict[str, int] = {}
        ticket_strategies: dict[int, str] = {}
        for pos in managed:
            tag = resolve_strategy_tag(explicit=getattr(pos, "strategy", "") or "")
            key = position_key(pos.symbol, tag)
            broker_map[key] = pos.ticket
            ticket_strategies[pos.ticket] = tag
        # Match by (symbol, strategy), not raw ticket: comparison books can reuse ticket ids.
        for key, ticket in list(previous.items()):
            if broker_map.get(key) != ticket:
                symbol, strategy = parse_position_key(key)
                self._on_position_closed_externally(symbol, ticket, now, strategy=strategy)
        self.state_store.reconcile_open_tickets(broker_map, ticket_strategies=ticket_strategies)
        self.open_tickets = dict(self.state_store.state.open_tickets)
        self.trade_journal.sync_open_from_broker(managed, now=now)
        self._restore_pending_heat_reservations()
        self._open_dollar_risks()
        self._write_broker_positions_snapshot()

        if alert_on_change and previous != self.open_tickets:
            self.alerts.notify(
                "State reconciled",
                f"before={previous} after={self.open_tickets}",
                AlertLevel.WARNING,
            )

    def _write_broker_positions_snapshot(self) -> None:
        """Persist live account positions for Telegram/dashboard (all magics)."""
        path = self.state_dir / f"broker_positions_{self.mode}.json"
        rows: list[dict] = []
        account: dict = {}
        try:
            if isinstance(self.broker, MT5Broker):
                rows = self.broker.snapshot_account_positions()
                account = self.broker.snapshot_account_summary()
            else:
                for p in self.broker.get_open_positions():
                    direction = (
                        p.direction.value if hasattr(p.direction, "value") else str(p.direction)
                    )
                    rows.append(
                        {
                            "ticket": int(p.ticket),
                            "symbol": str(p.symbol),
                            "direction": direction,
                            "volume": float(p.volume),
                            "entry_price": float(p.entry_price),
                            "stop_loss": float(p.stop_loss),
                            "take_profit": float(p.take_profit),
                            "profit": 0.0,
                            "magic": 0,
                            "comment": "",
                            "strategy": str(getattr(p, "strategy", "") or ""),
                            "open_time": p.open_time.isoformat() if p.open_time else "",
                        }
                    )
                try:
                    bal = float(self.broker.get_balance())
                    account = {
                        "equity": bal,
                        "balance": bal,
                        "margin": 0.0,
                        "profit": 0.0,
                        "login": 0,
                        "server": "",
                    }
                except Exception:  # noqa: BLE001
                    account = {}
            # Prefer journal strategy attribution when broker comment is blank/legacy.
            for row in rows:
                ticket = int(row.get("ticket") or 0)
                journal_open = self.trade_journal.open_trades.get(ticket)
                meta = self._lookup_meta(
                    str(row.get("symbol") or ""),
                    str(row.get("strategy") or ""),
                    ticket,
                )
                row["strategy"] = resolve_strategy_tag(
                    explicit=str(
                        row.get("strategy")
                        or (journal_open.strategy if journal_open else "")
                        or meta.get("strategy")
                        or ""
                    ),
                    reason=str(
                        (journal_open.reason if journal_open else "") or meta.get("reason") or ""
                    ),
                    comment=str(row.get("comment") or ""),
                )
            payload = {
                "mode": self.mode,
                "updated_at": datetime.now(tz=UTC).isoformat(),
                "account": account,
                "positions": rows,
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("Failed writing broker positions snapshot to {}", path)

    def _maybe_reconcile(self, now: datetime) -> None:
        if self._reconcile_interval <= 0:
            return
        if self._last_reconcile_at is None:
            self._reconcile_state_with_broker(alert_on_change=True)
            self._last_reconcile_at = now
            return
        elapsed = (now - self._last_reconcile_at).total_seconds()
        if elapsed >= self._reconcile_interval:
            self._reconcile_state_with_broker(alert_on_change=True)
            self._last_reconcile_at = now

    def _log_entry_gate_profile(self) -> None:
        """Log every gate that can suppress an entry, plus inert override keys.

        Low live trade counts are usually a configuration result, not a bug, so
        the effective profile belongs in the log next to the startup banner
        rather than only in the 5-minute skip heartbeat.
        """
        strategy_cfg = self.settings.strategy
        enabled = resolve_enabled_strategies(strategy_cfg)
        active = enabled.names()
        sessions_cfg = self.settings.sessions
        risk_cfg = self.settings.risk
        logger.info(
            "Entry gate profile: strategies=[{}] symbols=[{}] max_concurrent={} "
            "sessions={} trade_outside={} news_filter={} risk_pct={} min_rr={} "
            "broker_class={} broker_cfg={}",
            ",".join(active) or "none",
            ",".join(self.settings.symbols),
            self.max_concurrent,
            sessions_cfg.get("trading_hours_mode", "london_ny"),
            sessions_cfg.get("trade_outside_sessions", False),
            (self.settings.news_filter or {}).get("enabled", True),
            risk_cfg.get("active_risk_per_trade_pct", risk_cfg.get("max_risk_per_trade_pct")),
            risk_cfg.get("min_reward_risk_ratio"),
            type(self.broker).__name__,
            self.settings.execution.get("broker"),
        )
        logger.info(
            "Entry guards: three_strikes={} mistake_memory={} correlation={} "
            "volatility={} spread_ma={} daily_loss_lock={}",
            self.three_strikes_enabled,
            self.mistake_memory.config.enabled,
            bool(self.corr_cfg.get("enabled", False)),
            bool(self.vol_cfg.get("enabled", True)),
            self.spread_ma_enabled,
            self.daily_loss_limit_enabled,
        )
        logger.info(
            "Stop geometry: trailing_start={}R trailing_atr={} delta_stop_atr_source={}({}) "
            "spread_ma_multiplier={}",
            risk_cfg.get("trailing_start_r_multiple"),
            risk_cfg.get("trailing_stop_atr_multiple"),
            (strategy_cfg.get("delta") or {}).get("stop_atr_source", "trigger"),
            self._delta_stop_frame_name(strategy_cfg),
            (risk_cfg.get("spread_ma_guard") or {}).get("multiplier"),
        )
        self._log_unvalidated_symbols(strategy_cfg, active)
        if not active:
            logger.warning(
                "No entry strategy is enabled — the bot will never open a position. "
                "Enable one via Telegram Settings -> Strategies or "
                "strategy.enabled_strategies in config."
            )
        inert = unenforced_override_keys(getattr(self.settings, "runtime_overrides", {}))
        if inert:
            logger.warning(
                "Runtime overrides set {} key(s) that no code path enforces yet: {}. "
                "Do not rely on them as risk controls.",
                len(inert),
                ", ".join(inert),
            )

    def _delta_stop_frame_name(self, strategy_cfg: dict) -> str:
        """Timeframe Delta's stop distance is measured on, for the startup log.

        Logging the raw index made the gate profile unreadable: ``htf(1)`` does
        not say whether the M1-ATR fix is actually in effect.
        """
        delta = strategy_cfg.get("delta") or {}
        if str(delta.get("stop_atr_source", "trigger")).lower() != "htf":
            return str(self.trigger_timeframe.value)
        frames = [tf.value for tf in self.higher_timeframes]
        if not frames:
            return str(self.trigger_timeframe.value)
        index = min(max(0, int(delta.get("stop_atr_htf_index", 0) or 0)), len(frames) - 1)
        return str(frames[index])

    def _log_unvalidated_symbols(self, strategy_cfg: dict, active: list[str]) -> None:
        """Warn when an enabled strategy will trade a symbol it has no edge on.

        Reported, not enforced — the operator chose the symbol list. But Delta
        measured PF 1.754 on XAUUSD and four straight full stop-outs on EURUSD
        in the same window, so which symbol is carrying that verdict belongs in
        the startup record rather than only in a doc.
        """
        for strategy_id in active:
            block = strategy_cfg.get(strategy_id)
            if not isinstance(block, dict) or "symbol_validation" not in block:
                continue
            allowed = [str(s) for s in (block.get("allowed_symbols") or [])]
            scope = [s for s in self.settings.symbols if not allowed or s in allowed]
            risky = unvalidated_live_symbols(strategy_cfg, strategy_id, scope)
            if not risky:
                continue
            logger.warning(
                "{} has no positive broker-native evidence for {} — live risk on "
                "these symbols is unvalidated (see docs/STRATEGY_DELTA.md)",
                strategy_id,
                ", ".join(risky),
            )

    def _note_skip(self, reason: str) -> None:
        self._skip_counts[reason] = self._skip_counts.get(reason, 0) + 1

    def _maybe_log_skip_heartbeat(self, now: datetime) -> None:
        if self._last_skip_log_at is None:
            self._last_skip_log_at = now
            return
        if (now - self._last_skip_log_at).total_seconds() < self._skip_heartbeat_seconds:
            return
        if self._skip_counts:
            summary = ", ".join(f"{k}={v}" for k, v in sorted(self._skip_counts.items()))
            logger.info("Entry skip heartbeat ({}s): {}", self._skip_heartbeat_seconds, summary)
        else:
            logger.info(
                "Entry skip heartbeat ({}s): no skips recorded", self._skip_heartbeat_seconds
            )
        self._skip_counts.clear()
        self._last_skip_log_at = now

    def _check_data_health(self, now: datetime) -> None:
        """Reconnect + alert when market data has been empty too long."""
        ensure = getattr(self.connector, "ensure_connected", None)
        if callable(ensure):
            ensure()

        last_ok = getattr(self.connector, "last_successful_fetch_at", None)
        if last_ok is None:
            if self._started_at is None:
                return
            age = (now - self._started_at).total_seconds()
        else:
            age = (now - last_ok).total_seconds()

        if age < self._data_starvation_alert_seconds:
            self._data_starvation_alerted = False
            return
        if self._data_starvation_alerted:
            return
        self._data_starvation_alerted = True
        msg = (
            f"No successful market-data fetch for {int(age)}s "
            f"(threshold={self._data_starvation_alert_seconds}s). "
            "Check MT5 terminal login / Market Watch symbols."
        )
        logger.error(msg)
        self.alerts.notify("Data starvation", msg, AlertLevel.ERROR)
        if callable(ensure):
            ensure()

    def _min_rr_for_signal(self, signal) -> float:
        from chronoscalp.risk.position_sizing import HARD_MIN_GROSS_RR

        if "ultra_scalp" in (signal.reason or ""):
            scalp = self.settings.strategy.get("ultra_scalp") or {}
            requested = float(scalp.get("min_reward_risk_ratio", HARD_MIN_GROSS_RR))
        else:
            requested = float(self.settings.risk.get("min_reward_risk_ratio", HARD_MIN_GROSS_RR))
        return max(HARD_MIN_GROSS_RR, requested)

    def _persist_state(self) -> None:
        self.state_store.state.open_tickets = dict(self.open_tickets)
        self.state_store.state.processed_signals = sorted(self.signal_deduper.processed_keys)
        self.state_store.state.last_evaluated_bars = {
            sym: ts.isoformat() for sym, ts in self.bar_gate.last_evaluated_bars().items()
        }
        self.state_store.state.position_meta = {
            str(ticket): dict(meta) for ticket, meta in self._position_meta.items()
        }
        self.state_store.save()

    def _seed_daily_equity_from_broker(self) -> None:
        """Align daily-loss bases with live account equity (not backtest config)."""
        try:
            bal = float(self.broker.get_balance())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not seed daily equity from broker: {}", exc)
            return
        if bal <= 0:
            return
        self.risk_manager.daily_tracker.starting_equity = bal
        self.daily_dd_guard.starting_equity = bal
        self.daily_dd_guard.day_utc = datetime.now(tz=UTC).date()
        logger.info("Daily risk seeded from live equity={:.2f}", bal)

    def _mark_engine_bars_evaluated(
        self,
        symbol: str,
        *,
        run_scalp: bool,
        scalp_bar: datetime | None,
        run_institutional: bool,
        inst_bar: datetime | None,
    ) -> None:
        if not self.trade_on_bar_close:
            return
        if run_scalp and scalp_bar is not None:
            self.bar_gate.mark_evaluated(f"{symbol}:scalp", scalp_bar)
        if run_institutional and inst_bar is not None:
            self.bar_gate.mark_evaluated(f"{symbol}:inst", inst_bar)

    def tick(self) -> None:
        now = datetime.now(tz=UTC)
        self._maybe_reconcile(now)
        self._restore_pending_heat_reservations()
        self._check_data_health(now)
        tick_had_failure = False
        failure_context = ""

        if not self.connector.is_connected:
            tick_had_failure = True
            failure_context = "data_disconnect"
            if self._alert_on_connection_loss and not self._connection_loss_alerted:
                self.alerts.notify(
                    f"{connector_label(self.connector)} connection lost",
                    "Market data connector is disconnected — skipping new entries",
                    AlertLevel.ERROR,
                )
                self._connection_loss_alerted = True
        else:
            self._connection_loss_alerted = False

        kill_active = self.kill_switch.is_active()
        circuit_tripped = self.circuit_breaker.is_tripped
        equity_now = self.broker.get_balance()
        unrealized = self._estimate_unrealized_pnl()
        realized = float(self.risk_manager.daily_tracker._realized_pnl_today)
        comparison_mode = self._is_comparison_book()
        daily_dd_hit = False
        if not comparison_mode:
            daily_dd_hit = self.daily_dd_guard.check(equity_now, realized, unrealized, at=now)
        # Keep DailyRiskTracker base equity aligned with the DD guard day seed.
        if self.daily_dd_guard.starting_equity > 0:
            self.risk_manager.daily_tracker.starting_equity = float(
                self.daily_dd_guard.starting_equity
            )
        daily_limit_hit = False
        if not comparison_mode:
            daily_limit_hit = daily_dd_hit or self.risk_manager.daily_tracker.daily_loss_limit_hit(
                at=now
            )
        if daily_dd_hit and self.daily_dd_close_all:
            self._close_all_positions(now, reason="daily_drawdown")
        if comparison_mode:
            self._apply_comparison_book_guards(now)
        if daily_limit_hit and self._alert_on_daily_loss and not self._daily_loss_alerted:
            self.alerts.notify(
                "Daily loss limit hit",
                "No new entries until the next trading day",
                AlertLevel.WARNING,
            )
            self._daily_loss_alerted = True
        if not daily_limit_hit:
            self._daily_loss_alerted = False

        allow_new_entries = (
            self.connector.is_connected
            and not kill_active
            and not circuit_tripped
            and not daily_limit_hit
            and not self.daily_dd_guard.blocked
        )
        if not allow_new_entries:
            if not self.connector.is_connected:
                self._note_skip("data_disconnect")
            if kill_active:
                self._note_skip("kill_switch")
            if circuit_tripped:
                self._note_skip("circuit_breaker")
            if daily_limit_hit:
                self._note_skip("daily_loss_limit")

        for symbol in self.settings.symbols:
            try:
                spread_pips = self.broker.get_current_spread_pips(symbol)
                self.spread_sampler.record(symbol, spread_pips, at=now)
                self.spread_ma_guard.observe(symbol, spread_pips)
                self.spread_median.observe(symbol, spread_pips)
                self._publish_last_bar_quote(symbol, spread_pips, now)

                self._manage_open_position(symbol, now)
                self._harvest_pending_fills(symbol, now)

                enabled = resolve_enabled_strategies(self.settings.strategy)
                use_smc, use_liq, use_scalp, use_news_straddle = (
                    enabled.smc,
                    enabled.liquidity,
                    enabled.ultra_scalp,
                    enabled.news_straddle,
                )
                currency = self._news_currency(symbol)
                news_wants_place = False

                # News straddle management (OCO / expiry / abort) must run even when
                # kill switch / daily loss blocks *new* entries — otherwise pending
                # brackets are left unmanaged.
                if use_news_straddle:
                    session = self.news_straddle.sessions.get(symbol)
                    needs_manage = session is not None and session.phase.value in (
                        "pending",
                        "filled",
                    )
                    at_capacity = self._at_capacity(
                        "news_straddle" if self._is_comparison_book() else None
                    )
                    three_paused = self.three_strikes_enabled and self.three_strikes.is_paused(
                        symbol,
                        at=now,
                        strategy="news_straddle" if self._is_comparison_book() else "",
                    )
                    in_session = self.session_filter.is_within_session(now, symbol=symbol)
                    news_session_ok = in_session or not self.news_straddle.require_session
                    news_already = self._has_open_strategy(symbol, "news_straddle")
                    news_broker = self._broker_for("news_straddle")
                    news_risk_pct: float | None = None
                    netting_blocked = self._same_symbol_netting_blocked(symbol, "news_straddle")
                    heat_blocked = False
                    if allow_new_entries and not news_already and not self._is_comparison_book():
                        self._open_dollar_risks()
                        if self._heat_unknown:
                            heat_blocked = True
                    allow_place = (
                        allow_new_entries
                        and not news_already
                        and not three_paused
                        and not at_capacity
                        and news_session_ok
                        and not netting_blocked
                        and not heat_blocked
                    )
                    abort_pending = (
                        not allow_new_entries
                        and session is not None
                        and session.phase.value == "pending"
                    )
                    run_straddle = needs_manage or allow_place
                    placement_block_reason: str | None = None
                    if not allow_place:
                        if netting_blocked:
                            placement_block_reason = NewsSkipReason.BROKER_UNSUPPORTED.value
                        elif heat_blocked or self._heat_unknown:
                            placement_block_reason = NewsSkipReason.PORTFOLIO_HEAT.value
                        elif at_capacity:
                            placement_block_reason = NewsSkipReason.MAX_CONCURRENT.value
                        elif not news_session_ok:
                            placement_block_reason = NewsSkipReason.OUTSIDE_SESSION.value
                        elif news_already:
                            placement_block_reason = NewsSkipReason.ALREADY_OPEN_SAME_STRATEGY.value
                    if (
                        not run_straddle
                        and allow_new_entries
                        and news_session_ok
                        and self.news_straddle.is_scalp_paused(now, currency)
                    ):
                        # Enter pause/place path even when not yet PENDING.
                        run_straddle = True
                        allow_place = (
                            not news_already
                            and not three_paused
                            and not at_capacity
                            and not netting_blocked
                            and not heat_blocked
                        )
                        if allow_place:
                            placement_block_reason = None
                    news_wants_place = bool(allow_place)
                    if run_straddle:
                        m1_for_straddle = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=40)
                        if m1_for_straddle is not None and not m1_for_straddle.empty:
                            atr_period = int(
                                (self.settings.strategy.get("news_straddle") or {}).get(
                                    "atr_period", 14
                                )
                            )
                            m1_for_straddle = enrich_with_indicators(
                                m1_for_straddle,
                                atr_period=atr_period,
                            )
                        else:
                            m1_for_straddle = pd.DataFrame()

                        news_key = self._open_key(symbol, "news_straddle")
                        news_pre_reserved = False
                        allocated_news_dollars = 0.0
                        if (
                            allow_place
                            and news_risk_pct is not None
                            and news_key not in self._heat_reservations
                        ):
                            allocated_news_dollars = (
                                float(news_broker.get_balance()) * float(news_risk_pct) / 100.0
                            )
                            self._reserve_heat(symbol, "news_straddle", allocated_news_dollars, [])
                            news_pre_reserved = True

                        straddle_res = self.news_straddle.tick(
                            news_broker,
                            symbol=symbol,
                            moment=now,
                            m1_df=m1_for_straddle,
                            spread_pips=spread_pips,
                            currency=currency,
                            already_open=news_already,
                            allow_place=False,
                            abort_pending=abort_pending,
                            placement_block_reason=placement_block_reason,
                            risk_pct=news_risk_pct,
                        )
                        if straddle_res.action in (
                            "placed",
                            "oco_filled",
                            "filled",
                            "oco_retry",
                            "expired",
                            "aborted",
                        ):
                            logger.info(
                                "{} news_straddle action={} phase={}",
                                symbol,
                                straddle_res.action,
                                straddle_res.phase.value,
                            )
                        if straddle_res.action in ("expired", "aborted"):
                            self._release_heat(symbol, "news_straddle")
                        elif straddle_res.action == "placed" and straddle_res.session is not None:
                            sess = straddle_res.session
                            tickets = [
                                t for t in (sess.buy_ticket, sess.sell_ticket) if t is not None
                            ]
                            reserved = self._heat_reservations.get(news_key) or {}
                            cap = float(reserved.get("dollar_risk") or allocated_news_dollars)
                            risk = float(sess.dollar_risk or cap)
                            if cap > 0 and risk > cap + 1e-9:
                                logger.error(
                                    "{} news dollar_risk {:.2f} exceeds reserved {:.2f}; capping",
                                    symbol,
                                    risk,
                                    cap,
                                )
                                risk = cap
                            self._reserve_heat(symbol, "news_straddle", risk, tickets)
                        elif news_pre_reserved and straddle_res.action not in (
                            "placed",
                            "oco_filled",
                            "filled",
                            "oco_retry",
                        ):
                            self._release_heat(symbol, "news_straddle")
                        if straddle_res.opened_position is not None:
                            position = straddle_res.opened_position
                            already = (
                                self.open_tickets.get(self._open_key(symbol, "news_straddle"))
                                == position.ticket
                            )
                            if not already:
                                reserved = dict(
                                    self._heat_reservations.get(
                                        self._open_key(symbol, "news_straddle")
                                    )
                                    or {}
                                )
                                dollar_risk = float(reserved.get("dollar_risk") or 0.0)
                                if dollar_risk <= 0 and straddle_res.session is not None:
                                    dollar_risk = float(straddle_res.session.dollar_risk or 0.0)
                                self._register_open(symbol, "news_straddle", position.ticket)
                                self._store_meta(
                                    symbol,
                                    "news_straddle",
                                    {
                                        "symbol": symbol,
                                        "initial_volume": position.volume,
                                        "initial_stop_loss": position.stop_loss,
                                        "entry_price": position.entry_price,
                                        "dollar_risk": dollar_risk,
                                        "partial_taken": False,
                                        "breakeven_moved": False,
                                        "strategy": "news_straddle",
                                        "reason": "news_straddle",
                                    },
                                    position.ticket,
                                )
                                self._sync_heat_after_fill(symbol, "news_straddle", reserved)
                                self.attribution.for_strategy("news_straddle").filled += 1
                                if not getattr(position, "strategy", ""):
                                    position.strategy = "news_straddle"
                                self.trade_journal.record_open(
                                    position,
                                    strategy="news_straddle",
                                    reason="news_straddle",
                                )
                                self._persist_state()
                                self._last_trade_opened_at = now
                                event_title = ""
                                if straddle_res.session is not None:
                                    event_title = straddle_res.session.event_title
                                self.alerts.notify_trade_opened(
                                    "News straddle filled",
                                    (
                                        f"{symbol} {position.direction.value} "
                                        f"vol={position.volume:.2f} "
                                        f"entry={position.entry_price:.5f} "
                                        f"event={event_title}"
                                    ),
                                )
                        if straddle_res.action and straddle_res.action not in (
                            "placed",
                            "oco_filled",
                            "filled",
                            "oco_retry",
                            "manage_open",
                            "waiting",
                            "already_active",
                            "noop",
                        ):
                            if allow_new_entries:
                                self._note_skip(f"{symbol}:news_straddle_{straddle_res.action}")
                            counters = self.attribution.for_strategy("news_straddle")
                            counters.evaluated += 1
                            counters.record_internal_reject(straddle_res.action)

                if not allow_new_entries:
                    continue

                if (
                    self.three_strikes_enabled
                    and not self._is_comparison_book()
                    and self.three_strikes.is_paused(symbol, at=now)
                ):
                    self._note_skip(f"{symbol}:three_strikes")
                    continue

                if not self.session_filter.is_within_session(now, symbol=symbol):
                    self._note_skip(f"{symbol}:outside_session")
                    continue

                if self.news_filter.is_blackout(now, currency=currency):
                    self._note_skip(f"{symbol}:news_blackout")
                    continue

                if self.spread_ma_enabled and not self.spread_ma_guard.allows(symbol, spread_pips):
                    self._note_skip(f"{symbol}:spread_ma")
                    continue

                data_by_tf = self._fetch_and_enrich(symbol)
                want_institutional = (
                    use_smc
                    or use_liq
                    or enabled.delta
                    or enabled.xau_vwap_pullback
                    or (not use_scalp)
                )

                scalp_df = data_by_tf.get(self.trigger_timeframe) if use_scalp else None
                inst_tf = Timeframe.M1
                inst_df = data_by_tf.get(inst_tf) if want_institutional else None
                if want_institutional and (inst_df is None or inst_df.empty):
                    # Fallback when M1 missing (paper/tests): use trigger frame.
                    inst_df = data_by_tf.get(self.trigger_timeframe)
                    inst_tf = self.trigger_timeframe

                if (
                    use_scalp
                    and (scalp_df is None or scalp_df.empty)
                    and (inst_df is None or inst_df.empty)
                ):
                    self._note_skip(f"{symbol}:no_trigger_data")
                    continue
                if (not use_scalp) and (inst_df is None or inst_df.empty):
                    self._note_skip(f"{symbol}:no_trigger_data")
                    continue

                # Volatility / correlation regime still prefer M5.
                trigger_df = scalp_df if scalp_df is not None and not scalp_df.empty else inst_df
                if trigger_df is None or trigger_df.empty:
                    self._note_skip(f"{symbol}:no_trigger_data")
                    continue

                if bool(self.vol_cfg.get("enabled", True)):
                    # Regime check on M5 (configurable), not S15/M1 trigger ATR —
                    # ultra-scalp trigger bars have tiny ATR/close and would
                    # permanently fail a min ratio calibrated for higher TFs.
                    vol_tf_name = str(self.vol_cfg.get("timeframe", "M5"))
                    try:
                        vol_tf = Timeframe(vol_tf_name)
                    except ValueError:
                        vol_tf = Timeframe.M5
                    vol_df = data_by_tf.get(vol_tf)
                    if vol_df is None or vol_df.empty:
                        vol_df = data_by_tf.get(Timeframe.M5)
                    if vol_df is None or vol_df.empty:
                        vol_df = trigger_df
                    last = vol_df.iloc[-1]
                    atr_raw = last.get("atr", 0)
                    close_raw = last.get("close", 0)
                    try:
                        atr_v = float(atr_raw) if atr_raw is not None else 0.0
                    except (TypeError, ValueError):
                        atr_v = 0.0
                    try:
                        close_v = float(close_raw) if close_raw is not None else 0.0
                    except (TypeError, ValueError):
                        close_v = 0.0
                    allowed, vol_reason, ratio = volatility_decision(
                        atr_v,
                        close_v,
                        min_ratio=float(self.vol_cfg.get("min_atr_close_ratio", 0.00005)),
                        max_ratio=float(self.vol_cfg.get("max_atr_close_ratio", 0.05)),
                    )
                    if not allowed:
                        self._note_skip(f"{symbol}:volatility_{vol_reason}")
                        logger.debug(
                            "{} volatility_guard {}: atr={:.6g} close={:.6g} ratio={} tf={}",
                            symbol,
                            vol_reason,
                            atr_v,
                            close_v,
                            f"{ratio:.6g}" if ratio is not None else "n/a",
                            vol_tf.value,
                        )
                        continue

                # Cross-symbol correlation is optional. With independent_symbol_entries
                # each pair may open regardless of other open tickets (still one per symbol).
                if correlation_guard_enabled(self.settings.risk) and self.open_tickets:
                    m5 = data_by_tf.get(Timeframe.M5)
                    if m5 is not None and not m5.empty:
                        closes_map = {symbol: m5["close"]}
                        for other_key in list(self.open_tickets):
                            other_sym, _other_strat = parse_position_key(other_key)
                            if other_sym == symbol:
                                continue
                            other_m5 = self.connector.fetch_ohlcv(other_sym, Timeframe.M5, count=40)
                            if not other_m5.empty:
                                closes_map[other_sym] = other_m5["close"]
                        open_pos = self.broker.get_open_positions()
                        if correlation_blocks(
                            symbol,
                            m5["close"],
                            open_pos,
                            closes_map,
                            period=int(self.corr_cfg.get("period", 20)),
                            max_abs_corr=float(self.corr_cfg.get("max_abs_corr", 0.80)),
                        ):
                            self._note_skip(f"{symbol}:correlation")
                            continue

                run_scalp = False
                run_institutional = False
                scalp_bar = None
                inst_bar = None
                if self.trade_on_bar_close:
                    if use_scalp and scalp_df is not None and not scalp_df.empty:
                        scalp_bar = last_completed_bar_time(scalp_df)
                        if scalp_bar is not None and self.bar_gate.is_new_bar(
                            f"{symbol}:scalp", scalp_bar
                        ):
                            run_scalp = True
                    if want_institutional and inst_df is not None and not inst_df.empty:
                        inst_bar = last_completed_bar_time(inst_df)
                        if inst_bar is not None and self.bar_gate.is_new_bar(
                            f"{symbol}:inst", inst_bar
                        ):
                            run_institutional = True
                    if not run_scalp and not run_institutional:
                        continue
                else:
                    run_scalp = use_scalp
                    run_institutional = want_institutional

                # Independent engines on their own timeframes (not fallback chain).
                raw_signals: list = []
                skip_parts: list[str] = []
                engine_skips: list[str] = []
                cap = None
                spread_map = self.settings.spread_filter.get("max_spread_pips") or {}
                if isinstance(spread_map, dict):
                    cap = spread_map.get(symbol)
                median = self.spread_median.median(symbol)
                eval_kwargs = {
                    "symbol": symbol,
                    "data_by_timeframe": data_by_tf,
                    "higher_timeframes": self.higher_timeframes,
                    "trigger_timeframe": self.trigger_timeframe,
                    "spread_pips": spread_pips,
                    "median_spread_pips": median,
                    "broker_spread_cap_pips": float(cap) if cap is not None else None,
                    "skip_out": engine_skips,
                }
                if run_scalp:
                    raw_signals.extend(
                        self.strategy.evaluate_candidates(
                            **eval_kwargs, run_scalp=True, run_institutional=False
                        )
                    )
                if run_institutional:
                    raw_signals.extend(
                        self.strategy.evaluate_candidates(
                            **eval_kwargs, run_scalp=False, run_institutional=True
                        )
                    )

                if (
                    enabled.xau_vwap_pullback
                    and self.strategy.xau_vwap_engine.working_stop(symbol) is None
                ):
                    self._cancel_strategy_pendings(symbol, "xau_vwap_pullback")

                # Risk/dedup each candidate independently; fill all that pass.
                viable = []
                for cand in raw_signals:
                    tag = resolve_strategy_tag(
                        explicit=getattr(cand, "strategy", "") or "", reason=cand.reason
                    )
                    counters = self.attribution.for_strategy(tag)
                    counters.evaluated += 1
                    counters.candidate += 1
                    cand_tf = cand.timeframe or self.trigger_timeframe
                    if tag == "ultra_scalp":
                        cand_bar = scalp_bar or last_completed_bar_time(
                            scalp_df if scalp_df is not None else trigger_df
                        )
                    else:
                        cand_bar = inst_bar or last_completed_bar_time(
                            inst_df if inst_df is not None else trigger_df
                        )
                    if cand_bar is None:
                        cand_bar = now
                    dedup_key = signal_dedup_key(
                        f"{symbol}:{tag}", cand_tf, cand_bar, cand.signal_type
                    )
                    if self.signal_deduper.already_processed(dedup_key):
                        skip_parts.append(f"{tag}:dedup")
                        counters.record_internal_reject("dedup")
                        continue
                    if not self.risk_manager.validate_signal(
                        cand,
                        spread_pips,
                        min_reward_risk_ratio=self._min_rr_for_signal(cand),
                    ):
                        skip_parts.append(f"{tag}:risk_reject")
                        counters.risk_reject += 1
                        continue
                    viable.append((cand, cand_tf, cand_bar, dedup_key, tag))

                if not viable:
                    self._mark_engine_bars_evaluated(
                        symbol,
                        run_scalp=run_scalp,
                        scalp_bar=scalp_bar,
                        run_institutional=run_institutional,
                        inst_bar=inst_bar,
                    )
                    detail = (
                        "|".join(skip_parts or engine_skips)
                        if (skip_parts or engine_skips)
                        else "no_signal"
                    ).replace(" ", "_")
                    self._note_skip(f"{symbol}:{detail}")
                    continue

                session_name = self.session_filter.active_session_name(now) or "none"
                ready: list = []
                for signal, cand_tf, cand_bar, dedup_key, strategy_tag in viable:
                    counters = self.attribution.for_strategy(strategy_tag)
                    if self._has_open_strategy(symbol, strategy_tag):
                        skip_parts.append(f"{strategy_tag}:already_open_same_strategy")
                        counters.record_internal_reject("already_open_same_strategy")
                        continue
                    if self._open_key(symbol, strategy_tag) in self._heat_reservations:
                        skip_parts.append(f"{strategy_tag}:already_open_same_strategy")
                        counters.record_internal_reject("already_open_same_strategy")
                        continue
                    shadowish = is_shadow_only(
                        self.settings.strategy, strategy_tag
                    ) or blocks_real_live_orders(
                        self.settings.strategy,
                        strategy_tag,
                        mode=self.mode,
                        shadow_only=is_shadow_only(self.settings.strategy, strategy_tag),
                    )
                    if shadowish:
                        skip_parts.append(f"{strategy_tag}:shadow_only")
                        self.signal_deduper.mark_processed(dedup_key)
                        continue
                    if self._same_symbol_netting_blocked(symbol, strategy_tag):
                        logger.error(
                            "{} netting/unknown account cannot open a second independent "
                            "ticket (mode={}); skip {}",
                            symbol,
                            self._account_mode.value,
                            strategy_tag,
                        )
                        skip_parts.append(f"{strategy_tag}:broker_unsupported")
                        counters.lost_arbitration += 1
                        continue
                    mm_fp = self.mistake_memory.fingerprint(
                        symbol=symbol,
                        strategy=strategy_tag,
                        session=session_name,
                        direction=signal.signal_type.value,
                        reason=signal.reason,
                    )
                    if self.mistake_memory.blocks(mm_fp, now):
                        skip_parts.append(f"{strategy_tag}:mistake_memory")
                        continue
                    ready.append((signal, cand_tf, cand_bar, dedup_key, strategy_tag))

                requested = float(
                    self.risk_manager.risk_cfg.get(
                        "active_risk_per_trade_pct",
                        self.risk_manager.risk_cfg.get("max_risk_per_trade_pct", 1.0),
                    )
                )
                batch_risk = min(requested, 1.0)
                news_in_batch = bool(news_wants_place and not self._is_comparison_book())
                batch_n = len(ready) + int(news_in_batch)
                if batch_n and not self._is_comparison_book():
                    self._open_dollar_risks()
                    if self._heat_unknown:
                        for _sig, _tf, _bar, _dk, strategy_tag in ready:
                            skip_parts.append(f"{strategy_tag}:portfolio_heat")
                            self.attribution.for_strategy(strategy_tag).lost_arbitration += 1
                        ready = []
                        news_wants_place = False
                    else:
                        equity_live = float(self.broker.get_balance())
                        heat_cap = resolve_max_portfolio_heat_pct(self.settings.risk)
                        open_heat = self._committed_heat_pct(equity_live)
                        alloc = allocate_batch_risk_pct(
                            n=batch_n,
                            requested_risk_pct=batch_risk,
                            open_heat_pct=open_heat,
                            max_heat_pct=heat_cap,
                        )
                        if not alloc.allowed:
                            for _sig, _tf, _bar, _dk, strategy_tag in ready:
                                skip_parts.append(f"{strategy_tag}:portfolio_heat")
                                counters = self.attribution.for_strategy(strategy_tag)
                                counters.lost_arbitration += 1
                                holders = [parse_position_key(k)[1] for k in self.open_tickets]
                                for other in holders:
                                    counters.record_heat_block(other)
                            ready = []
                            news_wants_place = False
                        else:
                            batch_risk = alloc.risk_pct

                if news_wants_place:
                    news_risk_pct = (
                        min(requested, 1.0) if self._is_comparison_book() else batch_risk
                    )
                    self._place_deferred_news(
                        symbol,
                        now,
                        spread_pips=spread_pips,
                        currency=currency,
                        risk_pct=news_risk_pct,
                    )

                placed_any = False
                for signal, _signal_tf, _completed_bar, dedup_key, strategy_tag in ready:
                    counters = self.attribution.for_strategy(strategy_tag)
                    book_strategy = strategy_tag if self._is_comparison_book() else ""
                    if self.three_strikes_enabled and self.three_strikes.is_paused(
                        symbol, at=now, strategy=book_strategy
                    ):
                        skip_parts.append(f"{strategy_tag}:three_strikes")
                        continue
                    if self._is_comparison_book() and strategy_tag in self._book_dd_blocked:
                        skip_parts.append(f"{strategy_tag}:daily_drawdown")
                        continue
                    if self._at_capacity(strategy_tag if self._is_comparison_book() else None):
                        skip_parts.append(f"{strategy_tag}:max_concurrent")
                        counters.lost_arbitration += 1
                        counters.record_internal_reject("max_concurrent")
                        continue
                    if self._same_symbol_netting_blocked(symbol, strategy_tag):
                        skip_parts.append(f"{strategy_tag}:broker_unsupported")
                        counters.lost_arbitration += 1
                        continue
                    exec_broker = self._broker_for(strategy_tag)
                    equity = float(exec_broker.get_balance())
                    risk_pct = batch_risk
                    volume = self.risk_manager.position_size_for(signal, equity, risk_pct=risk_pct)
                    if volume <= 0:
                        skip_parts.append(f"{strategy_tag}:zero_volume")
                        counters.risk_reject += 1
                        continue
                    dollar_risk = equity * risk_pct / 100.0
                    is_stop = str(getattr(signal, "order_kind", "market") or "market") == "stop"
                    try:
                        if is_stop:
                            side = (
                                PendingOrderSide.BUY_STOP
                                if signal.signal_type == SignalType.BUY
                                else PendingOrderSide.SELL_STOP
                            )
                            pending = exec_broker.place_pending_stop(
                                symbol=symbol,
                                side=side,
                                volume=volume,
                                price=signal.entry_price,
                                stop_loss=signal.stop_loss,
                                take_profit=signal.take_profit,
                                comment=mt5_comment_for_strategy(strategy_tag),
                                strategy=strategy_tag,
                            )
                            self._reserve_heat(symbol, strategy_tag, dollar_risk, [pending.ticket])
                            placed_any = True
                            self.signal_deduper.mark_processed(dedup_key)
                            self._last_trade_opened_at = now
                            self._harvest_pending_fills(symbol, now)
                            continue
                        position = exec_broker.place_order(signal, volume)
                    except StaleStopsError:
                        skip_parts.append(f"{strategy_tag}:stale_stops")
                        continue
                    placed_any = True
                    self._register_open(symbol, strategy_tag, position.ticket)
                    position.strategy = strategy_tag
                    self._store_meta(
                        symbol,
                        strategy_tag,
                        {
                            "symbol": symbol,
                            "initial_volume": position.volume,
                            "initial_stop_loss": position.stop_loss,
                            "entry_price": position.entry_price,
                            "dollar_risk": dollar_risk,
                            "partial_taken": False,
                            "breakeven_moved": False,
                            "strategy": strategy_tag,
                            "reason": signal.reason or "",
                        },
                        position.ticket,
                    )
                    counters.filled += 1
                    self.trade_journal.record_open(
                        position, strategy=strategy_tag, reason=signal.reason or ""
                    )
                    self.signal_deduper.mark_processed(dedup_key)
                    self._last_trade_opened_at = now
                    if self.comparison_books is not None:
                        self.comparison_books.for_strategy(strategy_tag).mark_equity(now)
                    self.alerts.notify_trade_opened(
                        "Trade opened",
                        (
                            f"{symbol} {signal.signal_type.value} vol={volume:.2f} "
                            f"entry={position.entry_price:.5f} sl={position.stop_loss:.5f} "
                            f"tp={position.take_profit:.5f} strategy={strategy_tag}"
                        ),
                    )

                self._mark_engine_bars_evaluated(
                    symbol,
                    run_scalp=run_scalp,
                    scalp_bar=scalp_bar,
                    run_institutional=run_institutional,
                    inst_bar=inst_bar,
                )
                self.signal_deduper.prune_older_than()
                if placed_any:
                    self._persist_state()
                elif skip_parts:
                    self._note_skip(f"{symbol}:{('|'.join(skip_parts)).replace(' ', '_')}")

            except StaleStopsError as exc:
                # Price moved through SL/TP before fill — skip, do not trip circuit breaker.
                # Consume the bar so we do not hammer the same stale geometry.
                self._mark_engine_bars_evaluated(
                    symbol,
                    run_scalp=locals().get("run_scalp", False),
                    scalp_bar=locals().get("scalp_bar"),
                    run_institutional=locals().get("run_institutional", False),
                    inst_bar=locals().get("inst_bar"),
                )
                self._note_skip(f"{symbol}:stale_stops")
                logger.warning("Skipping {} — {}", symbol, exc)

            except Exception:  # noqa: BLE001 - one symbol's failure must not kill the loop
                # Do NOT mark the bar evaluated — retry on the next poll for soft broker errors.
                tick_had_failure = True
                failure_context = f"symbol={symbol}"
                self._note_skip(f"{symbol}:exception")
                self.alerts.notify(
                    "Processing error",
                    f"symbol={symbol} — see logs for traceback",
                    AlertLevel.ERROR,
                )
                logger.exception("Error processing {}", symbol)

        self._maybe_log_skip_heartbeat(now)

        if tick_had_failure:
            if self.circuit_breaker.record_failure(failure_context or "tick"):
                self.alerts.notify(
                    "Circuit breaker tripped",
                    f"Halting new entries after {self.circuit_breaker.consecutive_errors} errors",
                    AlertLevel.CRITICAL,
                )
        else:
            self.circuit_breaker.record_success()

    def _fetch_and_enrich(self, symbol: str) -> dict[Timeframe, pd.DataFrame]:
        ind_cfg = self.settings.indicators
        result = {}
        for tf in self.fetch_timeframes:
            df = self.connector.fetch_ohlcv(symbol, tf, count=300)
            if df.empty:
                continue
            df = enrich_with_indicators(
                df,
                ema_period=ind_cfg.get("ema_period_trend", 50),
                rsi_period=ind_cfg.get("rsi_period", 14),
                bb_period=ind_cfg.get("bollinger_period", 20),
                bb_std=ind_cfg.get("bollinger_std_dev", 2.0),
                macd_fast=ind_cfg.get("macd_fast", 12),
                macd_slow=ind_cfg.get("macd_slow", 26),
                macd_signal=ind_cfg.get("macd_signal", 9),
                atr_period=ind_cfg.get("atr_period", 14),
                rvol_period=ind_cfg.get("rvol_period", 20),
            )
            rvol_min = float(self.settings.strategy.get("liquidity_rvol_min", 1.5))
            df = enrich_with_smc(df, rvol_min=rvol_min)
            result[tf] = df
        return result

    def _apply_position_meta(self, position) -> None:
        strategy = resolve_strategy_tag(explicit=getattr(position, "strategy", "") or "")
        meta = self._lookup_meta(
            str(getattr(position, "symbol", "") or ""), strategy, position.ticket
        )
        if meta.get("initial_volume") is not None:
            position.initial_volume = float(meta["initial_volume"])
        if meta.get("initial_stop_loss") is not None:
            position.initial_stop_loss = float(meta["initial_stop_loss"])
        position.partial_taken = bool(meta.get("partial_taken", False))
        position.breakeven_moved = bool(meta.get("breakeven_moved", False))

    def _estimate_unrealized_pnl(self, strategy: str | None = None) -> float:
        total = 0.0
        for key, ticket in list(self.open_tickets.items()):
            symbol, tag = parse_position_key(key)
            if strategy is not None and tag != strategy:
                continue
            positions = self._broker_for(tag).get_open_positions(symbol)
            position = next((p for p in positions if p.ticket == ticket), None)
            if position is None:
                continue
            try:
                m1 = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=2)
                if m1.empty:
                    continue
                price = float(m1.iloc[-1]["close"])
                spec = self.settings.symbols_raw[symbol]
                pip_size = float(spec["pip_size"])
                pip_value = float(spec["pip_value_per_lot"])
                diff = (
                    price - position.entry_price
                    if position.direction == SignalType.BUY
                    else position.entry_price - price
                )
                total += (diff / pip_size) * pip_value * position.volume
            except Exception:  # noqa: BLE001
                continue
        return total

    def _session_name_for_memory(self, now: datetime) -> str:
        return self.session_filter.active_session_name(now) or "none"

    def _record_mistake_memory(self, closed, *, at: datetime) -> None:
        """Record a full-close loss fingerprint when journal fields allow."""
        if closed is None:
            return
        self.mistake_memory.record_from_closed_trade(
            closed,
            session=self._session_name_for_memory(at),
            at=at,
        )

    def _close_all_positions(self, now: datetime, *, reason: str) -> None:
        for key, ticket in list(self.open_tickets.items()):
            symbol, strategy = parse_position_key(key)
            try:
                trade = self._broker_for(strategy).close_position(ticket)
                self.risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=now)
                if self.three_strikes_enabled:
                    self.three_strikes.record_result(symbol, trade.pnl, at=now, strategy=strategy)
                closed = self.trade_journal.record_close(trade, ticket=ticket)
                self._record_mistake_memory(closed, at=now)
                self._clear_meta(symbol, strategy, ticket)
                self.open_tickets.pop(key, None)
                self.attribution.for_strategy(strategy).closed += 1
                logger.warning("Force-closed {} ticket={} reason={}", symbol, ticket, reason)
            except Exception:  # noqa: BLE001
                logger.exception("Failed force-close {} ticket={}", symbol, ticket)
        self._persist_state()

    def _manage_open_position(self, symbol: str, now: datetime) -> None:
        for key in list(self._keys_for_symbol(symbol)):
            ticket = self.open_tickets.get(key)
            if ticket is None:
                continue
            self._manage_one_ticket(symbol, key, ticket, now)

    def _manage_one_ticket(self, symbol: str, key: str, ticket: int, now: datetime) -> None:
        _symbol, strategy = parse_position_key(key)
        broker = self._broker_for(strategy)

        positions = broker.get_open_positions(symbol)
        position = next((p for p in positions if p.ticket == ticket), None)
        if position is None:
            self._on_position_closed_externally(symbol, ticket, now, strategy=strategy)
            return
        self._apply_position_meta(position)

        m1_df = self.connector.fetch_ohlcv(symbol, Timeframe.M1, count=40)
        if m1_df.empty:
            return
        m1_df = enrich_with_indicators(
            m1_df, atr_period=self.settings.indicators.get("atr_period", 14)
        )

        bar = m1_df.iloc[-1]
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        current_price = float(bar["close"])

        if self.mode == "paper":
            hit = check_sl_tp_hit(position, bar_high, bar_low)
            if hit.triggered:
                exit_price = exit_price_for_hit(position, hit)
                trade = broker.close_position(
                    ticket,
                    exit_price=exit_price,
                    at=now,
                    reason=hit.exit_reason(),
                )
                self.risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=now)
                if self.three_strikes_enabled:
                    self.three_strikes.record_result(symbol, trade.pnl, at=now, strategy=strategy)
                closed = self.trade_journal.record_close(trade, ticket=ticket)
                self._record_mistake_memory(closed, at=now)
                self.open_tickets.pop(key, None)
                self._clear_meta(symbol, strategy, ticket)
                self.attribution.for_strategy(strategy).closed += 1
                if self.comparison_books is not None:
                    self.comparison_books.for_strategy(strategy).record_close(trade, now)
                self._persist_state()
                logger.info(
                    "Paper {} closed via {} pnl={:.2f}",
                    symbol,
                    hit.exit_reason(),
                    trade.pnl,
                )
                self.alerts.notify(
                    "Trade closed",
                    f"{symbol} {hit.exit_reason()} pnl={trade.pnl:.2f}",
                    AlertLevel.INFO,
                )
                return

        pip_size = float(self.settings.symbols_raw[symbol]["pip_size"])
        spread_pips = broker.get_current_spread_pips(symbol)
        spread_price = spread_pips * pip_size
        action = manage_open_position(
            position,
            current_price,
            m1_df,
            spread_price=spread_price,
            partial_r=float(self.partial_cfg.get("r_multiple", 1.2)),
            chandelier_lookback=int(self.chandelier_cfg.get("lookback", 22)),
            chandelier_atr_multiple=float(self.chandelier_cfg.get("atr_multiple", 2.5)),
        )

        if bool(self.partial_cfg.get("enabled", True)) and action.partial is not None:
            try:
                trade = broker.close_partial(ticket, action.partial.close_volume)
                self.risk_manager.daily_tracker.record_trade_pnl(trade.pnl, at=now)
                self.trade_journal.record_close(trade, ticket=ticket)
                meta = self._lookup_meta(symbol, strategy, ticket)
                meta["partial_taken"] = True
                meta["breakeven_moved"] = True
                self._store_meta(symbol, strategy, meta, ticket)
                position.partial_taken = True
                position.breakeven_moved = True
                if action.partial.new_stop_loss is not None and broker.modify_sl_tp(
                    ticket, action.partial.new_stop_loss, position.take_profit
                ):
                    position.stop_loss = action.partial.new_stop_loss
                logger.info(
                    "Partial TP {} ticket={} vol={} pnl={:.2f}",
                    symbol,
                    ticket,
                    action.partial.close_volume,
                    trade.pnl,
                )
            except Exception:  # noqa: BLE001
                logger.exception("Partial TP failed for {} ticket={}", symbol, ticket)

        new_sl = action.new_stop_loss
        if new_sl is None and not (
            bool(self.chandelier_cfg.get("enabled", True)) and position.partial_taken
        ):
            atr_value = float(m1_df.iloc[-1]["atr"])
            new_sl = apply_breakeven_or_trailing(
                self.risk_manager, position, current_price, atr_value
            )
        if new_sl is not None and broker.modify_sl_tp(ticket, new_sl, position.take_profit):
            if abs(new_sl - position.entry_price) < pip_size * 2:
                position.breakeven_moved = True
                meta = self._lookup_meta(symbol, strategy, ticket)
                meta["breakeven_moved"] = True
                self._store_meta(symbol, strategy, meta, ticket)
            position.stop_loss = new_sl

    def _on_position_closed_externally(
        self, symbol: str, ticket: int, now: datetime, *, strategy: str | None = None
    ) -> None:
        pnl: float | None = None
        exit_price: float | None = None
        if self.mode == "live" and isinstance(self.broker, (MT5Broker, OANDABroker)):
            pnl = self.broker.fetch_closed_pnl(ticket)
            reader = getattr(self.broker, "fetch_closed_exit_price", None)
            if callable(reader):
                try:
                    exit_price = reader(ticket)
                except Exception as exc:  # broker/history hiccup must not lose the close
                    logger.warning("Exit price unavailable for ticket={}: {}", ticket, exc)

        closed = self.trade_journal.record_external_close(
            ticket, symbol, pnl, at=now, strategy=strategy, exit_price=exit_price
        )

        if pnl is not None:
            self.risk_manager.daily_tracker.record_trade_pnl(pnl, at=now)
            if self.three_strikes_enabled:
                self.three_strikes.record_result(symbol, pnl, at=now, strategy=strategy or "")
            if pnl < 0:
                self._record_mistake_memory(closed, at=now)
            logger.info("Position {} ticket={} closed externally, pnl={:.2f}", symbol, ticket, pnl)
            self.alerts.notify(
                "Trade closed",
                f"{symbol} external close pnl={pnl:.2f}",
                AlertLevel.INFO,
            )
        else:
            logger.info("Position {} ticket={} closed externally (PnL unknown)", symbol, ticket)
            self.alerts.notify(
                "Trade closed",
                f"{symbol} external close (PnL unknown)",
                AlertLevel.INFO,
            )

        self._drop_ticket(ticket, symbol=symbol, strategy=strategy)
        if strategy:
            self._clear_meta(symbol, strategy, ticket)
        else:
            self._position_meta.pop(ticket, None)
        self._persist_state()


def settings_config_dir():
    from chronoscalp.config import CONFIG_DIR

    return CONFIG_DIR


def main(mode: str = "paper") -> None:
    settings = get_settings()
    bot = TradingBot(settings, mode=mode)
    bot.start()


if __name__ == "__main__":
    main()
