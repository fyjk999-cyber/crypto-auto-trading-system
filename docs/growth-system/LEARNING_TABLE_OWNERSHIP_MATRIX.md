# Learning Table Ownership Matrix

This is the audit of the growth/learning tables relevant to the runtime
learning closure.  Empty rows are not automatically modified; status gates the
action.

| Table | Writer | Reader | Runtime owner | Expected populated? | Current rows (last audit) | Status | Action |
| --- | --- | --- | --- | --- | ---: | --- | --- |
| `trade_episodes` | `TradeEpisodeStore` | scheduler, review service, retrieval | runtime engine | yes | real factual 33 | CANONICAL_ACTIVE | none |
| `ai_trade_reviews` | `FactualEpisodeLearning` + structured audit updater | `ChiefContextLoader` support path, stats | daily review | yes (descriptive) | 9 | SUPPORT_ONLY | canonical experience no longer depends on it |
| `ai_market_patterns` | `FactualEpisodeLearning` | `ChiefContextLoader` support path | daily review | yes (descriptive) | 8 | SUPPORT_ONLY | not validated reusable experience |
| `trade_memory_records` | no canonical writer | legacy `MemoryPersistence` | none | no | 0 | LEGACY | no action this task |
| `daily_review_runs` | `MemoryPersistence.begin_daily_review` | scheduler/pipeline fence | daily review | yes | 1 | CANONICAL_ACTIVE | none |
| `growth_review_attempts` | `StructuredReviewService` | publisher, `DailyCardLearner`, recovery | `GrowthRuntimeLearningService` | yes when provider available | 0 before wiring | CANONICAL_ACTIVE | wired by Round-5 service |
| `growth_review_attempt_bindings` | `ReviewAttemptStore.bind_job` | exact job recovery | pipeline | yes | 0 | CANONICAL_ACTIVE | none |
| `growth_lessons` | `GrowthKnowledgePublisher` | pattern aggregation, compression, legacy contexts | publisher | yes when reviews publish | 0 | CANONICAL_ACTIVE | no template fabrication |
| `growth_patterns` | `GrowthKnowledgePublisher` | compression, card materialization | publisher | yes when min samples reached | 0 | CANONICAL_ACTIVE | same |
| `growth_compressions` | `GrowthKnowledgePublisher.compress` | legacy retrieval support | publisher | only when called | 0 | CANONICAL_ACTIVE | not required for card path |
| `ai_compressed_experience` | `AdaptiveCardStore` | `ExperienceCardRetriever` only (canonical) | `GrowthRuntimeLearningService` | yes when validated pattern materializes | 0 | CANONICAL_ACTIVE | canonical writer wired |
| `growth_card_versions` | `AdaptiveCardStore` journal | audit | card store | yes with card mutations | 0 | CANONICAL_ACTIVE | none |
| `growth_card_decision_traces` | `CardDecisionTraceStore` | audit/decision attach | retrieval path | yes on Chief card retrieval | 0 | CANONICAL_ACTIVE | trace-before-use enforced |
| `growth_tool_selections` | `GrowthContextLoader.record_selection` | audit | support path | support only | 0 | SUPPORT_ONLY | not canonical proof |
| `growth_import_batches/items/observations` | `LegacyImporter` (test-only) | audit | none in production | no | 0 | SUPPORT_ONLY | production import not authorized |
| `growth_episode_bindings` | `KnowledgeStore.record_binding` | retrieval scope checks | support/scope | when bound | 0 | CANONICAL_ACTIVE | none |
| `ai_coin_profiles` | legacy publisher profile update | legacy `coin_profile` (fail closed in canonical loader) | support | not required | 0 | SUPPORT_ONLY | fail-closed without account/mode provenance |
| other growth schema tables without writer+reader | none | none | none | no | 0 | UNREFERENCED / FUTURE_RESERVED / TEST_ONLY | dead-schema audit later; do not delete now |

## Action policy

```text
CANONICAL_ACTIVE         keep and test
CANONICAL_DORMANT_BUG    only status that may be fixed this round
SUPPORT_ONLY/LEGACY      readable for audit; must not be a second authority
FUTURE_RESERVED/TEST_ONLY/UNREFERENCED
                         no change in this round
DEAD_SCHEMA_CANDIDATE    report only; deletion deferred to dead-code audit
```

No production rows are backfilled or deleted by this document.
