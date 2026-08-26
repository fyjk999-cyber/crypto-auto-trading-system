# EVOLUTION ARCHITECTURE

- Updated: 2026-08-26T23:07:25.140636+00:00
- Live Trading Runtime and Evolution Runtime are logically separate.
- Evolution consumes immutable evidence; it never submits orders or mutates
  Ledger/Portfolio/Risk/Execution.
- Canonical components: UtcClock -> ReviewPeriod -> EvolutionReviewScheduler
  -> MemoryGateway/ResearchGateway -> EvolutionStateMachine.
- Staged migration: only audit + Phase 1/2/3 infrastructure implemented in
  this pass; remaining phases are documented for follow-up.
