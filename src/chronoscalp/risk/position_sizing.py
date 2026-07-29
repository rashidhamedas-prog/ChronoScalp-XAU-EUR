"""Position sizing, spread filtering, breakeven/trailing-stop, and daily
loss-limit enforcement.

This module is the single place that turns a `Signal` into an actual risked
dollar amount. See CLAUDE.md rule #1 — max_risk_per_trade_pct and
min_reward_risk_ratio (config/settings.yaml) are hard constraints enforced
here, not tuning knobs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Position, Signal

HARD_MAX_RISK_PCT = 1.0


def resolve_active_risk_pct(risk_cfg: dict) -> float:
    """Return the effective risk % for sizing, never above the hard 1% ceiling.

    UI may offer presets including 1.5, but ``max_risk_per_trade_pct`` (default
    1.0) and ``HARD_MAX_RISK_PCT`` always cap the result — see CLAUDE.md rule #1.
    """
    ceiling = float(risk_cfg.get("max_risk_per_trade_pct", HARD_MAX_RISK_PCT))
    ceiling = min(ceiling, HARD_MAX_RISK_PCT)
    requested = float(
        risk_cfg.get("active_risk_per_trade_pct", risk_cfg.get("max_risk_per_trade_pct", 1.0))
    )
    effective = min(max(requested, 0.0), ceiling)
    if requested > ceiling:
        logger.warning(
            "Requested risk {:.2f}% exceeds hard ceiling {:.2f}% — using {:.2f}%",
            requested,
            ceiling,
            effective,
        )
    return effective


def round_to_lot_step(volume: float, min_lot: float, max_lot: float, lot_step: float) -> float:
    if lot_step <= 0:
        return max(min_lot, min(volume, max_lot))
    steps = round(volume / lot_step)
    rounded = steps * lot_step
    return max(min_lot, min(round(rounded, 8), max_lot))


def commission_per_lot(symbol_spec: dict, entry_price: float) -> float:
    """Estimated round-turn commission (account currency) for 1.0 lot.

    Supports a fixed ``commission_per_lot`` and/or ``commission_pct_notional``
    (fraction of entry notional, round-turn — e.g. LiteFinance crypto ≈0.0012).
    Symbols without these fields cost 0 (spread-only pricing).
    """
    fixed = float(symbol_spec.get("commission_per_lot", 0.0) or 0.0)
    pct = float(symbol_spec.get("commission_pct_notional", 0.0) or 0.0)
    contract = float(symbol_spec.get("contract_size", 1.0) or 1.0)
    return fixed + pct * contract * max(entry_price, 0.0)


def fit_economic_scalp_geometry(
    *,
    entry: float,
    is_buy: bool,
    atr: float,
    atr_stop_multiple: float,
    atr_target_multiple: float,
    symbol_spec: dict | None = None,
    spread_pips: float | None = None,
    min_reward_risk_ratio: float = 1.0,
    net_rr_floor: float = 1.0,
    min_stop_spread_multiple: float = 2.0,
    max_stop_atr_multiple: float = 8.0,
    max_target_atr_multiple: float = 12.0,
) -> tuple[float, float] | None:
    """Widen ATR-based SL/TP so scalps clear spread floor and round-turn costs.

    Does **not** loosen the 1% equity risk ceiling — wider stops only shrink
    position size. Returns ``(stop_loss, take_profit)`` or ``None`` when the
    market is too quiet / costs too high to stay within ATR caps while still
    clearing ``net_rr_floor`` after estimated costs.
    """
    if entry <= 0 or atr <= 0:
        return None

    min_rr = max(1.0, float(min_reward_risk_ratio))
    net_floor = max(1.0, float(net_rr_floor))
    stop_dist = max(float(atr_stop_multiple), 0.0) * atr
    target_dist = max(float(atr_target_multiple), 0.0) * atr

    pip_size = 1.0
    pip_value = 0.0
    cost = 0.0
    if symbol_spec:
        pip_size = float(symbol_spec.get("pip_size", 1.0) or 1.0)
        pip_value = float(symbol_spec.get("pip_value_per_lot", 0.0) or 0.0)
        typical = float(symbol_spec.get("typical_spread_pips", 0.0) or 0.0)
        min_stop = max(0.0, float(min_stop_spread_multiple)) * typical * pip_size
        if min_stop > 0:
            # Pad by a tiny fraction of a pip so float equality never fails the
            # risk manager's ``sl_pips < 2x typical`` hard floor.
            stop_dist = max(stop_dist, min_stop + pip_size * 1e-6)

        spread_for_cost = typical
        if spread_pips is not None and math.isfinite(spread_pips) and spread_pips > 0:
            spread_for_cost = max(spread_for_cost, float(spread_pips))
        cost = commission_per_lot(symbol_spec, entry) + spread_for_cost * pip_value

    max_stop = max(float(max_stop_atr_multiple), float(atr_stop_multiple)) * atr
    if stop_dist > max_stop + 1e-12:
        return None

    target_dist = max(target_dist, stop_dist * min_rr)
    if cost > 0 and pip_size > 0 and pip_value > 0:
        risk_value = (stop_dist / pip_size) * pip_value
        # (reward - cost) / (risk + cost) >= net_floor
        # → reward >= net_floor * (risk + cost) + cost
        min_reward_value = net_floor * (risk_value + cost) + cost
        min_target = (min_reward_value / pip_value) * pip_size
        target_dist = max(target_dist, min_target)

    max_target = max(float(max_target_atr_multiple), float(atr_target_multiple)) * atr
    if target_dist > max_target + 1e-12:
        return None

    if is_buy:
        return entry - stop_dist, entry + target_dist
    return entry + stop_dist, entry - target_dist


def calculate_position_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    symbol_spec: dict,
) -> float:
    """Position size (in lots) such that a stop-loss hit loses at most
    `risk_pct`% of `equity` **including** estimated round-turn commission."""
    if equity <= 0:
        raise ValueError("equity must be positive")

    risk_amount = equity * (risk_pct / 100.0)
    price_risk = abs(entry_price - stop_loss)
    if price_risk <= 0:
        raise ValueError("entry_price and stop_loss must differ")

    pip_size = symbol_spec["pip_size"]
    pip_value_per_lot = symbol_spec["pip_value_per_lot"]
    risk_pips = price_risk / pip_size
    if risk_pips <= 0:
        raise ValueError("computed risk_pips must be positive")

    loss_per_lot = risk_pips * pip_value_per_lot + commission_per_lot(symbol_spec, entry_price)
    raw_volume = risk_amount / loss_per_lot
    return round_to_lot_step(
        raw_volume,
        min_lot=symbol_spec["min_lot"],
        max_lot=symbol_spec["max_lot"],
        lot_step=symbol_spec["lot_step"],
    )


def kelly_fraction(win_rate: float, reward_risk_ratio: float, cap_pct: float) -> float:
    """Kelly criterion position-sizing fraction (% of equity), hard-capped at
    `cap_pct`. Never returns a value above the cap regardless of how
    favorable win_rate/reward_risk_ratio look — see CLAUDE.md rule #1.
    """
    if reward_risk_ratio <= 0:
        return 0.0
    b = reward_risk_ratio
    p = win_rate
    q = 1 - p
    kelly = p - (q / b)
    kelly_pct = max(0.0, kelly) * 100.0
    return min(kelly_pct, cap_pct)


def passes_spread_filter(current_spread_pips: float, max_allowed_pips: float) -> bool:
    return current_spread_pips <= max_allowed_pips


def passes_reward_risk_filter(signal: Signal, min_ratio: float) -> bool:
    return signal.risk_reward_ratio >= min_ratio


@dataclass
class DailyRiskTracker:
    """Tracks realized P&L for the current day and enforces the daily loss
    limit — once hit, no new trades are permitted until the tracker rolls
    over to a new day."""

    max_daily_loss_pct: float
    starting_equity: float
    _current_date: date = field(default_factory=lambda: datetime.now(tz=UTC).date())
    _realized_pnl_today: float = 0.0

    def record_trade_pnl(self, pnl: float, at: datetime | None = None) -> None:
        self._roll_over_if_new_day(at or datetime.now(tz=UTC))
        self._realized_pnl_today += pnl

    def reset(self, *, starting_equity: float | None = None) -> None:
        """Zero today's realized P&L (manual override / demo unlock)."""
        self._current_date = datetime.now(tz=UTC).date()
        self._realized_pnl_today = 0.0
        if starting_equity is not None:
            self.starting_equity = float(starting_equity)
        self._last_limit_log_at = 0.0
        logger.info("Daily risk tracker reset (realized_pnl_today=0)")

    def _roll_over_if_new_day(self, at: datetime) -> None:
        day = at.date() if at.tzinfo is None else at.astimezone(UTC).date()
        if day != self._current_date:
            self._current_date = day
            self._realized_pnl_today = 0.0

    def daily_loss_limit_hit(self, at: datetime | None = None) -> bool:
        self._roll_over_if_new_day(at or datetime.now(tz=UTC))
        loss_limit = -abs(self.starting_equity * (self.max_daily_loss_pct / 100.0))
        hit = self._realized_pnl_today <= loss_limit
        if hit:
            # Avoid flooding logs every poll tick while the limit remains active.
            now_ts = (at or datetime.now(tz=UTC)).timestamp()
            last = getattr(self, "_last_limit_log_at", 0.0)
            if now_ts - last >= 300.0:
                self._last_limit_log_at = now_ts
                logger.warning(
                    "Daily loss limit hit: realized_pnl_today={:.2f} <= limit={:.2f}",
                    self._realized_pnl_today,
                    loss_limit,
                )
        return hit


class RiskManager:
    """Facade combining sizing, filters, and breakeven/trailing logic behind
    a small API consumed by main.py / backtest/engine.py."""

    def __init__(
        self,
        risk_cfg: dict,
        spread_cfg: dict,
        symbols_cfg: dict,
        starting_equity: float,
    ) -> None:
        self.risk_cfg = risk_cfg
        self.spread_cfg = spread_cfg
        self.symbols_cfg = symbols_cfg
        self.daily_tracker = DailyRiskTracker(
            max_daily_loss_pct=risk_cfg.get("max_daily_loss_pct", 3.0),
            starting_equity=starting_equity,
        )

    def validate_signal(
        self,
        signal: Signal,
        current_spread_pips: float,
        *,
        min_reward_risk_ratio: float | None = None,
    ) -> bool:
        if self.daily_tracker.daily_loss_limit_hit():
            return False

        # Default hard floor remains 1.5; callers may pass a scoped override
        # (e.g. ultra_scalp min 1.0) without lowering the global risk config.
        min_rr = (
            float(min_reward_risk_ratio)
            if min_reward_risk_ratio is not None
            else float(self.risk_cfg.get("min_reward_risk_ratio", 1.5))
        )
        if min_rr < 1.0:
            min_rr = 1.0
        if not passes_reward_risk_filter(signal, min_rr):
            logger.debug(
                "Signal rejected: R:R {:.2f} < min {:.2f}", signal.risk_reward_ratio, min_rr
            )
            return False

        # Net R:R must survive round-turn commission AND spread — a 25-point BTC
        # scalp against a $78/lot commission, or a 0.8-pip EURJPY scalp against
        # a 0.3-pip spread, is guaranteed negative expectancy regardless of win
        # rate, so refuse it instead of burning the account on costs.
        spec = self.symbols_cfg.get(signal.symbol)
        if spec:
            pip_size = float(spec["pip_size"])
            pip_value = float(spec["pip_value_per_lot"])
            sl_pips = abs(signal.entry_price - signal.stop_loss) / pip_size

            # Hard floor: sub-spread stops (e.g. 0.39-pip USDJPY) are noise
            # trades that also force absurd volumes; 2x typical spread minimum.
            min_stop_pips = 2.0 * float(spec.get("typical_spread_pips", 0) or 0)
            if min_stop_pips > 0 and sl_pips + 1e-9 < min_stop_pips:
                logger.info(
                    "Signal rejected ({}): SL distance {:.2f} pips < floor {:.2f} "
                    "(2x typical spread)",
                    signal.symbol,
                    sl_pips,
                    min_stop_pips,
                )
                return False

            comm = commission_per_lot(spec, signal.entry_price)
            spread_cost = 0.0
            if math.isfinite(current_spread_pips) and current_spread_pips > 0:
                spread_cost = current_spread_pips * pip_value
            cost = comm + spread_cost
            if cost > 0:
                risk_value = sl_pips * pip_value
                reward_value = abs(signal.take_profit - signal.entry_price) / pip_size * pip_value
                if risk_value + cost <= 0:
                    return False
                net_rr = (reward_value - cost) / (risk_value + cost)
                # Gross geometry already passed min_rr above. After costs the
                # trade must still offer at least 1:1 — otherwise expectancy is
                # negative at any realistic win rate. Negligible costs (≤5% of
                # reward) never veto.
                net_floor = 1.0
                if cost > 0.05 * reward_value and net_rr < net_floor:
                    logger.info(
                        "Signal rejected ({}): net R:R {:.2f} < floor {:.2f} after costs "
                        "(commission={:.2f} spread={:.2f} per lot; reward={:.2f} risk={:.2f})",
                        signal.symbol,
                        net_rr,
                        net_floor,
                        comm,
                        spread_cost,
                        reward_value,
                        risk_value,
                    )
                    return False

        if self.spread_cfg.get("enabled", True):
            max_spread = self.spread_cfg.get("max_spread_pips", {}).get(signal.symbol)
            if max_spread is not None and not passes_spread_filter(current_spread_pips, max_spread):
                logger.debug(
                    "Signal rejected: spread {:.2f} > max {:.2f} for {}",
                    current_spread_pips,
                    max_spread,
                    signal.symbol,
                )
                return False

        return True

    def position_size_for(
        self, signal: Signal, equity: float, win_rate_estimate: float = 0.6
    ) -> float:
        symbol_spec = self.symbols_cfg[signal.symbol]
        risk_pct = resolve_active_risk_pct(self.risk_cfg)

        if self.risk_cfg.get("use_kelly_sizing", False):
            risk_pct = kelly_fraction(
                win_rate=win_rate_estimate,
                reward_risk_ratio=signal.risk_reward_ratio,
                cap_pct=risk_pct,
            )
            if risk_pct <= 0:
                return 0.0

        return calculate_position_size(
            equity=equity,
            risk_pct=risk_pct,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            symbol_spec=symbol_spec,
        )

    def breakeven_stop(self, position: Position, current_price: float) -> float | None:
        """Return a new stop-loss at entry (breakeven) once price has moved
        ``breakeven_at_r_multiple`` R in favor, else None.

        R is measured from the *initial* stop (not a already-trailed SL). Never
        returns a stop that widens risk versus the current SL — e.g. after ATR
        trailing has already locked profit past entry.
        """
        if position.breakeven_moved:
            return None
        r_trigger = self.risk_cfg.get("breakeven_at_r_multiple", 1.0)
        sl0 = (
            position.initial_stop_loss
            if position.initial_stop_loss is not None
            else position.stop_loss
        )
        risk = abs(position.entry_price - sl0)
        if risk == 0:
            return None

        favorable_move = (
            current_price - position.entry_price
            if position.direction.value == "buy"
            else position.entry_price - current_price
        )
        if favorable_move < r_trigger * risk:
            return None

        candidate = position.entry_price
        if position.direction.value == "buy":
            return candidate if candidate > position.stop_loss else None
        return candidate if candidate < position.stop_loss else None

    def trailing_stop(
        self, position: Position, current_price: float, atr_value: float
    ) -> float | None:
        """ATR-based trailing stop. Returns a new SL only if it's tighter
        than the current one (never widens risk)."""
        multiple = self.risk_cfg.get("trailing_stop_atr_multiple", 1.5)
        if position.direction.value == "buy":
            candidate = current_price - multiple * atr_value
            if candidate > position.stop_loss:
                return candidate
        else:
            candidate = current_price + multiple * atr_value
            if candidate < position.stop_loss:
                return candidate
        return None
