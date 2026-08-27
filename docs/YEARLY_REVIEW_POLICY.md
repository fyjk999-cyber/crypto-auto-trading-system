# YEARLY REVIEW POLICY

Status: implemented (`HierarchicalLearningEngine.yearly_review`). Year-window
selection lives in docs/REVIEW_PERIOD_POLICY.md; this document covers aggregation
semantics only.

## Input

Completed `MonthlyReviewResult` payloads for all twelve months of the previous
completed UTC calendar year. Missing months warn; duplicates collapse per month
label.

## Aggregations

- annual return: sum of monthly PnL
- Sharpe / Sortino over the monthly series (>= 2 months required)
- Calmar (annual total / worst monthly drawdown) and max drawdown
- tail risk: worst single month
- lesson confirmation / rejection rate across all months
  (`INSUFFICIENT_EVIDENCE` when no resolved lessons exist)
- strategy and factor lifespan (first month, last month, month count)
- version lineage entries whenever a month carries version identifiers
- factor reliability trend and redundancy trend by month
- evolution pipeline statistics (candidate/validation/promotion/rejection/
  rollback/research-success) summed only when monthly inputs carry them
- complexity growth: strategy/factor evaluation counts per month

## Availability semantics

Unavailable metrics are explicitly labeled, never fabricated:

- `NOT_AVAILABLE`: inputs for a metric were entirely absent
- `INSUFFICIENT_EVIDENCE`: inputs exist but are insufficient to compute
  (e.g. fewer than two monthly points)
- `AVAILABLE`: computed normally

The `metric_availability` map records the label per metric.

## Proposal outputs

Yearly reviews emit architecture / research-policy / complexity-reduction
proposals (e.g. `FactorArchitectureProposal`) as data only. No automatic
production mutation occurs.
