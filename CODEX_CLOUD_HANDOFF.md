# CODEX CLOUD HANDOFF

- Environment: TESTNET
- API Base URL: <set after deploy>
- WebSocket URL: <set after deploy>
- OpenAPI URL: <set after deploy>
- Swagger URL: <set after deploy>
- Git SHA: 0dc4884ae3e416dc1df22f96620f55e8e4f41734 (pre-cloud code baseline)
- Cloudflare Access required: yes (service token)
- Codex token header names: CF-Access-Client-Id, CF-Access-Client-Secret
- Read-only endpoints: GET /api/v1/*, HEAD /api/v1/*, /openapi.json, /docs
- Control endpoints are denied for Codex.
- WebSocket events: market, regime, signal, position, margin, order, fill, PnL, risk, review, alert, runtime, exchange-health.
- Frontend constraints: Codex may call read APIs and WebSocket; no direct trading-core imports required.
- Real secrets must never be embedded; use environment variables.
