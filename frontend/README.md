# 中文量化交易控制台

以 Kalshi 简洁工作区为设计参考的 React + TypeScript PAPER 交易终端。

## Current scope

- 五个中文一级入口：交易、持仓、订单、复盘、系统。
- 默认交易页以 BTCUSDT 行情、K 线区域、系统判断、仓位、盈亏和风险为中心。
- REST refresh for core state plus `/market`, `/market/sources`, `/signals`, `/strategies`, `/risk`, reviews and learning.
- WebSocket reconnect followed by REST resynchronization.
- Official `lightweight-charts` v5 candlestick and volume renderer.
- No fabricated market, position, order, risk or performance data.
- No frontend trading decisions or execution authority.
- Sensitive actions fail closed.
- Cloudflare Workers Static Assets deployment configuration.

## Commands

```sh
npm install
npm run dev
npm test
npm run build
```

The development server proxies the configured default local API and WebSocket to avoid changing
the backend CORS policy. Production hosting must provide an equivalent same-origin proxy or allow
the configured origins explicitly.

## Kline integration gate

The current backend does not expose `GET /market/klines` or structured `kline` WebSocket events.
The chart therefore renders `K线接口尚未开放`; it never generates sample or random candles.
The exact required contract is recorded in `../BACKEND_INTEGRATION_ISSUE.md`.

Cloud integration remains deferred until Harness provides:

- `CODEX_CLOUD_HANDOFF.md`
- `codex-cloud-handoff.json`
- the deployed OpenAPI contract
- a reachable Cloudflare Access-protected TESTNET backend
- authorization rules proving the Codex service token is GET-only

After those artifacts exist:

1. Read URLs and deployment metadata from `codex-cloud-handoff.json`; never hardcode temporary URLs.
2. Generate the TypeScript client from the real OpenAPI document.
3. Add the server-side Access proxy if required; never expose service-token values through `VITE_*` variables.
4. Implement WebSocket recovery as disconnect → reconnect → REST resync → resume.
5. Bind each page to backend truth and test loading, empty, error, stale and disconnected states.
6. Run real-cloud GET smoke tests and verify sensitive POST requests return `403`.

The current Content Security Policy uses `connect-src 'self'` and must only be widened to contract-provided API and WebSocket origins.

## Provenance

The architecture was informed by a task-specific, unverified DesktopGPT candidate. Codex rewrote and validated the implementation locally; no third-party repository source code was copied.
