"""Integration tests that go through TradingBot.tick — not PaperBroker alone."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from chronoscalp.config import Settings
from chronoscalp.execution.account_mode import AccountMarginMode
from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.main import TradingBot
from chronoscalp.risk.portfolio_heat import allocate_batch_risk_pct, reconstruct_dollar_risk
from chronoscalp.utils.types import Signal, SignalType, Timeframe


def _frames(n: int = 80) -> dict[Timeframe, pd.DataFrame]:
    idx = pd.date_range("2026-07-13 13:00", periods=n, freq="min", tz="UTC")
    close = np.linspace(2000.0, 2010.0, n)
    df = pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 0.8,
            "low": close - 0.8,
            "close": close,
            "tick_volume": np.full(n, 100),
        },
        index=idx,
    )
    return {
        Timeframe.M1: df,
        Timeframe.M3: df.iloc[::3].copy(),
        Timeframe.M5: df.iloc[::5].copy(),
        Timeframe.M10: df.iloc[::10].copy(),
        Timeframe.M15: df.iloc[::15].copy(),
    }


class FakeConnector:
    is_connected = True

    def __init__(self, frames: dict[Timeframe, pd.DataFrame]) -> None:
        self.frames = frames

    def connect(self) -> bool:
        return True

    def shutdown(self) -> None:
        return None

    def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, count: int = 300) -> pd.DataFrame:
        df = self.frames.get(timeframe)
        if df is None or df.empty:
            return pd.DataFrame()
        return df.tail(count).copy()


def _signal(strategy: str, *, sl: float = 1990.0, tp: float = 2020.0) -> Signal:
    return Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime(2026, 7, 13, 13, tzinfo=UTC),
        entry_price=2000.0,
        stop_loss=sl,
        take_profit=tp,
        timeframe=Timeframe.M1,
        reason=f"{strategy},test",
        strategy=strategy,
    )


def _make_bot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "paper",
    multi_strategy_mode: str = "live",
    max_concurrent: int = 8,
    heat_pct: float = 3.0,
    strategies: list[str] | None = None,
    confirm_live: bool = False,
    broker: PaperBroker | None = None,
) -> TradingBot:
    frames = _frames()
    settings = Settings()
    settings.raw["execution"]["broker"] = "paper"
    settings.raw["execution"]["state_dir"] = str(tmp_path)
    settings.raw["execution"]["multi_strategy_mode"] = multi_strategy_mode
    settings.raw["sessions"]["trading_hours_mode"] = "always_on_24h"
    settings.raw["sessions"]["trade_outside_sessions"] = True
    settings.raw["risk"]["three_strikes"] = {"enabled": False}
    settings.raw["risk"]["spread_ma_guard"] = {"enabled": False}
    settings.raw["risk"]["volatility_guard"] = {"enabled": False}
    settings.raw["risk"]["correlation"] = {"enabled": False}
    settings.raw["risk"]["max_concurrent_positions"] = max_concurrent
    settings.raw["risk"]["max_portfolio_heat_pct"] = heat_pct
    settings.raw["risk"]["max_daily_loss_pct"] = max(heat_pct, 3.0)
    settings.raw["risk"]["max_risk_per_trade_pct"] = 1.0
    settings.raw["risk"]["active_risk_per_trade_pct"] = 1.0
    settings.raw["risk"]["independent_symbol_entries"] = True
    settings.raw["news_filter"]["enabled"] = False
    settings.raw["symbols"] = ["XAUUSD"]
    settings.raw["broker_symbol_aliases"] = {}
    settings.raw["strategy"]["derive_strategies_from_symbols"] = False
    settings.raw["strategy"].pop("symbol_catalogs", None)
    settings.raw["strategy"]["enabled_strategies"] = strategies or ["delta", "liquidity_volume"]
    settings.raw["strategy"]["use_news_straddle"] = "news_straddle" in (
        strategies or ["delta", "liquidity_volume"]
    )
    settings.raw["strategy"]["use_xau_vwap_pullback"] = "xau_vwap_pullback" in (strategies or [])
    xau = dict(settings.raw.get("strategy", {}).get("xau_vwap_pullback") or {})
    if "xau_vwap_pullback" in (strategies or []):
        xau["enabled"] = True
        xau["shadow_only"] = False
        xau["live_ready"] = False
        settings.raw["strategy"]["xau_vwap_pullback"] = xau
    if confirm_live:
        settings.secrets.chronoscalp_confirm_live = "yes"

    connector = FakeConnector(frames)
    if broker is None:
        broker = PaperBroker(
            symbols_cfg=settings.symbols_raw,
            starting_balance=10_000.0,
            slippage_pips=0.0,
        )
        broker.set_quote("XAUUSD", 1999.5, 2000.5)

    monkeypatch.setattr("chronoscalp.main.create_data_connector", lambda _s: connector)
    monkeypatch.setattr(
        "chronoscalp.main.create_broker", lambda _s, mode, connector: broker  # noqa: ARG005
    )

    bot = TradingBot(settings, mode=mode)
    bot.trade_on_bar_close = False
    bot._reconcile_interval = 0
    bot.connector.is_connected = True
    return bot


def test_allocate_batch_is_order_independent():
    alloc = allocate_batch_risk_pct(
        n=3, requested_risk_pct=1.0, open_heat_pct=0.0, max_heat_pct=2.0
    )
    assert alloc.allowed is True
    assert alloc.risk_pct == pytest.approx(2.0 / 3.0)


def test_reconstruct_dollar_risk_from_geometry():
    dollars = reconstruct_dollar_risk(
        entry=2000.0, stop=1990.0, volume=0.1, pip_size=0.01, pip_value=1.0
    )
    assert dollars == pytest.approx(100.0)
    assert (
        reconstruct_dollar_risk(entry=2000, stop=None, volume=0.1, pip_size=0.01, pip_value=1.0)
        is None
    )


def test_tick_splits_heat_fairly_across_simultaneous_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(tmp_path, monkeypatch, heat_pct=2.0, multi_strategy_mode="live")
    signals = [
        _signal("delta"),
        _signal("liquidity_volume"),
        _signal("smc_confluence"),
    ]

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return list(signals)
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    positions = bot.broker.get_open_positions("XAUUSD")
    assert len(positions) == 3
    volumes = sorted(p.volume for p in positions)
    assert volumes[0] == pytest.approx(volumes[1], abs=0.02)
    assert volumes[1] == pytest.approx(volumes[2], abs=0.02)
    assert all(v < 0.1 for v in volumes)


def test_tick_rechecks_max_concurrent_after_each_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(tmp_path, monkeypatch, max_concurrent=1, multi_strategy_mode="live")

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta"), _signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    assert len(bot.broker.get_open_positions("XAUUSD")) == 1
    assert bot._at_capacity()


def test_tick_places_vwap_stop_not_market(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["xau_vwap_pullback"],
        multi_strategy_mode="comparison",
    )
    bot.settings.raw["strategy"]["xau_vwap_pullback"] = {
        "enabled": True,
        "shadow_only": False,
        "live_ready": False,
    }
    stop = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime(2026, 7, 13, 13, tzinfo=UTC),
        entry_price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        timeframe=Timeframe.M1,
        reason="xau_vwap_pullback,pullback_rejection",
        strategy="xau_vwap_pullback",
        order_kind="stop",
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [stop]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    exec_broker = bot._broker_for("xau_vwap_pullback")
    pending = exec_broker.get_pending_orders("XAUUSD")
    assert pending, f"VWAP must rest as a stop pending; skips={bot._skip_counts}"
    assert pending[0].price == pytest.approx(2020.0)
    assert exec_broker.get_open_positions("XAUUSD") == []
    exec_broker.set_quote("XAUUSD", 2019.0, 2020.5)
    bot._harvest_pending_fills("XAUUSD", datetime.now(tz=UTC))
    assert exec_broker.get_open_positions("XAUUSD")


def test_tick_cancels_vwap_stop_after_engine_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["xau_vwap_pullback"],
        multi_strategy_mode="comparison",
    )
    bot.settings.raw["strategy"]["xau_vwap_pullback"] = {
        "enabled": True,
        "shadow_only": False,
        "live_ready": False,
    }
    stop = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime(2026, 7, 13, 13, tzinfo=UTC),
        entry_price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        timeframe=Timeframe.M1,
        reason="xau_vwap_pullback,pullback_rejection",
        strategy="xau_vwap_pullback",
        order_kind="stop",
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [stop]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    exec_broker = bot._broker_for("xau_vwap_pullback")
    assert exec_broker.get_pending_orders("XAUUSD")
    bot.strategy.xau_vwap_engine.reset()
    monkeypatch.setattr(bot.strategy, "evaluate_candidates", lambda **_k: [])
    bot.tick()
    assert exec_broker.get_pending_orders("XAUUSD") == []


def test_tick_live_blocks_xau_when_not_live_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        mode="live",
        confirm_live=True,
        strategies=["xau_vwap_pullback", "delta"],
        multi_strategy_mode="live",
    )
    bot.settings.raw["strategy"]["xau_vwap_pullback"] = {
        "enabled": True,
        "shadow_only": False,
        "live_ready": False,
    }
    xau = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime(2026, 7, 13, 13, tzinfo=UTC),
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2020.0,
        timeframe=Timeframe.M1,
        reason="xau_vwap_pullback,pullback_rejection",
        strategy="xau_vwap_pullback",
        order_kind="stop",
    )
    delta = _signal("delta")

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [xau, delta]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    assert not any(p.strategy == "xau_vwap_pullback" for p in bot.broker.get_open_positions())
    assert not bot.broker.get_pending_orders("XAUUSD", comment_prefix="CS_xau")
    assert any(p.strategy == "delta" for p in bot.broker.get_open_positions())


def test_tick_incomplete_heat_metadata_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(tmp_path, monkeypatch, multi_strategy_mode="live")
    pos = bot.broker.place_order(_signal("delta"), 0.1)
    bot._register_open("XAUUSD", "delta", pos.ticket)
    bot._position_meta[pos.ticket] = {"strategy": "delta"}  # no geometry, broker still has it

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    # Reconstructed from the live paper position → new entry allowed, OR fail-closed.
    # Either reconstruction succeeds (preferred) or liquidity is blocked. Never silent 0-heat.
    open_heat = bot._committed_heat_pct(10_000)
    assert open_heat > 0 or bot._heat_unknown


def test_tick_ghost_ticket_without_geometry_blocks_new_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(tmp_path, monkeypatch, multi_strategy_mode="live")
    pos = bot.broker.place_order(_signal("delta"), 0.1)
    pos.stop_loss = 0.0
    pos.initial_stop_loss = None
    bot._register_open("XAUUSD", "delta", pos.ticket)
    bot._position_meta[pos.ticket] = {"strategy": "delta"}
    monkeypatch.setattr(bot, "_manage_open_position", lambda *_a, **_k: None)

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    assert bot._heat_unknown
    assert not any(p.strategy == "liquidity_volume" for p in bot.broker.get_open_positions())


def test_tick_netting_blocks_second_symbol_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(tmp_path, monkeypatch, multi_strategy_mode="live")
    bot._account_mode = AccountMarginMode.NETTING
    pos = bot.broker.place_order(_signal("delta"), 0.1)
    bot._register_open("XAUUSD", "delta", pos.ticket)
    bot._position_meta[pos.ticket] = {
        "initial_volume": pos.volume,
        "initial_stop_loss": pos.stop_loss,
        "entry_price": pos.entry_price,
        "dollar_risk": 100.0,
        "strategy": "delta",
    }

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    assert len(bot.broker.get_open_positions("XAUUSD")) == 1


def test_tick_news_pending_reserves_heat_before_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.strategy.news_straddle_engine import (
        StraddlePhase,
        StraddleSession,
        StraddleTickResult,
    )
    from chronoscalp.utils.types import PendingOrderSide

    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["news_straddle", "delta"],
        multi_strategy_mode="live",
        heat_pct=3.0,
    )
    bot.use_news_straddle = True
    session = StraddleSession(
        symbol="XAUUSD",
        event_title="NFP",
        event_time=datetime.now(tz=UTC),
        phase=StraddlePhase.PENDING,
        buy_ticket=11,
        sell_ticket=12,
        dollar_risk=100.0,
        volume=0.10,
    )

    def _news_tick(*_a, **kwargs):
        if not kwargs.get("allow_place"):
            return StraddleTickResult(
                symbol="XAUUSD",
                phase=StraddlePhase.IDLE,
                action="blocked",
                session=None,
            )
        bot.broker.place_pending_stop(
            symbol="XAUUSD",
            side=PendingOrderSide.BUY_STOP,
            volume=0.10,
            price=2020.0,
            stop_loss=1990.0,
            take_profit=2080.0,
            comment="CS_News_B",
            strategy="news_straddle",
        )
        return StraddleTickResult(
            symbol="XAUUSD",
            phase=StraddlePhase.PENDING,
            action="placed",
            session=session,
        )

    monkeypatch.setattr(bot.news_straddle, "tick", _news_tick)
    monkeypatch.setattr(bot.news_straddle, "is_scalp_paused", lambda *_a, **_k: True)
    monkeypatch.setattr(bot.strategy, "evaluate_candidates", lambda **_k: [_signal("delta")])
    bot.tick()
    reserved = bot._heat_reservations.get(bot._open_key("XAUUSD", "news_straddle"))
    assert reserved is not None
    assert reserved["dollar_risk"] == pytest.approx(100.0)
    heat = bot._committed_heat_pct(10_000)
    assert heat >= 1.0
    assert bot.broker.get_pending_orders("XAUUSD")


def test_tick_news_reservation_keeps_total_heat_at_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.strategy.news_straddle_engine import (
        StraddlePhase,
        StraddleSession,
        StraddleTickResult,
    )
    from chronoscalp.utils.types import PendingOrderSide

    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["news_straddle", "delta"],
        multi_strategy_mode="live",
        heat_pct=3.0,
    )
    bot.use_news_straddle = True
    monkeypatch.setattr(bot, "_manage_open_position", lambda *_a, **_k: None)
    occupied = bot.broker.place_order(_signal("liquidity_volume"), 0.1)
    bot._register_open("XAUUSD", "liquidity_volume", occupied.ticket)
    bot._position_meta[occupied.ticket] = {
        "initial_volume": occupied.volume,
        "initial_stop_loss": occupied.stop_loss,
        "entry_price": occupied.entry_price,
        "dollar_risk": 200.0,
        "strategy": "liquidity_volume",
    }
    assert bot.max_concurrent >= 8
    assert bot._committed_heat_pct(10_000) == pytest.approx(2.0)
    assert bot._at_capacity() is False
    assert bot._same_symbol_netting_blocked("XAUUSD", "news_straddle") is False

    session = StraddleSession(
        symbol="XAUUSD",
        event_title="NFP",
        event_time=datetime.now(tz=UTC),
        phase=StraddlePhase.PENDING,
        buy_ticket=11,
        sell_ticket=12,
        dollar_risk=100.0,
        volume=0.10,
    )

    captured: dict[str, object] = {}

    def _news_tick(*_a, **kwargs):
        captured.update(kwargs)
        if kwargs.get("allow_place"):
            bot.broker.place_pending_stop(
                symbol="XAUUSD",
                side=PendingOrderSide.BUY_STOP,
                volume=0.10,
                price=2020.0,
                stop_loss=1990.0,
                take_profit=2080.0,
                comment="CS_News_B",
                strategy="news_straddle",
            )
            return StraddleTickResult(
                symbol="XAUUSD",
                phase=StraddlePhase.PENDING,
                action="placed",
                session=session,
            )
        return StraddleTickResult(
            symbol="XAUUSD",
            phase=StraddlePhase.IDLE,
            action="blocked",
            session=None,
        )

    monkeypatch.setattr(bot.news_straddle, "tick", _news_tick)
    monkeypatch.setattr(bot.news_straddle, "is_scalp_paused", lambda *_a, **_k: True)
    monkeypatch.setattr(bot.strategy, "evaluate_candidates", lambda **_k: [_signal("delta")])
    bot.tick()
    assert captured.get("allow_place") is True, captured
    heat = bot._committed_heat_pct(10_000)
    assert heat <= 3.0 + 1e-9
    assert bot._heat_reservations.get(bot._open_key("XAUUSD", "news_straddle")) is not None
    # Remaining 1% is split fairly; delta may open at the batch share, never above the cap.


def test_tick_comparison_uses_independent_brokers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta", "liquidity_volume"],
        multi_strategy_mode="comparison",
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta"), _signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    delta_broker = bot._broker_for("delta")
    liq_broker = bot._broker_for("liquidity_volume")
    assert delta_broker is not liq_broker
    assert delta_broker is not bot.broker
    assert delta_broker.get_open_positions("XAUUSD")
    assert liq_broker.get_open_positions("XAUUSD")
    delta_broker.balance = 8_000.0
    assert liq_broker.get_balance() == pytest.approx(10_000.0)
    reports = bot.comparison_books.reports()
    assert "delta" in reports
    assert "liquidity_volume" in reports
    assert "expectancy_r" in reports["delta"]


def test_tick_comparison_keeps_independent_ticket_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta", "liquidity_volume"],
        multi_strategy_mode="comparison",
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta"), _signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    delta_pos = bot._broker_for("delta").get_open_positions("XAUUSD")[0]
    liq_pos = bot._broker_for("liquidity_volume").get_open_positions("XAUUSD")[0]
    assert delta_pos.ticket != liq_pos.ticket
    opens = list(bot.trade_journal.open_trades.values())
    assert {row.strategy for row in opens} == {"delta", "liquidity_volume"}
    assert bot._lookup_meta("XAUUSD", "delta", delta_pos.ticket).get("strategy") == "delta"
    assert bot._lookup_meta("XAUUSD", "liquidity_volume", liq_pos.ticket).get("strategy") == (
        "liquidity_volume"
    )
    bot.tick()
    assert len(bot._broker_for("delta").get_open_positions("XAUUSD")) == 1
    assert len(bot.trade_journal.open_trades) == 2


def test_tick_restores_pending_heat_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    first = _make_bot(tmp_path, monkeypatch, strategies=["delta"], heat_pct=3.0)
    first.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        comment="CS_xau_vwap_pullback",
        strategy="xau_vwap_pullback",
    )
    broker = first.broker
    restarted = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta"],
        heat_pct=3.0,
        broker=broker,
    )
    assert restarted._heat_reservations == {}

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta")]
        return []

    monkeypatch.setattr(restarted.strategy, "evaluate_candidates", _eval)
    restarted.tick()
    reserved = restarted._heat_reservations.get(restarted._open_key("XAUUSD", "xau_vwap_pullback"))
    assert reserved is not None
    assert reserved["dollar_risk"] == pytest.approx(300.0)
    assert restarted._committed_heat_pct(10_000) == pytest.approx(3.0)
    assert not any(p.strategy == "delta" for p in restarted.broker.get_open_positions())


def test_tick_unreadable_pending_heat_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    first = _make_bot(tmp_path, monkeypatch, strategies=["delta"], heat_pct=3.0)
    first.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=0.0,
        take_profit=2080.0,
        comment="CS_xau_vwap_pullback",
        strategy="xau_vwap_pullback",
    )
    restarted = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta"],
        heat_pct=3.0,
        broker=first.broker,
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta")]
        return []

    monkeypatch.setattr(restarted.strategy, "evaluate_candidates", _eval)
    restarted.tick()
    assert restarted._heat_unknown
    assert not any(p.strategy == "delta" for p in restarted.broker.get_open_positions())


def test_tick_pending_list_failure_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    first = _make_bot(tmp_path, monkeypatch, strategies=["delta"], heat_pct=3.0)
    first.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        comment="CS_xau_vwap_pullback",
        strategy="xau_vwap_pullback",
    )
    restarted = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta"],
        heat_pct=3.0,
        broker=first.broker,
    )

    def _boom(*_a, **_k):
        raise RuntimeError("pending list failed")

    monkeypatch.setattr(restarted.broker, "get_pending_orders", _boom)

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta")]
        return []

    monkeypatch.setattr(restarted.strategy, "evaluate_candidates", _eval)
    restarted.tick()
    assert restarted._heat_unknown
    assert restarted._pending_restore_failed
    assert not any(p.strategy == "delta" for p in restarted.broker.get_open_positions())


def test_tick_restores_news_oco_as_max_not_sum(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    first = _make_bot(tmp_path, monkeypatch, strategies=["delta"], heat_pct=3.0)
    first.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        comment="CS_News_B",
        strategy="news_straddle",
    )
    first.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.SELL_STOP,
        volume=0.10,
        price=1980.0,
        stop_loss=2010.0,
        take_profit=1920.0,
        comment="CS_News_S",
        strategy="news_straddle",
    )
    restarted = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta"],
        heat_pct=3.0,
        broker=first.broker,
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta")]
        return []

    monkeypatch.setattr(restarted.strategy, "evaluate_candidates", _eval)
    restarted.tick()
    reserved = restarted._heat_reservations.get(restarted._open_key("XAUUSD", "news_straddle"))
    assert reserved is not None
    assert reserved["dollar_risk"] == pytest.approx(300.0)
    assert len(reserved["tickets"]) == 2
    assert restarted._committed_heat_pct(10_000) == pytest.approx(3.0)
    assert not any(p.strategy == "delta" for p in restarted.broker.get_open_positions())


def test_tick_comparison_reconcile_keeps_virtual_positions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta", "liquidity_volume"],
        multi_strategy_mode="comparison",
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta"), _signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    before = dict(bot.open_tickets)
    assert len(before) == 2
    bot._reconcile_state_with_broker()
    assert bot.open_tickets == before
    bot.tick()
    delta_broker = bot._broker_for("delta")
    liq_broker = bot._broker_for("liquidity_volume")
    assert len(delta_broker.get_open_positions("XAUUSD")) == 1
    assert len(liq_broker.get_open_positions("XAUUSD")) == 1


def test_failed_pending_cancel_keeps_heat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    bot = _make_bot(tmp_path, monkeypatch, strategies=["delta"], heat_pct=3.0)
    order = bot.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        comment="CS_xau_vwap_pullback",
        strategy="xau_vwap_pullback",
    )
    bot._reserve_heat("XAUUSD", "xau_vwap_pullback", 300.0, [order.ticket])
    monkeypatch.setattr(bot.broker, "cancel_pending_order", lambda *_a, **_k: False)
    bot._cancel_strategy_pendings("XAUUSD", "xau_vwap_pullback")
    assert bot.broker.get_pending_orders("XAUUSD")
    assert bot._heat_reservations.get(bot._open_key("XAUUSD", "xau_vwap_pullback")) is not None

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    assert not any(p.strategy == "delta" for p in bot.broker.get_open_positions())


def test_successful_pending_cancel_releases_heat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    bot = _make_bot(tmp_path, monkeypatch, strategies=["delta"], heat_pct=3.0)
    order = bot.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        comment="CS_xau_vwap_pullback",
        strategy="xau_vwap_pullback",
    )
    bot._reserve_heat("XAUUSD", "xau_vwap_pullback", 300.0, [order.ticket])
    bot._cancel_strategy_pendings("XAUUSD", "xau_vwap_pullback")
    assert not bot.broker.get_pending_orders("XAUUSD")
    assert bot._open_key("XAUUSD", "xau_vwap_pullback") not in bot._heat_reservations


def test_tick_pending_fill_between_reconciles_keeps_heat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    bot = _make_bot(tmp_path, monkeypatch, strategies=["delta"], heat_pct=3.0)
    order = bot.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        comment="CS_xau_vwap_pullback",
        strategy="xau_vwap_pullback",
    )
    bot._reserve_heat("XAUUSD", "xau_vwap_pullback", 300.0, [order.ticket])
    heat_before = bot._committed_heat_pct(10_000)
    assert heat_before == pytest.approx(3.0)
    bot.broker.set_quote("XAUUSD", 2020.2, 2020.6)
    assert bot.broker.get_open_positions("XAUUSD")
    assert bot._open_key("XAUUSD", "xau_vwap_pullback") not in bot.open_tickets
    monkeypatch.setattr(bot.strategy, "evaluate_candidates", lambda **_k: [])
    bot.tick()
    heat_after = bot._committed_heat_pct(10_000)
    assert heat_after >= heat_before - 1e-9
    assert (
        bot._open_key("XAUUSD", "xau_vwap_pullback") in bot.open_tickets or bot._heat_reservations
    )


def test_tick_restart_news_oco_cancels_leftover_or_counts_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.utils.types import PendingOrderSide

    first = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["news_straddle"],
        heat_pct=3.0,
    )
    first.use_news_straddle = True
    first.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.BUY_STOP,
        volume=0.10,
        price=2020.0,
        stop_loss=1990.0,
        take_profit=2080.0,
        comment="CS_News_B",
        strategy="news_straddle",
    )
    first.broker.place_pending_stop(
        symbol="XAUUSD",
        side=PendingOrderSide.SELL_STOP,
        volume=0.10,
        price=1980.0,
        stop_loss=2010.0,
        take_profit=1920.0,
        comment="CS_News_S",
        strategy="news_straddle",
    )
    first.broker.set_quote("XAUUSD", 2020.2, 2020.6)
    assert first.broker.get_open_positions("XAUUSD")
    leftover_before = first.broker.get_pending_orders("XAUUSD")
    assert leftover_before
    broker = first.broker
    restarted = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["news_straddle"],
        heat_pct=3.0,
        broker=broker,
    )
    restarted.use_news_straddle = True
    monkeypatch.setattr(restarted.strategy, "evaluate_candidates", lambda **_k: [])
    restarted.tick()
    leftover = restarted.broker.get_pending_orders("XAUUSD")
    positions = restarted.broker.get_open_positions("XAUUSD")
    assert positions
    if leftover:
        heat = restarted._committed_heat_pct(10_000)
        assert heat >= 2.0 - 1e-9
    else:
        assert not leftover
    session = restarted.news_straddle.sessions.get("XAUUSD")
    assert session is not None


def test_tick_comparison_limits_are_per_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta", "liquidity_volume"],
        multi_strategy_mode="comparison",
        max_concurrent=1,
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta"), _signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    assert bot._broker_for("delta").get_open_positions("XAUUSD")
    assert bot._broker_for("liquidity_volume").get_open_positions("XAUUSD")

    bot.three_strikes_enabled = True
    now = datetime.now(tz=UTC)
    for _ in range(3):
        bot.three_strikes.record_result("XAUUSD", -10.0, at=now, strategy="delta")
    assert bot.three_strikes.is_paused("XAUUSD", at=now, strategy="delta")
    assert not bot.three_strikes.is_paused("XAUUSD", at=now, strategy="liquidity_volume")


def test_tick_comparison_daily_dd_is_per_book(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["delta", "liquidity_volume"],
        multi_strategy_mode="comparison",
    )
    bot.comparison_books.for_strategy("delta")
    bot.comparison_books.for_strategy("liquidity_volume")
    monkeypatch.setattr(
        bot,
        "_book_realized_today",
        lambda strategy, _now: -400.0 if strategy == "delta" else 0.0,
    )

    def _eval(**kwargs):
        if kwargs.get("run_institutional"):
            return [_signal("delta"), _signal("liquidity_volume")]
        return []

    monkeypatch.setattr(bot.strategy, "evaluate_candidates", _eval)
    bot.tick()
    assert not bot._broker_for("delta").get_open_positions("XAUUSD")
    assert bot._broker_for("liquidity_volume").get_open_positions("XAUUSD")
    assert "delta" in bot._book_dd_blocked


def test_tick_news_and_delta_share_batch_when_heat_tight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from chronoscalp.strategy.news_straddle_engine import (
        StraddlePhase,
        StraddleSession,
        StraddleTickResult,
    )
    from chronoscalp.utils.types import PendingOrderSide

    bot = _make_bot(
        tmp_path,
        monkeypatch,
        strategies=["news_straddle", "delta"],
        multi_strategy_mode="live",
        heat_pct=3.0,
    )
    bot.use_news_straddle = True
    monkeypatch.setattr(bot, "_manage_open_position", lambda *_a, **_k: None)
    occupied = bot.broker.place_order(_signal("liquidity_volume"), 0.1)
    bot._register_open("XAUUSD", "liquidity_volume", occupied.ticket)
    bot._position_meta[occupied.ticket] = {
        "initial_volume": occupied.volume,
        "initial_stop_loss": occupied.stop_loss,
        "entry_price": occupied.entry_price,
        "dollar_risk": 150.0,
        "strategy": "liquidity_volume",
    }
    session = StraddleSession(
        symbol="XAUUSD",
        event_title="NFP",
        event_time=datetime.now(tz=UTC),
        phase=StraddlePhase.PENDING,
        buy_ticket=21,
        sell_ticket=22,
        dollar_risk=0.0,
        volume=0.05,
    )
    captured: list[bool] = []
    placed_risk_pct: list[float] = []
    batch_ns: list[int] = []
    import chronoscalp.main as main_mod

    real_alloc = main_mod.allocate_batch_risk_pct

    def _alloc_spy(**kwargs):
        batch_ns.append(int(kwargs["n"]))
        return real_alloc(**kwargs)

    monkeypatch.setattr(main_mod, "allocate_batch_risk_pct", _alloc_spy)

    def _news_tick(*_a, **kwargs):
        captured.append(bool(kwargs.get("allow_place")))
        if kwargs.get("allow_place"):
            risk_pct = float(kwargs.get("risk_pct") or 0.0)
            placed_risk_pct.append(risk_pct)
            session.dollar_risk = 10_000.0 * risk_pct / 100.0
            bot.broker.place_pending_stop(
                symbol="XAUUSD",
                side=PendingOrderSide.BUY_STOP,
                volume=0.05,
                price=2020.0,
                stop_loss=1990.0,
                take_profit=2080.0,
                comment="CS_News_B",
                strategy="news_straddle",
            )
            return StraddleTickResult(
                symbol="XAUUSD",
                phase=StraddlePhase.PENDING,
                action="placed",
                session=session,
            )
        return StraddleTickResult(
            symbol="XAUUSD",
            phase=StraddlePhase.IDLE,
            action="blocked",
            session=None,
        )

    monkeypatch.setattr(bot.news_straddle, "tick", _news_tick)
    monkeypatch.setattr(bot.news_straddle, "is_scalp_paused", lambda *_a, **_k: True)
    monkeypatch.setattr(bot.strategy, "evaluate_candidates", lambda **_k: [_signal("delta")])
    bot.tick()
    assert True in captured
    assert False in captured
    assert batch_ns == [2]
    assert placed_risk_pct
    assert placed_risk_pct[-1] == pytest.approx(0.75, abs=1e-9)
    heat = bot._committed_heat_pct(10_000)
    assert heat <= 3.0 + 1e-9
    assert bot._heat_reservations.get(bot._open_key("XAUUSD", "news_straddle")) is not None
    news_risk = float(
        bot._heat_reservations[bot._open_key("XAUUSD", "news_straddle")]["dollar_risk"]
    )
    assert news_risk == pytest.approx(75.0, abs=1e-6)
