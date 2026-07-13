from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from chronoscalp.orchestration.bar_scheduler import (
    BarCloseGate,
    SignalDeduper,
    last_completed_bar_time,
    signal_dedup_key,
)
from chronoscalp.utils.types import SignalType, Timeframe


def test_last_completed_bar_time_uses_penultimate_row():
    index = pd.date_range("2026-01-01", periods=5, freq="1min", tz="UTC")
    df = pd.DataFrame({"close": range(5)}, index=index)
    assert last_completed_bar_time(df) == index[-2].to_pydatetime()


def test_last_completed_bar_time_requires_two_rows():
    index = pd.date_range("2026-01-01", periods=1, freq="1min", tz="UTC")
    df = pd.DataFrame({"close": [1]}, index=index)
    assert last_completed_bar_time(df) is None


def test_bar_close_gate_only_fires_once_per_bar():
    gate = BarCloseGate()
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)

    assert gate.is_new_bar("XAUUSD", t1) is True
    gate.mark_evaluated("XAUUSD", t1)
    assert gate.is_new_bar("XAUUSD", t1) is False
    assert gate.is_new_bar("XAUUSD", t2) is True


def test_signal_dedup_key_stable():
    t = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    key = signal_dedup_key("XAUUSD", Timeframe.M1, t, SignalType.BUY)
    assert key == "XAUUSD|M1|2026-01-01T12:00:00+00:00|buy"


def test_signal_deduper_tracks_processed_keys():
    deduper = SignalDeduper()
    assert deduper.already_processed("a") is False
    deduper.mark_processed("a")
    assert deduper.already_processed("a") is True
