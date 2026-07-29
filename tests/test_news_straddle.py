"""Tests for Dynamic ATR news straddle + calendar countdown."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.filters.news_calendar import (
    NewsCalendarManager,
    event_matches_straddle_titles,
)
from chronoscalp.filters.news_filter import NewsEvent, NewsFilter
from chronoscalp.risk.position_sizing import RiskManager
from chronoscalp.strategy.multi_timeframe import resolve_enabled_strategies
from chronoscalp.strategy.news_straddle_engine import (
    COMMENT_PREFIX,
    DynamicNewsStraddleEngine,
    StraddlePhase,
)
from chronoscalp.utils.types import PendingOrderSide


def _symbols_cfg() -> dict:
    return {
        "XAUUSD": {
            "pip_size": 0.01,
            "pip_value_per_lot": 1.0,
            "contract_size": 100,
            "typical_spread_pips": 1.5,
            "min_lot": 0.01,
            "lot_step": 0.01,
            "max_lot": 10.0,
        }
    }


def _m1_df(n: int = 40, mid: float = 2000.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        o = mid + (i % 5) * 0.1
        rows.append(
            {
                "open": o,
                "high": o + 0.8,
                "low": o - 0.8,
                "close": o + 0.2,
                "tick_volume": 100 + i,
            }
        )
    return pd.DataFrame(rows)


def _engine(events: list[NewsEvent], **cfg) -> DynamicNewsStraddleEngine:
    news = NewsFilter(
        events=events,
        blackout_before=timedelta(minutes=30),
        blackout_after=timedelta(minutes=30),
        high_impact_only=True,
        enabled=True,
    )
    calendar = NewsCalendarManager.from_news_filter(news)
    risk = RiskManager(
        risk_cfg={
            "max_risk_per_trade_pct": 1.0,
            "active_risk_per_trade_pct": 1.0,
            "min_reward_risk_ratio": 1.5,
        },
        spread_cfg={"max_spread_pips": {"XAUUSD": 50.0}},
        symbols_cfg=_symbols_cfg(),
        starting_equity=10_000.0,
    )
    defaults = {
        "atr_period": 14,
        "atr_multiplier": 2.0,
        "max_spread_pips": 5.0,
        "pause_minutes_before": 2.0,
        "place_seconds_before": 30.0,
        "expiry_seconds": 120.0,
        "sl_distance_fraction": 0.8,
        "tp_distance_fraction": 1.8,
        "title_tokens": [],  # accept any high-impact
    }
    defaults.update(cfg)
    return DynamicNewsStraddleEngine(calendar=calendar, risk_manager=risk, cfg=defaults)


def test_resolve_enabled_strategies_includes_news_straddle():
    smc, liq, scalp, news = resolve_enabled_strategies(
        {"enabled_strategies": ["ultra_scalp", "news_straddle"]}
    )
    assert not smc and not liq and scalp and news
    *_, news2 = resolve_enabled_strategies({"use_news_straddle": True, "use_ultra_scalp": False})
    assert news2 is True


def test_spread_shield_blocks_wide_spread():
    assert NewsCalendarManager.is_spread_acceptable(1.5, 2.0) is True
    assert NewsCalendarManager.is_spread_acceptable(2.5, 2.0) is False


def test_event_title_tokens():
    event = NewsEvent(
        timestamp=datetime(2026, 7, 29, 12, 30, tzinfo=UTC),
        currency="USD",
        impact="high",
        title="US Non-Farm Payrolls",
    )
    assert event_matches_straddle_titles(event) is True
    assert event_matches_straddle_titles(event, frozenset({"cpi"})) is False


def test_calendar_upcoming_and_placement_window():
    release = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)
    events = [
        NewsEvent(timestamp=release, currency="USD", impact="high", title="NFP"),
    ]
    news = NewsFilter(
        events=events,
        blackout_before=timedelta(minutes=30),
        blackout_after=timedelta(minutes=30),
    )
    cal = NewsCalendarManager.from_news_filter(news)
    t_pause = release - timedelta(minutes=1, seconds=30)
    ok, upcoming = cal.is_news_event_upcoming(window_minutes=2, moment=t_pause, currency="USD")
    assert ok and upcoming is not None
    place_ok, _ = cal.is_straddle_placement_window(t_pause, place_seconds_before=30, currency="USD")
    assert place_ok is False  # 90s before — outside 30s place window
    t_place = release - timedelta(seconds=20)
    place_ok2, _ = cal.is_straddle_placement_window(t_place, place_seconds_before=30, currency="USD")
    assert place_ok2 is True


def test_place_straddle_and_oco_on_paper():
    release = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)
    events = [NewsEvent(timestamp=release, currency="USD", impact="high", title="CPI")]
    engine = _engine(events)
    broker = PaperBroker(_symbols_cfg(), starting_balance=10_000.0)
    mid = 2000.0
    broker.set_quote("XAUUSD", mid - 0.1, mid + 0.1)

    moment = release - timedelta(seconds=15)
    result = engine.tick(
        broker,
        symbol="XAUUSD",
        moment=moment,
        m1_df=_m1_df(mid=mid),
        spread_pips=1.5,
        currency="USD",
        already_open=False,
    )
    assert result.action == "placed"
    assert result.phase == StraddlePhase.PENDING
    pending = broker.get_pending_orders("XAUUSD", comment_prefix=COMMENT_PREFIX)
    assert len(pending) == 2
    sides = {o.side for o in pending}
    assert sides == {PendingOrderSide.BUY_STOP, PendingOrderSide.SELL_STOP}

    # Spike through buy stop → OCO cancels sell stop.
    buy = next(o for o in pending if o.side == PendingOrderSide.BUY_STOP)
    broker.set_quote("XAUUSD", buy.price + 1.0, buy.price + 1.2)
    oco = engine.manage_oco_and_trailing(broker, "XAUUSD")
    assert oco.action in ("oco_filled", "filled")
    assert oco.opened_position is not None
    assert oco.opened_position.direction.value == "buy"
    assert broker.get_pending_orders("XAUUSD", comment_prefix=COMMENT_PREFIX) == []


def test_spread_block_skips_placement():
    release = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)
    engine = _engine(
        [NewsEvent(timestamp=release, currency="USD", impact="high", title="FOMC")],
        max_spread_pips=1.0,
    )
    broker = PaperBroker(_symbols_cfg())
    broker.set_quote("XAUUSD", 2000.0, 2000.2)
    result = engine.tick(
        broker,
        symbol="XAUUSD",
        moment=release - timedelta(seconds=10),
        m1_df=_m1_df(),
        spread_pips=3.0,
        currency="USD",
        already_open=False,
    )
    assert result.action == "spread_block"
    assert broker.get_pending_orders() == []


def test_expiry_cancels_pendings():
    release = datetime(2026, 7, 29, 12, 30, tzinfo=UTC)
    engine = _engine(
        [NewsEvent(timestamp=release, currency="USD", impact="high", title="Rate Decision")],
        expiry_seconds=5,
    )
    broker = PaperBroker(_symbols_cfg())
    broker.set_quote("XAUUSD", 1999.9, 2000.1)
    placed = engine.tick(
        broker,
        symbol="XAUUSD",
        moment=release - timedelta(seconds=10),
        m1_df=_m1_df(),
        spread_pips=1.0,
        currency="USD",
        already_open=False,
    )
    assert placed.action == "placed"
    expired = engine.tick(
        broker,
        symbol="XAUUSD",
        moment=release + timedelta(seconds=10),
        m1_df=_m1_df(),
        spread_pips=1.0,
        currency="USD",
        already_open=False,
    )
    assert expired.action == "expired"
    assert broker.get_pending_orders("XAUUSD", comment_prefix=COMMENT_PREFIX) == []


def test_bracket_rr_meets_floor():
    engine = _engine([])
    from chronoscalp.utils.types import Quote

    quote = Quote(symbol="XAUUSD", bid=2000.0, ask=2000.2)
    buy, sell = engine.build_bracket_signals(
        symbol="XAUUSD",
        quote=quote,
        distance=2.0,
        moment=datetime.now(tz=UTC),
    )
    assert buy.risk_reward_ratio == pytest.approx(2.25)
    assert sell.risk_reward_ratio == pytest.approx(2.25)
