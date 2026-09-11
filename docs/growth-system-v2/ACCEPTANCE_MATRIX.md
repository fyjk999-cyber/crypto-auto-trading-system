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
| V2 focused | `pytest tests/growth_system_v2 -q` | 46 passed |
| Focused integration bundle | V2 + v1 growth + p8 daily review + memory persistence + migrations + governance | 140 passed |
| Full backend pytest | `.venv/bin/python -m pytest -q -p no:cacheprovider` | see `.ops-growth-v2/full_pytest.log` |
| Ruff | `.venv/bin/python -m ruff check .` | see `.ops-growth-v2/ruff.log` |
| Migration validation | legacy upgrade/repeat/downgrade/re-upgrade + SQLite/PostgreSQL dialect compile | passed in `test_card_schema_and_migration.py` and v1 migration-matrix test |
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
GROWTH_SYSTEM_V2_ENGINEERING_READY=YES
RUNTIME_AUTHORIZED=false
DEPLOYED=false
```

## Fact boundary

* `production_db_written=false`, `runtime_authorized=false`, `deployed=false`.
* `migration_status=DRAFT`; no Alembic revision claimed; the extended
  `ai_compressed_experience` columns and the two journals are covered by a
  portable, reversible draft helper and tests.
* Closed-loop evidence is an isolated simulation with a deterministic test
  provider.  It proves the code chain and invariants, not that a production
  provider/runtime has executed it.
* The frontend was not modified, so the unavailable environment gate is
  `NOT_APPLICABLE`, not a pass.
