# LOW-RISK UNIFIED MARKET CONTEXT V1 — SPAC

**Status:** FROZEN TARGET ARCHITECTURE  
**Scope:** Low-Risk Market Data / Context / Intelligence Integration  
**Trading Authority:** UNCHANGED  
**Risk Authority:** UNCHANGED  
**Execution Authority:** UNCHANGED  
**Historical System:** EXTERNAL SHARED DATA SERVICE  
**Historical Trading Authority:** NONE  

**Reference Low-Risk candidate:**  
`6ced1da3008edf49eac086596ff4f208ee7b0821`

**External Shared Market History contract:**  
`docs/shared-market-history/SHARED_MARKET_HISTORY_SPAC.md`

---

## 0. Purpose

Introduce one unified market-context layer between factual market data and Low-Risk intelligence.

The target architecture is:

```text
Layer 1 — DATA
  OKX realtime
  Shared Market History

        ↓

Layer 2 — CONTEXT
  Unified Market Context

        ↓

Layer 3 — INTELLIGENCE
  Scanner
  Expert #01–#24
  Model #21
  Model #25
  Core LLM
  Growth / Research

        ↓

Layer 4 — AUTHORITY
  TradePlan
  Risk
  ExecutionAuthority
  Base Exit
  Broker
```

The objective is to give all intelligence components access to one coherent,
versioned and auditable market truth without changing trading authority.

---

## 1. Non-Negotiable Core Architecture

The following Low-Risk authority chain MUST NOT change:

```text
Market Facts
    ↓
Expert / ML Evidence
    ↓
Core LLM
    ↓
TradePlan
    ↓
Risk
    ↓
ExecutionAuthority
    ↓
Broker
```

Core LLM remains the only intelligence component allowed to originate new risk.

Models #01–#25 remain `EVIDENCE_ONLY`.

Shared Market History remains `DATA_ONLY`.

Unified Market Context remains `CONTEXT_ONLY`.

Neither history nor context may:

- create orders;
- choose position direction;
- choose leverage;
- choose size;
- originate OPEN;
- originate ADD;
- originate HEDGE;
- originate REVERSE;
- bypass Core LLM;
- bypass Risk;
- bypass ExecutionAuthority;
- modify Base Exit;
- promote ML models;
- enable LIVE.

---

## 2. Old Architecture

Historically, different components obtain market information independently:

```text
OKX realtime
 ├── Scanner
 ├── Expert Engine
 ├── ML snapshot collector
 ├── Core LLM tools
 └── other consumers
```

This creates risks of:

- duplicated market queries;
- inconsistent context;
- inconsistent historical windows;
- duplicated feature computation;
- different freshness semantics;
- model-specific historical truth;
- difficult AS-OF enforcement.

---

## 3. Target Architecture

```text
                  OKX REALTIME
                      │
                      ▼
             RealtimeContextAdapter
                      │
                      │
Shared Market History │
Parquet + DuckDB      │
127.0.0.1:8770        │
        │             │
        ▼             │
 SharedHistoryClient  │
        │             │
        └──────┬──────┘
               ▼
     UnifiedMarketContextProvider
               │
      strict AS-OF enforcement
               │
        ┌──────┼──────┐
        │      │      │
       FAST  MEDIUM  LONG
        │      │      │
        └──────┼──────┘
               ▼
          MarketContext
               │
      ┌────────┼─────────┐
      │        │         │
   Scanner  Experts    ML #21
      │      #01–24      │
      │                  ▼
      │                 #25
      └────────┬─────────┘
               ▼
        Evidence Package
               │
               ▼
            Core LLM
       summary + tools
               │
               ▼
           TradePlan
               │
             Risk
               │
       ExecutionAuthority
               │
             Broker
```

---

## 4. Project Boundaries

Shared Market History is an independent service.

Default project:

`/Users/huhongjie/Documents/ChatGPT/shared-market-history`

Default API:

`http://127.0.0.1:8770`

Low-Risk MUST NOT directly open Shared Market History Parquet or DuckDB files.

Low-Risk consumes Shared Market History only through a versioned client/API.

Low-Risk realtime market data remains sourced through its canonical realtime
market feed.

---

## 5. Low-Risk Directory Target

Add:

`src/crypto_trader/market_context/`

Target structure:

```text
market_context/
├── __init__.py
├── provider.py
├── models.py
├── profiles.py
├── exceptions.py
├── asof.py
├── freshness.py
├── coverage.py
├── provenance.py
│
├── realtime/
│   ├── __init__.py
│   ├── adapter.py
│   ├── snapshot.py
│   └── normalizer.py
│
├── historical/
│   ├── __init__.py
│   ├── client.py
│   ├── schemas.py
│   ├── candles.py
│   ├── funding.py
│   ├── open_interest.py
│   ├── features.py
│   ├── regime.py
│   └── analogs.py
│
├── views/
│   ├── __init__.py
│   ├── fast.py
│   ├── medium.py
│   ├── long.py
│   ├── scanner.py
│   ├── expert.py
│   ├── model21.py
│   ├── model25.py
│   └── llm.py
│
├── cache/
│   ├── __init__.py
│   ├── memory.py
│   ├── keys.py
│   └── policy.py
│
├── tools/
│   ├── __init__.py
│   ├── long_term_context.py
│   ├── historical_candles.py
│   ├── historical_analogs.py
│   ├── regime_history.py
│   └── market_history_summary.py
│
├── observability/
│   ├── __init__.py
│   ├── health.py
│   ├── metrics.py
│   └── audit.py
│
└── versioning/
    ├── __init__.py
    ├── schema.py
    └── fingerprint.py
```

Existing:

`market_data/`  
`factors/`  
`ml_*`  
`llm_chief/`  
`risk/`  
`execution/`  
`runtime/`

must remain in their current architectural roles.

---

## 6. Single Canonical Entry Point

Canonical API inside Low-Risk:

`UnifiedMarketContextProvider`

Conceptual interface:

```python
async def get_context(
    symbol: str,
    *,
    as_of: datetime,
    profile: ContextProfile,
) -> MarketContext:
    ...
```

Consumers MUST NOT need to know whether data originated from:

- OKX realtime;
- local cache;
- Shared Market History;
- Parquet;
- DuckDB.

---

## 7. Market Context Identity

Every `MarketContext` must contain:

- symbol;
- as_of;
- context_schema_version;
- feature_schema_version;
- historical_schema_version;
- context_fingerprint;
- generated_at.

The context object must be immutable after generation.

---

## 8. Fast Context

FAST context covers approximately seconds → hours.

Possible factual fields include:

- price;
- mark_price;
- index_price;
- best_bid;
- best_ask;
- spread_bps;
- L1 imbalance;
- L5 imbalance;
- microprice;
- CVD;
- taker_buy_volume;
- taker_sell_volume;
- trade_count;
- trade_notional;
- large_trade_count;
- price_velocity;
- current funding;
- current OI;
- 1m return;
- 5m return;
- 15m return;
- 1h return;
- 4h return.

Only currently available factual fields may be populated.

---

## 9. Medium Context

MEDIUM context covers approximately hours → 30 days.

Fields may include:

- trend_1d;
- trend_7d;
- trend_30d;
- ATR;
- realized volatility;
- volume regime;
- volatility regime;
- volume_percentile_30d;
- volatility_percentile_30d;
- funding trend;
- funding_percentile_30d;
- OI trend;
- oi_percentile_30d;
- local high distance;
- local low distance.

---

## 10. Long Context

LONG context covers approximately 30 days → all factual history.

Fields may include:

- trend_90d;
- trend_1y;
- price_percentile_1y;
- price_percentile_all;
- volatility_percentile_1y;
- volume_percentile_1y;
- drawdown_from_ath;
- distance_from_ath;
- distance_from_historical_low;
- funding_percentile_90d;
- funding_percentile_2y;
- oi_percentile_30d;
- oi_percentile_1y;
- regime_4h;
- regime_1d;
- instrument_age_days;
- historical cycle/regime context;
- historical analog summaries.

---

## 11. AS-OF Contract

This is a HARD scientific invariant.

For every request:

`requested_as_of = decision/snapshot time`

Every factual source contributing to the result must satisfy:

`source_timestamp <= requested_as_of`

And:

`max_source_timestamp <= requested_as_of`

If violated:

`ASOF_VIOLATION`

The provider must fail closed for the offending historical component.

Never silently expose later data.

This applies to:

- training;
- validation;
- historical reconstruction;
- backtest;
- shadow;
- runtime;
- LLM tools;
- historical analogs.

---

## 12. Provenance

Every context should expose:

- realtime_source;
- historical_source;
- max_source_timestamp;
- coverage;
- freshness;
- feature versions;
- source dataset versions.

Historical-derived values must be distinguishable from realtime observations.

---

## 13. Coverage

Each requested component must return one of:

- `COMPLETE`
- `PARTIAL_HISTORY`
- `DATA_UNAVAILABLE`
- `STALE`

Missing data must remain explicit.

No synthetic substitution.

---

## 14. Source Precedence

Realtime truth:

canonical Low-Risk realtime market feed.

Historical truth:

Shared Market History.

The Context Provider merges but does not replace realtime market facts with
historical snapshots when factual realtime data exists.

Historical service failure must not silently generate fake realtime values.

---

## 15. Consumer Profiles

Canonical initial profiles:

- SCANNER;
- EXPERT;
- MODEL_21;
- MODEL_25;
- CORE_LLM;
- LABELER;
- RESEARCH;
- GROWTH.

Profiles control:

- which context groups are requested;
- maximum historical depth;
- expensive feature access;
- analog access;
- output size.

Profiles do NOT grant trading authority.

---

## 16. Scanner Profile

Scanner may consume:

- realtime facts;
- 24h facts;
- medium-term regime;
- volume percentile;
- volatility percentile;
- selected long-term facts.

Purpose:

candidate nomination and ranking evidence.

Historical context must NOT become deterministic directional trade authority.

---

## 17. Expert #01–#24 Profile

All expert models may access historical context through a common interface.

Each model should request only the history relevant to its defined method.

Do NOT pass the complete raw historical lake to every model.

Possible inputs:

- FAST;
- MEDIUM;
- LONG;
- REGIME.

Expert outputs remain `EVIDENCE_ONLY`.

---

## 18. Model #21

#21 remains the Order Flow ML model.

Its primary information remains:

- microstructure;
- order flow;
- spread;
- CVD;
- imbalance;
- taker flow;
- price velocity;
- execution economics.

Historical context may provide slower background features such as:

- 30d volatility percentile;
- 1y volatility percentile;
- 30d/90d/1y trend;
- 1y price percentile;
- ATH drawdown;
- funding percentiles;
- OI percentiles;
- 4h regime;
- 1d regime.

New feature schema must be versioned.

Example target feature version:

`order-flow-v3-long-context`

Adding historical context requires:

- new feature_schema_hash;
- new dataset_version;
- new artifact;
- new training_cutoff_ts;
- new true-forward evidence.

Historical replay cannot satisfy true-forward promotion.

---

## 19. Model #25

#25 is the Meta Forecast model.

It may consume the broadest context.

Inputs may include:

- #01–#24 frozen evidence;
- #21 output;
- FAST context;
- MEDIUM context;
- LONG context;
- market regime;
- liquidity;
- cost;
- historical analog summaries;
- historical model reliability.

#25 may never include:

- future outcomes;
- post-decision data;
- its own outcome;
- later Growth knowledge.

#25 remains `EVIDENCE_ONLY`.

---

## 20. Core LLM Context

Core LLM should NOT receive raw full history by default.

Default automatic context:

- compressed current market summary;
- medium-term context;
- long-term context;
- regime;
- historical percentile summary;
- historical analog summary.

Target size:

small enough to avoid unnecessary token expansion.

The Core LLM must have controlled historical tools for deeper access.

---

## 21. Core LLM Historical Tools

Allowlisted tools may include:

- `get_long_term_context`;
- `get_historical_candles`;
- `get_historical_analogs`;
- `get_regime_history`;
- `get_market_history_summary`.

The Core LLM MUST NOT receive:

- raw SQL;
- DuckDB shell;
- filesystem access;
- arbitrary Parquet access.

Every historical tool must enforce:

- symbol bounds;
- timeframe bounds;
- row limits;
- AS-OF;
- response-size bounds;
- tool budget.

---

## 22. Labeler

Label-v3 remains the canonical label logic unless separately superseded.

Historical factual target observations should migrate to Shared Market History.

Example:

```text
snapshot T0
+
forward horizon H
        ↓
Shared Historical Data
        ↓
first factual closed 1m candle at/after T0+H within canonical tolerance
```

Historical service use must not change label semantics.

Network/API implementation changes must not silently alter scientific label
meaning.

---

## 23. Growth / Research

Growth and Research may use Historical Context for:

- analysis;
- post-trade study;
- market-regime research;
- model-performance analysis.

Growth remains non-trading.

Historical evidence must not silently mutate active trading rules.

---

## 24. Historical Analogs

Historical analog search may be provided by Shared Market History or the
Context layer using deterministic feature vectors.

Example:

```text
current:
4h expansion
1d uptrend
funding percentile > 90
OI percentile > 80
volume percentile > 85
```

Output may include:

- analog_count;
- similarity distribution;
- forward return 1h;
- forward return 4h;
- forward return 24h;
- downside distribution;
- upside distribution.

All analog calculations for historical decision reconstruction MUST obey AS-OF.

---

## 25. Model Reliability History

Low-Risk may maintain a separate intelligence-performance layer.

Possible facts:

- Model #N performance by regime;
- Model #N performance by liquidity class;
- Model #N calibration by context;
- Model #N historical edge by horizon.

This is not the responsibility of raw Shared Market History.

It belongs to Low-Risk ML/research evidence.

#25 and Core LLM may consume summarized model reliability.

---

## 26. Cache Policy

Market Context may cache:

- latest context;
- recent historical summaries;
- features;
- regime;
- metadata.

It must NOT cache the entire market-history lake in RAM.

Cache must be:

- bounded;
- observable;
- version-aware;
- AS-OF-aware.

A context generated for a later AS-OF must never satisfy an earlier AS-OF query.

---

## 27. Failure / Degradation Policy

Shared Market History unavailable:

realtime trading infrastructure may remain alive.

Historical components become:

`DATA_UNAVAILABLE`

or:

`STALE`

Do not fabricate values.

Profiles may define required vs optional fields.

Historical failure must not crash unrelated:

- Risk;
- Execution;
- Position management;
- Base Exit.

Existing protective actions must continue.

---

## 28. Realtime Compatibility

The initial Market Context implementation must adapt the existing realtime
feed rather than replacing it.

Phase-one requirement:

new realtime context output must be behaviorally equivalent to existing
canonical realtime facts.

This allows migration without rewriting the realtime feed.

---

## 29. Observability

Minimum metrics:

- contexts_generated;
- context_latency_p50;
- context_latency_p95;
- realtime_context_requests;
- historical_context_requests;
- historical_cache_hits;
- scanner_context_requests;
- expert_context_requests;
- model21_context_requests;
- model25_context_requests;
- llm_context_requests;
- asof_queries;
- asof_violations;
- partial_contexts;
- data_unavailable;
- stale_contexts;
- historical_service_errors;
- context_schema_version;
- feature_schema_versions.

---

## 30. Versioning

Every semantic change requires versioning.

At minimum:

- context_schema_version;
- feature_schema_version;
- historical_schema_version.

Context fingerprint must deterministically identify the factual input/view.

Do not silently change old semantics.

---

## 31. Shared Market History Required Interface

The Low-Risk Context layer reserves integration against:

```text
GET  /v1/health
GET  /v1/stats
GET  /v1/universe
GET  /v1/metadata/{symbol}

GET  /v1/candles
GET  /v1/latest

GET  /v1/features/{symbol}
GET  /v1/regime/{symbol}

GET  /v1/funding/{symbol}
GET  /v1/open-interest/{symbol}

GET  /v1/analogs/{symbol}

POST /v1/batch/latest
POST /v1/batch/features
```

All historical endpoints used by Low-Risk must support strict AS-OF semantics
where scientifically applicable.

This interface is intentionally reserved here so the external Shared Market
History implementation can be completed independently.

Low-Risk must not assume the external service is complete until contract
acceptance passes.

---

## 32. Required Response Metadata

Historical responses must expose:

- source;
- symbol;
- requested_as_of;
- max_source_timestamp;
- first_timestamp;
- last_timestamp;
- row_count;
- coverage;
- freshness;
- schema_version;
- generated_at.

No request may hide that history is incomplete.

---

## 33. Resource Policy

The Context layer must remain lightweight.

Expensive historical computation should remain in Shared Market History.

Low-Risk Context should primarily:

- fetch;
- merge;
- validate;
- version;
- cache bounded summaries.

Do not repeatedly calculate 1-year/3-year statistics in:

- Scanner;
- #21;
- #25;
- Core LLM;

independently.

---

## 34. Migration Principle

Migration must be incremental.

Do not remove legacy market access first.

Migration sequence:

1. build new context layer;
2. run shadow;
3. prove realtime parity;
4. connect history;
5. migrate consumers individually;
6. compare old/new evidence;
7. activate new consumer path;
8. retire legacy paths only after proof.

---

## 35. Current Candidate Protection

Do not modify or redeploy the existing Low-Risk candidate:

`6ced1da3008edf49eac086596ff4f208ee7b0821`

while it remains an acceptance reference.

New Market Context integration requires:

- new branch;
- new SHA;
- full regression;
- PAPER verification;
- new acceptance clock / soak as required.

---

## 36. Implementation Phases

### Phase A — Context Skeleton + Schemas

Create the new package, contracts, versioning, profiles and tests.

### Phase B — Realtime Adapter and Parity Shadow

Adapt the existing realtime feed. Do not create a second realtime OKX stack.

### Phase C — Shared History Client

Implement the reserved client contract without exposing DuckDB/Parquet details.

### Phase D — AS-OF / Coverage / Provenance

Centralize no-future-leakage enforcement.

### Phase E — FAST / MEDIUM / LONG Views

Implement reusable context views.

### Phase F — Scanner + Experts Shadow Integration

Generate new context in parallel without changing decisions.

### Phase G — #21 Long-Context Research Version

Create a new feature schema and scientifically compare with the current #21.

### Phase H — #25 Long-Context Research Version

Only after the canonical #21 prerequisite is satisfied.

### Phase I — Core LLM Summary + Historical Tools

Give the LLM compressed context by default and bounded tools for deeper access.

### Phase J — Labeler Historical Source Migration

Use Shared Market History for factual historical observations without changing
label-v3 semantics.

### Phase K — Runtime Integration

Inject one unified provider into consumers.

### Phase L — Full Exact-SHA Acceptance

Run complete engineering and PAPER acceptance.

---

## 37. Test Requirements

Required tests include:

- realtime parity;
- AS-OF no future leakage;
- context fingerprint determinism;
- historical unavailable behavior;
- stale history;
- partial coverage;
- cache isolation by AS-OF;
- consumer profiles;
- Scanner context;
- Expert context;
- #21 context;
- #25 context;
- LLM summary;
- LLM historical tool limits;
- historical response bounds;
- label-v3 historical source equivalence;
- Risk unaffected;
- Execution unaffected;
- Base Exit unaffected;
- no new trading authority.

---

## 38. Final Acceptance

The new architecture passes only when:

```text
CONTEXT_LAYER_IMPLEMENTED = YES

REALTIME_PARITY = PASS

STRICT_ASOF = PASS

NO_FUTURE_LEAKAGE = PASS

SHARED_HISTORY_CLIENT = PASS

SCANNER_CONTEXT = PASS

EXPERT_CONTEXT = PASS

MODEL21_CONTEXT = PASS

MODEL25_CONTEXT = PASS

CORE_LLM_CONTEXT = PASS

CORE_LLM_HISTORY_TOOLS = PASS

LABELER_HISTORY_SOURCE = PASS

RISK_BEHAVIOR_CHANGED = NO

EXECUTION_BEHAVIOR_CHANGED = NO

BASE_EXIT_BEHAVIOR_CHANGED = NO

TRADING_AUTHORITY_CHANGED = NO

LIVE_ENABLED = NO

FULL_TEST_SUITE = PASS

RUFF = PASS

EXACT_SHA_ACCEPTANCE = PASS

PAPER_RUNTIME = PASS
```

---

## 39. Governing Principle

One historical truth.

One realtime truth.

One Market Context contract.

Many consumers.

Independent intelligence.

Unchanged trading authority.

Shared data must improve what Low-Risk can see without changing who is allowed
to decide, protect or execute a trade.
