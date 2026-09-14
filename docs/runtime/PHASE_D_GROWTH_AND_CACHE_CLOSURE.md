# Phase  Growth Utilization and DeepSeek Prompt Cache Closure

## 1. Three independent observability systems

These metrics are deliberately separate and must never be merged into one
"cache hit rate":

| System | Authority | API |
|---|---|---|
| Market Data Cache | `market_data/cache.py` | `GET /market-intelligence/cache` |
| DeepSeek Prompt Cache | `llm_chief/provider.py` | `GET /llm/prompt-cache` |
| Growth Experience Retrieval | `learning/growth_card_retrieval.py` | `GET /growth/experience-metrics` |

`market_data_cache_hit_rate` is about OHLC/quote payload reuse.
`deepseek_prompt_cache_hit_rate` is about provider prompt-prefix reuse.
`growth_experience_retrieval_hit_rate` is about factual cards selected for a
decision.  Matching one never proves another.

## 2. DeepSeek prompt cache formula

Official formula:

```text
deepseek_prompt_cache_hit_rate
  = prompt_cache_hit_tokens
    / (prompt_cache_hit_tokens + prompt_cache_miss_tokens)
```

Rules:

- provider fields missing -> `status = UNKNOWN`, tokens = null, rate = null;
- `hit + miss == 0` -> `UNKNOWN`, never `0%`;
- zeros reported by the provider are real observations, not UNKNOWN;
- metrics are grouped by operation (`market_selection`, `tool_selection`,
  `trading_decision`, `position_review`, `growth_review`) and overall.

`GlobalLLMBudget.snapshot()["prompt_cache"]` mirrors the same formula for
budgeted calls.  `GlobalLLMBudget` never owns direction, risk, sizing or
execution authority.

## 3. Prompt prefix optimization

`ChiefTraderEngine.render_prompt()` is split into:

1. a stable static instruction prefix (identity, action contract, output
   contract, authority/safety text);
2. a `--- DYNAMIC CONTEXT ---` payload (symbol, regime, market snapshot,
   evidence, portfolio, cards, timestamps).

The static prefix is byte-identical across symbols and market snapshots for a
given position state.  The refactor changes serialization order only; allowed
actions, risk semantics, evidence authority and fail-closed behavior are
unchanged.

## 4. Growth card lifecycle

```text
factual episode
  -> structured causal review
  -> lesson / proposition / pattern (sample_count >= min_pattern_samples)
  -> pattern-derived card proposal
  -> quality gate
  -> CANDIDATE | ACTIVE | WATCH | STALE | RETIRED
  -> retrieval with trace-before-use
  -> decision evidence
  -> outcome attribution / KEEP | UPDATE | WATCH | RETIRE
```

Promotion is factual only:

- Pattern -> Card requires real `ReviewAttempt` rows, provenance refs,
  complete factual trigger factors and the existing quality thresholds.
- Missing review evidence gives evidence quality `0.0`; a card stays
  CANDIDATE.
- Empty or UNKNOWN trigger metadata is never fabricated; absent
  `detector_version` stays UNKNOWN and keeps the card CANDIDATE.
- CANDIDATE cards are not retrievable by the Chief.
- `min_pattern_samples`, `proposition_identity()`, quality thresholds, Risk,
  Sizer and Execution authority are not changed by this phase.

## 5. Growth retrieval metrics semantics

`GET /growth/experience-metrics` returns:

```text
growth_experience_cards_available
growth_experience_retrieval_calls
growth_experience_retrieval_hits
growth_experience_retrieval_misses
growth_experience_retrieval_hit_rate
growth_cards_candidates_seen
growth_cards_filtered
growth_cards_selected
growth_card_refs_returned
growth_card_refs_cited_by_decisions
growth_decisions_with_card_evidence
growth_decisions_without_card_evidence
growth_card_trace_attach_success
growth_card_trace_attach_failure
growth_decision_utilization_rate
exclusion_reason_counts
```

`retrieval_hit_rate` denominator is only calls that actually executed the
`experience_cards` tool.  If no eligible call exists, the API returns
`status = UNKNOWN`, `reason = NO_ELIGIBLE_CALLS`, not `0%`.


## 5a. Exact-proposition recall for natural recurrence

`proposition_identity()` is deliberately unchanged.  To let independent
factual episodes reinforce the same proposition, the structured review now
receives a bounded `KNOWN_PROPOSITIONS` block containing only existing exact
propositions for the same account/mode/symbol/regime/direction.

Prompt rule (`growth-review-prompt-v2`):

- if the current episode's own evidence supports exactly one known
  proposition, reuse its statement exactly as written;
- otherwise write a new testable statement;
- a reused statement still requires this episode's `ALLOWED_REFS`, so recall
  never weakens evidence validation, `min_pattern_samples`, quality gates or
  card promotion.

This changes recall context only.  No threshold, identity function,
proposition key, risk, sizer or execution rule is modified.

## 6. Runtime acceptance

Code-level acceptance requires:

- provider hit/miss parsing and UNKNOWN semantics;
- durable-in-process per-operation metrics;
- static prefix stability tests;
- Growth utilization metrics from durable traces;
- trace-before-use tests;
- Mission C lifecycle/risk/execution regressions green.

Natural runtime acceptance waits for:

- an ACTIVE/WATCH card and a matching factual context (Growth retrieval);
- real provider responses with prompt-cache usage fields.

No forced trade, fake episode, fake card or threshold weakening is permitted
to accelerate either condition.

## 7. Rollback

If Phase D causes LLM error/latency regressions, tool-selection failures,
position-review starvation, Risk/Execution regression or duplicate learning,
stop the candidate runtime and return to the last Mission C accepted SHA.
Factual trade and growth rows are never deleted as part of a code rollback.
