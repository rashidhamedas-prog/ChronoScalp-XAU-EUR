"""Tests for the cost-stress validation window slicing.

History frames carry a tz-aware UTC index, while ``--from``/``--to`` parse to
naive datetimes. Comparing the two raises ``TypeError``, which made the
explicit-window arguments unusable and silently forced everyone onto
``--last-days``.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_cost_stress_validate.py"
_spec = importlib.util.spec_from_file_location("run_cost_stress_validate", _SCRIPT)
assert _spec is not None and _spec.loader is not None
validate = importlib.util.module_from_spec(_spec)
sys.modules["run_cost_stress_validate"] = validate
_spec.loader.exec_module(validate)


def _aware_frame(periods: int = 800) -> pd.DataFrame:
    index = pd.date_range("2026-06-01", periods=periods, freq="h", tz="UTC")
    return pd.DataFrame({"close": range(periods)}, index=index)


def _naive_frame(periods: int = 800) -> pd.DataFrame:
    index = pd.date_range("2026-06-01", periods=periods, freq="h")
    return pd.DataFrame({"close": range(periods)}, index=index)


def test_align_tz_localises_naive_bound_to_aware_index():
    frame = _aware_frame()
    aligned = validate._align_tz(pd.Timestamp("2026-06-20"), frame.index)
    assert aligned is not None
    assert aligned.tzinfo is not None
    assert aligned == pd.Timestamp("2026-06-20", tz="UTC")


def test_align_tz_strips_tz_for_naive_index():
    frame = _naive_frame()
    aligned = validate._align_tz(pd.Timestamp("2026-06-20", tz="UTC"), frame.index)
    assert aligned is not None
    assert aligned.tzinfo is None


def test_align_tz_passes_through_none():
    assert validate._align_tz(None, _aware_frame().index) is None


def test_slice_with_warmup_accepts_naive_bounds_against_aware_index():
    """Regression: this raised TypeError and aborted the whole validation run."""
    frame = _aware_frame()
    start = datetime(2026, 6, 20)
    end = datetime(2026, 6, 25)

    sliced = validate._slice_with_warmup(frame, start, end)

    assert not sliced.empty
    assert sliced.index.max() <= pd.Timestamp(end, tz="UTC")
    # Warmup bars before the start are retained for indicator stability.
    assert sliced.index.min() < pd.Timestamp(start, tz="UTC")


def test_slice_with_warmup_accepts_aware_bounds_too():
    frame = _aware_frame()
    sliced = validate._slice_with_warmup(
        frame, datetime(2026, 6, 20, tzinfo=UTC), datetime(2026, 6, 25, tzinfo=UTC)
    )
    assert not sliced.empty
    assert sliced.index.max() <= pd.Timestamp("2026-06-25", tz="UTC")


def test_slice_with_warmup_caps_warmup_length():
    frame = _aware_frame(periods=2000)
    sliced = validate._slice_with_warmup(frame, datetime(2026, 8, 1), None)
    warmup = sliced[sliced.index < pd.Timestamp("2026-08-01", tz="UTC")]
    assert len(warmup) == validate._WARMUP_BARS


def test_slice_with_warmup_returns_frame_unchanged_without_bounds():
    frame = _aware_frame()
    assert validate._slice_with_warmup(frame, None, None) is frame
