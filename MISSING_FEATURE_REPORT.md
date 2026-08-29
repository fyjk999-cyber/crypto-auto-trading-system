# MISSING FEATURE REPORT

- Updated: 2026-08-29T00:40:00+00:00 (PAPER trade funnel audit loop)

## FIXED in the AI-FIRST diagnose/repair loop (2026-08-29)

1. Silent decision stall after restart — `GatewayProviderAdapter.healthy()`
   required in-process gateway health == HEALTHY; UNVERIFIED (fresh process)
   blocked every decision with no logs. healthy() now = route/provider/secret
   resolvable. (llm_runtime/gateway.py)
2. Live Domain Prompt described the AI as a read-only analyzer
   ("Never execute actions", reasoning_policy evidence-bound-no-execution-v1);
   render_prompt was never sent (ChiefTraderEngine prefers
   complete_domain_analysis). CryptoTrader-Live now ships
   live-prompt-v2-ai-first with explicit entry decision authority.
   Learning/Evolution unchanged. (llm_runtime/domain_models.py)
3. Quant hard gates violating AI-FIRST removed from the Live entry path:
   pre-LLM INSUFFICIENT_STRATEGY_EDGE fit gate, post-LLM confidence veto,
   UNKNOWN-regime block. Fit/confidence/regime are prompt evidence now.
   Real missing context (FactorSnapshot / StrategyEvidence) still fails
   closed. (runtime/chief_trader_strategy.py)
4. Fake fill price: SimulatedExchangeAdapter._match_order eagerly re-seeded
   the synthetic mid=100 book on every match, clobbering real refreshed
   books; every paper SPOT fill executed at ~100.05. Fixed; the real-market
   adapter refreshes from real OKX before matching and fails closed when
   the real reference price is unavailable. (simulator/exchange.py,
   simulator/real_market_paper.py)
5. Reconciliation halt forever after restart: the paper exchange's
   in-memory state reset while the ledger persisted → BALANCE/POSITION
   MISMATCH → RECONCILIATION_HALT held all execution. The adapter now
   hydrates from the ledger projection at startup. (runtime/engine.py)
6. Pre-authorization orderbook refresh used the execution symbol for
   perpetual signals — now resolves to the reference market. (engine.py)
7. GET /trading-funnel: read-only funnel counters (decisions by
   action/class/reason, llm per-route, risk, authority, orders, fills).

## OPEN (documented follow-ups; none block the first-fill goal)

1. Multi-symbol PERPETUAL registry: only BTCUSDT maps to a paper perpetual
   contract; AI SHORT proposals on other symbols are correctly rejected by
   SPOT_OVERSHORT. A generic multi-symbol perpetual resolver is needed for
   symmetric 20-symbol bidirectional learning data.
2. MAE/MFE tracking: tick-level excursion capture not implemented;
   analytics report NOT_AVAILABLE.
3. Funding scheduling: apply_funding exists but no runtime scheduler runs it
   periodically; FUNDING_RUNTIME_APPLICATION = PARTIAL.
4. Stale-lease UX: a SIGKILLed engine leaves the runtime_leases row valid
   until TTL expiry; startup refuses with LeaseNotHeld until then.
5. tests/local_stability/test_market_semantics.py: two tests make LIVE OKX
   calls and assert fixed fixture values; they fail wherever OKX is
   reachable and need proper feed mocking.

## Historical entries

- Updated: 2026-08-26T05:08:06.826548+00:00
- 90-day real forward shadow evidence: not yet elapsed.
- Real LLM configuration: external.
- Full TradingEngine live-loop deployment wiring: canonical bootstrap integration
  tests pass; production supervisor activation remains operational step.
