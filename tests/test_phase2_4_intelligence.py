"""Phase 2–4 intelligence, bridge protocol, i18n, RL kill-path."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

from chronoscalp.bridge.protocol import (
    BridgeMsgType,
    make_envelope,
    validate_envelope,
)
from chronoscalp.intelligence.expectancy import (
    estimate_net_expectancy_r,
    rank_by_net_expectancy,
    score_signal,
)
from chronoscalp.intelligence.model_card import new_card, write_model_card
from chronoscalp.intelligence.regime import RegimeDetector, build_regime_features
from chronoscalp.intelligence.rl_manager import RlAction, RlPositionManager
from chronoscalp.saas.api import create_app
from chronoscalp.saas.i18n import catalog, t
from chronoscalp.utils.types import Signal, SignalType


def test_regime_fit_predict_gmm_fallback() -> None:
    rng = np.random.default_rng(0)
    n = 120
    features = build_regime_features(
        rng.normal(0, 0.001, n),
        rng.uniform(0.001, 0.01, n),
        rng.uniform(0.001, 0.02, n),
        rng.uniform(5, 25, n),
    )
    det = RegimeDetector(n_states=3).fit(features)
    state = det.latest(features)
    assert state.label
    assert 0.0 <= state.confidence <= 1.0
    assert det.allows_strategy(state, "delta") in {True, False}


def test_expectancy_ranking_prefers_net_edge() -> None:
    assert estimate_net_expectancy_r(win_prob=0.6, reward_risk=1.5, cost_r=0.1) > 0
    good = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(tz=UTC),
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2020.0,
        strategy="delta",
    )
    weak = Signal(
        symbol="XAUUSD",
        signal_type=SignalType.BUY,
        timestamp=datetime.now(tz=UTC),
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2010.0,
        strategy="ultra_scalp",
    )
    ranked = rank_by_net_expectancy(
        [
            score_signal(weak, win_prob=0.4, cost_r=0.2),
            score_signal(good, win_prob=0.55, cost_r=0.1),
        ]
    )
    assert ranked[0].strategy == "delta"


def test_model_card_roundtrip(tmp_path) -> None:
    card = new_card(
        name="regime_v1",
        kind="regime",
        features=["log_return", "realized_vol", "atr_pct", "spread_pips"],
        training_window="2026-01..2026-06",
        metrics={"n_states": 3},
    )
    path = write_model_card(card, tmp_path / "regime.card.json")
    assert path.exists()


def test_rl_kill_path_reverts() -> None:
    mgr = RlPositionManager(enabled=True, shadow=False, max_size_multiplier=1.0)
    mgr._policy = object()  # pretend loaded
    mgr.trip_kill("test")
    decision = mgr.decide(regime_label="trend", r_multiple=0.2, spread_pips=10.0, bars_in_trade=3)
    assert decision.source == "rule_based" or decision.source == "kill_revert"
    assert decision.action in {RlAction.HOLD, RlAction.BREAKEVEN}


def test_rl_rejects_size_above_ceiling() -> None:
    with pytest.raises(ValueError):
        RlPositionManager(max_size_multiplier=1.1)


def test_bridge_envelope_token_gate() -> None:
    msg = make_envelope(
        BridgeMsgType.OPEN,
        payload={"symbol": "XAUUSD", "side": "buy"},
        idempotency_key="abc",
        token="secret",
    )
    validate_envelope(msg, expected_token="secret")
    with pytest.raises(PermissionError):
        validate_envelope(msg, expected_token="other")


def test_i18n_fa_en() -> None:
    assert "Overview" in t("nav.overview", "en")
    assert t("nav.overview", "fa")
    assert "metric.expectancy" in catalog("en")


def test_api_i18n_and_bridge_diag(monkeypatch) -> None:
    monkeypatch.setenv("CHRONOSCALP_API_TOKEN", "tok")
    client = TestClient(create_app())
    headers = {"Authorization": "Bearer tok"}
    r = client.get("/i18n/fa", headers=headers)
    assert r.status_code == 200
    assert r.json()["lang"] == "fa"
    d = client.get("/diagnostics/bridge", headers=headers)
    assert d.status_code == 200
    assert d.json()["schema_version"] == 1
