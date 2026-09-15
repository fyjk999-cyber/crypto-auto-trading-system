# PHASE 3 RECEIPT — AI-DECISION FUSION BECOMES RECOMMENDATION-ONLY

Status: **PASS**
Date: 2026-09-15T18:12Z (2026-09-16 02:12 +08:00)

## Identity

| Item | Value |
|---|---|
| BASE_SHA | `65e3857` (phase 2) |
| FINAL_PHASE_SHA | commit containing this receipt |
| BRANCH | `codex/low-risk-v2-inplace-evolution` |
| WORKTREE | `/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-v2` |
| MIGRATIONS | none (head `0023_opportunity_lineage`) |
| PAPER/LIVE | PAPER only; no runtime started |

## Existing modules inspected / reused

- `ai_decision/decision_engine.py::AIDecisionEngine.decide` + `DirectionDecision`
- `ai_decision/fusion.py::fuse` (0.6 quant / 0.4 AI weighted fusion)
- `ai_decision/conflict.py::resolve_conflict`
- callers: `tests/ai_phases/test_ai_phases.py::test_ai_decision_long_short_conflict` (only real caller)
- Phase 2 package: `factors/expert/engine.py::build_consensus` and `ModelEvidence`
- `factors/expert/types.py::reliability_for_samples` sample tiers

## KEEP / EXTEND / ADAPT / DEPRECATE / ADD

| Action | Component | Detail |
|---|---|---|
| KEEP | `AIDecisionEngine.decide(...)` signature and numeric behavior | existing caller regression untouched (LONG 0.8 + LONG 0.6 → 0.72) |
| KEEP | `fusion.fuse`, `conflict.resolve_conflict` | retained for compatibility; recommendation path bypasses them for aggregate evidence |
| KEEP | no execution path in `ai_decision` | static source test |
| EXTEND | `DirectionDecision` | additive `recommendation: dict \| None`, `authority="RECOMMENDATION_ONLY"` |
| EXTEND | `AIDecisionEngine` | optional `RecommendationEngine`; new `recommend_from_evidence()`, `decide_from_evidence()` |
| ADAPT | authority semantics | fusion output is explicitly recommendation-level; nothing here can become a trade authority |
| DEPRECATE | none | old fusion remains readable; not removed |
| ADD | `ai_decision/recommendation.py` | `TradingRecommendation` + `RecommendationEngine` |
| ADD | `ai_decision/correlation.py` | `RollingScoreCorrelation` (30D/90D windows, union-find clusters, effective independent count) |
| ADD | `tests/low_risk/test_phase3_recommendation.py` | 7 tests |

No new top-level package, service, table or dependency.

## Recommendation contract

`TradingRecommendation` carries: suggested direction, score, confidence, long/short/neutral/unavailable counts, raw consensus score, correlation-adjusted score, effective independent evidence, family consensus, strongest support, strongest 3 counterarguments, full raw opposition, Growth reliability per model (sample size + tier), regime compatibility per model, strategy fit, data quality, degraded/unavailable reasons, correlation diagnostics, `authority="RECOMMENDATION_ONLY"`, `not_an_order=True`.

### Correlation control (initial auditable approach, configurable)

- `RollingScoreCorrelation(window_days=90, reference_windows=(30, 90), cluster_threshold=0.7, min_overlap=8)`.
- Union-find clusters by `|corr| >= threshold` (anti-correlated models carry the same information inverted).
- `effective_independent_evidence = min(family-collapsed directional count, observed correlation clusters)`; family collapsing is the baseline, observed correlation can only reduce breadth further and can never inflate it.
- No history yet → family-collapsed count (documented fallback, test-covered).

## Files changed

- `src/crypto_trader/ai_decision/recommendation.py` (new)
- `src/crypto_trader/ai_decision/correlation.py` (new)
- `src/crypto_trader/ai_decision/decision_engine.py` (additive)
- `tests/low_risk/test_phase3_recommendation.py` (new)
- `docs/low-risk/receipts/PHASE_3_RECEIPT.md`

## Backward compatibility

- `decide()` is byte-for-byte behavior-compatible for existing callers (regression asserts the exact historical score).
- New `DirectionDecision` fields have defaults → existing constructions/assertions unaffected.
- No import cycle: `ai_decision.recommendation` imports `factors.expert` (one-way; `factors` never imports `ai_decision`).

## Tests and evidence

Focused:

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests/low_risk -q
→ 26 passed (7 phase 1 + 12 phase 2 + 7 phase 3)
```

Full regression:

```
PYTHONPATH=$PWD/src .venv/bin/python -m pytest tests -q
→ 679 passed, 1 warning in 75.31s   (phase-2 baseline 672)
```

Ruff: `src/` and `tests/` → **All checks passed**.

Key assertions:
- 20L/5S/0N vs 20L/0S/5N produce different counts, raw scores and suggested action; both `NOT_AN_ORDER`.
- Correlated wave fixtures: `corr(A,B)=1.0`, `corr(A,C)=-1.0`, clusters `[1,3]`, effective independent count 2; full 25-model correlated history collapses to `effective_independent_evidence == 1`.
- Unavailable models reported in `degraded_reasons`, never assigned a direction.
- `decide_from_evidence()` returns `NO_TRADE` for an all-neutral package; `authority=RECOMMENDATION_ONLY`.
- Static test proves no `ExecutionAuthority/OrderManager/submit_order/process_signal/SignalIntent/TradePlan/ExecutionDecision` references in the recommendation layer.

## P0 / P1

- P0: none. Recommendation layer cannot reach execution; existing authority path unchanged.
- P1: correlation windows default to 90 daily samples and are not yet fed by Growth outcome history; the tracker is wired but only records in-process model scores. Phase 5 will persist score history and reliability outcomes.

## Next phase

PHASE 4 — Core LLM TradePlan + position management: structured contract (Base Exit, NEXT_REASSESSMENT, capital allocation), DeepSeek retry → GLM latest-state → offline, event-driven reassessment, Risk L1/L2 adaptation, Fast Profit, partial/hedge, exit coordination.
