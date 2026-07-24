from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from chronoscalp.execution.oanda_utils import (
    OANDA_LIVE_URL,
    OANDA_PRACTICE_URL,
    api_base_url,
    lots_to_units,
    signed_units,
    spread_pips_from_prices,
    to_instrument,
)
from chronoscalp.utils.types import SignalType


def test_api_base_url_practice_and_live():
    assert api_base_url("practice") == OANDA_PRACTICE_URL
    assert api_base_url("live") == OANDA_LIVE_URL


def test_to_instrument_mapping():
    assert to_instrument("EURUSD") == "EUR_USD"
    assert to_instrument("XAUUSD") == "XAU_USD"
    assert to_instrument("EURJPY") == "EUR_JPY"


def test_to_instrument_unknown_raises():
    with pytest.raises(KeyError):
        to_instrument("UNKNOWN")


def test_lots_to_units_eurusd():
    cfg = {"EURUSD": {"contract_size": 100_000}}
    assert lots_to_units("EURUSD", 0.1, cfg) == 10_000


def test_signed_units_sell_is_negative():
    cfg = {"EURUSD": {"contract_size": 100_000}}
    assert signed_units("EURUSD", 0.01, SignalType.SELL, cfg) == -1000


def test_spread_pips_from_prices():
    assert spread_pips_from_prices(1.10000, 1.10020, 0.0001) == pytest.approx(2.0)


def test_oanda_connector_connect_success():
    from chronoscalp.data.oanda_connector import OANDAConnector

    connector = OANDAConnector(api_token="tok", account_id="123", environment="practice")
    with patch("chronoscalp.data.oanda_connector.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: {"account": {}})
        assert connector.connect() is True
        assert connector.is_connected is True


def test_bootstrap_resolves_oanda_for_linux_broker():
    from chronoscalp.config import Settings
    from chronoscalp.orchestration.bootstrap import resolve_data_source

    settings = Settings.__new__(Settings)
    settings.raw = {"execution": {"broker": "oanda", "data_source": "auto"}}
    assert resolve_data_source(settings) == "oanda"
