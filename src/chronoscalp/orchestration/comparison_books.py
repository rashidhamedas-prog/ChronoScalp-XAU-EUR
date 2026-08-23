"""Independent virtual broker/equity books used in comparison mode.

Each strategy sizes and fills against its own starting equity so ranking is
R-normalized rather than dollar-size-biased. Live shared heat is not applied
here — that path uses the real broker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.utils.types import TradeResult


def r_normalized_stats(trades: list[TradeResult]) -> dict:
    """Per-strategy comparison row ranked by R, not dollar PnL."""
    if not trades:
        return {
            "trades": 0,
            "win_rate_pct": 0.0,
            "net_pnl": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "avg_r": 0.0,
            "max_dd_pct": 0.0,
        }
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl < 0]
    r_values = [float(t.r_multiple) for t in trades]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    return {
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 2),
        "net_pnl": round(sum(t.pnl for t in trades), 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else pf,
        "expectancy_r": round(sum(r_values) / len(r_values), 3),
        "avg_r": round(sum(r_values) / len(r_values), 3),
        "max_dd_pct": 0.0,
    }


@dataclass
class StrategyBook:
    """One virtual account for a single strategy id."""

    strategy: str
    broker: PaperBroker
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    trades: list[TradeResult] = field(default_factory=list)

    def mark_equity(self, at: datetime) -> None:
        self.equity_curve.append((at, float(self.broker.get_balance())))

    def record_close(self, trade: TradeResult, at: datetime) -> None:
        self.trades.append(trade)
        self.mark_equity(at)

    def report(self) -> dict:
        stats = r_normalized_stats(self.trades)
        stats["strategy"] = self.strategy
        stats["equity"] = float(self.broker.get_balance())
        if self.equity_curve:
            peak = self.equity_curve[0][1]
            max_dd = 0.0
            for _, eq in self.equity_curve:
                peak = max(peak, eq)
                dd = (peak - eq) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)
            stats["max_dd_pct"] = round(max_dd * 100.0, 3)
        return stats


class ComparisonBooks:
    """Lazy map of strategy id → independent PaperBroker."""

    def __init__(
        self,
        *,
        symbols_cfg: dict,
        starting_balance: float,
        slippage_pips: float,
    ) -> None:
        self.symbols_cfg = symbols_cfg
        self.starting_balance = float(starting_balance)
        self.slippage_pips = float(slippage_pips)
        self._books: dict[str, StrategyBook] = {}
        self._last_quotes: dict[str, tuple[float, float, datetime | None]] = {}

    def for_strategy(self, strategy: str) -> StrategyBook:
        tag = (strategy or "unknown").strip() or "unknown"
        book = self._books.get(tag)
        if book is None:
            broker = PaperBroker(
                symbols_cfg=self.symbols_cfg,
                starting_balance=self.starting_balance,
                slippage_pips=self.slippage_pips,
            )
            for symbol, (bid, ask, at) in self._last_quotes.items():
                broker.set_quote(symbol, bid, ask, at)
            book = StrategyBook(strategy=tag, broker=broker)
            self._books[tag] = book
        return book

    def broker_for(self, strategy: str) -> PaperBroker:
        return self.for_strategy(strategy).broker

    def set_quote(self, symbol: str, bid: float, ask: float, at: datetime | None = None) -> None:
        self._last_quotes[symbol] = (float(bid), float(ask), at)
        for book in self._books.values():
            book.broker.set_quote(symbol, bid, ask, at)

    def reports(self) -> dict[str, dict]:
        """R-normalized per-strategy rows plus a portfolio total keyed ``_portfolio``."""
        rows = {name: book.report() for name, book in sorted(self._books.items())}
        all_trades = [t for book in self._books.values() for t in book.trades]
        total = r_normalized_stats(all_trades)
        total["strategy"] = "_portfolio"
        rows["_portfolio"] = total
        return rows
