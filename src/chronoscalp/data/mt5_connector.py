"""MetaTrader5 data connector + CSV-backed historical storage.

IMPORTANT: the `MetaTrader5` pip package only runs on Windows (it talks to a
local MT5 terminal process via DLL — there is no Linux/macOS build). This
module raises a clear RuntimeError rather than a confusing ImportError if
imported on an unsupported platform, and CSV helpers below work everywhere so
backtesting/paper-trading never require MT5 to be installed at all.
See docs/ARCHITECTURE.md "Broker abstraction".
"""

from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path

import pandas as pd

from chronoscalp.logging_setup import logger
from chronoscalp.utils.types import Timeframe

OHLCV_COLUMNS = ["time", "open", "high", "low", "close", "tick_volume", "spread"]


def _require_windows() -> None:
    if platform.system() != "Windows":
        raise RuntimeError(
            "MetaTrader5 python package is Windows-only. Run this on a Windows "
            "VPS with the MT5 terminal installed and logged in, or use "
            "execution/paper_broker.py + CSV history for development/backtesting "
            "on Linux/macOS. See docs/ARCHITECTURE.md."
        )


_TIMEFRAME_MAP_NAMES = {
    Timeframe.M1: "TIMEFRAME_M1",
    Timeframe.M3: "TIMEFRAME_M3",
    Timeframe.M5: "TIMEFRAME_M5",
    Timeframe.M10: "TIMEFRAME_M10",
}


class MT5Connector:
    """Thin wrapper around the MetaTrader5 package. All MT5 SDK calls are
    isolated to this class + execution/mt5_broker.py — nothing else in the
    codebase imports `MetaTrader5` directly (see CLAUDE.md rule #3)."""

    def __init__(self, login: int, password: str, server: str, terminal_path: str = "") -> None:
        self._login = login
        self._password = password
        self._server = server
        self._terminal_path = terminal_path
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        _require_windows()
        import MetaTrader5 as mt5  # noqa: N813 - matches upstream package name

        kwargs = {}
        if self._terminal_path:
            kwargs["path"] = self._terminal_path

        if not mt5.initialize(**kwargs):
            logger.error("MT5 initialize() failed: {}", mt5.last_error())
            return False

        authorized = mt5.login(self._login, password=self._password, server=self._server)
        if not authorized:
            logger.error("MT5 login() failed: {}", mt5.last_error())
            mt5.shutdown()
            return False

        self._connected = True
        logger.info("Connected to MT5 server={} login={}", self._server, self._login)
        return True

    def shutdown(self) -> None:
        if not self._connected:
            return
        _require_windows()
        import MetaTrader5 as mt5

        mt5.shutdown()
        self._connected = False

    def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, count: int = 500) -> pd.DataFrame:
        """Fetch the most recent `count` completed bars for symbol/timeframe."""
        _require_windows()
        import MetaTrader5 as mt5

        mt5_timeframe = getattr(mt5, _TIMEFRAME_MAP_NAMES[timeframe])
        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, count)
        if rates is None or len(rates) == 0:
            logger.warning(
                "No rates returned for {} {}: {}", symbol, timeframe.value, mt5.last_error()
            )
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("time")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[
            [
                c
                for c in ["open", "high", "low", "close", "tick_volume", "spread"]
                if c in df.columns
            ]
        ]

    def fetch_ohlcv_range(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Fetch all completed bars for symbol/timeframe between start and end
        (both UTC). Used by scripts/fetch_history.py for backtest data."""
        _require_windows()
        import MetaTrader5 as mt5

        mt5_timeframe = getattr(mt5, _TIMEFRAME_MAP_NAMES[timeframe])
        rates = mt5.copy_rates_range(symbol, mt5_timeframe, start, end)
        if rates is None or len(rates) == 0:
            logger.warning(
                "No rates returned for {} {} [{} .. {}]: {}",
                symbol,
                timeframe.value,
                start,
                end,
                mt5.last_error(),
            )
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index("time")

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        return df[
            [
                c
                for c in ["open", "high", "low", "close", "tick_volume", "spread"]
                if c in df.columns
            ]
        ]

    def current_spread_points(self, symbol: str) -> float | None:
        _require_windows()
        import MetaTrader5 as mt5

        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        return float(info.spread)

    def symbol_point(self, symbol: str) -> float | None:
        """Broker price point size (needed to convert spread points → pips)."""
        _require_windows()
        import MetaTrader5 as mt5

        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        return float(info.point)


# --------------------------------------------------------------------------
# CSV-backed historical storage — platform-independent, used by the
# backtester and by scripts/fetch_history.py.
# --------------------------------------------------------------------------


def history_csv_path(data_dir: str | Path, symbol: str, timeframe: Timeframe) -> Path:
    return Path(data_dir) / symbol / f"{timeframe.value}.csv"


def save_history_csv(
    df: pd.DataFrame, data_dir: str | Path, symbol: str, timeframe: Timeframe
) -> Path:
    path = history_csv_path(data_dir, symbol, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)
    logger.info("Saved {} bars to {}", len(df), path)
    return path


def load_history_csv(data_dir: str | Path, symbol: str, timeframe: Timeframe) -> pd.DataFrame:
    path = history_csv_path(data_dir, symbol, timeframe)
    if not path.exists():
        raise FileNotFoundError(
            f"No historical data at {path}. Run scripts/fetch_history.py first, "
            "or drop a compatible OHLCV CSV (time,open,high,low,close,tick_volume,spread) there."
        )
    df = pd.read_csv(path, parse_dates=["time"], index_col="time")
    return clean_ohlcv(df)


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Handle missing bars / bad values: forward-fill small gaps, drop rows
    that are still NaN after that, and ensure a sorted, de-duplicated index.
    """
    df = df[~df.index.duplicated(keep="last")].sort_index()
    numeric_cols = [c for c in ["open", "high", "low", "close"] if c in df.columns]
    df[numeric_cols] = df[numeric_cols].ffill(limit=3)
    df = df.dropna(subset=numeric_cols)
    return df


def resample_ohlcv(df: pd.DataFrame, target: Timeframe) -> pd.DataFrame:
    """Resample a finer-grained OHLCV DataFrame up to a coarser timeframe,
    e.g. build M5 bars from M1 data when a broker doesn't offer M5 directly."""
    rule = f"{target.minutes}min"
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "tick_volume" in df.columns:
        agg["tick_volume"] = "sum"
    if "spread" in df.columns:
        agg["spread"] = "mean"
    return df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])
