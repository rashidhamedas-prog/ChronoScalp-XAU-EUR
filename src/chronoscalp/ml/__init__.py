"""ML setup-scoring pipeline for Phase 6.

Trains a classifier on backtest-labeled setups (features at signal time;
label = TP hit before SL). The model is an *additional* confidence gate —
never the sole signal source (see CLAUDE.md).
"""
