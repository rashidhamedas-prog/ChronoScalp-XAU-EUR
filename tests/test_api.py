from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from chronoscalp.orchestration.trade_journal import ClosedTradeRecord, TradeJournal
from chronoscalp.saas.api import create_app


def test_health_endpoint_open():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_status_requires_token_in_non_dev(monkeypatch):
    monkeypatch.setenv("CHRONOSCALP_ENV", "production")
    monkeypatch.setenv("CHRONOSCALP_API_TOKEN", "secret-token")
    client = TestClient(create_app())
    assert client.get("/status").status_code == 401
    ok = client.get("/status", headers={"Authorization": "Bearer secret-token"})
    assert ok.status_code == 200
    body = ok.json()
    assert "running" in body
    assert "symbols" in body
    assert "strategy_stats" in body
    assert "kill_switch" in body


def test_journal_and_strategy_stats_endpoints(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHRONOSCALP_ENV", "development")
    monkeypatch.delenv("CHRONOSCALP_API_TOKEN", raising=False)

    state = tmp_path / "state"
    state.mkdir()
    journal = TradeJournal(state / "trade_journal_paper.json", mode="paper")
    journal.closed_trades.append(
        ClosedTradeRecord(
            ticket=1,
            symbol="EURUSD",
            direction="buy",
            volume=0.1,
            entry_price=1.1,
            exit_price=1.11,
            open_time="2026-07-17T10:00:00+00:00",
            close_time="2026-07-17T11:00:00+00:00",
            pnl=25.0,
            strategy="ultra_scalp",
            reason="ultra_scalp_v3,trend=bullish",
        )
    )
    journal.save()
    (state / "broker_positions_paper.json").write_text(
        json.dumps(
            {
                "mode": "paper",
                "updated_at": "2026-07-17T12:00:00+00:00",
                "account": {"equity": 10000, "balance": 10000},
                "positions": [],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("chronoscalp.saas.api._state_dir", lambda: state)
    monkeypatch.setattr(
        "chronoscalp.saas.api._detect_mode",
        lambda: "paper",
    )

    client = TestClient(create_app())
    journal_resp = client.get("/journal")
    assert journal_resp.status_code == 200
    body = journal_resp.json()
    assert body["closed_trades"][0]["strategy"] == "ultra_scalp"
    assert body["strategy_stats"][0]["strategy"] == "ultra_scalp"

    strat = client.get("/strategy-stats")
    assert strat.status_code == 200
    assert strat.json()["by_strategy"][0]["net_pnl"] == 25.0

    positions = client.get("/positions")
    assert positions.status_code == 200
    assert positions.json()["account"]["equity"] == 10000

    snap = client.get("/desktop/snapshot")
    assert snap.status_code == 200
    body = snap.json()
    assert body["status"]["mode"] == "paper"
    assert body["journal"]["closed_trades"][0]["strategy"] == "ultra_scalp"
    assert "by_strategy" in body["strategy"]
    assert isinstance(body["logs"]["lines"], list)
