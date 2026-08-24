# CLOUDFLARE DEPLOYMENT STATUS

Checked at: 2026-08-24T21:31:16+08:00

This is a truthful deployment gate report. The existing Worker is reachable, but the requested
Worker -> Durable Object -> Container -> PostgreSQL runtime is **not deployed**.

## Status matrix

| Requirement | Status | Evidence |
|---|---|---|
| Cloudflare Worker | FAIL | Existing version `3a5d6997-89fe-4573-af8a-866cfaa9343e` answers static `/health`; `/ready` and `/internal/runtime-health` return 404. |
| Cloudflare Container | FAIL | Account API reports that Containers require a Workers Paid plan; local Docker CLI is absent. |
| Cron watchdog | FAIL | Correct `* * * * *` candidate config passes Wrangler dry-run, but it is not deployed or failure-drilled. |
| PostgreSQL | FAIL | No `DATABASE_URL`; no Neon authorization; migration and `SELECT 1` not run. |
| R2 backup | FAIL | R2 is not enabled on the Cloudflare account (API code 10042). |
| Cloudflare Access | FAIL | No deployed Access application/policies/service tokens; Worker secrets list is empty. |
| Runtime autostart | FAIL | Candidate env is configured, but the live Container/runtime does not exist and cannot be verified. |
| Browser independence | FAIL | No running cloud runtime exists for the mandatory zero-client observation. |
| Recovery drills | FAIL | Container, database, and R2 drills cannot run before the underlying resources exist. |
| `LIVE_TRADING_ENABLED` | `false` | Candidate config is fail-closed and TESTNET maps to PAPER execution mode. |
| 24-hour soak | PENDING | Not started; see `SOAK_STATUS.md`. |

## Validated candidate changes

- Wrangler 4.125.0 recognizes `TradingContainerV2`, `new_sqlite_classes`, the R2 binding,
  and the minute Cron in a worker-only dry-run.
- Worker routes through a named Container and contains no `BACKEND_URL` or
  `container-backend.example.internal` fallback.
- Cloudflare Access human JWTs require signature, issuer, and audience validation; a header alone
  is rejected. Codex is GET/HEAD-only and all configuration fails closed when secrets are absent.
- PostgreSQL runtime drivers are present in the Python dependency set.
- Local validation: 187 pytest tests, 14 Node tests, Ruff, JavaScript typecheck, generated binding
  type check, and Wrangler worker-only dry-run pass.

## Account and infrastructure blockers

1. Upgrade/enable a Cloudflare Workers plan with Containers access.
2. Install and start a Docker-compatible CLI/daemon on the deployment host.
3. Enable R2 in the Cloudflare dashboard.
4. Authorize/provision Neon (or provide an existing managed PostgreSQL async SQLAlchemy URL).
5. Configure Cloudflare Zero Trust Access, including team domain, application AUD, human policy,
   and Codex/Harness service tokens.
6. Add required Worker secrets without committing or printing their values.

## Remaining application blocker

`AUTO_START_RUNTIME=true` is now carried into the Container, but the FastAPI application does not
yet consume that setting or attach/start `TradingRuntimeSupervisor` in `build_default_app()`. The
current initial migration also has a runtime lease table but no dedicated heartbeat table requested
by the deployment brief. These must be implemented and tested against real PostgreSQL before the
runtime/autostart/watchdog gates can pass; a configured environment variable alone is not evidence
that autonomous trading loops are running.

No deploy, secret mutation, database migration, bucket creation, Access mutation, Git commit, or
push was performed after these blockers were discovered. No real-money order was placed.

Current repository base SHA: `3aa2d1442bbc38851550c3fe016fe9be8f8a96dc`.
The validated candidate changes remain uncommitted and are not the code currently serving traffic.
