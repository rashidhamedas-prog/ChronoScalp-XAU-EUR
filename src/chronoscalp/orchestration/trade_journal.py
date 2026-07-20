"""Persistent trade journal for live/paper sessions — feeds the dashboard."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from chronoscalp.logging_setup import logger
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenTradeRecord:
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
        )

    @classmethod
    def from_position(cls, position: Position, mode: str) -> OpenTradeRecord:
        direction = (
            position.direction.value
            if isinstance(position.direction, SignalType)
            else str(position.direction)
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ClosedTradeRecord:
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
class JournalSnapshot:
    """Full journal payload consumed by the dashboard."""

    mode: str
    open_trades: list[OpenTradeRecord] = field(default_factory=list)
    closed_trades: list[ClosedTradeRecord] = field(default_factory=list)
    stats: TradingStats = field(default_factory=TradingStats)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "open_trades": [t.to_dict() for t in self.open_trades],
            "closed_trades": [t.to_dict() for t in self.closed_trades],
            "stats": self.stats.to_dict(),
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


class TradeJournal:
    """JSON-backed journal of open + closed trades for one bot mode."""

    def __init__(self, path: str | Path, mode: str = "paper") -> None:
        self.path = Path(path)
        self.mode = mode
        self.open_trades: dict[int, OpenTradeRecord] = {}
        self.closed_trades: list[ClosedTradeRecord] = []

    def load(self) -> None:
        if not self.path.exists():
            self.open_trades = {}
            self.closed_trades = []
            return
        with self.path.open(encoding="utf-8") as f:
            raw = json.load(f)
        self.mode = str(raw.get("mode") or self.mode)
        self.open_trades = {
            int(row["ticket"]): OpenTradeRecord.from_dict(row)
            for row in (raw.get("open_trades") or [])
            if row.get("ticket") is not None
        }
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

    def record_open(self, position: Position) -> OpenTradeRecord:
        record = OpenTradeRecord.from_position(position, self.mode)
        self.open_trades[record.ticket] = record
        self.save()
        return record

    def record_close(self, trade: TradeResult, ticket: int | None = None) -> ClosedTradeRecord:
        resolved_ticket = ticket
        if resolved_ticket is None:
            # Match by symbol among open rows when ticket unknown
            for open_ticket, open_rec in list(self.open_trades.items()):
                if open_rec.symbol == trade.symbol:
                    resolved_ticket = open_ticket
                    break
        resolved_ticket = int(resolved_ticket or 0)

        open_rec = self.open_trades.pop(resolved_ticket, None)
        direction = (
            trade.direction.value
            if isinstance(trade.direction, SignalType)
            else str(trade.direction)
        )
        record = ClosedTradeRecord(
            ticket=resolved_ticket or (open_rec.ticket if open_rec else 0),
            symbol=trade.symbol,
            direction=direction or (open_rec.direction if open_rec else ""),
            volume=float(trade.volume or (open_rec.volume if open_rec else 0)),
            entry_price=float(trade.entry_price or (open_rec.entry_price if open_rec else 0)),
            exit_price=float(trade.exit_price),
            open_time=_dt_to_iso(trade.open_time) or (open_rec.open_time if open_rec else ""),
            close_time=_dt_to_iso(trade.close_time) or _utc_now_iso(),
            pnl=float(trade.pnl),
            r_multiple=float(trade.r_multiple or 0),
            exit_reason=str(trade.exit_reason or ""),
            mode=self.mode,
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
    ) -> ClosedTradeRecord | None:
        open_rec = self.open_trades.pop(ticket, None)
        if open_rec is None and pnl is None:
            self.save()
            return None

        entry = open_rec.entry_price if open_rec else 0.0
        risk = abs((open_rec.entry_price - open_rec.stop_loss) if open_rec else 0.0)
        realized = float(pnl) if pnl is not None else 0.0
        r_multiple = round(realized / risk, 3) if risk and pnl is not None else 0.0

        record = ClosedTradeRecord(
            ticket=ticket,
            symbol=symbol or (open_rec.symbol if open_rec else ""),
            direction=open_rec.direction if open_rec else "",
            volume=open_rec.volume if open_rec else 0.0,
            entry_price=entry,
            exit_price=entry,
            open_time=open_rec.open_time if open_rec else "",
            close_time=_dt_to_iso(at) or _utc_now_iso(),
            pnl=realized,
            r_multiple=r_multiple,
            exit_reason="external" if pnl is not None else "external_unknown_pnl",
            mode=self.mode,
        )
        self.closed_trades.append(record)
        self.save()
        return record

    def sync_open_from_broker(self, positions: list[Position]) -> None:
        """Adopt broker open positions missing from the journal (after reconcile)."""
        changed = False
        for position in positions:
            if position.ticket not in self.open_trades:
                self.open_trades[position.ticket] = OpenTradeRecord.from_position(
                    position, self.mode
                )
                changed = True
        if changed:
            self.save()

    def snapshot(self, reference_equity: float | None = None) -> JournalSnapshot:
        open_list = list(self.open_trades.values())
        stats = compute_trading_stats(
            self.closed_trades, open_list, reference_equity=reference_equity
        )
        return JournalSnapshot(
            mode=self.mode,
            open_trades=open_list,
            closed_trades=list(self.closed_trades),
            stats=stats,
        )


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
