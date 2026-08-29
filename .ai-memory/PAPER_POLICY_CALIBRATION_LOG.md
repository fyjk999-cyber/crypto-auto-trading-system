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
## 2026-08-29T18:30Z (Phase G window 3)
- Runtime: OK; Coverage: registry 2029 (runtime fixed-universe; Phase C/D pending)
- Funnel: LLM 15 / decisions 138 (0L/4S/134NT=97.1%) / fills 1 / FILLED 2 / rejects 0 / episodes 55
- PnL: RPNL 12h -0.3939 unchanged; open 22
- ACTION: HOLD
- Changes: none
- Reason: quiet window (1 fill); NO_TRADE 97.1% natural 47 - market has no edge claim, NOT a bug; SHORT-side activity continues on perp. LOW_SAMPLE_SIZE still applies to policy params (3 windows < 15 completed episodes total)
- Expected effect: none; continue baseline accumulation
- Next review: 2026-08-29T19:00Z
## 2026-08-29T19:00Z (Phase G window 4)
- Runtime: OK; Coverage: registry 2029 (runtime fixed-universe; Phase C/D pending)
- Funnel: LLM 11 / decisions 146 (2L/1S/143NT=97.9%) / fills 3 / FILLED 2 / rejects 0 / episodes 55 (+1 ADA TIME_STOP LOSS)
- PnL: RPNL 12h -0.3939 unchanged; open 24
- ACTION: HOLD
- Changes: none
- Reason: ADA round-trip within 5min (SELL 0.2007 -> BUY 0.2009) is a direction flip not re-entry churn; episode attribution clean (TIME_STOP). 4 windows cumulative still LOW_SAMPLE_SIZE; no repeated-mistake pattern
- Expected effect: none; watch ADA flip frequency - if it recurs 2+ consecutive windows, consider CONTRACT via cooldown +60s (bounded)
- Next review: 2026-08-29T19:30Z

## 2026-08-29T19:30Z (Phase G window 5)
- Runtime: OK; Coverage: registry 2029 (runtime fixed-universe; Phase C/D pending)
- Funnel: LLM 11 / decisions 138 (3L/2S/133NT=96.4%) / fills 7 across 7 symbols / FILLED 7 / rejects 0 / episodes 58 (+3)
- PnL: RPNL 12h -0.3939 unchanged; open 25
- ACTION: HOLD
- Changes: none
- Reason: highest-quality window so far - 7-symbol diversity, mixed spot/perp, mixed directions, no re-entry churn (ADA flip did NOT recur -> no CONTRACT trigger), episode attribution flowing. NO_TRADE 96.4% natural
- Expected effect: none; window-4 ADA trigger cleared; continue baseline
- Next review: 2026-08-29T20:00Z

## 2026-08-29T20:00Z (Phase G window 6)
- Runtime: OK; Coverage: registry 2029 (runtime fixed-universe; Phase C/D pending)
- Funnel: LLM 13 / decisions 145 (1L/3S/141NT=97.2%) / fills 7 / FILLED 7 / rejects 0 / episodes 63 (+5, biggest window)
- PnL: RPNL 12h 13 rows cum -0.7172 (BTC_PERP cycle settled -0.0936); open 22
- ACTION: HOLD
- Changes: none
- Reason: activity elevated but orderly - 6 distinct symbols, mixed directions, 3 clean TIME_STOP episodes; BTC_PERP entry+exit within 5min at real prices = natural short cycle, watch but not yet churn (1 occurrence). LOW_SAMPLE_SIZE for params persists
- Expected effect: none; if 5-min perp cycles recur 2+ windows -> CONTRACT analysis cooldown +60s
- Next review: 2026-08-29T20:30Z

## 2026-08-29T20:30Z (Phase G window 7)
- Runtime: OK; Coverage: registry 2029 (runtime fixed-universe; Phase C/D pending)
- Funnel: LLM 13 / decisions 145 (3L/2S/140NT=96.6%) / fills 5 / FILLED n-a / rejects 0 / episodes 65 (+2)
- PnL: RPNL 12h -0.7172 unchanged; open 23
- ACTION: HOLD
- Changes: none
- Reason: orderly window; 5 symbols; direction-flip re-entries (XRP) now 2 total but non-consecutive windows -> trigger NOT met (needs 2+ consecutive). LOW_SAMPLE_SIZE persists
- Expected effect: none; watch XRP/ADA flip pattern next window
- Next review: 2026-08-29T21:00Z

## 2026-08-29T21:00Z (Phase G window 8)
- Runtime: OK; Coverage: registry 2029 (runtime fixed-universe; Phase C/D pending)
- Funnel: LLM 18 / decisions 142 (2L/2S/138NT=97.2%) / fills 4 / rejects 0 / episodes 69 (+4)
- PnL: RPNL 12h -0.7172 unchanged; open 23
- ACTION: HOLD (with active CONTRACT trigger pending)
- Changes: none
- Reason: direction-flip re-entries now in 3rd window (SOL 20:20 SELL -> 20:32 BUY; TRX 19:45 SELL -> 20:40 BUY = 55min gap, not intra-5min churn). Pattern is cross-window re-entry at market-reasonable prices - characteristic of TIME_STOP 4h cycle recycling. NOT yet abnormal turnover (fills/hour ~8, fees tiny). If window 9 shows intra-5min flip churn -> CONTRACT: cooldown 240->300s (bounded +60s, sec.26)
- Expected effect: none now; pre-staged CONTRACT decision for next window
- Next review: 2026-08-29T21:30Z

## 2026-08-29T21:30Z (Phase G window 9) - ACTION: CONTRACT
- Runtime: OK; Coverage: registry 2029; Funnel: LLM 15 / decisions 145 (3L/2S/140NT) / fills 8 (16/h pace vs ~10 baseline) / episodes 74 (+5, accelerating) / rejects 0 / errors 0
- PnL: RPNL 12h -0.7172; open 21
- ACTION: CONTRACT (bounded single step, sec.26/48)
- Changes: per_symbol_analysis_cooldown_s 240 -> 300 (+60s, within MAX_CHANGE +-60s) via .env ENTRY_COOLDOWN_SECONDS (config-level, sec.65 compliant; takes effect at next runtime start, which requires Supervisor authorization)
- Reason (multi-factor sec.28, NOT fill-count alone): DOGE direction-flip 6min08s round-trip (21:22 SELL -> 21:28 BUY) = short holding noise; consecutive flip windows (8,9); turnover 16/h vs baseline; fees rising; LOSS count accelerating (41 vs 28 WIN). Pre-staged trigger from window 8 marginally met (6min vs strict 5min) - combined with turnover/holding factors per sec.48
- Expected effect: slower re-entry cadence (~17% fewer decision slots per symbol/hour); should reduce flip churn while NOT gating AI authority (cooldown is temporal safety, not a quant gate)
- ROLLBACK PLAN (sec.64): if window 10-11 show flip churn gone AND healthy fills continue, restore 240. If NO_TRADE rate spikes >99% with no structural reason, restore 240 immediately
- Next review: 2026-08-29T22:00Z

## 2026-08-29T22:00Z (Phase G window 10)
- Runtime: OK; Coverage: registry 2029; Funnel: LLM 10 / decisions 145 (2L/3S/140NT) / fills 6 / rejects 0 / episodes 78 (+4)
- PnL: RPNL 12h improved -0.7172 -> -0.2611 (16 rows; FIL/ZEC closes positive); open 19
- ACTION: HOLD (staged cooldown 300 remains; rollback review next window)
- Changes: none (staged CONTRACT from window 9 NOT yet effective - runtime unchanged)
- Reason: churn pattern CLEARED organically (no intra-5min flips; HYPE/ZEC/FIL re-entries are 2-4h TIME_STOP cycles = healthy lifecycle); PnL improved; LLM calls down (10 vs 15). Per sec.64 do not one-way push: keep 300 staged one more window; if window 11 also clean -> rollback to 240 (cancel staged) to avoid unnecessary tightening
- Expected effect: none now; decision on staged-300 rollback at window 11
- Next review: 2026-08-29T22:30Z
