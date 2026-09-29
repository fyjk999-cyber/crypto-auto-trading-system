# SHARED HISTORY STORAGE CONVERGENCE FINAL SPAC

Status: AUTHORITATIVE TASK SPEC
Version: 1.0
Scope: Shared Market History scheduling, final storage topology validation, and post-migration soak
Trading authority: NONE
LLM authority: NONE

## 1. Purpose

Complete the final storage/data-plane convergence for Shared Market History while preserving the original architecture:

- one canonical factual historical market-data source;
- one Shared History writer;
- LowRisk/Turbo are read-only consumers;
- no change to strategy, Risk, sizing, leverage, execution or LLM authority;
- full eligible OKX USDT-SWAP universe remains covered;
- 1-minute freshness target remains <= 300 seconds;
- final 24-hour soak is performed only after the final physical storage topology is in place.

This SPAC extends, and does not replace:

- docs/shared-market-history/SHARED_MARKET_HISTORY_SPAC.md
- docs/shared-market-history/SHARED_MARKET_HISTORY_FINAL_LANDING_SPAC.md

## 2. Known current facts

Accepted historical facts to preserve:

- Shared History uses Parquet + DuckDB.
- Shared History is local-only on 127.0.0.1:8770.
- exactly one historical writer is allowed.
- LowRisk and Turbo must not write Shared History.
- Shared History has no trading authority.
- DeepSeek/GLM calls for ingestion, maintenance and historical queries must remain 0.
- the AppleDouble/ExFAT reader defect has been remediated by centrally rejecting non-factual Parquet files such as `._*.parquet`.
- post-remediation validation reported funding/open_interest AppleDouble-related HTTP 500s reduced to 0.
- the current freshness blocker is scheduler coupling, not AppleDouble corruption.
- the strict 1-minute freshness gate remains `MAX(symbol_lag) <= 300s`.

Frozen LowRisk integration reference:

`codex/lowrisk-shared-history-readonly-integration`
`45a282621728a4aec39683a1ada035ce199ee1f6`

Its engineering acceptance is PASS but it is not deployed by this SPAC.

## 3. Non-goals

This SPAC does NOT authorize:

- raising the 300-second 1-minute freshness threshold;
- shrinking the eligible symbol universe;
- changing LowRisk/Turbo strategy semantics;
- changing Risk or ExecutionAuthority;
- deploying the frozen LowRisk integration;
- activating or promoting an ML model;
- changing ML feature/label semantics;
- moving trading runtime DBs;
- moving Growth memory;
- creating a second Shared History writer;
- merging ML derived datasets into SharedMarketHistory.

## 4. Target final physical topology

```text
/Volumes/My PSSD/
├── SharedMarketHistory/
│   └── canonical factual historical market data
└── MLArchive/
    └── lowrisk/
        └── datasets/
            └── derived ML datasets
```

Logical ownership is strict:

- SharedMarketHistory = factual historical market truth.
- MLArchive = derived ML training/OOS/replay datasets.
- trading state remains outside both.

## 5. Phase A — freshness-critical sweep decoupling

The current mega-sweep must be decomposed by cadence.

### Tier A — freshness critical

All eligible symbols:
- latest factual closed 1m candle.

This tier alone drives the canonical 1m freshness gate.

Requirements:
- full eligible universe, no symbol reduction;
- `SHARED_HISTORY_1M_FRESHNESS_MAX_SECONDS = 300` unchanged;
- one canonical Shared History writer;
- no synthetic or future bars;
- no checkpoint reset.

### Tier B — higher timeframes

5m / 15m / 1h / 4h / 1d must not block the next Tier A 1m cycle.

Prefer deterministic aggregation/downsampling from canonical lower-resolution factual bars where the existing design allows it.

If direct provider fetches remain necessary, they run on a separate cadence and must not be part of the 1m critical sweep.

### Tier C — funding and open interest

Funding and OI run independently according to factual upstream cadence and existing retention semantics.

They must not block the 1m refresh loop.

## 6. Phase A acceptance

Require three consecutive factual full-universe 1m cycles.

For each cycle record:
- universe size;
- pass start/end;
- duration;
- request count/rate;
- HTTP 429 count;
- timeout count;
- retry count;
- min/p50/p95/max 1m lag;
- symbols outside 300s.

All three cycles must satisfy:

```text
MAX_1M_LAG <= 300s
OUTSIDE_300S = 0
WRITER_COUNT = 1
FAILED_TERMINAL = 0
SYMBOL_UNIVERSE_REDUCED = NO
FRESHNESS_THRESHOLD_CHANGED = NO
```

Re-run AppleDouble regression tests.

Do NOT start the final 24h soak after Phase A. Record:

`FINAL_SOAK_DEFERRED_FOR_ML_MIGRATION = YES`

## 7. Phase B coordination boundary

Heavy LowRisk ML dataset migration is specified separately in:

`docs/ml/LOWRISK_ML_EXTERNAL_DATASET_ARCHIVE_SPAC.md`

During its bulk copy:
- Shared History may remain operational if safe;
- Shared History freshness measurements are observational only;
- migration-period disk contention must not be counted as scheduler acceptance evidence;
- the 300s SLO must not be altered;
- Shared History code/data roots must not be changed by the ML migration.

## 8. Phase C — final topology concurrent-load acceptance

After ML migration completes, validate the real final storage topology under production-like concurrent load:

- Shared History 1m incremental writer;
- normal Shared History API reads;
- LowRisk normal runtime;
- Turbo normal runtime;
- LowRisk ML normal external-dataset reads;
- normal ML dataset writes/collection where applicable.

Do not create abnormal stress solely to manufacture failure.

Measure:
- Shared History RSS;
- ML RSS;
- CPU/load;
- host memory pressure;
- swap growth;
- external disk throughput/latency;
- disk free;
- Shared History API p50/p95;
- LowRisk cycle latency;
- Turbo cycle latency.

Required:

```text
NO_TRADING_RUNTIME_STARVATION = YES
NO_UNBOUNDED_MEMORY_GROWTH = YES
NO_UNBOUNDED_SWAP_GROWTH = YES
EXTERNAL_DISK_IO_HEALTH = PASS
```

## 9. Post-migration freshness re-acceptance

After Phase B, run three new consecutive full-universe 1m cycles.

Each must again satisfy:

```text
MAX_1M_LAG <= 300s
OUTSIDE_300S = 0
WRITER_COUNT = 1
FAILED_TERMINAL = 0
```

This proves the scheduler contract under the final shared external-disk topology.

## 10. Final gates

Only after the post-migration three-cycle freshness acceptance, run:

1. full freshness gate;
2. full integrity scan;
3. retention validation;
4. operational preflight.

Required:

```text
FRESHNESS = PASS
INTEGRITY = PASS
RETENTION = PASS
OPERATIONAL_PREFLIGHT = PASS
```

Do not bypass or backdate any gate.

## 11. Final 24h soak

Start only after all final gates pass.

Set:
- `SHARED_HISTORY_SOAK_START` = factual current UTC timestamp;
- `SHARED_HISTORY_SOAK_TARGET` = start + 24h.

During the soak do not change:
- Shared History scheduler code;
- freshness threshold;
- symbol universe;
- Shared History data root;
- ML dataset root;
- retention policy;
- writer topology.

Any material code/storage-topology fix resets the soak clock after fresh preflight.

## 12. Soak monitoring

Track:
- writer_count;
- 1m freshness distribution;
- incremental cycles;
- terminal failures;
- API health/errors;
- AppleDouble rejection counters;
- integrity drift;
- retention jobs;
- ML external dataset reads/writes;
- unexpected local ML dataset recreation;
- disk free/latency;
- CPU/memory/swap;
- LowRisk/Turbo starvation signals.

## 13. Hard invariants

At all times:

```text
SHARED_HISTORY_WRITER_COUNT = 1
LOWRISK_SHARED_HISTORY_WRITES = 0
TURBO_SHARED_HISTORY_WRITES = 0
DEEPSEEK_CALLS_FOR_HISTORY = 0
GLM_CALLS_FOR_HISTORY = 0
STRATEGY_CHANGE = 0
RISK_CHANGE = 0
AUTHORITY_CHANGE = 0
ML_MODEL_ACTIVATED = NO
```

## 14. State machine

```text
A SPAC_WRITTEN
B FRESHNESS_DECOUPLING_IMPLEMENTED
C PRE_MIGRATION_3_CYCLE_FRESHNESS_PASS
D ML_DATASET_COPY_PASS
E ML_PATH_SWITCH_PASS
F LOCAL_ML_RECLAIM_PASS
G POST_MIGRATION_CONCURRENT_LOAD_PASS
H POST_MIGRATION_3_CYCLE_FRESHNESS_PASS
I INTEGRITY_PASS + RETENTION_PASS + PREFLIGHT_PASS
J 24H_SOAK_RUNNING
K 24H_SOAK_PASS
L FINAL_CONVERGENCE_PASS
```

Do not skip states.

## 15. Stop conditions

Stop and report if any of the following occurs:

- risk of factual data loss;
- unexpected second writer;
- checkpoint/integrity mismatch;
- target disk capacity unsafe;
- strategy/Risk/authority semantics would need modification;
- 300s full-universe freshness cannot be safely achieved under final topology;
- material divergence from this SPAC.

## 16. Required final receipt

Return:

```text
SHARED_HISTORY_AND_ML_STORAGE_FINAL_CONVERGENCE_RECEIPT

SPAC_SHA =
SHARED_HISTORY_STARTING_SHA =
SHARED_HISTORY_FINAL_SHA =

PHASE_A_3_CYCLE_FRESHNESS =
PHASE_B_ML_MIGRATION =
PHASE_C_CONCURRENT_LOAD =

FINAL_CYCLE_1_MAX_LAG =
FINAL_CYCLE_2_MAX_LAG =
FINAL_CYCLE_3_MAX_LAG =

FRESHNESS =
INTEGRITY =
RETENTION =
OPERATIONAL_PREFLIGHT =

SHARED_HISTORY_WRITER_COUNT =
APPLEDOUBLE_REGRESSION =
NO_TRADING_RUNTIME_STARVATION =
EXTERNAL_DISK_IO_HEALTH =

SHARED_HISTORY_SOAK_START =
SHARED_HISTORY_SOAK_TARGET =
SHARED_HISTORY_SOAK_HOURS =
SHARED_HISTORY_SOAK =

LOWRISK_INTEGRATION_SHA =
45a282621728a4aec39683a1ada035ce199ee1f6

LOWRISK_INTEGRATION_ENGINEERING_ACCEPTANCE = PASS
LOWRISK_RUNTIME_DEPLOYMENT_ACCEPTANCE = NOT_DEPLOYED

STORAGE_CONVERGENCE_ACCEPTANCE =
SHARED_MARKET_HISTORY_FINAL =
BLOCKERS =
NEXT_REQUIRED_ACTION =
```

## 17. Governing principle

Build the final storage topology first, then prove that final topology satisfies the original full-universe <=300s freshness contract and the 24h operational soak.
