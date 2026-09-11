# Concurrency, recovery and integration (G03)

## 1. Durable state separation

`growth_learning_jobs` has one row per
`(account_id, mode, review_date, source_revision, profile_version, revision)`:

| Column | Meaning |
| --- | --- |
| `stats_status` | deterministic factual statistics stage |
| `review_status` | structured provider review stage |
| `publish_status` | reusable-knowledge publication stage |
| `claim_token`, `claim_owner`, `claim_fence`, `claim_deadline_at` | mirrored day-claim identity for audit |
| `input_hash` | hash of the eligible input set for this revision |
| `revision`, `superseded_by_revision` | late-episode/funding revision lineage |

Each stage has its own `*_completed_at`; there is no single `SUCCEEDED` that
can hide a failed middle stage.

## 2. Claim and fence reuse

The day-level claim is **not re-implemented**.  `GrowthLearningPipeline`
calls the existing `MemoryPersistence.begin_daily_review` /
`heartbeat_daily_review` / `fail_daily_review` / `save_daily_review` used by
`DailyReviewScheduler`.  Every stage commit calls `heartbeat` first; the
`growth_learning_jobs` CAS then also requires the same token, owner, fence
and a non-expired deadline.  Therefore:

* two workers cannot execute the same day;
* an expired/old token cannot update a stage or publish;
* `save_daily_review` (the visible day publication) is itself fenced.

## 3. Failure boundaries covered by tests

`tests/growth_system/test_claim_publish_recovery.py` injects a failure at
each durable boundary:

| Injected failure | Asserted state |
| --- | --- |
| stats runner raises/returns FAILED | `stats=FAILED`, review/publish stay `PENDING`, day `FAILED`; retry only reruns non-SUCCEEDED stages |
| one review attempt fails | `stats=SUCCEEDED`, `review=PARTIAL`, publish `PENDING`, day `FAILED`; retry resumes |
| publisher raises/returns FAILED | `stats+review=SUCCEEDED`, `publish=FAILED`; retry completes |
| incomplete funding (`net_status != COMPLETE`) | `publish=SKIPPED_INCOMPLETE`; publisher is never called; day may be recorded with an explicit incomplete status |
| two workers race | exactly one non-idempotent run; the other returns `idempotent=True` |
| old worker wakes after claim expiry | old worker gets `CLAIM_LOST`, never publishes; new worker's day stays `SUCCEEDED` |
| 1,200 episodes in one day | all 1,200 are processed (no silent 1,000-row truncation at the pipeline layer) |
| late episode / changed input hash | new job revision, old row `superseded_by_revision`; same hash replay is idempotent |

## 4. External-call transaction rule

Structured provider calls happen in `StructuredReviewService` (G02) outside
any DB transaction.  The pipeline itself never opens a transaction around a
provider call.  At-least-once semantics are explicit:

* publication is idempotent via the attempt fingerprint and the fenced stage
  CAS;
* provider billing is **not** claimed as exactly-once; crash-before-save can
  duplicate a request;
* `usage_status=UNKNOWN` is persisted when the provider omits usage.

## 5. Production integration package (not yet applied)

The following changes are public-file integration items and are deliberately
**not** made in this branch phase:

1. `runtime/bootstrap.py`: construct a `GrowthLearningPipeline` and pass it
   to the single `DailyReviewScheduler` (or let the scheduler delegate its
   stats/review/publish stages to it).  The scheduler must remain the only
   entry that acquires the day claim.
2. `governance/scheduler.py` (allowed file, but its bootstrap wiring is
   public): after `pipeline.succeeded`, call the existing
   `TradeEpisodeStore.mark_reviewed_fenced` with the same claim token; never
   mark REVIEWED when review or publish stage is incomplete.
3. `runtime/engine.py`: the daily-review task and missed-day recovery must
   call the same pipeline for every UTC day from
   `earliest_factual_closed_date` to yesterday, bounded per run.
4. Apply the draft growth schema (see `MIGRATION_AND_ROLLBACK.md`) before
   enabling the pipeline in any deployed process.

Until those steps are reviewed and deployed, the implementation status is
IMPLEMENTATION only: no production scheduler, no production DB write and no
claim that the loop is running.
