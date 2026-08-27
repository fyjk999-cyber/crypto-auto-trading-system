# FACTOR SYSTEM REFACTOR AUDIT

## Audit Snapshot

- Audit mode: read-only architecture audit
- Audit baseline: `eacf033830b06c8394cfc77b8a9f77d31a6bd776`
- Method: repository-wide source inspection + AST-based import/use mapping
- Runtime Python changes during audit: none
- Status: `FACTOR_AUDIT_ONLY_COMPLETE = YES`

> This section records the state observed at the audit baseline. Later commits may have advanced wiring and persistence beyond this snapshot.

## Canonical Three-Brain Ownership

The factor system is shared infrastructure and must not become a fourth brain.

- **LIVE TRADING BRAIN** — calculate, capture, consume approved factor state.
- **DAILY LEARNING BRAIN** — replay, factor attribution, error mining, decay/redundancy review, lesson generation.
- **EVOLUTION BRAIN** — discovery, research, hypothesis, candidate generation, validation, safe promotion.

## Canonical Components Verified Present

The audit verified the canonical factor stack exists in-repo, including:

- `FactorToolGateway`
- `FactorCaptureEngine`
- `FactorEngine`
- `FactorRegistry`
- `FactorCatalog`
- versioned factor-set / factor-snapshot contracts
- read-only live factor tooling

## Wiring Findings at Audit Baseline

At `eacf033`, the factor foundation existed but canonical production consumption was still incomplete in the inspected call graph:

- the factor gateway was bootstrapped, but the audit found no confirmed production consumer using it as the single decision-time factor source;
- `llm_chief` had no confirmed factor-tool wiring in the inspected baseline;
- `evolution/` had no confirmed non-test caller in the inspected baseline;
- therefore, file existence alone was not treated as proof that a three-brain path was operational end-to-end.

The required canonical direction remains:

`Market -> FactorToolGateway -> FactorSnapshot -> Analysis -> Decision -> DecisionEvidence`

and then:

`DecisionEvidence -> DAILY LEARNING -> Lessons -> EVOLUTION -> Validated Candidate -> Safe Promotion`

## Duplicate / Competing Entry Points

The audit identified **10 duplicate or competing entry points** across the broader factor/alpha/evolution surface. The notable categories included:

- two snapshot/tool access paths;
- overlapping engine-vs-capture calculation paths;
- three decay-detection paths;
- two promotion stacks;
- additional overlapping factor/alpha access paths documented by the import map.

These should not be deleted blindly. The migration rule is:

1. establish one canonical entry point per brain;
2. move callers to canonical facades;
3. preserve older providers behind adapters when still useful;
4. mark redundant public entry points `DEPRECATE` only after caller migration and regression tests;
5. delete only after no production/test caller depends on them.

## Module Classification

|Module|Classification|Canonical Ownership / Action|
|-|-|-|
|`factors/capture.py`|KEEP|LIVE provider behind `FactorToolGateway`|
|`factors/engine.py`|KEEP|LIVE calculation provider; avoid competing public orchestration path|
|`factors/registry.py`|KEEP|Shared factor registry|
|`factors/catalog.py`|KEEP|Shared factor catalog|
|`factors/models.py`|ADAPT|Shared contracts; keep versioned immutable evidence semantics|
|`factors/service.py`|ADAPT|Shared persistence/access service; no parallel SSOT|
|`factors/attribution.py`|KEEP|DAILY factor attribution provider|
|`factors/decay.py`|KEEP|DAILY review / EVOLUTION evidence provider|
|`factors/evaluator.py`|KEEP|DAILY evaluation provider|
|`factors/confidence.py`|KEEP|LIVE approved factor-confidence consumption|
|`factors/analytics.py`|KEEP|DAILY monthly/yearly analytics provider|
|`factors/discovery.py`|ADAPT|EVOLUTION discovery provider|
|`factors/experiment.py`|KEEP|EVOLUTION validation/experiment provider|
|`factors/combinations/`|KEEP|EVOLUTION candidate provider|
|`factors/anomaly/`|KEEP|DAILY/weekly review signal provider|
|`alpha_decay/`|ADAPT|Evidence provider; avoid separate canonical decay authority|
|`alpha_discovery/`|ADAPT|EVOLUTION provider behind canonical research/discovery flow|
|`alpha_intelligence/`|ADAPT|DAILY reviewer/evidence provider|
|`evolution/factor_evolution.py`|KEEP|EVOLUTION core provider|
|`factors/lifecycle/`|KEEP|EVOLUTION lifecycle state provider|
|`factors/importance.py`|KEEP|DAILY reviewer/attribution provider|

## Canonical Wiring Order

To avoid snapshot divergence, the preferred integration order is:

1. `FactorToolGateway` becomes the canonical live factor access facade.
2. A single immutable `FactorSnapshot` is created for the decision context.
3. deterministic strategy/analysis consumes that snapshot.
4. LLM factor tools expose the same approved snapshot/read path rather than recomputing an independent one.
5. `DecisionEvidence` persists `factor_snapshot_id`, `factor_set_version`, and relevant version metadata.
6. DAILY LEARNING replays historical snapshots rather than recalculating past factors.
7. EVOLUTION receives lessons/patterns and may create candidates, but cannot mutate active production factors directly.

This ordering prevents a failure mode where strategy, LLM, and replay each observe different factor versions for the same decision.

## Audit Conclusion

`FACTOR_AUDIT_ONLY_COMPLETE = YES`

The audit itself made documentation-only changes and intentionally did not alter runtime behavior.
