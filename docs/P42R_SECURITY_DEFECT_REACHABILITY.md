# P4.2-R reachability and authority are separate

Fixed versions and per-edge hashes/lines: P42R_INTERNAL_CALL_EDGES.json.
Sink capability registry: P42R_CHECKPOINT_SINK_REGISTRY.json.
Thirty conditional source route records: P42R_ROUTE_EVIDENCE_MATRIX.json.

1. CLI main(backfill) -> _backfill -> BackfillEngine -> workers -> Store
   -> save -> atomic JSON -> replace -> directory sync. No WriterLease.
   pyproject smh entry17, main75/76, construction158, engine.run168.
   Import and local constructor bindings are source-backed, not variable names.
2. Service _serve103 -> runtime -> acquire97 -> background/controller loops.
   Runtime separately constructs its lease59 and default engine45. Preparation,
   background and HTTP startup109–111 occur before the cleanup try113.
   Store.save never consults that lease; multiple Store instances exist at
   controller157, API58 and stats38. No CAS/owner authentication at Store.
3. Store.load can create the checkpoint directory and merge defaults/unknown
   schema. A malformed old state can reach a fresh initialization write.
4. Replace/fsync uncertainty can reach mark_error and a second save. Neither
   an operation ID nor a persistent retry admission exists.
5. API factory assigns Handler.api_service=api; runtime constructs SharedHistoryAPI.
   Factory input from arbitrary external callers is not authenticated. GET
   metadata may write symbol metadata and load may mkdir; stats background
   reads list_all and writes snapshots. Cached health is a distinct no-I/O path.

Default engine constructor binding is P68, C86: checkpoints or CheckpointStore.
A truthy injected object can be arbitrary; annotation is not runtime enforcement.
Known runtime/CLI defaults are conditional source proof, not proof of all callers.
Same-UID noncooperative processes can ignore the advisory lease. Isolated
fork/replacement tests demonstrate capability, not an observed production event.

Legacy BackgroundBackfill is not the running service class. It is a public
constructor/start capability with no discovered internal construction edge.
cleanup_stale_temp_files is a public temp-deletion capability with no discovered
internal caller, not an inferred scheduled cleanup. Retention constructs a Store
attribute but has no checkpoint method calls in its pinned module.

capture_service_state hashes checkpoint bytes, reads lock text and writes a
report; it is not safe metadata-only inventory and was not executed.
reset_state_i_gates replaces landing_state metadata, NOT checkpoint JSON.
Other tracked legacy artifacts are classified in immutable P42_ARTIFACT_AUDIT_NOTES;
external ML/Turbo dependencies are not followed or authenticated in this phase.

Installed paths, environment values, third-party dispatch, public injections and
historical restored writers remain external/unavailable boundaries. No source
path proof admits PAPER, T1, migration, production maintenance or a real fix.
