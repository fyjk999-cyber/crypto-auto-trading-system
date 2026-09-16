# Legacy LLM isolation and extraction call graph

**Audit baseline:** `115571c` (Low-Risk V2 working tree)
**Scope:** original/pre-Low-Risk-V2 LLM call paths only.  This document does
not classify a module by its directory name; classification follows its actual
provider construction and runtime wiring.

## Classification

| Classification | Caller and method | Provider/network boundary | Input | Output | Downstream consumer | Runtime status |
| --- | --- | --- | --- | --- | --- | --- |
| LEGACY | `deepseek.client.DeepSeekClient._chat` | direct `httpx.AsyncClient` → DeepSeek `/chat/completions` | free-form prompt | JSON text, then `MarketOpinion` / `CapitalReview` | no source production caller; unit-only references | guarded by `LEGACY_LLM_ENABLED` |
| LEGACY | `llm_runtime.executor.LLMExecutor.execute` | injected object's `complete_json()` | free-form prompt | untyped `dict` | no source production caller; unit-only references | guarded by `LEGACY_LLM_ENABLED` |
| LEGACY, dormant decision utility | `deepseek.decision_engine.fuse_quant_deepseek` | none | quant direction plus optional legacy opinion | `FusedDecision` | no source production caller; unit-only references | **unsafe if reactivated:** absent opinion becomes `QUANT_ONLY` |
| LEGACY, dormant review utility | `deepseek.risk_committee.apply_capital_review` | none | requested size/leverage plus optional review | `CommitteeResult` | no source production caller; unit-only references | **unsafe if reactivated:** absent review applies a deterministic adjustment |
| LEGACY, mislabeled deterministic utility | `deepseek.market_selector.DeepSeekMarketSelector.rank` | none | candidate facts | ranked `CoinScore` values | no source production caller; unit-only references | no network call despite name |
| LOW_RISK_V2 | `llm_chief.engine.ChiefTraderEngine.decide` and `select_tools` | `CoreLLMRouter` → `DeepSeekProvider` → optional `GLMProvider` | canonical `ChiefTraderContext` | validated `ChiefTraderDecision` | `LiveLLMDecisionStrategy`, `LiveLLMPositionManager` | **excluded from this switch** |
| LOW_RISK_V2 | `llm_chief.failover.CoreLLMRouter.complete_json` | primary `complete_json`, then only a freshly rebuilt backup prompt | rendered canonical prompt + state version | `LLMResponse` with provider/state binding | `ChiefTraderEngine` | **excluded from this switch** |
| LOW_RISK_V2 | `llm_chief.provider.DeepSeekProvider.complete_json` | `httpx.AsyncClient` → configured DeepSeek OpenAI-compatible endpoint | canonical JSON prompt | parsed `LLMResponse` | `CoreLLMRouter` | **excluded from this switch** |
| LOW_RISK_V2 | `llm_chief.provider.GLMProvider.complete_json` | `httpx.AsyncClient` → configured GLM endpoint | freshly rebuilt canonical JSON prompt | parsed `LLMResponse` | `CoreLLMRouter` | **excluded from this switch** |
| LOW_RISK_V2 | `api.deps.LLMRuntimeStatus.probe` | canonical `DeepSeekProvider.complete_json` | fixed health prompt | provider health state | `/llm/health` | **excluded from this switch** |
| SHARED, evidence-only | `llm.tools.*`, `llm.context` | none | factual market/factor/growth data | tool evidence/prompt text | ChiefTrader tool registry | no provider dependency |
| SHARED, legacy bridge | `runtime.ai_position_bridge.AIPositionRuntimeBridge` | none in source | AI brain intent | runtime signal mapping | not installed in official bootstrap | no provider dependency in source |

## Verified production construction points

`runtime.bootstrap.build_system()` creates the **Low-Risk V2** router:

```text
DeepSeekProvider + optional GLMProvider
    → CoreLLMRouter
    → ChiefTraderEngine
    → LiveLLMDecisionStrategy / LiveLLMPositionManager
```

It does **not** construct `DeepSeekClient` or `LLMExecutor`.  The legacy
direct DeepSeek client therefore has no current source-level production caller.
The legacy gate deliberately must not alter this V2 construction.

## Hidden-coupling findings

1. `LLMExecutor` accepts an arbitrary provider object.  Without the new gate,
   any future caller can make an untracked LLM network request through
   dependency injection.
2. `fuse_quant_deepseek()` promotes quant direction when the legacy opinion is
   missing.  It is dormant today, but must be removed from any future entry
   path or changed to `NO_DECISION` before reactivation.
3. `apply_capital_review()` modifies requested size/leverage in the absence of
   an LLM review.  It is dormant and must remain outside canonical risk
   authority; canonical `RiskEngine` owns approve/scale-down/reject.
4. The official bootstrap is already coupled to the V2 Core Decision Port in
   practice, but provider-specific types are centralized in
   `llm_chief.provider` / `llm_chief.failover`, not in market, risk, execution,
   persistence, or Growth.

## Zero-network experiment boundary

With `LEGACY_LLM_ENABLED=false`, every guarded legacy call stops before
constructing an HTTP client or calling an injected provider.  The
`LegacyLLMInvocationTracker` records only caller labels and counts:

```text
LLM_PROVIDER_CALLS = 0
DEEPSEEK_REQUESTS = 0
GLM_REQUESTS = 0
OTHER_LEGACY_LLM_REQUESTS = 0
```

It never stores prompts, response content, headers, keys, or provider URLs.
The test suite also replaces the HTTP client/provider with fail-on-use sentinels
to prove that disabled code cannot reach a network boundary.

## Current architecture and target boundary

```text
CURRENT (two eras)
legacy DeepSeekClient / LLMExecutor (dormant) ─── direct provider boundary
Low-Risk V2 llm_chief ─────────────────────────── CoreLLMRouter → providers

TARGET (in-process logical extraction)
market + scanner + factors + growth + risk + execution
                     ↓
             CoreDecisionPort
                     ↓
        CoreLLMRouter / provider adapters
                     ↓
              DeepSeek / GLM
```

`CoreDecisionPort` should expose only `decide(request)`,
`reassess(request)`, and `health()`.  Domain/risk/execution code must consume
validated domain decisions, not SDK objects, API URLs, API keys, retry policy,
or provider response classes.

## Migration plan

1. Keep the legacy switch permanently while the original modules remain.
2. Block any new runtime import of `crypto_trader.deepseek.client` or
   `crypto_trader.llm_runtime.executor` with an architecture test.
3. Before reusing a legacy utility, move it behind `CoreDecisionPort` and make
   missing/unavailable decisions fail closed (`NO_DECISION`/`WAIT`), never
   `QUANT_ONLY`, BUY, SELL, or cached-entry reuse.
4. After no callers remain and historical compatibility is retired, delete the
   legacy layer in a separately approved change.  Do not turn it into a
   separate service until a measured operational need justifies the added
   failure modes.
