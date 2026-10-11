# Proposed writer ownership contract

Status: REVIEW_PENDING, not production admission. Sources: 25505ff15dd6acd623140d70c0a8eb216c59ea48 and b1a3f97b213d062ed70375ac7aedbd0d67745a0b. No actual modules changed.

Creation and ordinary updates belong only to the admitted canonical service writer. An authorized CLI must use the SAME canonical root/lock identity and reject an occupied owner before constructor side effects. Deletion, migration and manual repair remain separate maintenance authorizations, not powers implied by acquiring the service lease.

Proposed commit authority is an exclusive OS lock on an authenticated stable inode bound to admitted root, current PID/start identity and a live retained FD. Caller-supplied owner strings/booleans, successful past acquisition, lock-file contents and process counts are not capabilities. Verify device/inode/root and non-inheritance on fork; reject lock-path replacement, symlinks and different mount. No filesystem lock behavior is assumed portable across the canonical volume: platform tests are a later gate.

Lease lifetime encloses directory initialization, engine preparation, all worker callbacks and complete final commit/fsync/reconciliation. Release on every preparation failure and normal shutdown; never release while a worker can commit. Crash closes OS FDs, but stale on-disk owner metadata is not proof of current ownership. Lost/closed FD, forked PID, altered root or unverified external caller must fail before write, including mark_error.

Within one process use one root-scoped serialization coordinator shared by all Store instances; separate descriptors are not proof that a cooperative same-PID store is serialized. Maintain commit serialization from ownership validation through comparison, replace, durability and postread. CLI/service/direct engine/maintenance/background callbacks must all enter this same boundary. Constructors must not mutate roots before admission. API/stats read consumers receive no writer capability.

OS advisory locking alone cannot prevent an uncooperative same-UID script from replacing files. reset_state_i_gates demonstrates an auxiliary metadata writer; protected CP paths also remain technically reachable by arbitrary external callers. Enforcing an admitted-writer-only permission boundary requires separate identity/ACL/runtime authorization. INDEPENDENT_EXECUTION_IDENTITY remains NOT_ESTABLISHED; do not claim this document solves it. Gate new deployment until every writer is admitted or excluded by an enforceable boundary. No role/ACL change here.

Future tests: occupied lock, failed acquire, prepare error, closed FD, forked identity, replaced lock inode/root, callback after release, multiple stores/threads/processes. Isolated OS lock tests prove only their fixture filesystem; production guarantees remain blocked.
