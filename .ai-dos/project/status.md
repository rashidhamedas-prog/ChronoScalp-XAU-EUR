# Project Status

- Last verified: 2026-09-03T20:50:00Z
- TASK-005: live books are Delta + news straddle for XAUUSD and EURUSD.
  M1 ultra_scalp is off the catalog after the 2026-08-27..09-03 demo week
  (46 CS_ultra_scalp tickets, MT5 −$6,947). Delta was +$510 / 7 tickets.
  Overlay `always_on_24h` and `daily_loss_limit_enabled: false` were live
  defects. YAML calendar covers NFP 2026-09-04 12:30 UTC; Finnhub 403 keeps
  YAML. Overlay `enabled_strategies` is ignored while catalogs are on.
- Live 2026-09-03 (VPS 45.90.98.99, demo 55625500, HEAD was `9305bc9`):
  two `run_live.py` processes; bot skips `delta:regime_neutral` /
  `scalp:weak_impulse` / `low_rvol`. Operator magic=0 gold bursts
  (Iran 13:00–18:00, 6–25 lots) are outside 1% risk — not copied.
- Primary branch: main. Implementer branch `ai/TASK-005-delta-news-straddle`.
- Invariants: 1%/3% intact; live heat 3%; `CHRONOSCALP_CONFIRM_LIVE` unchanged.
