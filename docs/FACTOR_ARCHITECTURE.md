# FACTOR ARCHITECTURE

## Phase 4 Hierarchical Factor Review
Weekly consumes DailyReviewResult and confirms lessons only with multi-day evidence.
Monthly evaluates factor portfolio from WeeklyReviewResult.
Yearly evaluates factor lifecycle from MonthlyReviewResult.
Raw evidence remains addressable by IDs.

## Factor Health (added 2026-08-27)

`src/crypto_trader/factors/health/` provides explicit per-factor health states
(`OK`, `VALID_ZERO`, `MISSING_DATA`, `INSUFFICIENT_HISTORY`, `STALE_INPUT`,
`CALCULATION_FAILED`, `DISABLED`) with `USABLE_STATES = (OK, VALID_ZERO)`.

- The package did not exist before 2026-08-27; see docs/FACTOR_HEALTH.md for the
  truthful provenance note.
- Capture is group-isolated: one group's exception is recorded, not swallowed.
- Snapshot creation reports unusable factors via `failed_factors` and
  `calculation_warnings` (`factor:STATE[:detail]`) without fabricating zero-value
  entries; `VALID_ZERO` marks legitimate measured zeros.

## Factor Profiles (added 2026-08-27)

`factors/profiles.py` defines canonical profiles (`TREND`, `MOMENTUM`,
`MEAN_REVERSION`, `DERIVATIVES`, `MICROSTRUCTURE`, plus full-set `FULL`) as
required/optional factor groups and deterministic readiness evaluation:

- required factor missing or unusable -> `BLOCKED`
- only optional factors unusable -> `DEGRADED`
- all present and usable -> `READY`
- missing status entries and unknown status strings fail closed

Assessment entry points: `assess_profile(profile, statuses)` and
`assess_profile_from_snapshot(snapshot, profile_name)`.

Boundary note: profiles stop at readiness classification. Enforcing a BLOCKED
verdict against execution remains an integration decision outside this contract.
