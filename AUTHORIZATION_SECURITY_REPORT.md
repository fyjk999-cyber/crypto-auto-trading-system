# AUTHORIZATION SECURITY REPORT

- Updated: 2026-08-25T16:10:41.520418+00:00
- RBAC roles: VIEWER, OPERATOR, ADMIN.
- Dangerous endpoints now have backend dependencies:
  - OPERATOR: POST okx credentials, validate, paper open/close, daily-review run,
    manual-orders.
  - ADMIN: DELETE okx credentials, POST killswitch.
- When AUTH_ENABLED=true, tokens verified by sha256 digest; missing/invalid
  tokens raise PermissionError.
- Audit events: actor/role/action/target/reason/result/timestamp.
- AUTH_ENABLED=false for local dev/test; production must set true and provide keys.
