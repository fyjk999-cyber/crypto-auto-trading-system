# DECISIONS

- 2026-08-29 (ARCHITECTURE GUARDRAIL, user interrupt): AI-FIRST /
  QUANT-AS-EVIDENCE recorded as a permanent Architecture Invariant in
  HARNESS_GOAL.md (and here). Live-path audit results: (1) no forced/
  fallback LONG/SHORT anywhere in runtime/llm paths; (2) no quant hard
  gates — fit/confidence/regime/scores are labels and prompt evidence;
  (3) action space stays Literal[LONG, SHORT, NO_TRADE, WAIT] — NO_TRADE
  and WAIT are first-class; (4) opportunity ranking is ADVISORY ONLY
  (top_k feeds observability, never eligibility); (5) remaining hard
  gates are all Safety Gates (real data health, provider health,
  position-duplicate, cooldown, kill switch, lease, reconciliation);
  (6) RiskEngine and ExecutionAuthority code untouched this loop.
  One regression candidate found: the exploration sampler
  (EXPLORATION_SKIPPED) skipped ~10% of borderline-fit AI calls — a
  quant-conditioned AI invocation gate. Resolved by setting
  EXPLORATION_PROBABILITY=1.0 (every symbol reaches the AI every cycle;
  the code path remains as an explicit budget control, disabled).
  Priority order fixed: PAPER safety > AI-FIRST integrity > Risk/
  Execution safety > data integrity > Long Goal completion > trading
  frequency > fill count.
- 2026-08-29: Ledger = single source of truth; the paper exchange hydrates
  from it at startup. Reconciliation is spot-scoped (FUTURES_*/FUNDING
  excluded) - the perpetual engine owns futures integrity; halt semantics
  unchanged. Duplicate-entry protection is symbol-scoped and fails closed on
  state errors. The 01:02:55 stacked fill is excluded from clean evidence.
- 2026-08-27T14:32:22.377974+00:00: Do not fabricate runtime soak. FINAL report reflects PARTIAL/NO where external staging unavailable.
- 2026-08-28: LLM is shared infrastructure only. It cannot call the exchange or bypass RiskEngine/ExecutionAuthority.
- 2026-08-28: Runtime qualification baseline superseded to 20a4db8 (LLM integration
  changed production runtime behavior). Entry-path LLM decisions rate-limited to
  one per min_decision_interval_seconds (default 60s) to bound token cost on the
  0.5s market tick; position safety paths unaffected. Domain-model prompts now
  carry explicit output schema examples + DecisionId correlation; strategy gate
  requires route readiness (routes+provider+key) not just provider health.
