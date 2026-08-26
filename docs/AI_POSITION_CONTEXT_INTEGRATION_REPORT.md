# AI POSITION CONTEXT INTEGRATION REPORT

- Updated: 2026-08-26T14:59:06.691937+00:00
- Bridge now computes current_price from market_data orderbook mid when available.
- LONG/SHORT unrealized PnL computed from current price, entry price, abs qty.
- Realized PnL from portfolio position.
- Position age still 0 until persisted opened_at is available (documented gap).
- Factor/regime wiring remains opt-in via factor_intelligence_provider.
