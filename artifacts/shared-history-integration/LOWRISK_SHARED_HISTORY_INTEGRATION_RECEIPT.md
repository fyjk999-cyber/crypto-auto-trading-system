# LOWRISK — SHARED MARKET HISTORY ORIGINAL-DESIGN INTEGRATION LANDING — RECEIPT

Task: integrate LowRisk → Shared Market History read-only, using the existing
repository architecture and contracts. Integration/landing only; no redesign.

---

## BASELINE

```
LOWRISK_BASELINE_SHA                = 6ced1da3008edf49eac086596ff4f208ee7b0821
BASELINE_PROVENANCE                 = deployment dir
                                      "LowRisk/deployments/final-candidate-2-6ced1da"
                                      HEAD == 6ced1da, tree b93a9c51194433d1…, clean
                                      (identical tree to 6ced1da; verified)
LANDING_REPO_DETACHED_HEAD          = 374ee96022d0360d49dc4a8dbaa1619e2a1fbe54
                                      (the PARENT of 6ced1da — not the running code;
                                       do not use it as the integration baseline)
CURRENT_RUNTIME_SHA                 = 6ced1da3008edf49eac086596ff4f208ee7b0821
CURRENT_RUNTIME_PID                 = 871
CURRENT_RUNTIME_CMD                 = python -m crypto_trader.runtime.local_runner
                                      --host 127.0.0.1 --port 8010
CURRENT_RUNTIME_CWD                 = /Users/huhongjie/Library/Application Support/
                                      LowRisk/deployments/final-candidate-2-6ced1da
CURRENT_PAPER_STATE                 = PAPER_ONLY (unchanged, not restarted)
CURRENT_PROVIDER_STATE              = unchanged (no resume, no model change)
INTEGRATION_WORKTREE                = /Users/huhongjie/lowrisk-shared-history-integration
INTEGRATION_BRANCH                  = codex/lowrisk-shared-history-readonly-integration
PRODUCTION_MODIFIED_IN_PLACE        = NO
```

## PRIOR DESIGN

The design was read from the repository history, not re-invented:

```
AUTHORITATIVE_LANDING_SPEC          = docs/shared-market-history/
                                      SHARED_MARKET_HISTORY_FINAL_LANDING_SPAC.md
                                      @ 2d3957f (origin/codex/shared-market-history-final-landing-spac)
ARCHITECTURE_SPEC                   = docs/shared-market-history/
                                      SHARED_MARKET_HISTORY_SPAC.md
                                      @ a70d0519c63acd7f6ced1c9ea357227052a3ddf5
STANDALONE_IMPLEMENTATION_SHA       = 83b445f1144976cac820cc04964a0a884f7e75df
REFERENCE_LOWRISK_RUNTIME_IN_SPEC   = 6ced1da3008edf49eac086596ff4f208ee7b0821
                                      (the spec itself names the running SHA — matched)
DESIGN_REUSED                       = YES
DESIGN_REDESIGNED                   = NO
```

The spec's Low-Risk integration section requires: do not change the 6ced1da runtime in
place; create a new integration branch and SHA; keep Shared History evidence-only; run
the full LowRisk deterministic acceptance suite. All four were followed.

## ARCHITECTURE

```
EXISTING_LOW_RISK_CLIENT_FOUND      = YES
EXISTING_CLIENT_LOCATION            = shared-market-history project
                                      src/shared_market_history/clients/base.py
                                      src/shared_market_history/clients/lowrisk/client.py
EXISTING_CLIENT_CLASS               = LowRiskSharedHistoryClient
EXISTING_CLIENT_REPO_HEAD           = 8fcb90a77705e28c308d0dd25717996a2572f5d2
EXISTING_CLIENT_BLOB_BASE_PY        = 5b95f5748a29f6f6a6b8425ca4716621cf4f31b6
EXISTING_CLIENT_BLOB_LOWRISK_PY     = 8bb105c7ea0dddc39ba0ea673f56ce216826fc17
EXISTING_CLIENT_REUSED              = YES
NEW_DUPLICATE_CLIENT_CREATED        = false
REUSE_MECHANISM                     = vendored by source with provenance recorded in
                                      the module header (the producer package is not a
                                      LowRisk dependency and must not become one)
DELTAS_FROM_SOURCE                  = 2 (both contract-mandated)
                                      1. POST transport + 3 batch_* methods removed
                                      2. loopback-only URL enforcement added
SEMANTICS_DIVERGED                  = NO (all other client behavior byte-preserved)

TARGET ARCHITECTURE (unchanged)
  OKX -> Shared Market History Service (sole writer) -> Parquet + DuckDB
      -> localhost read API -> LowRisk SharedHistoryClient -> evidence layers

FILES_ADDED                         = src/crypto_trader/shared_history/{__init__,client,adapter}.py
                                      tests/shared_history/*.py (7)
                                      scripts/shared_history_probe.py
                                      docs/shared-history/LOWRISK_SHARED_HISTORY_READONLY_INTEGRATION.md
FILES_MODIFIED                      = src/crypto_trader/config.py  (+11 lines)
STRATEGY_FILES_MODIFIED             = 0
RISK_FILES_MODIFIED                 = 0
EXECUTION_FILES_MODIFIED            = 0
ML_FILES_MODIFIED                   = 0
FACTOR_FILES_MODIFIED               = 0
EXPERT_FILES_MODIFIED               = 0
GROWTH_FILES_MODIFIED               = 0
DEEPSEEK_FILES_MODIFIED             = 0
```

## READ CONTRACT

```
LOWRISK_INTEGRATION_SHA             = 76564e7440e67dfda2e87050d94575056873d8bf
READ_INTERFACE_health               = YES
READ_INTERFACE_universe             = YES
READ_INTERFACE_latest_candles       = YES
READ_INTERFACE_historical_candles   = YES
READ_INTERFACE_features             = YES
READ_INTERFACE_regime               = YES
READ_INTERFACE_funding              = YES
READ_INTERFACE_open_interest        = YES
TRANSPORT_METHODS                   = GET only
LOOPBACK_ONLY_ENFORCED              = YES (non-loopback URL refused at construction)
ARBITRARY_REMOTE_HOST_REACHABLE     = NO
CONSUMER_HEADER                     = X-Consumer: lowrisk (informational, grants nothing)
RECORD_ACCESS                       = none (no writer, no admin, no storage handle)
```

Live service status for each endpoint, measured against PID 48026:

```
health              HTTP 200  AVAILABLE
stats               HTTP 200  AVAILABLE (slow, >10s)
universe            HTTP 200  AVAILABLE (478 symbols)
latest / candles    HTTP 200  AVAILABLE
regime              HTTP 200  AVAILABLE
analogs             HTTP 200  AVAILABLE
metadata            HTTP 500  UNAVAILABLE  <- producer defect
features            HTTP 500  UNAVAILABLE  <- producer defect (also no dataset)
funding             HTTP 500  UNAVAILABLE  <- producer defect
open-interest       HTTP 500  UNAVAILABLE  <- producer defect
```

## DATA QUALITY

```
SHARED_HISTORY_SERVICE_ACCEPTANCE   = PARTIAL
SHARED_HISTORY_IMPLEMENTATION_SHA   = 4fd7e3419dc4022f1389902c433283d28a876787
                                      (from the live /v1/health)
SHARED_HISTORY_SERVICE_PIDS         = 1 (PID 48026)
SHARED_HISTORY_UNIVERSE_SIZE        = 478
SHARED_HISTORY_UNIVERSE_PROCESSED   = 478
SHARED_HISTORY_UNRESOLVED_SYMBOLS   = 0
SHARED_HISTORY_FULL_MARKET          = PASS
SHARED_HISTORY_PENDING_BACKFILL     = 0
SHARED_HISTORY_SOAK                 = WAITING_FOR_GATES
```

Producer defect (reproduced, root-caused, NOT fixed — out of scope):

```
DEFECT                              = HTTP 500 on /v1/{metadata,features,funding,open-interest}
ROOT_CAUSE                          = ParquetStore._dataset_files() uses
                                      base.rglob("*.parquet") without excluding ExFAT
                                      AppleDouble sidecars (._*.parquet); DuckDB raises
                                      InvalidInputException "No magic bytes found at end of file"
FILE                                = src/shared_market_history/storage/parquet_store.py
CANDLES_UNAFFECTED_BECAUSE          = strict month glob
                                      "*/<tf>/[0-9][0-9][0-9][0-9]/[0-9][0-9].parquet"
CAUSAL_CONTROL                      = funding: 442 symbols WITH sidecars -> HTTP 500;
                                      36 symbols WITHOUT -> HTTP 200
                                      open_interest: identical 442 / 36 split
AFFECTED_FRACTION                   = 442/478 = 92.5% of the universe, both datasets
EVIDENCE                            = artifacts/shared-history-integration/
                                      SHARED_HISTORY_SERVICE_DEFECT.md
                                      defect_scope.json
FIXED_HERE                          = NO (production single-writer service, not this task)
PROPOSED_FIX                        = filter p.name.startswith("._") in _dataset_files
LOWRISK_HANDLING                    = DATA_UNAVAILABLE / SHARED_HISTORY_HTTP_ERROR

UNAVAILABLE_IS_NOT_ZERO             = ENFORCED (unavailable results carry zero rows)
ZERO_FILLED_VALUES                  = 0
SYNTHETIC_FALLBACK                  = NONE
INVENTED_VALUES                     = NONE
PARTIAL_HISTORY_PRESERVED           = YES (never upgraded to COMPLETE)
STALE_DISTINCT_FROM_FRESH           = YES
```

## TEMPORAL

```
MAX_DATA_TIMESTAMP_LE_DECISION_AS_OF = ENFORCED
SHARED_HISTORY_FUTURE_ROWS_VISIBLE   = 0
FUTURE_DATA_REJECTION                = whole-payload rejection (never silent trimming)
FUTURE_CHECK_COVERS                  = row timestamps AND envelope max_source_timestamp
                                       (so document endpoints such as regime are covered)
WINDOW_END_CLAMPED_TO_AS_OF          = YES (before the request is sent)
AS_OF_FORWARDED_TO_SERVICE           = YES
FUTURE_DATA_REJECTION_COUNTER        = present and proven to fire
DETERMINISTIC_LEAKAGE_TESTS          = 9 (tests/shared_history/test_temporal_as_of.py)
```

## INTEGRATION

```
LOWRISK_INTEGRATION_ENGINEERING_ACCEPTANCE = PASS
LOWRISK_SHARED_HISTORY_ENABLED      = false (production default)
FLAG_MECHANISM                      = existing LowRisk Settings (pydantic BaseSettings)
DUPLICATE_FLAG_INTRODUCED           = NO
SETTINGS_FIELDS_ADDED               = shared_history_enabled
                                      shared_history_base_url
                                      shared_history_timeout_seconds
                                      shared_history_cache_ttl_seconds
                                      shared_history_cache_max_entries
FILE_ACCESS_OCCURS_WHEN_DISABLED    = NONE (0 requests observed with the flag off)
BOUNDED_QUERIES                     = YES (row limit clamped to 10 000; time ranges bounded)
BOUNDED_CACHE                       = YES (explicit TTL + explicit entry bound + eviction)
CACHE_RETAINS_PROVENANCE            = YES (source, freshness, schema version, read time)
CACHE_SERVED_AS_FRESH               = NEVER (hits are labelled cached; failures are not cached)
FULL_HISTORY_MATERIALISED           = NO
PROVENANCE_FIELDS                   = source, symbol, timeframe, first_timestamp,
                                      last_timestamp, row_count, historical_coverage,
                                      freshness, schema_version, as_of, read_at
STORAGE_INTERNALS_EXPOSED           = NO (data_root deliberately dropped by the adapter;
                                      asserted in tests)
```

## AUTHORITY

```
SHARED_HISTORY_AUTHORITY            = DATA ONLY
DIRECTION_AUTHORITY                 = DeepSeek Chief (unchanged)
RISK_AUTHORITY                      = Risk (unchanged, hard safety authority)
EXECUTION_AUTHORITY                 = existing PAPER authority (unchanged)
FACTOR_EXPERT_ML_MEMORY             = EVIDENCE_ONLY
SHARED_HISTORY_GAINED_AUTHORITY     = NONE
LOWRISK_GAINED_HISTORY_WRITER_ROLE  = NO
SINGLE_WRITER_ARCHITECTURE_PRESERVED = YES
STRATEGY_BEHAVIOR_CHANGED           = NO
LEVERAGE_CHANGED                    = NO
RISK_THRESHOLDS_CHANGED             = NO
PROVIDER_STATE_CHANGED              = NO
DEEPSEEK_RESUMED                    = NO
ML_ACTIVATED                        = NO

LOWRISK_SHARED_HISTORY_WRITE_PATHS        = 0
LOWRISK_SHARED_HISTORY_ADMIN_PATHS        = 0
LOWRISK_DIRECT_PARQUET_PATHS              = 0
LOWRISK_DIRECT_DUCKDB_PATHS               = 0
LOWRISK_CHECKPOINT_MUTATION_PATHS         = 0
NO_INSERT_NO_UPDATE_NO_DELETE_NO_ALTER    = PASS (0 SQL write verbs present)
NO_POST_NO_PUT_NO_PATCH_NO_DELETE_HTTP    = PASS (only HTTP verb in source is GET)
PARQUET_APPEND_OVERWRITE_DELETE           = 0
DUCKDB_CREATE_INSERT_UPDATE_DELETE_ALTER  = 0
CHECKPOINT_MUTATION_BACKFILL_INGESTION    = 0
RETENTION_COMPACTION_REPAIR_PRUNING       = 0
WRITER_LOCK_ACQUISITION                   = 0

APPLICATION_LAYER_WRITE_ISOLATION   = PASS
OS_LAYER_WRITE_ISOLATION            = NOT_ENFORCED
                                      (disk ownership/permissions deliberately unchanged,
                                       as the directive requires)
```

## RUNTIME

```
LOWRISK_RUNTIME_DEPLOYMENT_ACCEPTANCE = NOT_DEPLOYED
DEPLOYMENT_AUTHORIZED               = false
PRODUCTION_RESTARTED                = NO
PRODUCTION_TRADING_RUNTIME_STOPPED  = NO
TURBO_MODIFIED_OR_RESTARTED         = NO

SHARED_HISTORY_WRITER_COUNT         = 1
SHARED_HISTORY_WRITER_EXPECTED      = com.sharedmarkethistory.service
SHARED_HISTORY_WRITER_LOCK_HOLDER   = PID 48026 (history-writer.lock, sole holder)
LOWRISK_WRITER_COUNT                = 0
LOWRISK_PROCESSES_SCANNED           = 13, none holding any descriptor on the store

LOWRISK_WRITABLE_FDS_ON_SHARED_HISTORY = 0
LOWRISK_DIRECT_FDS_ON_SHARED_HISTORY   = 0
FD_SAMPLES_COLLECTED                   = 1 188 – 1 359 per probe run
FD_DETECTION_CONTROLS                  = PASS (all 4 positive controls fire)
  control_direct_fd_detected           = true
  control_direct_fd_classified_readonly= true
  control_writable_fd_classified       = true
  control_readonly_fd_not_writable     = true
  (note: on macOS os.readlink("/dev/fd/N") fails EINVAL; the probe uses F_GETPATH.
   Without that fix the sampler could never detect anything and a reported 0 would
   have been meaningless — the control caught it.)

DEEPSEEK_CALLS                      = 0
GLM_CALLS                           = 0
TRADING_DB_WRITES                   = 0

RUNTIME_FACTS_ARTIFACT              = artifacts/shared-history-integration/runtime_facts.json
RUNTIME_PROBE_ARTIFACT              = artifacts/shared-history-integration/runtime_probe.json
PROBE_IS_READ_ONLY                  = YES (safe against production)
```

## PARITY

```
LOWRISK_TURBO_DATA_PARITY           = NOT_ASSESSED
REASON                              = Turbo integration is a separate candidate and this
                                      task must not modify or restart Turbo. Both consumer
                                      clients subclass the same SharedHistoryClient and
                                      read the same localhost endpoint, so parity is
                                      structural, but it is NOT claimed as measured.
CONSUMER_SPECIFIC_INTERPRETATION    = inside each trading system, not in Shared History
```

## TESTS

```
PYTEST                              = PASS
PYTEST_TOTAL                        = 1 263 passed, 0 failed, 1 warning
PYTEST_NEW_TESTS                    = 83 passed
PYTEST_DURATION                     = 247 s
FULL_LOWRISK_DETERMINISTIC_SUITE_RUN= YES (tests/, the whole repository suite)
RUFF                                = PASS
RUFF_COMMAND                        = ruff check (select E,F,I,UP,B,ASYNC; line-length 100)
RUFF_NEW_FILES_FORMAT_CLEAN         = YES (also ruff format clean)
BUSINESS_LOGIC_MODIFIED_TO_SATISFY_TESTS = NO
EXTERNAL_NETWORK_TESTS              = none added; no external network used
                                      (the fake API is an ephemeral loopback server)

TEST_FILES
  tests/shared_history/test_client_contract.py     read interface, GET-only, loopback
  tests/shared_history/test_fail_closed.py         failure semantics, no zero-fill
  tests/shared_history/test_temporal_as_of.py      future leakage, as-of clamping
  tests/shared_history/test_cache_bounds.py        TTL, size bound, provenance
  tests/shared_history/test_write_prohibition.py   AST write/admin prohibition scanner
  tests/shared_history/test_service_envelopes.py   real live payload shapes
  tests/shared_history/conftest.py                 hermetic loopback fake service

SCANNER_RULES_PROVEN_ABLE_TO_FIRE   = YES (10 synthetic violators detected)
                                     ("a condition that cannot fire is worse than a
                                       missing one")
```

## FINAL

```
LOWRISK_INTEGRATION_CODE_SHA        = 76564e7440e67dfda2e87050d94575056873d8bf
                                      (the integration commit: src, tests, probe, docs, evidence)
LOWRISK_INTEGRATION_RECEIPT_SHA     = 4bf860e02c4f27c15d6fcf1ac4d6f8ada3aa5658
                                      (this receipt; the branch tip carries the push record
                                       on top of it — a commit cannot name its own SHA, so the
                                       tip SHA is reported in the delivery message)
LOWRISK_INTEGRATION_BRANCH          = codex/lowrisk-shared-history-readonly-integration
WORKTREE_CLEAN_AT_CODE_COMMIT       = YES
GITHUB_REMOTE                       = PUSHED
REVIEW_REF                          = origin/codex/lowrisk-shared-history-readonly-integration
REMOTE_REF_SHA_AT_PUSH              = 4bf860e02c4f27c15d6fcf1ac4d6f8ada3aa5658
REMOTE_REF_MATCHED_LOCAL_HEAD       = YES (verified with git ls-remote at push time)
PULL_REQUEST_OPENED                 = NO (review ref only; no merge, no main landing)

SHARED_HISTORY_SERVICE_ACCEPTANCE       = PARTIAL
LOWRISK_INTEGRATION_ENGINEERING_ACCEPTANCE = PASS
LOWRISK_RUNTIME_DEPLOYMENT_ACCEPTANCE   = NOT_DEPLOYED
STRATEGY_ACCEPTANCE                     = NOT_ASSESSED

LOWRISK_SHARED_HISTORY_ENABLED      = false
PAPER_ONLY                          = TRUE
LIVE_TRADING                        = FALSE
DEPLOYMENT_AUTHORIZED               = false
MAIN_LANDING_READY                  = NO (not requested; no merge to main performed)

BLOCKERS
  P0_OPEN = 0
  P1_OPEN = 1  (producer defect: 4 endpoints HTTP 500 for 92.5% of the universe;
                requires a separate Shared History remediation phase)
  P2_OPEN = 1  (producer: /v1/stats latency >10 s; health_snapshot refresher cadence)

GOVERNING PRINCIPLE
  ONE SHARED FACTUAL HISTORICAL MARKET DATA SOURCE.
  SHARED DATA. INDEPENDENT INTELLIGENCE. INDEPENDENT RISK. INDEPENDENT EXECUTION.
```

### What was NOT done, deliberately

* Not deployed; no LowRisk production restart; the running PAPER runtime was untouched.
* No merge to main and no main-landing authorization requested.
* No change to strategy, Risk, sizing, leverage, execution, factors, ML, Growth or
  DeepSeek. Provider state preserved exactly.
* No historical writer, ingestion, backfill, retention, compaction, repair or
  checkpoint role granted to LowRisk.
* No disk ownership or permission changes (hence `OS_LAYER_WRITE_ISOLATION =
  NOT_ENFORCED`).
* The producer defect was reported, not patched, because fixing it would modify the
  running single-writer production service.
* Turbo was neither modified nor restarted; Turbo parity is therefore not measured.