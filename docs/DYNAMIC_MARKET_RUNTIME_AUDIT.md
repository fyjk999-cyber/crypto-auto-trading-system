# DYNAMIC MARKET RUNTIME AUDIT

- Generated: 2026-08-30T01:16:50.898387+00:00
- DB: data/crypto_trader.db (read-only)

## Registry
- Total: 2029
- SPOT: 1383
- SWAP: 459
- FUTURES: 187
- OPTION rows: 0 (option underlyings are counted but not persisted row-by-row)
- MARGIN rows: 0
- Live: 2028
- Preopen: 1
- Delisted: 0
- Last refresh: 2026-08-29T17:12:04.797598+00:00

## Runtime consumption
- Runtime currently imports registry: NO (grep shows market_registry used only by tests/refresh)
- ChiefTrader runtime universe: strategy ticks are symbol-scoped; no fixed-30
  constants found in src. Market universe discovery is not yet driven by
  okx_instruments at runtime.
- Execution universe: execution_symbols module still owns paper-perp mapping.

## Gap
- DYNAMIC_MARKET_UNIVERSE = PARTIAL

## Update 2026-08-30T03:05Z (P2-1 Phase 3 wiring)
- Runtime now imports the registry: YES — bootstrap builds
  DynamicMarketUniverse(okx_public_data client) + HierarchicalMarketObserver
  + OKXTickerWsManager when scanner_enabled; wired into TradingEngine (tick
  poll) and MultiSymbolChiefTraderStrategyAdapter (advisory evidence +
  dynamic rotation).
- Layer-1: one batch tickers call per product class (SPOT+SWAP), throttled
  60s, stale-marked on failure (STALE freshness, last_error recorded, never
  fabricated).
- Layer-2: bounded WS candidate stream (<=50 instruments) with REST-batch
  fallback (observer.source WS/FALLBACK).
- Candidate selection: FACTUAL ONLY (pinned held+core instruments, then top
  24h notional volume). No composite score, no opportunity gate — advisory
  evidence for the Chief Trader LLM (deep_analysis_candidate_limit from the
  hot policy).
- Dynamic rotation: core configured symbols ALWAYS retained first; dynamic
  candidates appended, rotation bounded at 40 symbols; per-symbol decision
  cooldown (hot policy) bounds LLM burn.
- Observability: GET /runtime now exposes market_observer summary
  (breadth/candidates/freshness/source).
- DYNAMIC_MARKET_UNIVERSE = WIRED (live verification follows restart).
