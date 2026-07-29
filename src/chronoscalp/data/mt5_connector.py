"""MetaTrader5 data connector + CSV-backed historical storage.

IMPORTANT: the `MetaTrader5` pip package only runs on Windows (it talks to a
local MT5 terminal process via DLL — there is no Linux/macOS build). This
module raises a clear RuntimeError rather than a confusing ImportError if
imported on an unsupported platform, and CSV helpers below work everywhere so
backtesting/paper-trading never require MT5 to be installed at all.
See docs/ARCHITECTURE.md "Broker abstraction".
"""

from __future__ import annotations

import contextlib
import platform
import time
from datetime import UTC, datetime, timedelta
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
    Timeframe.M15: "TIMEFRAME_M15",
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
        price = df["last"].mask(df["last"] == 0).ffill()
    elif "bid" in df.columns and "ask" in df.columns:
        price = (df["bid"].astype(float) + df["ask"].astype(float)) / 2.0
    elif "bid" in df.columns:
        price = df["bid"].astype(float)
    else:
        raise ValueError("ticks need last or bid/ask columns")

    price = price.ffill().dropna()
    out = pd.DataFrame({"price": price}, index=price.index)
    # MT5 CFD/crypto ticks often have volume=0; count ticks so RVOL is meaningful.
    if "volume" in df.columns:
        vol = df["volume"].reindex(out.index).astype(float)
        if float(vol.fillna(0).sum()) <= 0:
            out["tick_volume"] = 1.0
        else:
            out["tick_volume"] = vol.fillna(1.0)
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
        self._last_warn_at: dict[str, float] = {}
        self._consecutive_empty = 0
        self.last_successful_fetch_at: datetime | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        """Attach to (or launch) the MT5 terminal and log in.

        On a Windows VPS the named-pipe handshake often needs well over the
        package default of 60s, and a hung already-running ``terminal64`` can
        return ``-10003`` forever. We retry with credentials embedded in
        ``initialize`` so the package can spawn a fresh terminal in-process.
        """
        _require_windows()
        import MetaTrader5 as mt5  # noqa: N813 - matches upstream package name

        # MetaTrader5 docs: timeout is milliseconds. Some builds still print
        # "60 sec" in the error string even when a larger timeout is used.
        timeout_ms = 180_000
        attempts: list[dict[str, object]] = []
        base: dict[str, object] = {
            "timeout": timeout_ms,
            "login": int(self._login),
            "password": self._password,
            "server": self._server,
        }
        if self._terminal_path:
            with_path = dict(base)
            with_path["path"] = self._terminal_path
            attempts.append(with_path)
        attempts.append(dict(base))  # auto-discover / launch
        if self._terminal_path:
            # Last resort: path only, then separate login() (older package path).
            attempts.append({"timeout": timeout_ms, "path": self._terminal_path})

        last_err: object = None
        for i, kwargs in enumerate(attempts, start=1):
            with contextlib.suppress(Exception):
                mt5.shutdown()
            if i > 1:
                time.sleep(3)

            logger.info(
                "Connecting to MT5 attempt={}/{} path={} timeout_ms={} ...",
                i,
                len(attempts),
                kwargs.get("path") or "(auto)",
                timeout_ms,
            )
            t0 = time.monotonic()
            ok = bool(mt5.initialize(**kwargs))
            elapsed = time.monotonic() - t0
            if not ok:
                last_err = mt5.last_error()
                logger.error(
                    "MT5 initialize() failed attempt={} elapsed={:.1f}s err={}",
                    i,
                    elapsed,
                    last_err,
                )
                continue

            # If credentials were not passed into initialize, login explicitly.
            if "login" not in kwargs:
                authorized = mt5.login(self._login, password=self._password, server=self._server)
                if not authorized:
                    last_err = mt5.last_error()
                    logger.error("MT5 login() failed: {}", last_err)
                    mt5.shutdown()
                    continue

            info = mt5.account_info()
            if info is None:
                last_err = mt5.last_error()
                logger.error("MT5 account_info() is None after initialize: {}", last_err)
                mt5.shutdown()
                continue

            self._connected = True
            self._consecutive_empty = 0
            logger.info(
                "Connected to MT5 server={} login={} elapsed={:.1f}s",
                self._server,
                self._login,
                elapsed,
            )
            return True

        logger.error("MT5 connect exhausted retries; last_error={}", last_err)
        self._connected = False
        return False

    def shutdown(self) -> None:
        if not self._connected:
            return
        _require_windows()
        import MetaTrader5 as mt5

        mt5.shutdown()
        self._connected = False

    def ensure_connected(self) -> bool:
        """Probe terminal health and reconnect when the IPC link is dead."""
        _require_windows()
        import MetaTrader5 as mt5

        if self._connected:
            info = mt5.terminal_info()
            if info is not None:
                return True
            logger.warning("MT5 terminal_info() is None — reconnecting")
            self._connected = False

        return self.connect()

    def _warn_rate_limited(self, key: str, message: str, *args: object) -> None:
        now = time.monotonic()
        last = self._last_warn_at.get(key, 0.0)
        if now - last < 60.0:
            return
        self._last_warn_at[key] = now
        logger.warning(message, *args)

    def _ensure_symbol(self, symbol: str) -> bool:
        import MetaTrader5 as mt5

        info = mt5.symbol_info(symbol)
        if info is None:
            # Some brokers use a suffix (e.g. XAUUSD.m) — still try select.
            if not mt5.symbol_select(symbol, True):
                self._warn_rate_limited(
                    f"sym_missing:{symbol}",
                    "MT5 symbol unavailable for {} (not in Market Watch / wrong name) — last_error={}",
                    symbol,
                    mt5.last_error(),
                )
                return False
            info = mt5.symbol_info(symbol)
            if info is None:
                return False
        if not info.visible:
            mt5.symbol_select(symbol, True)
        return True

    def _empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(columns=OHLCV_COLUMNS).set_index(
            pd.DatetimeIndex([], tz="UTC", name="time")
        )

    @staticmethod
    def _drop_forming_bar(df: pd.DataFrame) -> pd.DataFrame:
        """Drop the incomplete current candle so callers see completed bars only."""
        if len(df) >= 2:
            return df.iloc[:-1].copy()
        return df

    def _mark_empty(self) -> None:
        self._consecutive_empty += 1
        if self._consecutive_empty >= 8:
            logger.warning(
                "MT5 returned empty data {} times — forcing reconnect",
                self._consecutive_empty,
            )
            self._connected = False
            self.ensure_connected()
            self._consecutive_empty = 0

    def _mark_success(self) -> None:
        self._consecutive_empty = 0
        self.last_successful_fetch_at = datetime.now(tz=UTC)

    def fetch_ohlcv(self, symbol: str, timeframe: Timeframe, count: int = 500) -> pd.DataFrame:
        """Fetch the most recent `count` completed bars for symbol/timeframe.

        Sub-minute frames (``S15`` / ``S30``) are aggregated from ticks because
        the MetaTrader5 Python API has no native second-bar timeframes.
        Retries once after reconnect on terminal IPC failures.
        """
        _require_windows()
        if not self.ensure_connected():
            return self._empty_frame()

        for attempt in range(2):
            df = self._fetch_ohlcv_once(symbol, timeframe, count)
            if not df.empty:
                self._mark_success()
                return df
            if attempt == 0:
                self._warn_rate_limited(
                    f"retry:{symbol}:{timeframe.value}",
                    "Empty {} {} — reconnect + retry",
                    symbol,
                    timeframe.value,
                )
                self._connected = False
                if not self.ensure_connected():
                    break
        self._mark_empty()
        return self._empty_frame()

    def _fetch_ohlcv_once(self, symbol: str, timeframe: Timeframe, count: int) -> pd.DataFrame:
        import MetaTrader5 as mt5

        if not self._ensure_symbol(symbol):
            return self._empty_frame()

        if timeframe.is_subminute:
            return self._fetch_ohlcv_from_ticks(symbol, timeframe, count)

        mt5_timeframe = getattr(mt5, _TIMEFRAME_MAP_NAMES[timeframe])
        rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, count)
        if rates is None or len(rates) == 0:
            self._warn_rate_limited(
                f"rates:{symbol}:{timeframe.value}",
                "No rates returned for {} {}: {}",
                symbol,
                timeframe.value,
                mt5.last_error(),
            )
            return self._empty_frame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df = df.set_index("time")
        df = df[
            [
                c
                for c in ["open", "high", "low", "close", "tick_volume", "spread"]
                if c in df.columns
            ]
        ]
        # Position 0 from copy_rates_from_pos is the still-forming candle —
        # drop it so strategy iloc[-1] matches the bar-close gate.
        return self._drop_forming_bar(df)

    def _broker_time_now(self, symbol: str) -> datetime:
        """Latest tick timestamp for ``symbol`` (server-stamped pseudo-UTC).

        MT5 stamps ticks/bars in *broker server time* exposed as raw epoch
        seconds. Using real UTC wall clock for ``copy_ticks_range`` on a
        UTC+N broker silently drops the newest N hours of ticks, so signals
        get built from stale prices. Anchor range queries to the broker's own
        clock instead.
        """
        import MetaTrader5 as mt5

        tick = mt5.symbol_info_tick(symbol)
        if tick is not None:
            msc = int(getattr(tick, "time_msc", 0) or 0)
            if msc > 0:
                return datetime.fromtimestamp(msc / 1000.0, tz=UTC)
            sec = int(getattr(tick, "time", 0) or 0)
            if sec > 0:
                return datetime.fromtimestamp(sec, tz=UTC)
        return datetime.now(tz=UTC)

    def _fetch_ohlcv_from_ticks(
        self, symbol: str, timeframe: Timeframe, count: int
    ) -> pd.DataFrame:
        """Build sub-minute OHLCV from recent ticks."""
        import MetaTrader5 as mt5

        seconds = timeframe.seconds
        # Extra headroom: thin markets / gaps need more wall-clock than count*seconds
        window = timedelta(seconds=max(seconds * count * 3, 900))
        end = self._broker_time_now(symbol) + timedelta(seconds=2)
        start = end - window
        ticks = mt5.copy_ticks_range(symbol, start, end, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            self._warn_rate_limited(
                f"ticks:{symbol}:{timeframe.value}",
                "No ticks for {} {}: {}",
                symbol,
                timeframe.value,
                mt5.last_error(),
            )
            return self._empty_frame()

        tdf = pd.DataFrame(ticks)
        # MT5 tick time is seconds; time_msc is milliseconds
        if "time_msc" in tdf.columns:
            tdf["time"] = pd.to_datetime(tdf["time_msc"], unit="ms", utc=True)
        else:
            tdf["time"] = pd.to_datetime(tdf["time"], unit="s", utc=True)
        bars = ticks_to_ohlcv(tdf, seconds)
        if bars.empty:
            return bars
        # Last tick-bucket is incomplete until the period rolls — drop it.
        return self._drop_forming_bar(bars.tail(count + 1))

    def fetch_ohlcv_range(
        self, symbol: str, timeframe: Timeframe, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Fetch all completed bars for symbol/timeframe between start and end
        (both UTC). Used by scripts/fetch_history.py for backtest data."""
        _require_windows()
        import MetaTrader5 as mt5

        if not self.ensure_connected():
            return self._empty_frame()
        if not self._ensure_symbol(symbol):
            return self._empty_frame()

        mt5_timeframe = getattr(mt5, _TIMEFRAME_MAP_NAMES[timeframe])
        rates = mt5.copy_rates_range(symbol, mt5_timeframe, start, end)
        if rates is None or len(rates) == 0:
            self._warn_rate_limited(
                f"range:{symbol}:{timeframe.value}",
                "No rates returned for {} {} [{} .. {}]: {}",
                symbol,
                timeframe.value,
                start,
                end,
                mt5.last_error(),
            )
            return self._empty_frame()

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

        if not self.ensure_connected() or not self._ensure_symbol(symbol):
            return None
        info = mt5.symbol_info(symbol)
        if info is None:
            return None
        return float(info.spread)

    def symbol_point(self, symbol: str) -> float | None:
        """Broker price point size (needed to convert spread points → pips)."""
        _require_windows()
        import MetaTrader5 as mt5

        if not self.ensure_connected() or not self._ensure_symbol(symbol):
            return None
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
