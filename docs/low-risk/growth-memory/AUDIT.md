# Growth / Memory Forensic Audit (Phase A)

STARTING_SHA: `8dc0ca43451372b877f95bf7bc054170492a04ec`
Task branch: `codex/low-risk-growth-memory-autonomous-v2`
PAPER only. Growth authority is LEARNING_ONLY; can_modify_core is always false.

## Module inventory

| Component | Current factual role | Action |
|---|---|---|
| `governance/memory_persistence.py` | writer/reader of `trade_memory_records` | KEEP |
| `governance/{daily_review,scheduler,trade_review,factual_learning}.py` | daily review and factual learning helpers | KEEP / audit wiring |
| `learning/review_taxonomy.py` | ReviewType/ReviewFinding/classify_review (7 types) | KEEP as taxonomy |
| `learning/memory_speeds.py` | in-memory MemoryRecord, classify_speed, thresholds 20/3 | ADAPT: >=100 samples, post-cost, multi-regime, persisted |
| `learning/growth_persistence.py` | writes `ai_trade_reviews` (episode_id unique) | EXTEND: episode summary; add derived event reviews |
| `learning/thesis_discipline.py` | POSSIBLE_THESIS_RATIONALIZATION | KEEP |
| `learning/growth_report.py` | report assembly | KEEP |
| `ai_memory/market_memory.py` | in-memory dict, find_similar | DEPRECATE as truth; optional index only |
| `llm_chief/memory.py` | in-memory ExperienceMemory, compress min 3 | DEPRECATE as truth; compressor must become provenance-gated |
| `llm_chief/persistence.py` | writers for patterns/profiles/compressed experience | ADAPT: no production callers found; wire autonomous writers |
| `llm_chief/context_loader.py` | SQL reads of compressed/profile/pattern | EXTEND: canonical retriever, persist memory refs per decision |
| `vector_memory/vector_store.py` | MemoryVectorStore is in-memory | ADAPT: persistent index bound to DB generation |
| `vector_memory/retrieval.py` | HybridRetriever exists but has no src/scripts instantiation | ADAPT into canonical retriever |
| `market_data/opportunity/daily_freeze.py` | freezes candidates as of the freeze moment | ADAPT: completed-day full ledger |
| `market_data/opportunity/outcomes.py` | 15m..24h outcomes, one shared path_prices | ADAPT: per-horizon factual target and path |
| `scripts/freeze_daily_top10.py` | reads live `/opportunity/candidates` | ADAPT: read immutable ledger |
| `scripts/growth_lifecycle_review.py` | reviews only newest episode (LIMIT 1) | DEPRECATE as scheduler; replace incremental engine |

## Persistence tables

| Table | Action |
|---|---|
| `trade_memory_records` | KEEP |
| `ai_trade_reviews` | KEEP as episode summary (episode_id unique) |
| `ai_market_patterns` | EXTEND: asset x regime x strategy x horizon x setup signature, direction separate |
| `ai_coin_profiles` | EXTEND: distributions, strategy performance, post-cost expectancy, sample tier |
| `ai_compressed_experience` | EXTEND: provenance, sample tier, contradictions, versioning |
| `daily_opportunity_top10` | EXTEND: opportunity-level identity, full evidence refs, first-freeze immutable |
| `opportunity_outcomes` | EXTEND: per-horizon path, alignment metadata, direction source |
| `scan_snapshots` | KEEP/EXTEND as derived full-day opportunity observation ledger |
| new `growth_event_reviews` (derived) | ADD: episode_id + event_id/decision_id + review_type + review_version |

## Factual answers required by the directive

- Current factual writers: `MemoryPersistence.save_trade_memory` (trade_memory_records),
  `GrowthPersistence` (ai_trade_reviews), ML collector (`scan_snapshots` + `scan_snapshot_labels`),
  `OpportunityOutcomeRecorder` (opportunity_outcomes, manual callers).
- Pattern/profile/compressed writers exist in `llm_chief/persistence.py` but have **no automatic caller**;
  they are effectively dormant.
- In-memory only: `ExperienceMemory`, `MarketMemory`, `MemoryVectorStore`, `MemoryRecord` speeds.
- CoinProfile has NO automatic writer.
- AICompressedExperience has NO automatic writer; in-memory compress uses min_samples=3.
- MemorySpeed is NOT persisted.
- OpportunityOutcome has NO autonomous maturer for Top10 rows.
- The 7 review taxonomy is not automatically produced; the script reviews only the newest episode.
- Retrieval is NOT restart-safe: the vector store is in-memory and HybridRetriever has no production wiring.
- Parallel memory truth stores exist (`ai_memory`, `llm_chief/memory`, `vector_memory`) and must become
  derived indexes over SQL, which stays canonical.
- Top10 today freezes the live API snapshot at run time, not the completed trading day.

## Why a derived observation ledger is justified

`scan_snapshots` already persists decision-time candidate/control features each cycle with a unique
`snapshot_id`, but it lacks trading-day partitioning, snapshot hash/version, model-evidence refs and
decision refs. Rather than a second scanner, EXTEND `scan_snapshots` (additive migration) and make it
the LEARNING_ONLY full-day opportunity observation ledger.

## Phase plan

- B: extend `scan_snapshots` into a full-day immutable ledger; completed-day Top10 from it.
- C: per-horizon factual maturer with alignment metadata and direction source.
- D: incremental `growth_event_reviews` counterfactual engine (unique per event/type/version).
- E: persistent memory speeds and sample tiers (FAST/PATTERN/VALIDATED; 100+ sample gate).
- F: pattern identity, coin profiles, compressed experience with provenance.
- G: persistent canonical retriever over SQL plus derived vector index, bound to DB generation.
- H: retrieval observability counters and `/growth/status` read-only API.
- I: `com.lowrisk.growth` launchd worker, restart-safe cursors, `data/growth/` state.
- J: optional read-only Flash advisory (disabled pending canonical resolver merge).

No Growth component may submit orders or modify Risk/Execution/Core LLM/ML training.
