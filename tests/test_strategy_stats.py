"""Tests for strategy tag normalization and journal strategy stats."""

from __future__ import annotations

from chronoscalp.orchestration.trade_journal import (
    ClosedTradeRecord,
    OpenTradeRecord,
    compute_strategy_stats,
)
from chronoscalp.utils.strategy_tags import (
    mt5_comment_for_strategy,
    normalize_strategy_tag,
    resolve_strategy_tag,
    strategy_from_reason,
)


def test_strategy_from_reason_common_engines() -> None:
    assert strategy_from_reason("ultra_scalp_v3,trend=bullish,rvol=1.5") == "ultra_scalp"
    assert strategy_from_reason("institutional_entry, trend=bullish, mss") == "institutional"
    assert strategy_from_reason("news_straddle,buy_stop") == "news_straddle"
    assert normalize_strategy_tag("CS_ultra_scalp") == "ultra_scalp"
    assert resolve_strategy_tag(reason="", comment="CS_news_straddle") == "news_straddle"
    assert strategy_from_reason("delta,sweep_reclaim,trend=bullish") == "delta"
    assert normalize_strategy_tag("CS_delta") == "delta"
    assert normalize_strategy_tag("CS_News_B") == "news_straddle"
    assert normalize_strategy_tag("CS_News_S") == "news_straddle"
    assert normalize_strategy_tag("CS_News") == "news_straddle"


def test_mt5_comment_for_strategy_is_short() -> None:
    comment = mt5_comment_for_strategy("ultra_scalp")
    assert comment.startswith("CS_")
    assert len(comment) <= 31


def test_compute_strategy_stats_shares() -> None:
    closed = [
        ClosedTradeRecord(
            ticket=1,
            symbol="EURUSD",
            direction="buy",
            volume=0.1,
            entry_price=1.1,
            exit_price=1.11,
            open_time="2026-07-17T10:00:00+00:00",
            close_time="2026-07-17T11:00:00+00:00",
            pnl=100.0,
            strategy="ultra_scalp",
        ),
        ClosedTradeRecord(
            ticket=2,
            symbol="XAUUSD",
            direction="sell",
            volume=0.1,
            entry_price=2400.0,
            exit_price=2410.0,
            open_time="2026-07-17T12:00:00+00:00",
            close_time="2026-07-17T13:00:00+00:00",
            pnl=-40.0,
            strategy="institutional",
        ),
        ClosedTradeRecord(
            ticket=3,
            symbol="EURUSD",
            direction="buy",
            volume=0.1,
            entry_price=1.1,
            exit_price=1.12,
            open_time="2026-07-17T14:00:00+00:00",
            close_time="2026-07-17T15:00:00+00:00",
            pnl=50.0,
            strategy="ultra_scalp",
        ),
    ]
    open_trades = [
        OpenTradeRecord(
            ticket=9,
            symbol="USDJPY",
            direction="buy",
            volume=0.2,
            entry_price=150.0,
            stop_loss=149.5,
            take_profit=151.0,
            open_time="2026-07-17T16:00:00+00:00",
            strategy="news_straddle",
        )
    ]
    rows = compute_strategy_stats(closed, open_trades, reference_equity=10_000)
    by = {r.strategy: r for r in rows}
    assert by["ultra_scalp"].trades == 2
    assert by["ultra_scalp"].net_pnl == 150.0
    assert by["ultra_scalp"].profit_share_pct == 100.0
    assert by["institutional"].loss_share_pct == 100.0
    assert by["news_straddle"].open_trades == 1
    assert by["ultra_scalp"].pnl_pct_of_equity == 1.5
