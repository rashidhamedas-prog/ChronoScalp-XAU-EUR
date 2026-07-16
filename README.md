# ChronoScalp XAU/EUR

**Multi-timeframe algorithmic scalping system for Gold (XAUUSD) and EUR/USD**, built for autonomous session-based execution across the 1m / 3m / 5m / 10m timeframes.

> ⚠️ **Risk Disclaimer** — Trading leveraged FX/metals instruments carries a high risk of loss. This repository is a research/engineering scaffold, not financial advice, and does not guarantee profitability. Always validate on a **demo account** before risking real capital. Read [docs/RISK_DISCLAIMER.md](docs/RISK_DISCLAIMER.md) in full before running anything live.

---

## 1. What this project actually is

The bot analyzes XAUUSD and EURUSD (and any broker-native cross such as `XAUEUR`, configurable) across four timeframes, requires **trend alignment on the higher timeframes (M10/M5)** before allowing **entries on the lower timeframes (M3/M1)**, and only trades inside defined liquidity windows (London / New York sessions), while pausing around high-impact news.

Realistic target: **55–65% win rate**, not 90%+. Profitability comes from risk/reward discipline (≥1:1.5), strict position sizing (max 1% equity risk/trade), a hard spread filter, and consistent execution — not from a "magic" win rate. This is stated explicitly in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) so that no future prompt (human or AI) quietly regresses the risk model chasing an unrealistic win rate.

## 2. A design conflict we resolved up front

The original brief asked for **"Linux VPS near broker servers"** *and* **"MetaTrader5 Python library"**. These are incompatible as stated: the official `MetaTrader5` PyPI package only works on Windows (it talks to a local MT5 terminal via DLL, there is no Linux build). Shipping code that assumes both silently would fail the first time someone deploys to a Linux box.

We resolved it with an abstraction, not a compromise:

- `execution/broker.py` defines a `Broker` **interface** (connect, get_balance, place_order, modify_sl_tp, close_position, get_open_positions).
- `execution/mt5_broker.py` implements it against **MetaTrader5** — requires a **Windows VPS** (or a Windows box running the MT5 terminal) near the broker's servers (London/NY).
- `execution/oanda_broker.py` implements **OANDA v20 REST** — runs on **Linux VPS** (e.g. Netherlands/Amsterdam). See [docs/DEPLOY_NL_VPS.md](docs/DEPLOY_NL_VPS.md).
- `execution/paper_broker.py` is a fully working **simulated broker** — runs anywhere (including Linux), used for dry-runs, CI, and strategy validation without touching a real account.

Pick your deployment target once (Windows VPS + MT5, **or** Linux VPS + OANDA) — the strategy/risk/filter code above the broker layer does not change either way.

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
| Packaging | Docker (`docker/`) | Reproducible deployment, auto-restart |
| CI | GitHub Actions | Lint (ruff) + tests (pytest) on every push |

## 4. Project structure

```
ChronoScalp-XAU-EUR/
├── CLAUDE.md                 # Instructions for Claude Code sessions
├── .cursor/rules/project.mdc # Instructions for Cursor
├── config/                   # settings.yaml, symbols.yaml
├── docs/                     # architecture, roadmap, risk disclaimer
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

```bash
git clone https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git
cd ChronoScalp-XAU-EUR
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in MT5 credentials / API keys
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

**راهنمای فارسی قدم‌به‌قدم:** [docs/RAHNAMA_FA.md](docs/RAHNAMA_FA.md)  
**فروش لایسنس + IB:** [docs/FOROOSH_FA.md](docs/FOROOSH_FA.md)  
**VPS هلند (انگلیسی):** [docs/DEPLOY_NL_VPS.md](docs/DEPLOY_NL_VPS.md)

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
