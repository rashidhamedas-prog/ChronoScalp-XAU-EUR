from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from chronoscalp.orchestration.strategy_attribution import AttributionLedger
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy, is_shadow_only
from chronoscalp.strategy.xau_vwap_pullback import (
    ImpulseState,
    XauVwapPullbackEngine,
    _root,
    assess_m1_pullback,
    detect_m5_impulse,
    generate_xau_vwap_pullback_signal,
    origin_violated,
    score_m15_regime,
)
from chronoscalp.utils.types import SignalType, Timeframe, TrendDirection


def _cfg(**overrides):
    cfg = {
        "enabled": True,
        "shadow_only": True,
        "allowed_symbols": ["XAUUSD"],
        "ema_slope_bars": 3,
        "impulse_lookback": 8,
        "impulse_swing_bars": 10,
        "impulse_body_atr": 0.6,
        "impulse_rvol_min": 1.10,
        "impulse_expire_m1_bars": 6,
        "min_body_fraction": 0.45,
        "level_touch_atr": 0.20,
        "no_chase_atr": 0.25,
        "trigger_expire_m1_bars": 2,
        "sl_buffer_atr": 0.15,
        "min_stop_atr": 0.70,
        "max_stop_atr": 1.80,
        "reward_risk_ratio": 2.0,
        "cost_stress_multiple": 1.5,
        "min_net_rr_cost_stress": 1.25,
        "min_score": 5,
        "m1_rvol_score_min": 1.10,
        "spread_median_expansion": 1.2,
    }
    cfg.update(overrides)
    return cfg


def _m15(direction: str, n: int = 16) -> pd.DataFrame:
    index = pd.date_range("2026-07-13 12:00", periods=n, freq="15min", tz="UTC")
    if direction == "up":
        close = np.linspace(2000.0, 2045.0, n)
        ema20 = close - 1.0
        ema50 = close - 6.0
    elif direction == "down":
        close = np.linspace(2045.0, 2000.0, n)
        ema20 = close + 1.0
        ema50 = close + 6.0
    else:
        close = np.full(n, 2020.0)
        ema20 = close.copy()
        ema50 = close.copy()
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "ema_20": ema20,
            "ema_50": ema50,
            "atr": np.full(n, 4.0),
            "rvol": np.full(n, 1.2),
        },
        index=index,
    )


def test_root_alias_xauusd_o():
    assert _root("XAUUSD_o") == "XAUUSD"
    assert _root("XAUUSD") == "XAUUSD"


def test_regime_long_short_neutral():
    cfg = _cfg()
    bias, score, full = score_m15_regime(_m15("up"), cfg)
    assert bias == TrendDirection.BULLISH
    assert score >= 2
    bias, score, _ = score_m15_regime(_m15("down"), cfg)
    assert bias == TrendDirection.BEARISH
    assert score >= 2
    bias, score, _ = score_m15_regime(_m15("flat"), cfg)
    assert bias == TrendDirection.NEUTRAL


def test_m5_impulse_valid_and_missing():
    cfg = _cfg()
    n = 22
    index = pd.date_range("2026-07-13 12:00", periods=n, freq="5min", tz="UTC")
    close = np.full(n, 2000.0)
    high = close + 0.4
    low = close - 0.4
    open_ = close.copy()
    # Last bar breaks the prior swing high with a large body + rvol.
    open_[-1], high[-1], low[-1], close[-1] = 2000.0, 2012.0, 1999.5, 2011.0
    m5 = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "atr": np.full(n, 5.0),
            "rvol": np.full(n, 1.2),
            "ema_20": close + 1,
            "ema_50": close - 1,
        },
        index=index,
    )
    impulse = detect_m5_impulse(m5, TrendDirection.BULLISH, cfg)
    assert impulse is not None
    assert impulse.direction == TrendDirection.BULLISH
    quiet = m5.copy()
    quiet.loc[quiet.index[-1], "rvol"] = 0.5
    assert detect_m5_impulse(quiet, TrendDirection.BULLISH, cfg) is None


def test_pullback_valid_and_too_deep():
    cfg = _cfg()
    impulse = ImpulseState(
        direction=TrendDirection.BULLISH,
        origin=1990.0,
        extreme=2020.0,
        broken_level=2005.0,
        started_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
    )
    index = pd.date_range("2026-07-13 13:00", periods=8, freq="min", tz="UTC")
    close = np.full(8, 2006.8)
    open_ = np.full(8, 2004.0)
    high = np.full(8, 2007.0)
    low = np.full(8, 2003.5)
    m1 = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "atr": np.full(8, 4.0),
            "rvol": np.full(8, 1.2),
        },
        index=index,
    )
    setup = assess_m1_pullback(m1, impulse, vwap=2004.6, cfg=cfg)
    assert setup is not None
    deep = m1.copy()
    deep.loc[deep.index[-1], ["open", "high", "low", "close"]] = (1992.0, 1993.0, 1991.0, 1992.8)
    assert assess_m1_pullback(deep, impulse, vwap=2010.0, cfg=cfg) is None


def test_origin_break_and_no_chase_pending():
    impulse = ImpulseState(
        direction=TrendDirection.BULLISH,
        origin=2000.0,
        extreme=2020.0,
        broken_level=2010.0,
        started_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
    )
    row = pd.Series({"close": 1999.0, "open": 2001.0, "high": 2002.0, "low": 1998.0})
    assert origin_violated(row, impulse) is True
    engine = XauVwapPullbackEngine(cfg=_cfg(), symbols_cfg={"XAUUSD": {"pip_size": 0.01}})
    engine._impulse["XAUUSD"] = ImpulseState(
        direction=TrendDirection.BULLISH,
        origin=1990.0,
        extreme=2020.0,
        broken_level=2010.0,
        started_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
        m1_bars=1,
    )
    from chronoscalp.strategy.xau_vwap_pullback import PendingTrigger

    engine._pending["XAUUSD"] = PendingTrigger(
        direction=TrendDirection.BULLISH,
        entry=2010.0,
        stop_loss=2000.0,
        take_profit=2030.0,
        rejection_high=2009.99,
        rejection_low=2005.0,
        score=6,
        rvol=1.2,
        created_at=datetime(2026, 7, 13, 13, tzinfo=UTC),
        bars_left=2,
        atr=4.0,
        reason="xau_vwap_pullback,pending",
        stop_emitted=True,
    )
    m1 = _m15("up").copy()
    m1["atr"] = 4.0
    m1["rvol"] = 1.2
    # Far from trigger → no chase.
    m1.iloc[-1, m1.columns.get_loc("close")] = 2025.0
    sig = engine.evaluate(
        "XAUUSD",
        m1=m1,
        m5=_m15("up"),
        m15=_m15("up"),
        spread_pips=20.0,
        median_spread_pips=20.0,
        broker_spread_cap_pips=35.0,
    )
    assert sig.signal_type == SignalType.NONE
    assert "no_chase" in sig.reason


def test_symbol_allowlist_and_spread_reject():
    engine = XauVwapPullbackEngine(cfg=_cfg(), symbols_cfg={"XAUUSD": {"pip_size": 0.01}})
    frames = dict(m1=_m15("up"), m5=_m15("up"), m15=_m15("up"))
    blocked = engine.evaluate(
        "EURUSD",
        **frames,
        spread_pips=20.0,
        median_spread_pips=20.0,
        broker_spread_cap_pips=35.0,
    )
    assert "symbol_blocked" in blocked.reason
    wide = engine.evaluate(
        "XAUUSD_o",
        **frames,
        spread_pips=40.0,
        median_spread_pips=20.0,
        broker_spread_cap_pips=35.0,
    )
    assert "spread" in wide.reason


def test_default_config_is_live_ready():
    import yaml

    from chronoscalp.config import CONFIG_DIR

    data = yaml.safe_load((CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))
    strat = data["strategy"]
    xau = strat.get("xau_vwap_pullback") or {}
    assert xau.get("enabled") is True
    assert xau.get("shadow_only") is False
    assert xau.get("live_ready") is True
    assert "xau_vwap_pullback" in (strat.get("enabled_strategies") or [])
    assert is_shadow_only(strat, "xau_vwap_pullback") is False


def test_no_lookahead_truncation_regime():
    full = _m15("up", n=20)
    prefix = full.iloc[:-4]
    a = score_m15_regime(prefix, _cfg())
    b = score_m15_regime(full.iloc[: len(prefix)], _cfg())
    assert a == b


def test_generate_wrapper_uses_m15_then_m5():
    sig = generate_xau_vwap_pullback_signal(
        "XAUUSD",
        _m15("flat"),
        [_m15("flat"), _m15("flat")],
        config=_cfg(enabled=True),
        symbol_spec={"pip_size": 0.01},
        spread_pips=20.0,
        median_spread_pips=20.0,
        broker_spread_cap_pips=35.0,
    )
    assert sig.strategy == "xau_vwap_pullback"
    assert sig.signal_type == SignalType.NONE


def test_simultaneous_delta_and_xau_candidates(monkeypatch):
    from chronoscalp.strategy import delta as delta_mod
    from chronoscalp.strategy import xau_vwap_pullback as xau_mod
    from chronoscalp.utils.types import Signal

    ts = datetime(2026, 7, 13, 13, tzinfo=UTC)

    def _delta(*_a, **_k):
        return Signal(
            symbol="XAUUSD",
            signal_type=SignalType.BUY,
            timestamp=ts,
            entry_price=2000.0,
            stop_loss=1990.0,
            take_profit=2020.0,
            timeframe=Timeframe.M1,
            reason="delta,test",
            strategy="delta",
        )

    def _xau(*_a, **_k):
        return Signal(
            symbol="XAUUSD",
            signal_type=SignalType.BUY,
            timestamp=ts,
            entry_price=2001.0,
            stop_loss=1991.0,
            take_profit=2021.0,
            timeframe=Timeframe.M1,
            reason="xau_vwap_pullback,pullback_rejection,trend=bullish,score=6,rvol=1.20",
            strategy="xau_vwap_pullback",
        )

    monkeypatch.setattr(delta_mod, "generate_delta_signal", _delta)
    monkeypatch.setattr(xau_mod, "generate_xau_vwap_pullback_signal", _xau)
    strategy = MultiTimeframeStrategy(
        {
            "enabled_strategies": ["delta", "xau_vwap_pullback"],
            "xau_vwap_pullback": _cfg(),
            "delta": {"enabled": True, "allowed_symbols": ["XAUUSD"]},
            "min_signal_confidence": 0.0,
        },
        {"ema_period_trend": 50},
        symbols_cfg={"XAUUSD": {"pip_size": 0.01}},
    )
    m1 = _m15("up")
    cands = strategy.evaluate_candidates(
        "XAUUSD",
        {Timeframe.M15: m1, Timeframe.M5: m1, Timeframe.M1: m1},
        higher_timeframes=[Timeframe.M15, Timeframe.M5],
        trigger_timeframe=Timeframe.M1,
        ignore_confidence_gate=True,
        spread_pips=20.0,
        median_spread_pips=20.0,
        broker_spread_cap_pips=35.0,
    )
    tags = {s.strategy for s in cands}
    assert tags == {"delta", "xau_vwap_pullback"}


def test_attribution_heat_block_counters():
    ledger = AttributionLedger()
    counters = ledger.for_strategy("xau_vwap_pullback")
    counters.evaluated += 1
    counters.candidate += 1
    counters.lost_arbitration += 1
    counters.record_heat_block("delta")
    snap = ledger.snapshot()
    assert snap["xau_vwap_pullback"]["lost_arbitration"] == 1
    assert snap["xau_vwap_pullback"]["heat_blocked_by"]["delta"] == 1


def _append_m1(df: pd.DataFrame, close: float) -> pd.DataFrame:
    nxt = df.index[-1] + pd.Timedelta(minutes=1)
    row = df.iloc[-1].copy()
    row["open"] = close
    row["high"] = close + 0.2
    row["low"] = close - 0.2
    row["close"] = close
    row.name = nxt
    return pd.concat([df, row.to_frame().T])


def _eval_pending(engine, m1):
    return engine.evaluate(
        "XAUUSD",
        m1=m1,
        m5=_m15("up"),
        m15=_m15("up"),
        spread_pips=20.0,
        median_spread_pips=20.0,
        broker_spread_cap_pips=35.0,
    )


def _seed_emitted_stop(engine) -> pd.DataFrame:
    engine._impulse["XAUUSD"] = ImpulseState(
        direction=TrendDirection.BULLISH,
        origin=1990.0,
        extreme=2020.0,
        broken_level=2010.0,
        started_at=datetime(2026, 7, 13, 12, tzinfo=UTC),
        m1_bars=1,
    )
    from chronoscalp.strategy.xau_vwap_pullback import PendingTrigger

    engine._pending["XAUUSD"] = PendingTrigger(
        direction=TrendDirection.BULLISH,
        entry=2010.0,
        stop_loss=2000.0,
        take_profit=2030.0,
        rejection_high=2009.99,
        rejection_low=2005.0,
        score=6,
        rvol=1.2,
        created_at=datetime(2026, 7, 13, 13, tzinfo=UTC),
        bars_left=2,
        atr=4.0,
        reason="xau_vwap_pullback,pending",
        stop_emitted=True,
    )
    m1 = _m15("up").copy()
    m1["atr"] = 4.0
    m1["rvol"] = 1.2
    m1.iloc[-1, m1.columns.get_loc("close")] = 2010.2
    return m1


def test_stop_trigger_same_m1_bar_does_not_expire():
    engine = XauVwapPullbackEngine(cfg=_cfg(), symbols_cfg={"XAUUSD": {"pip_size": 0.01}})
    m1 = _seed_emitted_stop(engine)
    first = _eval_pending(engine, m1)
    second = _eval_pending(engine, m1)
    assert first.signal_type == SignalType.NONE
    assert "awaiting_fill" in first.reason
    assert "awaiting_fill" in second.reason
    assert engine.working_stop("XAUUSD") is not None
    assert engine.working_stop("XAUUSD").bars_left == 2


def test_stop_trigger_expires_after_two_m1_bars():
    engine = XauVwapPullbackEngine(cfg=_cfg(), symbols_cfg={"XAUUSD": {"pip_size": 0.01}})
    m1 = _seed_emitted_stop(engine)
    first = _eval_pending(engine, m1)
    assert first.signal_type == SignalType.NONE
    assert "awaiting_fill" in first.reason
    m1 = _append_m1(m1, 2010.2)
    mid = _eval_pending(engine, m1)
    assert "awaiting_fill" in mid.reason
    assert engine.working_stop("XAUUSD") is not None
    m1 = _append_m1(m1, 2010.2)
    expired = _eval_pending(engine, m1)
    assert "trigger_expired" in expired.reason
    assert engine.working_stop("XAUUSD") is None
