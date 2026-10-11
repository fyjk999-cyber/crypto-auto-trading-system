# Coverage is not implementation acceptance

Both pinned actual-source variants are tested by P41 and P42 modules. No XFAIL is removed. Reproductions passing means existing defects are observed. Reference loader is a pure byte, minimal synthetic profile: not an approved production schema, actual caller adaptation, migration, durable operation-ID implementation, or power-loss proof.

| Requested case | Evidence / remaining limit |
|---|---|
| Service lease owner | P41 actual WriterLease tests; full runtime constructor/worker lifecycle NOT executed |
| CLI without lease | P41 executes actual CLI function body with fixture dependencies and actual store leaf |
| Multiple Store instances | P41 stale overwrite reproduction |
| Different process competition | P42 isolated POSIX child writes shared fixture under active parent lease; not a production process test |
| CAS window | P42 actual atomic replace boundary injects competing whole-state write; no CAS exists |
| Unknown fields | P41 preserves successful load/mark_success; P42 window loses newly added field |
| bool/int | P41 unvalidated types; P42 string false coerced true; reference rejects numeric/bool substitution |
| Nested changes | P42 nested unknown field lost; P4 synthetic raw-CAS fixture rejects protected nested changes |
| Missing/corrupt | P41 both fresh defaults; reference six-category classification |
| No read mkdir | P41 actual defect and retained strict XFAIL; reference has no filesystem access |
| Before replace failure | P41 file fsync / rename injection, unchanged old bytes |
| After replace directory fsync | P41 published bytes despite error, silent directory-open failure |
| Unknown result recovery | P41 ERROR after new completed bytes; P42 post-publish overwrite undetected; reference retry production implementation BLOCKED |
| Retry idempotence | P41 repeated mark_error increments; P4 synthetic retry only; durable production format NOT approved |
| mark_error new completion | P41 preserves completed but changes status ERROR; no caller-level concurrency recovery certification |
| restored fields | P41 success preservation and reference raw bytes; source origin NOT_RECOVERED |
| Old-version compatibility | Two exact versions, source hashes; historical population not captured or certified |
| Unknown dynamic writers | Contracts deny admission; actual Store has no enforcement, full receiver proof and authenticated identities pending |

All test data is synthetic under owned temporary directories or byte objects. Source is loaded from fixed Git objects; installed source, protected DBs/checkpoints and service control are not used. Required implementation-level tests remain future blockers; they are not silently satisfied by reference success.
