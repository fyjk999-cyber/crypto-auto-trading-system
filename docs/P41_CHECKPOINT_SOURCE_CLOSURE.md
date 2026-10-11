# P4.1 checkpoint source audit and recovery proposal

Scope: Git source only. Producer `25505ff15dd6acd623140d70c0a8eb216c59ea48`;
candidate `b1a3f97b213d062ed70375ac7aedbd0d67745a0b`.
No runtime paths, DBs, checkpoint contents, provider calls or services were used.

## Coverage and limits

`P41_SOURCE_INVENTORY.json` enumerates every tracked Python/shell/plist file under
src/scripts/tests and pyproject.toml in each pinned version: producer 85 files,
candidate 88. It records byte hashes, all function definitions, imports, lexical
checkpoint/lease/atomic/callback/dynamic targets and exact field-token sites.
826/872 function definitions include test helpers; these are NOT counts of proven
production entrypoints. Literal fields include unrelated records; a token hit is
not automatically a checkpoint reader. This is a reproducible index, not a whole
program points-to analysis. No missing AST match is proof of absence.

22 additional tracked artifact scripts are named but not read or executed: their
project scope includes unrelated recovery/migration work. Classification is
OUTSIDE_REPOSITORY_SCOPE, not unreachable. Installed launchd wrappers, arbitrary
external Python users and injected store/client callbacks remain unknown.
FULL_SOURCE_CLOSURE = BLOCKED. Unknown control keys stay protected.

`P41_ENTRYPOINT_MATRIX.json` gives function-level chains and the requested fields.
These chains prove named repository routes, not the entire external caller set.
Errors in dependencies are not converted to a safe classification.

## Read/write source conclusions

CheckpointStore (identical in both versions) owns JSON writes through save :73–83.
mark_started :85–89, mark_success :91–120, mark_error :122–127 and mark_paused
:129–134 load-modify-save without CAS or an ownership check. `_trace_tls` is
thread-local diagnostics, not mutual exclusion. Atomic replace prevents partial
JSON publication, not competing whole-state writes or stale overwrites.
No store delete method exists. Forward completion pops three control keys in the
engine as a documented transition, not metadata exclusion. The general public
cleanup_stale_temp_files helper deletes old temp names and is not a checkpoint
delete contract; its arbitrary caller/root is outside demonstrated ownership.

`__main__.main :64–91 → _backfill :135–178 → engine.run` acquires no WriterLease.
The validation shell script reaches exactly this CLI. The fixture executes the
actual `_backfill` body with discovery/engine dependencies replaced and the real
CheckpointStore at the leaf; no network/Parquet/real CLI launch occurs.
This proves an absent CLI lease, not an actual production duplicate writer event.

`runtime.serve_forever :97–160` acquires its service lease before background start.
However constructors ensure directories before acquire; a failed pre-server
prepare/start/build is outside its later finally block. This lifetime wrapper
does not make CheckpointStore itself ownership-aware. Direct LandingController,
BackgroundBackfill or BackfillEngine callers can bypass it. Do not run those
constructors in this phase to infer their runtime effects.

maintenance.start :234–248 launches main and deferred threads. Main :586–629
reaches stage :647–773 or maintenance :857–1010; incremental :1165–1194 and deferred
:1142–1163 both reach engine.run. Service lease is inherited only when invoked
under runtime. Candidate and producer share these controller paths. No independent
per-key CAS exists. Distinct timeframes reduce some normal overlap, but do not
prove immunity to duplicate tasks, external callers, retries or injected stores.

Actual engine.run uses ThreadPoolExecutor; run_task dispatches candle/funding/OI;
_timed_ckpt accepts a callable; trace callbacks and injected dependencies are not
globally resolved. Named callback destinations are in the matrix. Every engine
checkpoint call is indexed with its containing function and source line.

### Completion, status, pause and freshness are not interchangeable

producer engine :536–544 sets IN_PROGRESS without clearing historical completed.
_persist_forward_progress :680–687 preserves completed while advancing forward
work. Candidate shifts these locations and additionally validates daily domains;
the inventory supplies version-specific locations, not reused producer line numbers.

maintenance._resolution :374–394 counts completed and skips failure classification
when true; _terminal_dataset_status :476–502 requires completed plus anchors.
stats._compute_checkpoint_summary :342–359 counts historical completion separately
from ERROR/PAUSED, and suppresses in_progress counts for completed entries.
API._metadata_coverage :252–254 treats completed as sufficient for archive coverage
on unlimited-retention timeframes. engine.run_task :1061–1066 uses completed or
forward_in_progress to choose forward work. These consumers answer different
questions; changing completed/status to look consistent would change behavior.

Current 1m freshness uses newest_fetched + full eligible universe + independent
300s validation (maintenance :1219 onward). Completion/operational publication
does not refresh market time. last_success_at is consumed by stats :351 and public
latest_update/last_ingestion_at, not equivalent to newest_fetched. updated_at is
stamped on save; metadata stage-cursor timestamps with the same name are a
different object. No digest exclusion is authorized.

pause_reason has a store writer and survives subsequent mark_started/success;
there is no named pinned production reader in this index. A surviving reason is
not proof that a particular historical event was superseded, nor proof a checkpoint
was never paused when the field is absent. G1 order §5a's historical reconstruction
is possible but not established by the current source alone.

## Atomic/load defects and caller recovery

atomic.py :36–53 writes a unique temp, flushes/fsyncs the file, replaces, then
fsyncs parent. fsync_dir :23–32 silently returns if directory open fails, but
propagates an fsync failure after successful open. Both pinned versions reproduce
these distinctions. File-fsync/rename failures before publication leave old bytes;
failure after replace leaves new bytes despite an exception. No power-loss/crash
durability claim follows from exception injection on a temporary filesystem.

engine.run_task's broad except (producer :1072–1080, candidate :1099 onward) calls
mark_error, which reloads the possibly committed state and writes ERROR while
preserving completed. mark_error itself can fail and escape. Repeated identical
failure increments retry_count; there is no operation identifier/idempotent retry
contract. The post-rename test demonstrates the leaf transition; the entire
thread/network runner is NOT executed. Simply raising fsync errors does not solve
commit ambiguity or recovery semantics.

load calls path_for → _dir.mkdir even on reads. read_json :63–69 returns defaults
for missing, malformed, unreadable documents; load ignores non-dict JSON and
accepts unvalidated dict types. Corrupt historical state can therefore look fresh
to the dispatcher. Valid dict unknown fields survive load/save/mark_success.
This preservation is not a restored_* migration or an authenticated history proof.

## Historical source investigation

Local repository has 158 reachable commits at observation, no tags returned.
`git log --all -S restored_ -- src scripts` returns no introduction/removal commit.
Both pinned versions and known earliest checkpoint source contain no restored_*
writer. This is a bounded local-history result; unavailable/unfetched/unreachable
commits and one-off external repair scripts are not ruled out.

Initial known implementation `83b445f1144976cac820cc04964a0a884f7e75df`
(2026-09-18) contains the 12 base fields, updated_at, pause_reason and forward
in_progress/latest/cursor. Persistent forward_bridge_start_ms first known in
`cd0ab513582731a88930de01cf261fe1f099b7b5` (2026-10-08), whose diff shows the
fixed anchor/SAFE_LEGACY_UNSTARTED/AMBIGUOUS_LEGACY_PARTIAL recovery policy.
Other reachable branches have bounded retry-backoff additions; they are not the
pinned producer/candidate and do not establish current checkpoint populations.

Saved Harness rounds 254/255 are narrative evidence, not the missing writer source.
Their reason-string-to-earlier-release inference cannot identify an actual commit,
writer, authorization or original bytes. G1 order's daily-only 485 count and old
493 set differ; neither is refreshed here. SOURCE_ORIGIN_PARTIAL applies to the
documented forward-completion semantics. For restored_completed_at/restored_reason
writer/origin/migration: SOURCE_ORIGIN_NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE.
Never synthesize a historical checkpoint or label the preservation test a migration.

## Field catalog — separately bound to each version

`P41_FIELD_CATALOG.json` contains separate producer/candidate records, defaults,
types, readers, writers, serializers, recovery rules and known introduction.
20 is a known source-plus-legacy-reference set, not a proven current full keyset.
Types describe implementation intention, not enforced validation. Serialized
arbitrary dict keys and injected/external callers prevent schema completeness.
METADATA_EXCLUSION_ALLOWLIST = [].

The saved capture script's whitelist has 21 keys. Extra projection keys are inst_id,
listing_time, retention_days, target_start_ms, schema_version. Known 20 keys omitted
from it are last_error, pause_reason, restored_completed_at, restored_reason.
Intersecting counts do not prove T0 or T1 equivalence. Original history gap remains.

## Recovery-changing proposals — NOT IMPLEMENTED

Every proposed fix changes caller/recovery behavior; obey P4.1 §6 by stopping
automatic implementation pending independent engineering review:

1. Require explicit lease capability on every writer entry (CLI included); reject
failed ownership before touching stores. Define initialization and release-on-
prepare-error behavior; per-key CAS must preserve whole unknown/origin control.
2. Distinguish absent checkpoint from corrupt/unreadable/schema-invalid; fail
closed without creating read directories. Audit API/stats/maintenance callers'
new exceptions so error handling cannot restart history from defaults.
3. Define committed-but-not-durably-synced separately from not-committed. Parent
sync failures must not claim success; callers must reconcile immutable operation
identity before any retry/mark_error. Preserve original bytes/errors and do not
automatically roll back an already-replaced state.
4. Define full-object raw CAS under ownership and operation IDs for retries;
reject stale observations without dropping unknown keys. Prove same-process,
cross-process and callback/injected paths; no synthetic revision can substitute
for an approved production format/migration contract.

PRODUCTION_PATCH = NONE. ISOLATED_REMEDIATIONS = PROPOSALS_ONLY.
Existing P4 rewritten CAS fixture is not a fix to these actual source modules.
Strict xfail safety contracts remain explicitly FAIL (6 parameterized failures),
not downgraded warnings. Focused reproduction pass means the defects are reproduced.

## Remaining gates

Source closure is partial; external dynamic and restored-origin paths unresolved.
G1_ORIGINAL BLOCKED; G1_WAIVER NO; T0_EQUIVALENCE_395 NOT_PROVABLE;
G1_R NOT_FORMALLY_ACCEPTED; T1_ACTUAL_CAPTURE NOT_RUN; independent custody absent;
G2 old budget FAIL, G2_R not newly accepted; PAPER not started; soak credit 0.
Next: independent review of this source audit and explicit recovery contract,
then a bounded isolated implementation stage if accepted. Production maintenance,
read/capture, installation, deployment, boot and natural acceptance require their
own later authorization. No strategy/factor or Quant work follows automatically.
