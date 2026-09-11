# Trigger / Context contract (G10)

Single canonical entry points (no module may invent its own context):

```python
TriggerSignature.from_factor_states(factor_states, as_of=...)
ContextSignature.from_market_state(market_state, as_of=..., symbol=...)
```

## TriggerSignature

`factor_states` items: `factor_id`, `state`, `definition_version`,
optional `observed_at`.

Rules:

* factor ids/states are normalized to upper case; **definition versions are
  identifiers and are preserved exactly** (case included);
* missing state or definition version → `UNKNOWN`;
* duplicate factor with conflicting state/version → the factor is degraded to
  `UNKNOWN` and listed in `conflicts`;
* `complete` is false when any factor is unknown/conflicting;
* `signature_hash()` is deterministic and order-independent;
* a card does not require every current factor; all card factors must match
  current factors exactly (state + definition version) for a hard match.

## ContextSignature

Fields: `symbol`, `instrument_class`, `regime`, `trend_state`,
`volatility_state`, `liquidity_state`, `direction`, `timeframe`, `as_of`.

Rules:

* missing/blank values are `UNKNOWN`, never inferred from another field;
* `unknown_fields` lists them explicitly;
* `to_json()` includes the schema version and `as_of`;
* same factor trigger with different regime produces different applicability.

## Applicability rules

`evaluate_hard_applicability()` returns `ApplicabilityResult(allowed,
reasons, field_results)`:

| Situation | Result |
| --- | --- |
| card factor missing from current | `FACTOR_NOT_OBSERVED:<id>` |
| current factor state UNKNOWN | `FACTOR_STATE_UNKNOWN:<id>` |
| card factor state UNKNOWN | `CARD_FACTOR_STATE_UNKNOWN:<id>` |
| state differs | `FACTOR_STATE_MISMATCH:<id>` |
| definition version unknown | `FACTOR_DEFINITION_UNKNOWN:<id>` |
| definition version differs | `FACTOR_DEFINITION_INCOMPATIBLE:<id>` |
| card context field specific, current UNKNOWN | `CONTEXT_UNKNOWN:<field>` |
| both known and differ | `CONTEXT_MISMATCH:<field>` |
| card field UNKNOWN | `WILDCARD` (lower scope score) |
| symbol not in card scope | `SYMBOL_MISMATCH` when policy requires, else `CROSS_SYMBOL` |
| card `known_at > as_of` | `FUTURE_KNOWN_AT` |
| legacy card without trigger | `GENERAL_FALLBACK` (policy gated, penalized) |

No factor-specific card is created automatically: one card can reference many
factors; “one factor = one card” is forbidden.

Tests: `tests/growth_system_v2/test_trigger_context.py`,
`tests/growth_system_v2/test_card_retrieval.py`.
