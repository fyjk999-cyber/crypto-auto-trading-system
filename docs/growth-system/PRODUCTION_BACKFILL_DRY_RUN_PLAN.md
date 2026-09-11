# Production backfill dry-run plan (NOT EXECUTED)

Status: **PLAN ONLY.**  No production backfill, migration, scheduler start or
review publication is authorized by this document.  It is the dry-run plan
required as a hand-off artifact; execution needs a separately approved
integration/deployment package.

## 1. Preconditions (all must be true)

1. Independent Codex review of candidate `99c744c` (or the merged SHA) is
   `APPROVED` and bound to the exact SHA.
2. Integration owner has assigned the Alembic revision and applied the growth
   schema to the target database under the migration matrix.
3. The target database identity is proven read-only first:
   absolute path, schema revision, account_id, mode, source SHA, owning PID
   and open file descriptors (see `SOURCE_MANIFEST.json` / `ROOT_CAUSE.md`).
4. Exactly one scheduler owner exists.  No other process holds
   `crypto_engine_execution` or is writing the same `daily_review_runs` day
   row.
5. LLM budget, provider key/balance and a per-run cost ceiling are approved.
   Authentication/balance errors must pause the review stage, not loop.
6. A verified backup/snapshot procedure exists for the live DB (backup API or
   equivalent); no main-file-only copy, no `immutable=1` on a live DB.

## 2. Dry-run sequence (read-only until step 8)

1. **Manifest refresh**
   `python scripts/growth_system_dry_run.py manifest --db <label>=<path> ...`
   Compare against `SOURCE_MANIFEST.json`; record hashes and schema revision.
2. **Eligibility census**
   `... episodes --db <path> [--date YYYY-MM-DD]`
   Classify each closed day as eligible / pending / reviewed / quarantined and
   list closed trade plans that produced no episode with the fail-closed
   reason (ownership overlap, funding coverage unknown, missing close proof).
3. **Review status**
   `... review-status --db <path>`
   Confirm the daily-review row count, statuses, claim fields and that no
   process holds an unexpired claim.
4. **Legacy inventory only**
   `... import-inventory --source <legacy-db> --plan-out /tmp/plan.json`
   No target write.  Confirm namespace/content hashes and that near
   duplicates remain `DUPLICATE_SUSPECT`.
5. **Bounded backfill estimate**
   Compute `[earliest eligible closed day, yesterday UTC)`; cap to
   `--max-days` (recommend 7) and `--max-episodes-per-run` (recommend 1000).
   Record the per-day episode count before any LLM work.
6. **Claim rehearsal on an isolated copy**
   Run the pipeline against a throwaway copy/DB with injected test provider
   (`TEST_ONLY`) to prove stages, claim/fence and rollback; no real provider.
7. **Provider smoke (separate budget)**
   One real structured-review call on a single already-reviewed factual
   episode, with
   `provider/model/profile/prompt/schema/input` hashes, usage recorded as
   KNOWN or UNKNOWN, and a hard cost cap.  This smoke must not be reused as
   production review evidence and must not create a trade.
8. **Bounded production backfill (only after explicit authorization)**
   One UTC day per pipeline run, oldest first, `owner` = dedicated backfill
   owner, claim lease > worst-case call time, daily budget cap, stop on first
   `CLAIM_LOST`, auth/balance error or provider error-rate threshold.
   Knowledge publication is gated by `net_status=COMPLETE`.
9. **Verification**
   Re-run the census: pending count decreases only for reviewed days;
   per-stage counts and usage are recorded; no duplicate attempt/publish
   rows; revoked/superseded knowledge is not retrieved.
10. **Rollback**
    If a batch is bad: revoke the new knowledge versions (append-only), mark
    the affected growth job/revision failed, and for legacy import batches use
    the batch-scoped rollback (never delete canonical data).  Restore from the
    verified DB backup only if a durable corruption is proven.

## 3. Stop conditions

* No independent approval / no migration authorization.
* Any DB identity ambiguity (running SHA ≠ worktree SHA ≠ DB owner).
* Any live claim held by another owner.
* Provider auth/balance failure, or usage unknown beyond the approved rate.
* A day whose stats are incomplete (`INCOMPLETE_UNKNOWN_FUNDING`) must not
  publish reusable knowledge.
* Any test written against a production DB path (the conftest must refuse it).

## 4. Cost/observability hooks

* `collect_growth_metrics` exposes eligible/pending/quarantined,
  stage-complete, usage-known tokens and `usage_unknown_attempts`; alert on
  unknown usage rather than converting it to zero.
* Record last scheduler time, next UTC review time, oldest backlog, active and
  expired claims, stage failures and retries.
* Do not promise profit improvement or a “learned” claim from these metrics.

## 5. Evidence required after a real run

A real run must produce: factual Episode ids, provider attempt rows with
hashes, published knowledge ids/versions, `growth_tool_selections` rows, the
final decision prompt containing the retrieved refs, and an independent
review receipt.  Until then the only allowed status string is
`FACTUAL_LEARNING_AND_RETRIEVAL_EVIDENCE = NOT_PROVEN`.
