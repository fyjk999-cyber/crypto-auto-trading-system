# Canonical Learning Architecture

This document is the single ownership statement for Growth runtime learning.
If code and this document disagree, the code path below is the intended
canonical path and the discrepancy must be fixed or explicitly documented.

1. **Canonical closed-episode source**
   `trade_episodes` (factual closed lifecycle, `TradeEpisodeStore`).
2. **Canonical review owner**
   `DailyReviewScheduler.run_once` -> `GrowthRuntimeLearningService.run`
   on the live daily-review claim.  `FactualEpisodeLearning.review_many` is
   factual accounting/audit input only.
3. **Canonical lesson/proposition/pattern owner**
   `GrowthKnowledgePublisher` / `KnowledgeStore`:
   `growth_review_attempts` -> `growth_lessons` -> `growth_patterns`.
4. **Canonical reusable experience object**
   Adaptive Experience Card in `ai_compressed_experience` (V2 fields), with
   `growth_card_versions` as append-only journal.
5. **Canonical writer**
   `GrowthRuntimeLearningService` -> `DailyCardLearner.propose_from_pattern`
   -> `AdaptiveCardStore.apply`, under a live fence.
6. **Canonical Chief retriever**
   `ExperienceCardRetriever` registered as `experience_cards` in
   `runtime/bootstrap.py`.
7. **Canonical trace store**
   `CardDecisionTraceStore` / `growth_card_decision_traces`; trace is
   persisted before card evidence is released.
8. **Legacy/support paths**
   `FactualEpisodeLearning` (`ai_trade_reviews`, `ai_market_patterns`);
   `ChiefContextLoader` learned tools (`memory_search`, `episode_search`,
   `factor_intelligence`, `coin_profile`); `save_compressed` (dead caller).
   These are scoped/support-only and must not become a second learned
   authority.
9. **Tables no longer part of runtime authority**
   `ai_trade_reviews` and `ai_market_patterns` are descriptive audit/stats
   rows, not reusable learned experience.  `trade_memory_records` is legacy
   with no canonical writer in this path.

## Runtime status contract

```text
NO_DATA       no factual closed episode seen
REVIEW_ONLY   reviews exist, no reusable lesson/pattern/card yet
LEARNING      structured review produced reusable canonical knowledge
DEGRADED      review/knowledge exists but trace/partial failure occurred
BLOCKED       required structured provider/input/fence unavailable
```

`REVIEW_ONLY` is not healthy learning.  `NATURAL_PAPER_GROWTH_LOOP` remains
PENDING until a real natural PAPER episode travels this path and a later Chief
decision retrieves the exact card version with a durable trace.
