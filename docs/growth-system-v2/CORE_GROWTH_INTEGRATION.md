# Core + Growth V2 Integration Convergence

CORE_BASE_SHA=dde3cbc9c4adef615c9501d527927506396fe7fb
GROWTH_SOURCE_SHA=1624ddeb2adaa3f6897538d57706afaaf4a43468
GROWTH_FINAL_SHA=66b237018cb2bbb0714ecabd8bd22b6ecb9ede3f
MERGE_BASE=df55b11bcde5d50670ef92d05ba2166feb4735d9

This integration uses the core candidate as the semantic base and merges
Growth V2 without reverting core market-selection, global LLM-budget,
valuation, risk, execution, or recovery behavior.

## Shared-file resolutions

- `llm_chief/runtime_strategy.py`: preserves core MarketSelection research
  queue/lineage and adds Growth V2 canonical card context + decision-trace
  attachment.
- `persistence/models.py`: preserves core decision scan/selection lineage and
  `MarketSelectionORM`, while extending `ai_compressed_experience` as the
  canonical Adaptive Experience Card store.
- `runtime/bootstrap.py`: preserves core `GlobalLLMBudget`, scanner state,
  `MarketDirectory`, and `MarketSelectionService`, while registering
  `ExperienceCardRetriever`, `CardDecisionTraceStore`, and
  `DailyCardLearner`.

## Migration convergence

```text
0039_applicability
  -> 0040_runtime_settings
  -> 0041_market_selection
  -> 0042_growth_v2_cards
```

The original Growth branch revision number `0040_growth_v2_cards` is
semantically rebased to `0042_growth_v2_cards` to preserve a single Alembic
head. Growth schema semantics remain additive.

## Safety

Growth evidence remains evidence-only. It does not gain Risk, Execution,
order, exchange, or direction authority.

No runtime was started, no execution lease was touched, and no production
database was written by this GitHub integration operation.

Real-provider smoke and natural PAPER growth-loop evidence remain separate
runtime qualification gates.
