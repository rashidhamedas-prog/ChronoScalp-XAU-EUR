from __future__ import annotations

from pathlib import Path

from chronoscalp.config import Settings
from chronoscalp.saas.broker_wizard import apply_enabled_strategies
from chronoscalp.strategy.live_gates import (
    FAILED,
    UNVALIDATED,
    VALIDATED,
    blocks_real_live_orders,
    force_shadow_if_not_live_ready,
    is_strategy_live_ready,
    symbol_validation_state,
    unvalidated_live_symbols,
)
from chronoscalp.strategy.multi_timeframe import is_shadow_only


def test_xau_is_not_live_ready_by_default():
    cfg = {"xau_vwap_pullback": {"enabled": True, "shadow_only": False, "live_ready": False}}
    assert is_strategy_live_ready(cfg, "xau_vwap_pullback") is False
    assert is_strategy_live_ready(cfg, "delta") is True
    assert force_shadow_if_not_live_ready(
        "xau_vwap_pullback", strategy_cfg=cfg, requested_shadow=False
    )
    assert blocks_real_live_orders(cfg, "xau_vwap_pullback", mode="live", shadow_only=False)


def test_apply_enabled_strategies_cannot_live_enable_xau_when_gate_closed(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(
        "chronoscalp.saas.broker_wizard._committed_xau_live_ready",
        lambda: False,
    )
    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_enabled_strategies(
        ["delta", "xau_vwap_pullback"],
        overrides_path=overrides,
    )
    assert "xau_vwap_pullback" in saved
    import yaml

    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    xau = data["strategy"]["xau_vwap_pullback"]
    assert xau["shadow_only"] is True
    assert xau.get("live_ready") is False
    assert is_shadow_only(data["strategy"], "xau_vwap_pullback") is True


def test_apply_enabled_strategies_live_enables_xau_when_gate_open(tmp_path: Path):
    overrides = tmp_path / "runtime_overrides.yaml"
    saved = apply_enabled_strategies(
        ["delta", "xau_vwap_pullback"],
        overrides_path=overrides,
    )
    assert "xau_vwap_pullback" in saved
    import yaml

    data = yaml.safe_load(overrides.read_text(encoding="utf-8"))
    xau = data["strategy"]["xau_vwap_pullback"]
    assert xau["shadow_only"] is False
    assert xau.get("live_ready") is True
    assert is_shadow_only(data["strategy"], "xau_vwap_pullback") is False


def test_symbol_validation_reads_the_recorded_verdict():
    cfg = {"delta": {"symbol_validation": {"XAUUSD": "validated", "EURUSD": "failed"}}}
    assert symbol_validation_state(cfg, "delta", "XAUUSD") == VALIDATED
    assert symbol_validation_state(cfg, "delta", "EURUSD") == FAILED


def test_absence_of_evidence_is_never_read_as_evidence():
    """An unlisted symbol, a missing block, and junk all mean unvalidated."""
    assert symbol_validation_state({"delta": {}}, "delta", "GBPUSD") == UNVALIDATED
    assert symbol_validation_state({}, "delta", "XAUUSD") == UNVALIDATED
    assert (
        symbol_validation_state(
            {"delta": {"symbol_validation": {"XAUUSD": "probably fine"}}}, "delta", "XAUUSD"
        )
        == UNVALIDATED
    )
    # A non-dict block must not raise.
    assert symbol_validation_state({"delta": {"symbol_validation": []}}, "delta", "XAUUSD") == (
        UNVALIDATED
    )


def test_unvalidated_live_symbols_flags_failed_and_unknown_but_not_validated():
    cfg = {"delta": {"symbol_validation": {"XAUUSD": "validated", "EURUSD": "failed"}}}
    risky = unvalidated_live_symbols(cfg, "delta", ["XAUUSD", "EURUSD", "GBPUSD"])
    assert risky == ["EURUSD", "GBPUSD"]
    assert unvalidated_live_symbols(cfg, "delta", ["XAUUSD"]) == []


def test_shipped_config_records_the_measured_delta_verdicts():
    """Guards the 2026-08-29 evidence against a silent config edit.

    XAUUSD earned its verdict (PF 1.754, E[R] +0.284 on the parity engine);
    EURUSD produced four straight full stop-outs at exactly -1.00R.
    """
    strategy_cfg = Settings().strategy
    assert symbol_validation_state(strategy_cfg, "delta", "XAUUSD") == VALIDATED
    assert symbol_validation_state(strategy_cfg, "delta", "EURUSD") == FAILED
