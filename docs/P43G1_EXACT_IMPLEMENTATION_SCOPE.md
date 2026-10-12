# Exact future scope request — NOT an implementation order

Target b1a3f97b213d062ed70375ac7aedbd0d67745a0b; engineering basef681faad.
The seven G0 paths stay PROPOSED ONLY. Scope insufficient: NO. Request two extra files:

1. src/shared_market_history/observability/stats.py:
   StatsService._compute_checkpoint_summary, _coverage_by_timeframe, refresh_snapshot,
   _refresher_loop, _snapshot_checkpoint_summary, _checkpoint_summary, cached, health,
   stats. Checkpoint errors must invalidate checkpoint/health success caches immediately
   in background and expose explicit DEGRADED without I/O/lock in GET. Do not restamp
   old facts or alter600s legacy freshness, market/resource thresholds or heavy cadence.
   Failing safety reproduction: test_stats_strict_error_and_actual_cached_ok_gap
   observes actual health OK after summary error. Future fixed test must assert DEGRADED.
2. src/shared_market_history/maintenance.py:
   LandingController._checkpoint_index, _resolution, _max_1m_freshness_seconds, _run_loop,
   _run_background_loop plus narrowly bounded callsites to root quarantine before tasks.
   Preserve actual algorithms/scheduling/resource300s policy. Invalidate resolution cache
   after strict read failure; latch safety error, stop both retrying loops; never treat
   malformed as missing/terminal/cleanup-safe. Existing loop source catch+continue evidence
   complements test_maintenance_strict_failure_prevents_index_result (leaf-only).
   Full-loop safe-stop test is still an actual implementation prerequisite, not claimed.

API/service.py:_metadata_coverage/get_metadata and api/server.py:Handler.do_GET are
READ-ONLY compatibility checks, not required patch paths with proposed generic RuntimeError
subtype: actual extracted do_GET returns500, not200/normal empty. ValueError subtype would
return400 and must not be chosen. No health/metadata API schema redesign admitted.

Within seven paths, G0 function scope also needs precise amendment:
CheckpointStore.pending_count preserves list failure; candidate observe_current_thread/_observe
diagnostics cannot swallow authoritative safety errors (their callbacks are otherwise telemetry).
BackfillEngine._flush_candle_buffer, _persist_forward_progress, _flush_funding_buffer,
_write_funding_rows, _flush_oi_buffer, _write_oi_rows are additional evidenced Store callsites.
No data-domain/algorithm change. Their exact SHAs/lines are in direct-edge matrix, both profiles.
Background.state indirectly uses pending_count; CLI/runtime entries delegate to actual engine.
Capture raw-byte/report capability remains outside safe inventory and must not be run.
Retention constructs Store but has no selected Checkpoint method call; not a new writer claim.

No source change from this request. No automatic expansion after G1; stop preparation.
C4 restart inhibit/history schema and C5 persist contract remain explicit blockers.
Human must approve exact baseline, filenames/functions and which persistence/admission contract
before actual implementation. Production/T1/boot/provider/qualification/soak need separate Gates.

Test coverage map (all fixture/source only): valid shapes2; API strict boundary4;
Stats cached error2; Maintenance index2; strict6-outcome classifier4;
CLI/external owner defect2; real fixture competition1; unknown/type preservation1;
postreplace stop1; crossrestart admission1; insufficient/unknown scope1; generic helper2;
G0 immutable failure/route XML2. Old failures remain via frozen G0 evidence.
No global Parquet behavior proof or actual power-loss test. Six ordinary old FAIL not repaired.

Operational note: a mis-scoped filename-only AGENTS discovery across the home tree was
interrupted; no contents, database, checkpoint or secrets read by that search. It is not
callgraph evidence or a claimed authorized client audit. Subsequent inspection was restricted
to parent instruction paths and selected immutable SH Git objects.
