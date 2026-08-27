# CANDIDATE CONTRACT

Status: implemented contracts only (`src/crypto_trader/evolution/lab/`), tested by
tests/evolution/test_candidate_contracts.py. Deliberately NOT implemented:
self-modification engine, sandbox execution, validation/backtest/OOS/walk-forward
certification, safe upgrade windows, champion replacement, activation, rollback.

## Contracts

### FactorHypothesis (frozen)

Why an experiment deserves to exist: `hypothesis_id`, `source_lesson_ids`,
`source_review_ids`, `target_factor/regime/strategy`, `problem_statement`,
`expected_mechanism`, `proposed_change`, `expected_benefit`, `possible_harm`,
`success_metrics` (>= 1 required), `guardrail_metrics`, `created_at_utc`.

### EvolutionCandidate (frozen)

The materializable artifact: `candidate_id`, `candidate_type`, `parent_version`,
`candidate_version`, `hypothesis_id`, `changed_components` (>= 1), `code_hash`,
`config_hash`, `strategy_version`, `factor_version`, `model_version`,
`prompt_version`, `dataset_version`, `created_at_utc`, `status`.

Statuses: `DRAFT`, `MATERIALIZED`, `VALIDATING`, `REJECTED`, `CERTIFIED`,
`READY_FOR_UPGRADE`.

**There is no ACTIVE status.** Production activation belongs to Safe Promotion;
the transition guard rejects `ACTIVE/PROMOTED/DEPLOYED` outright with
`IllegalCandidateTransition`.

### CandidateLineageRecord (frozen)

Provenance row: `candidate_id`, `parent_candidate_id`, `parent_version`,
`hypothesis_id`, `mutation_type`, `changed_components`, `created_at_utc`.
`lineage_chain(records, leaf)` walks parent links leaf->root and raises on cycles.

## Status state machine

```text
DRAFT -> MATERIALIZED -> VALIDATING -> { REJECTED | CERTIFIED }
CERTIFIED -> READY_FOR_UPGRADE
REJECTED terminal; READY_FOR_UPGRADE terminal
```

Any other jump raises `IllegalCandidateTransition`. Frozen instances advance via
`transition(target)`, which returns a new instance (`dataclasses.replace`);
the original is never mutated.
