# 24x7 RUNTIME REPORT

Checked at: 2026-08-24T21:31:16+08:00

- Runtime state: `NOT_DEPLOYED`
- Environment: `TESTNET` (normalized to safe `PAPER` execution mode)
- Logical Container: `crypto-trading-primary`
- Worker URL: `https://crypto-trading-gateway.huhongjie-kalshi.workers.dev`
- Database provider: `UNPROVISIONED` (Neon preferred)
- R2 bucket: `crypto-trading-backups` (`NOT_ENABLED`)
- Access: `NOT_CONFIGURED`
- Cron: candidate `* * * * *`, not deployed
- Browser-independent runtime: not verified
- Recovery: not drilled
- Application autostart wiring: missing; `AUTO_START_RUNTIME` is not consumed by FastAPI startup
- Dedicated heartbeat table: missing from the current Alembic migration
- `LIVE_TRADING_ENABLED`: `false`
- 24-hour soak: `PENDING`

The existing live Worker health response is edge-only and must not be interpreted as runtime
health. At verification time, `/ready` and `/internal/runtime-health` both returned 404.
