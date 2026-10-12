# P4.2-R error/retry source matrix

Exact P = 25505ff15dd6acd623140d70c0a8eb216c59ea48.
Exact C = b1a3f97b213d062ed70375ac7aedbd0d67745a0b.
All function spans and file hashes are in the sink registry / edge evidence.
This is path evidence, not an implementation fix or production observation.

| Input/outcome | Actual reader/helper | Business continuation | Safety |
|---|---|---|---|
| Missing JSON | atomic.read_json returns default | Store.load returns NOT_STARTED; worker may mark_started/save | FAIL |
| Corrupt JSON | ValueError swallowed by read_json | Same fresh-default continuation | FAIL |
| Unreadable | OSError swallowed (is_file errors can also escape) | Default or outer engine exception -> mark_error -> reload/save | FAIL |
| Schema-invalid dict | load merges dictionary without schema validation | bool/completed and cursor coercions influence worker selection | FAIL |
| Unsupported version | no version admission in actual load | dict merged unchanged, not typed UNSUPPORTED | FAIL |
| Temp/file fsync failure | atomic_write_bytes may raise before replace | engine broad handler may write ERROR, not a durable operation ID | FAIL |
| Replace succeeded + directory open fails | fsync_dir returns silently | save may report success without demonstrated directory durability | FAIL |
| Replace succeeded + directory fsync fails | fsync_dir propagates | run_task catches -> mark_error -> new save; COMMIT_OUTCOME_UNKNOWN | FAIL |
| mark_error's second save fails | outside original try handler | exception may reach Future.result and scheduler cycle catch | FAIL |
| Next scheduler/deferred cycle | same task control state reread | no persistent operation identity across restart | BLOCKED |

Unchanged actual Store: load50, path_for48, mkdir41, read_json53;
mark_started86/89; mark_success101/117; mark_error120/123/124.
Unchanged atomic: file fsync41 -> replace42 -> fsync_dir43; fsync_dir
open25–27 can return; fsync29 propagates. No compare-and-swap is present.

Engine P run_task load1061 -> backward1065 / forward1063;
catch mark_error1073. Engine C load1086 -> forward1088 /
freshness-tail1090 / backward1092; catch mark_error1100.
Backward P346/347, C364/365 loads then mark_started.
Timing wrapper P219/223 and C237/241 invokes the supplied bound method.
Do not interchange these source-version line numbers.

Trace callbacks: P1101/C1170 register _trace_checkpoint, actual Store._observe35
invokes callback and catches diagnostic exceptions36–37. Trace update passed
by maintenance1193 is conditional and _update_task_trace197–207 changes
in-memory snapshots. Public progress/trace arguments remain external boundaries.

completed=True with status=ERROR/IN_PROGRESS is not automatically impossible:
mark_error changes status/count, not completed. Maintenance/API/stats read
different combinations; clocks and operational freshness remain independent.
restored_* original writers = NOT_RECOVERABLE_FROM_AVAILABLE_SOURCE.

Fixtures prove isolated behavior only. Six original safety XFAILs stay unmet;
no corrupted checkpoint was reinitialized in production.
