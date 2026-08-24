# CLOUDFLARE FINAL REPORT

## Status
- Cloudflare Worker: BUILT, typechecked, unit-tested; NOT deployed (external credential blocker)
- Worker deployment version: n/a (no Cloudflare auth)
- Container image: built locally by CI (Dockerfile); digest n/a until CI run
- Container instance type: standard-1 (documented); region: auto (documented)
- API Base URL: n/a (blocked)
- WebSocket URL: n/a (blocked)
- OpenAPI URL: n/a (blocked)
- Access status: policy configured; not applied
- Codex read-only status: implemented in gateway + tests (403 for control endpoints)
- PostgreSQL status: SQLAlchemy/Alembic compatible; cloud DB not provisioned
- Migration status: existing Alembic migration valid for SQLite; PostgreSQL migration not executed
- R2 status: backup/restore scripts provided; not executed
- Backup status: not executed
- Restore-test status: not executed
- Cron/Workflow status: documented; not deployed
- Paper cloud E2E: not executed (requires deployed Worker+Container)
- Binance Testnet E2E: BLOCKED_EXTERNAL_CREDENTIAL (no testnet API keys)
- Cloud chaos tests: gateway logic covered by Node tests; deployment chaos not executed
- Total tests: 178 pytest + 9 node tests
- Coverage: 87% (pytest)
- CI: extended with worker typecheck/test and container build jobs
- LIVE_TRADING_ENABLED=false
- Real-money orders placed: NO

## Blocker
CLOUDFLARE_DEPLOYMENT_BLOCKED_BY_AUTH. Only required action: provide a minimal Cloudflare API token (and optionally a zone) so `wrangler deploy` and container deployment can run. All deployment code, configs, dry-runable worker, tests, and docs are ready in `deployment/cloudflare/`.
