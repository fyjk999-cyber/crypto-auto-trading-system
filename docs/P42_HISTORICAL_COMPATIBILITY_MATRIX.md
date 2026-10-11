# Compatibility boundaries for both pinned versions

| Field/path | Current factual source behavior | Proposed compatibility constraint |
|---|---|---|
| restored_completed_at / restored_reason | Valid dict keys preserved; actual writer/migration unavailable | Preserve value/type/raw CAS inclusion; history UNKNOWN; no destructive migration or invented origin |
| completed / status | completed may coexist with IN_PROGRESS for forward work; consumers answer different questions | Preserve legitimate transition, never normalize to infer current market readiness |
| pause_reason | Store pause writer; survives success/start; no historical chronology proven | Preserve unless independently authorized transition; existence/absence not history proof |
| next_cursor / forward_cursor | Drive engine work/cursor recovery | Compare full raw object, no stale rollback; transitions need callsite-specific approval |
| source / origin / unknown keys | Arbitrary dict persists; external repair possible | No whitelist filtering/exclusion; unknown semantics block incompatible update |
| last_success_at | Latest successful work timestamp observed by stats | Not market newest or historical authority |
| updated_at | Re-stamped by save | Publication only; CAS cannot compare this field alone |
| corrupt/unreadable load | Default/fresh state and possible mkdir | Deliberate fail-closed change; adapt callers together; no historical equivalence claim |
| CLI | Can reach store without service lease | Deliberate admission change; reject occupied/unverified writers; no bypass compatibility |
| fsync directory-open failure | Silent success | Deliberate uncertain outcome; full caller/retry adaptation required |
| retry_count | Repeated mark_error increments | New idempotency blocked until durable identity/format contract, no invented history |

Candidate adds engine domain validation/freshness-tail behavior; CheckpointStore/atomic unchanged. Existing forward-anchor introduction source remains cd0ab513582731a88930de01cf261fe1f099b7b5. Both versions require separate regression binding, even where exact source is identical. No T0 proof recovered; raw historical bytes unavailable. No current production key population read.
