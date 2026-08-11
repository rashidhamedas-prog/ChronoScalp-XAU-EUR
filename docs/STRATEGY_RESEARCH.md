# Strategy Research Notes

Working notes for ChronoScalp strategy redesign and validation. Live enablement
still requires broker-native walk-forward / out-of-sample / cost-stress evidence
and intact 1% per-trade / 3% daily risk ceilings.

## Mistake Memory

Deterministic “learn from mistakes” veto (not ML). Losing setups are fingerprinted
as `{symbol}|{strategy}|{session}|{direction}|{setup_reason_bucket}` and stored
under `state_dir/lessons_{mode}.json`. When the same fingerprint repeats within
`cooldown_minutes` at least `max_repeats` times, new entries with that fingerprint
are skipped (`mistake_memory` skip reason).

Configured under `risk.mistake_memory` in `config/settings.yaml`. This gate does
not loosen risk ceilings and does not authorize live trading by itself.
