# CURRENT_STATE

- Updated: 2026-08-27 (three-brain support workstream consolidation)
- GLM three-brain support workstream: Chapters 1-9 executed on main.
- Factor health package canonical at src/crypto_trader/factors/health/
  (did not exist before 2026-08-27), integrated into snapshot path.
- Factor profile readiness contracts implemented (READY/DEGRADED/BLOCKED,
  fail-closed); BLOCKED is not yet wired into execution authority.
- Weekly/Monthly/Yearly aggregation implemented and wired via
  HierarchicalReviewService (idempotent, proposal-only, no production mutation).
- Evolution candidate contracts exist in evolution/lab/ (CONTRACTS ONLY):
  FactorHypothesis, EvolutionCandidate, CandidateLineageRecord, guarded status
  graph; NO sandbox execution / self-modification / activation.
- POSTGRES_TEST_RESTORE_READY = NO (see docs/POSTGRES_TEST_RESTORE_AUDIT.md;
  four engine-loop tests remain bare-skipped; integration job has no DATABASE_URL).
- REAL_MONEY_READY = NO.
