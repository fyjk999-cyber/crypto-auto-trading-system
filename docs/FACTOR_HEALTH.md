# FACTOR HEALTH

Status: implemented and tested (`tests/factors/test_factor_health.py`).
Introduced 2026-08-27 by the three-brain support workstream.

## Historical note (truthful provenance)

A canonical `src/crypto_trader/factors/health/` package **did not exist before
this workstream**. Prior state carried only:

- inline status strings inside the capture/tool-gateway path, and
- a lifecycle class named `FactorHealth` inside `models.py` with different
  semantics.

This document describes the newly established package. Earlier docs that imply a
pre-existing health module are outdated on this point.

## States

`factors/health/states.py`

| State | Meaning | Usable for decisions? |
|---|---|---|
| `OK` | value computed, normal confidence | yes |
| `VALID_ZERO` | real `Decimal(0)` value with positive confidence | yes |
| `MISSING_DATA` | no book / no trades / empty metadata | no |
| `INSUFFICIENT_HISTORY` | warm-up window not yet satisfied | no |
| `STALE_INPUT` | inputs older than freshness bounds | no |
| `CALCULATION_FAILED` | computation raised or returned non-numeric | no |
| `DISABLED` | factor explicitly disabled by configuration | no |

Structural rule: `VALID_ZERO` is distinct from failure. Zero is a legitimate
observed value; failed/missing factors must never be represented as zero entries.

`USABLE_STATES = (OK, VALID_ZERO)`; `is_usable(state)` answers the same question.

## Assessment

`factors/health/assessment.py`

- `FactorHealthAssessment(factor_name, state, detail)`: frozen record; validates
  the state string at construction.
- `report_from_legacy_result(result)`: maps legacy `FactorResult` shapes to health:
  - `NO_BOOK` / `NO_TRADES` metadata -> `MISSING_DATA`
  - confidence <= 0 -> `MISSING_DATA`
  - real `Decimal(0)` with confidence > 0 -> `VALID_ZERO`
  - non-Decimal / None value -> `CALCULATION_FAILED`
- Convenience constructors: `failure_assessment`, `insufficient_history_assessment`,
  `stale_input_assessment`.

## Capture integration

`factors/capture.py`

- Group-isolated computation: each factor group is wrapped in try/except;
  exceptions are recorded into `__init__.last_calculation_errors`, never swallowed.
- A group crash cannot erase other groups' results.

## Snapshot / tool gateway path

`factors/tool_gateway.py`

- Unusable factors land in `failed_factors` plus `calculation_warnings`
  formatted `factor:STATE[:detail]`.
- Failed factors produce **no fabricated snapshot entry**.
- Factors absent from output due to insufficient warm-up are marked
  `INSUFFICIENT_HISTORY`.
- If capture itself raises, the whole snapshot fails loudly (all expected ids in
  `failed_factors`) instead of emitting partial fabricated data.

Downstream consumers check `is_usable(state)` instead of guessing from values.
