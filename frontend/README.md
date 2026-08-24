# Trading Control Center frontend

React and TypeScript local control center for the PAPER trading system.

## Current scope

- Responsive local control-center pages backed by the FastAPI API.
- REST refresh for `/health`, `/ready`, `/runtime`, `/account`, `/positions`, `/orders`, and `/killswitch`.
- WebSocket reconnect followed by REST resynchronization.
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

## Integration gate

The following currently remain unavailable and intentionally render an honest backend-unavailable
state: `/regime`, `/signals`, `/strategies`, `/risk`, `/margin`, `/daily-reviews`, `/learning`,
and `/exchange-health`.

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
