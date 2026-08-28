# Domain Models Above Base LLM Providers

An OpenAI-compatible Provider Model is transport-level capability, such as
`DeepSeek / deepseek-chat`. A Domain Model is a constrained, versioned reasoning
profile that uses one configured base model through the canonical `LLMGateway`.
It does not introduce a Brain or a second provider client.

| Existing Brain | Domain Model | Routes | Structured output |
| --- | --- | --- | --- |
| Live Trading | `CryptoTrader-Live-v1` | `live_analysis` | `TradingAnalysisResult` |
| Daily Learning | `CryptoTrader-Learning-v1` | `daily_review`, `daily_lesson_extraction` | review and lesson schemas |
| Evolution | `CryptoTrader-Evolution-v1` | research, hypothesis, candidate reasoning | existing research schemas |

Each profile has independent prompt, context, factor, tool-policy, memory-policy
and output-schema versions, plus a bounded token budget and reasoning policy.
The Live profile accepts canonical read-only MarketSnapshot, FactorSnapshot,
FactorHealth, FactorProfile, PortfolioState, PositionState, RiskContext,
RelevantMemory and TradingRelease context. Its output is advisory only:
`TradingAnalysisResult -> Decision -> SignalIntent -> RiskEngine ->
ExecutionAuthority`.

The provider transport is unchanged. No profile can call an ExchangeAdapter,
submit/cancel an order, calculate ledger/PnL truth, change a champion, or promote
a candidate. `domain_model_version` is carried in decision metadata and can be
persisted in `DecisionEvidence`; migration `0017_domain_model_evidence` adds the
durable evidence column.
