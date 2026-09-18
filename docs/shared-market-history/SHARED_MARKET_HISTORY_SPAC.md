# SHARED MARKET HISTORY SPAC
## Low-Risk + Turbo Shared Historical Market Data Layer

**Status:** SPECIFICATION  
**Version:** 1.0  
**Scope:** DATA INFRASTRUCTURE ONLY  
**Trading Authority:** NONE  
**LLM Authority:** NONE  
**Reference Low-Risk Candidate:** `6ced1da3008edf49eac086596ff4f208ee7b0821`

---

## 1. Purpose

Build one standalone historical market-data layer shared by:

- Low-Risk
- Turbo

The service provides factual historical market data and deterministic long-term features.

It MUST NOT:

- create trade direction;
- create orders;
- modify positions;
- modify Risk;
- modify ExecutionAuthority;
- modify Low-Risk strategy;
- modify Turbo strategy;
- call DeepSeek;
- call GLM;
- own any trading authority.

The historical layer is **DATA ONLY**.

---

## 2. Isolation and Safety

This work MUST NOT modify the frozen Low-Risk final-candidate branch:

`codex/low-risk-final-candidate-2`

This work MUST NOT change the exact candidate SHA:

`6ced1da3008edf49eac086596ff4f208ee7b0821`

The current Low-Risk PAPER soak must remain unaffected.

No main merge, LIVE enablement, force-push, history rewrite, credential exposure, or trading-DB mutation is authorized by this specification.

Historical market data MUST live outside both trading-runtime databases.

The following stores remain independent:

1. Low-Risk runtime DB;
2. Turbo runtime DB;
3. Shared Market History storage.

Low-Risk and Turbo MUST NOT open the shared DuckDB store in writer mode. Only the Shared Market History Service owns historical writes.

---

## 3. Target Hardware Profile

Primary target machine:

- MacBook Pro 15-inch, 2018
- 2.6 GHz 6-core Intel Core i7
- 16 GB DDR4
- Intel integrated graphics
- macOS

Canonical resource profile:

`MACBOOK_2018_16GB_BALANCED`

Default resource ceilings:

- DuckDB memory limit: **4 GB**
- DuckDB threads: **4**
- Historical download concurrency: **2**
- Historical aggregation concurrency: **2**
- Feature calculation concurrency: **2**
- ML training threads: **max 4**
- Normal historical-service RSS target: **< 2 GB**
- Absolute historical-service working-memory target: **<= 4 GB**

The implementation MUST use chunked, streaming, partition-pruned processing and MUST NOT load the whole market history into RAM.

---

## 4. Project and Durable Data Location

Standalone implementation project:

`/Users/huhongjie/Documents/ChatGPT/shared-market-history`

Default durable data root:

`~/Library/Application Support/SharedMarketHistory`

Recommended logical layout:

```text
SharedMarketHistory/
  parquet/
    candles/
    funding/
    open_interest/
  features/
  metadata/
  checkpoints/
  cache/
  logs/
  duckdb/
```

The service MUST NOT use `/tmp` or `/private/tmp` as canonical durable storage.

The data root MUST be overrideable through a single explicit environment variable so the historical lake can later move to an external NVMe without changing the API contract.

---

## 5. Canonical Market Universe

Primary source:

**OKX public market data**

Universe:

**all currently live USDT-settled perpetual SWAP instruments**

Required factual universe filter:

- `instType = SWAP`
- `state = live`
- instrument id suffix `-USDT-SWAP`

No hardcoded canonical symbol list is allowed.

The universe MUST be dynamically discovered and refreshed.

Required metadata per instrument:

- canonical symbol;
- OKX instId;
- state;
- listing timestamp when available;
- first factual candle timestamp;
- latest factual candle timestamp;
- supported historical coverage;
- source;
- schema version.

---

## 6. Historical Retention Profile

The historical layer MUST reduce detail as data ages so the 16 GB Mac remains responsive.

Canonical retention policy:

| Dataset | Retention |
|---|---:|
| 1m candles | 30 days |
| 5m candles | 180 days |
| 15m candles | 1 year |
| 1h candles | 3 years |
| 4h candles | all available history |
| 1d candles | all available history |
| Funding | 2 years where factual history exists |
| Open Interest | 1 year where factual history exists |
| Raw trades | 24 hours maximum |
| Raw order book | 1 hour default, 6 hours absolute maximum |

Full historical tick-by-tick archives are OUT OF SCOPE.

Full historical order-book reconstruction is OUT OF SCOPE.

---

## 7. Downsampling Policy

Recent 1-minute data is the highest-resolution retained historical layer.

As data ages:

- after 30 days, 1m may be deleted after safe aggregation;
- after 180 days, 5m may be deleted;
- after 1 year, 15m may be deleted;
- after 3 years, 1h may be deleted;
- 4h and 1d remain for all factual history.

Derived bars MUST preserve factual OHLCV semantics.

Do not permanently store redundant full-history copies of every timeframe if they can be safely derived and compacted.

Retention pruning MUST be transactional or otherwise crash-safe.

---

## 8. Storage and Query Engine

Canonical storage:

**Parquet**

Canonical analytical/query engine:

**DuckDB**

SQLite MUST NOT be used as the historical candle lake.

Suggested partition layout:

```text
parquet/
  candles/
    BTCUSDT/
      1h/
        2026/
          01.parquet
          02.parquet
```

Partitioning should be approximately:

`dataset / symbol / timeframe / year / month`

The implementation MUST avoid creating excessive tiny files.

Monthly partitions are preferred where practical.

---

## 9. Candle Truth Contract

Only factual CLOSED candles may enter the historical truth layer.

Required candle fields:

- symbol;
- timeframe;
- open_time;
- close_time;
- open;
- high;
- low;
- close;
- volume;
- source;
- ingested_at;
- schema_version.

Optional factual fields when available:

- quote_volume;
- trade_count;
- taker_buy_volume;
- taker_sell_volume.

An unfinished candle MUST NOT be persisted as a closed historical candle.

No synthetic replacement is allowed.

Missing provider data remains explicitly missing.

---

## 10. Backfill Contract

Historical backfill MUST be resumable and idempotent.

Persist checkpoint state per:

- dataset;
- symbol;
- timeframe.

Checkpoint fields should include:

- oldest_fetched;
- newest_fetched;
- next_cursor or equivalent;
- status;
- last_error;
- retry_count;
- last_success_at.

On restart, completed partitions MUST NOT be redownloaded without cause.

Backfill must be low priority relative to trading runtimes.

When host resource pressure is high, the backfill worker should reduce concurrency or pause itself. It MUST NOT kill Low-Risk or Turbo.

---

## 11. Long-Term Historical Features

Long-term features are deterministic local calculations.

Required LLM usage:

- DeepSeek calls: **0**
- GLM calls: **0**

Minimum feature set:

- price percentile;
- volume percentile;
- ATR percentile;
- realized-volatility percentile;
- distance from ATH;
- drawdown from ATH;
- distance from historical low;
- 30d trend;
- 90d trend;
- 1y trend;
- 4h regime;
- 1d regime;
- funding percentile;
- OI percentile;
- historical return distribution;
- forward-return statistics for 1h / 4h / 24h;
- historical analog count where computationally practical.

Every feature record MUST include:

- symbol;
- as_of timestamp;
- source horizon;
- source dataset version;
- feature schema version;
- factual coverage status.

The service MUST distinguish `COMPLETE`, `PARTIAL_HISTORY`, and `DATA_UNAVAILABLE`.

---

## 12. Shared Read-Only Service

Canonical bind address:

`127.0.0.1`

Canonical default port:

`8770`

Canonical URL:

`http://127.0.0.1:8770`

The service MUST NOT bind to `0.0.0.0` by default.

This is a local shared-data service, not a public internet API.

---

## 13. Required API

Implement at least:

```text
GET /v1/health
GET /v1/stats
GET /v1/universe
GET /v1/metadata/{symbol}

GET /v1/candles
GET /v1/latest

GET /v1/features/{symbol}
GET /v1/regime/{symbol}

GET /v1/funding/{symbol}
GET /v1/open-interest/{symbol}
```

### /v1/candles

Required parameters:

- symbol
- timeframe
- start (optional)
- end (optional)
- limit

Example:

`/v1/candles?symbol=BTCUSDT&timeframe=1h&limit=300`

### /v1/latest

Example:

`/v1/latest?symbol=BTCUSDT&timeframe=5m&limit=300`

Single-request maximum candle count:

**10,000**

Larger research reads must paginate/chunk.

---

## 14. Response Contract

Every market-data response MUST include enough metadata to prove factuality and coverage.

Required response metadata:

- symbol;
- source;
- timeframe when applicable;
- first_timestamp;
- last_timestamp;
- row_count;
- data_freshness;
- historical_coverage;
- generated_at;
- schema_version.

The service MUST NOT silently return synthetic or guessed values.

If requested history is incomplete, return explicit state such as:

- `PARTIAL_HISTORY`
- `DATA_UNAVAILABLE`

---

## 15. Low-Risk Consumer Contract

Provide a reusable read client under the shared project, for example:

`clients/lowrisk/`

Suggested interface:

`SharedHistoryClient`

Methods:

- `health()`
- `universe()`
- `latest_candles(symbol, timeframe, limit)`
- `historical_candles(symbol, timeframe, start, end)`
- `features(symbol)`
- `regime(symbol)`
- `funding(symbol)`
- `open_interest(symbol)`

Low-Risk historical outputs are **EVIDENCE ONLY**.

They MUST NOT:

- create trade direction;
- create orders;
- bypass Core LLM;
- bypass Risk;
- bypass ExecutionAuthority;
- alter Base Exit authority.

---

## 16. Turbo Consumer Contract

Provide an equivalent reusable client:

`clients/turbo/`

Turbo must be able to consume the same factual full-market history without knowing:

- Parquet paths;
- DuckDB file paths;
- storage layout;
- backfill internals.

The shared service provides DATA ONLY.

Turbo retains its own independent strategy, risk, execution and model authority.

The Shared Market History Service MUST NOT impose Low-Risk trading semantics on Turbo.

---

## 17. Consumer Identification

Consumers may send:

`X-Consumer: lowrisk`

or:

`X-Consumer: turbo`

This header is for observability only.

It MUST NOT grant trading permissions or change data semantics.

Track query counts separately by consumer.

---

## 18. Cache Contract

Allowed bounded caches:

- latest candles;
- metadata;
- long-term features;
- recent universe snapshot.

The service MUST NOT cache the entire historical market universe in RAM.

Cache limits must be explicit and bounded.

Normal steady-state memory target remains < 2 GB.

---

## 19. Offline Behavior

When internet access is unavailable:

Existing local historical queries MUST continue to work.

The following may continue:

- stored candle queries;
- stored features;
- local regime queries;
- historical funding/OI reads;
- local ML research.

The following pause:

- new ingestion;
- backfill;
- universe refresh requiring network.

Network failure MUST NOT corrupt or invalidate existing historical truth.

---

## 20. LLM Cost Contract

Historical ingestion, retention, compaction, aggregation and feature generation MUST make:

```text
DEEPSEEK_CALLS = 0
GLM_CALLS = 0
```

No LLM is needed to build or maintain the historical layer.

---

## 21. Observability

`GET /v1/health` should expose:

- service_status;
- parquet_status;
- duckdb_status;
- data_root;
- disk_usage;
- memory_usage;
- backfill_running;
- backfill_queue;
- universe_size;
- symbols_with_history;
- last_ingestion_at.

`GET /v1/stats` should expose:

- total_symbols;
- storage_size;
- rows_by_timeframe;
- coverage_by_timeframe;
- backfill_progress;
- latest_update;
- query_count_1h;
- turbo_queries_1h;
- lowrisk_queries_1h.

No credentials or secrets may appear in health/stats output.

---

## 22. Startup and Shutdown

Provide:

`scripts/start-history-service.sh`

`scripts/stop-history-service.sh`

Starting or stopping the historical service MUST NOT start, stop, restart or reconfigure:

- Low-Risk runtime;
- Turbo runtime.

Expected startup receipt:

```text
SHARED_HISTORY_READY=YES
URL=http://127.0.0.1:8770
```

---

## 23. Validation Requirements

Minimum factual validation set:

- BTCUSDT;
- ETHUSDT;
- one mid-cap live USDT SWAP;
- one lower-liquidity eligible live USDT SWAP.

Validate:

1. dynamic OKX universe discovery;
2. 1m recent coverage;
3. 5m retention/aggregation;
4. 15m retention/aggregation;
5. 1h long-range coverage where instrument age permits;
6. 4h all-available history;
7. 1d all-available history;
8. funding history where available;
9. OI history where available;
10. Turbo client query;
11. Low-Risk client query;
12. concurrent Low-Risk + Turbo reads;
13. no trading DB writes;
14. no shared-writer access from consumers;
15. bounded RAM;
16. resumable backfill;
17. offline local queries;
18. zero LLM calls.

---

## 24. Performance Acceptance

On the target 16 GB Mac:

- historical-service working memory MUST stay <= 4 GB under designed load;
- normal steady-state should target < 2 GB;
- query paths must use partition pruning;
- long range queries must chunk/paginate;
- backfill concurrency must not exceed configured cap;
- service must degrade background work before affecting trading processes.

A large historical request MUST NOT attempt to materialize the full market history into RAM.

---

## 25. Non-Goals

This specification does NOT authorize:

- full historical order-book reconstruction;
- full tick archive;
- a public internet data API;
- LLM-based feature generation;
- strategy changes;
- Risk changes;
- execution changes;
- LIVE trading;
- main merge;
- modification of the frozen Low-Risk soak candidate.

---

## 26. Delivery Phases

### Phase A — Storage Foundation

- project scaffold;
- durable root;
- DuckDB/Parquet integration;
- schema/version contract;
- health endpoint.

### Phase B — Dynamic Universe + Backfill

- OKX live USDT SWAP universe;
- checkpointed historical downloader;
- retention and compaction.

### Phase C — Long-Term Features

- deterministic historical features;
- coverage state;
- local feature cache.

### Phase D — Shared API

- read-only localhost API;
- query limits;
- factual metadata.

### Phase E — Low-Risk/Turbo Clients

- Low-Risk client;
- Turbo client;
- consumer observability.

### Phase F — Acceptance

- hardware-bound performance;
- offline behavior;
- concurrent consumers;
- no trading DB mutation;
- zero LLM calls.

---

## 27. Final Acceptance Receipt

The implementation acceptance report MUST return at least:

```text
PROJECT_PATH =
DATA_ROOT =
API_URL =

DATA_SOURCE =
UNIVERSE_SIZE =

1M_RETENTION =
5M_RETENTION =
15M_RETENTION =
1H_RETENTION =
4H_RETENTION =
1D_RETENTION =

FUNDING_RETENTION =
OI_RETENTION =

DUCKDB_MEMORY_LIMIT =
DUCKDB_THREADS =

BACKFILL_CONCURRENCY =

LOWRISK_CLIENT =
TURBO_CLIENT =

LOWRISK_QUERY_TEST =
TURBO_QUERY_TEST =
CONCURRENT_QUERY_TEST =

OFFLINE_QUERY_TEST =
RETENTION_TEST =
BACKFILL_RESUME_TEST =
MEMORY_LIMIT_TEST =

LLM_CALLS = 0

LOWRISK_TRADING_RUNTIME_MODIFIED = NO
TURBO_TRADING_RUNTIME_MODIFIED = NO

FINAL_RESULT =
PASS | BLOCKED
```

---

## 28. Governing Principle

There must be exactly one shared factual historical market-data source for local trading systems.

Low-Risk and Turbo may interpret that data differently, but they must not maintain incompatible duplicate historical truth.

**Shared data, independent intelligence, independent risk, independent execution.**
