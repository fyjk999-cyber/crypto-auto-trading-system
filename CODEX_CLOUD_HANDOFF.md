# CODEX CLOUD HANDOFF

- Deployment status: BLOCKED / NOT COMPLETE
- Environment: TESTNET, safely normalized to PAPER execution
- Existing Worker URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev
- API Base URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/api/v1
- WebSocket URL: wss://crypto-trading-gateway.huhongjie-kalshi.workers.dev/ws
- OpenAPI URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/openapi.json
- Swagger URL: https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/docs
- Repository base SHA: 3aa2d1442bbc38851550c3fe016fe9be8f8a96dc
- Existing Worker version: 3a5d6997-89fe-4573-af8a-866cfaa9343e
- Candidate changes deployed: no
- Container: not deployed; Workers Paid plan and Docker required
- PostgreSQL provider: unprovisioned; Neon preferred
- R2: not enabled
- Cron: candidate configured, not deployed
- Cloudflare Access: not configured
- 24-hour soak: PENDING
- LIVE_TRADING_ENABLED: false
- Application blocker: `AUTO_START_RUNTIME` is not yet consumed by FastAPI startup; no autonomous
  runtime may be claimed until this is implemented and verified against PostgreSQL.

Codex access must use a Cloudflare Access service token and remains GET/HEAD-only. Control
endpoints are denied. Human JWT validation additionally requires `ACCESS_TEAM_DOMAIN` and
`ACCESS_POLICY_AUD`; the JWT signature, issuer, and audience must all validate.

Do not treat the existing `/health` 200 response as runtime health. The deployed version returns
404 for `/ready` and `/internal/runtime-health` and does not prove a Container or database exists.

See `CLOUDFLARE_FINAL_REPORT.md`, `24X7_RUNTIME_REPORT.md`, and `SOAK_STATUS.md` before resuming.
