# Risk Disclaimer

This repository provides software for researching and executing automated
trading strategies on leveraged instruments (Gold / XAUUSD, EURUSD, and
related crosses). Read this in full before connecting any real trading
account.

## No financial advice

Nothing in this codebase, its documentation, comments, or generated signals
constitutes financial, investment, or trading advice. It is engineering
scaffolding for a personal automated-trading research project.

## Leveraged products are high risk

CFDs and margined FX/metals trading involve a high risk of losing money
rapidly due to leverage. A significant percentage of retail accounts lose
money trading these products. Only trade with capital you can afford to lose
in full.

## Backtest and paper results are not guarantees

- Backtests are subject to look-ahead bias, overfitting, and unrealistic fill
  assumptions unless carefully controlled for (this project uses historical
  spread/slippage modeling in `backtest/engine.py`, but no simulation is
  perfect).
- Paper-trading results can still diverge from live results due to latency,
  requotes, partial fills, and broker-specific execution behavior.
- Past performance, simulated or real, does not guarantee future results.

## Operational requirements before going live

1. Run the strategy in **backtest** mode across at least 2 years of data.
2. Run in **paper** mode against a live data feed for a minimum of 2–4 weeks.
3. Confirm the spread filter, session filter, and news filter are active and
   correctly configured for your broker's actual spread/swap behavior.
4. Start live trading at the minimum position size your broker allows, and
   only scale up after confirming live execution matches paper behavior.
5. Never disable the daily loss limit or per-trade risk cap
   (`config/settings.yaml → risk`) to "catch up" after a losing streak.

## Your responsibility

You are solely responsible for the configuration, deployment, monitoring, and
consequences of running this software against a real brokerage account. The
authors and contributors accept no liability for financial losses incurred
through its use.
