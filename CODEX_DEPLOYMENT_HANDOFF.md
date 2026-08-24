# CODEX DEPLOYMENT HANDOFF

## Required Cloudflare resources
- Worker: crypto-trading-gateway
- Container: crypto-trading-primary (TradingContainer Durable Object)
- R2 bucket: crypto-trading-backups
- Cron trigger: * * * * *
- Access applications + service tokens:
  - Human User
  - crypto-codex-readonly (GET/HEAD/WS read)
  - Harness Deployment (control)

## Required secrets (wrangler secret / Cloudflare Secret Store)
- DATABASE_URL
- BINANCE_TESTNET_API_KEY
- BINANCE_TESTNET_API_SECRET
- INTERNAL_API_SECRET
- CODEX_CLIENT_ID / CODEX_CLIENT_SECRET
- HARNESS_CLIENT_ID / HARNESS_CLIENT_SECRET

## PostgreSQL requirements
- Managed PostgreSQL (recommend Neon/Supabase/PlanetScale)
- SQLAlchemy async URL
- Alembic migration command: `alembic upgrade head`

## Deploy commands
```bash
# Worker only (no container rollout when Docker unavailable locally)
cd deployment/cloudflare/worker
npx wrangler deploy --containers-rollout=none

# With Docker/Cloudflare Containers available
npx wrangler deploy

# Secrets
npx wrangler secret put DATABASE_URL
npx wrangler secret put BINANCE_TESTNET_API_KEY
npx wrangler secret put BINANCE_TESTNET_API_SECRET
npx wrangler secret put INTERNAL_API_SECRET
npx wrangler secret put CODEX_CLIENT_ID
npx wrangler secret put CODEX_CLIENT_SECRET
npx wrangler secret put HARNESS_CLIENT_ID
npx wrangler secret put HARNESS_CLIENT_SECRET
```

## Verification commands
```bash
curl https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/health
curl https://crypto-trading-gateway.huhongjie-kalshi.workers.dev/api/v1/version
npx wrangler tail
```

## Rollback
- Worker rollback: `npx wrangler rollback`
- Container image rollback: redeploy previous image tag
- Application rollback: redeploy previous git SHA
- DB migrations must remain backward compatible; never rollback code without compatible schema.
