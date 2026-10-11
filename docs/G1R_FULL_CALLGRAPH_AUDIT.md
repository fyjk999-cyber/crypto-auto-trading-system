# G1-R static control audit — partial, fail closed

Subject versions: producer-source `25505ff15dd6acd623140d70c0a8eb216c59ea48`
and candidate `b1a3f97b213d062ed70375ac7aedbd0d67745a0b`. These are Git
source identities, not observations of the current running process.

`P4_SOURCE_LITERAL_AND_CALL_CATALOG.json` preserves per-file SHA256, exact line,
function and version for discovered references (16 files/version, 245/249 field
literal references). It is a search index, NOT an exhaustive semantic callgraph.
All catalog calls remain unresolved until manually mapped below; aliasing,
callbacks, external scripts and historical versions cannot be ruled out by AST.

## Known source paths

Line citations in this section are for 25505ff; candidate changed functions must
be traced independently. The catalog retains both source versions, not inferred
line equivalence. Paths below describe source behavior; none was executed.

| Class | Origin → functions → sink | Ownership / CAS / recovery |
|---|---|---|
| Service writer | `__main__.py:96 _serve` → `runtime.py:96 serve_forever` → `WriterLease.acquire` → `start_background` → LandingController scheduler → BackfillEngine.run/run_task | Runtime lifetime advisory lease; individual checkpoint writes do not perform CAS. Worker identity is not authenticated per entry. |
| Manual writer | `__main__.py:135 _backfill` → build tasks → `engine.run:1134` → worker | This inspected CLI function does not acquire WriterLease; outside wrappers UNKNOWN. Do not infer service-wide lease protects every invocation. |
| Candle backward | `engine.py:335 _run_candle_backfill` → load/mark_started → fetch → `_flush_candle_buffer:312` → Parquet writes + mark_success → save | Partial pagination, stop/resource pause, retry errors. No raw CAS inside CheckpointStore. Unknown external writers can cause lost updates. |
| Candle forward | `engine.py:504 _run_candle_forward` → classifier/load → bridge init → `_persist_forward_progress:666` → save; completion reload/save:648–656 | Anchor from newest stored is a derived watermark, not original-origin recovery. Ambiguous legacy partial remains fail closed; catalog does not prove all crash paths. |
| Funding/OI | `engine.py:700/876` task → load/mark_started → write/flush:833,852,999,1018 → mark_success/save | Completed and cursor change task behavior; no per-file CAS. |
| Common create/reload | `checkpoint_store.py:49 load` → path_for → `_dir:38` → read_json → defaults merged with full payload | Even load can mkdir; read_json defaults on parse/I/O failure. Unknown keys preserved, not validated as safe metadata. |
| Common serialization/write | `checkpoint_store.py:73 save` → updated_at → `atomic_write_json` → temp write/flush/file fsync → replace → fsync_dir | Atomic replace is not CAS. `storage/atomic.py` silently returns on directory-open failure; no production durability guarantee inferred. |
| Discovery/retry | `checkpoint_store.py:132 list_all`, pending_count → scheduler/checkpoint index `maintenance.py:334` → `_resolution:354` → stage/incremental tasks | completed and status are independently interpreted; retry_count/error and coverage bounds matter. Missing/invalid documents are not a proven safe recovery. |
| API consumer | `api/service.py:252 _coverage_status` → load → completed → COMPLETE for long retention | Read consumer can call mkdir path; no I/O-free or observational guarantee claimed for this API. |
| Stats consumer | `stats.py` coverage → oldest/newest/completed/status/last_success_at → health output | Timestamps influence observability; no semantic-exclusion proof. |
| Background alternative | `backfill/background.py:86 _run_loop` → scheduler/engine; recent external activity:73 | File mtimes are not an ownership proof. Reachability from current service versus historical configuration UNKNOWN. |
| Maintenance/retention | LandingController deferred/stage/incremental paths; RetentionManager constructor owns CheckpointStore | Construction alone is not read/write proof. Complete retention/aggregation closure still UNKNOWN. |
| Reconciliation/CAS/migration | Old run-scoped forensic/CAS plans + isolated P4 laboratory | No production CAS implementation certified. Historical restored_* origin and external manual tools UNKNOWN. |

WriterLease (`storage/writer_lease.py`) uses writable lock FD, nonblocking flock,
PID text, truncate/write/fsync; its helper `live_writer_count` attempts a writable
FD and lock probe. Neither helper was executed. A lock file PID alone is not a
verified unique live owner. CheckpointStore does not enforce this lease itself.

## Explicit remaining unknowns

- Historical `restored_completed_at` / `restored_reason` producers and all old
  release/manual restoration consumers; source absence in these two versions is
  not proof of harmlessness.
- Complete alias, callback, reflection, imported helper and manual/migration
  closure; catalog omits non-key-bearing files unless checkpoint/lease markers
  select them. This is a documented limitation, not exhaustive coverage.
- Candidate-specific full semantic review and all maintenance/retention sinks.
- Actual current checkpoint key universe, types and unknown residual keys:
  production capture was prohibited and not performed.
- Lease protection of every writer and authenticated maintenance ownership.

`METADATA_EXCLUSION_ALLOWLIST = []`; preserve all unknown fields and both clocks.
`FULL_CALLGRAPH_COMPLETENESS = BLOCKED`; `G1_R = NOT_FORMALLY_ACCEPTED`.
Next safe work is source-only closure of these unknowns, not production capture.

The first oversized search result was truncated and discarded; the reduced
catalog was recaptured without interpreting a truncated result as evidence.
