# OKX Public Kline Switch — Final Report

## Scope

- Visible frontend candles now use OKX's unauthenticated public endpoint:
  `GET /api/v5/market/candles` with `BTC-USDT-SWAP`.
- `KLINE_PROVIDER=OKX` is the default. The existing Binance market-data and strategy
  provider are unchanged; their `GEO_RESTRICTED` state remains independently visible.
- No credentials, synthetic candle fallback, trading calls, or frontend direct WebSocket
  connection were added.

## Contract

- Intervals map as required: `1m`, `5m`, `15m`, `1H`, `4H`, `1D`.
- Responses are normalized to the existing candle shape, deduplicated by open time, and
  returned chronologically. OKX failures return `source=OKX`, `status=UNAVAILABLE`, and
  an empty candle list.
- The trade-page header reads `行情源：OKX · 实时` after a healthy candle response;
  the system page separates `K线行情 OKX 实时`, Binance state, and OKX Demo status.

## Verification

- `8 passed`: `tests/local_stability/test_market_semantics.py`
- `17 passed`: `frontend/src/App.test.tsx`
- `npm run typecheck` and `npm run build` passed.
- `ruff check src tests` and `git diff --check` passed.
- Live, unauthenticated OKX request returned 9-field candles. The local API and Vite proxy
  both returned HTTP 200 with `source=OKX`, `status=HEALTHY`, and `BTC-USDT-SWAP`.

Browser interaction was not used to bypass the in-app browser URL policy after its reload
was blocked; the Vite proxy and frontend unit rendering test provide the local UI evidence.
