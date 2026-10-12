# P4.3-G0 exact implementation admission map — not implementation

Baseline engineering77702929f03ab6c5d9a8e1f6b75faaf8c4429ef6.
Actual SH source profiles P25505ff15dd6acd623140d70c0a8eb216c59ea48 and
Cb1a3f97b213d062ed70375ac7aedbd0d67745a0b. Function spans/file hashes reuse
P42R sink/edge records and previously reviewed recovery contracts. No original
source, contract, knowledge or immutable receipt is overwritten.

| Candidate file | Exact functions | Current proven defect | Minimal proposed change | Affected callers / compatibility | Fail-first / desired result / rollback |
|---|---|---|---|---|---|
| storage/checkpoint_store.py | __init__, _dir, path_for, load, list_all, save, mark_started, mark_success, mark_error, mark_paused | read mkdir/defaults, unchecked schema, no owner/CAS, stale overwrite | C1 root-scoped authenticated coordinator; C2 immutable raw-byte expectation and protected compare+replace; C3 typed outcomes without read mkdir; C4 explicit publish outcome | All30routes; unknown/restored/nested bool-int fields retained; no invented revision/opID; valid historical dict shape must stay compatible or caller-scope amendment required | Corrupt/CAS red tests; controlled unknown state cannot initialize; stale write refused. Rollback candidate only, original bytes/readers unchanged |
| storage/writer_lease.py | __init__, acquire, release, held | fd presence/advisory lifetime not Store authority; inherited fd/PID changes not authenticated | C1 explicit owner/root/inode/process-generation validation; invalidate after release/fork; same-root same-process coordinator | Runtime/CLI/background/Store; not OS enforcement against noncooperative same UID. No writer lock is opened here | Existing lease-bypass reproductions; future owner-loss/inode/fork negatives must reject. Roll back candidate only |
| storage/atomic.py | new checkpoint-only publish helper; existing atomic_write_bytes/json/text, fsync_dir/file untouched by default | global helper swallows directory-open failure, outcome ambiguous after replace | C4 prefer checkpoint-specific raw publish/outcome path under existing allowed file, NOT global durability-semantic change | Generic Evidence/Parquet helpers unchanged; any shared behavior change needs explicit non-checkpoint regression and additional approval | Directory-open red test; pre/postreplace fixtures; NOT_COMMITTED/DURABLE/UNKNOWN distinct. No blind rollback of committed bytes |
| backfill/engine.py | __init__, _timed_ckpt, run_task, _run_candle_backfill, _run_candle_forward, _run_funding_task, _run_oi_task; candidate _post_resume_freshness_tail for adapter only | all workers use unowned Store; invalid state appears new; broad catch mark_error may resave uncertain commit | Inject authenticated Store/coordinator, propagate invalid load/CAS/owner failures; quarantine unknown commit instead of blind mark_error/replay | Task/data-domain algorithms and cursor rules frozen. Preserve completed+forward work and old field clocks. Tail logic not redesigned | Actual run_task handler + fixture leaf confirms two publishes after uncertainty; after fix no second business write. Candidate rollback, no production rollback/repair |
| backfill/background.py | __init__, start, _run_loop, state, stop | public external legacy start has no lease; state constructs read Store | Explicit admitted owner supplied or reject writable start; read state no mkdir. Do not silently give a legacy external caller a service lease | No known internal constructor; external entry remains gated; unchanged worker scheduling/resource thresholds | Lease-bypass/sourceroute baseline; future admitted/unadmitted start tests. No real start here |
| __main__.py | _backfill, _serve, main dispatch only if needed | CLI engine.run no lease; runtime construction before service acquire | C1 acquire verified owner before writable assembly; lifetime finally-release; explicit Store injection | Existing argparse/tasks/progress semantics unchanged; no network/ingestion probe in G0 | Actual _backfill body with stub engine and real Store reproduces leaf bypass; full real engine boot NOT tested |
| runtime.py | __init__, serve_forever, start_background | separate lease does not authorize Store; pre-try startup exceptions bypass explicit cleanup | Ownership before writable assembly; one guarded try/finally for admitted startup and cleanup; inject same coordinator | Producer resource/market/operational contracts unchanged. No duplicate instance/new service behavior | Actual lease/Store fixtures, source lifecycle proof; future constructor/prepare/start failure tests required before implementation acceptance |

Paths above are relative to src/shared_market_history. Seven paths are an upper
bound, not instructions to modify all files. New G0 tests live in this engineering
repo as tests/test_p43g0_fail_first.py and tests/test_p43g0_route_baseline.py.
No actual SH tests or business modules have been patched.

## Contracts and remaining decisions

C1/C2/C3/C4 = existing reviewed contracts, not newly redesigned.
C5 = in-process conflict/unknown-outcome fail-closed proposal only; cross-restart
retry identity remains BLOCKED. If persistent operation IDs are required, a
separate format migration/admission/compatibility contract is necessary.
No revision field, operation-ID field or old-file conversion is authorized.

ADDITIONAL_SOURCE_SCOPE_REQUIRED = CONDITIONAL_READ_CALLER_COMPATIBILITY_GATE.
api/service.py:_metadata_coverage/get_metadata, observability/stats.py:list_all
consumers/refresh_snapshot and maintenance.py:_checkpoint_index/_resolution/
_max_1m_freshness_seconds expect dictionary/list semantics today. A typed-result
signature replacement requires caller adaptation outside the seven-file bound.
Preferred minimal option: preserve VALID dictionary/list interface while exposing
typed failure outcomes at a checkpoint-specific boundary; no fresh defaults on
corrupt/unreadable state. Before choosing that option, test missing/invalid/version
states through these consumers. If adaptation is necessary, request the exact
additional files/functions, never auto-expand scope. No Parquet patch proposed.

P43_IMPLEMENTATION_SCOPE = BLOCKED_FOR_FULL_C1_C5_PROMOTION_PENDING_ADMISSION.
The file/function map is reviewable; it is not an approved patch or migration.
Do not claim seven-file scope already resolves all read callers, schema population,
independent identities or cross-restart idempotency.

Future authorization request: exact isolated SH baseline/branch; permitted seven
files and selected functions; preserve old field/namespace semantics; no global
helper drift; authorize explicit additional read-caller adaptation only after its
compatibility negatives establish necessity; retain no production/T1/provider/boot
authority. No strategy/factor/Chief/Risk/KB/Quant/Turbo change.
