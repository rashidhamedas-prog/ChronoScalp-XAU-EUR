"""Regression tests for MT5 connection churn.

Every ``connect()`` retry (attempt 2+) calls ``mt5.shutdown()`` before
``initialize()``. The first attach to a healthy terminal does not shutdown,
so panel/Telegram probes must not tear down the live IPC link.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from chronoscalp.data.mt5_connector import MT5Connector


def _fake_mt5(
    *, terminal_alive: bool, logged_in_as: int = 1
) -> tuple[SimpleNamespace, dict[str, int]]:
    calls = {"initialize": 0, "shutdown": 0}
    # The real package exposes one terminal link per process: nothing is
    # reachable until initialize() succeeds, and shutdown() tears it down.
    state = {"up": False}

    def initialize(**_kwargs: object) -> bool:
        calls["initialize"] += 1
        state["up"] = True
        return True

    def shutdown() -> None:
        calls["shutdown"] += 1
        state["up"] = False

    def terminal_info() -> SimpleNamespace | None:
        if not state["up"] or not terminal_alive:
            return None
        return SimpleNamespace(connected=True)

    def account_info() -> SimpleNamespace | None:
        return SimpleNamespace(login=logged_in_as) if state["up"] else None

    module = SimpleNamespace(
        initialize=initialize,
        shutdown=shutdown,
        login=lambda *_a, **_k: True,
        account_info=account_info,
        terminal_info=terminal_info,
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
    assert calls["shutdown"] == 0, "must not tear the link down on first attach or reuse"
    assert connector.is_connected is True


def test_fresh_connector_reuses_the_process_link() -> None:
    """The panel API and Telegram build a throwaway connector per request.

    An instance-scoped "already connected" flag is always False for those, so
    the reuse check has to look at the process-wide MetaTrader5 link instead.
    """
    module, calls = _fake_mt5(terminal_alive=True)
    with (
        patch("chronoscalp.data.mt5_connector._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": module}),
    ):
        assert _connector().connect() is True
        for _ in range(5):
            assert _connector().connect() is True

    assert calls["initialize"] == 1
    assert calls["shutdown"] == 0


def test_link_to_a_different_login_is_rebuilt() -> None:
    """Never trade on a link someone re-pointed at another account."""
    module, calls = _fake_mt5(terminal_alive=True, logged_in_as=999)
    with (
        patch("chronoscalp.data.mt5_connector._require_windows"),
        patch.dict("sys.modules", {"MetaTrader5": module}),
    ):
        assert _connector().connect() is True
        assert _connector().connect() is True

    assert calls["initialize"] == 2


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
