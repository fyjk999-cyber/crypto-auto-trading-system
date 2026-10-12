# G0 failed-implementation baseline, not green admission

Old P25505ff15dd6acd623140d70c0a8eb216c59ea48 and
Cb1a3f97b213d062ed70375ac7aedbd0d67745a0b:

| Desired contract | Actual RED tests | Actual current result |
|---|---|---|
| Corrupt load rejected | test_corrupt_load_contract_is_not_met x2 | DID NOT RAISE ValueError |
| Stale full-object update rejected | test_full_object_cas_contract_is_not_met x2 | DID NOT RAISE RuntimeError |
| Directory-open failure explicit | test_directory_open_durability_contract_is_not_met x2 | DID NOT RAISE OSError |

P43G0_FAIL_FIRST_RESULTS.xml records6failures,0errors,0skips; pytest exit1.
New wrappers call the original marked test bodies as normal functions, without
propagating xfail marks. Original test files and six strict XFAILs are untouched.
These are intentionally failing future requirements, not unexpected CI green.
They are not silently excluded from a claimed full-suite PASS.

Separate route reproduction:16PASS confirms old unsafe behavior. Actual _backfill
body uses stub engine/discovery but actual Store leaf; actual run_task/_timed_ckpt/
_stamp_timing are compiled from fixed Git, with a fixture worker and real Store.
First worker publish raises after replace; actual handler mark_error publishes
again. Old state becomes completed=True/status=ERROR/retry_count1, two publish
attempts. Full production service/worker/network lifecycle is not exercised.
Active service-style lease test uses actual lease leaf, not a real service boot.

All behavior files are owned temporary fixtures behind the original I/O guard.
Git engine bytes are fetched by a session-scoped source fixture BEFORE that guard.
An initial fetch attempted under the guard was blocked (2failed/14passed); log
and first XML are preserved. Moving source fetch before guard did not relax it.
Final route log/XML R2 records16PASS. No test helper opened production data.

Historical restored fields use explicitly synthetic provenance and stay equal
after normal updates. A write-window test loses concurrent nested unknown data;
neither fixture is historical origin or T0-equivalence evidence.

Only after an explicitly authorized implementation should these RED requirements
become green against a new candidate SHA. Existing pinned versions remain RED.
Do not invoke whole-suite pytest and disguise these6 failures as a passing suite:
run RED-baseline invocation separately, and name every selected regression file.
