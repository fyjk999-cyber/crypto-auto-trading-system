# DECISIONS

- 2026-08-27T05:37:04.762548+00:00: Do not fabricate PostgreSQL/soak validation. Report NOT_RUN when environment cannot execute it. REAL_MONEY_READY remains NO.
- 2026-08-27 (workstream): Aggregation reviews are proposal-only by construction;
  duplicate child reports collapse to one canonical report per sub-period;
  hierarchical service reuses scheduler idempotency-key convention without a new
  scheduler; evolution/lab contracts carry no ACTIVE status (activation belongs to
  Safe Promotion); PostgreSQL restoration documented truthfully as NOT READY with
  blockers instead of weakening skips.
