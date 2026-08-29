# PAPER POLICY CALIBRATION LOG (§60)

每 30 分钟追加:Timestamp / Window / Runtime Health / Market Coverage / Trading Funnel / PnL / Tool Usage / Current Policy / Action (EXPAND/HOLD/CONTRACT) / Changes / Reason / Expected Effect / Next Review。

## 2026-08-29T17:20Z (Phase G start, pre-baseline)
- Window: initial; Runtime: OK (PID 48151, zero restarts since 15:11Z)
- Market coverage: dynamic registry LIVE (SPOT 1383 / SWAP 458 / FUTURES 187 live); Layer-1 scan not yet wired into runtime
- Funnel (24h context): AI entries/exits flowing naturally; episodes 52 clean rows
- Policy state: defaults (LLM cadence ~60s, symbol cooldown 240s, exploration small)
- ACTION: HOLD (baseline window - no changes until funnel metrics exist)
- Reason: LOW_SAMPLE_SIZE on new policy params; establish baseline first (§29)
- Expected effect: none; next review computes first real funnel deltas

## 2026-08-29T17:30Z (first real funnel window)
- Runtime: OK (PID 48151, zero restarts); Coverage: registry 2029 instruments live (SPOT 1383/SWAP 458/FUTURES 187); runtime still on FIXED universe (Phase C/D pending)
- Funnel: observed ~20 (fixed list) / LLM calls 16 / decisions 145 (4L/1S/140 NT) / fills 7 / orders FILLED 10 / risk+exec no rejects / episodes 53
- PnL: FUTURES_RPNL 12h cum -0.3939 (12 rows); spot+perp open 19 positions
- Tool usage: n/a yet (Phase H)
- ACTION: HOLD
- Changes: none
- Reason: first window on new policy params = LOW_SAMPLE_SIZE; 96.6% NO_TRADE is natural (no market edge claim), NOT under-trading bug - fills flowing, round-trips closing
- Expected effect: baseline established; next windows watch re-entry frequency (DOGE/LINK twice each in-window - monitor, not yet abnormal) and NO_TRADE reason quality
- Next review: 2026-08-29T18:00Z

## 2026-08-29T18:00Z (Phase G window 2)
- Runtime: OK; Coverage: registry 2029 (runtime still fixed-universe; Phase C/D pending)
- Funnel: LLM 9 / decisions 145 (2L/3S/140NT=93.3%) / fills 5 / FILLED 5 / rejects 0 / episodes 54
- PnL: RPNL 12h -0.3939 unchanged (no perp closes this window); open 22
- ACTION: HOLD
- Changes: none
- Reason: stable window; NO_TRADE 93.3% still natural; fills diverse across 5 symbols incl 3 perp - no concentration, no re-entry anomaly (DOGE/LINK pattern from window 1 did not repeat)
- Expected effect: none; watch HYPE/ZEC/FIL perp exit reasons at next episode completion
- Next review: 2026-08-29T18:30Z