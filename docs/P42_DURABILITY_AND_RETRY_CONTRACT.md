# Proposed durability and retry contract

Status: REVIEW_PENDING. Actual fsync helper and mark_error remain unfixed. This contract does not claim power-loss durability.

NOT_COMMITTED: failure is proven before successful replace, while original raw state is unchanged. Includes fixture temp creation/file write/file fsync or pre-replace fault. Cleanup only own unique temp, never historical CP or arbitrary stale paths. A crash with no evidence of replace success cannot automatically be assigned this result on restart.

COMMITTED_AND_DURABLE: authenticated ownership held, complete expected payload file fsync, replace, directory fsync and postread succeeded; observed bytes match operation intent. This is an OS acknowledgment contract, subject to tested filesystem semantics. Logging/response failure AFTER recorded durability must not reclassify into not committed or cause second business submission.

COMMIT_OUTCOME_UNKNOWN: replace occurred but directory open/fsync/postread failed; replace result itself is ambiguous; process crashed without durable operation provenance; postread differs; ownership lost during commit. Preserve original failure/expected and prior bytes in approved durable operation evidence when available. Do not report old data retained, retry blindly, invoke mark_error, or automatically rollback new bytes. Read visibility alone does not prove durability.

Reconciliation must happen under reacquired authenticated ownership in a separately admitted recovery operation: match durable operation identity and exact before/after payload with observed state; if confirmed committed, finish acknowledgment without second mutation; if confirmed not committed, retry the SAME logical operation once through full CAS; otherwise remain blocked. No trusted durable operation identity exists in either pinned format. Cross-restart recovery/idempotency therefore remains BLOCKED_PENDING_FORMAT_CONTRACT. Memory IDs or payload equality alone cannot establish that a business operation occurred once.

Normal business failure, load failure, CAS conflict, ownership failure and storage commit uncertainty are separate classes. Existing engine broad except + mark_error must be split; mark_error is itself a protected operation with expected latest bytes and distinct admitted error event identity. It must not reload-and-overwrite newly completed state or repeat retry_count increment for the same event. No completion/cursor rollback, and no deletion of unknown origin fields. A mark_error storage failure preserves both primary and secondary errors and halts dependent writes.

Future migration proposal must define operation record atomicity/ordering relative to CP, startup reconciliation, legacy rollback, retention and crash points; no such production format is introduced here. Reference tests may verify rejection/blocked transitions but cannot mark cross-restart idempotency PASS without that contract.

Required faults: temp/file fsync/pre-replace, ambiguous replace, post-replace parent-open/fsync, post-durable response, mismatch postread, same-event repeated mark_error, concurrent completion, crash recovery without record, recovered outcome with valid record only under future approval.
