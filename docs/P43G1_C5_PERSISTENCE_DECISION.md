# C5 persistence decision — separate authorization required

C5_CROSS_RESTART_IDEMPOTENCY = BLOCKED_PENDING_PERSISTENT_CONTRACT
P43_C5_FORMAT_CONTRACT = SEPARATE_AUTHORIZATION_REQUIRED
No operation ID, generation, journal, sidecar or checkpoint extension implemented.
Current saved dictionaries have no authenticated business-operation identity. Equal
desired bytes do not prove same operation; two distinct valid attempts may look equal.
Old FixtureCAS revision and already-committed branch are synthetic and NOT C5 proof.

| Future option (not selected) | Persistence/old-reader compatibility | Mixed-version/crash rules | Migration/rollback and human scope |
|---|---|---|---|
| checkpoint operation_id/generation | same checkpoint namespace; old readers may preserve unknown fields but old writers can lose/ignore identity | fence old writers; atomically bind operation and business outcome; repeat ID must match payload or reject; unknown commit reconcile | approved version/schema/history mapping; old writer rollback cannot silently discard identities; explicit schema+writers authorization |
| durable journal | separate explicitly approved root/format, not existing receipts; old readers do not consult | ordering of intent/business/checkpoint/commit must survive crash; exclusive authenticated owner; bounded retention | approved durable transactional ordering, migration and non-destructive rollback; no generic evidence log substitute |
| inhibit/reconciliation sidecar | separate approved protected file, legacy readers ignore | every process/boot must honor unresolved marker; ID alone not exactly-once proof; root quarantine until authorized resolution | mandatory reader/boot admission integration, crash behavior and rollback; explicit sidecar/authentication permission |

None is automatically preferable or admitted. Existing same-UID ACL/lease is not
independent provenance. Any externally enforced restart admission alternative needs
exact verified owner/configuration and durability evidence before claiming no-format
safety. Current known source neither provides it nor an atomic business transaction.
No production source/data inspected for content, and no historical format invented.
Independent reviewers assess preparation accuracy only; final hashes in receipt.
