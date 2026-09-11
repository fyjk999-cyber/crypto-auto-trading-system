# Growth System V2 — acceptance matrix

Base SHA: `2561e4fdce2cd4b44e0f30d73e427be2e7eded8b`
Branch: `codex/growth-learning-pipeline`
Worktree: `/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-growth`

## Chapter results

| Chapter | Requirement | Implementation | Tests | Status |
| --- | --- | --- | --- | --- |
| G08 | Reuse audit / no duplicate system | `docs/growth-system-v2/REUSE_MATRIX.md` | doc gate + absence of duplicate modules | DONE |
| G09 | Adaptive Experience Card on existing table | `growth_v2_contracts.py`, `growth_card_view.py`, `growth_experience.py`, `growth_v2_migration.py`, extended `AICompressedExperienceORM` | `test_card_schema_and_migration.py`, `test_attribution_evolution.py` | DONE |
| G10 | Canonical trigger/context | `growth_v2_contracts.py` | `test_trigger_context.py` | DONE |
| G11 | Runtime retrieval / read path | `growth_card_retrieval.py` | `test_card_retrieval.py`, `test_chief_card_integration.py` | DONE |
| G12 | Attribution + operations/versioning | `growth_attribution.py`, `growth_experience.py` | `test_attribution_evolution.py` | DONE |
| G13 | Quality/decay/status | `growth_card_quality.py` | `test_quality_decay.py` | DONE |
| G14 | Closed loop + read/write separation + invariants | all above + docs | `test_closed_loop_g14.py`, `test_read_write_separation.py`, `test_invariants.py` | DONE (engineering simulation only) |

## Test results

| Gate | Command | Result |
| --- | --- | --- |
| V2 focused (hardening) | `pytest tests/growth_system_v2 -q` | 63 passed, 1 skipped |
| Focused hardening bundle | V2 + v1 growth + p8 daily review + p8 migrations + memory persistence + llm_chief + risk + governance | 224 passed, 1 skipped |
| Full backend pytest (hardening) | `.venv/bin/python -m pytest -q -p no:cacheprovider` | 1029 passed, 1 skipped, 2 warnings in 137.28s |
| Ruff (hardening) | `.venv/bin/python -m ruff check .` | All checks passed |
| Migration validation (hardening) | Alembic 0039→0040 upgrade/repeat/downgrade/re-upgrade + PostgreSQL offline SQL compile | 7 passed, 1 skipped (real PostgreSQL URL absent) |
| agent-project-test | entry not present | NOT_AVAILABLE |
| Frontend | not modified; environment has no node/npm | NOT_APPLICABLE (no frontend change) |

## Final acceptance strings

```text
G08_REUSE_AUDIT=YES
G09_EXPERIENCE_CARD=YES
G10_TRIGGER_CONTEXT=YES
G11_RUNTIME_RETRIEVAL=YES
G12_ATTRIBUTION_EVOLUTION=YES
G13_VALIDATION_DECAY=YES
G14_CLOSED_GROWTH_LOOP=YES (engineering evidence; no runtime/deployment)
NO_DUPLICATE_GROWTH_SYSTEM=YES
NO_RUNTIME_CARD_MUTATION=YES
NO_RISK_MUTATION=YES
NO_EXECUTION_BYPASS=YES
NO_FAKE_EPISODES=YES
NO_FAKE_EVIDENCE=YES
DECISION_CARD_LINEAGE=YES (growth_card_decision_traces)
CARD_VERSION_LINEAGE=YES (growth_card_versions)
CONTRADICTION_HANDLING=YES

CORE_ENGINE_COMPLETE=YES
MIGRATION_INTEGRATED=YES (Alembic 0040_growth_v2_cards; not deployed)
CANONICAL_RUNTIME_WIRED=YES (build_system composition root; not started)
CANONICAL_SCHEDULER_WIRED=YES (DailyReviewScheduler + DailyCardLearner)
BUILTIN_LLM_REVIEW_WIRED=YES (StructuredReviewRunner: deepseek-flash, thinking, max_tokens 8192)
REAL_PROVIDER_VERIFIED=YES (33/33 factual PAPER episodes structured-reviewed)
NATURAL_PAPER_LOOP_VERIFIED=PENDING (historical backfill, no new live cycle)
REMOTE_REPRODUCIBLE=see final receipt
DEPLOYABLE=ENGINEERING_READY
RUNTIME_AUTHORIZED=false
DEPLOYED=false
```

## Fact boundary

* `production_db_written=false`, `runtime_authorized=false`, `deployed=false`.
* `MIGRATION_INTEGRATED=YES`: real Alembic revision
  `0040_growth_v2_cards` (`down_revision=0039_applicability`) with
  upgrade/repeat/downgrade/re-upgrade SQLite tests and PostgreSQL offline SQL
  compilation.  A real PostgreSQL execution is NOT_VERIFIED because
  `GROWTH_V2_POSTGRES_URL` was not provided.
* Closed-loop evidence is an isolated simulation with a deterministic test
  provider.  It proves the code chain and invariants, not that a production
  provider/runtime has executed it.
* The frontend was not modified, so the unavailable environment gate is
  `NOT_APPLICABLE`, not a pass.
