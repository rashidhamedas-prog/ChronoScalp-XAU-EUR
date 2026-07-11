# Architecture

## Goals, in priority order

1. **Capital preservation** over win-rate maximization. Every module upstream
   of `execution/` can veto a trade (filters, risk sizing); nothing downstream
   of a `Signal` can increase risk beyond what `risk/position_sizing.py`
   computed.
2. **Determinism and testability.** Strategy/risk logic is pure functions
   over pandas DataFrames wherever possible, so it can be unit-tested and
   backtested without a live broker connection.
3. **Broker-agnostic core.** See "Broker abstraction" below — this is the fix
   for the Linux-VPS-vs-MT5-Windows-only conflict in the original brief.

## Data flow

```
MT5 terminal / REST feed
        │  (data/mt5_connector.py)
        ▼
 OHLCV DataFrames, per symbol × timeframe (M1/M3/M5/M10)
        │  (indicators/technical.py, smc/structure.py)
        ▼
 Enriched DataFrames (EMA/RSI/MACD/BB/ATR + swing structure, order blocks, FVGs)
        │  (strategy/multi_timeframe.py)
        ▼
 Trend alignment check (M10+M5) → entry trigger (M3+M1) → Signal
        │  (filters/session_filter.py, filters/news_filter.py)
        ▼
 Session window + news blackout gate (veto only, never generates signals)
        │  (risk/position_sizing.py)
        ▼
 Position size, SL, TP computed from account equity + ATR-based stop
        │  (execution/broker.py → mt5_broker.py | paper_broker.py)
        ▼
 Order placement, breakeven-at-1R, trailing stop management
```

The same pipeline runs in `backtest/engine.py` (fed historical bars instead of
live ticks) and `main.py` (fed live/polled bars) — this is why strategy code
must stay broker- and mode-agnostic.

## Broker abstraction

`execution/broker.py` defines:

```python
class Broker(Protocol):
    def connect(self) -> bool: ...
    def get_balance(self) -> float: ...
    def get_open_positions(self, symbol: str | None = None) -> list[Position]: ...
    def place_order(self, signal: Signal, volume: float) -> Position: ...
    def modify_sl_tp(self, ticket: int, sl: float, tp: float) -> bool: ...
    def close_position(self, ticket: int) -> TradeResult: ...
```

Implementations:

- **`mt5_broker.py`** — wraps the `MetaTrader5` pip package. **Windows-only**
  (the package has no Linux/macOS build; it talks to a local MT5 terminal
  process). Deploy this on a Windows VPS located near your broker's servers
  (London/NY, per the session windows in `config/settings.yaml`).
- **`paper_broker.py`** — in-memory simulated broker with realistic spread
  and slippage assumptions pulled from `config/symbols.yaml`. Runs anywhere,
  including this Linux dev sandbox. Use for dry-runs and CI.
- **Documented, not yet implemented: an OANDA v20 REST broker** — cross
  platform (pure HTTPS/WebSocket), Docker/Linux-native, would let you deploy
  on a Linux VPS exactly as the original brief wanted, without a Windows
  terminal in the loop. This is the recommended Phase-2 addition if
  Linux-native live deployment matters more than MT5-specific brokers.

Pick one live deployment target; the pipeline above the broker layer is
identical either way.

## Win-rate expectations (why the risk model is fixed, not tunable)

1-minute to 10-minute timeframes are dominated by market noise. A realistic,
sustainable edge for a rules-based bot in this regime is **55–65% win rate**,
not 90%+. This system is designed to be profitable at 60% win rate with a
1:1.5+ R:R and 1% max risk per trade — the math:

```
EV per trade = (0.60 × 1.5R) − (0.40 × 1R) = 0.90R − 0.40R = +0.50R expectancy
```

This is why `config/settings.yaml → risk.max_risk_per_trade_pct` and
`risk.min_reward_risk_ratio` are treated as fixed constraints throughout the
codebase (see `CLAUDE.md` / `.cursor/rules/project.mdc`) rather than
parameters to optimize away.

## Multi-timeframe alignment logic

- **M10 + M5**: EMA(50) slope + price position, and RSI(14) regime, determine
  `TrendDirection` (bullish / bearish / neutral). Trades are only permitted
  when M10 and M5 agree.
- **M3 + M1**: Bollinger Band mean-reversion-in-trend + MACD crossover confirm
  the actual entry trigger, filtered by the SMC layer (order block / FVG /
  liquidity sweep context) when `strategy.use_smc_confluence: true` in
  `config/settings.yaml`.

## SMC (Smart Money Concepts) layer

`smc/structure.py` implements, from raw OHLCV, without external dependencies:

- Swing high/low detection (fractal-based).
- Market structure shift detection (break of structure / change of character).
- Order block identification (last opposite-direction candle before an
  impulsive move).
- Fair Value Gap (FVG) detection (3-candle imbalance).
- Liquidity sweep detection (wick beyond a prior swing point followed by
  rejection).

This is a real, testable implementation of the "advanced technique" section
of the original brief — not a placeholder — but it is intentionally simpler
than a full SMC engine; treat it as Phase 5/6 extension surface.

## ML setup-scoring (Phase 6, stub)

`strategy/multi_timeframe.py` exposes a `score_setup_probability()` hook that
currently returns a neutral 0.5 confidence. The intended extension (see
`docs/ROADMAP.md` Phase 6) is a `scikit-learn`/`xgboost` classifier trained on
backtest-labeled setups (features: indicator state + SMC context at signal
time; label: whether the trade hit TP before SL). Do not wire this into live
trading until it has its own backtest validation — see the non-negotiable
rules in `CLAUDE.md`.
