# SYMBOL EPISODIC MEMORY + LLM RETRIEVAL/CACHE FINAL LANDING SPAC

Status: AUTHORITATIVE TASK SPEC
Version: 1.0
Scope: Turbo + LowRisk symbol-level episodic memory, retrieval cache, stable prompt composition, factual historical backfill, PAPER integration and final acceptance
Trading authority: NONE
Risk authority: NONE
Execution authority: NONE
Memory authority: EVIDENCE ONLY

## 1. Purpose

Build and land a durable per-symbol episodic memory layer so each LLM decision can reuse factual historical experience for the same symbol and similar setups without dumping all historical data into every prompt.

The system must retain and retrieve, where factually available:

- prior candidate-selection events;
- candidate reasons and normalized reason codes;
- prior LLM decisions;
- prior trade logic;
- entry, exit and invalidation logic;
- factual orders/fills/trades/episodes;
- rejected candidates and NO_TRADE decisions;
- factual fees, funding, realized PnL, MFE and MAE;
- post-trade review / Growth findings;
- strategy, factor, model and source-version provenance.

Primary goals:

1. improve relevant memory retrieval hit rate;
2. improve internal retrieval-cache hit rate;
3. maximize stable LLM prompt-prefix reuse;
4. measure provider prompt-cache behavior when the provider exposes factual telemetry;
5. reduce duplicated reasoning, token waste and repeated historical scanning;
6. preserve current strategy, Risk and execution authority.

The optimization target is not maximum history in the prompt.

The optimization target is:

~~~text
relevant factual prior experience
---------------------------------
tokens + retrieval latency + LLM latency
~~~

## 2. Existing Stage A reference

Accepted frozen Stage A implementation reference:

~~~text
CANDIDATE_SHA = 10090d23897e443264f46aafe9ba108d848157d5
BRANCH = codex/symbol-memory-stage-a-20261004
~~~

Accepted Stage A evidence:

- episode schema ready;
- candidate-memory schema ready;
- candidate-reason ontology ready;
- deterministic trade-logic signature ready;
- Turbo/LowRisk namespace isolation ready;
- no-future-memory / as-of guard ready;
- version-purity rules ready;
- retriever ready;
- retrieval cache ready;
- symbol memory card ready;
- deterministic prompt serializer ready;
- telemetry structures ready;
- 44 isolated tests PASS;
- Ruff PASS;
- production history not accessed;
- no deployment;
- no strategy/Risk/execution/authority change.

Stage A is a frozen engineering input, not production approval.

## 3. Mandatory migration/storage prerequisite

This SPAC must not start factual historical backfill or production-history integration while the active research DB migration is incomplete.

Known research migration target:

~~~text
/Volumes/My PSSD/ResearchArchive/turbo-deepseek-strategy/state/history/historical_market.db
~~~

Stage B and later require a factual migration handoff proving, at minimum:

~~~text
MIGRATION_ACCEPTANCE = PASS
TARGET_QUICK_CHECK = ok
FULL_FILE_INTEGRITY_MATCH = YES
PATH_SWITCH = PASS
EXTERNAL_VOLUME_UUID_MATCH = YES
EXTERNAL_DB_READ = PASS
EXTERNAL_DB_WRITE = PASS
AUTO_RESUME_USES_EXTERNAL_DB = YES
LOCAL_DB_RECREATED = NO
LOCAL_FALLBACK_CREATED = NO
SPACE_RECOVERY_ACCEPTANCE = PASS
SHARED_HISTORY_RECOVERY_ACCEPTANCE = PASS
READY_FOR_POST_MIGRATION_ACTIVATION = YES
~~~

Until those gates are satisfied:

~~~text
HISTORICAL_BACKFILL_STARTED = NO
PRODUCTION_INDEX_CREATED = NO
PRODUCTION_EMBEDDINGS_CREATED = NO
PRODUCTION_LLM_INTEGRATION = NO
~~~

Do not use memory development as a reason to read or scan either 302GB DB during its migration validation.

## 4. Authority and architecture invariants

The canonical decision chain remains:

~~~text
market facts
→ scanner / factors / tools
→ symbol episodic-memory retrieval
→ LLM
→ Risk
→ execution
→ factual episode closure
→ review / Growth
→ validated memory write
~~~

Memory is evidence only.

Forbidden:

- memory directly emitting orders;
- memory bypassing the LLM;
- memory bypassing Risk;
- memory changing leverage;
- memory promoting a model;
- memory changing execution authority;
- memory treating historical profitability as trade authorization.

Required final invariants:

~~~text
STRATEGY_AUTHORITY_CHANGE = 0
RISK_CHANGE = 0
EXECUTION_CHANGE = 0
LEVERAGE_CHANGE = 0
MODEL_AUTHORITY_CHANGE = 0
~~~

## 5. Strict namespace isolation

Trading experience must be isolated by system.

Required namespaces:

~~~text
turbo/<symbol>
lowrisk/<symbol>
~~~

Shared factual market history may remain shared, but strategy experience may not.

Examples:

- Turbo BTCUSDT episodes must not appear in LowRisk BTCUSDT retrieval results.
- LowRisk rejected candidates must not become Turbo strategy memory.
- SharedMarketHistory may supply factual market context, but never implicitly merges experience namespaces.

Required:

~~~text
CROSS_STRATEGY_EXPERIENCE_CONTAMINATION = 0
~~~

## 6. Final logical architecture

Target architecture:

~~~text
                        Shared factual market data
                                  |
                    +-------------+-------------+
                    |                           |
               Turbo namespace            LowRisk namespace
                    |                           |
          +---------+---------+       +---------+---------+
          |                   |       |                   |
   Symbol Memory Card   Episode Index  Symbol Memory Card  Episode Index
          |                   |       |                   |
          +---------+---------+       +---------+---------+
                    |                           |
              Retrieval Cache             Retrieval Cache
                    |                           |
                    +------------+--------------+
                                 |
                      deterministic prompt blocks
                                 |
                                LLM
                                 |
                                Risk
                                 |
                             Execution
~~~

## 7. Authoritative-source mapping is mandatory

Do not assume the large research historical database is the authoritative truth for trading experience.

Before any backfill, discover and document the authoritative source for every memory field.

At minimum map:

~~~text
candidate selection
candidate reasons
factor snapshot
market regime
LLM request / response
trade plan
Risk approval/rejection
orders
fills
position lifecycle
fees
funding
closed episodes
MFE / MAE
post-trade review
Growth findings
strategy version
factor version
model version
source SHA
~~~

For each source record:

~~~text
FIELD =
AUTHORITATIVE_SOURCE =
TABLE_OR_FILE =
PRIMARY_KEY =
TIME_COLUMN =
ACCOUNT_SCOPE =
SYMBOL_SCOPE =
VERSION_SCOPE =
KNOWN_GAPS =
~~~

Conflicting sources must be reconciled explicitly.

Do not choose the source with the easiest schema merely to increase coverage.

## 8. Factuality rules

Canonical memory records may contain only:

- factual stored values;
- deterministic transforms of factual stored values;
- explicitly labeled review summaries derived from factual evidence.

Missing fields remain:

~~~text
NULL
DATA_UNAVAILABLE
~~~

Forbidden:

- inferring missing candidate reasons from trade outcome;
- generating historical logic after the fact and presenting it as original logic;
- treating hypothetical missed PnL as realized PnL;
- fabricating MFE/MAE;
- fabricating provider-cache telemetry;
- inventing model/version provenance.

## 9. Symbol episode schema

Canonical closed-episode records must support at least:

~~~text
namespace
symbol
episode_id

candidate_at
decision_at
entry_at
exit_at

candidate_reasons
candidate_reason_codes
candidate_reason_fingerprint

market_regime
regime_signature

factor_snapshot_ref
factor_signature

llm_provider
llm_model
llm_decision
llm_reasoning_summary

trade_direction
trade_logic
trade_logic_signature

entry_logic
exit_logic
invalidation_logic

entry_price
exit_price
quantity
notional

gross_pnl
fees
funding
net_pnl
return_bps

MFE
MAE

what_worked
what_failed
post_trade_review

strategy_version
factor_version
model_version
memory_schema_version
source_sha

factual_as_of
closed_at
~~~

Episode identity must be idempotent and unique within namespace.

## 10. Candidate-memory schema

Persist opportunities that did not become trades.

Required fields include:

~~~text
namespace
symbol
candidate_id
candidate_time

candidate_reasons
candidate_reason_codes
candidate_reason_fingerprint

why_selected
llm_decision
why_rejected
risk_rejection
execution_rejection

market_regime
factor_signature

subsequent_observed_market_outcome

strategy_version
model_version
source_sha
factual_as_of
~~~

Counterfactual or observational outcomes must be labeled as such and must never be combined with realized PnL.

## 11. Candidate-reason ontology

Maintain a deterministic canonical ontology including, where factually supported:

~~~text
OFI_IMBALANCE
ORDERBOOK_IMBALANCE
BREAKOUT_ACCELERATION
BREAKOUT_CONTINUATION
BREAKOUT_FAILURE
LIQUIDATION_CLUSTER
CROWDING
FUNDING_DIVERGENCE
OPEN_INTEREST_EXPANSION
VOLUME_ACCELERATION
VOLATILITY_EXPANSION
CROSS_MARKET_CONFIRMATION
MOMENTUM_CONTINUATION
MEAN_REVERSION
REGIME_SHIFT
NEWS_CATALYST
OTHER_FACTUAL
DATA_UNAVAILABLE
~~~

Preserve original source text separately.

candidate_reason_fingerprint must be deterministic from normalized sorted reason codes.

Equivalent reason sets must produce the same fingerprint.

## 12. Trade-logic signature

Store both:

~~~text
trade_logic
trade_logic_signature
~~~

The signature must be deterministic and semantic.

Example:

~~~text
SHORT|BREAKOUT_FAILURE|OFI_REVERSAL|CROWDING_HIGH|VOLATILE_REGIME
~~~

Do not use a raw hash of arbitrary free-form LLM prose as the canonical semantic signature.

## 13. No-future-memory guarantee

For any live, replay or backtest decision:

~~~text
episode.closed_at < current_decision_time
candidate.factual_as_of <= current_decision_time
~~~

Historical outcomes that were not known at the decision timestamp must not be retrievable.

Hard gate:

~~~text
NO_FUTURE_MEMORY = PASS
FUTURE_LEAKAGE = 0
~~~

## 14. Version purity

Every record must retain:

~~~text
strategy_version
factor_version
model_version
source_sha
memory_schema_version
~~~

Retrieval must support:

1. same-generation preference;
2. compatible-generation down-ranking;
3. incompatible-generation exclusion where required.

Do not silently merge materially different historical strategy generations.

## 15. Symbol Memory Card

For each namespace + symbol create a compact deterministic long-term summary.

Required content:

~~~text
namespace
symbol
memory_version

closed_episode_count
candidate_count

historically_effective_reason_patterns
historically_weak_reason_patterns

effective_trade_logic_patterns
weak_trade_logic_patterns

regime_specific_results
frequent_invalidation_reasons
recent_relevant_patterns

sample_count
coverage
last_updated
~~~

Canonical statistics must be calculated deterministically from factual records.

The LLM may summarize already-calculated facts, but it must not generate the canonical statistics itself.

## 16. Memory Card stability

Do not rebuild a Symbol Memory Card every scanner cycle.

Rebuild only when:

- a new factual closed episode matures;
- a candidate outcome becomes finalized;
- a factual correction changes memory;
- schema/version changes;
- an explicit rebuild is authorized.

Goal:

~~~text
SYMBOL_MEMORY_CARD_STABILITY = HIGH
~~~

This is required for stable prompt-prefix reuse.

## 17. Retrieval architecture

Primary structured ranking keys:

~~~text
namespace
symbol
candidate_reason_fingerprint
trade_logic_signature
market_regime
factor_signature
direction
strategy/model compatibility
recency
outcome class
~~~

Default ranking order:

1. namespace exact match;
2. symbol exact match;
3. same/similar candidate-reason fingerprint;
4. same/similar trade-logic signature;
5. same market regime;
6. similar factor state;
7. compatible strategy/model generation;
8. recency.

Top-K must be bounded and configurable.

Default design target may be approximately 5-10 episodes, but final value must be justified by token/latency measurements.

## 18. Survivorship-bias prevention

Retrieval must include relevant:

- winners;
- losers;
- invalidated setups;
- rejected candidates;
- NO_TRADE decisions.

Do not build a successful-trades-only memory.

Required tests must prove loss episodes and rejected candidates remain retrievable.

## 19. Structured retrieval first

Structured factual filters are authoritative for:

- namespace;
- as-of;
- symbol;
- version;
- reason fingerprint;
- logic signature.

Embeddings may supplement later similarity ranking, but may not replace factual constraints.

No production embedding build is authorized until factual backfill and source mapping pass.

## 20. Internal retrieval cache

Cache key must include enough semantic identity to avoid cross-context leakage.

Minimum conceptual key:

~~~text
namespace
symbol
memory_version
candidate_reason_fingerprint
trade_logic_signature
regime_bucket
factor_bucket
retriever_version
~~~

Cached values may include:

~~~text
retrieved_episode_ids
ranking_scores
memory_card_version
retrieved_at
TTL
~~~

Do not cache current live market facts or final current-cycle LLM decisions.

## 21. Cache invalidation

Invalidate symbol-scoped retrieval cache when:

- a new factual episode is added;
- candidate outcome is finalized;
- episode is corrected;
- Symbol Memory Card version changes;
- schema version changes;
- retriever version changes;
- namespace/strategy compatibility rules change.

Do not invalidate global memory for an unrelated symbol update.

Required:

~~~text
SYMBOL_SCOPED_INVALIDATION = PASS
~~~

## 22. Deterministic prompt architecture

LLM prompt composition must use stable ordered blocks:

~~~text
BLOCK A — SYSTEM / AUTHORITY CONTRACT
stable

BLOCK B — STRATEGY CONTRACT
stable

BLOCK C — SYMBOL MEMORY CARD
stable for memory_version

BLOCK D — TOP-K EPISODIC MEMORY
bounded / semi-dynamic

BLOCK E — CURRENT MARKET FACTS
dynamic

BLOCK F — DECISION REQUEST
dynamic
~~~

Use deterministic:

- field ordering;
- JSON ordering;
- reason ordering;
- whitespace;
- number formatting;
- schema/version markers.

Blocks A-C must not be regenerated merely for stylistic variation.

## 23. Three distinct hit-rate layers

Do not report a single ambiguous LLM cache hit rate.

### Layer 1 — Memory Retrieval Hit Rate

Did the system find relevant factual historical experience?

~~~text
memory_queries
memory_hits
memory_misses
MEMORY_RETRIEVAL_HIT_RATE
~~~

### Layer 2 — Internal Retrieval Cache Hit Rate

Did an equivalent retrieval reuse a cached ranking/result?

~~~text
retrieval_cache_hits
retrieval_cache_misses
RETRIEVAL_CACHE_HIT_RATE
~~~

### Layer 3 — Provider Prompt Cache Hit Rate

If the provider exposes factual telemetry:

~~~text
cached_prompt_tokens
uncached_prompt_tokens
provider_cache_hits
provider_cache_misses
PROVIDER_PROMPT_CACHE_HIT_RATE
~~~

If the provider does not expose this:

~~~text
PROVIDER_PROMPT_CACHE_HIT_RATE = DATA_UNAVAILABLE
~~~

Never fabricate provider cache results.

## 24. Prefix-stability telemetry

Even when provider cache telemetry is unavailable, measure deterministic prefix reuse separately.

Record:

~~~text
PROMPT_PREFIX_HASH
PROMPT_PREFIX_VERSION
PREFIX_REUSE_COUNT
PREFIX_CHANGE_REASON
PREFIX_STABILITY_RATE
~~~

This is an engineering proxy only.

It must never be mislabeled as provider cache hit rate.

## 25. Efficiency telemetry

Measure:

~~~text
prompt_tokens_without_memory
prompt_tokens_with_memory
memory_context_tokens

cached_prompt_tokens
uncached_prompt_tokens

retrieval_latency_ms
llm_latency_ms
total_decision_latency_ms

episode_reuse_rate
~~~

Acceptance must verify memory context is bounded and does not cause unbounded prompt growth.

## 26. Canonical memory write path

Only validated factual closure may write canonical memory:

~~~text
execution/candidate facts
→ episode/candidate finalization
→ factual review
→ deterministic normalization
→ validation
→ canonical memory persistence
→ retrieval-index update
→ Symbol Memory Card update
→ symbol-scoped cache invalidation
~~~

Forbidden:

~~~text
LLM free-form output
→ direct canonical-memory write
~~~

## 27. Memory unavailable semantics

If memory backend/index/cache is unavailable, distinguish:

~~~text
MEMORY_UNAVAILABLE
LLM_MEMORY = DEGRADED
~~~

from:

~~~text
NO_RELEVANT_PRIOR_EXPERIENCE
~~~

A backend failure must never be presented to the LLM as factual evidence that no historical experience exists.

Memory failure must not corrupt Risk, execution or market facts.

## 28. Phase/state machine

The authoritative landing sequence is:

~~~text
A  SPAC_WRITTEN
B  MIGRATION_AND_STORAGE_READY
C  AUTHORITATIVE_SOURCE_MAP_PASS
D  FACTUAL_BACKFILL_PASS
E  RETRIEVAL_INDEX_AND_CARD_PASS
F  SHADOW_INTEGRATION_PASS
G  PAPER_LLM_INTEGRATION_PASS
H  A_B_EVALUATION_PASS
I  DURABILITY_AND_FAIL_CLOSED_PASS
J  MEMORY_RUNTIME_SOAK_PASS
K  FINAL_DELIVERY_PASS
~~~

No phase may be credited from synthetic fixtures once factual evidence is required.

## 29. Phase B — migration/storage gate

Before source mapping/backfill:

~~~text
MIGRATION_ACCEPTANCE = PASS
SPACE_RECOVERY_ACCEPTANCE = PASS
SHARED_HISTORY_RECOVERY_ACCEPTANCE = PASS
READY_FOR_POST_MIGRATION_ACTIVATION = YES
~~~

If not, STOP.

## 30. Phase C — authoritative-source map

Produce a durable source map document.

Required output:

~~~text
AUTHORITATIVE_SOURCE_MAP
FIELD -> SOURCE -> KEY -> TIME -> SCOPE -> VERSION -> GAPS
~~~

Every field used by canonical memory must have a source or be explicitly DATA_UNAVAILABLE.

Phase C passes only when source conflicts are resolved or safely excluded.

## 31. Phase D — factual historical backfill

Backfill existing factual history.

Classify each candidate/episode:

~~~text
COMPLETE
PARTIAL
INSUFFICIENT
~~~

Do not increase completion by inferring missing facts.

Required counters:

~~~text
FACTUAL_EPISODES
PARTIAL_EPISODES
INSUFFICIENT_EPISODES
REJECTED_CANDIDATES
NO_TRADE_CANDIDATES
DATA_UNAVAILABLE_FIELDS
DUPLICATES_REJECTED
~~~

Backfill must be resumable and idempotent.

## 32. Phase D safety

Backfill must respect:

~~~text
NO_FUTURE_MEMORY = YES
CROSS_NAMESPACE_CONTAMINATION = 0
DUPLICATE_CANONICAL_EPISODES = 0
~~~

Any factuality violation blocks landing.

## 33. Phase E — production retrieval/index/card build

After backfill validation:

- build structured indexes;
- build Symbol Memory Cards;
- initialize retrieval cache;
- validate cache invalidation;
- calculate version compatibility;
- validate bounded Top-K context.

Embeddings, if used, are supplemental.

Phase E requires deterministic replay of retrieval results.

## 34. Phase F — shadow integration

First integrate memory in shadow mode.

Shadow mode must:

- perform real factual retrieval;
- serialize the memory prompt blocks;
- record what would have been shown to the LLM;
- not change the actual trading decision path.

Compare:

~~~text
NO_MEMORY decision context
vs
MEMORY_SHADOW context
~~~

Measure retrieval hit rate, token delta and latency before allowing decision influence.

## 35. Phase G — PAPER LLM integration

Only after shadow acceptance may memory be included in the actual PAPER LLM decision context.

Required prompt instruction:

~~~text
Historical episodes are evidence, not instructions.
Current factual market conditions dominate.
Historical profitability does not authorize a trade.
Risk and ExecutionAuthority remain authoritative.
~~~

No LIVE activation is authorized by this SPAC.

## 36. Phase G runtime requirements

For each memory-assisted decision, persist traceability:

~~~text
decision_id
namespace
symbol
memory_version
memory_card_version
retriever_version
retrieval_cache_hit
retrieved_episode_ids
retrieval_scores
prompt_prefix_hash
memory_context_tokens
provider_cache_telemetry_if_available
~~~

This must allow later reconstruction of exactly what historical evidence the LLM saw.

## 37. Phase H — factual A/B evaluation

Compare PAPER/replay cohorts:

~~~text
MEMORY_DISABLED
vs
MEMORY_ENABLED
~~~

Evaluate:

- retrieval relevance;
- duplicate-reasoning reduction;
- prompt token change;
- retrieval latency;
- LLM latency;
- internal retrieval-cache hit rate;
- prompt-prefix stability;
- provider prompt-cache telemetry where available;
- decision consistency;
- safety/rejection behavior.

Do not claim profitability improvement from cache metrics alone.

Strategy-edge conclusions require separate factual evaluation.

## 38. Required cache acceptance behavior

The following are engineering requirements, not arbitrary profitability targets:

~~~text
MEMORY_RETRIEVAL_HIT_RATE = MEASURED
RETRIEVAL_CACHE_HIT_RATE = MEASURED
PROVIDER_PROMPT_CACHE_HIT_RATE = MEASURED_OR_DATA_UNAVAILABLE
PREFIX_STABILITY_RATE = MEASURED
~~~

For symbols with eligible historical memory, repeated semantically equivalent retrieval requests must demonstrate non-zero internal cache reuse under controlled PAPER/replay observation.

Do not weaken factual retrieval to inflate hit rate.

## 39. Phase I — durability and failure injection

Test at minimum:

- memory backend unavailable;
- retrieval cache unavailable/corrupt;
- stale cache version;
- duplicate episode replay;
- symbol card rebuild;
- wrong namespace;
- future-dated episode;
- incompatible old strategy version;
- provider cache telemetry absent;
- malformed memory payload;
- partial historical record;
- process restart.

Required:

~~~text
NO_FALSE_HISTORY = YES
NO_CROSS_NAMESPACE_LEAK = YES
NO_FUTURE_LEAK = YES
NO_DIRECT_EXECUTION_PATH = YES
FAIL_CLOSED_OR_DEGRADED_AS_DESIGNED = YES
~~~

## 40. Phase J — memory runtime soak

After PAPER integration and durability pass, run a continuous memory-runtime observation window.

Default target:

~~~text
24 hours
~~~

This is a memory/integration soak, not authorization for LIVE trading.

During the window monitor:

- memory query success/failure;
- retrieval hit/miss;
- cache hit/miss;
- cache invalidation;
- Symbol Memory Card version changes;
- prompt-prefix stability;
- provider cache telemetry if exposed;
- token/latency;
- memory backend health;
- namespace isolation;
- as-of correctness;
- PAPER trading runtime health.

Any source/schema/deployment identity change that materially affects memory semantics invalidates the memory soak.

## 41. Final test matrix

Required deterministic tests include:

~~~text
NO_FUTURE_MEMORY = PASS
NO_CROSS_NAMESPACE_CONTAMINATION = PASS
DUPLICATE_EPISODE_INSERT = PASS
DETERMINISTIC_REASON_FINGERPRINT = PASS
DETERMINISTIC_LOGIC_SIGNATURE = PASS
DETERMINISTIC_PROMPT_PREFIX = PASS
SYMBOL_SCOPED_INVALIDATION = PASS
MEMORY_UNAVAILABLE_SEMANTICS = PASS
LOSS_EPISODE_RETRIEVAL = PASS
REJECTED_CANDIDATE_RETRIEVAL = PASS
OLD_VERSION_DOWNRANK = PASS
EMPTY_RESULT_NOT_VACUOUS_PASS = PASS
WRONG_NAMESPACE_BLOCKED = PASS
FUTURE_DATED_EPISODE_BLOCKED = PASS
MALFORMED_MEMORY_FAILS_SAFE = PASS
~~~

## 42. Explicit non-goals

This SPAC does NOT authorize:

- LIVE trading;
- changing strategy direction logic;
- changing Risk;
- changing leverage;
- changing execution authority;
- using memory as a voting engine;
- treating retrieval frequency as trade confidence;
- mixing Turbo and LowRisk experience;
- changing Shared History write authority;
- modifying the 300-second Shared History freshness threshold;
- weakening existing FULL_MARKET ownership/lease protections;
- using future outcomes in replay;
- fabricating provider-cache telemetry.

## 43. Rollback

Memory integration must be feature-gated.

Required rollback must allow:

~~~text
MEMORY_ENABLED = false
~~~

while preserving:

- market-data runtime;
- LLM baseline decision path;
- Risk;
- execution;
- factual memory data already written.

Rollback must not require deleting canonical memory.

## 44. Final deliverables

At final landing produce:

1. authoritative source map;
2. canonical memory schema/version;
3. historical backfill receipt;
4. retrieval/index/card receipt;
5. PAPER integration receipt;
6. A/B evaluation report;
7. durability/failure-injection receipt;
8. memory runtime soak receipt;
9. final cache/latency/token metrics;
10. final landing receipt.

## 45. Required final receipt

~~~text
SYMBOL_EPISODIC_MEMORY_LLM_CACHE_FINAL_RECEIPT

PROVENANCE
------------------------------------------------
SPAC_BRANCH =
SPAC_COMMIT =
STAGE_A_SHA =
FINAL_IMPLEMENTATION_SHA =
DEPLOYED_PAPER_SHA =

PREREQUISITES
------------------------------------------------
MIGRATION_ACCEPTANCE =
SPACE_RECOVERY_ACCEPTANCE =
SHARED_HISTORY_RECOVERY_ACCEPTANCE =

SOURCE MAP
------------------------------------------------
AUTHORITATIVE_SOURCE_MAP =
SOURCE_CONFLICTS =
UNRESOLVED_FIELDS =

BACKFILL
------------------------------------------------
FACTUAL_EPISODES =
PARTIAL_EPISODES =
INSUFFICIENT_EPISODES =
REJECTED_CANDIDATES =
NO_TRADE_CANDIDATES =
DATA_UNAVAILABLE_FIELDS =
DUPLICATES_REJECTED =

NAMESPACE
------------------------------------------------
TURBO_ISOLATED =
LOWRISK_ISOLATED =
CROSS_CONTAMINATION =

RETRIEVAL
------------------------------------------------
RETRIEVER_VERSION =
TOP_K =
AS_OF_ENFORCED =
VERSION_PURITY =
SYMBOL_MEMORY_CARD =
MEMORY_CARD_VERSION =

CACHE
------------------------------------------------
RETRIEVAL_CACHE =
RETRIEVAL_CACHE_HIT_RATE =
CACHE_INVALIDATION =
PREFIX_STABILITY_RATE =

PROVIDER
------------------------------------------------
LLM_PROVIDER =
LLM_MODEL =
PROVIDER_PROMPT_CACHE_TELEMETRY =
PROVIDER_PROMPT_CACHE_HIT_RATE =

EFFICIENCY
------------------------------------------------
MEMORY_RETRIEVAL_HIT_RATE =
EPISODE_REUSE_RATE =
AVERAGE_MEMORY_CONTEXT_TOKENS =
TOKEN_DELTA =
RETRIEVAL_LATENCY_P50 =
RETRIEVAL_LATENCY_P95 =
LLM_LATENCY_DELTA =

INTEGRATION
------------------------------------------------
SHADOW_INTEGRATION =
PAPER_LLM_INTEGRATION =
MEMORY_FEATURE_GATE =
MEMORY_ROLLBACK_TEST =

A_B
------------------------------------------------
MEMORY_DISABLED_COHORT =
MEMORY_ENABLED_COHORT =
RETRIEVAL_RELEVANCE =
DECISION_CONSISTENCY =
SAFETY_REGRESSION =

DURABILITY
------------------------------------------------
NO_FUTURE_LEAKAGE =
NO_CROSS_NAMESPACE_LEAK =
NO_FAKE_MEMORY =
FAILURE_INJECTION =
PROCESS_RESTART_RECOVERY =

SOAK
------------------------------------------------
MEMORY_SOAK_START =
MEMORY_SOAK_END =
MEMORY_SOAK_DURATION =
MEMORY_SOAK_BREACHES =
MEMORY_SOAK_ACCEPTANCE =

AUTHORITY
------------------------------------------------
STRATEGY_AUTHORITY_CHANGE = 0
RISK_CHANGE = 0
EXECUTION_CHANGE = 0
LEVERAGE_CHANGE = 0
MODEL_AUTHORITY_CHANGE = 0

FINAL
------------------------------------------------
STAGE_A_ACCEPTANCE =
STAGE_B_BACKFILL_ACCEPTANCE =
RETRIEVAL_ACCEPTANCE =
PAPER_INTEGRATION_ACCEPTANCE =
A_B_ACCEPTANCE =
DURABILITY_ACCEPTANCE =
FINAL_DELIVERY_ACCEPTANCE =

BLOCKERS =
NEXT_REQUIRED_ACTION =
~~~

## 46. Final state-machine acceptance

Final delivery may be declared only when:

~~~text
A SPAC_WRITTEN = PASS
B MIGRATION_AND_STORAGE_READY = PASS
C AUTHORITATIVE_SOURCE_MAP_PASS = PASS
D FACTUAL_BACKFILL_PASS = PASS
E RETRIEVAL_INDEX_AND_CARD_PASS = PASS
F SHADOW_INTEGRATION_PASS = PASS
G PAPER_LLM_INTEGRATION_PASS = PASS
H A_B_EVALUATION_PASS = PASS
I DURABILITY_AND_FAIL_CLOSED_PASS = PASS
J MEMORY_RUNTIME_SOAK_PASS = PASS
K FINAL_DELIVERY_PASS = PASS
~~~

No skipped phase may be treated as implicitly passed.

## 47. Governing principle

Build memory to improve factual reuse, not to increase historical influence for its own sake.

The system must prefer:

~~~text
small, relevant, factual, version-compatible, as-of-correct memory
~~~

over:

~~~text
large, stale, mixed-version, survivorship-biased history dumps
~~~

Final success means the LLM can repeatedly receive the right prior experience with bounded cost, clear provenance, stable prompt structure and zero change to Risk/execution authority.
