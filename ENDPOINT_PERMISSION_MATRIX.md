# ENDPOINT PERMISSION MATRIX

- PUBLIC: /health, /ready, /version, /market*, /regime, /signals, /strategies,
  /risk, /margin, /reviews, /stress-tests, /daily-reviews, /learning,
  /exchange-health, /cloud-status, /runtime, /orders*, /positions, /account,
  /ledger, /audit, /killswitch GET
- VIEWER: read-only endpoints listed above.
- OPERATOR: POST /exchange/okx/credentials, POST /exchange/okx/validate,
  POST /paper/perpetual/open, POST /paper/perpetual/close,
  POST /dev/daily-review/run, POST /manual-orders.
- ADMIN: DELETE /exchange/okx/credentials, POST /killswitch.
- INTERNAL_ONLY: /internal/runtime-health.

When AUTH_ENABLED=true, dependencies enforce roles. When AUTH_ENABLED=false
(local dev/test), endpoints remain reachable for backward-compatible tests.
