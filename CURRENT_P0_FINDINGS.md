# CURRENT P0 FINDINGS

- Stale data survival: previously engine kept old orderbook when adapter fetch failed.
  Fixed: explicit book.invalidate() and strategy context returns None.
- New-risk checks: centralized in market_data/new_risk_gate.py.
- Market HEALTHY: canonical MarketState.health from required sources; generation invalidates on failure.
- Frontend reads /market and /market/sources; backend now returns new_risk_allowed and reason.
- CrossExchangeGuard: added SAME_EXCHANGE mode with stale/spread/slippage rejection.
