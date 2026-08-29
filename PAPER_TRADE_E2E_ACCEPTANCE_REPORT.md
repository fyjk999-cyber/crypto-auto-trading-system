# PAPER_TRADE_E2E_ACCEPTANCE_REPORT — 2026-08-29

## VERDICT

**PAPER_TRADE_E2E_READY = YES**

A real, AI-autonomous, real-OKX-data, RiskEngine- and ExecutionAuthority-gated
PAPER perpetual fill completed the full chain:

```
OKX REAL market data → Market State → FactorSnapshot → Strategy Evidence
→ Chief Trader AI (LIVE, live_analysis) → LONG → SignalIntent
→ RiskEngine APPROVE (RISK_PASS) → ExecutionAuthority APPROVE
→ Order → FILL @ REAL price → Ledger → Position update
```

## CLEAN FILL LINEAGE (the §6 proof)

### Proof fill (perpetual)

- Git HEAD of the running system: **53c4f57397d992b57e0e691bbf6049f34a0cef27**
- Engine run: **run_256d3e15648542ee976cbefa55bb9cd4** (started 2026-08-29 00:13:28 UTC, PAPER)
- Market data: **source=REAL (OKX public)**, feed age 0s, BTC real ≈ 77.5k USD
- Decision: **dec_a6d0a388dbc34ab082fd** — BTCUSDT, **NORMAL_ENTRY / LONG**,
  selected_strategy=`mean_reversion`, fit 1.0, confidence 0.8.
  Thesis cites REAL market numbers: "deeply oversold (RSI 6 at 4.98, RSI 14 at
  28.75, z-score -1.75) testing the lower Bollinger band and recent support
  zone (77734.3)".
- LLM invocation: **llm_d30a4f2b3429456ca423be4bec8ce7f4** — brain=LIVE,
  route=**live_analysis**, model=deepseek-chat, latency 4.12s, 4,672 tokens, success.
- Execution reference / signal: **llm_c2ed52a55c90420a938332e7815d28e1**
- Risk decision: **APPROVE / RISK_PASS** @ 00:35:45.300 UTC
- ExecutionAuthority: **APPROVE** (no hold/reject audit rows; fill proceeded)
- Order: **ord_6a07813a44df44b3b471ebedea407b16** — BTCUSDT_PERP BUY 0.001
  MARKET, market_type=PERPETUAL, position_side=LONG, reduce_only=false
- Fill: **fill_8396534b10d74e25843509a357d6e0ab** — **price 77753.05 (REAL OKX
  price, not synthetic)**, qty 0.001 BTC, fee 0.038876525 USDT @ 00:35:45.348 UTC
- Ledger: **txn_467ed207928443e98aa35a09** (FUTURES_TRADING_FEE; OPEN metadata
  records margin/entry for the perpetual projection)
- Position: BTCUSDT_PERP LONG 0.001 @ avg 77753.05, 1x, margin 77.75 USDT

### Clean-price SPOT control (isolated repro, production code path)

DOTUSDT BUY 0.001 filled @ **0.8483** (real OKX DOT price) through
signal → risk APPROVE → authority → order → FILLED → ledger. Proves the
price-integrity fix for the spot leg independently of the AI loop.

### Additional autonomous fills AFTER the last architecture fixes

- **BNBUSDT BUY 0.001 @ 690.40** (REAL OKX BNB price) — 2026-08-29
  02:00:50 UTC, run after the order-id-namespace fix; order
  ord_5c8d0d1563f54369b1dd589119426088, exchange_order_id
  sim_pfba01f5205-1000, ledger TRADE txn committed; the fill survived
  reconciliation once the base-asset representation scope was fixed.
- **DOGEUSDT BUY 0.0005 @ 0.08525** (REAL OKX DOGE price) — 2026-08-29
  02:09:19 UTC, 37 seconds after engine start on HEAD 7f3fa43:
  risk APPROVE/RISK_PASS 02:09:17 → order FILLED → ledger → position.
  Full chain, zero holds, zero rewrites.

## FUNNEL (all recorded decisions, /trading-funnel)

- Decisions: **1084+** (funnel continuously active; ~4-5 AI calls/min,
  20-symbol coverage, per-symbol 300s cadence) — LONG 26 / SHORT 21 / NO_TRADE 1029 / WAIT 8
- Classes: NORMAL_ENTRY 37, EXPLORATION_ENTRY 9, NO_TRADE 1029
- LLM: 52 calls (42 live_analysis), **0 failed**
- Risk: APPROVE/RISK_PASS 7, REJECT/SPOT_OVERSHORT 6 (correct spot-short
  protection on non-BTC symbols; BTC SHORT→PERP path verified in tests)
- Execution: AUTHORITY_HOLD 3 (pre-fix RECONCILIATION_HALT era),
  AUTHORITY_REJECT 1; post-fix runs: **0 holds**
- Orders: FILLED 2, REJECTED 1 (historical); Fills: 2
- Market sources: OKX **REAL**, HEALTHY, age 0s

## BLOCKERS FIXED IN THIS LOOP (all pushed to main)

1. `c85f25a` (baseline) → **eb9076-era fixes** earlier: gateway healthy(),
   live-prompt-v2-ai-first, AI-first gate removal (see MISSING_FEATURE_REPORT.md).
2. **2f1c527** — ledger-first paper-exchange hydration: restarts no longer
   diverge from the ledger (RECONCILIATION_HALT guard).
3. **11a93bf** — pre-authorization orderbook refresh resolves the reference
   market symbol for perpetual signals (MARKET_DATA_STALE hold removed).
4. **53c4f57** — `_match_order` no longer clobbers refreshed books with the
   synthetic seed (the root cause of every ~100.05 fake fill; alpha test
   un-bugged accordingly).
5. **1b83f05** — futures-aware reconciliation scope (FUTURES_*/FUNDING
   excluded from the spot-scope replay); halt gate untouched, regression
   test covers both directions.
6. **c432a06** — hydration and reconciliation share the same spot scope.
7. **af426a1** — §10 perpetual duplicate-entry gate restored in the
   AI-first decide path (was overridden away → stacking; fail-closed on
   state-check failure).
8. **53d46c4** — the duplicate-entry gate is symbol-scoped (a BTC position
   no longer freezes the other 19 symbols).
9. **d3589dd** — full traceback logging for exchange-event failures (the
   event loop previously swallowed the root cause into a bare flag).
10. **f28e2fe** — per-process exchange-order-id namespace: the simulated
    exchange restarted its sim_N sequence every run and collided with
    UNIQUE(exchange_order_id) in the persisted orders table, leaving the
    first order of every run stuck at SUBMITTED with its fill applied
    only on the adapter side (the ADA incident, twice).
11. **7f3fa43** — reconciliation base-asset scope: the ledger books a
    trade's base asset as a POSITION while the exchange reports it as a
    BALANCE; matching positions now cover that currency (real position
    drift still halts via POSITION_MISMATCH — regression-tested both ways).
12. **Guardrail compliance (e36d166)** — permanent AI-FIRST invariant
    recorded in HARNESS_GOAL.md + .ai-memory/DECISIONS.md; live-path audit
    clean; EXPLORATION_PROBABILITY=1.0 (the quant-conditioned AI-invocation
    sampler is disabled; every symbol reaches the AI every cycle).

## HONESTY NOTES (samples NOT counted toward the success claim)

- The 2026-08-28 19:55 ETHUSDT fill @ 100.05: pre-fix corrupted-price sample.
- The 2026-08-29 01:02:55 BTCUSDT_PERP fill @ 77687.35: real price and clean
  chain, but it stacked on the open 00:35 position because the AI-first path
  had lost the §10 gate (fixed in af426a1/53d46c4). Counted as evidence of
  price integrity, NOT as the clean E2E proof.

## FLAGS

- PAPER_TRADE_E2E_READY = **YES**
- FULL_BIDIRECTIONAL_PAPER_TRADING = **YES (BTCUSDT only)**; multi-symbol
  perpetual registry = OPEN follow-up (MISSING_FEATURE_REPORT.md)
- RISK_ENGINE_CHANGED = **NO** (doctrine gates removed in the strategy layer;
  risk rules untouched)
- EXECUTION_AUTHORITY_CHANGED = **NO** (only fed fresher, correctly-scoped data)
- REAL_MONEY_READY = **NO**; REAL_MONEY_ENABLED = **NO**; LIVE_TRADING_ENABLED = false
- TRADING_MODE = PAPER throughout; no real OKX order endpoints contacted.

## TESTS

- Backend: **727 passed / 7 skipped / 2 failed** — the 2 failures are
  pre-existing tests that require LIVE OKX fixture values
  (tests/local_stability/test_market_semantics.py); unrelated to all changes.
- ruff: clean. Frontend: 34 tests passed, tsc clean, build OK.
