# SHARED MARKET HISTORY — FINAL LANDING SPAC

Status: AUTHORITATIVE IMPLEMENTATION SPEC
Version: 1.0
Goal: move Shared Market History from engineering PASS to full operational landing.

## 1. Current baseline

Authoritative architecture spec:
a70d0519c63acd7f6ced1c9ea357227052a3ddf5

Standalone implementation:
83b445f1144976cac820cc04964a0a884f7e75df

Reference Low-Risk runtime:
6ced1da3008edf49eac086596ff4f208ee7b0821

Current accepted facts:
- API: http://127.0.0.1:8770
- OKX live USDT-SWAP universe: 467
- symbols currently populated: 4
- Parquet + DuckDB
- one historical writer
- Low-Risk client PASS
- Turbo client PASS
- concurrent reads PASS
- offline reads PASS
- DeepSeek calls: 0
- GLM calls: 0
- trading DB writes: 0
- runtime integration: deferred

Therefore:
ENGINEERING_IMPLEMENTATION = PASS
FULL_MARKET_POPULATION = INCOMPLETE
LOWRISK_INTEGRATION = DEFERRED
TURBO_INTEGRATION = DEFERRED
PROJECT_LANDING = IN_PROGRESS

## 2. Final mission

Project landing requires all of the following:
1. process the complete current live OKX USDT-SWAP universe;
2. populate factual historical coverage according to retention policy;
3. leave no unresolved backfill checkpoints;
4. run continuous incremental updates;
5. run retention, compaction, feature refresh and integrity checks automatically;
6. survive service restart and host reboot with durable checkpoints;
7. remain within the 2018 Intel Mac / 16GB resource profile;
8. integrate the read-only client into Low-Risk on a new integration candidate;
9. integrate the read-only client into Turbo on a separate integration candidate;
10. prove both consumers receive the same underlying factual history;
11. keep trading authority, risk authority, sizing authority and execution authority outside Shared Market History;
12. keep historical ingestion and feature generation at zero LLM calls.

## 3. Frozen retention profile

- 1m: 30 days
- 5m: 180 days
- 15m: 365 days
- 1h: 1095 days
- 4h: all factual provider-available history
- 1d: all factual provider-available history
- Funding: 2 years where available
- Open Interest: 1 year where available
- raw trades: 24 hours maximum
- raw order book: 1 hour default, 6 hours maximum

Unavailable provider history must remain explicit. Do not synthesize missing history.

## 4. Target host limits

Profile: MACBOOK_2018_16GB_BALANCED

- DuckDB memory limit: 4GB
- DuckDB threads: 4
- backfill concurrency: 2
- aggregation concurrency: 2
- feature concurrency: 2
- ML training threads: max 4
- normal Shared History RSS target: below 2GB
- absolute Shared History working-memory limit: 4GB

Historical background work must yield resources before trading runtimes are affected.

## 5. Full-market completion definition

Every live instrument must be processed.

For each symbol, every required dataset must end in one of:
- COMPLETE
- PARTIAL_HISTORY
- DATA_UNAVAILABLE

PARTIAL_HISTORY and DATA_UNAVAILABLE require factual provider evidence.

Final population gate:
UNIVERSE_PROCESSED_COUNT == LIVE_USDT_SWAP_COUNT
UNRESOLVED_SYMBOL_COUNT == 0
PENDING_BACKFILL_CHECKPOINTS == 0

A newly listed symbol with limited provider history may still be resolved as PARTIAL_HISTORY.

## 6. Staged backfill

Keep backfill concurrency at 2.

Use staged progression:
- 4 -> 25 symbols
- 25 -> 75
- 75 -> 150
- 150 -> 300
- 300 -> full live universe

At every stage record:
- processed/completed/partial/unavailable counts
- retries and errors
- pages fetched
- rows written
- storage growth
- peak RSS
- CPU/load
- free disk

Only advance when integrity and resource gates remain healthy.

## 7. Incremental maintenance

After full backfill, continuous operation must maintain:
- dynamic universe refresh
- latest closed candles
- derived 5m/15m/1h/4h/1d bars
- Funding
- Open Interest
- long-term features
- retention/compaction
- integrity scan
- checkpoints
- observability

All jobs must be idempotent.

Target freshness under healthy provider/network conditions:
- latest closed 1m candle lag <= 5 minutes
- derived higher-timeframe data <= 10 minutes after source closure where applicable

## 8. Durable service

The service remains local-only on 127.0.0.1:8770.

It must run durably on macOS, with:
- automatic restart after process failure
- automatic start after host reboot
- exactly one historical writer
- durable data root
- durable checkpoints
- durable evidence
- no dependency on Low-Risk or Turbo process lifecycle

A restart/reboot test must prove:
- data remains intact
- checkpoints remain intact
- exactly one writer returns
- incomplete backfill resumes
- no completed history is re-created unnecessarily
- API reads recover

## 9. Storage integrity

Canonical storage remains Parquet + DuckDB.

Candle identity:
(symbol, timeframe, open_time)

Validate:
- timestamp ordering
- duplicate prevention
- closed-candle status
- OHLC validity
- non-negative volume
- source and schema version
- explicit gaps rather than fabricated values

Retention may remove fine-grained data only after the required coarser representation is successfully materialized and validated.

## 10. Resource guard

When host resource pressure rises:
- reduce background concurrency from 2 to 1
- pause optional feature recomputation if needed
- preserve read API
- preserve recent incremental maintenance

Suggested disk policy:
- soft free-space floor: 20%
- hard free-space floor: 10%

Below the hard floor, suspend nonessential historical writes and report BLOCKED rather than deleting protected long-term truth outside the retention contract.

## 11. Low-Risk integration

Do not change the existing 6ced1da runtime in place.

If Low-Risk code changes:
- create a new integration branch and SHA
- preserve Shared History as evidence-only
- run the full Low-Risk deterministic acceptance suite
- follow the Low-Risk exact-SHA operational acceptance rules
- reset any acceptance clock required by its constitution

Shared History may provide:
- historical candles
- long-term features
- regime
- Funding history
- OI history

Shared History must not gain:
- new-risk authority
- sizing authority
- leverage authority
- order authority
- exit authority

If Shared History is unavailable, Low-Risk must receive DATA_UNAVAILABLE and must not invent values.

## 12. Turbo integration

Turbo uses the same localhost read API through its Turbo client.

Turbo must not directly depend on Parquet paths or DuckDB file paths.

Turbo keeps its own strategy, model, risk, sizing and execution logic.

Any Turbo runtime change requires its own integration branch, SHA and normal acceptance process.

## 13. Consumer parity

For the same symbol/timeframe/start/end/as-of request, Low-Risk and Turbo must receive the same factual underlying market history.

Required:
LOWRISK_TURBO_DATA_PARITY = PASS

Consumer-specific strategy interpretation belongs inside each trading system, not inside Shared History.

## 14. Full-system resource validation

After full-market population, validate on the actual target Mac with realistic concurrent load:
- Shared History service
- incremental updater
- maintenance jobs
- Low-Risk
- Turbo
- normal ML collection/training windows
- concurrent Low-Risk/Turbo historical queries

Measure:
- per-process RSS
- host memory pressure
- swap growth
- CPU/load
- disk throughput
- disk free
- API latency p50/p95
- Low-Risk cycle latency
- Turbo cycle latency

Required:
SHARED_HISTORY_PEAK_WORKING_MEMORY <= 4GB
NO_SUSTAINED_HOST_MEMORY_PRESSURE_CAUSED_BY_HISTORY = YES
NO_TRADING_RUNTIME_STARVATION = YES
NO_UNBOUNDED_SWAP_GROWTH = YES

## 15. Operational soak

After full-market population, run Shared History continuously for at least 24 hours.

During the soak:
- service remains available
- exactly one writer remains
- incremental updates continue
- retention and feature refresh run
- no data corruption occurs
- LLM calls remain zero
- trading DB writes remain zero
- memory remains bounded
- API remains localhost-only

Any code change required to fix a material blocker resets the Shared History soak clock.

Low-Risk and Turbo integration candidates separately follow their own acceptance windows.

## 16. Observability and evidence

/v1/health and /v1/stats must expose at least:
- implementation version/SHA
- writer count
- universe size
- processed universe count
- complete/partial/unavailable counts
- pending checkpoints
- rows by timeframe
- storage bytes
- last ingestion
- last feature update
- backfill progress
- Low-Risk query count
- Turbo query count
- API errors
- memory/CPU
- disk free
- last retention run
- last integrity scan
- LLM call count

Persist final evidence under durable storage, including:
- full-market population receipt
- coverage matrix
- unresolved-symbol report
- resource report
- retention/integrity report
- reboot recovery report
- offline report
- 24h soak report
- Low-Risk integration receipt
- Turbo integration receipt
- parity report
- final landing receipt

## 17. Blocking conditions

Final landing is BLOCKED if any of the following remains:
- unresolved backfill work
- more than one historical writer
- synthetic provider history
- corrupted retention/compaction
- historical writes into trading DBs
- non-local API exposure by default
- any trading/risk/order authority added to Shared History
- any DeepSeek/GLM dependency for history maintenance
- unstable resource use on the target Mac
- failed restart/reboot recovery
- failed consumer parity
- Low-Risk or Turbo integration not accepted
- open P0 or P1 blocker

## 18. Completion state machine

A:
ENGINEERING = BLOCKED
PROJECT_LANDING = BLOCKED

B:
ENGINEERING = PASS
FULL_MARKET = AUTONOMOUSLY_BACKFILLING
PROJECT_LANDING = IN_PROGRESS

C:
ENGINEERING = PASS
FULL_MARKET = PASS
SHARED_HISTORY_SOAK = PASS
LOWRISK_INTEGRATION = DEFERRED
TURBO_INTEGRATION = DEFERRED
PROJECT_LANDING = IN_PROGRESS

D:
ENGINEERING = PASS
FULL_MARKET = PASS
SHARED_HISTORY_SOAK = PASS
LOWRISK_INTEGRATION = PASS
TURBO_INTEGRATION = PASS
LOWRISK_TURBO_DATA_PARITY = PASS
P0_OPEN = 0
P1_OPEN = 0
PROJECT_LANDING = PASS
SHARED_MARKET_HISTORY_FINAL = PASS

Only state D is final project landing.

## 19. Main landing rule

This specification does not authorize an automatic merge to main.

When every final gate is satisfied, report:
MAIN_LANDING_READY = YES

and wait for explicit operator authorization.

## 20. Final receipt

The final landing report must include:

AUTHORITATIVE_LANDING_SPEC_SHA =
SHARED_HISTORY_IMPLEMENTATION_SHA =
WORKTREE_CLEAN =

PROJECT_PATH =
DATA_ROOT =
API_URL =

LIVE_USDT_SWAP_COUNT =
UNIVERSE_PROCESSED_COUNT =
UNRESOLVED_SYMBOL_COUNT =
SYMBOLS_COMPLETE =
SYMBOLS_PARTIAL =
SYMBOLS_DATA_UNAVAILABLE =
PENDING_BACKFILL_CHECKPOINTS =

ROWS_1M =
ROWS_5M =
ROWS_15M =
ROWS_1H =
ROWS_4H =
ROWS_1D =

LATEST_1M_FRESHNESS =
INCREMENTAL_UPDATER =
BACKFILL_RESUMABLE =
RETENTION_HEALTH =
INTEGRITY_HEALTH =

SHARED_HISTORY_WRITER_COUNT =
REBOOT_RECOVERY_TEST =
OFFLINE_QUERY_TEST =

NORMAL_RSS =
PEAK_RSS =
HOST_MEMORY_PRESSURE =
SWAP_GROWTH =
DISK_FREE =
NO_TRADING_RUNTIME_STARVATION =

DEEPSEEK_CALLS =
GLM_CALLS =
TRADING_DB_WRITES =

SHARED_HISTORY_SOAK_START =
SHARED_HISTORY_SOAK_HOURS =
SHARED_HISTORY_SOAK =

LOWRISK_INTEGRATION_SHA =
LOWRISK_INTEGRATION_ACCEPTANCE =
LOWRISK_SHARED_HISTORY_ENABLED =

TURBO_INTEGRATION_SHA =
TURBO_INTEGRATION_ACCEPTANCE =
TURBO_SHARED_HISTORY_ENABLED =

LOWRISK_TURBO_DATA_PARITY =

P0_OPEN =
P1_OPEN =
P2_OPEN =

MAIN_LANDING_READY =
PROJECT_LANDING =
SHARED_MARKET_HISTORY_FINAL =

Do not report "all tasks completed" until state D is factually satisfied.
