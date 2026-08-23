"""Persistent trade journal for live/paper sessions — feeds the dashboard."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chronoscalp.logging_setup import logger
from chronoscalp.utils.strategy_tags import (
    STRATEGY_REPORT_ORDER,
    STRATEGY_UNKNOWN,
    normalize_strategy_tag,
    resolve_strategy_tag,
)
from chronoscalp.utils.types import Position, SignalType, TradeResult


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _dt_to_iso(value: datetime | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.isoformat()
    return str(value)


def dollar_risk_amount(
    *,
    entry: float,
    stop: float,
    volume: float,
    pip_size: float,
    pip_value_per_lot: float,
) -> float:
    """Dollar risk at entry given stop distance, pip specs, and lot volume.

    ``(abs(entry - stop) / pip_size) * pip_value_per_lot * volume``.
    Returns 0.0 when pip_size is non-positive.
    """
    if pip_size <= 0:
        return 0.0
    return (
        (abs(float(entry) - float(stop)) / float(pip_size))
        * float(pip_value_per_lot)
        * float(volume)
    )


def r_multiple_from_pnl(pnl: float, dollar_risk: float) -> float:
    """Realized R as ``pnl / dollar_risk``, rounded to 3 decimals.

    Returns 0.0 when ``dollar_risk`` is not positive (fail closed for analytics).
    """
    if dollar_risk <= 0:
        return 0.0
    return round(float(pnl) / float(dollar_risk), 3)


def _join_data_quality(*flags: str) -> str:
    parts = [f.strip() for f in flags if f and str(f).strip()]
    return ",".join(parts)


def _lookup_symbol_spec(symbols_cfg: dict[str, Any] | None, symbol: str) -> dict[str, Any] | None:
    """Resolve symbol pip specs; try exact key, then strip a trailing ``_o`` suffix."""
    if not symbols_cfg or not symbol:
        return None
    if symbol in symbols_cfg:
        return symbols_cfg[symbol]
    if symbol.endswith("_o"):
        base = symbol[:-2]
        if base in symbols_cfg:
            return symbols_cfg[base]
    return None


@dataclass
class OpenTradeRecord:
    """An open position as recorded when the bot places an order."""

    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    stop_loss: float
    take_profit: float
    open_time: str
    mode: str = "paper"
    strategy: str = ""
    reason: str = ""
    initial_stop_loss: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenTradeRecord:
        strategy = resolve_strategy_tag(
            explicit=str(data.get("strategy") or ""),
            reason=str(data.get("reason") or ""),
        )
        raw_isl = data.get("initial_stop_loss")
        initial_stop_loss: float | None = (
            None if raw_isl is None or raw_isl == "" else float(raw_isl)
        )
        return cls(
            ticket=int(data["ticket"]),
            symbol=str(data["symbol"]),
            direction=str(data.get("direction") or ""),
            volume=float(data.get("volume") or 0),
            entry_price=float(data.get("entry_price") or 0),
            stop_loss=float(data.get("stop_loss") or 0),
            take_profit=float(data.get("take_profit") or 0),
            open_time=str(data.get("open_time") or ""),
            mode=str(data.get("mode") or "paper"),
            strategy=strategy,
            reason=str(data.get("reason") or ""),
            initial_stop_loss=initial_stop_loss,
        )

    @classmethod
    def from_position(cls, position: Position, mode: str) -> OpenTradeRecord:
        direction = (
            position.direction.value
            if isinstance(position.direction, SignalType)
            else str(position.direction)
        )
        strategy = resolve_strategy_tag(explicit=getattr(position, "strategy", "") or "")
        initial_sl = (
            position.initial_stop_loss
            if position.initial_stop_loss is not None
            else position.stop_loss
        )
        return cls(
            ticket=position.ticket,
            symbol=position.symbol,
            direction=direction,
            volume=float(position.volume),
            entry_price=float(position.entry_price),
            stop_loss=float(position.stop_loss),
            take_profit=float(position.take_profit),
            open_time=_dt_to_iso(position.open_time),
            mode=mode,
            strategy=strategy,
            reason="",
            initial_stop_loss=float(initial_sl) if initial_sl is not None else None,
        )


@dataclass
class ClosedTradeRecord:
    """A fully closed trade with realized P&L."""

    ticket: int
    symbol: str
    direction: str
    volume: float
    entry_price: float
    exit_price: float
    open_time: str
    close_time: str
    pnl: float
    r_multiple: float = 0.0
    exit_reason: str = ""
    mode: str = "paper"
    strategy: str = ""
    reason: str = ""
    data_quality: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClosedTradeRecord:
        strategy = resolve_strategy_tag(
            explicit=str(data.get("strategy") or ""),
            reason=str(data.get("reason") or data.get("exit_reason") or ""),
        )
        return cls(
            ticket=int(data.get("ticket") or 0),
            symbol=str(data.get("symbol") or ""),
            direction=str(data.get("direction") or ""),
            volume=float(data.get("volume") or 0),
            entry_price=float(data.get("entry_price") or 0),
            exit_price=float(data.get("exit_price") or 0),
            open_time=str(data.get("open_time") or ""),
            close_time=str(data.get("close_time") or ""),
            pnl=float(data.get("pnl") or 0),
            r_multiple=float(data.get("r_multiple") or 0),
            exit_reason=str(data.get("exit_reason") or ""),
            mode=str(data.get("mode") or "paper"),
            strategy=strategy,
            reason=str(data.get("reason") or ""),
            data_quality=str(data.get("data_quality") or ""),
        )


@dataclass
class TradingStats:
    """Aggregated live/paper trading statistics for the dashboard."""

    closed_trades: int = 0
    open_trades: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakevens: int = 0
    win_rate_pct: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    avg_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_r_multiple: float = 0.0
    avg_return_pct: float = 0.0
    profit_factor: float | None = None
    expectancy: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    today_pnl: float = 0.0
    today_trades: int = 0
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["profit_factor"] is None:
            data["profit_factor"] = None
        elif data["profit_factor"] == float("inf"):
            data["profit_factor"] = "inf"
        return data


@dataclass
class StrategyStats:
    """Per-strategy P&L breakdown for API / dashboard reports."""

    strategy: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate_pct: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    avg_pnl: float = 0.0
    profit_share_pct: float = 0.0
    loss_share_pct: float = 0.0
    pnl_pct_of_equity: float = 0.0
    open_trades: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_strategy_stats(
    closed: list[ClosedTradeRecord],
    open_trades: list[OpenTradeRecord] | None = None,
    *,
    reference_equity: float | None = None,
) -> list[StrategyStats]:
    """Aggregate closed (and open counts) by strategy tag."""
    open_trades = open_trades or []
    by_tag: dict[str, list[ClosedTradeRecord]] = {}
    for trade in closed:
        tag = normalize_strategy_tag(trade.strategy) or STRATEGY_UNKNOWN
        by_tag.setdefault(tag, []).append(trade)

    open_counts: dict[str, int] = {}
    for trade in open_trades:
        tag = normalize_strategy_tag(trade.strategy) or STRATEGY_UNKNOWN
        open_counts[tag] = open_counts.get(tag, 0) + 1

    total_profit = sum(t.pnl for t in closed if t.pnl > 0) or 0.0
    total_loss_abs = abs(sum(t.pnl for t in closed if t.pnl < 0)) or 0.0
    equity = float(reference_equity) if reference_equity and reference_equity > 0 else 0.0

    tags = set(by_tag) | set(open_counts)
    ordered = [t for t in STRATEGY_REPORT_ORDER if t in tags]
    ordered.extend(sorted(t for t in tags if t not in STRATEGY_REPORT_ORDER))

    rows: list[StrategyStats] = []
    for tag in ordered:
        group = by_tag.get(tag, [])
        wins = [t for t in group if t.pnl > 0]
        losses = [t for t in group if t.pnl < 0]
        net = sum(t.pnl for t in group)
        gp = sum(t.pnl for t in wins)
        gl = abs(sum(t.pnl for t in losses))
        n = len(group)
        rows.append(
            StrategyStats(
                strategy=tag,
                trades=n,
                wins=len(wins),
                losses=len(losses),
                win_rate_pct=round(len(wins) / n * 100, 2) if n else 0.0,
                net_pnl=round(net, 2),
                gross_profit=round(gp, 2),
                gross_loss=round(gl, 2),
                avg_pnl=round(net / n, 2) if n else 0.0,
                profit_share_pct=round(gp / total_profit * 100, 2) if total_profit else 0.0,
                loss_share_pct=round(gl / total_loss_abs * 100, 2) if total_loss_abs else 0.0,
                pnl_pct_of_equity=round(net / equity * 100, 4) if equity else 0.0,
                open_trades=int(open_counts.get(tag, 0)),
            )
        )
    return rows


@dataclass
class JournalSnapshot:
    """Full journal payload consumed by the dashboard."""

    mode: str
    open_trades: list[OpenTradeRecord] = field(default_factory=list)
    closed_trades: list[ClosedTradeRecord] = field(default_factory=list)
    stats: TradingStats = field(default_factory=TradingStats)
    strategy_stats: list[StrategyStats] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "open_trades": [t.to_dict() for t in self.open_trades],
            "closed_trades": [t.to_dict() for t in self.closed_trades],
            "stats": self.stats.to_dict(),
            "strategy_stats": [s.to_dict() for s in self.strategy_stats],
        }


def compute_trading_stats(
    closed: list[ClosedTradeRecord],
    open_trades: list[OpenTradeRecord],
    *,
    reference_equity: float | None = None,
    as_of: datetime | None = None,
) -> TradingStats:
    """Compute dashboard metrics from closed + open journal rows.

    ``as_of`` pins the \"today\" cutoff (UTC date) for tests; production leaves it
    unset so the wall-clock UTC date is used.
    """
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl < 0]
    flats = [t for t in closed if t.pnl == 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    net_pnl = sum(t.pnl for t in closed)
    n = len(closed)

    ref = as_of.astimezone(UTC) if as_of is not None else datetime.now(tz=UTC)
    today = ref.date().isoformat()
    today_rows = [t for t in closed if (t.close_time or "")[:10] == today]

    avg_return_pct = 0.0
    if reference_equity and reference_equity > 0 and n:
        avg_return_pct = round(
            sum(t.pnl / reference_equity * 100 for t in closed) / n,
            4,
        )

    profit_factor: float | None
    if gross_loss > 0:
        profit_factor = round(gross_profit / gross_loss, 3)
    elif gross_profit > 0:
        profit_factor = float("inf")
    else:
        profit_factor = None

    r_values = [t.r_multiple for t in closed]
    avg_r = round(sum(r_values) / len(r_values), 3) if r_values else 0.0

    return TradingStats(
        closed_trades=n,
        open_trades=len(open_trades),
        total_trades=n + len(open_trades),
        wins=len(wins),
        losses=len(losses),
        breakevens=len(flats),
        win_rate_pct=round(len(wins) / n * 100, 2) if n else 0.0,
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        net_pnl=round(net_pnl, 2),
        avg_pnl=round(net_pnl / n, 2) if n else 0.0,
        avg_win=round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0.0,
        avg_loss=round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0.0,
        avg_r_multiple=avg_r,
        avg_return_pct=avg_return_pct,
        profit_factor=profit_factor,
        expectancy=round(net_pnl / n, 2) if n else 0.0,
        best_trade=round(max((t.pnl for t in closed), default=0.0), 2),
        worst_trade=round(min((t.pnl for t in closed), default=0.0), 2),
        max_consecutive_wins=_max_streak(closed, winning=True),
        max_consecutive_losses=_max_streak(closed, winning=False),
        today_pnl=round(sum(t.pnl for t in today_rows), 2),
        today_trades=len(today_rows),
        updated_at=_utc_now_iso(),
    )


def _max_streak(closed: list[ClosedTradeRecord], *, winning: bool) -> int:
    best = 0
    current = 0
    for trade in closed:
        hit = trade.pnl > 0 if winning else trade.pnl < 0
        if hit:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _open_trade_key(symbol: str, strategy: str, ticket: int) -> str:
    tag = resolve_strategy_tag(explicit=strategy)
    return f"{symbol}::{tag}::{int(ticket)}"


class OpenTradesMap(dict):
    """Open rows keyed by symbol::strategy::ticket, with unique-ticket int lookup."""

    def store(self, record: OpenTradeRecord) -> None:
        dict.__setitem__(
            self, _open_trade_key(record.symbol, record.strategy, record.ticket), record
        )

    def keys_for(
        self,
        ticket: int,
        *,
        symbol: str | None = None,
        strategy: str | None = None,
    ) -> list:
        tag = resolve_strategy_tag(explicit=strategy) if strategy else ""
        matches: list = []
        for key, rec in dict.items(self):
            if int(rec.ticket) != int(ticket):
                continue
            if symbol is not None and rec.symbol != symbol:
                continue
            if tag and rec.strategy != tag:
                continue
            matches.append(key)
        if not matches and dict.__contains__(self, ticket):
            matches.append(ticket)
        return matches

    def __contains__(self, key: object) -> bool:
        if dict.__contains__(self, key):
            return True
        if isinstance(key, int):
            return any(rec.ticket == key for rec in dict.values(self))
        return False

    def __getitem__(self, key: object) -> OpenTradeRecord:
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if isinstance(key, int):
            matches = [rec for rec in dict.values(self) if rec.ticket == key]
            if len(matches) == 1:
                return matches[0]
        raise KeyError(key)

    def get(self, key, default=None):  # noqa: ANN001
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key, default=None):  # noqa: ANN001
        if dict.__contains__(self, key):
            return dict.pop(self, key)
        if isinstance(key, int):
            matches = self.keys_for(key)
            if len(matches) == 1:
                return dict.pop(self, matches[0])
            return default
        return dict.pop(self, key, default)


class TradeJournal:
    """JSON-backed journal of open + closed trades for one bot mode."""

    def __init__(
        self,
        path: str | Path,
        mode: str = "paper",
        symbols_cfg: dict[str, Any] | None = None,
    ) -> None:
        self.path = Path(path)
        self.mode = mode
        self.symbols_cfg = symbols_cfg
        self.open_trades: OpenTradesMap = OpenTradesMap()
        self.closed_trades: list[ClosedTradeRecord] = []

    def load(self) -> None:
        if not self.path.exists():
            self.open_trades = OpenTradesMap()
            self.closed_trades = []
            return
        with self.path.open(encoding="utf-8-sig") as f:
            raw = json.load(f)
        self.mode = str(raw.get("mode") or self.mode)
        self.open_trades = OpenTradesMap()
        for row in raw.get("open_trades") or []:
            if row.get("ticket") is None:
                continue
            self.open_trades.store(OpenTradeRecord.from_dict(row))
        self.closed_trades = [
            ClosedTradeRecord.from_dict(row) for row in (raw.get("closed_trades") or [])
        ]
        logger.info(
            "Loaded trade journal {}: {} open, {} closed",
            self.path,
            len(self.open_trades),
            len(self.closed_trades),
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "mode": self.mode,
            "updated_at": _utc_now_iso(),
            "open_trades": [t.to_dict() for t in self.open_trades.values()],
            "closed_trades": [t.to_dict() for t in self.closed_trades],
        }
        with self.path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def _pop_open(
        self,
        ticket: int,
        *,
        symbol: str | None = None,
        strategy: str | None = None,
    ) -> OpenTradeRecord | None:
        keys = self.open_trades.keys_for(ticket, symbol=symbol, strategy=strategy)
        if len(keys) == 1:
            return dict.pop(self.open_trades, keys[0])
        return None

    def record_open(
        self,
        position: Position,
        *,
        strategy: str | None = None,
        reason: str | None = None,
    ) -> OpenTradeRecord:
        record = OpenTradeRecord.from_position(position, self.mode)
        if strategy is not None and str(strategy).strip():
            record.strategy = resolve_strategy_tag(explicit=strategy, reason=reason)
        elif reason:
            record.strategy = resolve_strategy_tag(explicit=record.strategy, reason=reason)
        if reason is not None:
            record.reason = str(reason)
        self.open_trades.store(record)
        self.save()
        return record

    def record_close(self, trade: TradeResult, ticket: int | None = None) -> ClosedTradeRecord:
        resolved_ticket = ticket
        if resolved_ticket is None:
            for open_rec in list(self.open_trades.values()):
                if open_rec.symbol == trade.symbol:
                    resolved_ticket = open_rec.ticket
                    break
        resolved_ticket = int(resolved_ticket or 0)

        open_rec = self._pop_open(
            resolved_ticket,
            symbol=getattr(trade, "symbol", None),
            strategy=getattr(trade, "strategy", None) or None,
        )
        direction = (
            trade.direction.value
            if isinstance(trade.direction, SignalType)
            else str(trade.direction)
        )
        strategy = resolve_strategy_tag(
            explicit=getattr(trade, "strategy", "") or (open_rec.strategy if open_rec else ""),
            reason=(open_rec.reason if open_rec else ""),
        )
        volume = float(trade.volume or (open_rec.volume if open_rec else 0))
        entry_price = float(trade.entry_price or (open_rec.entry_price if open_rec else 0))
        pnl = float(trade.pnl)
        quality_flags: list[str] = []
        r_multiple = float(trade.r_multiple or 0)
        # Broker adapters (e.g. MT5) often omit r_multiple; recompute from dollar risk.
        if abs(r_multiple) < 1e-12 and open_rec is not None and self.symbols_cfg:
            stop_for_risk = (
                float(open_rec.initial_stop_loss)
                if open_rec.initial_stop_loss is not None
                else float(open_rec.stop_loss)
            )
            spec = _lookup_symbol_spec(self.symbols_cfg, trade.symbol or open_rec.symbol)
            if spec is None:
                quality_flags.append("missing_spec")
            else:
                dollar_risk = dollar_risk_amount(
                    entry=entry_price,
                    stop=stop_for_risk,
                    volume=volume,
                    pip_size=float(spec.get("pip_size") or 0),
                    pip_value_per_lot=float(spec.get("pip_value_per_lot") or 0),
                )
                r_multiple = r_multiple_from_pnl(pnl, dollar_risk)
                if abs(r_multiple) > 10:
                    logger.warning(
                        "Journal: implausible R={:.3f} ticket={} on record_close — clamping to 0",
                        r_multiple,
                        resolved_ticket,
                    )
                    r_multiple = 0.0
                    quality_flags.append("implausible_r")
        record = ClosedTradeRecord(
            ticket=resolved_ticket or (open_rec.ticket if open_rec else 0),
            symbol=trade.symbol,
            direction=direction or (open_rec.direction if open_rec else ""),
            volume=volume,
            entry_price=entry_price,
            exit_price=float(trade.exit_price),
            open_time=_dt_to_iso(trade.open_time) or (open_rec.open_time if open_rec else ""),
            close_time=_dt_to_iso(trade.close_time) or _utc_now_iso(),
            pnl=pnl,
            r_multiple=r_multiple,
            exit_reason=str(trade.exit_reason or ""),
            mode=self.mode,
            strategy=strategy,
            reason=open_rec.reason if open_rec else "",
            data_quality=_join_data_quality(*quality_flags),
        )
        self.closed_trades.append(record)
        self.save()
        return record

    def record_external_close(
        self,
        ticket: int,
        symbol: str,
        pnl: float | None,
        *,
        at: datetime | None = None,
        strategy: str | None = None,
    ) -> ClosedTradeRecord | None:
        """Record a broker-side close matched to a journal open row.

        Fail-closed for orphans (no open row): returns ``None`` and does not
        write a blank volume=0 closed trade. R is ``pnl / dollar_risk`` using
        ``initial_stop_loss`` when available and symbol pip specs from
        ``symbols_cfg``; missing specs or implausible |R|>10 yield ``r_multiple=0``
        with a ``data_quality`` flag rather than a price-distance fallback.
        """
        open_rec = self._pop_open(ticket, symbol=symbol, strategy=strategy)
        if open_rec is None:
            logger.warning(
                "Journal: orphan external close ticket={} symbol={} pnl={} — skipped",
                ticket,
                symbol,
                pnl,
            )
            return None

        entry = float(open_rec.entry_price)
        stop_for_risk = (
            float(open_rec.initial_stop_loss)
            if open_rec.initial_stop_loss is not None
            else float(open_rec.stop_loss)
        )
        realized = float(pnl) if pnl is not None else 0.0
        quality_flags: list[str] = []

        resolved_symbol = symbol or open_rec.symbol
        spec = _lookup_symbol_spec(self.symbols_cfg, resolved_symbol)
        r_multiple = 0.0
        if pnl is None:
            r_multiple = 0.0
        elif spec is None:
            quality_flags.append("missing_spec")
            r_multiple = 0.0
        else:
            pip_size = float(spec.get("pip_size") or 0)
            pip_value = float(spec.get("pip_value_per_lot") or 0)
            dollar_risk = dollar_risk_amount(
                entry=entry,
                stop=stop_for_risk,
                volume=float(open_rec.volume),
                pip_size=pip_size,
                pip_value_per_lot=pip_value,
            )
            r_multiple = r_multiple_from_pnl(realized, dollar_risk)
            if abs(r_multiple) > 10:
                logger.warning(
                    "Journal: implausible R={:.3f} ticket={} — clamping to 0",
                    r_multiple,
                    ticket,
                )
                r_multiple = 0.0
                quality_flags.append("implausible_r")

        open_time_str = open_rec.open_time or ""
        close_time_str = _dt_to_iso(at) or _utc_now_iso()
        opened_at = _parse_iso(open_time_str)
        closed_at = _parse_iso(close_time_str)
        if opened_at is not None and closed_at is not None and closed_at < opened_at:
            close_time_str = open_time_str
            quality_flags.append("timestamp_adjusted")
            logger.warning(
                "Journal: close_time before open_time ticket={} — adjusted close to open",
                ticket,
            )

        record = ClosedTradeRecord(
            ticket=ticket,
            symbol=resolved_symbol,
            direction=open_rec.direction,
            volume=float(open_rec.volume),
            entry_price=entry,
            exit_price=entry,
            open_time=open_time_str,
            close_time=close_time_str,
            pnl=realized,
            r_multiple=r_multiple,
            exit_reason="external" if pnl is not None else "external_unknown_pnl",
            mode=self.mode,
            strategy=resolve_strategy_tag(
                explicit=open_rec.strategy,
                reason=open_rec.reason,
            ),
            reason=open_rec.reason,
            data_quality=_join_data_quality(*quality_flags),
        )
        self.closed_trades.append(record)
        self.save()
        return record

    def sync_open_from_broker(
        self,
        positions: list[Position],
        *,
        ghost_grace_seconds: float = 90.0,
        now: datetime | None = None,
    ) -> None:
        """Reconcile journal opens with broker: adopt missing, drop stale ghosts.

        Fresh opens are kept for ``ghost_grace_seconds`` even if a transient
        ``positions_get`` miss would otherwise wipe them (common right after
        ``order_send`` or during MT5 reconnect hiccups).
        """
        changed = False
        as_of = now or datetime.now(tz=UTC)

        def _identity(symbol: str, strategy: str, ticket: int) -> tuple[str, str, int]:
            return (symbol, resolve_strategy_tag(explicit=strategy), int(ticket))

        broker_ids = {
            _identity(pos.symbol, getattr(pos, "strategy", "") or "", pos.ticket)
            for pos in positions
        }
        for key, open_rec in list(self.open_trades.items()):
            rec_id = _identity(open_rec.symbol, open_rec.strategy, open_rec.ticket)
            if rec_id in broker_ids:
                continue
            ticket_hits = [pos for pos in positions if int(pos.ticket) == int(open_rec.ticket)]
            if len(ticket_hits) == 1 and ticket_hits[0].symbol == open_rec.symbol:
                continue
            opened_at = _parse_iso(open_rec.open_time)
            if opened_at is not None and ghost_grace_seconds > 0:
                age = (as_of - opened_at).total_seconds()
                if age < ghost_grace_seconds:
                    logger.debug(
                        "Journal: keeping recent open ticket={} age={:.1f}s < grace={:.0f}s",
                        open_rec.ticket,
                        age,
                        ghost_grace_seconds,
                    )
                    continue
            self.open_trades.pop(key, None)
            changed = True
            logger.info(
                "Journal: dropping ghost open ticket={} strategy={} (not on broker)",
                open_rec.ticket,
                open_rec.strategy,
            )
        for position in positions:
            rec_id = _identity(
                position.symbol, getattr(position, "strategy", "") or "", position.ticket
            )
            exists = any(
                _identity(rec.symbol, rec.strategy, rec.ticket) == rec_id
                for rec in self.open_trades.values()
            )
            if not exists:
                self.open_trades.store(OpenTradeRecord.from_position(position, self.mode))
                changed = True
        if changed:
            self.save()

    def snapshot(self, reference_equity: float | None = None) -> JournalSnapshot:
        open_list = list(self.open_trades.values())
        stats = compute_trading_stats(
            self.closed_trades, open_list, reference_equity=reference_equity
        )
        strategy_stats = compute_strategy_stats(
            self.closed_trades, open_list, reference_equity=reference_equity
        )
        return JournalSnapshot(
            mode=self.mode,
            open_trades=open_list,
            closed_trades=list(self.closed_trades),
            stats=stats,
            strategy_stats=strategy_stats,
        )


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def sum_closed_pnl_today(
    closed_trades: list[ClosedTradeRecord],
    now: datetime | None = None,
    since: datetime | None = None,
) -> float:
    """Realized P&L of trades closed on the current UTC date.

    Used to re-seed the daily loss tracker after a restart so the 3% daily
    stop cannot be bypassed by bouncing the process. ``since`` (an explicit
    operator reset marker) excludes trades closed at or before that moment —
    a conscious demo-account reset, not an accidental loophole.
    """
    ref = (now or datetime.now(tz=UTC)).astimezone(UTC)
    today = ref.date().isoformat()
    total = 0.0
    for t in closed_trades:
        close_time = t.close_time or ""
        if close_time[:10] != today:
            continue
        if since is not None:
            closed_at = _parse_iso(close_time)
            if closed_at is not None and closed_at <= since:
                continue
        total += t.pnl
    return float(total)


def load_daily_reset_marker(state_dir: str | Path, mode: str) -> datetime | None:
    """Operator's explicit daily-tracker reset timestamp (or None)."""
    path = Path(state_dir) / f"daily_reset_{mode}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return _parse_iso(str(payload.get("reset_at") or ""))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def write_daily_reset_marker(state_dir: str | Path, mode: str) -> datetime:
    """Write an operator reset marker so prior closed trades stop counting today.

    The live/paper bot must be restarted for the marker to take effect (it is
    applied when seeding the daily tracker at startup).
    """
    path = Path(state_dir) / f"daily_reset_{mode}.json"
    reset_at = datetime.now(tz=UTC)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"reset_at": reset_at.isoformat()}, indent=2),
        encoding="utf-8",
    )
    return reset_at


def journal_path_for(state_dir: str | Path, mode: str) -> Path:
    """Canonical path: ``data/state/trade_journal_{mode}.json``."""
    return Path(state_dir) / f"trade_journal_{mode}.json"


def load_journal_snapshot(
    state_dir: str | Path,
    mode: str,
    *,
    reference_equity: float | None = None,
) -> JournalSnapshot:
    """Read-only helper for dashboards (does not mutate disk)."""
    journal = TradeJournal(journal_path_for(state_dir, mode), mode=mode)
    journal.load()
    return journal.snapshot(reference_equity=reference_equity)
