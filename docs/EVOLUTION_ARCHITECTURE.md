# EVOLUTION ARCHITECTURE

Phase 4 hierarchical learning:
- DAILY review is COMPLETE.
- WEEKLY review: consumes DailyReviewResult, confirms/invalidates lessons
  (multi-day evidence required), produces WeeklyReviewResult.
  See docs/WEEKLY_REVIEW_POLICY.md.
- MONTHLY review: consumes WeeklyReviewResult, strategy/factor evaluation,
  proposal-only recommendations. See docs/MONTHLY_REVIEW_POLICY.md.
- YEARLY review: consumes MonthlyReviewResult, lifecycle + complexity analysis.
  See docs/YEARLY_REVIEW_POLICY.md.
- All higher-level reviews are proposals only; no production mutation.

## Wiring (added 2026-08-27)

`HierarchicalReviewService` (evolution/hierarchical/service.py) composes the
canonical components - period_for windows, the aggregation engine,
HierarchicalReviewStore, HierarchicalReviewJobStore, SqlEvidenceBackend -
without introducing a second scheduler. Idempotency uses the shared
`review:{weekly|monthly|yearly}:{period_id}` key convention plus deterministic
review ids; completed jobs short-circuit and FAILED jobs are retryable.

## Candidate contract foundation (added 2026-08-27)

`evolution/lab/` holds frozen FactorHypothesis / EvolutionCandidate /
CandidateLineageRecord contracts with a guarded status graph
(DRAFT->...->READY_FOR_UPGRADE). No ACTIVE status exists; activation belongs to
Safe Promotion. Contracts only - sandbox execution, self-modification, and
certification pipelines are explicitly out of scope. See docs/CANDIDATE_CONTRACT.md.
