# Review receipt — growth-learning-pipeline (G00–G07)

```text
task_id = growth-learning-pipeline
chapter_id = G00–G07
request_id = d9e58e0a-ef86-456c-85a4-062ecf1fc98a
base_sha = df55b11bcde5d50670ef92d05ba2166feb4735d9
candidate_sha = 99c744cbb169ebaf01238d23f26d1ff9a35df2a5 (implementation commit; this receipt is a later docs-only metadata commit)
worktree = /Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-growth
other_task_conflict = OTHER_TASK_FULLMARKET_DIRTY_FILES (list below; not copied/staged/committed/reverted)
pre_existing_dirty = fullmarket 16 dirty/untracked items recorded in ROOT_CAUSE.md §1
migration_status = DRAFT (no Alembic revision; current committed head remains 0039_applicability)
production_db_written = false
runtime_authorized = false
next_stage_requested = minimum rework list from round 2, then a new independent review bound to the new SHA; integration/deploy remains separately authorized
independent_review_status = ROUND2_CHANGES_REQUIRED (candidate 99c744c; 13 findings: S1/S2 + P1-P11; no integration/deploy)
```

## 1. Baseline / isolation

* The task book named `98e4b6c…`; the actual fullmarket HEAD at diagnosis was
  `df55b11…` (one docs commit ahead).  `98e4b6c` is an ancestor, so the
  implementation baseline is re-bound to `df55b11` as required by the task’s
  “baseline change → re-run tests and bind the new SHA” rule.
* New sibling worktree, no checkout/switch/reset in fullmarket.  Branch
  `codex/growth-learning-pipeline` was created from `df55b11`.
* Other-task dirty files (left untouched):
  `.env.example`, `data/paper-runtime.log`, `RUNTIME_ACCEPTANCE_PLAN.md`,
  `frontend/src/App.test.tsx`, `frontend/src/App.tsx`,
  `scripts/deepseek-keychain.sh`, `src/crypto_trader/api/app.py`,
  `src/crypto_trader/api/deps.py`, `src/crypto_trader/runtime/bootstrap.py`,
  `.ops/`, `data/crypto_trader.db.bak-0911-1547`,
  `data/crypto_trader.db.pre-0040`, `data/crypto_trader.db.presep8-history`,
  `migrations/versions/0040_runtime_settings.py`,
  `src/crypto_trader/llm_chief/model_control.py`,
  `tests/llm_chief/test_model_control.py`.

## 2. Changed files

```text
A docs/growth-system/ACCEPTANCE_MATRIX.md
A docs/growth-system/CONCURRENCY_AND_INTEGRATION.md
A docs/growth-system/CONTRACTS.md
A docs/growth-system/MERGE_CONFLICTS.md
A docs/growth-system/MIGRATION_AND_ROLLBACK.md
A docs/growth-system/PRODUCTION_BACKFILL_DRY_RUN_PLAN.md
A docs/growth-system/REVIEW_RECEIPT.md
A docs/growth-system/ROOT_CAUSE.md
A docs/growth-system/SOURCE_MANIFEST.json
A scripts/growth_system_dry_run.py
M src/crypto_trader/governance/daily_review.py
M src/crypto_trader/governance/factual_learning.py
M src/crypto_trader/governance/scheduler.py
A src/crypto_trader/learning/growth_contracts.py
A src/crypto_trader/learning/growth_import.py
A src/crypto_trader/learning/growth_knowledge.py
A src/crypto_trader/learning/growth_metrics.py
A src/crypto_trader/learning/growth_models.py
A src/crypto_trader/learning/growth_pipeline.py
A src/crypto_trader/learning/growth_retrieval.py
A src/crypto_trader/learning/growth_review.py
M tests/governance_unit/test_governance.py
A tests/growth_system/conftest.py
A tests/growth_system/test_chief_memory_integration.py
A tests/growth_system/test_claim_publish_recovery.py
A tests/growth_system/test_financial_truth.py
A tests/growth_system/test_g00_db_guard.py
A tests/growth_system/test_g00_readonly_snapshot.py
A tests/growth_system/test_knowledge_revision.py
A tests/growth_system/test_legacy_import.py
A tests/growth_system/test_metrics_and_gates.py
A tests/growth_system/test_review_schema_and_refs.py
```

Public files listed by the task (`runtime/bootstrap.py`, `runtime/engine.py`,
`api/*`, `frontend/*`, `persistence/models.py`, `llm_chief/context_loader.py`,
`migrations/versions/*`) were **not** modified in this phase.  Their required
wiring is an explicit integration package documented in
`CONCURRENCY_AND_INTEGRATION.md` §5.

## 3. Test commands and results

All commands executed in the task worktree with the independent `.venv`
(`Python 3.12.14`, SQLAlchemy 2.0.52); test fixtures are TEST_ONLY and the
conftest refuses known runtime/production DB paths.

| # | Command | Result |
| --- | --- | --- |
| 1 | `.venv/bin/python -m pytest -q -p no:cacheprovider` on final candidate `99c744c` | `966 passed, 2 warnings in 147.18s` |
| 2 | `.venv/bin/python -m pytest tests/growth_system -q` | `66 passed in 16.40s` |
| 3 | `pytest tests/integration/test_p8_daily_review_concurrency.py tests/integration/test_memory_persistence.py tests/integration/test_p8_migrations.py tests/governance_unit/test_governance.py -q` | `28 passed in 6.19s` |
| 4 | `.venv/bin/python -m ruff check .` | `All checks passed!` |
| 5 | `test_growth_schema_is_additive_and_compiles_for_both_dialects` | `1 passed` (SQLite + PostgreSQL dialect compile; tables disjoint from shared metadata) |
| 6 | `.venv/bin/alembic heads` | `0039_applicability (head)` — draft growth schema is not on the Alembic chain |
| 7 | `scripts/frontend-verify.sh` | `NOT_AVAILABLE` — no `node`/`npm`, `frontend/node_modules` absent |
| 8 | `agent-project-test` | `NOT_AVAILABLE` — no such harness entry in this environment (not invented) |

## 4. Evidence paths and SHA-256

Evidence lives in the ignored `.ops-growth/` directory of the task worktree
(not part of the committed tree).  Hashes were captured on the candidate
content; the full `SHA256SUMS` file is included.

```text
744b5488ba23285d0b790603ad5f5b6d2d06fadb719328db73b5b1879e4f29e3  full_pytest_final2.log   (candidate 99c744c)
82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18  ruff_full_final2.log
d3fc3fc07756c9a4f31c98a2ab6fddb63de9f1f3e73c943aad6801d6c379f3aa  review_dispatch.json (round 1)
f1b780ee85d41a871ab145271a8d4a32430d639f52ff4074b3c3bfeb09ee1bdf  review_dispatch_round2.json (round 2 delivery failure)
62b8eb7c2c5d6d7a1264355e56895a070d358d59fee7e27ecdb9db535355c8cb  full_pytest.log (previous candidate 119752e)
4988d271343a3454122361dfba768979a7decef36b9d391bdfbac27bac78b28e  growth_system_pytest.log
32c69d65ff416f49b6532fcd8d50e768410d59409cfc17b369d7a7bb171f018d  affected_integration_pytest.log
82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18  ruff_full.log
63203b4ec2b29e7ab8c45616e4d500960794bb60488784fb13fb7fe05b0386bf  migration_matrix.log
0999fe67297717811c39253d4d0180cb7e47e4ae155938df4aa7af0d06380ff7  alembic_heads.log
79c34b5a9c4ee0990aa126bb8c8fe42fb0656d5cf44344473511dd1e8267d7a1  dry_run_manifest.log
5918058253e853dc45ac45a8cb73d9cde11d046d4ebb590d4964f37986347392  dry_run_episodes.log
d527db2eebc6c819346c5d6146bbaa09380f4cd523f60ecb93bba651d4b9f3f1  dry_run_review_status.log
d1aeace3f2e808cd0266077bff9fae77a61f5150825f40846a35c5be62b93b05  dry_run_import_inventory.log
292a10a21fd424a40fc7959c510a94024b36d207a98534d05ddfce2c3ba4dc09  legacy_import_plan.json
557f790779d82e72bd13c5525cafc7aefb08ab098060722a49e5b4651df1af26  frontend_gate.log
db8158d2e9aa00958a39b6303900e102da2272bc60a86965ab10a58514921ece  production_write_statement.txt
```

## 5. Dispatch / review outcome

`codex-dispatch` was verified with `--help` before use:
`~/.dsh/bin/codex-dispatch --help` → usage with sandbox `read-only|workspace-write|danger-full-access`,
`--session`, `--name`, `--out`.

### Round 1 (candidate `119752e`, delivered)

```text
dispatch_command = ~/.dsh/bin/codex-dispatch --name growth-pipeline-review-119752e --workdir <worktree> --sandbox read-only --timeout 1800 --effort high --prompt-file .ops-growth/review_request.txt --out .ops-growth/review_dispatch.json
dispatch_thread_id = 01a08fcf-d919-7983-b7aa-00d58cab0c30
dispatch_status = error (exit=1; the read-only sandbox prevented pytest temp dirs, so the reviewer could not complete a formal verdict)
review_findings = CHANGES_REQUIRED:
  1) G03 publish retry skipped the already-SUCCEEDED review stage without reloading
     durable attempts, so an empty review list could mark publish SUCCEEDED;
  2) G02 cache-hit path returned a stored review without revalidating its refs
     against THIS call's allowed_refs.
fixes = commit 99c744cbb169ebaf01238d23f26d1ff9a35df2a5
  - GrowthLearningPipeline reloads ReviewAttemptStore.load_succeeded_for_date for
    the publish retry; empty publish input becomes SKIPPED_INCOMPLETE/NO_PUBLISH_INPUT,
    never SUCCEEDED (test_publish_retry_reloads_durable_review_attempts);
  - StructuredReviewService re-runs validate_review on a cache hit and falls back to a
    new provider attempt when the current allowed_refs do not cover the cached refs
    (test_cache_hit_must_satisfy_current_allowed_refs).
```

### Round 2 (candidate `99c744c`, verdict delivered)

```text
dispatch_command = ~/.dsh/bin/codex-dispatch --session 01a08fcf-d919-7983-b7aa-00d58cab0c30   --name growth-pipeline-review-round2 --workdir <worktree> --sandbox workspace-write   --timeout 1800 --effort high --prompt-file .ops-growth/review_request_round2.txt   --out .ops-growth/review_dispatch_round2.json
dispatch_started_at = 2026-09-11T13:35:22.454Z
dispatch_finished_at = 2026-09-11T13:46:02.871Z
dispatch_duration_ms = 640417
dispatch_exit_code = 0
dispatch_record_status = error (post-verdict TLS "Reconnecting 2/5" notice)
review_verdict = CHANGES_REQUIRED
candidate_sha = 99c744cbb169ebaf01238d23f26d1ff9a35df2a5
thread_id = 01a08fcf-d919-7983-b7aa-00d58cab0c30
record_path = /Users/huhongjie/.dsh/codex-dispatch/records/2026-09-11T13-35-22-454Z-01a08fcf.json
usage = input=2799701 cached=2600320 output=17822 reasoning=3355
```

Round-1 fixes independently verified by the reviewer:

1. G02 cache-hit revalidates refs against the current `allowed_refs`
   (`test_cache_hit_must_satisfy_current_allowed_refs` passes).
2. G03 publish retry reloads durable attempts
   (`test_publish_retry_reloads_durable_review_attempts` passes).

However the reviewer found 13 blocking items (2 Standards P1 + 8 Speck P1 +
3 P2).  The seven minimum rework items are:

```text
1 G03 atomic publish fencing: an expired claim can still commit a
  retrievable VALIDATED Pattern before the pipeline returns CLAIM_LOST.
2 G03 exact job-input binding on retry: reload mixes other account/mode
  attempts; changed input reuses the old revision/review;
  NO_PUBLISH_INPUT is still treated as terminal success and blocks retry.
3 G04 knowledge validation/version selection: mutually different single
  samples are co-promoted; revoked old Pattern versions remain compressible;
  revocation backfills old known_at and distorts historical visibility.
4 G05 real-target binding and batch identity: the guard does not bind the
  actual DB connection; unauthorized rollback deletes data; resume can mix
  plans from different sources into one batch.
5 G06 retrieval boundaries: cross-account/mode profile leakage; per-category
  token budgets exceed the shared limit; official-path test manually calls
  evidence persistence instead of proving the decision chain persists it.
6 G02 persist thrown-provider attempts with UNKNOWN usage (currently zero
  durable attempt rows on transport exceptions).
7 G00/G07 evidence wording: separate runtime facts from static inference and
  rebind the candidate/test records and valid/cited knowledge statistics.
```

Independent verification / evidence:

```text
candidate_snapshot = git archive 99c744c; 997 blobs all matched
growth_suite = 66 passed in 16.75s (candidate snapshot, isolated tmp)
ruff = All checks passed
alembic_head = 0039_applicability
full_pytest_966 = log SHA-256 matched; not independently re-run this round
real_provider = NOT_RUN
production_db/runtime = not accessed / not started
original_worktree_at_end = git status --short empty
```

Evidence hashes (SHA-256):

```text
a3fe937b29da5f8a5e5e25a1b83bddaf25cf1847c94e8e680f53ee80c53c2f7f  .ops-growth/independent-audit-99c744c-v_xz8qpf/INDEPENDENT_REVIEW.md
7ba37091f9a48c19dc471d3167f549b63a6a9b94cde109a3b25bcbbfd6fca835  .ops-growth/independent-audit-99c744c-v_xz8qpf/audit-probes.log
7a24a01b73bc87c436d6d9ed9b7e3224aad83700bb486b6024b6d396f52ac074  .ops-growth/review_dispatch_round2.json
bb3a1c9beb7debcab830e350e353e8bcfcc91bbed789ada99d1d780fe94c2560  .ops-growth/review_dispatch_round2.stdout
a61c4aa23224db3d1cba73f1809c400ec0c7d1f3715cbd8abf97874cc9075ceb  .ops-growth/review_dispatch_round2.stderr
79731b8aca4e16339ed0d01c42cac06df340259571bccdc71f0afc11ea2d39a4  .ops-growth/review_round2_final_message.txt
```

State:

```text
IMPLEMENTATION = CHANGES_REQUIRED
INDEPENDENT_REVIEW = CHANGES_REQUIRED (bound to 99c744c)
MIGRATION_AUTHORIZATION = NOT_GRANTED / DRAFT
DEPLOYMENT = NOT_PERFORMED
FACTUAL_LEARNING_AND_RETRIEVAL_EVIDENCE = NOT_PROVEN_FOR_THIS_CANDIDATE
```

A queue acceptance is delivery only; exit code 0 is not APPROVED. No self-approval
and no concurrent resume of an active writer thread was performed.

## 6. Explicit non-claims

* No production migration, import, backfill, deploy or scheduler enablement.
* No real DeepSeek provider smoke was run (`REAL_PROVIDER_SMOKE = NOT_RUN`,
  needs budget authorization).
* No factual Episode → real review → published knowledge → retrieval evidence
  was produced; status remains `FACTUAL_LEARNING_AND_RETRIEVAL_EVIDENCE = NOT_PROVEN`.
* Engineering gate results above are bound to the candidate SHA, not to any
  running process or production database.
