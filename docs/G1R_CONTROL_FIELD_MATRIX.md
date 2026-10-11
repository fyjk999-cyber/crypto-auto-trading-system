# G1R_CONTROL_FIELD_MATRIX — known source fields, not current inventory

Versions, per-file hashes and exact reference rows are in the accompanying
`P4_SOURCE_LITERAL_AND_CALL_CATALOG.json`. Primary source is
`storage/checkpoint_store.py::load/save/mark_*` at both pinned versions; forward
fields originate in `backfill/engine.py::_run_candle_forward/_persist_forward_progress`.
The complete actual current keyset remains UNKNOWN until separately admitted T1.
JSON types below are intended source forms, not schema validation guarantees.

| Field | Source/default/type | Interpretation / protection |
|---|---|---|
| dataset | load; string argument | path identity; preserve |
| symbol | load; uppercase string argument | path and task identity; preserve |
| timeframe | load; string/null | domain/path/time boundary; preserve |
| oldest_fetched | load null; mark_success integer min | backward coverage / maintenance terminal state |
| newest_fetched | load null; mark_success integer max, forward persist | moving watermark, never immutable origin |
| next_cursor | load null; mark_success integer/oldest fallback | backward restart cursor |
| status | load NOT_STARTED; mark_started/success/error/paused string | independent from completed; no status-only rewrite |
| completed | load false; mark_success bool; forward preservation | scheduler, coverage and next-action authority |
| last_error | load null; mark_error bounded string | retry/error evidence; not excluded |
| retry_count | load 0; mark_error int increment | retry/terminal classification |
| last_success_at | load null; mark_success/forward now integer ms | stats/health latest ingestion; protected clock |
| source | load okx string; existing payload overrides | origin evidence, protected |
| updated_at | absent in load defaults; save now integer ms | persistence observation clock, not origin; protected |
| forward_in_progress | absent; forward bool | independent forward state, dispatcher |
| forward_bridge_start_ms | absent; derived newest stored + interval int | bridge start, not original lower-origin proof |
| forward_cursor | absent; forward int | mutable pagination cursor |
| forward_latest | absent; forward int | phase target watermark |
| pause_reason | absent; mark_paused bounded string | residual may survive later status; don't clear |
| restored_completed_at | absent; writer source UNKNOWN | historical restoration provenance, protected |
| restored_reason | absent; writer source UNKNOWN | historical restoration provenance, protected |

This 20-field source catalog is not the old 21-key projection and is not a claim
that only 20 keys exist. Full objects, extra keys, types and raw bytes must be
captured in T1. No absent key is populated from today's state into old T0.
All known read/write literals are indexed, but alias/dynamic semantic closure is
still BLOCKED. Candidate differences are separately indexed, not assumed equal.

`CONTROL_FIELD_SET_COMPLETE = BLOCKED`
`METADATA_EXCLUSION_ALLOWLIST = []`
`T0_EQUIVALENCE_395 = NOT_PROVABLE`
