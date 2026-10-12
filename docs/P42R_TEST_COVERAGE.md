# P4.2-R validation scope

Tests never run the real producer, scheduler, backfill service or capture script.
Actual module tests reuse the existing guarded temporary-filesystem fixtures;
this is isolated source behavior, not factual production recovery.

| Required check | Test evidence |
|---|---|
| Direct calls, import alias, construction | test_direct_calls_import_alias_and_constructor |
| Constructor/default versus injection | test_constructor_injection_preserves_condition_not_safety |
| Wrapper/callback | test_timing_wrapper_supplied_callback_path |
| Unknown config/injection/callback | test_injection_and_callback_unknown_cannot_make_full_path |
| Unknown receiver not safe | test_receiver_reassignment_is_unresolved_not_fake_safe |
| Forward/reverse graph consistency | test_thirty_route_binding_and_bidirectional_consistency |
| CLI writes without lease | test_existing_lease_is_not_store_authorization and actual CLI fixture |
| Lease exists but Store bypasses | actual test_different_process_store_bypasses_active_lease |
| Invalid/unreadable load fallback | actual invalid_document/schema_types/unreadable_document fixtures |
| Postreplace uncertainty | actual post_rename_fsync_failure_has_committed_bytes fixture |
| mark_error retry resaves | actual retry_mark_error_is_not_idempotent fixture |
| Version separation | test_different_versions_keep_file_line_and_identity_separate |
| Incomplete/made-up route fails | test_corrupt_route_cannot_be_accepted |
| Unknown historical restored source | test_no_historical_origin_or_production_credit |
| Frozen source hash/census | test_bad_frozen_input_fails_closed, exact Git scope verification |

Six original safety XFAILs remain strict and unmet. A reproduction test PASS
is proof of a defect's isolated reachability, not a fix PASS.
Factory arguments / receiver bindings are conditional source proof only; public
injection, inherited/dynamic overrides and installed paths are not authenticated.

No power-loss simulation, real retry after a production crash, T1 capture,
production volume/fsync durability, DB/API integration, qualification or soak
was performed. P42R_TEST_RESULTS.xml is the scoped JUnit log; raw stdout is
retained under the run directory, separately hashed.
