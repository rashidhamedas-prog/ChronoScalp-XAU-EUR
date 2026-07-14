from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from chronoscalp.data.spread_sampler import SpreadSampler
from chronoscalp.filters.news_filter import NewsEvent, _fetch_events_from_api
from chronoscalp.ml.features import FEATURE_COLUMNS, extract_setup_features
from chronoscalp.ml.model import SetupClassifier
from chronoscalp.ml.scorer import configure_scorer, predict_setup_probability, reset_scorer
from chronoscalp.strategy.multi_timeframe import MultiTimeframeStrategy
from chronoscalp.utils.types import SignalType, Timeframe, TrendDirection


def _sample_row() -> pd.Series:
    return pd.Series(
        {
            "close": 2000.0,
            "rsi": 55.0,
            "macd": 0.5,
            "histogram": 0.1,
            "atr": 2.0,
            "bb_upper": 2005.0,
            "bb_lower": 1995.0,
            "bullish_ob": True,
            "bearish_ob": False,
            "fvg_bullish": False,
            "fvg_bearish": False,
            "liquidity_sweep_low": True,
            "liquidity_sweep_high": False,
        }
    )


def test_extract_setup_features_shape():
    features = extract_setup_features(
        trigger_row=_sample_row(),
        trend=TrendDirection.BULLISH,
        signal_type=SignalType.BUY,
        entry_price=2000.0,
        stop_loss=1990.0,
        take_profit=2025.0,
    )
    assert set(features.keys()) == set(FEATURE_COLUMNS)
    assert features["trend_bullish"] == 1.0
    assert features["is_buy"] == 1.0


def test_setup_classifier_train_and_predict():
    rng = pytest.importorskip("numpy").random.default_rng(0)
    rows = []
    for _ in range(80):
        row = {col: float(rng.random()) for col in FEATURE_COLUMNS}
        row["label"] = int(row["rsi"] > 0.5)
        rows.append(row)
    dataset = pd.DataFrame(rows)

    clf = SetupClassifier()
    report = clf.train(dataset)
    assert report.train_samples > 0
    assert 0.0 <= report.accuracy <= 1.0

    proba = clf.predict_proba({col: 0.5 for col in FEATURE_COLUMNS})
    assert 0.0 <= proba <= 1.0


def test_scorer_uses_loaded_model(tmp_path):
    reset_scorer()
    dataset = pd.DataFrame(
        [{**{col: 0.5 for col in FEATURE_COLUMNS}, "label": i % 2} for i in range(60)]
    )
    path = tmp_path / "model.joblib"
    clf = SetupClassifier()
    clf.train(dataset)
    clf.save(path)

    configure_scorer(path)
    score = predict_setup_probability({col: 0.5 for col in FEATURE_COLUMNS})
    assert 0.0 <= score <= 1.0
    reset_scorer()


def test_confidence_gate_only_when_model_loaded():
    reset_scorer()
    strategy = MultiTimeframeStrategy(
        {
            "require_trend_alignment": False,
            "use_smc_confluence": False,
            "min_signal_confidence": 0.99,
        },
        {"ema_period_trend": 50},
    )
    # Without model, gate is inactive — evaluate should not crash
    empty = pd.DataFrame(columns=["open", "high", "low", "close"])
    signal = strategy.evaluate("XAUUSD", {Timeframe.M1: empty}, [Timeframe.M5], Timeframe.M1)
    assert signal.signal_type == SignalType.NONE


def test_spread_sampler_writes_csv(tmp_path):
    sampler = SpreadSampler(tmp_path, enabled=True)
    ts = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    sampler.record("XAUUSD", 1.5, at=ts)
    content = (tmp_path / "XAUUSD_spread.csv").read_text(encoding="utf-8")
    assert "spread_pips" in content
    assert "1.5" in content


def test_finnhub_fetch_parses_events():
    mock_response = MagicMock(status_code=200)
    mock_response.json.return_value = {
        "economicCalendar": [
            {
                "country": "US",
                "event": "Nonfarm Payrolls",
                "time": "2026-01-10T13:30:00+00:00",
                "impact": "high",
            }
        ]
    }
    with patch("requests.get", return_value=mock_response):
        events = _fetch_events_from_api("test-key")
    assert events is not None
    assert len(events) == 1
    assert isinstance(events[0], NewsEvent)
    assert events[0].currency == "USD"
