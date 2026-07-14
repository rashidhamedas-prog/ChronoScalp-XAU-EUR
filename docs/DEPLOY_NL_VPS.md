# Deploying ChronoScalp on a Netherlands VPS (Linux)

This guide targets an **Amsterdam / Netherlands Linux VPS** — a common choice
for forex bots because latency to **London** liquidity (your London session
window in `config/settings.yaml`) is typically **5–15 ms**.

MetaTrader5 **does not run on Linux**. For a Netherlands VPS, use the **OANDA
v20 REST broker** built into ChronoScalp instead of MT5.

---

## Recommended architecture

```
┌──────────────────────────── Netherlands VPS (Linux) ────────────────────────────┐
│  Docker or systemd                                                              │
│    └── ChronoScalp (scripts/run_live.py)                                        │
│          ├── data: OANDAConnector  (candles, pricing)                           │
│          └── live: OANDABroker     (orders, SL/TP)                              │
│  Optional: Telegram alerts, Sentry, Finnhub news API                            │
└─────────────────────────────────────────────────────────────────────────────────┘
         │ HTTPS                           │ HTTPS
         ▼                                 ▼
   OANDA v20 REST API              Finnhub / Telegram
   (practice → live)
```

**Do not** install Wine + MT5 on Linux for production — it is fragile and
unsupported by this project.

---

## 1. OANDA account setup

1. Create an OANDA account (EU entity is fine from Netherlands).
2. Open a **practice** account first: https://www.oanda.com/demo-account/
3. Generate a **v20 API token** (Manage API Access in the platform).
4. Note your **Account ID** (e.g. `101-004-1234567-001`).

Supported instruments (mapped in `execution/oanda_utils.py`):

| ChronoScalp | OANDA      |
|-------------|------------|
| XAUUSD      | XAU_USD    |
| EURUSD      | EUR_USD    |

Verify contract specs in `config/symbols.yaml` match OANDA's minimum units.

---

## 2. VPS provisioning

**Minimum:** 1 vCPU, 1 GB RAM, Ubuntu 22.04/24.04 LTS.

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git python3.11 python3.11-venv docker.io docker-compose-plugin
```

Clone and configure:

```bash
git clone https://github.com/rashidhamedas-prog/ChronoScalp-XAU-EUR.git
cd ChronoScalp-XAU-EUR
cp .env.example .env
# Edit .env — see section 3
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 3. Configuration

### `.env` (secrets)

```env
OANDA_API_TOKEN=your-v20-token
OANDA_ACCOUNT_ID=101-004-xxxxxxx-001

CHRONOSCALP_CONFIRM_LIVE=no          # keep no until paper validated
CHRONOSCALP_STOP_TRADING=no

TELEGRAM_BOT_TOKEN=...               # recommended for unattended ops
TELEGRAM_CHAT_ID=...
NEWS_API_KEY=...                     # optional Finnhub key
```

### `config/settings.yaml`

**Phase 1 — paper on Linux (OANDA data, simulated fills):**

```yaml
execution:
  broker: paper
  data_source: oanda
```

**Phase 2 — live on OANDA practice:**

```yaml
execution:
  broker: oanda
  data_source: oanda

oanda:
  environment: practice
```

**Phase 3 — live real money** (only after weeks of practice + backtest):

```yaml
oanda:
  environment: live
```

Set `CHRONOSCALP_CONFIRM_LIVE=yes` in `.env` **only** when starting live mode.

Enable alerting:

```yaml
alerting:
  enabled: true
```

---

## 4. Validate before live

```bash
# Backtest from CSV (no broker needed)
python scripts/run_backtest.py --symbol XAUUSD

# Paper loop — OANDA data, simulated orders (Linux-safe)
python scripts/run_live.py --mode paper

# After 2–4 weeks stable paper + backtest review:
# Set broker: oanda, CHRONOSCALP_CONFIRM_LIVE=yes
python scripts/run_live.py --mode live
```

Run tests locally or in CI:

```bash
pytest -q
ruff check src tests scripts
```

---

## 5. Docker (unattended)

```bash
cd docker
docker compose up chronoscalp-paper-oanda -d    # paper + OANDA data
# After validation:
docker compose up chronoscalp-live-oanda -d     # live OANDA
```

Logs: `docker compose logs -f chronoscalp-live-oanda`

**Kill switch** without SSH:

```bash
touch ../data/state/STOP_TRADING
# or set CHRONOSCALP_STOP_TRADING=yes in .env and restart
```

---

## 6. Windows + MT5 alternative

If your broker only supports MT5 (no OANDA), use a **Windows VPS near London**
instead of Netherlands Linux. Set:

```yaml
execution:
  broker: mt5
  data_source: mt5
```

---

## 7. Latency notes (Netherlands)

| Route              | Typical RTT |
|--------------------|-------------|
| Amsterdam → London | 5–15 ms     |
| Amsterdam → NY     | 80–95 ms    |

Your strategy trades **London + New York sessions** — Netherlands VPS is well
placed for the London window. NY session is acceptable for M1–M10 scalping on
OANDA's REST API (not HFT).

---

## 8. Checklist before real money

- [ ] Backtest + walk-forward (`scripts/run_optimize.py`) reviewed
- [ ] Paper mode 2–4 weeks, daily loss limit never hit unexpectedly
- [ ] Telegram alerts firing on open/close/errors
- [ ] Kill switch tested (`data/state/STOP_TRADING`)
- [ ] `max_risk_per_trade_pct: 1.0` and `min_reward_risk_ratio: 1.5` unchanged
- [ ] Practice → live OANDA only after explicit `CHRONOSCALP_CONFIRM_LIVE=yes`

See also `docs/RISK_DISCLAIMER.md` and `docs/ARCHITECTURE.md`.
