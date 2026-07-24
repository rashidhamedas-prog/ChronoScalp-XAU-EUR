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


def ticks_to_ohlcv(ticks: pd.DataFrame, seconds: int) -> pd.DataFrame:
    """Aggregate MT5 tick rows into OHLCV bars of ``seconds`` length.

    Expects columns ``time`` (datetime index or column) and price via
    ``last`` / ``bid`` / ``ask``. Volume uses ``volume`` when present.
    """
    if ticks is None or len(ticks) == 0:
        return pd.DataFrame(columns=["open", "high", "low", "close", "tick_volume"])

    df = ticks.copy()
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("ticks must be indexed by time")

    if "last" in df.columns and df["last"].fillna(0).ne(0).any():
        price = df["last"].replace(0, pd.NA).ffill()
    elif "bid" in df.columns and "ask" in df.columns:
        price = (df["bid"].astype(float) + df["ask"].astype(float)) / 2.0
    elif "bid" in df.columns:
        price = df["bid"].astype(float)
    else:
        raise ValueError("ticks need last or bid/ask columns")

    price = price.ffill().dropna()
    out = pd.DataFrame({"price": price}, index=price.index)
    if "volume" in df.columns:
        out["tick_volume"] = df["volume"].reindex(out.index).fillna(1).astype(float)
    else:
        out["tick_volume"] = 1.0

    rule = f"{int(seconds)}s"
    agg = out.resample(rule).agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        tick_volume=("tick_volume", "sum"),
    )
    return agg.dropna(subset=["open", "high", "low", "close"])


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
        """Fetch the most recent `count` completed bars for symbol/timeframe.

        Sub-minute frames (``S15`` / ``S30``) are aggregated from ticks because
        the MetaTrader5 Python API has no native second-bar timeframes.
        """
        _require_windows()
        import MetaTrader5 as mt5

        if timeframe.is_subminute:
            return self._fetch_ohlcv_from_ticks(symbol, timeframe, count)

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

    def _fetch_ohlcv_from_ticks(
        self, symbol: str, timeframe: Timeframe, count: int
    ) -> pd.DataFrame:
        """Build sub-minute OHLCV from recent ticks."""
        from datetime import timedelta

        import MetaTrader5 as mt5

        seconds = timeframe.seconds
        # Extra headroom: thin markets / gaps need more wall-clock than count*seconds
        window = timedelta(seconds=max(seconds * count * 3, 900))
        from datetime import UTC as _UTC

        end = datetime.now(tz=_UTC)
        start = end - window
        ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            logger.warning(
                "No ticks for {} {}: {}", symbol, timeframe.value, mt5.last_error()
            )
            return pd.DataFrame(columns=OHLCV_COLUMNS).set_index(
                pd.DatetimeIndex([], tz="UTC", name="time")
            )

        tdf = pd.DataFrame(ticks)
        # MT5 tick time is seconds; time_msc is milliseconds
        if "time_msc" in tdf.columns:
            tdf["time"] = pd.to_datetime(tdf["time_msc"], unit="ms", utc=True)
        else:
            tdf["time"] = pd.to_datetime(tdf["time"], unit="s", utc=True)
        bars = ticks_to_ohlcv(tdf, seconds)
        if bars.empty:
            return bars
        return bars.tail(count)

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
    rule = f"{target.seconds}s" if target.is_subminute else f"{target.minutes}min"
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    if "tick_volume" in df.columns:
        agg["tick_volume"] = "sum"
    if "spread" in df.columns:
        agg["spread"] = "mean"
    return df.resample(rule).agg(agg).dropna(subset=["open", "high", "low", "close"])
