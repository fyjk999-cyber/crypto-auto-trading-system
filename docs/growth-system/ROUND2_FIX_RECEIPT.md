# Round-2 correctness fix receipt

```text
OLD_REVIEW_TARGET = 99c744cbb169ebaf01238d23f26d1ff9a35df2a5
OLD_REVIEW_VERDICT = CHANGES_REQUIRED
THREAD = 01a08fcf-d919-7983-b7aa-00d58cab0c30
INTEGRATION_BASE = b3873d015b40916066dc19243e7d005be5ae3f5b
REPAIR_BRANCH = codex/core-growth-v2-review2-fixes
REPAIR_WORKTREE = /Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-growth-r2-fix
REPAIR_IMPLEMENTATION_SHA = a7ddf5ae0c91a42c7edfcf33cc1afd58abfb0386
PR = https://github.com/fyjk999-cyber/crypto-auto-trading-system/pull/4 (draft)
FINAL_BRANCH_SHA = docs-only receipt commit after the implementation SHA
REMOTE_BRANCH = codex/core-growth-v2-review2-fixes
```

This receipt records remediation of the 13 findings from the independent
Round-2 review.  The old verdict was bound to `99c744c`; it does not approve
this integration SHA.  A fresh independent review is required after the new
implementation SHA is frozen.

## Finding matrix

| ID | Reviewer finding | Current reproduction | Code fix | Regression test | Status |
| --- | --- | --- | --- | --- | --- |
| R01 | Stale claim could still publish retrievable knowledge | knowledge committed after fence expiry | staged CANDIDATE writing + single fenced activation transaction (`growth_knowledge.py::publish_attempts/_activate_staged`) | `test_round2_publication_semantics.py::test_t01_stale_claim_cannot_publish_reviewable_knowledge` | PASS |
| R02 | Incomplete revision could silently change `input_hash` | rev1 A stats SUCCEEDED / review FAILED, retry B reused spec | any `input_hash` change creates `revision+1`; resume asserts exact identity (`growth_pipeline.py::claim`) | `test_round2_input_recovery.py::test_changed_incomplete_input_opens_new_clean_revision` | PASS |
| R03 | Recovery loaded attempts from other account/mode/input/job | date/profile-only reload | exact `account_id`/`mode`/`input_hash`/`job_key`/`job_revision` filter; attempts bound to job (`growth_review.py`, migration 0043) | `test_round2_input_recovery.py::test_recovery_filters_wrong_account_mode_and_input_hash`, `test_recovery_prefers_exact_job_revision` | PASS |
| R04 | `COMPLETE` + zero publish input counted as success | publish retry marked SKIPPED_INCOMPLETE/succeeded | `BLOCKED_NO_PUBLISH_INPUT` → `publish_status=FAILED`, `succeeded=False`, retryable (`growth_pipeline.py`) | `test_round2_input_recovery.py::test_complete_input_with_zero_publish_input_is_blocked` | PASS |
| R05 | Provider exception left no durable attempt | `TimeoutError` before persist | provider call wrapped; one FAILED/UNKNOWN attempt, no exception text persisted (`growth_review.py`) | `test_round2_input_recovery.py::test_provider_exception_leaves_one_failed_unknown_attempt` | PASS |
| R06 | Latest version selected before status filter | `v2 REVOKED` still returned `v1 VALIDATED` | latest visible version chosen first, then status filter; `as_of` propagated (`KnowledgeStore`, `GrowthContextLoader`) | `test_round2_publication_semantics.py::test_t08_*`, `test_t09_*` | PASS |
| R07 | Revoke/expire backdated `known_at` | historical as_of saw revocation early | revoke `known_at=at`; expire `known_at=valid_until`; old versions immutable | `test_round2_publication_semantics.py::test_t08_*`, `test_t10_t11_*` | PASS |
| R08 | Different propositions co-validated by scope | 3 unrelated single cases → one validated pattern | deterministic proposition identity in lesson scope; pattern id/aggregation includes proposition key (`growth_knowledge.py`) | `test_round2_publication_semantics.py::test_t12_different_propositions_do_not_validate_each_other` | PASS |
| R09 | Importer trusted `target_path` string | `/tmp` label with production bind passed | real engine URL resolved, SQLite file/inode/device compared, temp-root guard fails closed (`growth_import.py`) | `test_round2_import_safety.py::test_t13_target_path_must_match_real_connection` | PASS |
| R10 | Rollback was an unauthenticated delete | rollback without authorization deleted rows | rollback requires `test_only`, actual target identity, existing provable batch identity, optional expected hashes | `test_round2_import_safety.py::test_t14_*`, `test_t15_*` | PASS |
| R11 | Resume could cross source/plan identity | source A batch resumed with source B plan | resume loads batch and requires exact `source_db_sha256`/`plan_hash`/status; `_set_batch_status` never manufactures UNKNOWN identity | `test_round2_import_safety.py::test_t16_t17_resume_identity_mismatch_rejected` | PASS |
| R12 | Symbol-only coin profile crossed account/mode | profile evidence returned for any account | v1 `GrowthContextLoader._coin_profile_evidence` fails closed (`scope_unavailable`, `NO_MATCHES`) because `AICoinProfileORM` lacks provenance; canonical runtime uses V2 cards | `test_round2_retrieval_bounds.py::test_t18_ambiguous_coin_profile_never_crosses_account_scope` | PASS |
| R13 | Token budget not enforced on serialized evidence | per-category estimates could exceed budget | `ToolBudget.limit` clamped to 5; final serialized evidence trimmed whole-item until <= budget (`growth_retrieval.py`) | `test_round2_retrieval_bounds.py::test_t19_final_serialized_growth_evidence_respects_hard_budget` | PASS |
| R14 | v1 `record_selection` manual helper ≠ official persistence | docs/tests claimed helper canonical | canonical path remains `experience_cards → ExperienceCardRetriever → CardDecisionTraceStore → trace-before-use → decision attach`; v1 loader marked support/legacy | `tests/growth_system_v2/test_integration_wiring.py::test_trace_persisted_before_card_evidence_exposed`, `test_trace_failure_hides_card_evidence_and_decision_continues`, `test_strategy_attaches_trace_to_decision_after_evidence` | PASS (v1 helper demoted in docs) |
| R15 | Evidence claims mixed runtime fact / static inference / snapshots / external observations | docs over-claimed scheduler state from static code | evidence taxonomy added; `33,081` remains external observation / NOT RECONCILED; runtime facts separated from static inference and historical snapshots | `ROOT_CAUSE.md` classification update; this receipt | PASS |

## Migration

```text
OLD_HEAD = 0042_growth_v2_cards
NEW_HEAD = 0043_growth_review_job_binding  (single head)
reason   = exact job/revision binding on durable review attempts (R03)
down_revision = 0042_growth_v2_cards
real PostgreSQL execution = NOT_VERIFIED (GROWTH_V2_POSTGRES_URL absent)
SQLite upgrade/repeat/downgrade/re-upgrade = PASS
```

## Evidence taxonomy (R15)

* **Runtime fact**: observed PID, actual DB opened by a process, API response,
  provider telemetry.
* **Static code inference**: “this path would construct the scheduler if
  `AUTO_START_RUNTIME=true`” — not evidence the process did so.
* **Historical snapshot**: `canonical-clean` had 13,271 `llm_decisions` at a
  stated snapshot time; a frozen observation, not a live count.
* **External observation**: the user-reported `33,081` provider requests is
  `EXTERNAL OBSERVATION / NOT RECONCILED`; it is never derived by multiplying
  `13,271 × 2`.
* No test or this Harness claims REAL_PROVIDER_SMOKE or a natural PAPER loop.

## Regression / gate results

```text
Phase A new regressions (R01-R15)  = 21 new test functions + existing suites updated
Phase B growth suite               = tests/growth_system + tests/growth_system_v2 + tests/governance_unit
                                     = 170 passed, 1 skipped
Phase C core constraints           = valuation scope + orphan recovery + opportunity +
                                     risk/risk-scale-down + global budget
                                     = 174 passed
Phase D migration                  = alembic 0042→0043 upgrade/repeat/downgrade/re-upgrade
                                     + PostgreSQL offline compile
                                     = 4 passed, 1 skipped (real PG NOT_VERIFIED)
Phase E full backend               = 1179 passed, 1 skipped, 2 warnings in 198.01s
Phase F ruff                       = All checks passed
Migration head                     = 0043_growth_review_job_binding (single head)
REAL_PROVIDER_SMOKE                = NOT_VERIFIED (no provider run in this task)
NATURAL_PAPER_GROWTH_LOOP          = PENDING
PRODUCTION_DB_WRITE                = NO
RUNTIME_AUTHORIZED                 = false
```

## Runtime loader decision (R14)

```text
CANONICAL RUNTIME:
  experience_cards
  → ExperienceCardRetriever
  → CardDecisionTraceStore (trace persisted before evidence is exposed)
  → decision_id attachment by LiveLLMDecisionStrategy

SUPPORT / LEGACY / RESEARCH ONLY:
  v1 GrowthContextLoader (memory_search / episode_search / coin_profile /
  factor_intelligence / research_retrieval) and its record_selection helper.

The v1 helper is not a canonical AI path and must not be cited as automatic
decision-trace persistence evidence; `LEGACY_RUNTIME_CARD_READS=0` and
`LEGACY_RUNTIME_CARD_WRITES=0` remain enforced by
tests/growth_system_v2/test_legacy_path_audit.py.
```


## Fresh-review counterexamples (interrupted dispatch)

The new independent review dispatch (`core-growth-v2-round2-hardening`, thread
`01a090ea-89c0-7633-b781-82a8afc48930`) hit the Codex account usage limit
before producing a formal verdict, but it produced reproducible
counterexamples.  All were fixed and re-tested:

1. The v2 card tool counted only a partial token estimate; the final
   serialized `ToolEvidence` could exceed the configured budget.
   Fix: enforce the budget on the full serialized evidence object, dropping
   whole cards then observability fields
   (`test_round2_card_budget_trace.py::test_card_evidence_respects_full_serialized_budget`).
2. Two accounts reading the same explicitly shared card reused one trace id.
   Fix: `account_id`/`mode` are part of the deterministic trace identity
   (`test_shared_card_trace_is_isolated_per_account`).
3. v1 `episode_search` could return foreign account/mode episodes.
   Fix: episode evidence is joined to `GrowthEpisodeBindingORM` for the exact
   account/mode.
4. The official v1 `ChiefContextLoader` coin-profile tool still leaked
   symbol-only profiles.  Fix: fail closed there as well
   (`test_t18b_official_v1_coin_profile_loader_fails_closed`).
5. Staged activation could promote an unrelated-proposition lesson, rewrite
   historical lesson rows, and collapsed Chinese statements to one identity.
   Fix: activation filters by `proposition_key`, appends a new lesson version,
   and uses Unicode-safe normalization (publication semantics additions).
6. Recovery could admit unbound obsolete attempts when a job identity was
   known.  Fix: strict `job_key`/`job_revision` matching, no unbound fallback
   (`test_recovery_ignores_unbound_rows_when_job_identity_is_known`).

Formal independent verdict for the final repair SHA remains pending a retry
after the usage limit resets.  This receipt does not claim approval.
