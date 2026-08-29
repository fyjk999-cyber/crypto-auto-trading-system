# DECISIONS

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
