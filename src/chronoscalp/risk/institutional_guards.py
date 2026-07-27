"""Institutional risk guards: 3-strikes, correlation, volatility, spread MA."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position


@dataclass
class ThreeStrikesGuard:
    """Pause a symbol for ``pause_hours`` after ``max_losses`` consecutive losses."""

    max_losses: int = 3
    pause_hours: int = 12
    _streak: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _paused_until: dict[str, datetime] = field(default_factory=dict)

    def record_result(self, symbol: str, pnl: float, at: datetime | None = None) -> None:
        now = at or datetime.now(tz=UTC)
        if pnl > 0:
            self._streak[symbol] = 0
            self._paused_until.pop(symbol, None)
            return
        if pnl < 0:
            self._streak[symbol] = self._streak.get(symbol, 0) + 1
            if self._streak[symbol] >= self.max_losses:
                until = now + timedelta(hours=self.pause_hours)
                self._paused_until[symbol] = until
                logger.warning(
                    "{} paused until {} after {} consecutive losses",
                    symbol,
                    until.isoformat(),
                    self._streak[symbol],
                )

    def is_paused(self, symbol: str, at: datetime | None = None) -> bool:
        now = at or datetime.now(tz=UTC)
        until = self._paused_until.get(symbol)
        if until is None:
            return False
        if now >= until:
            self._paused_until.pop(symbol, None)
            self._streak[symbol] = 0
            return False
        return True


@dataclass
class SpreadMovingAverageGuard:
    """Reject when current spread > MA(last N samples) * multiplier."""

    window: int = 100
    multiplier: float = 1.2
    _history: dict[str, deque[float]] = field(default_factory=dict)

    def observe(self, symbol: str, spread_pips: float) -> None:
        hist = self._history.setdefault(symbol, deque(maxlen=self.window))
        hist.append(float(spread_pips))

    def allows(self, symbol: str, spread_pips: float) -> bool:
        hist = self._history.get(symbol)
        if not hist or len(hist) < max(5, self.window // 10):
            return True
        avg = sum(hist) / len(hist)
        if avg <= 0:
            return True
        ok = spread_pips <= avg * self.multiplier
        if not ok:
            logger.info(
                "{} spread guard: {:.2f} > MA{:.2f}*{:.2f}",
                symbol,
                spread_pips,
                avg,
                self.multiplier,
            )
        return ok


def volatility_decision(
    atr: float,
    close: float,
    *,
    min_ratio: float = 0.00005,
    max_ratio: float = 0.05,
) -> tuple[bool, str, float | None]:
    """Classify ATR/close regime for the volatility guard.

    Returns ``(allowed, reason, ratio)`` where ``reason`` is one of
    ``ok``, ``low``, ``high``, or ``invalid`` (non-positive / NaN inputs).
    """
    try:
        atr_v = float(atr)
        close_v = float(close)
    except (TypeError, ValueError):
        return False, "invalid", None
    if close_v <= 0 or atr_v <= 0 or math.isnan(atr_v) or math.isnan(close_v):
        return False, "invalid", None
    ratio = atr_v / close_v
    if ratio < min_ratio:
        return False, "low", ratio
    if ratio > max_ratio:
        return False, "high", ratio
    return True, "ok", ratio


def volatility_allows(
    atr: float,
    close: float,
    *,
    min_ratio: float = 0.00005,
    max_ratio: float = 0.05,
) -> bool:
    """Block dead markets and extreme ATR/close regimes."""
    allowed, _reason, _ratio = volatility_decision(
        atr, close, min_ratio=min_ratio, max_ratio=max_ratio
    )
    return allowed


def m5_correlation(a: pd.Series, b: pd.Series, period: int = 20) -> float | None:
    """Pearson correlation of last ``period`` closes."""
    if a is None or b is None or len(a) < period or len(b) < period:
        return None
    x = a.astype(float).tail(period).to_numpy()
    y = b.astype(float).tail(period).to_numpy()
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def correlation_blocks(
    candidate_symbol: str,
    candidate_closes: pd.Series,
    open_positions: list[Position],
    closes_by_symbol: dict[str, pd.Series],
    *,
    period: int = 20,
    max_abs_corr: float = 0.80,
) -> bool:
    """Return True if a new trade should be blocked due to high correlation."""
    for pos in open_positions:
        if pos.symbol == candidate_symbol:
            continue
        other = closes_by_symbol.get(pos.symbol)
        if other is None:
            continue
        corr = m5_correlation(candidate_closes, other, period=period)
        if corr is not None and abs(corr) > max_abs_corr:
            logger.info(
                "{} blocked: corr with {} = {:.2f} > {:.2f}",
                candidate_symbol,
                pos.symbol,
                corr,
                max_abs_corr,
            )
            return True
    return False


@dataclass
class DailyDrawdownGuard:
    """Hard daily cutoff using starting equity at 00:00 GMT (realized + unrealized)."""

    max_daily_loss_pct: float = 3.0
    starting_equity: float = 0.0
    day_utc: date | None = None
    blocked: bool = False

    def roll_day(self, equity: float, at: datetime) -> None:
        day = at.astimezone(UTC).date() if at.tzinfo else at.date()
        if self.day_utc != day:
            self.day_utc = day
            self.starting_equity = float(equity)
            self.blocked = False
            logger.info("Daily DD guard reset: start_equity={:.2f} day={}", equity, day)

    def check(
        self,
        equity: float,
        realized_pnl_today: float,
        unrealized_pnl: float,
        at: datetime | None = None,
    ) -> bool:
        """Return True if daily loss limit is hit (should close all + block)."""
        now = at or datetime.now(tz=UTC)
        self.roll_day(equity, now)
        if self.starting_equity <= 0:
            self.starting_equity = float(equity)
        limit = -abs(self.starting_equity * (self.max_daily_loss_pct / 100.0))
        total = float(realized_pnl_today) + float(unrealized_pnl)
        if total <= limit:
            if not self.blocked:
                logger.warning(
                    "Daily DD cutoff: total={:.2f} <= limit={:.2f} (realized={:.2f} unrealized={:.2f})",
                    total,
                    limit,
                    realized_pnl_today,
                    unrealized_pnl,
                )
            self.blocked = True
            return True
        return self.blocked
