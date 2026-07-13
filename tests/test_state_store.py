from __future__ import annotations

import json
from pathlib import Path

from chronoscalp.orchestration.state_store import TradingStateStore


def test_state_store_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    store = TradingStateStore(path)
    store.state.open_tickets = {"XAUUSD": 42}
    store.state.processed_signals = ["XAUUSD|M1|2026-01-01T12:00:00|buy"]
    store.save()

    reloaded = TradingStateStore(path)
    reloaded.load()
    assert reloaded.state.open_tickets == {"XAUUSD": 42}
    assert reloaded.state.processed_signals == ["XAUUSD|M1|2026-01-01T12:00:00|buy"]


def test_state_store_reconcile_adopts_broker_positions(tmp_path: Path):
    path = tmp_path / "state.json"
    store = TradingStateStore(path)
    store.state.open_tickets = {"XAUUSD": 999}
    store.load()

    store.reconcile_open_tickets({"EURUSD": 55})
    assert store.state.open_tickets == {"EURUSD": 55}
    assert json.loads(path.read_text(encoding="utf-8"))["open_tickets"]["EURUSD"] == 55
