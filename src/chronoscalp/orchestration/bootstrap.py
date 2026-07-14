"""Runtime wiring — select data connector and broker for the deployment target.

Netherlands / Linux VPS  →  ``data_source=oanda``, ``broker=oanda``
Windows + MT5            →  ``data_source=mt5``, ``broker=mt5`` (live) or ``paper``
"""

from __future__ import annotations

from typing import Any

from chronoscalp.config import Settings
from chronoscalp.data.mt5_connector import MT5Connector
from chronoscalp.data.oanda_connector import OANDAConnector
from chronoscalp.execution.mt5_broker import MT5Broker
from chronoscalp.execution.mt5_utils import CHRONOSCALP_MAGIC
from chronoscalp.execution.oanda_broker import OANDABroker
from chronoscalp.execution.paper_broker import PaperBroker


def resolve_data_source(settings: Settings) -> str:
    """Return ``mt5`` or ``oanda`` based on config (``auto`` picks from broker)."""
    broker_kind = settings.execution.get("broker", "paper")
    data_source = settings.execution.get("data_source", "auto")
    if data_source == "auto":
        return "oanda" if broker_kind == "oanda" else "mt5"
    return str(data_source)


def create_data_connector(settings: Settings) -> MT5Connector | OANDAConnector:
    """Instantiate the market-data connector for this deployment."""
    source = resolve_data_source(settings)
    if source == "oanda":
        oanda_cfg = settings.raw.get("oanda", {})
        return OANDAConnector(
            api_token=settings.secrets.oanda_api_token,
            account_id=settings.secrets.oanda_account_id,
            environment=oanda_cfg.get("environment", "practice"),
            timeout_seconds=float(oanda_cfg.get("timeout_seconds", 15)),
        )
    return MT5Connector(
        login=settings.secrets.mt5_login,
        password=settings.secrets.mt5_password,
        server=settings.secrets.mt5_server,
        terminal_path=settings.secrets.mt5_terminal_path,
    )


def create_broker(
    settings: Settings,
    mode: str,
    connector: Any,
) -> PaperBroker | MT5Broker | OANDABroker:
    """Instantiate the execution broker for ``mode`` (paper or live)."""
    broker_kind = settings.execution.get("broker", "paper")
    magic = int(settings.execution.get("magic_number", CHRONOSCALP_MAGIC))
    slippage = float(settings.execution.get("slippage_pips", 0.5))
    starting = float(settings.backtest.get("initial_balance", 10_000))

    if mode == "paper" or broker_kind == "paper":
        return PaperBroker(
            symbols_cfg=settings.symbols_raw,
            starting_balance=starting,
            slippage_pips=slippage,
        )

    if broker_kind == "oanda":
        oanda_cfg = settings.raw.get("oanda", {})
        return OANDABroker(
            api_token=settings.secrets.oanda_api_token,
            account_id=settings.secrets.oanda_account_id,
            environment=oanda_cfg.get("environment", "practice"),
            symbols_cfg=settings.symbols_raw,
            timeout_seconds=float(oanda_cfg.get("timeout_seconds", 15)),
        )

    if broker_kind == "mt5":
        return MT5Broker(
            connector=connector,
            login=settings.secrets.mt5_login,
            password=settings.secrets.mt5_password,
            server=settings.secrets.mt5_server,
            terminal_path=settings.secrets.mt5_terminal_path,
            symbols_cfg=settings.symbols_raw,
            magic=magic,
        )

    raise ValueError(f"Unknown execution.broker: {broker_kind!r} (expected paper, mt5, oanda)")


def connector_label(connector: Any) -> str:
    if isinstance(connector, OANDAConnector):
        return "OANDA"
    if isinstance(connector, MT5Connector):
        return "MT5"
    return type(connector).__name__
