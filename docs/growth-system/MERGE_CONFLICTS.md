# Merge-conflict / semantic-overlap register

This task runs in an isolated sibling worktree/branch and never rewrites the
other task's files, refs or queue state.  The table below is the integration
hand-off register: what can be merged independently and what must be serial.

## 1. Files changed by this branch

| File | Owner policy | Conflict risk | Integration action |
| --- | --- | --- | --- |
| `governance/daily_review.py` | explicitly allowed in this branch | other task also has runtime/learning work but did not touch this file at diagnosis | semantic review of the G01 net/PF contract before merge |
| `governance/factual_learning.py` | explicitly allowed | same | keep G02/G04 as the evidence-bound successor; old result descriptors remain only as compatibility |
| `governance/scheduler.py` | explicitly allowed | same | merge with the other task's bootstrap changes, not by rebase of unfinished work |
| `learning/growth_contracts.py`, `growth_review.py`, `growth_pipeline.py`, `growth_knowledge.py`, `growth_import.py`, `growth_retrieval.py`, `growth_metrics.py`, `growth_models.py` | new files owned by this task | none at diagnosis | additive |
| `scripts/growth_system_dry_run.py` | new file | none | additive |
| `tests/growth_system/**` | new directory | none | additive; another task must not be asked to run it against a production DB |
| `docs/growth-system/**` | new directory | none | additive |
| `.gitignore` | shared | one new ignored path `.ops-growth/` | trivial |

## 2. Public files intentionally NOT modified

`runtime/bootstrap.py`, `runtime/engine.py`, `api/*`, `frontend/*`,
`persistence/models.py`, `llm_chief/context_loader.py`, `migrations/versions/*`.

At diagnosis, several of these were dirty in fullmarket and belong to the
other task (`.env.example`, `api/app.py`, `api/deps.py`,
`runtime/bootstrap.py`, `frontend/src/App.tsx`, `frontend/src/App.test.tsx`,
`scripts/deepseek-keychain.sh`,
`migrations/versions/0040_runtime_settings.py`,
`src/crypto_trader/llm_chief/model_control.py`, plus DB backups and `.ops/`).
Nothing from that set was copied, staged, committed, reverted or rebased.

## 3. Mandatory serial integration steps

1. Freeze the other task's migration head first.  This branch does not use or
   depend on `0040_runtime_settings.py` and its draft growth schema has no
   Alembic revision.
2. Apply the draft growth schema under a reviewer-approved revision
   (`MIGRATION_AND_ROLLBACK.md`).
3. In `runtime/bootstrap.py`, construct the growth pipeline/loader and pass
   them to the single `DailyReviewScheduler` (one claim owner).  This is the
   only public wiring step for G03/G06.
4. In the scheduler/engine path, call `mark_reviewed_fenced` only after the
   pipeline's `stats`, `review` and `publish` stages reach a terminal safe
   state.
5. Re-run the full gate suite on the merged SHA; the current evidence is bound
   to candidate `99c744c` and does not transfer to a merged tree.
6. Do not cherry-pick/rebase either unfinished branch into the other.

## 4. Known semantic conflicts to resolve

| Area | This branch | Possible other-task state | Resolution rule |
| --- | --- | --- | --- |
| Daily-review scheduling | pipeline separated into stats/review/publish; day claim reused | other task changed bootstrap gating of `DailyReviewScheduler` | exactly one claim owner; model loader must not call `begin_daily_review` twice |
| Legacy review rows | result descriptors marked `DESCRIPTIVE_*`, `confidence=0` | `factual_learning` may still be used by dev API | keep compatibility wrapper until the pipeline is enabled |
| Daily-review metrics | net fields + nullable ratios + status suffix | `DailyReviewRunORM` legacy non-null scalar columns | keep the `for_storage()` compatibility mapping until a shared migration adds status columns |
| Growth schema | independent `GrowthBase` draft | untracked `0040` migration | integrate only after numbering/`down_revision` is assigned by the integration owner |
| Memory retrieval | `GrowthContextLoader` injected through the official registry | `llm_chief/context_loader.py` is public | production change must be a reviewed patch that selects one loader or a composite, never two divergent memory stores |
| Frontend | untouched | other task owns `frontend/src/App*` | no frontend changes in this package |

## 5. Rebase/candidate protocol

* This branch is based on `df55b11`; it was never created from the stale
  `98e4b6c` baseline.
* If the integration base changes, re-run every gate in
  `ACCEPTANCE_MATRIX.md` and bind the review receipt to the new SHA; previous
  evidence does not carry over.
* Until the independent review and integration owner approve, status is
  `IMPLEMENTATION` only.
