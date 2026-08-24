# Market UI readability and exchange-entry report

## Verification reference

Final SHA: run `git rev-parse HEAD` after checkout to obtain the immutable
delivery revision for this report.

## Delivery status

| Area | Result |
| --- | --- |
| Binance market source UI | PASS — `Binance USDⓈ-M` is explicit on the trading page and top bar. |
| Binance Kline | BACKEND_UNAVAILABLE — existing `/market/klines` remains the only source; no synthetic candle or browser bypass was added. |
| Binance real-time WebSocket | BACKEND_UNAVAILABLE — the existing backend WebSocket remains the sole UI path. |
| OKX execution UI | PASS — System page identifies `OKX` and `模拟盘 DEMO`. |
| OKX credential form | PASS — password fields are shown only after `配置 API`. |
| OKX backend credential endpoint | BACKEND_BLOCKED — no credential endpoint appears in the current OpenAPI document. See `BACKEND_INTEGRATION_ISSUE.md`. |
| Client-side secret storage | NO — no `localStorage`, `sessionStorage`, or IndexedDB usage was added. |
| Secrets committed | NO — staged-diff secret scan is required before publishing. |
| Global font scale | PASS — shared CSS font variables set minimum user-facing size to 12px. |
| Navigation | PASS — 15px minimum. |
| Panel titles | PASS — 17px. |
| Tables | PASS — 13px headers and 15px body. |
| Desktop QA | PASS — browser-checked source labels, OKX card, and non-overlapping controls. |
| 390px mobile | PASS — component regression test retains the main market/decision/K-line regions. |
| Existing Kline path | PASS — `/market/klines` hook and WebSocket incremental update are unchanged. |
| Backend trading core modified | NO |
| Cloud | DEFERRED |
| `LIVE_TRADING_ENABLED` | `false` — unchanged. |

## Test gates

- `npm test`
- `npm run typecheck`
- `npm run build`
- full backend `pytest`

## Safety boundary

The frontend does not call Binance directly, does not use private Binance APIs,
does not contain an OKX LIVE selector, and does not send, persist, log, or
return OKX credentials. Backend-owned encryption, status, and validation are
documented but not invented in the UI.
