from __future__ import annotations

from types import SimpleNamespace

from chronoscalp.execution.paper_broker import PaperBroker
from chronoscalp.orchestration.bootstrap import create_broker


def _settings(*, broker: str = "paper", data_source: str = "mt5") -> SimpleNamespace:
    return SimpleNamespace(
        execution={
            "broker": broker,
            "data_source": data_source,
            "magic_number": 1,
            "slippage_pips": 0.5,
        },
        backtest={"initial_balance": 10_000},
        symbols_raw={},
        secrets=SimpleNamespace(
            mt5_login=1,
            mt5_password="x",
            mt5_server="Demo",
            mt5_terminal_path="",
            oanda_api_token="t",
            oanda_account_id="a",
        ),
        raw={"oanda": {"environment": "practice", "timeout_seconds": 15}},
    )


def test_paper_mode_uses_paper_even_when_broker_is_mt5() -> None:
    broker = create_broker(_settings(broker="mt5"), mode="paper", connector=object())
    assert isinstance(broker, PaperBroker)


def test_live_mode_ignores_overlay_paper_and_uses_mt5(monkeypatch) -> None:
    captured: dict = {}

    class FakeMT5:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("chronoscalp.orchestration.bootstrap.MT5Broker", FakeMT5)
    broker = create_broker(
        _settings(broker="paper", data_source="mt5"), mode="live", connector="conn"
    )
    assert isinstance(broker, FakeMT5)
    assert captured["connector"] == "conn"
    assert captured["magic"] == 1


def test_live_mode_paper_overlay_with_oanda_data_uses_oanda(monkeypatch) -> None:
    class FakeOanda:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr("chronoscalp.orchestration.bootstrap.OANDABroker", FakeOanda)
    broker = create_broker(
        _settings(broker="paper", data_source="oanda"),
        mode="live",
        connector=object(),
    )
    assert isinstance(broker, FakeOanda)
