"""Per-user desktop home seeding. No Windows installer is executed here."""

from __future__ import annotations

from pathlib import Path

from chronoscalp.platform.desktop import prepare_desktop_home


def test_prepare_desktop_home_seeds_env_as_no_and_does_not_overwrite(
    tmp_path: Path, monkeypatch
) -> None:
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "settings.yaml").write_text("symbols: []\n", encoding="utf-8")
    example = tmp_path / ".env.example"
    example.write_text("CHRONOSCALP_CONFIRM_LIVE=yes\nMT5_LOGIN=0\n", encoding="utf-8")
    home = tmp_path / "home"
    monkeypatch.setenv("CHRONOSCALP_HOME", str(home))
    monkeypatch.setenv("CHRONOSCALP_CONFIG_DIR", str(home / "config"))

    first = prepare_desktop_home(bundled, example, home=home)
    assert first == home
    assert (home / "config" / "settings.yaml").is_file()
    env_text = (home / ".env").read_text(encoding="utf-8")
    assert "CHRONOSCALP_CONFIRM_LIVE=no" in env_text
    assert "CHRONOSCALP_CONFIRM_LIVE=yes" not in env_text

    (home / ".env").write_text("CHRONOSCALP_CONFIRM_LIVE=yes\n", encoding="utf-8")
    (home / "config" / "settings.yaml").write_text("symbols: [XAUUSD]\n", encoding="utf-8")
    prepare_desktop_home(bundled, example, home=home)
    assert (home / ".env").read_text(encoding="utf-8") == "CHRONOSCALP_CONFIRM_LIVE=yes\n"
    assert "XAUUSD" in (home / "config" / "settings.yaml").read_text(encoding="utf-8")
