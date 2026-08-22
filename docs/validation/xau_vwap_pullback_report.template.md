# xau_vwap_pullback validation report (template)

Fill this only from broker-native runs. Every metric below is **UNKNOWN**
until a numbered trial writes a real value. Do not copy guessed PF / WR / DSR.

- Strategy: `xau_vwap_pullback`
- Status: **not live-ready**
- Config: `enabled: false`, `shadow_only: true`
- Broker / symbol / account: UNKNOWN
- Date range: UNKNOWN
- Folds (walk-forward): UNKNOWN
- Trial count: UNKNOWN

## Metrics (all UNKNOWN)

| Metric | Value |
|---|---|
| Trade count | UNKNOWN |
| Expectancy (R) | UNKNOWN |
| Profit factor (net) | UNKNOWN |
| Max drawdown | UNKNOWN |
| Sharpe / Sortino | UNKNOWN |
| DSR | UNKNOWN |
| PBO | UNKNOWN |
| Avg spread / slippage / commission | UNKNOWN |

## Gates

- [ ] 2-year broker-native M1 with spread
- [ ] Walk-forward + untouched test
- [ ] 1.5× cost stress
- [ ] Demo forward test (8 weeks / 100+ trades)
- [ ] Independent reviewer + security sign-off
- [ ] Do **not** enable live until the boxes above are evidence
