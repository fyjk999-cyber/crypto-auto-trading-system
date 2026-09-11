# Growth System V2 — final report

```text
BASE_SHA = 2561e4fdce2cd4b44e0f30d73e427be2e7eded8b
FINAL_SHA = 3907b1a4ed5c48ff23829de20f077db40533c572 (implementation commit; the report commit is docs-only metadata)
BRANCH = codex/growth-learning-pipeline
WORKTREE = /Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-growth
REMOTE = https://github.com/fyjk999-cyber/crypto-auto-trading-system.git
DIRTY_FILES = [] (task worktree clean at baseline discovery)
```

## FILES_CHANGED

Modified:

```text
src/crypto_trader/persistence/models.py            (AICompressedExperienceORM extended in place)
src/crypto_trader/learning/growth_models.py        (+ growth_card_versions / decision traces)
```

Added:

```text
src/crypto_trader/learning/growth_v2_contracts.py
src/crypto_trader/learning/growth_card_view.py
src/crypto_trader/learning/growth_card_quality.py
src/crypto_trader/learning/growth_experience.py
src/crypto_trader/learning/growth_card_retrieval.py
src/crypto_trader/learning/growth_attribution.py
src/crypto_trader/learning/growth_v2_migration.py

tests/growth_system_v2/conftest.py
tests/growth_system_v2/test_card_schema_and_migration.py
tests/growth_system_v2/test_trigger_context.py
tests/growth_system_v2/test_card_retrieval.py
tests/growth_system_v2/test_attribution_evolution.py
tests/growth_system_v2/test_quality_decay.py
tests/growth_system_v2/test_chief_card_integration.py
tests/growth_system_v2/test_closed_loop_g14.py
tests/growth_system_v2/test_read_write_separation.py
tests/growth_system_v2/test_invariants.py

docs/growth-system-v2/ARCHITECTURE.md
docs/growth-system-v2/REUSE_MATRIX.md
docs/growth-system-v2/EXPERIENCE_CARD_SCHEMA.md
docs/growth-system-v2/TRIGGER_CONTEXT_CONTRACT.md
docs/growth-system-v2/RETRIEVAL_CONTRACT.md
docs/growth-system-v2/ATTRIBUTION_AND_EVOLUTION.md
docs/growth-system-v2/SAFETY_BOUNDARIES.md
docs/growth-system-v2/ACCEPTANCE_MATRIX.md
docs/growth-system-v2/FINAL_REPORT.md
```

`tests/growth_system/test_metrics_and_gates.py` was updated only for the draft
schema table count (10 → 12).  No runtime/router/frontend file was modified.

## REUSE_DECISIONS

```text
KEEP
- trade_episodes / TradeEpisodeStore (factual truth)
- MemoryPersistence day claim/fence
- vector_memory HybridRetriever + MemoryVectorStore (semantic component)
- MemoryGovernor quality formula
- KnowledgeDecayEngine decay health
- FactorLifecycleManager / FactorLifecycleORM (factor lifecycle)
- KnowledgeGraph (relations, not replaced)
- LLMDecisionStore / DynamicEvidencePackage (decision truth + evidence)
- llm_chief in-memory ExperienceMemory/KnowledgeBase (decision layer)

ADAPT
- AICompressedExperienceORM → canonical Adaptive Experience Card table
- growth_v2 migration helper (additive columns, draft, not on Alembic chain)
- DailyCardLearner on the Daily Review path
- card status enum on top of the existing small lifecycle pattern

MERGE
- none required; card journals are narrow lineage/trace sidecars

DEPRECATE
- v1 growth_compressions is no longer the runtime card store; it remains only
  for v1 compression tests and must be merged/removed at integration
```

## G08_RESULT

`REUSE_MATRIX.md` completed after reading the listed modules.  Duplicate gates
all pass: NO_DUPLICATE_MEMORY/REVIEW/RETRIEVAL/LIFECYCLE/EPISODE systems.
Canonical card persistence is the existing `ai_compressed_experience`.

## G09_RESULT

Adaptive Experience Card domain + store + version journal implemented.
Single-episode cards stay `CANDIDATE`; independent evidence is required for
`ACTIVE`.  Migration helper supports fresh/upgrade/repeat/downgrade/re-upgrade
and legacy backfill to `COMPRESSED_EXPERIENCE/WATCH`.

## G10_RESULT

Canonical `TriggerSignature`/`ContextSignature` entry points are deterministic,
order-independent, preserve factor definition versions and use explicit
`UNKNOWN` (never guessed).  Same trigger + different regime changes hard
applicability.

## G11_RESULT

Runtime read path: hard filter → bounded candidate set → HybridRetriever
semantic → MemoryGovernor quality → KnowledgeDecayEngine decay → versioned
weights → Top-K ≤ 5 → token budget.  Every result carries candidate/selected/
excluded reasons, versions, scores, signatures and metrics; decision trace is
persisted.  Retrieval is proven write-free by a SQLAlchemy statement listener.

## G12_RESULT

Attribution splits market outcome / decision quality / prediction correctness /
risk adjustment / execution quality / data quality / external effects and only
records `OUTCOME_ASSOCIATED`.  Operations KEEP/UPDATE/CREATE/SPLIT/MERGE/WATCH/
RETIRE implemented with append-only version lineage; WIN/LOSS alone never
changes confidence.

## G13_RESULT

Card quality reuses MemoryGovernor + KnowledgeDecayEngine; confidence has
explicit axes and is never wins/samples.  Status path
CANDIDATE→ACTIVE→WATCH→STALE→RETIRED is covered, history is never deleted, and
auto-retire is policy-gated.

## G14_RESULT

Closed-loop simulation passes: factual episode → review → pattern → card →
retrieval → Chief evidence → decision trace → next outcome → support/
contradiction → version update → replay idempotent.  Read/write separation and
invariant tests pass; no runtime/deployment was performed.

## EXPERIENCE_CARD_SCHEMA

See `EXPERIENCE_CARD_SCHEMA.md`.  Canonical table `ai_compressed_experience`
extended with trigger/context/scope/guidance/evidence/quality/decay/status/
lineage/known-at fields; journals `growth_card_versions` and
`growth_card_decision_traces`.  Schema revision: DRAFT; no Alembic revision or
`down_revision` claimed.

## READ_PATH

`growth_card_retrieval.ExperienceCardRetriever` +
`register_experience_card_tool` (official `LLMToolRegistry`) +
`CardDecisionTraceStore` (write trace only).

## WRITE_PATH

`growth_attribution.DailyCardLearner` → `growth_experience.AdaptiveCardStore`
→ canonical table + version journal.  Runtime origin is rejected with
`PermissionError`; fence loss raises `ClaimLostError` before any write.

## CHIEFTRADER_INTEGRATION

Cards enter through the same `ToolDrivenChiefTrader` / `LLMToolRegistry` path
used by existing evidence tools.  Tool output carries
`evidence_only=true`, `can_emit_direction=false` and
`HISTORICAL_EXPERIENCE_EVIDENCE_NOT_COMMANDS`; the test asserts the final
prompt contains card refs plus this semantics and that the Chief still decides
`NO_TRADE`.  No direction/action is derived from a card.

## ATTRIBUTION_MODEL

Seven explicit axes; causality string is `OUTCOME_ASSOCIATED`.  Support/
contradiction are derived from structured-review evidence refs, not PnL.
Contradiction downgrades to WATCH (or RETIRE only under explicit policy);
support cannot silently re-promote an unresolved WATCH.

## VERSIONING_AND_ROLLBACK

Every operation writes a `growth_card_versions` row with a unique
`proposal_hash`; KEEP reuses the current version, other operations append a new
version and `supersedes` links.  SPLIT children carry parent lineage; MERGE
requires compatible trigger/context/guidance and retires sources.  Rollback:
draft downgrade drops only the added columns/journals; knowledge retirement is
append-only and canonical tables are never dropped.

## TEST_RESULTS (integration hardening, current branch)

```text
focused hardening bundle (V2 + v1 growth + p8 daily review + p8 migrations +
memory persistence + llm_chief + risk + governance)
  = 224 passed, 1 skipped in 31.96s
V2 suite                     = 63 passed, 1 skipped (real PostgreSQL URL absent)
full backend pytest          = 1029 passed, 1 skipped, 2 warnings in 137.28s
ruff (whole repo)            = All checks passed
migration tests              = 7 passed, 1 skipped
                               (0039→0040 upgrade/repeat/downgrade/re-upgrade;
                                PostgreSQL offline SQL compile)
alembic head                 = 0040_growth_v2_cards
agent-project-test           = NOT_AVAILABLE (entry does not exist)
frontend                     = NOT_APPLICABLE (no frontend files changed; no node/npm)
```

The previously observed position-lifecycle failure ran in this full suite and
did not recur; it remains monitored, not auto-labelled flaky.

Evidence logs (ignored `.ops-growth-v2/`, SHA-256):

```text
174aec0a113b95640efb76dd522fc899249cf054e6a80fe8ab8e76360e02db73  hardening_full_pytest.log (1029 passed)
1ec5d00a874d886d55ed90f088bbb5ea871789ebc61469cee6618fb747ce088f  hardening_focused.log (224 passed)
82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18  hardening_ruff.log
ba1122be5eb405b7106b23a451b25a8a699ebbea335d92884f0a45712d9ea253  hardening_migration.log
f7dd325af8f0ee813426c385b5d2fac311ad381521b1e1e99be51aab587cc795  full_pytest_final_sha.log (previous phase)
```

## DEFINITION_OF_DONE (12)

```text
1  factual CLOSED trade enters Daily Review                                   YES (G14 test)
2  review produces factual/testable lesson                                    YES (v1 growth + G14)
3  lesson/pattern matches or updates an Experience Card                        YES (DailyCardLearner)
4  card keeps evidence + contradiction + version lineage                       YES (journals + tests)
5  next similar market state retrieves the card                                YES (retrieval tests)
6  card enters ChiefTrader context as evidence                                 YES (tool registry test)
7  ChiefTrader keeps sole direction authority                                  YES (NO_TRADE assertion, no direction field)
8  decision records used card + version                                        YES (decision trace test)
9  next factual outcome revalidates the card                                   YES (G14 support/contradiction)
10 KEEP/UPDATE/SPLIT/MERGE/RETIRE supported                                    YES (evolution tests)
11 live runtime cannot modify cards                                            YES (write-free listener + origin gate)
12 growth never modifies Risk/Execution hard safety                           YES (import graph + config/count tests)

GROWTH_SYSTEM_V2_COMPLETE = YES (engineering)
GROWTH_SYSTEM_V2_ENGINEERING_READY = YES
RUNTIME_AUTHORIZED = false
DEPLOYED = false
```

## INVARIANT_RESULTS

```text
V2 modules import no risk/execution/order/exchange/runtime/simulator module        PASS
V2 modules define no authority function (submit_order/place_order/...)            PASS
Card semantics evidence_only=true, can_emit_direction=false                        PASS
Card operations create no Order/Fill/TradeEpisode rows                             PASS
RiskEngine configuration unchanged after card operations                           PASS
Runtime retrieval issues no INSERT/UPDATE/DELETE (statement listener)              PASS
Fence loss blocks card mutation                                                    PASS
Replay/restart does not double-update cards                                        PASS
Historical as_of uses the visible journal snapshot, not the latest row             PASS
```

## KNOWN_LIMITATIONS

* Real Alembic revision `0040_growth_v2_cards` is integrated and tested on
  SQLite (upgrade/repeat/downgrade/re-upgrade) plus PostgreSQL offline SQL
  compilation.  A real PostgreSQL execution is `NOT_VERIFIED` because
  `GROWTH_V2_POSTGRES_URL` was not provided.
* Card closed loop was proven with deterministic test providers on temp DBs;
  `REAL_PROVIDER_SMOKE=NOT_VERIFIED` (no approved credential in this
  environment) and `NATURAL_PAPER_GROWTH_LOOP=PENDING` (no runtime started, no
  natural closed lifecycle in the window).
* Legacy `growth_compressions` remains for v1 metrics/tests and is classified
  LEGACY_WRITE/READ/TEST_ONLY; `LEGACY_RUNTIME_CARD_READS=0` and
  `LEGACY_RUNTIME_CARD_WRITES=0` are enforced by
  `test_legacy_path_audit.py`.
* Full-suite run #1 in the previous phase had one order/timing-sensitive
  position-lifecycle failure that passed 5/5 in isolation; the current
  integration-hardening full suite is 1029 passed / 0 failed and the test is
  monitored on every run.
* `agent-project-test` is unavailable in this environment.
* No deployment, runtime start/restart or production backfill was performed.

## BLOCKERS

```text
engineering: none
REAL_PROVIDER_SMOKE: no approved DeepSeek/provider credential in this environment
NATURAL_PAPER_GROWTH_LOOP: no runtime authorization and no natural closed lifecycle
PRODUCTION_DEPLOY: separate authorization required
REMOTE_PUSH: see final receipt (push attempted after tests)
```

```text
CORE_ENGINE_COMPLETE = YES
MIGRATION_INTEGRATED = YES (not deployed)
CANONICAL_RUNTIME_WIRED = YES (composition root wired; not started)
CANONICAL_SCHEDULER_WIRED = YES
REAL_PROVIDER_VERIFIED = NO (NOT_VERIFIED)
NATURAL_PAPER_LOOP_VERIFIED = PENDING
DEPLOYABLE = ENGINEERING_READY
RUNTIME_AUTHORIZED = false
DEPLOYED = false
```
