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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenTradeRecord:
        strategy = resolve_strategy_tag(
            explicit=str(data.get("strategy") or ""),
            reason=str(data.get("reason") or ""),
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
        )

    @classmethod
    def from_position(cls, position: Position, mode: str) -> OpenTradeRecord:
        direction = (
            position.direction.value
            if isinstance(position.direction, SignalType)
            else str(position.direction)
        )
        strategy = resolve_strategy_tag(explicit=getattr(position, "strategy", "") or "")
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
        with self.path.open(encoding="utf-8-sig") as f:
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
            record.strategy = resolve_strategy_tag(
                explicit=record.strategy, reason=reason
            )
        if reason is not None:
            record.reason = str(reason)
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
        strategy = resolve_strategy_tag(
            explicit=getattr(trade, "strategy", "") or (open_rec.strategy if open_rec else ""),
            reason=(open_rec.reason if open_rec else ""),
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
            strategy=strategy,
            reason=open_rec.reason if open_rec else "",
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
            strategy=resolve_strategy_tag(
                explicit=open_rec.strategy if open_rec else "",
                reason=open_rec.reason if open_rec else "",
            ),
            reason=open_rec.reason if open_rec else "",
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
        broker_tickets = {position.ticket for position in positions}
        as_of = now or datetime.now(tz=UTC)
        for ticket in list(self.open_trades):
            if ticket in broker_tickets:
                continue
            open_rec = self.open_trades.get(ticket)
            opened_at = _parse_iso(open_rec.open_time if open_rec else "")
            if opened_at is not None and ghost_grace_seconds > 0:
                age = (as_of - opened_at).total_seconds()
                if age < ghost_grace_seconds:
                    logger.debug(
                        "Journal: keeping recent open ticket={} age={:.1f}s < grace={:.0f}s",
                        ticket,
                        age,
                        ghost_grace_seconds,
                    )
                    continue
            self.open_trades.pop(ticket, None)
            changed = True
            logger.info("Journal: dropping ghost open ticket={} (not on broker)", ticket)
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
