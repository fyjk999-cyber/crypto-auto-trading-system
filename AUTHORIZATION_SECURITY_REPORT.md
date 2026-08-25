# AUTHORIZATION SECURITY REPORT

- Updated: 2026-08-25T15:47:16.949572+00:00
- Auth architecture: environment-token RBAC (VIEWER/OPERATOR/ADMIN) in
  src/crypto_trader/security/auth.py.
- AUTH_ENABLED=false in dev/test; when enabled, dangerous endpoints require
  ADMIN/OPERATOR bearer tokens whose sha256 digest matches env keys.
- Audit events record actor/role/action/target/reason/result/timestamp.
- Backend remains authoritative; frontend state cannot enable live trading.
- CORS/debug exposure: existing local dev proxy used; deployment must restrict
  CORS origins and disable debug.
- Known limitation: full endpoint wiring and session lifecycle are deployment
  configuration work; unit tests cover verification and audit helpers.
