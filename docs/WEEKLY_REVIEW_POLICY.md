# WEEKLY REVIEW POLICY

Status: implemented (`HierarchicalLearningEngine.weekly_review`,
`HierarchicalReviewService`). Scheduling windows (Monday 00:05 UTC, previous
completed ISO week) are defined in docs/REVIEW_PERIOD_POLICY.md; this document
covers aggregation semantics only.

## Input

All completed `DailyReviewResult` payloads whose `period_id` falls on the seven
UTC dates of the previous ISO week. The service fetches one canonical report per
day (`_collapse_per_period`: first occurrence per day wins); the engine drops
exact duplicates again as a safety net.

## Aggregations

- trade count / decision count / daily report count
- lesson recurrence: `{statement: {days, evidence}}` counted over DISTINCT days;
  same-day repetition never counts as multi-day confirmation
- failure-class recurrence from daily `error_clusters`
- factor issue/conflict recurrence from daily factor attributions
- regime weakness notes per regime
- strategy / factor consistency: mean, spread, observations
- confidence calibration: mean reported confidence bucketed by outcome quality
- weekly drawdown over the ordered daily net PnL series
- repeat profitable patterns and repeat avoidable-error patterns

## Lesson lifecycle

`CANDIDATE -> CONFIRMED | REJECTED`, decided deterministically:

- present on >= 2 distinct days with contradicting days outweighing support
  -> `REJECTED` (lands in `invalidated_lessons`)
- present on >= 2 distinct days otherwise -> `CONFIRMED`
- single-day lessons stay `CANDIDATE`

## Warnings

- `NO_DAILY_REPORTS` when no child report exists for the window
- `MISSING_DAILY_REPORTS:<comma-separated UTC dates>` enumerating absent days

## Guarantees

- Deterministic: same input yields identical output apart from `created_at_utc`.
- Proposal-only: never mutates active factor weights, production strategy,
  candidate activation, or live configuration.
- Idempotent: deterministic review id `review-weekly-<period_id>` plus job-store
  status gate; duplicate runs return the stored report without new writes.
