# Runtime Learning Path Audit

BASE = ddf646d (Round-4 implementation)
Scope: read-only static/runtime-path analysis.  No production DB write, no
runtime start/stop/restart, no execution lease change.

## Actual call graph (before Round-5 wiring)

```text
TradingEngine.start
  └─ DailyReviewScheduler.run_once
       ├─ TradeEpisodeStore.load_all_closed_on   -> factual closed episodes
       ├─ DailyReview(...)                       -> descriptive stats
       ├─ FactualEpisodeLearning.review_many     -> ai_trade_reviews
       │                                            ai_market_patterns
       ├─ DailyCardLearner.learn_day             -> updates cards only from
       │                                            existing GrowthReviewAttempt
       │                                            rows + card traces
       └─ MemoryPersistence.save_daily_review
```

There was **no runtime construction** of `StructuredReviewService`,
`GrowthLearningPipeline` or `GrowthKnowledgePublisher`.  Therefore no
`growth_review_attempts`, `growth_lessons` or `growth_patterns` could be
produced from a fresh factual episode, and `DailyCardLearner` had no review
supply to materialize a card.

Round-5 wiring: `DailyReviewScheduler` now optionally receives
`GrowthRuntimeLearningService` (constructed in `runtime/bootstrap.py`).  When
configured, the scheduler still runs factual accounting, then:

```text
FactualEpisodeLearning (accounting/audit only)
        ↓
GrowthRuntimeLearningService.run
        ↓ StructuredReviewService (DeepSeek provider, durable attempt)
        ↓ GrowthKnowledgePublisher.publish_attempts (fenced activation)
        ↓ lesson / proposition / pattern
        ↓ DailyCardLearner.propose_from_pattern + AdaptiveCardStore.apply
        ↓ ai_compressed_experience (canonical Adaptive Experience Card)
```

## Q1 — Daily review canonical owner

| Item | Result |
| --- | --- |
| Entrypoint | `TradingEngine.start` -> `DailyReviewScheduler.run_once` |
| Caller | `runtime/bootstrap.py::build_system` |
| Writer | `FactualEpisodeLearning.review_many` (descriptive), then Round-5 `GrowthRuntimeLearningService` (causal/structured) |
| Tables written | `ai_trade_reviews`, `ai_market_patterns` (factual audit); `growth_review_attempts`, `growth_lessons`, `growth_patterns`, `ai_compressed_experience` (new canonical path) |
| Runtime flag | scheduler exists only when `auto_start_runtime`; structured provider is `DeepSeekProvider` |
| Classification | `FactualEpisodeLearning` = **FACTUAL ACCOUNTING INPUT**, `GrowthRuntimeLearningService` = **CANONICAL REVIEW/PUBLISH OWNER** |

`FactualEpisodeLearning.review_many` was never a learned-experience authority:
it writes result descriptors (`DESCRIPTIVE_POSITIVE_NET_PNL`,
`CAUSAL_CLAIM:NONE`) and market aggregates.  It is retained for audit and
stats and is not counted as Growth learning completion.

## Q2 — Chief canonical learned-context source

`runtime/bootstrap.py` registers two groups on the canonical tool registry:

1. `register_context_tools(ChiefContextLoader)` — legacy `memory_search`,
   `episode_search`, `factor_intelligence`, `coin_profile`, `research_retrieval`.
   It reads `AITradeReviewORM`, `AICompressedExperienceORM`,
   `AIMarketPatternORM` and factual episodes.
2. `register_experience_card_tool(ExperienceCardRetriever, trace_store)` —
   canonical Growth V2 card path (`experience_cards`) with trace-before-use.

`LiveLLMDecisionStrategy` also calls `chief_context.enrich()`, which injects
legacy descriptive episodes/reviews/compressed/paterns into the Chief context
as support evidence.

Canonical classification:

```text
experience_cards -> ExperienceCardRetriever -> CardDecisionTraceStore
    = CANONICAL learned-experience authority

memory_search / episode_search / factor_intelligence / coin_profile
    = LEGACY / SUPPORT ONLY; account/mode scoped and status/latest-version
      guarded, but never a second card authority

research_retrieval
    = SUPPORT / RESEARCH (not learned trading experience)
```

`GROWTH_RUNTIME_STATUS=REVIEW_ONLY` is the honest state while the legacy
descriptive rows exist but no canonical card/experience was produced.

## Q3 — `ai_compressed_experience` writer

`llm_chief/persistence.py::save_compressed` has **zero production callers**
(`DEAD_SUPPLY_PATH=YES`).  The canonical writer for
`ai_compressed_experience` is the Growth V2 `AdaptiveCardStore` reached from
`DailyCardLearner.propose_from_pattern` -> `GrowthRuntimeLearningService`.
`save_compressed` is marked legacy/support-only and is not resurrected as a
parallel supply path.

## Q4 — Growth V2 card writer

| Item | Result |
| --- | --- |
| Input source | canonical structured `ReviewAttempt` for a factual closed episode + published VALIDATED/CONTESTED `GrowthPatternORM` |
| Write trigger | `DailyReviewScheduler.run_once` after structured review publication/wins, with live daily-review fence |
| Output table | `ai_compressed_experience` (`AdaptiveCardStore`), plus `growth_card_versions` journal |
| Eligibility | pattern status VALIDATED/CONTESTED, exact proposition/account/mode, minimum independent samples, fence alive |
| Minimum evidence | `min_pattern_samples` (default 3) independent episodes; `CardUpdateProposal` evidence refs point to pattern/version |

## Q5 — empty/learning-table ownership

See `LEARNING_TABLE_OWNERSHIP_MATRIX.md`.  Key statuses:

```text
trade_episodes                         CANONICAL_ACTIVE
ai_trade_reviews                       SUPPORT_ONLY (factual accounting/audit)
ai_market_patterns                     SUPPORT_ONLY (descriptive aggregate)
growth_review_attempts                 CANONICAL_ACTIVE
growth_lessons / growth_patterns       CANONICAL_ACTIVE
growth_compressions                    CANONICAL_ACTIVE (pattern-derived)
ai_compressed_experience               CANONICAL_ACTIVE (Adaptive Experience Card)
growth_card_versions                   CANONICAL_ACTIVE (journal)
growth_card_decision_traces            CANONICAL_ACTIVE (trace-before-use)
trade_memory_records                   LEGACY (no canonical writer in this path)
```

## Canonical decision

One canonical authority:

```text
closed factual episode
  -> factual accounting (support/audit)
  -> structured evidence-bound review
  -> lesson / proposition / pattern
  -> GrowthKnowledgePublisher
  -> Adaptive Experience Card
  -> ExperienceCardRetriever (experience_cards)
  -> CardDecisionTraceStore (trace before use)
  -> Chief decision
```

Legacy rows remain readable for audit/support but are not a second learned
experience authority.
