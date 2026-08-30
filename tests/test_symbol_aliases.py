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


def test_higher_trend_names_uses_the_ultra_scalp_set_when_asked(monkeypatch, tmp_path):
    """Ultra-scalp has its own frames, so reporting must not name the wrong one."""
    (tmp_path / "settings.yaml").write_text(
        "\n".join(
            [
                "symbols: [XAUUSD]",
                "timeframes:",
                "  higher_trend: [H1, M15]",
                "  entry_trigger: [M1]",
                "  ultra_scalp:",
                "    higher_trend: [M5, M1]",
                "    entry_trigger: [S15]",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "symbols.yaml").write_text("XAUUSD: {}\n", encoding="utf-8")
    monkeypatch.setattr("chronoscalp.config.CONFIG_DIR", tmp_path)

    settings = Settings()
    assert settings.higher_trend_names() == ["H1", "M15"]
    assert settings.higher_trend_names(ultra_scalp=True) == ["M5", "M1"]


def test_higher_trend_names_is_empty_when_unconfigured(monkeypatch, tmp_path):
    (tmp_path / "settings.yaml").write_text("symbols: [XAUUSD]\n", encoding="utf-8")
    (tmp_path / "symbols.yaml").write_text("XAUUSD: {}\n", encoding="utf-8")
    monkeypatch.setattr("chronoscalp.config.CONFIG_DIR", tmp_path)

    settings = Settings()
    assert settings.higher_trend_names() == []
    # Ultra-scalp keeps its documented default rather than reporting nothing.
    assert settings.higher_trend_names(ultra_scalp=True) == ["M15", "M5"]


def test_symbol_casing_normalizes_to_symbols_yaml_key(monkeypatch, tmp_path):
    settings_yaml = tmp_path / "settings.yaml"
    settings_yaml.write_text(
        "\n".join(
            [
                "symbols:",
                "  - XAUUSD_O",
                "  - EURUSD_O",
                "broker_symbol_aliases: {}",
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
    symbols_yaml.write_text("XAUUSD_o: {}\nEURUSD_o: {}\n", encoding="utf-8")

    monkeypatch.setattr("chronoscalp.config.CONFIG_DIR", tmp_path)
    settings = Settings()
    assert settings.symbols == ["XAUUSD_o", "EURUSD_o"]
