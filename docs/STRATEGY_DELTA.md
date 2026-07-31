# Strategy Delta (XAUUSD / EURUSD)

Delta is an explainable, multi-timeframe, cost-aware strategy. It is a research
strategy, not a promise of profit or a claim that one rule set is universally
"best". Its edge must be demonstrated separately for each broker, symbol, and
market regime using out-of-sample and forward demo results.

## Decision stack

1. **M15 + M5 regime:** both frames must agree on price/EMA50 location, EMA
   slope, and a non-extreme RSI regime. Delta rejects extended price (>2.5 ATR
   from EMA) instead of chasing it.
2. **M1 location/event:** price must sweep and reclaim the recent 12-bar range,
   or break it and successfully retest it.
3. **M1 confirmation:** a directional close with body at least 45% of candle
   range and relative volume >=1.15.
4. **Execution economics:** the stop is beyond local structure plus 0.2 ATR,
   never tighter than 0.8 ATR or 2x current spread, and never wider than 2.5
   ATR. Target defaults to 1.8R (hard floor remains 1.5R).
5. **Existing bot gates still apply:** session, high-impact news, spread,
   stale-data, portfolio/daily loss, three-strikes, and 1% maximum risk.

## Why these constraints

- Bid/ask spread is a direct execution cost and liquidity changes through the
  day; CME's liquidity material explicitly treats spread and depth as core
  execution-quality measures: <https://www.cmegroup.com/education/courses/trading-and-analysis/liquidity-and-immediacy>.
- Gold trades nearly around the clock and has meaningful liquidity outside US
  hours, so Delta does not encode the false assumption that Asia is always
  illiquid. ChronoScalp's configured London/New York windows remain the initial
  conservative deployment choice: <https://www.cmegroup.com/education/articles-and-reports/trading-comex-gold-and-silver>.
- Macroeconomic releases can abruptly change volatility and liquidity. Delta
  therefore relies on the existing high-impact-news veto rather than attempting
  to predict release outcomes. Official calendars should be the operational
  source of truth: <https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm>
  and <https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html>.

## Configuration

`config/settings.yaml -> strategy.delta` contains only defensible execution and
signal-quality parameters. Do not optimize the 1% risk ceiling or 1.5R floor.
Tune XAUUSD and EURUSD separately; never select parameters on the same period
used to report performance.

## Required validation before live use

1. Import at least two years of broker-native M1 data including spread.
2. Use walk-forward splits (train/tune, validation, untouched test).
3. Report net profit factor, expectancy in R, max drawdown, trade count,
   exposure, and results by symbol/session/setup—not win rate alone.
4. Run Monte Carlo trade-order and cost stress tests (spread/slippage >=1.5x).
5. Forward-test on demo for at least 100 trades per symbol and four weeks.
6. Keep `CHRONOSCALP_CONFIRM_LIVE` disabled until all gates pass.

## Data needed from the operator

- Broker name and exact symbol specifications/screenshots for XAUUSD and EURUSD.
- Broker-native M1 history with spread, ideally tick data.
- Commission, swap, minimum stop distance, lot step, and typical/worst spread.
- Demo journal exports after each 25–50 trades.
