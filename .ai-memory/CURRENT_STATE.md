# CURRENT_STATE

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
