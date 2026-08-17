"""Regression tests for MT5 connection churn.

Every ``connect()`` attempt calls ``mt5.shutdown()`` before ``initialize()``.
Repeated callers (broker adapters, panel and Telegram status probes) therefore
used to tear down and rebuild the IPC link underneath in-flight quote fetches
and orders, which showed up on the VPS as bursts of
"Connecting to MT5 / Connected to MT5 elapsed=0.0s" pairs every poll.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from chronoscalp.data.mt5_connector import MT5Connector


def _fake_mt5(*, terminal_alive: bool) -> tuple[SimpleNamespace, dict[str, int]]:
    calls = {"initialize": 0, "shutdown": 0}

    def initialize(**_kwargs: object) -> bool:
        calls["initialize"] += 1
        return True

    def shutdown() -> None:
        calls["shutdown"] += 1

    module = SimpleNamespace(
        initialize=initialize,
        shutdown=shutdown,
        login=lambda *_a, **_k: True,
        account_info=lambda: SimpleNamespace(login=1),
        terminal_info=lambda: SimpleNamespace(connected=True) if terminal_alive else None,
        last_error=lambda: (1, "Success"),
    )
    return module, calls


def _connector() -> MT5Connector:
    return MT5Connector(login=1, password="x", server="test")


def test_repeated_connect_reuses_live_terminal_link() -> None:
    module, calls = _fake_mt5(terminal_alive=True)
    connector = _connector()
    with (
        patch("chronoscalp.data.mt5_connector._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": module}),
    ):
        assert connector.connect() is True
        for _ in range(5):
            assert connector.connect() is True

    assert calls["initialize"] == 1
    assert calls["shutdown"] == 1, "must not tear the link down once per caller"
    assert connector.is_connected is True


def test_force_rebuilds_the_link() -> None:
    module, calls = _fake_mt5(terminal_alive=True)
    connector = _connector()
    with (
        patch("chronoscalp.data.mt5_connector._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": module}),
    ):
        connector.connect()
        assert connector.connect(force=True) is True

    assert calls["initialize"] == 2


def test_dead_terminal_still_reconnects() -> None:
    module, calls = _fake_mt5(terminal_alive=False)
    connector = _connector()
    with (
        patch("chronoscalp.data.mt5_connector._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": module}),
    ):
        connector.connect()
        # terminal_info() returns None, so the cached flag must not be trusted.
        assert connector.ensure_connected() is True

    assert calls["initialize"] == 2
