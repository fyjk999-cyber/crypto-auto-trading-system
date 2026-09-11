# Migration and rollback (draft)

Status: **DRAFT — not verified, not applied to any production database.**
`migration_status = DRAFT`.  No Alembic revision number is claimed and no
`down_revision` is assumed because the integration owner has not frozen the
shared migration head.  In particular this branch does **not** use or depend
on the other task's untracked `0040_runtime_settings.py`.

## 1. Why new tables are required (field-gap table)

| Requirement | Existing ORM/store | Gap | Draft structure |
| --- | --- | --- | --- |
| One review attempt per provider call with result/error/usage/fingerprints | none | no attempt ledger at all | `growth_review_attempts` |
| Stage-separated durable job with claim mirror | `DailyReviewRunORM` has a single `status` and scalar metrics | one `SUCCEEDED` would hide a failed review/publish; no input hash or revision | `growth_learning_jobs` |
| Episode account/currency/mode/instrument binding | `TradeEpisodeORM` has no account/currency/mode columns | cannot prove multi-account/multi-mode isolation on the episode row itself | `growth_episode_bindings` |
| Versioned, evidence-bound lesson candidates | `AITradeReviewORM.lessons_json` is a list on one row per episode | no version, status, sample count, support/contrary refs or confidence axes | `growth_lessons` |
| Pattern independent samples + counterexamples + grade | `AIMarketPatternORM` has `sample_count/win_rate/profit_factor` | no contrary counts, revocation status, known_at or non-profitability basis | `growth_patterns` |
| Conditional compression with source lineage | `AICompressedExperienceORM` has `source_episode_count` only | no source ids/versions, contrary refs, invalidation conditions or known_at | `growth_compressions` |
| Legacy import lineage and rollback | none | no batch/namespace/content-hash/decision rows | `growth_import_batches`, `growth_import_items`, `growth_legacy_observations` |
| Proof the Chief selected and received memory evidence | `LLMDecisionORM` stores refs but not the selected-tool list/prompt | no auditable selection row | `growth_tool_selections` |

Existing tables (including `AICoinProfileORM`) are reused where they already
carry the needed fields.  No existing table is altered or dropped.

## 2. Draft DDL

The authoritative Python draft is
`src/crypto_trader/learning/growth_models.py` (`GROWTH_TABLES`,
`GrowthBase.metadata`).  To render SQL for review:

```python
from crypto_trader.learning.growth_models import growth_schema_sql
print("\n".join(growth_schema_sql()))
```

Tests create the schema only on throwaway SQLite databases via
`create_growth_schema(engine)`; the test conftest refuses known
runtime/production database paths.

## 3. Integration requirements before production

1. Integrator assigns the next Alembic revision id and `down_revision` after
   freezing the shared migration head.
2. Migration must be idempotent-safe on SQLite and PostgreSQL; the draft uses
   only portable column types.
3. A migration matrix must cover: fresh schema, upgrade from the frozen head,
   upgrade from a legacy schema lacking `trade_episodes`, and rollback to the
   frozen head.
4. No production application without the deployment authorization listed in
   `ACCEPTANCE_MATRIX.md`.

## 4. Rollback contract

* Growth tables are additive; rollback may drop only the growth tables and
  must never drop or rewrite canonical `trade_episodes`, ledger, orders,
  fills or engine tables.
* A rollback of a legacy import batch is **batch-scoped**: delete only
  `growth_import_items`, `growth_legacy_observations` and the
  `growth_import_batches` row for that batch id.  The source database and any
  pre-existing canonical data are untouched.
* Knowledge revocation is append-only: a new version row with `REVOKED`
  status is inserted; old versions remain for audit and are excluded from
  default retrieval.
* The pipeline stores no external provider payload beyond the sanitized
  structured result/error; rollback therefore cannot leak prompt data.
