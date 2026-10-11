# Fixed-version delta content audit

Read-only Git diff producer 25505ff15dd6acd623140d70c0a8eb216c59ea48 to candidate b1a3f97b213d062ed70375ac7aedbd0d67745a0b. All 16 changed source/test files' diff content read. No changed file imported/executed here. Complete per-file hashes and function names remain in source index; this is a semantic delta audit, not whole-program receiver closure.

| File (under src/shared_market_history unless tests/) | Semantic delta and checkpoint relevance |
|---|---|
| backfill/engine.py | daily canonical boundary validation, explicit legacy mixed-window rejection; post-resume 1m bounded tail only after proven bridge completion; one new method and three selected checkpoint calls. No lease/CAS added. Broad run_task recovery still mark_error. Tail can reach load/save through _run_candle_forward; exact candidate locations indexed, not producer line numbers reused. |
| candle_series.py | Two added pure ownership predicate/validation functions; no checkpoint writes. Canonical OKX daily UTC16 and derived UTC00 separated. |
| config.py | Added derived_daily_root property; no checkpoint path/format change. |
| integrity.py | Two query ownership filters, no new functions or checkpoint sink. |
| retention/manager.py | _target_index selects derived daily for 1d, not canonical; changes dependent data reader, no new checkpoint operation. |
| storage/aggregation.py | Daily materialization dispatches write_derived_daily; data mutation path, not checkpoint writer; never executed this phase. |
| storage/parquet_store.py | Three new methods: write_derived_daily, _candle_files, _series_dedup. Public read/write ownership validation, derived namespace and dedup behavior; daily count scans rows, recent daily reader includes all months. No CheckpointStore change; future atomic changes require other callers' regressions. |
| timeframes.py | Five added helpers _boundary_offset/is_valid_open/next_open/previous_open/initial_forward_cursor and daily floor/latest-closed changes. Temporal control semantics differ; do not normalize candidate cursors back to producer domain. |
| tests/test_aggregation_retention.py | Existing daily fixture moved to provider boundary. No new functions/call count. |
| tests/test_contract_api.py | Existing provider daily and newly listed first-open fixtures aligned. No new functions/call count. |
| tests/test_daily_series_ownership.py | 15 new definitions including fixture helper; ten selected calls, including actual-store checkpoint tests under test settings. Not ten new production writer entrypoints. |
| tests/test_features.py | Daily fixture uses provider boundary; import only, no new function/call count. |
| tests/test_forward_bridge_durability.py | Existing zero target assertion separates old bridge window and factual tail request. No new functions/call count. |
| tests/test_freshness_decoupling.py | Daily closed-bar boundary assertion now canonical phase; no new functions/call count. |
| tests/test_incremental_causal_trace.py | Existing trace asserts old bridge then bounded tail; minute fixture changed 1ms→0 valid boundary. No new definitions/selected call net change. |
| tests/test_safe_freshness_tail.py | 19 definitions including nested fake crash callbacks/guard helpers; 35 selected calls. Isolated source tests describe factual-shaped fixtures, not actual production crash/72h proof. |

Count reconciliation: functions +46 = engine1 + candle_series2 + config1 + parquet3 + timeframes5 + daily_tests15 + tail_tests19. Selected lexical calls +48 = engine3 + daily_tests10 + tail_tests35. Files +3 = candle_series + two test modules. Other nine modified files can change semantics without increasing these counts. Added 22 historical artifact scripts are identical across the pinned versions and were outside the old directory selector, not newly introduced candidate files.

Remaining internal receiver/caller certification and route-specific retry/error evidence are explicitly pending. These differences do not establish runtime provenance, live file populations, full field schemas, or production readiness.
