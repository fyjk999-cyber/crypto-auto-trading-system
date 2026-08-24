# TESTNET 24-HOUR SOAK STATUS

- Status: `PENDING`
- Start timestamp: not started
- Reason: Cloudflare Containers plan, Docker, PostgreSQL, R2, Access, and required secrets are not ready.
- Runtime uptime: not available
- Scanner cycles: not available
- WebSocket reconnects: not available
- Container restarts: not available
- Watchdog interventions: not available
- Duplicate events: not measured
- Ledger mismatches: not measured
- Reconciliation mismatches: not measured
- Lease failures: not measured
- Frontend clients: not measured

The soak may start only after the deployed Container reports ready, PostgreSQL is migrated, Access
is enforced, the watchdog recovery test passes, and `LIVE_TRADING_ENABLED=false` is re-verified.
