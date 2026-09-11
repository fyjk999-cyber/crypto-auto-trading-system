# Core + Growth V2 Integration Convergence

```text
CORE_BASE_SHA=dde3cbc9c4adef615c9501d527927506396fe7fb
GROWTH_SOURCE_SHA=1624ddeb2adaa3f6897538d57706afaaf4a43468
GROWTH_FINAL_SHA=66b237018cb2bbb0714ecabd8bd22b6ecb9ede3f
MERGE_BASE=df55b11bcde5d50670ef92d05ba2166feb4735d9

INTEGRATION_MERGE_SHA=1fb68dcb039c7913faffcd67df6c0dcfe6ee05d8
INTEGRATION_IMPLEMENTATION_SHA=42a65be572231c303cc40f08bb0ccdef2017449e
TEMP_QUALIFICATION_WORKFLOW_REMOVED_AT=54f47873b7f04cbc8f7018685008f11c33f54038
FINAL_BRANCH_SHA=this receipt commit
BRANCH=codex/final-core-growth-v2-integration
PR=3
```

## Convergence

Before integration the two candidates were diverged from
`df55b11bcde5d50670ef92d05ba2166feb4735d9`:

- core candidate: 16 commits ahead of merge base;
- Growth candidate: 19 commits ahead / 16 commits behind core in the direct compare.

The integration merge has both the core candidate and Growth final branch as
parents.  Post-merge ancestry verification:

```text
core -> integration:   behind=0, merge_base=dde3cbc...
growth -> integration: behind=0, merge_base=66b2370...
```

The final integration branch is therefore no longer diverged from either
candidate.

## Shared-file resolutions

### `src/crypto_trader/llm_chief/runtime_strategy.py`

Preserved core:

- MarketSelection research queue;
- `selection_service`;
- `current_selection` / `_selected_research_queue`;
- scan/selection lineage;
- `deepseek_selected`;
- `mark_llm_research`.

Added Growth V2:

- `CardDecisionTraceStore`;
- `build_card_tool_context`;
- account/mode card context;
- trace attachment to final `decision_id`.

Both paths coexist.  Market selection remains research-attention authority
only; Growth cards remain evidence only.

### `src/crypto_trader/persistence/models.py`

Preserved core:

- `LLMDecisionORM.scan_id`;
- `LLMDecisionORM.selection_id`;
- `MarketSelectionORM`;
- all core portfolio/risk/accounting models.

Added Growth V2 by extending the existing canonical
`ai_compressed_experience` table in place with scope, trigger/context,
guidance, evidence, support/contradiction, confidence/quality/decay, status,
known-at and version-lineage fields.

### `src/crypto_trader/runtime/bootstrap.py`

Preserved core:

- `GlobalLLMBudget`;
- `MarketDirectory`;
- `MarketSelectionService` / `MarketSelectionStore`;
- `ScannerStateStore` / `ScannerConfig`;
- core market-intelligence engine/app-state wiring.

Added Growth V2:

- `ExperienceCardRetriever`;
- `CardDecisionTraceStore`;
- official-registry `experience_cards` tool;
- card context/trace injection into `LiveLLMDecisionStrategy`;
- `DailyCardLearner` injection into the canonical `DailyReviewScheduler`.

Risk and Execution authority were not expanded.

## Migration convergence

The Growth branch's original `0040_growth_v2_cards` could not be merged as-is
because the core branch already owned `0040_runtime_settings` and
`0041_market_selection`.

The integrated single-head chain is:

```text
0039_applicability
  -> 0040_runtime_settings
  -> 0041_market_selection
  -> 0042_growth_v2_cards
```

Growth schema semantics remain additive.  Legacy compressed-experience rows are
backfilled, not deleted.

## Qualification

Exact integration implementation SHA tested:

`42a65be572231c303cc40f08bb0ccdef2017449e`

Full integration qualification:

```text
Growth focused:
145 passed, 1 skipped

Core constraint / opportunity / risk focused:
172 passed

Growth migration:
2 passed, 1 skipped
(real PostgreSQL execution remains skipped without GROWTH_V2_POSTGRES_URL)

Alembic heads:
0042_growth_v2_cards (head)
single head = YES

Full backend pytest:
1153 passed, 2 skipped, 2 warnings

Ruff:
All checks passed
```

Default repository CI on the same implementation SHA also completed
successfully, including lint, unit-test, integration-test, cloudflare-worker
and container-build.

Two pre-existing CI portability defects were exposed during full qualification
and fixed without changing trading behavior:

1. a full-market authority test used a hard-coded local macOS repository path;
2. macOS installer diagnostics tests did not fully model required macOS tool
   availability when executed on Linux CI.

## Preserved invariants

```text
CORE_CONSTRAINTS_PRESERVED=YES
MARKET_SELECTION_PRESERVED=YES
GLOBAL_LLM_BUDGET_PRESERVED=YES

GROWTH_V2_RUNTIME_WIRED=YES
GROWTH_V2_SCHEDULER_WIRED=YES
TRACE_BEFORE_USE=YES
ACCOUNT_MODE_ISOLATION=YES

LEGACY_RUNTIME_CARD_READS=0
LEGACY_RUNTIME_CARD_WRITES=0

SINGLE_ALEMBIC_HEAD=YES
INTEGRATION_CONVERGENCE=PASS
```

Core factual cash-flow constraints remain intact, including verified ownership,
currency ambiguity fail-closed behavior, UNKNOWN != ZERO, valuation
completeness gating, and reduce-only lifecycle behavior.

## Runtime / deployment state

```text
REAL_PROVIDER_SMOKE=NOT_VERIFIED
NATURAL_PAPER_GROWTH_LOOP=PENDING

PRODUCTION_DB_WRITE=NO
EXECUTION_LEASE_TOUCHED=NO
RUNTIME_STARTED_OR_RESTARTED=NO
RUNTIME_AUTHORIZED=false
DEPLOYED=false
REAL_MONEY_READY=NO
```

This convergence establishes one engineering candidate containing both the
core trading-system corrections and Growth V2.  It does not authorize
production migration, runtime restart, or real-money trading.
