"""OANDA v20 REST market-data connector — runs on Linux/macOS/Windows.

Fetches OHLCV candles for live/paper loops without MetaTrader5. M3 bars are
built by resampling M1 (OANDA has no native M3 granularity).
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import requests

from chronoscalp.data.mt5_connector import OHLCV_COLUMNS, resample_ohlcv
from chronoscalp.execution.oanda_utils import (
    OANDA_GRANULARITY,
    api_base_url,
    to_instrument,
)
from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Timeframe


class OANDAConnector:
    """Thin wrapper around OANDA v20 instrument candle endpoints."""

    def __init__(
        self,
        api_token: str,
        account_id: str,
        environment: str = "practice",
        timeout_seconds: float = 15.0,
    ) -> None:
        self._token = api_token.strip()
        self._account_id = account_id.strip()
        self._base_url = api_base_url(environment)
        self._timeout = timeout_seconds
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def account_id(self) -> str:
        return self._account_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def connect(self) -> bool:
        if not self._token or not self._account_id:
            logger.error("OANDA connect failed: OANDA_API_TOKEN and OANDA_ACCOUNT_ID required")
            return False
        url = f"{self._base_url}/v3/accounts/{self._account_id}/summary"
        try:
            response = requests.get(url, headers=self._headers(), timeout=self._timeout)
        except requests.RequestException as exc:
            logger.error("OANDA connect request failed: {}", exc)
            return False
        if response.status_code >= 400:
            logger.error(
                "OANDA connect failed: HTTP {} {}", response.status_code, response.text[:200]
            )
            return False
        self._connected = True
        logger.info("Connected to OANDA ({}, account={})", self._base_url, self._account_id)
        return True

    def shutdown(self) -> None:
        self._connected = False

    def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, count: int = 500) -> pd.DataFrame:
        """Fetch recent candles for ``symbol`` at ``timeframe``."""
        granularity = OANDA_GRANULARITY.get(timeframe)
        if granularity is None:
            m1 = self.fetch_ohlcv(symbol, Timeframe.M1, count=count * timeframe.minutes + 50)
            if m1.empty:
                return m1
            return resample_ohlcv(m1, timeframe).tail(count)

        instrument = to_instrument(symbol)
        url = f"{self._base_url}/v3/instruments/{instrument}/candles"
        params = {
            "granularity": granularity,
            "count": count,
            "price": "M",
        }
        try:
            response = requests.get(
                url, headers=self._headers(), params=params, timeout=self._timeout
            )
        except requests.RequestException as exc:
            logger.warning(
                "OANDA candles request failed for {} {}: {}", symbol, timeframe.value, exc
            )
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("time")

        if response.status_code >= 400:
            logger.warning(
                "OANDA candles HTTP {} for {} {}: {}",
                response.status_code,
                symbol,
                timeframe.value,
                response.text[:200],
            )
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("time")

        return self._parse_candles(response.json())

    def fetch_ohlcv_range(
        self,
        symbol: str,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """Fetch candles between ``start`` and ``end`` (UTC)."""
        granularity = OANDA_GRANULARITY.get(timeframe)
        if granularity is None:
            m1 = self.fetch_ohlcv_range(symbol, Timeframe.M1, start, end)
            if m1.empty:
                return m1
            return resample_ohlcv(m1, timeframe)

        instrument = to_instrument(symbol)
        url = f"{self._base_url}/v3/instruments/{instrument}/candles"
        params = {
            "granularity": granularity,
            "from": start.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "to": end.strftime("%Y-%m-%dT%H:%M:%S.000000000Z"),
            "price": "M",
        }
        try:
            response = requests.get(
                url, headers=self._headers(), params=params, timeout=self._timeout
            )
        except requests.RequestException as exc:
            logger.warning("OANDA range request failed: {}", exc)
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("time")

        if response.status_code >= 400:
            logger.warning("OANDA range HTTP {}: {}", response.status_code, response.text[:200])
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("time")

        return self._parse_candles(response.json())

    @staticmethod
    def _parse_candles(payload: dict) -> pd.DataFrame:
        candles = payload.get("candles") or []
        rows: list[dict] = []
        for candle in candles:
            if not candle.get("complete", True):
                continue
            mid = candle.get("mid") or {}
            rows.append(
                {
                    "time": candle["time"],
                    "open": float(mid.get("o", 0)),
                    "high": float(mid.get("h", 0)),
                    "low": float(mid.get("l", 0)),
                    "close": float(mid.get("c", 0)),
                    "tick_volume": int(candle.get("volume", 0)),
                }
            )
        if not rows:
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("time")

        df = pd.DataFrame(rows)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df.set_index("time")
