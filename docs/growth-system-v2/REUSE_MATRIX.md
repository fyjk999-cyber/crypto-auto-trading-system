# G08 — Existing system reuse audit

Scope: `/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-growth`.
Baseline `2561e4f` (`codex/growth-learning-pipeline`, based on `df55b11`).

This is a read-only audit performed **before** writing V2 code.  The V2 rule is
“extend the existing compressed-experience memory into an Adaptive Experience
Card”; no second Episode, Review, Retrieval, Lifecycle or Memory store is
created.

## 1. Classification matrix

| Capability | Existing implementation | Classification | V2 decision |
| --- | --- | --- | --- |
| Factual Episode | `governance/trade_episode.py` (`FactualTradeEpisode`, `TradeEpisodeStore`, `trade_episodes` ORM) | KEEP | canonical truth source; V2 never creates episodes from cards or tests |
| Daily Review / claim | `governance/daily_review.py`, `governance/scheduler.py`, `governance/memory_persistence.py` | ADAPT | V2 write path reuses the same day claim/fence and `DailyReviewStats`; no second cron/review table |
| Review Lessons | `governance/factual_learning.py`, `growth_lessons` (v1 draft schema), `AITradeReviewORM` | ADAPT | V2 attribution consumes structured review evidence + lesson candidates; does not create a second review store |
| Market Pattern | `growth_knowledge.py` (`GrowthPatternORM`), legacy `AIMarketPatternORM` | ADAPT | patterns are one input to card proposals; legacy pattern table remains read-only for compatibility |
| Compressed Experience | `persistence/models.py` `AICompressedExperienceORM`, `llm_chief/persistence.py` `LLM_MEMORY` helpers | **ADAPT → canonical card table** | `ai_compressed_experience` is extended in place; this is the only runtime card persistence truth |
| v1 `growth_compressions` | `learning/growth_models.py` `GrowthCompressionORM` | DEPRECATE | V2 runtime retrieval must not read it; it remains only for v1 compression tests and will be merged/removed at integration |
| Similarity retrieval | `ai_memory/similarity.py`, `ai_memory/market_memory.py` | KEEP | reusable similarity helper; no new vector DB |
| Hybrid retrieval | `vector_memory/retrieval.py` `HybridRetriever`, `vector_memory/vector_store.py` | ADAPT | used as the semantic component of bounded card ranking (transient index over the already-hard-filtered candidate set) |
| Memory governance | `memory_governance/governor.py` `MemoryGovernor.score` | ADAPT | quality-score component; weights stay in one versioned policy |
| Knowledge decay | `intelligence/knowledge/decay.py` `KnowledgeDecayEngine.evaluate` | ADAPT | decay component; card status transitions consume `KnowledgeHealth` |
| Factor lifecycle | `factors/lifecycle/manager.py`, `factors/lifecycle/rules.py`, `FactorLifecycleORM` | KEEP | factor-level lifecycle remains the owner of factor state; cards store `factor_id` + `definition_version` |
| Knowledge graph | `intelligence/knowledge/graph.py` `KnowledgeGraph` | KEEP | available for relation queries; card lineage does not need a second graph store |
| Promotion / shadow | `evolution/promotion.py`, `shadow_campaign` | KEEP / NOT_USED for cards | the promoter requires BACKTEST/OOS/WALK_FORWARD/SHADOW evidence; fabricating that for cards is forbidden, so card CANDIDATE→ACTIVE uses the card quality policy, and strategy/factor promotion keeps using the existing promoter |
| Governance memory / failure memory | `governance/memory.py`, `TradeMemoryRecordORM`, `FailureMemory` | KEEP | transaction-level diagnostics; not a card store |
| LLM-chief in-memory experience | `llm_chief/memory.py` (`ExperienceMemory`), `llm_chief/engines.py` | KEEP (decision-layer only) | keeps the decision context API; no DB ownership, no duplicate persistence |
| LLM-chief knowledge base | `llm_chief/knowledge.py` (`KnowledgeBase`) | KEEP | theory/tool knowledge is distinct from factual experience cards |
| Learning coordinator | `learning_coordinator/coordinator.py` | NOT_USED for truth | report assembler only; V2 write path is the scheduler + pipeline, not this class |
| Decision / evidence trace | `LLMDecisionORM` (`tool_refs_json`, `memory_refs_json`, `episode_refs_json`, `triggered_factors_json`), `LLMDecisionStore`, `DynamicEvidencePackage` | ADAPT | card trace is attached to the existing decision/evidence path; one narrow `growth_card_decision_traces` journal records candidate/selected/excluded details that the current columns cannot express |
| Runtime safety | `risk/engine.py`, `execution/authority.py`, `order/*`, exchange adapters | KEEP, untouchable | V2 modules must not import or mutate these; enforced by import-graph invariant tests |

## 2. Why one narrow version/trace journal is added

`AICompressedExperienceORM` has a unique `rule_id` and a single `version`
column.  It can safely hold the **current** card version (extended in place),
but it cannot hold the full “what changed, why, which episodes, which decision
used which version” history.  The V2 design therefore adds only:

* `growth_card_versions` — append-only version/operation journal (snapshot per
  version; `KEEP` events reuse the current version with a unique proposal hash);
* `growth_card_decision_traces` — per-decision retrieval trace (candidate,
  selected, excluded + reasons, versions, scores, signatures, as-of).

Neither is a second memory store: runtime retrieval reads **only**
`ai_compressed_experience`, and the journals are write-side audit surfaces.

## 3. Duplicate-system exit gate

```text
NO_DUPLICATE_MEMORY_SYSTEM      = PASS  (canonical card memory = ai_compressed_experience; journals are lineage/trace only)
NO_DUPLICATE_REVIEW_SYSTEM      = PASS  (Daily Review + structured review from v1 reused)
NO_DUPLICATE_RETRIEVAL_SYSTEM   = PASS  (HybridRetriever + MemoryGovernor + KnowledgeDecayEngine reused; card policy only adapts them)
NO_DUPLICATE_LIFECYCLE_SYSTEM   = PASS  (card status is a small enum; factor lifecycle keeps FactorLifecycleManager)
NO_DUPLICATE_EPISODE_SYSTEM     = PASS  (trade_episodes remains the only factual episode truth)
```

## 4. Existing gaps closed by G09–G14

| Gap | Closure |
| --- | --- |
| Compressed experience had no trigger/context/scope-aware applicability | G09 card fields + G10 canonical signatures |
| No bounded, explainable runtime retrieval | G11 hard filter + versioned weights + decision trace |
| No evidence-to-card attribution/evolution | G12 attribution + KEEP/UPDATE/CREATE/SPLIT/MERGE/WATCH/RETIRE |
| No card quality/decay/status lifecycle | G13 reuses MemoryGovernor + KnowledgeDecayEngine |
| No end-to-end proof that cards are evidence only | G14 closed-loop + read/write-separation + invariant tests |
