# Fixed-source artifact content audit

Sources: producer 25505ff15dd6acd623140d70c0a8eb216c59ea48 and candidate b1a3f97b213d062ed70375ac7aedbd0d67745a0b. All 22 artifact scripts were read from producer Git objects. `git diff --stat ... -- artifacts` is empty: candidate artifact bytes are unchanged. Per-file hashes/index still need durable generated custody. No script was imported or executed. Reads of historical SH orchestration source do not authorize following its external LowRisk/Turbo/ML dependencies.

| File basename | Content classification and effects if executed |
|---|---|
| concurrent_load_monitor.py | Reads landing state/process census/HTTP, writes arbitrary --out append and 2MiB external probe with fsync/unlink. Not read-only filesystem. No checkpoint sink. |
| evaluate_final_convergence.py | Reads landing/evidence/ML metadata and lake census, subprocesses service imports and live_writer_count, writes --receipt-out. Has historical fixed PASS and empty universe acceptance; NOT current admission logic. External invoked imports unresolved. |
| pass_observer.py | Reads landing and prior output; appends pass outcomes, fixed historic window. No service state write. |
| pass_observer_watchdog.sh | pgrep then nohup python3 observer; writes log and spawns process. Installed scheduling/executable binding unknown. |
| render_receipt.py | Reads aggregate receipt, writes Markdown, repeats static provenance statements without independent verification. No checkpoint sink. |
| reset_state_i_gates.py | Direct landing_state read-copy-full-object temporary replace without lease/CAS/fsync; gate/soak deletion plus confirmation polls. This is an auxiliary metadata writer, not a CheckpointStore sink; unauthenticated concurrency boundary retained. Never execute in this phase. |
| soak_closer.py | Reads landing; appends logs/trajectory, launches evaluator and renderer with side effects above. Fixed historic 24h window is not LowRisk 72h credit. |
| soak_health.py | Reads landing/evidence and pgrep, stdout only. No checkpoint writes. |
| soak_monitor.py | Reads landing/topology, pgrep/ps eww (environment credential exposure risk), invokes service/ML imports via subprocess, appends output. Indirect writer-lock collector and environment-selected ML dependencies unresolved; not safe inventory admission. |
| copy_acceptance.py | Reads caller-selected JSON/log, writes arbitrary --out; absent/default validation may manufacture PASS including empty maps. Not checkpoint source or trustworthy current gate. |
| path_switch_acceptance.py | Imports external ML configuration/readers, ensures availability, reads dataset/manifests, trains scratch artifacts, writes --out. External implementation effects unresolved; no execution. |
| post_delete_write_proof.py | Reads/hashes ML dataset, moves canonical object with os.replace to force natural producer recovery, may rmtree aside, writes receipt. Active production-data mutation ability; no lease/CAS shown; strictly forbidden execution. |
| scan_dataset_root.py | Full raw dataset reads/hashes and ProcessPoolExecutor, arbitrary report output. Not bounded metadata inventory; no checkpoint sink. |
| space_reclaim.py | Reads receipts/plists/data census, external write probe, lsof/diskutil; unlinks local dataset objects after gates and sync; static invariant claims. Destructive data workflow not authorized here. |
| validate_dataset_root.py | Full raw JSON reads/parsing, process pool, external ML reader imports, report output. No CheckpointStore sink; external ML side effects unresolved. |
| chain_check.py | Reads heartbeat/alarm files/path metadata, ps-equivalent pgrep/launchctl/diskutil, writes chain_status. Stale/future heartbeat handling is not current LowRisk acceptance; no checkpoint sink. |
| liveness_supervisor.py | Reads heartbeat/path metadata, subprocess process/disk census, writes alarms/heartbeat/logs. Environment selects cadence, no producer operation. |
| r10_receipt.py | Reads landing/samples/alarms; imported runtime_observation can read execution SQLite/API/processes; writes report. Unsafe for this source-only phase; no checkpoint write. |
| r6_cycles.py | sys.path-selected import of validate_three_cycles main; invokes qualification which is outside this phase. Repository target source indexed in P4.1; current external execution context unknown. |
| recovery_monitor.py | Reads landing/topology and runtime_observation; 4KiB external probe fsync/unlink, API/process commands; writes monitor outputs. Docstring read-only is narrower than real effects. |
| runtime_observation.py | import-time sys.path modifications; qualification evidence reads; lease_snapshot opens external execution DB via mode=ro SQLite and PRAGMA; API curl, host/process identity. producer_truth routes FULL_MARKET successor --db to lease_snapshot. Cross-project runtime DB dependency, no direct checkpoint write; must never invoke here. |
| soak_r9.py | Reads landing/evidence/lake census, imports layout/runtime_observation; external probe, HTTP/process/sysctl commands; writes watch/state/evaluation. No checkpoint write, broad data/DB side effects indirect. Legacy 24h thresholds not reused. |

All Python entrypoints are main except r6 import wrapper and soak_r9 watch/evaluate dispatch; helper/import/subprocess callsite enumeration to be generated separately. No literal restored_* writer found in the reviewed 22 scripts. This does not prove external origin absent. Unknown external imports and env/sys.path selection remain blocked, not ignored.

This completes human content reading of these named artifacts only, NOT all repository function semantics, Full Runtime Closure, or current service evidence. One combined output was capped; space_reclaim was reread alone in full before classification. No truncated content used as completed audit.
