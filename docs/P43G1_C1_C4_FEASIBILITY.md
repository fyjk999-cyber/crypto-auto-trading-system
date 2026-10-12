# C1–C4 no-format feasibility — bounded preparation, not implementation

Engineering base f681faad91d357168725fe985ba2263051a0bc0c.
Target source b1a3f97b213d062ed70375ac7aedbd0d67745a0b; producer observed source
25505ff15dd6acd623140d70c0a8eb216c59ea48, NOT current runtime assertion.
Source citations are the exact-version P42R edge IDs/file hashes in the matrix.
The matrix enumerates every selected direct Store callsite, not every external caller.
Tests extract selected actual methods without class construction, run temp-only Store
behavior or synthetic protocols. Fixture success is not implementation correctness.

## C1 — possible without changing checkpoint bytes, not proven safe implementation

Authenticated lease lifetime, canonical root/inode, process generation and FD identity
can reside in memory. Same-root Store instances must share one coordinator and reject
releases, forked ownership and injected foreign authorities. CLI must acquire before
writable assembly; service/worker lifetime must finally-release. A failed/unacquired
lease must never authorize Store. Existing source does not enforce these properties.
Advisory locks require cooperating code; same UID can bypass them. No claim of OS
isolation, independent custody or permission enforcement. Runtime/CLI/default engines
and externally constructed background objects must all use/reject this admission.
Result: DESIGN_FEASIBLE_WITHOUT_CHECKPOINT_FORMAT; NOT_IMPLEMENTED_OR_VALIDATED.

## C2 — possible raw-byte CAS, conditional on complete root coordination

Load returns valid legacy dict and privately records exact raw bytes (absence has an
explicit sentinel, never an empty document). Compare and replace must occur under the
same authenticated root lock + same-process mutex, through every Store writer. Tokens
are bound to root/path/owner generation, invalidated after conflict/exception/release;
no blind rebase. Unknown keys and nested values remain in the complete object. JSON
identity must distinguish bool/int; duplicate/nonfinite/schema-invalid input rejects.
Missing initialization requires the admitted owner and protected absence CAS.
No persisted revision needed in this design. The existing FixtureCAS uses a SYNTHETIC
revision; its real lock-window test proves only that laboratory's exclusion, NOT a
new no-format implementation. Actual stale overwrite still reproduced by G0.
Result: DESIGN_FEASIBLE_WITHOUT_CHECKPOINT_FORMAT; EXACT_COMPETITION_IMPLEMENTATION_UNPROVEN.

## C3 — preserve valid shape; fail explicitly, no default recovery

VALID dict/list remain existing public return shapes, including unknown/restored fields,
completed+forward semantics and field clocks. Missing must raise distinct outcome for
ordinary reads; only authenticated initialization may construct defaults. CORRUPT,
UNREADABLE, SCHEMA_INVALID and VERSION_UNSUPPORTED propagate checkpoint-specific
exceptions, not request ValueError or normal empty lists. Reads do not create dirs.
Actual API coverage propagates a synthetic strict error, HTTP boundary returns500.
Stats summary propagates but cached health still OK; Maintenance index propagates but
outer loop logs/retries and cached resolution can bypass an observation. Additional
Stats and Maintenance adaptation is necessary. Full historical schema population is
NOT_CAPTURED; reference minimal fields/schema1 are fixture assumptions, not adopted
historical schema. Tightening field policy without population compatibility is BLOCKED.
Result: BLOCKED_FOR_ADMISSION_PENDING_READER_ADAPTATION_AND_HISTORICAL_SCHEMA.

## C4 — distinguish outcomes but restart-safe stop remains BLOCKED

Checkpoint-only publication can classify NOT_COMMITTED (known before replace),
COMMITTED_DURABLE (successful temp flush/fsync + replace + directory fsync), and
COMMIT_OUTCOME_UNKNOWN (replace uncertainty/postreplace sync failure). Do not change
global helpers used for Parquet. UNKNOWN forbids second save, mark_error, retry_count,
business replay or blind rollback. Proposed in-process root quarantine rejects every
new write across engines/Store/controller tasks, freezes admission, stops both loops
and exposes degraded cached health until separately authorized factual reconciliation.
The test demonstrates one synthetic attempt with committed bytes and no automatic
second publication. Actual engine still performs second publication (G0 retained).

An in-memory quarantine vanishes on restart; normal service restart can reacquire the
lease and replay without learning the uncertainty. No existing durable admission
inhibit/manual-reconciliation enforcement has been proved. A written plan to ask a
human is not an enforceable gate. Therefore C4 cannot safely be promoted alone as an
operational repair in this no-persistence scope. Need separately authorized persistent
inhibit/recovery contract OR independently proved externally enforced restart admission.
Neither is granted here. No sidecar written, no service disabled/restarted.
Result: BLOCKED_RESTART_UNKNOWN_OUTCOME_SAFETY_NOT_ESTABLISHED.

## Final classification

P43_G1_READ_COMPATIBILITY = BLOCKED (known compatibility limits, not population proof)
P43_C1_C4_SCOPE = BLOCKED
P43_ACTUAL_IMPLEMENTATION = NOT_STARTED
G0 six real failures and original six strict XFAIL remain. No waiver from fixture PASS.
Hashes/test source/reviewer conclusions are sealed in the final receipt after review.
