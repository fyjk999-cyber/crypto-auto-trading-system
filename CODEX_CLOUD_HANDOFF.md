# CODEX CLOUD HANDOFF

- Environment: TESTNET
- API Base URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/api/v1
- WebSocket URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/ws
- OpenAPI URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/openapi.json
- Swagger URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/docs
- Git SHA: 92320083378b229816114f639b29dea5f15b33dd
- Cloudflare Access required: yes (service token)
- Codex token header names: CF-Access-Client-Id, CF-Access-Client-Secret
- Read-only endpoints: GET /api/v1/*, HEAD /api/v1/*, /openapi.json, /docs
- Control endpoints are denied for Codex.
- WebSocket events: market, regime, signal, position, margin, order, fill, PnL, risk, review, alert, runtime, exchange-health.
- Frontend constraints: Codex may call read APIs and WebSocket; no direct trading-core imports required.
- Real secrets must never be embedded; use environment variables.
