# Future implementation plan — not authority to implement

P4.2 proposes contracts only. P4.3 must name exact source base, files and accepted contract clauses. Format/independent identity changes remain separate blockers.

| Future file/function | Callers/reach | Proposed behavior | Required gate and tests |
|---|---|---|---|
| storage/checkpoint_store.py load/path_for | API, stats, maintenance, engine, repair callers | Typed nonmutating read, preserved unknown keys | Approved historical schema + all six load outcomes and caller regressions |
| storage/checkpoint_store.py save/mark_* | All engine/control routes, direct external users | Proven ownership + root coordinator + raw CAS, no blind reload overwrite | Actual lease/CAS negative tests, external exclusion/compatibility |
| storage/writer_lease.py | runtime, CLI, direct controllers | Authenticated stable FD/inode lifetime and fork safety | Fixture OS/process tests; canonical-volume/identity admission later |
| storage/atomic.py atomic_write_bytes/fsync_dir | CP and metadata publication | Explicit uncertainty after replace, parent failures not swallowed | Fault matrix, postread, no power-loss overclaim |
| runtime.py serve_forever | service startup/background lifecycle | Acquire before mutation, release on prep failure, drain workers before release | All prep failures and active callback shutdown |
| __main__.py _backfill | CLI/validation shell | Same canonical owner admission as service | Occupied/missing/unverified capability rejection before fetch/CP |
| backfill/engine.py run_task/_timed_ckpt | Backfill/funding/OI/incremental/thread callbacks | Typed load/CAS/ownership/durability handling; mark_error only admitted business error | No fresh reset after corrupt, concurrent completion, uncertainty halt |
| maintenance.py stage/deferred/resolution | Controller loops/API aggregated state | Unknown/error preserved, no defaults interpreted as complete/fresh | Domain/freshness regression and error isolation policy |
| stats.py / api.py read consumers | Public health/coverage/status | Unavailable evidence explicit, no read mkdir/fake current state | Existing legacy API fields/semantics preserved except explicit errors |

Additional tracked reset_state_i_gates and direct callers require explicit admission or exclusion; no automatic removal/rewrite. External ML/Turbo readers or installed wrappers remain outside this implementation's authority. Do not follow them to fix this scope.

Deployment risks: old writers bypass new advisory lock/CAS, legacy schemas might be rejected, uncertain commit recovery could duplicate work, metadata atomic helper may have other callers. Before deployment: full applicable SH suites, exact-SHA independent review, format/rollback contract, single admitted writer enforcement, safe production preflight and separately authorized maintenance. Rollback is not file rollback: never overwrite unknown committed state with old CP bytes. Halt if older code cannot safely interpret state; use reviewed reconciliation, not automatic service restart.

No production installation, field format change, provider, T1 capture, gate adoption or PAPER launch is authorized by this plan.
