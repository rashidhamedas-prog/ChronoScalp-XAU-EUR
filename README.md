# ChronoScalp XAU/EUR

**Multi-timeframe research bot for Gold (XAUUSD) and EUR/USD**, installed on your own Windows PC and checked only during the London and New York sessions.

> ⚠️ **Risk Disclaimer** — Trading leveraged FX/metals instruments carries a high risk of loss. This repository is a research/engineering scaffold, not financial advice, and does not guarantee profitability or any win rate. The honest review is [docs/BAZRASI_SADEGHANE_FA.md](docs/BAZRASI_SADEGHANE_FA.md). Always validate on a **demo account** before risking real capital. Read [docs/RISK_DISCLAIMER.md](docs/RISK_DISCLAIMER.md) in full before running anything live.

---

## 1. What this project actually is

The bot analyzes the symbols you select (the intended book is XAUUSD and EURUSD, including broker-native names). It requires higher-timeframe alignment before a lower-timeframe entry, and it only evaluates new entries inside the London and New York windows in `config/settings.yaml` (clocks: `Europe/London` and `America/New_York`). It pauses around configured high-impact news.

No win-rate target is a measured result. Older notes used 55–65% as an unverified design hypothesis; that figure is not evidence. Risk stays capped at 1% per trade and at least 1:1.5 reward:risk. Ultra-short scalping stays off. See [docs/BAZRASI_SADEGHANE_FA.md](docs/BAZRASI_SADEGHANE_FA.md).

## 2. A design conflict we resolved up front

The supported install is a Windows PC with MetaTrader 5 already logged in. The official `MetaTrader5` package talks to that local terminal and has no Linux build. A VPS is optional history, not the setup path: [docs/DEPLOY_NL_VPS.md](docs/DEPLOY_NL_VPS.md) and [docs/VPS_TROUBLESHOOTING_FA.md](docs/VPS_TROUBLESHOOTING_FA.md).

- `execution/broker.py` defines a `Broker` **interface**.
- `execution/mt5_broker.py` implements **MetaTrader5** on Windows.
- `execution/oanda_broker.py` remains an optional REST adapter. It is not part of the desktop installer.
- `execution/paper_broker.py` simulates fills and is the default.

Build and install: [docs/WINDOWS_INSTALL_FA.md](docs/WINDOWS_INSTALL_FA.md). The installer is per-user (`%LOCALAPPDATA%\ChronoScalp`), stores `.env` in `%APPDATA%\ChronoScalp`, registers an interactive logon task, and leaves `CHRONOSCALP_CONFIRM_LIVE=no`.

## 3. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Fast iteration, best-in-class quant/ML ecosystem |
| Broker (default) | `MetaTrader5` (Windows) | Matches most retail gold/FX brokers, direct order/position API |
| Indicators | `pandas-ta` + hand-rolled fallback | No native/TA-Lib compile step required |
| Config | `pydantic-settings` + YAML | Typed, validated, environment-overridable |
| Scheduling | `APScheduler` | Reliable timeframe-aligned polling loop |
| Logging | `loguru` + optional `sentry-sdk` | Structured logs, remote error tracking |
| Backtesting | Custom event-driven engine (`backtest/engine.py`) | Freqtrade/Jesse are crypto/CCXT-oriented and don't model MT5 spread/swap mechanics well; a small purpose-built engine is more correct for this use case |
| ML (Phase 6) | `scikit-learn` / `xgboost` | Setup-probability scoring, optional and off by default |
| Packaging | PyInstaller onedir + Inno Setup | Per-user Windows install. See `scripts/windows/build_installer.ps1` |
| CI | GitHub Actions | Lint (ruff) + tests (pytest) on every push |

## 4. Project structure

```
ChronoScalp-XAU-EUR/
├── CLAUDE.md                 # Instructions for Claude Code sessions
├── AGENTS.md                 # Shared guidance for coding agents
├── .cursor/rules/project.mdc # Instructions for Cursor
├── config/                   # settings.yaml, symbols.yaml
├── docs/                     # architecture, roadmap, risk disclaimer, VPS ops
├── src/chronoscalp/
│   ├── config.py             # typed settings loader
│   ├── logging_setup.py
│   ├── data/                 # MT5 connector, OHLCV fetch/resample
│   ├── indicators/           # EMA, RSI, MACD, Bollinger, ATR
│   ├── smc/                  # swing structure, order blocks, FVG, liquidity sweeps
│   ├── filters/              # trading-session + news-blackout filters
│   ├── strategy/             # multi-timeframe alignment + signal generation
│   ├── risk/                 # position sizing, Kelly-capped, breakeven/trailing
│   ├── execution/            # Broker interface + MT5 / paper implementations
│   ├── backtest/             # event-driven backtest engine
│   └── main.py               # live/paper trading orchestration loop
├── scripts/                  # run_live.py, run_backtest.py, fetch_history.py
├── tests/                    # pytest unit tests
└── docker/                   # Dockerfile, docker-compose.yml
```

## 5. Getting started

Windows install (primary): build `dist\ChronoScalp-Setup.exe` with `scripts\windows\build_installer.ps1` on a Windows machine, or download the `ChronoScalp-Setup` artifact from the `Windows installer` GitHub Actions workflow. Steps, MT5, the logon task, stop, and uninstall are in [docs/WINDOWS_INSTALL_FA.md](docs/WINDOWS_INSTALL_FA.md). Persian walkthrough: [docs/RAHNAMA_FA.md](docs/RAHNAMA_FA.md).

Source checkout (tests and research on any OS):

```bash
git clone https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git
cd ChronoScalp-XAU-EUR
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # placeholders only; live confirmation stays no
```

### Run a backtest (works on any OS, no broker needed)

```bash
python scripts/fetch_history.py --symbol XAUUSD --timeframe M5 --years 2
python scripts/run_backtest.py --symbol XAUUSD --from 2024-01-01 --to 2026-01-01
```

### Paper trade (simulated fills, live data feed)

```bash
python scripts/run_live.py --mode paper
```

### Go live (Windows host with MT5 terminal running + logged in)

```bash
python scripts/run_live.py --mode live
```

`--mode live` refuses to start unless `CHRONOSCALP_CONFIRM_LIVE=yes` is set in `.env` — a deliberate friction point so nobody flips to real money by accident.

**نصب ویندوز:** [docs/WINDOWS_INSTALL_FA.md](docs/WINDOWS_INSTALL_FA.md)  
**بررسی صادقانه (بدون وعدهٔ سود):** [docs/BAZRASI_SADEGHANE_FA.md](docs/BAZRASI_SADEGHANE_FA.md)  
**راهنمای فارسی:** [docs/RAHNAMA_FA.md](docs/RAHNAMA_FA.md)  
**آرشیو VPS (اختیاری، مسیر اصلی نیست):** [docs/VPS_TROUBLESHOOTING_FA.md](docs/VPS_TROUBLESHOOTING_FA.md) · [docs/DEPLOY_NL_VPS.md](docs/DEPLOY_NL_VPS.md)  
**فروش لایسنس + IB:** [docs/FOROOSH_FA.md](docs/FOROOSH_FA.md)

### Control panel (recommended for end users)

```bash
streamlit run scripts/app.py
# or double-click scripts/start.bat on Windows
```

Flow: activate license → connect broker (OANDA/MT5) → start paper bot.

## 6. Configuration

All strategy/risk parameters live in [`config/settings.yaml`](config/settings.yaml) (git-tracked, safe to version) — timeframes, session windows, risk %, spread caps, R:R minimum. Secrets (MT5 login, Sentry DSN, news API key) live only in `.env` (git-ignored) — see [`.env.example`](.env.example).

## 7. Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for the full Phase 1–6 breakdown (data pipeline → multi-timeframe features → session/news filtering → risk management → backtesting/optimization → SMC + ML enhancement). Phases 1–4 are implemented in this scaffold; Phase 5 (hyperparameter optimization) and Phase 6 (ML setup-scoring) are stubbed with clear extension points.

## 8. Testing

```bash
pytest -q                 # unit tests
ruff check src tests      # lint
black --check src tests   # formatting
```

CI runs the same checks on every push via `.github/workflows/ci.yml`.

## 9. Building this with Claude Code / Cursor

This repo ships **`CLAUDE.md`** and **`.cursor/rules/project.mdc`** specifically so that Claude Code and Cursor share the same project context, conventions, and current build status — open the repo in either tool and continue from [docs/ROADMAP.md](docs/ROADMAP.md) without re-explaining the architecture.

## License

MIT — see [LICENSE](LICENSE).
