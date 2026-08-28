# Phase 8D-1.5 LLM Runtime Audit

## Scope and safety baseline

Audit target: canonical `build_system(Settings)` runtime on `main`, base SHA
`ce4b709e9f317a133462a6c36c6e5b101b3980da`. The worktree already contains
uncommitted local PAPER/OKX/frontend corrections; they are preserved.

The runtime remains PAPER-only. LLM output is analysis infrastructure and cannot
call `ExchangeAdapter`, submit/cancel orders, bypass `RiskEngine`, bypass
`ExecutionAuthority`, mutate Ledger truth, or certify an Evolution candidate.

## Existing components

### AI interface and Live decision path

- `ai_interface/context_builder.py` builds typed analysis context but makes no LLM call.
- `llm_chief/provider.py` contains a narrow `LLMProvider` protocol and a DeepSeek-only
  client. It reads a raw environment key, hardcodes the endpoint/model behavior, has no
  persistence, routing, usage audit, circuit breaker, or hot reload.
- `llm_chief/engine.py` validates provider JSON into `ChiefTraderDecision` and fails safe
  to `NO_TRADE` when the provider is absent/invalid.
- `runtime/chief_trader_strategy.py` maps a validated decision to `SignalIntent`; the
  existing `TradingEngine` subsequently applies `RiskEngine`, `ExecutionAuthority`,
  `OrderManager`, adapter and Ledger boundaries.
- `runtime/bootstrap.py` currently constructs `ChiefTraderStrategyAdapter(provider=None)`.
  Therefore the Live LLM path is interface-only and not wired to a configured provider.

### Existing LLM runtime concepts

- `llm_runtime/executor.py` is only a small provider wrapper with a fail-safe decision.
  It is not a canonical gateway and has no route registry, persistence, audit, usage,
  retry policy, or circuit breaker.
- Literal provider/model configuration remains in the old DeepSeek provider.
- No production `LLMGateway`, provider registry, model router, semantic route table, or
  shared invocation audit exists.

### Daily Learning Brain

- `evolution/daily/pipeline.py` deterministically performs replay, error mining, factor
  attribution, pattern extraction and lesson construction.
- `governance/scheduler.py` loads durable trade memory and writes daily statistics.
- Exact PnL, timestamps, fills, balances and factors are deterministic and must remain so.
- No semantic review or lesson-extraction call is currently wired to a shared LLM.

### Evolution Brain

- `evolution/gateways/research_gateway.py` is the canonical research boundary and
  explicitly denies execution authority.
- Existing generation, materialization, validation and promotion components already
  exist under `evolution/`; they must be reused.
- Research/hypothesis/candidate semantic reasoning is not routed through a shared LLM.

### Runtime bootstrap

- `runtime/bootstrap.py::build_system()` is the single official constructor.
- It constructs one `TradingEngine`, one `AIPositionRuntimeBridge`, one
  `TradingRuntimeSupervisor`, existing safety services and the FastAPI `AppState`.
- LLM infrastructure must be added to this bundle once and injected into all three brains;
  it must not introduce another scheduler or engine.

### Configuration and secrets

- `Settings` uses Pydantic settings and `.env`.
- `credentials.py` provides atomic, chmod-600, gitignored local OKX credential storage,
  but it is provider-specific and plaintext-at-rest.
- Phase 8D requires a canonical LLM `SecretStore`; provider metadata/routes belong in the
  database while API keys must not be stored in plaintext DB rows.
- A local deployment master key plus authenticated encryption is appropriate; it must be
  gitignored, chmod 600, never returned, and never logged.

### Persistence and migrations

- SQLAlchemy async sessions support SQLite and PostgreSQL.
- Alembic is canonical, with current head `0015_hierarchical`.
- No LLM provider, route, secret or usage tables exist.

### API and frontend

- FastAPI routes currently have no `/llm` configuration namespace.
- The React/Vite frontend has five pages and safe password handling for OKX credentials.
- No LLM / AI Models page, provider status, route editor, usage summary, or actual provider
  test flow exists.

### Audit, retries and circuit breaking

- `AuditService` persists generic safe audit events.
- The old DeepSeek client has bounded loop retries but no typed error classification,
  rate-limit handling, exponential backoff, circuit state, or usage aggregation.
- No existing reusable circuit-breaker utility was found.

## Missing canonical pieces

1. Shared typed `LLMGateway` and OpenAI-compatible provider transport.
2. Durable provider metadata and route configuration.
3. encrypted restart-safe LLM secret store.
4. semantic model routes for Live, Daily and Evolution.
5. structured-output validation at the gateway boundary.
6. bounded timeout/retry/backoff/circuit breaker.
7. safe invocation usage/audit persistence and aggregation.
8. hot-reload configuration API and actual provider test.
9. real `build_system()` injection into all three brains.
10. frontend provider and route configuration flow.
11. manual real-provider qualification script.

## Reuse decisions

- Extend the existing `llm_runtime` package; do not create `llm_v2`.
- Keep `ChiefTraderDecision` and `ChiefTraderStrategyAdapter` as the Live structured
  decision boundary.
- Adapt the gateway to the existing `LLMProvider.complete_json` protocol for Live.
- Add optional LLM collaborators to the existing Daily pipeline and ResearchGateway;
  deterministic calculations and promotion gates remain authoritative.
- Reuse SQLAlchemy/Alembic, FastAPI `AppState`, `AuditService`, current frontend patterns,
  local `.env`/gitignore conventions and the single canonical bootstrap.

## Planned new components

- `llm_runtime/contracts.py`: provider/route/request/response/structured contracts.
- `llm_runtime/secrets.py`: encrypted local secret store.
- `llm_runtime/repository.py`: provider, route and usage persistence.
- `llm_runtime/provider.py`: OpenAI-compatible transport.
- `llm_runtime/gateway.py`: registry, router, retries, circuit breaker, validation and audit.
- one Alembic migration for LLM provider, route and usage metadata.
- FastAPI `/llm/*` endpoints and one frontend LLM page.
- `scripts/llm_runtime_qualification.sh` for post-key manual validation.

## Audit verdict before implementation

- Three brains exist as architectural systems: **YES**.
- Shared production LLM runtime: **NOT IMPLEMENTED**.
- Live LLM runtime wired: **NO** (`provider=None`).
- Daily LLM runtime wired: **NO**.
- Evolution LLM runtime wired: **NO**.
- LLM provider runtime validated: **NOT RUN**.
- 24-hour PAPER qualification: **NOT STARTED**.
