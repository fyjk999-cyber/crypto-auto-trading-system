# MONTHLY REVIEW POLICY

Status: implemented (`HierarchicalLearningEngine.monthly_review`). Month-window
selection lives in docs/REVIEW_PERIOD_POLICY.md; this document covers aggregation
semantics only.

## Input

Completed `WeeklyReviewResult` payloads for every ISO week label touched by the
previous completed UTC calendar month (a week counts if any of its days falls in
the month). Missing weeks produce warnings; duplicates collapse to the first
canonical report per week label.

## Aggregations

- strategy / factor evaluations carried up from weekly summaries
- factor usage frequency; factor failure and conflict frequency summed over weeks
- strategy x regime and factor x regime matrices (regime defaults to UNKNOWN)
- risk-adjusted block: monthly PnL, weekly-return Sharpe, max drawdown (worst
  weekly drawdown), Calmar (PnL / worst drawdown)
- execution costs: fees, funding, slippage, turnover, capital efficiency. Each is
  `{"availability": AVAILABLE|NOT_AVAILABLE, "value"}` - absent inputs are labeled
  NOT_AVAILABLE, never invented
- factor stability: max-min spread of weekly quality scores
- redundancy indicators: factors used every observed week (>= 2)
- confidence calibration merged from weekly buckets

## Recommendation outputs (proposal-only)

Factor proposals are one of `KEEP`, `INCREASE_WEIGHT_CANDIDATE`,
`DECREASE_WEIGHT_CANDIDATE`, `FREEZE`, `RESEARCH`, `CHALLENGE`,
`RETIRE_CANDIDATE`, `COMBINE_CANDIDATE`; every proposal carries
`proposal_only: true` plus its numeric basis. Strategy proposals derive from mean
weekly quality (`KEEP` positive / `DECREASE_WEIGHT_CANDIDATE` negative /
`RESEARCH` zero).

These are review artifacts. They must never mutate FactorSetVersion ACTIVE,
production strategies, RiskEngine, or TradingEngine.

## Tests lock

Month boundary, February, leap-year February, missing/duplicate weekly handling,
deterministic aggregation, proposal-only enforcement, and unchanged ACTIVE
factor set: see tests/evolution/test_hierarchical_service.py.
