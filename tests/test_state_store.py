from __future__ import annotations

import json
from pathlib import Path

from chronoscalp.orchestration.state_store import TradingStateStore


def test_state_store_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    store = TradingStateStore(path)
    store.state.open_tickets = {"XAUUSD::delta": 42}
    store.state.processed_signals = ["XAUUSD|M1|2026-01-01T12:00:00|buy"]
    store.save()

    reloaded = TradingStateStore(path)
    reloaded.load()
    assert reloaded.state.open_tickets == {"XAUUSD::delta": 42}
    assert reloaded.state.processed_signals == ["XAUUSD|M1|2026-01-01T12:00:00|buy"]


def test_state_store_upgrades_legacy_symbol_keys(tmp_path: Path):
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"open_tickets": {"XAUUSD": 42}}), encoding="utf-8")
    store = TradingStateStore(path)
    store.load()
    assert store.state.open_tickets == {"XAUUSD::unknown": 42}


def test_state_store_reconcile_adopts_broker_positions(tmp_path: Path):
    path = tmp_path / "state.json"
    store = TradingStateStore(path)
    store.state.open_tickets = {"XAUUSD::unknown": 999}
    store.load()

    store.reconcile_open_tickets({"EURUSD::liquidity_volume": 55})
    assert store.state.open_tickets == {"EURUSD::liquidity_volume": 55}
    assert (
        json.loads(path.read_text(encoding="utf-8"))["open_tickets"]["EURUSD::liquidity_volume"]
        == 55
    )


def test_state_store_reconcile_keeps_two_tickets_on_one_symbol(tmp_path: Path):
    path = tmp_path / "multi.json"
    store = TradingStateStore(path)
    store.reconcile_open_tickets(
        {"XAUUSD::delta": 11, "XAUUSD::news_straddle": 22},
        ticket_strategies={11: "delta", 22: "news_straddle"},
    )
    assert store.state.open_tickets == {"XAUUSD::delta": 11, "XAUUSD::news_straddle": 22}


def test_state_store_loads_utf8_bom(tmp_path: Path):
    path = tmp_path / "state_bom.json"
    payload = {
        "open_tickets": {"BTCUSD": 7},
        "processed_signals": [],
        "last_evaluated_bars": {},
        "updated_at": "2026-07-25T00:00:00",
    }
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))
    store = TradingStateStore(path)
    store.load()
    assert store.state.open_tickets == {"BTCUSD::unknown": 7}


def test_state_store_persists_position_meta(tmp_path: Path):
    path = tmp_path / "state_meta.json"
    store = TradingStateStore(path)
    store.state.open_tickets = {"XAUUSD::delta": 42}
    store.state.position_meta = {
        "42": {
            "initial_volume": 0.1,
            "initial_stop_loss": 1990.0,
            "partial_taken": True,
            "breakeven_moved": False,
        }
    }
    store.save()

    reloaded = TradingStateStore(path)
    reloaded.load()
    assert reloaded.state.position_meta["42"]["initial_stop_loss"] == 1990.0
    assert reloaded.state.position_meta["42"]["partial_taken"] is True
