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
