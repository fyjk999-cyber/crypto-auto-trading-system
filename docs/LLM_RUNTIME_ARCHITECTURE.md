# LLM Provider Runtime Architecture

Phase 8D-1.5 adds one shared `LLMGateway`; it is infrastructure, not a fourth
Brain.  Provider selection is route based, so production callers never embed a
vendor model name.

```text
Live Trading Brain ───────┐
Daily Learning Brain ─────┼──> LLMGateway -> ModelRoute -> OpenAI-compatible provider
Evolution Brain ──────────┘       |                |
                                  |                +-> OpenAI / DeepSeek / Custom endpoint
                                  +-> encrypted SecretStore, retry, circuit breaker, usage audit
```

The six explicit routes are `live_analysis`, `daily_review`,
`daily_lesson_extraction`, `evolution_research`, `evolution_hypothesis`, and
`evolution_candidate_reasoning`.

Above those base-model routes sits the versioned Domain Model layer:
`CryptoTrader-Live-v1`, `CryptoTrader-Learning-v1`, and
`CryptoTrader-Evolution-v1`. These profiles are constrained reasoning contracts
for the three existing brains, not additional brains or provider models. See
[`DOMAIN_MODELS.md`](DOMAIN_MODELS.md).

## Safety boundaries

The Live route is adapted into the existing Chief Trader decision interface.
Any candidate SignalIntent still goes through the existing RiskEngine,
ExecutionAuthority, OrderManager, PAPER adapter, ledger, and portfolio path.
The gateway has no ExchangeAdapter, order-manager, or execution dependency.

If Live LLM analysis is unavailable or invalid, the existing Chief Trader
fail-safe yields no new entry. Position risk monitoring, reduce/exit logic,
reconciliation, the ledger, and the kill switch remain outside this dependency.

Daily reasoning occurs before the daily review is persisted. An unavailable or
invalid result raises a retryable error, preventing a partial semantic lesson
commit. Exact PnL, fills, balances, timestamps and factor values remain
deterministic. Evolution uses the gateway only to make proposals; a failed
request returns no proposal and cannot mutate a champion or protected core.

## Runtime configuration

`build_system()` creates exactly one `LLMGateway`, then injects that same
instance into the Live adapter, DailyReviewScheduler, ResearchGateway, API
state, and RuntimeBundle. It loads empty configuration successfully: a process
can start as `NOT_CONFIGURED`, and configuration reloads after provider/route
saves without a restart.

Provider and route metadata are persisted through `LLMRepository`. The
`0016_llm_runtime` migration creates `llm_providers`, `llm_routes`, and
`llm_usage`.
