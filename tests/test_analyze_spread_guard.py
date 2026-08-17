"""Tests for the spread-guard funnel report.

The parser reads real log shapes, including skip reasons that contain colons
and pipes, so a naive ``split(":")`` would silently mis-attribute counts.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import defaultdict
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "analyze_spread_guard.py"
_spec = importlib.util.spec_from_file_location("analyze_spread_guard", _SCRIPT)
assert _spec is not None and _spec.loader is not None
analyze = importlib.util.module_from_spec(_spec)
sys.modules["analyze_spread_guard"] = analyze
_spec.loader.exec_module(analyze)


LOG = """\
2026-08-17 03:02:40.820 | INFO | chronoscalp.risk.institutional_guards:allows:77 - \
XAUUSD spread guard: 8.00 > MA6.06*1.20
2026-08-17 03:05:50.955 | INFO | chronoscalp.risk.institutional_guards:allows:77 - \
XAUUSD spread guard: 12.00 > MA6.16*1.20
2026-08-17 03:07:28.920 | INFO | chronoscalp.risk.institutional_guards:allows:77 - \
XAUUSD spread guard: 13.00 > MA6.15*1.20
2026-08-17 03:02:38.639 | INFO | chronoscalp.risk.institutional_guards:allows:77 - \
EURUSD spread guard: 0.20 > MA0.11*1.20
2026-08-17 03:06:58.239 | INFO | chronoscalp.main:_maybe_log_skip_heartbeat:455 - \
Entry skip heartbeat (300s): XAUUSD:spread_ma=6, \
XAUUSD:scalp:scalp:symbol_blocked|inst:inst:trend_neutral|delta:regime_neutral=4, \
EURUSD:spread_ma=2, EURUSD:scalp:scalp:symbol_blocked=8
"""


@pytest.fixture
def report(tmp_path: Path) -> dict:
    log = tmp_path / "chronoscalp_2026-08-17.log"
    log.write_text(LOG, encoding="utf-8")
    stats: dict[str, analyze.SymbolStats] = defaultdict(analyze.SymbolStats)
    analyze.parse_log(log, stats)
    return analyze.build_report(stats, [log.name])


def test_spread_share_of_the_skip_funnel(report: dict) -> None:
    gold = report["symbols"]["XAUUSD"]
    assert gold["skipped_evaluations"] == 10
    assert gold["spread_guard_skips"] == 6
    assert gold["spread_guard_share_of_skips"] == 0.6


def test_compound_skip_reasons_are_not_split_on_colons(report: dict) -> None:
    gold = report["symbols"]["XAUUSD"]
    assert (
        gold["top_skip_reasons"]["scalp:scalp:symbol_blocked|inst:inst:trend_neutral"
                                 "|delta:regime_neutral"]
        == 4
    )
    assert "XAUUSD" not in report["symbols"]["EURUSD"]["top_skip_reasons"]


def test_blocked_spread_quantiles_and_excess(report: dict) -> None:
    gold = report["symbols"]["XAUUSD"]
    observed = gold["observed_spread_when_blocked"]
    assert (observed["min"], observed["median"], observed["max"]) == (8.0, 12.0, 13.0)
    assert gold["rejections_sampled"] == 3
    # cap = MA * 1.20, median of (7.27, 7.39, 7.38) = 7.38
    assert gold["cap_when_blocked_median"] == 7.38
    assert gold["median_excess_ratio"] == pytest.approx(1.63, abs=0.01)


def test_symbol_without_rejections_reports_none(tmp_path: Path) -> None:
    log = tmp_path / "chronoscalp_2026-08-18.log"
    log.write_text(
        "2026-08-18 01:00:00.000 | INFO | chronoscalp.main:_maybe_log_skip_heartbeat:455 - "
        "Entry skip heartbeat (300s): EURUSD:trend_neutral=3\n",
        encoding="utf-8",
    )
    stats: dict[str, analyze.SymbolStats] = defaultdict(analyze.SymbolStats)
    analyze.parse_log(log, stats)
    eur = analyze.build_report(stats, [log.name])["symbols"]["EURUSD"]
    assert eur["spread_guard_skips"] == 0
    assert eur["observed_spread_when_blocked"]["median"] is None
    assert eur["median_excess_ratio"] is None
