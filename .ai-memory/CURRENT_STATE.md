# CURRENT_STATE

- Updated: 2026-08-29T02:30:00+00:00 (checkpoint cron-2: 2 new clean fills SOL/ADA, health OK, 0 errors)
- **PHASE 2  OVERNIGHT LONG-RUN PAPER OBSERVATION MODE**
- FIRST_AI_PAPER_FILL = YES
- PAPER_TRADE_E2E_READY = YES (PHASE 1 milestone; see PAPER_TRADE_E2E_ACCEPTANCE_REPORT.md)
- OVERNIGHT_PAPER_TRADING = ACTIVE
- REVIEW_DATA_READY = CONTINUOUSLY_UPDATING (OVERNIGHT_PAPER_REVIEW.md)
- PROJECT_COMPLETE =  do not stop the runtime until the user's manual review
- Session index: .ai-memory/OVERNIGHT_PAPER_STATE.md (30-min checkpoints)
- Clean E2E proof: run_256d3e15648542ee976cbefa55bb9cd4 / decision
  dec_a6d0a388dbc34ab082fd / LLM llm_d30a4f2b3429456ca423be4bec8ce7f4
  (LIVE, live_analysis, deepseek-chat) / risk APPROVE RISK_PASS / order
  ord_6a07813a44df44b3b471ebedea407b16 / fill
  fill_8396534b10d74e25843509a357d6e0ab @ 77753.05 REAL OKX price
  (BTCUSDT_PERP LONG 0.001, fee 0.038876525) / ledger txn_467ed207928443e98aa35a09.
- NEW_RUNTIME_BASELINE_SHA = ebcff589921d4c03b4c952cb8ffd80bac60a5ab6
- Post-fix autonomous fills: BNBUSDT 0.001 @ 690.40 (02:00:50), DOGEUSDT
  0.0005 @ 0.08525 (02:09:19) - both full chain, real OKX prices, zero holds.
- Fixed after the v1 report: order-id restart collision (f28e2fe, per-process
  namespace), base-asset balance-vs-position reconciliation scope (7f3fa43),
  event-failure traceback logging (d3589dd), architecture guardrail recorded
  (e36d166; EXPLORATION_PROBABILITY=1.0 - AI sees every symbol every cycle).
- Runtime live: PAPER_REAL_MARKET, OKX REAL feeds healthy (age 0s), recon ok,
  overall OK, LLM_PROVIDER_RUNTIME_VALIDATED=YES.
- Anti-pyramiding: symbol-scoped perp gate restored in AI-first path
  (af426a1 + 53d46c4). A stacked 0.002 BTC position exists from the gate-gap
  window; the bridge owns its HOLD/time-stop; not counted as clean evidence.
- Missing (documented, non-blocking): multi-symbol perpetual registry,
  MAE/MFE tracking, funding scheduler, stale-lease takeover UX, 2 live-OKX
  test fixtures. See MISSING_FEATURE_REPORT.md.
- REAL_MONEY_READY = NO. REAL_MONEY_ENABLED = NO. TRADING_MODE = PAPER only.

## Historical (2026-08-28)

- Updated: 2026-08-28T05:52:00+00:00
- EXECUTION LOCK ACTIVE. POST_COMPLETION_MAINTENANCE_MODE = NOT_ACTIVE.
- PRE_COMPLETION_AUDIT_ONLY = YES.
- CHAPTER 10 = BLOCKED_BY_ENVIRONMENT.
- Frozen runtime qualification baseline: 7b746df09ba5a8e2e9e10cd676fa5d14a2535f10
- REAL_MONEY_READY = NO. REAL_MONEY_ENABLED = NO.
- LLM provider runtime: VALIDATED (deepseek-chat, 6/6 routes) for PAPER-only three-brain use.
- PAPER_SMOKE_TEST = PASS. 24H_PAPER_QUALIFICATION_READY = NO (environment only).
- 2026-08-28 (harness LLM takeover): Shared LLM runtime integrated; earlier baseline
  20a4db8... superseded by
  NEW_RUNTIME_QUALIFICATION_BASELINE_SHA = 7b746df09ba5a8e2e9e10cd676fa5d14a2535f10.
  Session commits: efc25b1 (opt-in DoH transport against fake-IP VPN DNS + route
  output schema examples + DecisionId anchoring + 60s entry decision rate limit),
  e5e3711 (honest /risk metrics + frontend NOT_AVAILABLE/空仓 rendering),
  7b746df (DecisionEvidence persistence for every live decision incl. NO_TRADE,
  with llm_invocation_id correlation).
  Smoke evidence: 27 live correlated decisions, 0 orders/fills, LLM failure
  isolation proven live (disable -> 0 invocations -> re-enable -> recovery),
  market-data DNS outage handled fail-closed. See docs/PAPER_SMOKE_TEST_REPORT.md.
  Blocked for Chapter 10: PostgreSQL absent on this machine; local VPN DNS unstable.
  PAPER ONLY: REAL_MONEY_READY=NO, REAL_MONEY_ENABLED=NO, LIVE_TRADING_ENABLED=false.
- 2026-08-28 (trading logic wiring hardening, PAPER only): Live decision philosophy
  changed from all-conditions gating to STRATEGY SELECTION + EVIDENCE WEIGHTING.
  Five canonical strategies now produce regime-adjusted fit-score candidates
  (StrategyEvidenceBuilder); real FactorSnapshot lineage wired into every Live
  decision (snapshot_id + factor_set_version, no more ""); deterministic PAPER
  gates live_min_strategy_fit=0.45 / live_min_trade_confidence=0.55 (Settings,
  documented); exhaustive entry action mapping (WAIT/unknown/ADD/REDUCE/EXIT
  fail closed, never SELL); evidence persistence instrumented (never silent);
  /decision-context read-only API + frontend strategy-fit panel (real values).
  See docs/TRADING_LOGIC_HARDENING.md. Tests: 669 passed. New baseline recorded
  at the hardening commit SHA (git log -1). RiskEngine/ExecutionAuthority/Ledger
  untouched.
- 2026-08-28 (PAPER exploration + CORE_TRADING_DOCTRINE_V1): STAGE_A_EXPLORATION
  active (.env PAPER_EXPLORATION_MODE=true; guarded by Settings validator that
  REFUSES unsafe configs — exploration only in PAPER with no live/real-money).
  PAPER decision gates: exploration_min_fit=0.40,
  exploration_min_confidence=0.45, borderline-band sampling
  exploration_probability=0.30 (fit 0.40-0.50; skips persisted as
  EXPLORATION_SKIPPED counterfactuals), NORMAL band fit>=0.55 & conf>=0.55,
  exploration entries 0.5x size (0.0005 vs 0.001 BTC),
  decision classes NORMAL_ENTRY/EXPLORATION_ENTRY/NO_TRADE recorded in
  evidence + signal metadata, entry_cooldown_seconds=240 (separate from 60s
  LLM cadence), one open position blocks new entries (POSITION_ALREADY_OPEN),
  bridge PAPER time stop 4h (EXPLORATION_TIME_STOP).
  FINAL CONTEXT PATCH: factor/strategy context fails closed for NEW ENTRY —
  missing snapshot (FACTOR_CONTEXT_UNAVAILABLE), missing candidates
  (STRATEGY_EVIDENCE_UNAVAILABLE), or UNKNOWN regime from context failure
  (MARKET_CONTEXT_UNAVAILABLE) all persist NO_TRADE without calling the
  Live LLM; position safety remains alive. Real Memory -> Live: bounded
  read-only LiveMemoryProvider (confirmed lessons <=5, patterns <=5, similar
  episodes <=5, compressed experience <=5) populates ChiefTraderContext
  knowledge/similar_episodes/compressed_experience and every DecisionEvidence
  records memory_refs; memory is soft evidence only. Learning analytics split
  decision_coverage / executed_trade_coverage / completed_trade_coverage;
  valid_completed_samples exclude INVALID_LEARNING_SAMPLE (mandatory lineage
  filter). Live smoke: real factors -> strategy candidates -> memory refs ->
  LLM -> decision -> signal -> RiskEngine (1 RISK_REJECT SPOT_OVERSHORT)
  verified; LLM invoked on eligible decisions only. Tests: 692 passed.
  RiskEngine/ExecutionAuthority/Ledger unchanged.
