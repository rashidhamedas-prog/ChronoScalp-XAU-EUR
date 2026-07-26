from __future__ import annotations

from chronoscalp.config import Settings


def test_broker_symbol_aliases_resolve_litefinance_suffix(monkeypatch, tmp_path):
    settings_yaml = tmp_path / "settings.yaml"
    settings_yaml.write_text(
        "\n".join(
            [
                "symbols:",
                "  - BTCUSD",
                "  - XAUUSD",
                "  - EURUSD",
                "broker_symbol_aliases:",
                "  XAUUSD: XAUUSD_o",
                "  EURUSD: EURUSD_o",
                "strategy: {}",
                "risk: {}",
                "sessions: {}",
                "news_filter: {}",
                "indicators: {}",
                "timeframes: {}",
                "spread_filter: {}",
                "execution: {}",
                "backtest: {}",
                "resilience: {}",
                "ml: {}",
                "alerting: {}",
            ]
        ),
        encoding="utf-8",
    )
    symbols_yaml = tmp_path / "symbols.yaml"
    symbols_yaml.write_text("BTCUSD: {}\nXAUUSD_o: {}\nEURUSD_o: {}\n", encoding="utf-8")

    monkeypatch.setattr("chronoscalp.config.CONFIG_DIR", tmp_path)
    settings = Settings()
    assert settings.symbols == ["BTCUSD", "XAUUSD_o", "EURUSD_o"]
