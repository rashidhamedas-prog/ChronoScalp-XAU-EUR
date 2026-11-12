"""Regression: panel dark-theme text stays readable (WCAG AA)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_panel_theme():
    path = ROOT / "scripts" / "panel_theme.py"
    spec = importlib.util.spec_from_file_location("chronoscalp_panel_theme", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def theme():
    return _load_panel_theme()


def test_body_and_muted_meet_wcag_aa_on_oled_bg(theme) -> None:
    assert theme.contrast_ratio(theme.CS_TEXT, theme.CS_BG) >= 4.5
    assert theme.contrast_ratio(theme.CS_MUTED, theme.CS_BG) >= 4.5


def test_panel_css_forces_widget_label_colors(theme) -> None:
    css = theme.panel_theme_css(rtl=True)
    assert "stWidgetLabel" in css
    assert ".stRadio label" in css
    assert "stCaptionContainer" in css
    assert "-webkit-text-fill-color: var(--cs-text)" in css
    assert "direction: rtl" in css
    assert "Vazirmatn" in css
    assert "prefers-reduced-motion" in css


def test_panel_css_ltr_mode(theme) -> None:
    css = theme.panel_theme_css(rtl=False)
    assert "direction: ltr" in css
    assert "text-align: left" in css


def test_streamlit_config_forces_dark_base(theme) -> None:
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert 'base = "dark"' in config
    assert f'textColor = "{theme.CS_TEXT}"' in config
    assert f'backgroundColor = "{theme.CS_BG}"' in config


def test_theme_export_has_light_and_dark_blocks(theme) -> None:
    theme_css = (ROOT / "assets" / "chronoscalp-theme.css").read_text(encoding="utf-8")
    assert ":root {" in theme_css
    assert ".dark {" in theme_css
    assert "--foreground:" in theme_css
    assert theme.CS_TEXT in theme_css or theme.CS_TEXT.lower() in theme_css.lower()
