# Growth System V2 — Architecture

Scope: extend the existing factual learning loop with **Adaptive Experience
Cards**.  No second Skill/Memory/Review/Retrieval/Lifecycle system is created.

## Components

```text
FACTUAL EPISODE (trade_episodes, canonical)
        │
        ▼
DAILY REVIEW + STRUCTURED REVIEW (v1 pipeline, claim/fence reused)
        │  lessons / patterns (growth_lessons / growth_patterns)
        ▼
ATTRIBUTION (growth_attribution.py)
        │  axes + OUTCOME_ASSOCIATED (never CAUSALLY_PROVEN from PnL alone)
        ▼
CARD EVOLUTION (growth_experience.py)
        │  KEEP/UPDATE/CREATE/SPLIT/MERGE/WATCH/RETIRE
        ▼
CANONICAL CARD MEMORY (ai_compressed_experience, extended in place)
        │  current version
        ├── growth_card_versions         (append-only version/operation journal)
        └── growth_card_decision_traces  (per-decision retrieval audit)
        │
        ▼  READ-ONLY
TRIGGER + CONTEXT (growth_v2_contracts.py)
        ▼
HARD FILTER → HybridRetriever semantic → MemoryGovernor quality
             → KnowledgeDecayEngine freshness → bounded ranking
        ▼
Top-K cards (≤ policy limit, token-bounded)
        ▼
ChiefTrader EvidencePackage (evidence, never commands)
        ▼
LLM decision + decision trace (card ids + versions + excluded reasons)
        │
        ▼
next FACTUAL EPISODE → revalidation loop
```

## Read / write separation

| Path | Owner | Allowed to mutate cards? |
| --- | --- | --- |
| Trading runtime (`ExperienceCardRetriever`, `register_experience_card_tool`) | runtime | **NO** — read-only; no imports of `growth_experience` |
| Daily Review / low-frequency learner (`DailyCardLearner`, `AdaptiveCardStore`) | learning | yes, via explicit operations and fence |
| Decision layer (`CardDecisionTraceStore`) | runtime | writes only the trace table, never canonical card state |
| Risk / Execution (`risk/*`, `execution/*`, `order/*`) | unchanged | never imported by V2 modules |

## Status model

```text
CANDIDATE → ACTIVE → WATCH → STALE → RETIRED
```

Small enum only; factor lifecycle remains owned by `FactorLifecycleManager`.
Status transitions and quality/decay are computed by
`growth_card_quality.py` using the existing `MemoryGovernor` and
`KnowledgeDecayEngine`.

## Reused existing infrastructure

See `REUSE_MATRIX.md`.  Key reuse: `HybridRetriever`, `MemoryGovernor`,
`KnowledgeDecayEngine`, `LLMToolRegistry`, `DynamicEvidencePackage`,
`LLMDecisionStore`, `MemoryPersistence` day claim/fence, `TradeEpisodeStore`,
`DailyReviewScheduler`, structured review (`growth_review`), pattern/lesson
publishing (`growth_knowledge`), metrics (`growth_metrics`).

## New narrow modules (V2)

| Module | Purpose |
| --- | --- |
| `growth_v2_contracts.py` | Trigger/Context/Card/Proposal/Retrieval domain |
| `growth_card_view.py` | read-only ORM/snapshot ↔ domain mapping |
| `growth_card_quality.py` | quality axes + decay status policy |
| `growth_experience.py` | canonical store + evolution operations + version journal |
| `growth_card_retrieval.py` | hard filter + bounded ranking + decision trace + tool registration |
| `growth_attribution.py` | attribution axes + Daily-Review card learner |
| `growth_v2_migration.py` | draft additive migration helper for the extended table |
