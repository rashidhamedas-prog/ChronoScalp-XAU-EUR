"""Dynamic ATR news straddle with spread shield and OCO management.

Places BUY_STOP + SELL_STOP brackets shortly before high-impact releases.
Uses the :class:`~chronoscalp.execution.broker.Broker` protocol only — never
imports MetaTrader5. Volume is always sized through
:class:`~chronoscalp.risk.position_sizing.RiskManager` (1% equity ceiling).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import pandas as pd

from chronoscalp.filters.news_calendar import (
    NewsCalendarManager,
    UpcomingNews,
    event_matches_straddle_titles,
)
from chronoscalp.indicators.technical import atr as atr_series
from chronoscalp.logging_setup import logger
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.utils.types import (
    PendingOrder,
    PendingOrderSide,
    Position,
    Quote,
    Signal,
    SignalType,
    Timeframe,
)

COMMENT_PREFIX = "CS_News"
COMMENT_BUY = "CS_News_B"
COMMENT_SELL = "CS_News_S"


class StraddlePhase(StrEnum):
    IDLE = "idle"
    PAUSED = "paused"
    PENDING = "pending"
    FILLED = "filled"


@dataclass
class StraddleSession:
    """Per-symbol live state for one news release."""

    symbol: str
    event_title: str
    event_time: datetime
    phase: StraddlePhase = StraddlePhase.IDLE
    buy_ticket: int | None = None
    sell_ticket: int | None = None
    placed_at: datetime | None = None
    expires_at: datetime | None = None
    filled_position_ticket: int | None = None
    distance: float = 0.0
    volume: float = 0.0


@dataclass
class StraddleTickResult:
    """Outcome of one controller tick for a symbol."""

    symbol: str
    phase: StraddlePhase
    action: str
    session: StraddleSession | None = None
    opened_position: Position | None = None
    message: str = ""


@dataclass
class DynamicNewsStraddleEngine:
    """Compute ATR brackets and drive pending/OCO lifecycle via a Broker."""

    calendar: NewsCalendarManager
    risk_manager: RiskManager
    cfg: dict[str, Any] = field(default_factory=dict)
    sessions: dict[str, StraddleSession] = field(default_factory=dict)

    @property
    def atr_period(self) -> int:
        return int(self.cfg.get("atr_period", 14))

    @property
    def atr_multiplier(self) -> float:
        return float(self.cfg.get("atr_multiplier", 2.0))

    @property
    def max_spread_pips(self) -> float:
        return float(self.cfg.get("max_spread_pips", 2.0))

    @property
    def pause_minutes_before(self) -> float:
        return float(self.cfg.get("pause_minutes_before", 2.0))

    @property
    def place_seconds_before(self) -> float:
        return float(self.cfg.get("place_seconds_before", 30.0))

    @property
    def expiry_seconds(self) -> float:
        return float(self.cfg.get("expiry_seconds", 120.0))

    @property
    def sl_distance_fraction(self) -> float:
        return float(self.cfg.get("sl_distance_fraction", 0.8))

    @property
    def tp_distance_fraction(self) -> float:
        return float(self.cfg.get("tp_distance_fraction", 1.8))

    @property
    def comment_prefix(self) -> str:
        return str(self.cfg.get("comment_prefix", COMMENT_PREFIX))

    def _title_filter(self) -> frozenset[str] | None:
        raw = self.cfg.get("title_tokens")
        if raw is None:
            return None  # use default high-impact tokens
        if isinstance(raw, list) and not raw:
            return frozenset()  # empty list = accept all high-impact
        return frozenset(str(t).lower() for t in raw)

    def is_scalp_paused(self, moment: datetime, currency: str | None) -> bool:
        paused, upcoming = self.calendar.is_scalp_paused(
            moment,
            pause_minutes_before=self.pause_minutes_before,
            pause_seconds_after=self.expiry_seconds,
            currency=currency,
        )
        if not paused or upcoming is None:
            return False
        return event_matches_straddle_titles(upcoming.event, self._title_filter())

    def atr_distance(self, m1_df: pd.DataFrame) -> float | None:
        """Return ATR(M1) * multiplier in price units, or None if insufficient data."""
        if m1_df is None or m1_df.empty or len(m1_df) < self.atr_period + 1:
            return None
        if "atr" in m1_df.columns and pd.notna(m1_df["atr"].iloc[-1]):
            atr_val = float(m1_df["atr"].iloc[-1])
        else:
            series = atr_series(m1_df, period=self.atr_period)
            if series.empty or pd.isna(series.iloc[-1]):
                return None
            atr_val = float(series.iloc[-1])
        if atr_val <= 0:
            return None
        return atr_val * self.atr_multiplier

    def build_bracket_signals(
        self,
        *,
        symbol: str,
        quote: Quote,
        distance: float,
        moment: datetime,
    ) -> tuple[Signal, Signal]:
        """BUY_STOP / SELL_STOP geometry with R:R = tp_frac / sl_frac (≥ 1.5 when defaults)."""
        sl_d = distance * self.sl_distance_fraction
        tp_d = distance * self.tp_distance_fraction
        buy_entry = quote.ask + distance
        sell_entry = quote.bid - distance
        buy = Signal(
            symbol=symbol,
            signal_type=SignalType.BUY,
            timestamp=moment,
            entry_price=buy_entry,
            stop_loss=buy_entry - sl_d,
            take_profit=buy_entry + tp_d,
            confidence=0.9,
            reason="news_straddle,buy_stop",
            timeframe=Timeframe.M1,
        )
        sell = Signal(
            symbol=symbol,
            signal_type=SignalType.SELL,
            timestamp=moment,
            entry_price=sell_entry,
            stop_loss=sell_entry + sl_d,
            take_profit=sell_entry - tp_d,
            confidence=0.9,
            reason="news_straddle,sell_stop",
            timeframe=Timeframe.M1,
        )
        return buy, sell

    def place_straddle_orders(
        self,
        broker: Any,
        *,
        symbol: str,
        quote: Quote,
        m1_df: pd.DataFrame,
        moment: datetime,
        upcoming: UpcomingNews,
        spread_pips: float,
    ) -> StraddleTickResult:
        """Place dynamic Buy Stop & Sell Stop pending orders (spread-shield gated)."""
        session = self.sessions.get(symbol)
        if session and session.phase in (StraddlePhase.PENDING, StraddlePhase.FILLED):
            return StraddleTickResult(
                symbol=symbol,
                phase=session.phase,
                action="already_active",
                session=session,
            )

        if not NewsCalendarManager.is_spread_acceptable(spread_pips, self.max_spread_pips):
            msg = f"spread_too_high:{spread_pips:.2f}>{self.max_spread_pips:.2f}"
            logger.warning("[STRADDLE CANCELLED] {} {}", symbol, msg)
            return StraddleTickResult(
                symbol=symbol, phase=StraddlePhase.PAUSED, action="spread_block", message=msg
            )

        distance = self.atr_distance(m1_df)
        if distance is None:
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.PAUSED,
                action="no_atr",
                message="insufficient_m1_atr",
            )

        buy_sig, sell_sig = self.build_bracket_signals(
            symbol=symbol, quote=quote, distance=distance, moment=moment
        )
        if buy_sig.risk_reward_ratio < 1.5 or sell_sig.risk_reward_ratio < 1.5:
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.PAUSED,
                action="rr_reject",
                message=f"rr_buy={buy_sig.risk_reward_ratio} rr_sell={sell_sig.risk_reward_ratio}",
            )

        if not self.risk_manager.validate_signal(buy_sig, spread_pips):
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.PAUSED,
                action="risk_reject",
                message="buy_leg_risk_reject",
            )

        equity = float(broker.get_balance())
        volume = float(self.risk_manager.position_size_for(buy_sig, equity))
        if volume <= 0:
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.PAUSED,
                action="zero_volume",
                message="position_size_zero",
            )

        expiration = moment + timedelta(seconds=self.expiry_seconds)
        try:
            buy_order = broker.place_pending_stop(
                symbol=symbol,
                side=PendingOrderSide.BUY_STOP,
                volume=volume,
                price=buy_sig.entry_price,
                stop_loss=buy_sig.stop_loss,
                take_profit=buy_sig.take_profit,
                expiration=expiration,
                comment=COMMENT_BUY,
            )
            sell_order = broker.place_pending_stop(
                symbol=symbol,
                side=PendingOrderSide.SELL_STOP,
                volume=volume,
                price=sell_sig.entry_price,
                stop_loss=sell_sig.stop_loss,
                take_profit=sell_sig.take_profit,
                expiration=expiration,
                comment=COMMENT_SELL,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[STRADDLE] place failed for {}: {} — cleaning up", symbol, exc)
            self.cancel_all_pending_orders(broker, symbol)
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.PAUSED,
                action="place_error",
                message=str(exc)[:200],
            )

        session = StraddleSession(
            symbol=symbol,
            event_title=upcoming.title,
            event_time=upcoming.event.timestamp,
            phase=StraddlePhase.PENDING,
            buy_ticket=buy_order.ticket,
            sell_ticket=sell_order.ticket,
            placed_at=moment,
            expires_at=expiration,
            distance=distance,
            volume=volume,
        )
        self.sessions[symbol] = session
        logger.info(
            "[SUCCESS] Straddle {} ATR×{} dist={:.5f} vol={} buy={} sell={} event={}",
            symbol,
            self.atr_multiplier,
            distance,
            volume,
            buy_order.ticket,
            sell_order.ticket,
            upcoming.title,
        )
        return StraddleTickResult(
            symbol=symbol,
            phase=StraddlePhase.PENDING,
            action="placed",
            session=session,
            message=upcoming.title,
        )

    def manage_oco_and_trailing(self, broker: Any, symbol: str) -> StraddleTickResult:
        """OCO: once one news leg fills, cancel the opposite pending order."""
        session = self.sessions.get(symbol)
        if session is None or session.phase != StraddlePhase.PENDING:
            phase = session.phase if session else StraddlePhase.IDLE
            return StraddleTickResult(symbol=symbol, phase=phase, action="noop", session=session)

        positions = broker.get_open_positions(symbol) or []
        pending = broker.get_pending_orders(symbol, comment_prefix=self.comment_prefix) or []
        our_tickets = {t for t in (session.buy_ticket, session.sell_ticket) if t is not None}
        pending_ours = [o for o in pending if o.ticket in our_tickets]

        # Paper/MT5: detect fill by open position appearing while a pending disappears.
        filled: Position | None = None
        for pos in positions:
            # Prefer freshly opened positions while we still have a pending twin.
            if session.filled_position_ticket and pos.ticket == session.filled_position_ticket:
                filled = pos
                break
            if pos.ticket not in our_tickets:
                # Market fill creates a position ticket different from pending order ticket.
                if pending_ours and len(pending_ours) < 2:
                    filled = pos
                    break
                if not pending_ours and session.phase == StraddlePhase.PENDING:
                    filled = pos
                    break

        if filled is None and len(pending_ours) < 2 and positions:
            # One pending gone — treat newest position as the fill.
            filled = max(positions, key=lambda p: p.open_time)

        if filled is not None and pending_ours:
            for order in pending_ours:
                try:
                    broker.cancel_pending_order(order.ticket)
                    logger.info(
                        "[OCO TRIGGERED] {} cancelled pending {} (filled ticket={})",
                        symbol,
                        order.ticket,
                        filled.ticket,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("OCO cancel failed ticket={}: {}", order.ticket, exc)
            session.phase = StraddlePhase.FILLED
            session.filled_position_ticket = filled.ticket
            session.buy_ticket = None
            session.sell_ticket = None
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.FILLED,
                action="oco_filled",
                session=session,
                opened_position=filled,
            )

        if filled is not None and not pending_ours:
            session.phase = StraddlePhase.FILLED
            session.filled_position_ticket = filled.ticket
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.FILLED,
                action="filled",
                session=session,
                opened_position=filled,
            )

        return StraddleTickResult(
            symbol=symbol, phase=StraddlePhase.PENDING, action="waiting", session=session
        )

    def cancel_all_pending_orders(self, broker: Any, symbol: str | None = None) -> int:
        """Cancel news pending orders (expiry / place failure / operator abort)."""
        cancelled = 0
        orders: list[PendingOrder] = broker.get_pending_orders(
            symbol, comment_prefix=self.comment_prefix
        ) or []
        for order in orders:
            try:
                if broker.cancel_pending_order(order.ticket):
                    cancelled += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("cancel pending {} failed: {}", order.ticket, exc)
        if symbol and symbol in self.sessions:
            sess = self.sessions[symbol]
            if sess.phase == StraddlePhase.PENDING:
                sess.phase = StraddlePhase.IDLE
                sess.buy_ticket = None
                sess.sell_ticket = None
        elif symbol is None:
            for sess in self.sessions.values():
                if sess.phase == StraddlePhase.PENDING:
                    sess.phase = StraddlePhase.IDLE
                    sess.buy_ticket = None
                    sess.sell_ticket = None
        return cancelled

    def tick(
        self,
        broker: Any,
        *,
        symbol: str,
        moment: datetime,
        m1_df: pd.DataFrame,
        spread_pips: float,
        currency: str | None,
        already_open: bool,
    ) -> StraddleTickResult:
        """Drive pause → place → OCO → expiry for one symbol."""
        now = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
        session = self.sessions.get(symbol)

        if session and session.phase == StraddlePhase.PENDING:
            oco = self.manage_oco_and_trailing(broker, symbol)
            if oco.action in ("oco_filled", "filled"):
                return oco
            if session.expires_at and now >= session.expires_at:
                n = self.cancel_all_pending_orders(broker, symbol)
                logger.info("[STRADDLE EXPIRED] {} cancelled {} pendings", symbol, n)
                return StraddleTickResult(
                    symbol=symbol,
                    phase=StraddlePhase.IDLE,
                    action="expired",
                    session=session,
                    message=f"cancelled={n}",
                )
            return oco

        if session and session.phase == StraddlePhase.FILLED:
            # Keep session until the position is gone so we don't re-arm same event.
            positions = broker.get_open_positions(symbol) or []
            if session.filled_position_ticket and not any(
                p.ticket == session.filled_position_ticket for p in positions
            ):
                session.phase = StraddlePhase.IDLE
                return StraddleTickResult(
                    symbol=symbol, phase=StraddlePhase.IDLE, action="position_closed", session=session
                )
            return StraddleTickResult(
                symbol=symbol, phase=StraddlePhase.FILLED, action="manage_open", session=session
            )

        paused, upcoming = self.calendar.is_scalp_paused(
            now,
            pause_minutes_before=self.pause_minutes_before,
            pause_seconds_after=self.expiry_seconds,
            currency=currency,
        )
        if not paused or upcoming is None:
            return StraddleTickResult(symbol=symbol, phase=StraddlePhase.IDLE, action="idle")

        if not event_matches_straddle_titles(upcoming.event, self._title_filter()):
            return StraddleTickResult(
                symbol=symbol, phase=StraddlePhase.IDLE, action="title_skip", message=upcoming.title
            )

        # Avoid duplicate arming for the same event timestamp.
        if (
            session
            and session.event_time == upcoming.event.timestamp
            and session.phase == StraddlePhase.IDLE
            and session.placed_at is not None
        ):
            return StraddleTickResult(
                symbol=symbol, phase=StraddlePhase.IDLE, action="event_done", session=session
            )

        in_place, _ = self.calendar.is_straddle_placement_window(
            now, place_seconds_before=self.place_seconds_before, currency=currency
        )
        if not in_place:
            self.sessions[symbol] = StraddleSession(
                symbol=symbol,
                event_title=upcoming.title,
                event_time=upcoming.event.timestamp,
                phase=StraddlePhase.PAUSED,
            )
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.PAUSED,
                action="paused",
                session=self.sessions[symbol],
                message=f"eta={upcoming.seconds_until:.0f}s {upcoming.title}",
            )

        if already_open:
            return StraddleTickResult(
                symbol=symbol,
                phase=StraddlePhase.PAUSED,
                action="already_open",
                message="skip_place_existing_position",
            )

        quote = broker.get_quote(symbol)
        if quote is None:
            return StraddleTickResult(
                symbol=symbol, phase=StraddlePhase.PAUSED, action="no_quote", message="quote_unavailable"
            )

        return self.place_straddle_orders(
            broker,
            symbol=symbol,
            quote=quote,
            m1_df=m1_df,
            moment=now,
            upcoming=upcoming,
            spread_pips=spread_pips,
        )
