# Round-3 correctness fix receipt

Base implementation SHA: `a7ddf5ae0c91a42c7edfcf33cc1afd58abfb0386`
Base verdict: `CHANGES_REQUIRED` (13 findings: 6 P1 + 7 P2)
Repair branch: `codex/core-growth-v2-review3-fixes`
Migration head: `0044_growth_review_attempt_bindings` (single head)

## Finding matrix

| ID | Independent finding | Repair summary | Tests / evidence | Status |
| --- | --- | --- | --- | --- |
| F01 | Failed staging remained authoritative | Staged rows now use `STAGED` status / `staged=true` + stage token, are excluded from every authoritative lookup, aggregation, retrieval, compression and revocation path, and are adopted only in one fenced transaction with new authoritative versions. | `test_round3_invariants.py::test_f01_stale_staging_never_reaches_authoritative_aggregation`; reviewer `publication-probe.json` (`stale_contamination`, `stale_hides_validated`) | PASS |
| F05 | `RSI > 70` collided with `RSI < 70` | Proposition normalization preserves semantic operators/punctuation and Unicode while normalizing whitespace. | operator collision regression in `test_round3_invariants.py`; reviewer `operator_collision` no longer forms one VALIDATED pattern | PASS |
| F06 | Compression borrowed an unrelated candidate | `_statements_for_pattern` now binds exact proposition, account/mode/scope, episode membership, latest as-of version and validated/contested eligibility. | `test_f06_f10_compression_and_revoke_use_exact_proposition`; reviewer `unrelated_revoke_compress` | PASS |
| F10 | Revocation crossed proposition boundaries | Pattern revocation cascades only to lessons matching the revoked pattern's exact proposition/source membership. | same test; reviewer `before_B` / `after_B` | PASS |
| F11 | Future revocation hid historical compression | `list_published_compressions` filters `known_at <= as_of` before choosing the latest version, then applies status/validity. | `test_f11_compression_history_survives_later_revocation`; reviewer `compression_history` | PASS |
| F02 | Legacy canonical `memory_search` leaked foreign cards | Legacy compressed-card reads require account/mode provenance, latest as-of version and safe status; explicit foreign/LIVE/RETIRED cards are excluded, and legacy episode/review reads are binding-scoped once any binding exists. | `test_f02_legacy_card_tool_fails_closed_for_foreign_scope`; reviewer `CANONICAL_MEMORY_FOREIGN_LIVE_RETIRED` / `TRACE_COUNT 0` | PASS |
| F04 | Budget loop could hang or exceed hard limit | V2 card and v1 evidence go through explicit budget finalizers; budgets below the minimum representable value raise `TOKEN_BUDGET_CONFIGURATION_INVALID`, every shrink step is monotonic, success/empty/failure paths share the same finalizer. | `test_f04_impossible_budget_is_explicit_configuration_failure`; reviewer hang probe returns, failure path budget is enforced | PASS |
| F12 | Trace disagreed with released evidence | Budget pruning finalizes `selected`/metrics/excluded refs first, then persists the trace for that exact result and releases the identical refs. | reviewer `BUDGET_DROPPED_RETURNED_REFS` = trace selected refs/count; existing card budget tests | PASS |
| F13 | Different retrieval signatures reused one trace | Trace identity now includes account, mode, symbol, as-of, trigger/context signatures, selected card ids+versions, policy version/fingerprint; incompatible override IDs are never blindly reused. | reviewer `probe_trace_identity.py` (`SAME_TRACE_ID=False`, 2 traces); `test_round2_card_budget_trace.py` | PASS |
| F03 | Mapper-specific binds bypassed target check | Import/rollback resolve every effective model bind and verify the SQLite database actually opened by `PRAGMA database_list` plus device/inode; alternate binds fail closed before mutation. | `test_round2_import_safety.py`; reviewer `test_actual_target_must_follow_session_table_binds` now raises `ImportSafetyError` with zero writes | PASS |
| F09 | Ordinary `batch_id` reuse bypassed resume identity | Any already-existing resolved batch ID is checked for exact source hash, plan hash and resumable/completed state before mutation, regardless of which parameter selected it. | `test_t16_t17_resume_identity_mismatch_rejected`; reviewer `test_batch_id_reuse_cannot_bypass_resume_identity` now raises before mutation | PASS |
| F07 | Cache reuse overwrote historical job membership | New `growth_review_attempt_bindings` association (migration 0044) records immutable many-to-many job/revision membership; recovery resolves both source revisions without rewriting the attempt's original binding. | reviewer `test_cache_rebinding_must_not_destroy_prior_job_recovery`; `test_round2_input_recovery.py` | PASS |
| F08 | `NO_PUBLISH_INPUT` was permanently stuck | Empty required review input rolls the review stage back to `FAILED`/retryable, so the next same-input run calls the loader again and can proceed through review and publication. | reviewer `test_no_publish_input_retries_reload_inputs`; updated claim/publish recovery tests | PASS |

## Preserved passes

* R02 exact input revision binding: unchanged and still covered by `test_round2_input_recovery.py`.
* R05 provider exception durable persistence: unchanged and still covered by `test_round2_input_recovery.py`.
* `LEGACY_RUNTIME_CARD_READS=0`, `LEGACY_RUNTIME_CARD_WRITES=0`, account/mode isolation share_scope, trace-before-use and Core constraints remain in place.

## Gate results on the frozen SHA

```text
Round-3 adversarial (Wave 1)        = publication probes all green
Growth bundle                        = 170 passed, 1 skipped
Core constraints                     = 174 passed
Migration                            = 5 passed, 1 skipped (real PG NOT_VERIFIED)
Full backend                         = 1185 passed, 1 skipped, 2 warnings in 186.59s
Ruff                                 = All checks passed
Alembic head                         = 0044_growth_review_attempt_bindings (single head)
```

## Safety boundary

```text
RUNTIME_AUTHORIZED=false
DEPLOYED=false
PRODUCTION_DB_WRITE=NO
EXECUTION_LEASE_TOUCHED=NO
REAL_PROVIDER_SMOKE=NOT_VERIFIED
NATURAL_PAPER_GROWTH_LOOP=PENDING
MIGRATION_AUTHORIZATION=NOT_GRANTED
REAL_POSTGRES_EXECUTION=NOT_VERIFIED
REAL_ORDER=NO
LIVE_TRADING=NO
FAKE_EPISODE=NO
FORCED_PAPER_TRADE=NO
```

Round-3 findings are implemented and locally verified; `GROWTH_FINAL_ACCEPTANCE` remains pending a fresh exact-SHA independent review.
