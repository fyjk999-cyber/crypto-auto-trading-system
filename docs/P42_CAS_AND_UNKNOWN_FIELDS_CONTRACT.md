# Proposed full-object CAS contract

Status: REVIEW_PENDING. Applies to both pinned P4.1 versions; no persistent format change.

CAS token is the exact raw bytes read (or an explicit ABSENT token), not default revision/updated_at. Under the shared ownership/serialization boundary reread the complete file and compare raw bytes before publishing. A digest may index evidence, never replace unavailable original bytes. Reject any byte drift, including unknown keys, ordering, historical control, nested type, bool/int, newly completed state and origin. Strict JSON comparison is additional validation, not permission to accept raw drift.

Missing initialization requires an explicitly admitted CREATE operation and an unchanged absent token. Corrupt/unreadable/unsupported data is never a valid CAS base. Duplicate keys, non-finite numbers and invalid root types cannot be normalized into valid input. Preserve original rejected bytes outside the mutation flow using a later approved custody contract; do not rewrite them.

Updates use a declared operation delta. All valid unknown fields and unmodified historical fields must survive exactly as values/types, including nested structures. Deletion of any field needs a named approved business transition; existing forward completion removes its three forward-control keys intentionally, but a blanket filter is prohibited. No metadata exclusions. Completed plus new IN_PROGRESS can be legal; do not prohibit it by simplistic status normalization.

The comparison-to-replace window is protected by the same admitted coordinator and OS ownership lock. Against a writer that ignores advisory locks this is NOT atomic CAS. A postread detects some interference but cannot undo a lost concurrent update; it must enter COMMIT_OUTCOME_UNKNOWN, not claim prevention. Enforceable external writer exclusion is a separate gate.

No revision or operation ID is inserted into existing JSON. If cross-restart operation identity becomes necessary, propose an authenticated durable operation record/checkpoint format contract with compatibility, old-reader/writer behavior, rollback and migration. Until approved: RETRY_IDEMPOTENCY = BLOCKED_PENDING_FORMAT_CONTRACT. A rollback old writer that ignores new controls is not admitted concurrently.

Required tests: stale full bytes, unknown mutation/deletion, nested changes, bool/int, completed drift, ABSENT racing create, duplicate JSON, same-process serialization, separate fixture process contention, uncooperative writer classified unknown rather than safe.
