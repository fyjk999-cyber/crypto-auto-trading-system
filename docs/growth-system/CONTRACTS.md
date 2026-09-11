# Growth-system contracts

This file is the machine-verifiable contract index. Each contract names the
implementation, the tests that bind it and what it explicitly does **not**
promise.

## C1 — Financial truth (G01)

Implementation: `src/crypto_trader/governance/daily_review.py`,
`src/crypto_trader/governance/scheduler.py`,
`src/crypto_trader/governance/factual_learning.py`.
Tests: `tests/growth_system/test_financial_truth.py`.

| Rule | Contract |
| --- | --- |
| Per-trade net | `net = gross(realized) - fees + funding` |
| Aggregate | `DailyReviewStats.gross_pnl`, `.fees`, `.funding_pnl`, `.net_pnl` are separate fields; wins/losses/expectancy/win-rate/long-short use **net** |
| Funding provenance | A record with `funding_provenance` in `{PROVEN, KNOWN_ZERO, KNOWN_VALUE, SETTLED, NO_OP}` is complete; `UNKNOWN/UNPROVEN/INCOMPLETE/QUARANTINED` or missing provenance under `STRICT` is incomplete |
| Unknown funding | `net_pnl = null`, `net_status = INCOMPLETE_UNKNOWN_FUNDING`, `unknown_funding_count > 0`; the knowledge pipeline must not promote the day (C5) |
| Breakeven | `net == 0` increments `breakeven_count`, never win/loss |
| Profit factor | nullable ratio with `profit_factor_status ∈ {OK, NO_LOSSES, NO_SAMPLES, INCOMPLETE_FUNDING}`. `NO_LOSSES`/`NO_SAMPLES` → `null`. `999` is not allowed, and an amount is never substituted for a ratio |
| Compatibility layer | `legacy_metrics()` and `profit_factor_compat`/`win_rate_compat` return `Decimal("0")` for undefined values **together with** the status fields. `DailyReviewRunORM` non-null columns receive the same compatibility values while `output_ref` carries `net_status` and `pf_status` |
| Funding unknown is not zero | The legacy mirror `daily_pnl` may contain a partial value for an incomplete day but is always paired with a non-`COMPLETE` `net_status` |
| Factual episodes | `_episode_record` marks `funding_provenance="PROVEN"`; factual episodes only exist after `TradeEpisodeStore` proved single ownership + funding coverage |
| Legacy DB rows | The scheduler reads legacy `TradeMemoryRecordORM` under `STRICT`, so those days are reported incomplete rather than as complete net PnL |
| PF for factual aggregates | `factual_learning` stores `profit_factor_status` and `descriptive_only` in `applicability_scope_json`; `confidence_basis=SAMPLE_COUNT_ONLY`; review rows carry `CAUSAL_CLAIM:NONE` and `confidence=0` |

Not promised: a complete net figure when funding is unknown; a profit factor
when no loss sample exists; that “result descriptor” rows are causal
explanations (G02/G04 supersede them).

## C2 — Structured Review (G02)

Implementation: `src/crypto_trader/learning/growth_contracts.py`,
`src/crypto_trader/learning/growth_review.py`,
`src/crypto_trader/learning/growth_models.py`.
Tests: `tests/growth_system/test_review_schema_and_refs.py`.

| Rule | Contract |
| --- | --- |
| Transport | Existing `LLMProvider.complete_json` protocol; no second trading brain |
| Inputs | Raw thesis, selected tool evidence, TradePlan, Risk adjustments, position HOLD/REDUCE/EXIT, fills/fees/funding, market changes and missing evidence |
| Output | Observation facts, candidate explanations, support/contrary refs, testable lessons, scope, uncertainty, data gaps |
| Refs | Every ref must be in the allowed set derived from this episode's input; `allowed_refs` may not contain refs absent from the input; violations become `REF_NOT_ALLOWED` with no success row |
| Authority | `extra="forbid"`; an authoritative `net_pnl` field is a schema failure; `risk_rule_changes` must be empty; the model never mutates risk/leverage/execution |
| Attempt persistence | provider, model, profile/prompt/schema versions, prompt hash, schema hash, input hash, attempt number, result or safe error, latency, usage; missing usage becomes `usage_status=UNKNOWN` |
| Provider failure | Recorded as `FAILED` with `PROVIDER_*`; never written as a successful review |
| Idempotency | Fingerprint `(review_date, episode_id, profile_version, input_hash)`; an existing `SUCCEEDED` attempt returns `idempotent=True` without a second provider call |
| Claim fence | Optional `claim_checker` is re-checked after the provider call; a lost claim persists `CLAIM_LOST` and no visible success |
| Cost honesty | At-least-once provider call; crash-before-save can duplicate a request. Publication is idempotent, billing is not claimed as exactly-once |
| Prompt injection | Episode text is embedded inside `<untrusted_episode_data>` and treated as data; instruction-like text is never promoted to a system rule |

## C3 — Idempotent stages (G03)

Implementation: `src/crypto_trader/learning/growth_pipeline.py`.
Tests: `tests/growth_system/test_claim_publish_recovery.py`.
Detailed design and integration package: `CONCURRENCY_AND_INTEGRATION.md`.

| Rule | Contract |
| --- | --- |
| Job identity | `(account_id, mode, review_date, source_revision, profile_version, revision)` |
| Stage separation | `stats_status`, `review_status`, `publish_status`; per-stage completion timestamps; a single `SUCCEEDED` never covers a failed middle stage |
| Claim reuse | Existing `MemoryPersistence.begin_daily_review/heartbeat/fail/save`; no second claim implementation |
| Fence | Every stage commit and day publication requires the live token/owner/fence/deadline; stale token → `CLAIM_LOST`, no visible publish |
| External call | Provider calls outside DB transactions; at-least-once, duplicate-billing risk recorded |
| Late revision | Changed `input_hash` opens `revision+1`, sets `superseded_by_revision` on the old row, retains old revision for audit |
| Incomplete funding | `net_status != COMPLETE` → `publish_status=SKIPPED_INCOMPLETE`; publisher never called |
| Recovery | Retry resumes only non-`SUCCEEDED` stages; >1,000-episode day is fully processed |
| Integration | Public bootstrap/engine wiring and migration application remain a separate integration package; this branch is IMPLEMENTATION only |

## C4 — Knowledge promotion and compression (G04)

Implementation: `src/crypto_trader/learning/growth_knowledge.py`.
Tests: `tests/growth_system/test_knowledge_revision.py`.
Schema draft and field-gap table: `MIGRATION_AND_ROLLBACK.md`.

| Rule | Contract |
| --- | --- |
| Lesson | A single case produces a `CANDIDATE` lesson with `sample_count=1`, explicit scope, support/contrary refs and separate `data_completeness`/`measurement_quality`/`hypothesis_support` axes; no PnL-derived confidence |
| Pattern | Requires `min_pattern_samples` distinct episode ids; duplicate publication of the same episode never increases the sample count |
| Non-profitability | Pattern support is derived only from structured-review evidence refs; `features_json.profitability_used=false`; no win-rate/profit-factor is derived from PnL |
| Contradiction | Contrary evidence creates a new retained version and downgrades to `CONTESTED` with an explicit grade; old versions stay auditable |
| Default retrieval | `CANDIDATE`, `REVOKED`, `EXPIRED` and future `known_at` knowledge are excluded |
| Revocation/expiry | Append-only `REVOKED`/`EXPIRED` version rows with reason; old versions retained |
| Compression | Only published (`VALIDATED`/`CONTESTED`) patterns with enough samples; stores source ids/versions/sample counts, contrary refs, invalidation conditions and `known_at`; repeated compression of the same source set is idempotent |
| Absolute rules | `always/never/must/guaranteed/all trades` language is rejected; output is phrased as a conditional hypothesis |
| Coin profile | Reuses `AICoinProfileORM`, counts distinct episodes and evidence grades, and is labelled `NOT_A_WIN_RATE` |

## C5 — Legacy import (G05)

Implementation: `src/crypto_trader/learning/growth_import.py`.
Tests: `tests/growth_system/test_legacy_import.py`.
Rollback contract: `MIGRATION_AND_ROLLBACK.md`.

| Rule | Contract |
| --- | --- |
| Read-only first | `inventory`/`build_plan` use a read-only SQLite URI + backup API; source hash is unchanged by tests |
| No automatic upgrade | Legacy rows become `LEGACY_OBSERVATION` (with `proof_kind` like `LEGACY_AI_EPISODE`) or `QUARANTINED`; they are never written to canonical `trade_episodes` |
| Namespace | `sha256(source_db_sha256|table|source_id|account_id|mode)` preserves source identity and isolates accounts |
| Near duplicates | Same symbol/time/PnL similarity only marks `DUPLICATE_SUSPECT` and quarantines; it is never used to merge rows |
| Same namespace, different content | `CONTENT_CONFLICT` item + quarantine; the original observation is not overwritten |
| Time semantics | `economic_closed_at` comes from the source; `imported_at`/`known_at` are import-time and never time-travel into past as-of queries |
| Batch identity | Batch id + plan hash + source hash; a completed identical plan is idempotent |
| Resume | Failure after a durable item boundary marks the batch `FAILED`; `resume_batch_id` continues without duplicating items |
| Rollback | Deletes only that batch's observations/items and marks the batch `ROLLED_BACK`; source and other batches untouched |
| Authorization | `import_plan` requires `test_only=True` and a target under an ephemeral temp directory; known production paths are refused |

## C6 — Chief retrieval (G06)

Status: retrieval adapter in `src/crypto_trader/learning/growth_retrieval.py`;
production bootstrap wiring is an integration package (public file).
