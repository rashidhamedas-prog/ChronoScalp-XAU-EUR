# Architecture

## System boundaries

Market data adapters feed broker-agnostic strategy, filter, risk, and execution layers. Live broker boundaries are MT5 and OANDA; paper/backtest execution is local. Verified in `docs/ARCHITECTURE.md` and `src/chronoscalp/execution/broker.py`.

## Components and data flow

OHLCV/ticks -> indicators and market structure -> multi-timeframe strategy -> session/news/risk gates -> broker execution -> trade journal. Backtest and live paths are intended to share signal and position logic.

## Invariants and constraints

- Maximum risk per trade is 1%; minimum reward/risk is 1.5; daily loss limit is 3% unless explicitly disabled by the operator.
- Live mode requires explicit confirmation and must remain disabled for redesigned strategies until out-of-sample and forward-demo gates pass.
- Strategy evaluation must be symbol-specific and cost-aware; XAUUSD and EURUSD cannot share unverified parameters.
- Journal, backtest, and broker accounting must use consistent price, pip, contract, commission, and timestamp semantics.

## Architecture decisions

Record material decisions as dated entries with context, decision, alternatives, consequences, and rollback/migration notes.

### 2026-08-09 — Evidence-first redesign

- Context: available live journal shows abnormal sizing and invalid R multiples, while the latest logged XAUUSD backtest produced zero trades.
- Decision: freeze live enablement, audit accounting/sizing first, then evaluate separate scalp and M15-H1 candidates with walk-forward and cost stress tests.
- Alternatives rejected: selecting a GitHub strategy by claimed win rate or optimizing only in-sample win rate.
- Consequences: implementation may replace existing strategy rules, but risk ceilings and broker abstraction remain invariant.
- Rollback: retain the current branch history; disable new strategy flags and revert configuration to paper-only if any validation gate fails.
