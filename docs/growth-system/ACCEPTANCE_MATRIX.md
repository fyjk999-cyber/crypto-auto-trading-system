# Acceptance matrix — growth-learning pipeline

Task: `growth-learning-pipeline`
Base SHA: `df55b11bcde5d50670ef92d05ba2166feb4735d9`
Branch: `codex/growth-learning-pipeline`
Worktree: `/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-growth`

## Status vocabulary

| Status | Meaning |
| --- | --- |
| IMPLEMENTATION | Code + tests exist on this branch |
| INDEPENDENT_REVIEW | Requires an external Codex `APPROVED`/`CHANGES_REQUIRED` receipt bound to the candidate SHA |
| MIGRATION_AUTHORIZATION | Draft schema only; no Alembic revision/head approved |
| DEPLOYMENT | No process restarted, no production scheduler enabled, no runtime authorized |
| FACTUAL_LEARNING_AND_RETRIEVAL_EVIDENCE | Requires real factual Episode → real DeepSeek review → published knowledge → later Chief retrieval; not created by tests or by this Harness |

## Chapter matrix

| Chapter | Deliverable | Implementation files | Tests | IMPLEMENTATION | Other gates |
| --- | --- | --- | --- | --- | --- |
| G00 | Runtime identity, source manifest, zero-review root cause | `scripts/growth_system_dry_run.py`, `docs/growth-system/SOURCE_MANIFEST.json`, `ROOT_CAUSE.md` | `test_g00_readonly_snapshot.py`, `test_g00_db_guard.py` | DONE | INDEPENDENT_REVIEW pending; production counts are observations only |
| G01 | Net financial truth, nullable PF, funding completeness | `governance/daily_review.py`, `governance/scheduler.py`, `governance/factual_learning.py` | `test_financial_truth.py` (+ updated existing governance test) | DONE | — |
| G02 | Structured evidence-bound review | `learning/growth_contracts.py`, `growth_review.py` | `test_review_schema_and_refs.py` | DONE | Real-provider smoke NOT_RUN (no budget authorization) |
| G03 | Staged fenced claim/recovery/late revision | `learning/growth_pipeline.py` | `test_claim_publish_recovery.py` | DONE | Public bootstrap wiring = integration package |
| G04 | Lessons/patterns/profiles/compression | `learning/growth_knowledge.py`, `growth_models.py` | `test_knowledge_revision.py` | DONE | Pattern count in production is 0 (no reviewed knowledge) |
| G05 | Legacy read-only inventory + isolated import/rollback | `learning/growth_import.py` | `test_legacy_import.py` | DONE | Production import NOT_AUTHORIZED |
| G06 | Chief selects memory tools and receives evidence | `learning/growth_retrieval.py` | `test_chief_memory_integration.py` (incl. `build_system` + injected provider) | DONE | Production bootstrap wiring = integration package |
| G07 | Metrics, gates, review receipt | `learning/growth_metrics.py`, this matrix, `REVIEW_RECEIPT.md` | `test_metrics_and_gates.py` | DONE | INDEPENDENT_REVIEW pending |

## Gate results on the candidate SHA

All commands ran inside the task worktree with `.venv`; raw logs are in
`.ops-growth/` (untracked evidence; SHA-256 listed in `REVIEW_RECEIPT.md`).

| Gate | Command | Result |
| --- | --- | --- |
| Full unit/component/integration pytest | `.venv/bin/python -m pytest -q -p no:cacheprovider` on final candidate `99c744c` | **966 passed** in 147.18s, 2 pre-existing SQLAlchemy warnings |
| Growth-system suite | `.venv/bin/python -m pytest tests/growth_system -q` on final candidate | **66 passed** |
| Directly affected governance/integration tests | `pytest tests/integration/test_p8_daily_review_concurrency.py tests/integration/test_memory_persistence.py tests/integration/test_p8_migrations.py tests/governance_unit/test_governance.py -q` | **28 passed** |
| Ruff (whole repo) | `.venv/bin/python -m ruff check .` | **All checks passed** |
| Migration matrix (draft) | `test_growth_schema_is_additive_and_compiles_for_both_dialects`; `alembic heads` | SQLite + PostgreSQL dialect compile passed; Alembic head remains `0039_applicability`; no new revision claimed |
| Read-only dry-run | `scripts/growth_system_dry_run.py manifest/episodes/review-status/import-inventory` against the five candidate DBs | completed; source opened `mode=ro` + `query_only`; no source write |
| Frontend gates | `scripts/frontend-verify.sh` | **NOT_AVAILABLE**: this environment has no `node`/`npm` and `frontend/node_modules` is absent |
| `agent-project-test` harness | path/command not present | **NOT_AVAILABLE** (not invented) |
| Production backfill/deploy | not executed | **NOT_AUTHORIZED** |

## Fact boundary

* `production_db_written = false` for this task.  The fullmarket database is
  being written independently by the other task's PID 8845; this task only
  read it through a read-only backup snapshot.
* `runtime_authorized = false`; no trading runtime was started, no execution
  lease acquired, no scheduler enabled and no review backfilled.
* No “the system has learned”, “pattern promoted” or “loop is live” claim is
  made.  `ai_trade_reviews = 0` in the inspected snapshots, so the production
  pattern count is legitimately zero; insufficient evidence means no approved
  Pattern rather than a fabricated one.
* Engineering pass ≠ production closed loop.  The five categories below are
  reported separately and are not interchangeable.

```
IMPLEMENTATION:                                 DONE for G00–G07 on candidate SHA
INDEPENDENT_REVIEW:                             ROUND-1 CHANGES ADDRESSED; ROUND-2 DELIVERY_FAILED; RETRY SCHEDULED (cron-16, 2026-09-11T13:35Z)
MIGRATION_AUTHORIZATION:                        NOT_GRANTED (draft only)
DEPLOYMENT:                                     NOT_PERFORMED
FACTUAL_LEARNING_AND_RETRIEVAL_EVIDENCE:        NOT_PROVEN (no real provider run, no deployed loop)
```
