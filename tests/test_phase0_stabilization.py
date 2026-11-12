"""Phase 0 regression locks for critical audit defects C-01..C-06 / P0-*."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from chronoscalp.execution.cost_model import side_fill_costs
from chronoscalp.execution.oanda_broker import OANDABroker
from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.execution.position_logic import check_sl_tp_hit
from chronoscalp.filters.news_filter import NewsFilter
from chronoscalp.ml.dataset import _label_outcome
from chronoscalp.ml.model import chronological_train_test_split
from chronoscalp.orchestration.circuit_breaker import CircuitBreaker
from chronoscalp.orchestration.instance_lock import InstanceLock, InstanceLockError
from chronoscalp.orchestration.state_store import TradingStateStore
from chronoscalp.utils.atomic_json import read_json_with_fallback, write_json_atomic
from chronoscalp.utils.broker_clock import measure_offset_from_tick, to_true_utc
from chronoscalp.utils.types import Position, Signal, SignalType, Timeframe

XAU_SPEC = {
    "pip_size": 0.01,
    "pip_value_per_lot": 1.0,
    "typical_spread_pips": 20.0,
    "commission_per_lot": 7.0,
    "contract_size": 100.0,
}


def test_paper_broker_charges_spread_and_commission() -> None:
    broker = PaperBroker(
        {"XAUUSD": dict(XAU_SPEC)},
        starting_balance=10_000.0,
        slippage_pips=0.0,
    )
    signal = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timeframe=Timeframe.M1,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2020.0,
        timestamp=datetime.now(tz=UTC),
        reason="test",
        strategy="delta",
    )
    pos = broker.place_order(signal, volume=1.0, fill_price=2000.0)
    entry_costs = side_fill_costs(
        XAU_SPEC, entry_price=pos.entry_price, volume=1.0, spread_pips=20.0
    )
    assert broker.balance == pytest.approx(10_000.0 - entry_costs.total)
    result = broker.close_position(pos.ticket, exit_price=2000.0)
    assert result.pnl < result.gross_pnl
    assert result.commission_paid == pytest.approx(7.0)
    assert result.spread_cost == pytest.approx(20.0)
    assert result.pnl < 0


def test_shared_sl_first_label_matches_position_logic() -> None:
    df = pd.DataFrame(
        {
            "high": [2005.0, 2025.0],
            "low": [1995.0, 1985.0],
            "close": [2000.0, 2010.0],
        }
    )
    # Label walk starts at entry_idx+1; bar 1 pierces both SL (1990) and TP (2020).
    label = _label_outcome(df, 0, SignalType.BUY, 2000.0, 1990.0, 2020.0)
    assert label == 0
    hit = check_sl_tp_hit(
        Position(
            ticket=1,
            symbol="XAUUSD",
            direction=SignalType.BUY,
            volume=0.1,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            open_time=datetime.now(tz=UTC),
        ),
        bar_high=2025.0,
        bar_low=1985.0,
    )
    assert hit.hit_sl and hit.hit_tp
    assert hit.exit_reason() == "stop_loss"


def test_chronological_split_with_embargo() -> None:
    ds = pd.DataFrame({"a": range(20), "label": [i % 2 for i in range(20)]})
    train, test = chronological_train_test_split(ds, test_size=0.25, embargo=2)
    assert len(test) == 5
    assert train.index.max() < test.index.min()
    assert len(train) == 13  # 15 - embargo 2


def test_circuit_breaker_min_trip_and_success_threshold() -> None:
    br = CircuitBreaker(max_consecutive_errors=2, min_trip_seconds=600, success_threshold=3)
    t0 = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)
    assert br.record_failure("a", now=t0) is False
    assert br.record_failure("b", now=t0) is True
    assert br.is_tripped
    # Successes inside the min trip window are ignored.
    br.record_success(now=t0 + timedelta(seconds=30))
    assert br.is_tripped
    # After min duration, half-open then needs N successes.
    br.record_success(now=t0 + timedelta(seconds=601))
    assert br.is_half_open
    br.record_success(now=t0 + timedelta(seconds=602))
    br.record_success(now=t0 + timedelta(seconds=603))
    assert not br.is_tripped


def test_atomic_json_recovers_from_backup(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    write_json_atomic(path, {"ok": 1})
    path.write_text("{broken", encoding="utf-8")
    payload, source = read_json_with_fallback(path, default={"ok": 0})
    assert source == "backup"
    assert payload["ok"] == 1


def test_state_store_tolerates_corrupt_main(tmp_path: Path) -> None:
    path = tmp_path / "trading_state.json"
    store = TradingStateStore(path)
    store.state.open_tickets["XAUUSD::delta"] = 7
    store.save()
    path.write_text("NOT-JSON", encoding="utf-8")
    loaded = TradingStateStore(path)
    state = loaded.load()
    assert state.open_tickets["XAUUSD::delta"] == 7
    assert loaded._loaded_from_backup is True


def test_instance_lock_blocks_second_live_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    real_pid = os.getpid()
    lock_a = InstanceLock(tmp_path, enabled=True)
    lock_a.acquire(magic=42)
    monkeypatch.setattr(
        "chronoscalp.orchestration.instance_lock._pid_alive",
        lambda pid: True,
    )
    # Simulate a different process id attempting to acquire the same lock.
    monkeypatch.setattr(
        "chronoscalp.orchestration.instance_lock.os.getpid",
        lambda: 999999,
    )
    lock_b = InstanceLock(tmp_path, enabled=True)
    with pytest.raises(InstanceLockError):
        lock_b.acquire(magic=42)
    monkeypatch.setattr(
        "chronoscalp.orchestration.instance_lock.os.getpid",
        lambda: real_pid,
    )
    lock_a.release()


def test_news_filter_fail_closed_when_stale() -> None:
    nf = NewsFilter(
        events=[],
        blackout_before=timedelta(minutes=30),
        blackout_after=timedelta(minutes=30),
        fail_closed_when_stale=True,
        max_calendar_age_minutes=10,
        fetched_at=datetime(2026, 11, 12, 10, 0, tzinfo=UTC),
    )
    assert nf.is_blackout(datetime(2026, 11, 12, 10, 20, tzinfo=UTC)) is True


def test_broker_clock_offset_rounds_to_quarter_hour() -> None:
    wall = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    server_epoch = wall.timestamp() + 3 * 3600
    offset = measure_offset_from_tick(server_epoch, wall_utc=wall, max_tick_age_seconds=120)
    assert offset.offset_hours == pytest.approx(3.0)
    true_utc = to_true_utc(server_epoch, offset)
    assert abs((true_utc - wall).total_seconds()) < 60


def test_oanda_fetch_closed_pnl_from_transactions(monkeypatch: pytest.MonkeyPatch) -> None:
    broker = OANDABroker(
        api_token="tok",
        account_id="acct",
        symbols_cfg={"XAUUSD": dict(XAU_SPEC)},
        environment="practice",
    )

    class _Resp:
        def __init__(self, code: int, body: dict):
            self.status_code = code
            self._body = body

        def json(self) -> dict:
            return self._body

    def fake_get(url, headers=None, params=None, timeout=None):  # noqa: ANN001
        if url.endswith("/trades/99"):
            return _Resp(404, {})
        if url.endswith("/transactions"):
            return _Resp(
                200,
                {
                    "transactions": [
                        {
                            "type": "ORDER_FILL",
                            "tradesClosed": [{"tradeID": "99", "realizedPL": "-12.5"}],
                        }
                    ]
                },
            )
        return _Resp(500, {})

    monkeypatch.setattr("chronoscalp.execution.oanda_broker.requests.get", fake_get)
    assert broker.fetch_closed_pnl(99) == pytest.approx(-12.5)
