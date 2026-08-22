from __future__ import annotations

from datetime import UTC, datetime

from chronoscalp.execution.account_mode import (
    AccountMarginMode,
    independent_same_symbol_allowed,
)
from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.orchestration.position_keys import position_key
from chronoscalp.risk.portfolio_heat import allocate_risk_pct
from chronoscalp.strategy.news_skip_reasons import (
    NEWS_SKIP_REASONS,
    NewsSkipReason,
    idle_calendar_skip,
)
from chronoscalp.utils.types import Signal, SignalType, Timeframe


def _symbols() -> dict:
    return {
        "XAUUSD": {
            "pip_size": 0.01,
            "pip_value_per_lot": 1.0,
            "contract_size": 100,
            "typical_spread_pips": 20,
        }
    }


def _signal(strategy: str, *, direction: SignalType = SignalType.BUY) -> Signal:
    sl = 1990.0 if direction == SignalType.BUY else 2010.0
    tp = 2030.0 if direction == SignalType.BUY else 1970.0
    return Signal(
        symbol="XAUUSD",
        signal_type=direction,
        timestamp=datetime(2026, 7, 13, 13, tzinfo=UTC),
        entry_price=2000.0,
        stop_loss=sl,
        take_profit=tp,
        timeframe=Timeframe.M1,
        reason=f"{strategy},test",
        strategy=strategy,
    )


def test_three_strategies_fill_independently_on_paper():
    broker = PaperBroker(symbols_cfg=_symbols(), starting_balance=10_000)
    broker.set_quote("XAUUSD", 1999.9, 2000.1)
    tickets = []
    for name in ("delta", "liquidity_volume", "xau_vwap_pullback"):
        pos = broker.place_order(_signal(name), 0.1)
        tickets.append(pos.ticket)
        assert pos.strategy == name
    assert len(set(tickets)) == 3
    assert len(broker.get_open_positions("XAUUSD")) == 3


def test_hedging_allows_opposing_live_tickets_netting_does_not():
    assert independent_same_symbol_allowed(AccountMarginMode.HEDGING) is True
    assert independent_same_symbol_allowed(AccountMarginMode.NETTING) is False


def test_news_one_leg_fill_cancels_only_twin():
    from chronoscalp.utils.types import PendingOrderSide

    broker = PaperBroker(symbols_cfg=_symbols(), starting_balance=10_000)
    broker.set_quote("XAUUSD", 1999.5, 2000.5)
    delta = broker.place_order(_signal("delta"), 0.1)
    broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.1,
        price=2001.0,
        stop_loss=1999.0,
        take_profit=2005.0,
        comment="CS_News_B",
    )
    broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.SELL_STOP,
        volume=0.1,
        price=1999.0,
        stop_loss=2001.0,
        take_profit=1995.0,
        comment="CS_News_S",
    )
    broker.set_quote("XAUUSD", 1998.0, 2002.0)
    news_positions = [
        p for p in broker.get_open_positions("XAUUSD") if p.strategy == "news_straddle"
    ]
    assert len(news_positions) == 1
    assert any(p.ticket == delta.ticket for p in broker.get_open_positions("XAUUSD"))
    remaining_news = broker.get_pending_orders("XAUUSD", comment_prefix="CS_News")
    assert len(remaining_news) == 1


def test_all_news_skip_reasons_are_closed():
    expected = {
        "disabled",
        "no_calendar_event",
        "stale_calendar",
        "currency_mismatch",
        "title_skip",
        "outside_placement_window",
        "outside_session",
        "spread_block",
        "already_open_same_strategy",
        "portfolio_heat",
        "max_concurrent",
        "broker_unsupported",
        "risk_rejected",
    }
    assert expected == NEWS_SKIP_REASONS
    assert idle_calendar_skip(events_loaded=False, unfiltered_upcoming=False, currency="USD") == (
        NewsSkipReason.STALE_CALENDAR
    )
    assert idle_calendar_skip(events_loaded=True, unfiltered_upcoming=True, currency="USD") == (
        NewsSkipReason.CURRENCY_MISMATCH
    )
    assert idle_calendar_skip(events_loaded=True, unfiltered_upcoming=False, currency="USD") == (
        NewsSkipReason.NO_CALENDAR_EVENT
    )


def test_position_keys_are_per_strategy():
    assert position_key("XAUUSD", "delta") != position_key("XAUUSD", "news_straddle")
    assert position_key("XAUUSD", "delta") == "XAUUSD::delta"


def test_remaining_heat_is_allocated_not_winner_takes_all():
    first = allocate_risk_pct(requested_risk_pct=1.0, open_heat_pct=0.0, max_heat_pct=3.0)
    second = allocate_risk_pct(requested_risk_pct=1.0, open_heat_pct=1.0, max_heat_pct=3.0)
    third = allocate_risk_pct(requested_risk_pct=1.0, open_heat_pct=2.0, max_heat_pct=3.0)
    fourth = allocate_risk_pct(requested_risk_pct=1.0, open_heat_pct=3.0, max_heat_pct=3.0)
    assert first.risk_pct == 1.0
    assert second.risk_pct == 1.0
    assert third.risk_pct == 1.0
    assert fourth.allowed is False
