"""ChronoScalp control-panel visual theme (Streamlit CSS).

Design intent: dark OLED fintech ops console — dense, high-contrast status
colors, subtle glass cards. Inspired by Magic UI / Aceternity motion language
but implemented in Streamlit (those libs are React-only).

Accessibility (WCAG 2.2 AA): body/widget text must stay light on --cs-bg.
Streamlit defaults to light-theme textColor when theme.base is unset; pair
this CSS with `.streamlit/config.toml` (`base = "dark"`) and keep the
label/radio/caption overrides below as a hard failsafe.
"""

from __future__ import annotations

# Semantic tokens — also mirrored in `.streamlit/config.toml` and
# `assets/chronoscalp-theme.css` (21st.dev publish candidate).
CS_BG = "#020617"
CS_SURFACE = "#0b1220"
CS_SURFACE_2 = "#111827"
CS_TEXT = "#e2e8f0"
CS_MUTED = "#cbd5e1"  # slate-300: ≥4.5:1 on CS_BG for captions/labels
CS_ACCENT = "#34d399"
CS_ACCENT_2 = "#38bdf8"


def panel_theme_css(*, rtl: bool = True) -> str:
    """Return injected <style> for the SaaS control panel."""
    direction = "rtl" if rtl else "ltr"
    text_align = "right" if rtl else "left"
    return f"""
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Sora:wght@500;600;700&family=Vazirmatn:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --cs-bg: {CS_BG};
    --cs-surface: {CS_SURFACE};
    --cs-surface-2: {CS_SURFACE_2};
    --cs-border: rgba(148, 163, 184, 0.28);
    --cs-text: {CS_TEXT};
    --cs-muted: {CS_MUTED};
    --cs-accent: {CS_ACCENT};
    --cs-accent-2: {CS_ACCENT_2};
    --cs-danger: #f87171;
    --cs-warn: #fbbf24;
    --cs-glow: 0 0 0 1px rgba(52, 211, 153, 0.15), 0 12px 40px rgba(2, 6, 23, 0.65);
    /* Override Streamlit theme vars when light base bleeds through */
    --text-color: {CS_TEXT};
    --secondary-text-color: {CS_MUTED};
    --text-color-faded: {CS_MUTED};
  }}

  html, body, [data-testid="stAppViewContainer"],
  [data-testid="stAppViewContainer"] p,
  [data-testid="stAppViewContainer"] span,
  [data-testid="stMarkdownContainer"],
  [data-testid="stMarkdownContainer"] p,
  [data-testid="stMarkdownContainer"] span,
  [data-testid="stWidgetLabel"],
  [data-testid="stWidgetLabel"] p,
  [data-testid="stWidgetLabel"] span,
  label, .stMarkdown, .stCaption, .stText {{
    color: var(--cs-text) !important;
  }}

  html, body, [data-testid="stAppViewContainer"] {{
    background: radial-gradient(1200px 600px at 10% -10%, #0b1b2e 0%, transparent 55%),
                radial-gradient(900px 500px at 100% 0%, #06281f 0%, transparent 45%),
                var(--cs-bg) !important;
    font-family: "Vazirmatn", "IBM Plex Sans", "Segoe UI", Tahoma, sans-serif !important;
  }}

  [data-testid="stHeader"] {{ background: transparent !important; }}
  [data-testid="stToolbar"] {{ visibility: hidden; height: 0; }}

  section.main > div {{
    direction: {direction};
    text-align: {text_align};
    padding-top: 0.5rem;
  }}
  code, pre, .stCode, [data-testid="stCode"] {{
    direction: ltr !important;
    text-align: left !important;
  }}

  /* Widget labels, radio/checkbox option text, captions — failsafe contrast */
  [data-testid="stWidgetLabel"],
  [data-testid="stWidgetLabel"] *,
  .stRadio label,
  .stRadio [data-testid="stMarkdownContainer"],
  .stRadio [data-testid="stMarkdownContainer"] p,
  .stRadio [data-testid="stMarkdownContainer"] span,
  .stCheckbox label,
  .stCheckbox [data-testid="stMarkdownContainer"],
  .stSelectbox label,
  .stMultiSelect label,
  .stTextInput label,
  .stNumberInput label,
  .stTextArea label,
  div[data-baseweb="radio"] label,
  div[data-baseweb="checkbox"] label,
  [data-testid="stCaptionContainer"],
  [data-testid="stCaptionContainer"] p,
  [data-testid="stCaptionContainer"] span,
  .stCaption, .stCaption p, .stCaption span {{
    color: var(--cs-text) !important;
    opacity: 1 !important;
    -webkit-text-fill-color: var(--cs-text) !important;
  }}

  /* Muted helper copy still needs AA on OLED black */
  [data-testid="stCaptionContainer"],
  .stCaption, .stCaption p {{
    color: var(--cs-muted) !important;
    -webkit-text-fill-color: var(--cs-muted) !important;
  }}

  /* BaseWeb select / dropdown menus */
  div[data-baseweb="select"] *,
  ul[role="listbox"] li,
  [data-baseweb="menu"] li,
  [data-baseweb="popover"] * {{
    color: var(--cs-text) !important;
  }}

  [data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #07111f 0%, #050b14 100%) !important;
    border-inline-end: 1px solid var(--cs-border);
  }}
  [data-testid="stSidebar"] > div:first-child {{
    direction: {direction};
    text-align: {text_align};
  }}
  [data-testid="stSidebar"] .stMarkdown h1 {{
    font-family: Sora, "Vazirmatn", "IBM Plex Sans", sans-serif !important;
    font-size: 1.35rem !important;
    letter-spacing: 0.02em;
    background: linear-gradient(90deg, #34d399, #38bdf8);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent !important;
    color: transparent !important;
    margin-bottom: 0.15rem !important;
  }}
  [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
  [data-testid="stSidebar"] .stCaption {{
    color: var(--cs-muted) !important;
    -webkit-text-fill-color: var(--cs-muted) !important;
  }}
  [data-testid="stSidebar"] .stButton > button {{
    color: var(--cs-text) !important;
  }}

  div[data-testid="stMetric"] {{
    background: linear-gradient(145deg, rgba(17,24,39,0.92), rgba(11,18,32,0.88));
    border: 1px solid var(--cs-border);
    border-radius: 16px;
    padding: 0.85rem 1rem;
    box-shadow: var(--cs-glow);
    transition: border-color 180ms ease, transform 180ms ease;
  }}
  div[data-testid="stMetric"]:hover {{
    border-color: rgba(52, 211, 153, 0.45);
    transform: translateY(-1px);
  }}
  div[data-testid="stMetric"] label,
  div[data-testid="stMetric"] [data-testid="stMetricLabel"],
  div[data-testid="stMetric"] [data-testid="stMetricLabel"] * {{
    color: var(--cs-muted) !important;
    -webkit-text-fill-color: var(--cs-muted) !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }}
  div[data-testid="stMetric"] [data-testid="stMetricValue"] {{
    font-family: Sora, "Vazirmatn", "IBM Plex Sans", sans-serif !important;
    color: var(--cs-text) !important;
    -webkit-text-fill-color: var(--cs-text) !important;
    font-weight: 600 !important;
  }}

  .stButton > button {{
    border-radius: 12px !important;
    border: 1px solid var(--cs-border) !important;
    background: rgba(15, 23, 42, 0.95) !important;
    color: var(--cs-text) !important;
    -webkit-text-fill-color: var(--cs-text) !important;
    font-weight: 600 !important;
    transition: all 180ms ease !important;
  }}
  .stButton > button:hover {{
    border-color: rgba(56, 189, 248, 0.55) !important;
    box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.2);
  }}
  .stButton > button[kind="primary"] {{
    background: linear-gradient(135deg, #059669, #0ea5e9) !important;
    border: none !important;
    color: #041016 !important;
    -webkit-text-fill-color: #041016 !important;
  }}

  .stTextInput input, .stSelectbox div[data-baseweb="select"] > div,
  .stNumberInput input, textarea {{
    background: #0b1220 !important;
    border-radius: 10px !important;
    border-color: var(--cs-border) !important;
    color: var(--cs-text) !important;
    -webkit-text-fill-color: var(--cs-text) !important;
  }}
  .stTextInput input::placeholder,
  textarea::placeholder {{
    color: var(--cs-muted) !important;
    opacity: 0.85 !important;
  }}

  .cs-hero {{
    position: relative;
    overflow: hidden;
    border-radius: 22px;
    padding: 1.6rem 1.8rem;
    margin-bottom: 1.25rem;
    border: 1px solid var(--cs-border);
    background:
      linear-gradient(120deg, rgba(52,211,153,0.12), transparent 40%),
      linear-gradient(300deg, rgba(56,189,248,0.10), transparent 35%),
      rgba(11, 18, 32, 0.92);
    box-shadow: var(--cs-glow);
  }}
  .cs-hero::after {{
    content: "";
    position: absolute;
    inset: auto -20% -60% 40%;
    height: 180px;
    background: radial-gradient(circle, rgba(52,211,153,0.25), transparent 70%);
    pointer-events: none;
  }}
  .cs-hero h1 {{
    font-family: Sora, "Vazirmatn", sans-serif;
    font-size: 1.85rem;
    margin: 0 0 0.35rem 0;
    color: #f8fafc;
    -webkit-text-fill-color: #f8fafc;
  }}
  .cs-hero p {{
    margin: 0;
    color: var(--cs-muted);
    -webkit-text-fill-color: var(--cs-muted);
    max-width: 52rem;
    line-height: 1.55;
  }}
  .cs-badge {{
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    margin-bottom: 0.75rem;
    padding: 0.25rem 0.7rem;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: #a7f3d0;
    -webkit-text-fill-color: #a7f3d0;
    background: rgba(16, 185, 129, 0.12);
    border: 1px solid rgba(52, 211, 153, 0.35);
  }}
  .cs-steps {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.85rem;
    margin: 1rem 0 0.5rem;
  }}
  .cs-step {{
    border-radius: 16px;
    padding: 1rem;
    background: rgba(15, 23, 42, 0.75);
    border: 1px solid var(--cs-border);
  }}
  .cs-step strong {{
    display: block;
    font-family: Sora, "Vazirmatn", sans-serif;
    margin-bottom: 0.35rem;
    color: #f1f5f9;
    -webkit-text-fill-color: #f1f5f9;
  }}
  .cs-step span {{
    color: var(--cs-muted);
    -webkit-text-fill-color: var(--cs-muted);
    font-size: 0.9rem;
  }}
  @media (max-width: 900px) {{
    .cs-steps {{ grid-template-columns: 1fr; }}
  }}

  @media (prefers-reduced-motion: reduce) {{
    div[data-testid="stMetric"],
    .stButton > button {{
      transition: none !important;
    }}
    div[data-testid="stMetric"]:hover {{
      transform: none;
    }}
  }}

  hr {{ border-color: var(--cs-border) !important; }}
  .stAlert {{ border-radius: 14px !important; }}
</style>
"""


def hero_html(*, title: str, subtitle: str, badge: str) -> str:
    """Top-of-page hero band."""
    return f"""
<div class="cs-hero">
  <div class="cs-badge">{badge}</div>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</div>
"""


def steps_html(items: list[tuple[str, str]]) -> str:
    """Three-column onboarding steps."""
    cards = "".join(
        f'<div class="cs-step"><strong>{title}</strong><span>{body}</span></div>'
        for title, body in items
    )
    return f'<div class="cs-steps">{cards}</div>'


def relative_luminance(hex_color: str) -> float:
    """WCAG relative luminance for a #RRGGBB color."""
    raw = hex_color.lstrip("#")
    if len(raw) != 6:
        raise ValueError(f"Expected #RRGGBB, got {hex_color!r}")
    channels = [int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (_lin(c) for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two #RRGGBB colors."""
    l1 = relative_luminance(fg)
    l2 = relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)
