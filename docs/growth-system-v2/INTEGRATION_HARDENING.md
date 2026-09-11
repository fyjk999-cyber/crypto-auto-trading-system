# Growth V2 — integration hardening (I00–I11)

This phase only wires the completed core engine into the canonical runtime,
migration and Daily Review paths.  No new Skill/memory/retrieval/lifecycle/
graph/attribution/agent abstraction was added.

## I00 — factual baseline

```text
WORKTREE=/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-growth
BRANCH=codex/growth-learning-pipeline
BASE_SHA=2561e4fdce2cd4b44e0f30d73e427be2e7eded8b
IMPLEMENTATION_SHA (pre-hardening)=3907b1a4ed5c48ff23829de20f077db40533c572
DOCS_HEAD=09f7948a19f3832c9655d9eb0a1540be832d9b18
DIRTY_FILES=[] (clean at discovery; no reset/clean/rebase)
```

## I01 — real Alembic integration

```text
ALEMBIC_OLD_HEAD=0039_applicability
ALEMBIC_NEW_HEAD=0040_growth_v2_cards
MIGRATION_REVISION=migrations/versions/0040_growth_v2_cards.py
down_revision=0039_applicability
```

The revision adds the V2 columns to `ai_compressed_experience`, the account/
mode/status and scope indexes, and creates `growth_card_versions` +
`growth_card_decision_traces` with their unique/idempotency constraints.
Legacy rows are backfilled to `COMPRESSED_EXPERIENCE/WATCH`, `ACCOUNT_MODE`,
never deleted.  Tests cover previous head → new head, repeat upgrade,
downgrade, re-upgrade, SQLite execution and PostgreSQL offline SQL
compilation (`test_alembic_migration.py`).  The old draft helper is now
test/support only.

## I02 — account / mode hard isolation

`ExperienceCardRetriever` filters by exact `account_id` + `mode` with an
explicit `share_scope` column:

* `ACCOUNT_MODE` (default): exact account + mode only;
* `GLOBAL_EXPLICIT`: only allowed when the card also carries
  `applicability_scope_json.sharing == "GLOBAL_EXPLICIT"` and an explicit
  `approved_by`;
* missing/empty/`UNKNOWN` account, mode or share scope = ineligible; never
  inferred as GLOBAL.

Tests: `tests/growth_system_v2/test_account_mode_isolation.py`.

## I03 — canonical runtime wiring

Canonical composition root: `runtime/bootstrap.py::build_system`.

* `ExperienceCardRetriever(database.session_factory)` → official
  `LLMToolRegistry` via `register_experience_card_tool`.
* `CardDecisionTraceStore(database.session_factory)` shared by the tool and
  `LiveLLMDecisionStrategy`.
* `LiveLLMDecisionStrategy` receives the factual strategy context and builds
  canonical trigger/context through `learning/growth_v2_runtime.py`
  (`factor_states_from_observations`, `market_state_from_strategy_context`)
  and passes them into `ToolDrivenChiefTrader.decide`.
* After the Chief decision, `_attach_card_decision_trace` links the durable
  trace row to `decision_id`; attach failure is audited, never changes the
  decision.
* Risk and Execution code were not modified.

Tests: `test_integration_wiring.py::test_build_system_canonical_composition_root`.

## I04 — trace before use

The `experience_cards` tool persists the retrieval trace **before** returning
card evidence.  If trace persistence fails, it returns an empty evidence item
with `card_evidence_available=false`, `data_quality=TRACE_UNAVAILABLE`, and the
Chief decision continues without cards.  No card evidence is exposed without a
durable trace.

Tests: `test_trace_persisted_before_card_evidence_exposed`,
`test_trace_failure_hides_card_evidence_and_decision_continues`.

## I05 — canonical Daily Review wiring

`DailyReviewScheduler` (the only scheduler) now accepts an optional
`DailyCardLearner` and runs, in deterministic order:

```text
factual episode selection
→ DailyReview stats
→ FactualEpisodeLearning review_many (lesson/pattern update)
→ claim heartbeat (fence)
→ DailyCardLearner.learn_day (proposal → fence validation → canonical card
  update + journal)
→ fenced daily publication + episode mark
```

Claim/fence loss raises `ClaimLostError` in the learner and produces
`card_learning.status=CLAIM_LOST` with **no card mutation**.  Card-learning
failure is reported (`FAILED`) without blocking the factual daily review.
Replay remains idempotent through `proposal_hash`.

Tests: `test_scheduler_card_learning_updates_once_and_replay_is_idempotent`,
`test_scheduler_claim_loss_blocks_card_mutation`,
`test_scheduler_card_failure_is_reported_but_does_not_block_review`.

## I06 — v1 duplicate path

Reference classification (audited in `test_legacy_path_audit.py`):

| Call site | Classification |
| --- | --- |
| `learning/growth_models.py` (`GrowthCompressionORM`) | schema/test support |
| `learning/growth_knowledge.py` (`compress`) | LEGACY_WRITE (v1 only) |
| `learning/growth_metrics.py` | LEGACY_READ (metrics only) |
| `learning/growth_retrieval.py` (v1 loader) | LEGACY_READ (not canonical runtime) |
| `tests/**` | TEST_ONLY |

```text
LEGACY_RUNTIME_CARD_READS=0
LEGACY_RUNTIME_CARD_WRITES=0
canonical truth = ai_compressed_experience
```

## I07 — real provider run (built-in LLM enabled)

Credential check (values never printed; no environment dump):

```text
macOS Keychain (project helper) = credential exists
DEEPSEEK_API_KEY env before run  = false
model for review                 = deepseek-flash
thinking                         = enabled
max_tokens                       = 8192
in-process only                  = true (never printed/persisted)
```

The built-in DeepSeek provider was connected in memory and the real
`StructuredReviewRunner` processed the 33 factual PAPER episodes in
canonical-clean.  No simulation was substituted:

```text
REAL_PROVIDER_SMOKE=VERIFIED
provider_attempts=53 (KNOWN usage), successful structured reviews=33/33 episodes
episode review_status: PENDING=0, REVIEWED=33
generated knowledge: growth_lessons=59 CANDIDATE, growth_patterns=20 CANDIDATE
cards=0 (all pattern scopes have independent_sample_count=1 < required 3)
data integrity: orders=205, fills=434, risk_decisions=3388,
                llm_decisions=13271, trade_plans=167 — identical to backup
```

Model lineage during the run: 24 episodes were first reviewed by
`deepseek-chat` before the operator switched back to flash thinking; the
remaining 9 were reviewed by `deepseek-flash` with thinking enabled and the
8192-token cap.  The runtime review provider is now configured as
`deepseek-flash`, thinking=true, max_tokens=8192 (`LLM_REVIEW_MODEL` /
`LLM_REVIEW_MAX_TOKENS` override).

Runner: `scripts/growth_review_worker.py`; scheduler stage:
`StructuredReviewRunner`; report evidence in
`.ops-growth-v2/paper_review/SYSTEM_REVIEW_SUMMARY.json`.

## I08 — natural PAPER closed loop

Read-only snapshot before the review run:

```text
canonical-clean: trade_episodes=33, max closed_at=2026-09-10 08:29:35, reviews=0
fullmarket:      trade_episodes=0, reviews=0
```

The 33 episodes were reviewed post-hoc by the built-in LLM; no new runtime was
started and no natural decision→fill→episode→review cycle was observed in this
window:

```text
NATURAL_PAPER_GROWTH_LOOP=PENDING (historical backfill ≠ natural live loop)
```

No fake fill/episode was created.

## I09 — status semantics

```text
CORE_ENGINE_COMPLETE=YES
MIGRATION_INTEGRATED=YES (Alembic revision real; not deployed)
CANONICAL_RUNTIME_WIRED=YES (build_system composition root; not started)
CANONICAL_SCHEDULER_WIRED=YES (DailyReviewScheduler + DailyCardLearner)
BUILTIN_LLM_REVIEW_WIRED=YES (StructuredReviewRunner, flash/thinking/8192)
REAL_PROVIDER_VERIFIED=YES (33 factual PAPER episodes)
NATURAL_PAPER_LOOP_VERIFIED=PENDING
REMOTE_REPRODUCIBLE=see final receipt (push status)
DEPLOYABLE=ENGINEERING_READY (production migration/deploy authorization required)
RUNTIME_AUTHORIZED=false
```

## I10 — full regression

```text
focused hardening bundle (V2 + v1 growth + p8 daily review + p8 migrations +
memory persistence + llm_chief + risk + governance)
  = 224 passed, 1 skipped
full backend pytest = 1029 passed, 1 skipped, 2 warnings in 137.28s
ruff (whole repo)   = All checks passed
migration tests     = 7 passed, 1 skipped (real PostgreSQL URL not provided)
```

The previously observed position-lifecycle test ran in this full suite and did
**not** recur (no flaky labelling; it is monitored).

## I11 — remote reproducibility

```text
IMPLEMENTATION_SHA=1624ddeb2adaa3f6897538d57706afaaf4a43468
  (I01 migration commit 36b7b3ca6915912100430ed07a7ec64c9b3daad7 precedes it)
FINAL_BRANCH_SHA=c0c4be51ffdee89c27d7034354062a6528a708c8 (docs status commit)
REMOTE_BRANCH_SHA=c0c4be51ffdee89c27d7034354062a6528a708c8
push command: git push -u origin codex/growth-learning-pipeline
push result: SUCCESS (new branch created)
  remote: https://github.com/fyjk999-cyber/crypto-auto-trading-system/pull/new/codex/growth-learning-pipeline
```

The final docs-only commit that records this receipt is pushed afterwards so
local and remote branch SHAs remain identical; `IMPLEMENTATION_SHA` remains the
code SHA above.
