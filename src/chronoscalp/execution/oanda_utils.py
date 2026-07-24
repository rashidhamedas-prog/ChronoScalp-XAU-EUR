"""OANDA v20 REST helpers — symbol mapping, units conversion, API URLs.

All OANDA HTTP calls stay inside ``oanda_broker.py`` and ``oanda_connector.py``.
This module is pure and unit-testable.
"""

from __future__ import annotations

from chronoscalp.utils.types import SignalType, Timeframe

OANDA_PRACTICE_URL = "https://api-fxpractice.oanda.com"
OANDA_LIVE_URL = "https://api-fxtrade.oanda.com"

# ChronoScalp symbol → OANDA instrument name
SYMBOL_TO_INSTRUMENT: dict[str, str] = {
    "XAUUSD": "XAU_USD",
    "EURUSD": "EUR_USD",
    "EURJPY": "EUR_JPY",
    "USDJPY": "USD_JPY",
    "XAUEUR": "XAU_EUR",
    "BTCUSD": "BTC_USD",
    "ETHUSD": "ETH_USD",
}

INSTRUMENT_TO_SYMBOL: dict[str, str] = {v: k for k, v in SYMBOL_TO_INSTRUMENT.items()}

# OANDA native granularities (M3 is resampled from M1 in the connector)
OANDA_GRANULARITY: dict[Timeframe, str | None] = {
    Timeframe.S15: None,  # no native; connector falls back to M1
    Timeframe.S30: None,
    Timeframe.M1: "M1",
    Timeframe.M3: None,  # resample from M1
    Timeframe.M5: "M5",
    Timeframe.M10: "M10",
}


def api_base_url(environment: str) -> str:
    """Return REST base URL for ``practice`` or ``live``."""
    if environment.strip().lower() == "live":
        return OANDA_LIVE_URL
    return OANDA_PRACTICE_URL


def to_instrument(symbol: str) -> str:
    """Map a ChronoScalp symbol to an OANDA instrument id."""
    instrument = SYMBOL_TO_INSTRUMENT.get(symbol)
    if instrument is None:
        raise KeyError(
            f"No OANDA instrument mapping for '{symbol}'. "
            f"Add it to execution/oanda_utils.py SYMBOL_TO_INSTRUMENT."
        )
    return instrument


def to_chronoscalp_symbol(instrument: str) -> str:
    """Map an OANDA instrument back to a ChronoScalp symbol."""
    return INSTRUMENT_TO_SYMBOL.get(instrument, instrument.replace("_", ""))


def lots_to_units(symbol: str, lots: float, symbols_cfg: dict) -> int:
    """Convert standard lots to OANDA units (signed: negative for sells)."""
    spec = symbols_cfg[symbol]
    contract_size = int(spec.get("contract_size", 100_000))
    units = int(round(lots * contract_size))
    return max(units, 1)


def signed_units(symbol: str, lots: float, direction: SignalType, symbols_cfg: dict) -> int:
    """Return OANDA order units with sign for direction."""
    units = lots_to_units(symbol, lots, symbols_cfg)
    if direction == SignalType.SELL:
        return -units
    return units


def spread_pips_from_prices(bid: float, ask: float, pip_size: float) -> float:
    """Compute bid/ask spread in pips."""
    if pip_size <= 0:
        raise ValueError("pip_size must be positive")
    return (ask - bid) / pip_size
