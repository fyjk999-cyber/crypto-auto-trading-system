# FAILURE INJECTION REPORT

- Updated: 2026-08-27T05:20:41.040797+00:00
- Unit-level failure isolation verified:
  - promotion health/smoke fail -> ROLLED_BACK
  - rollback health fail -> SAFE_DEGRADED
  - uncertified candidate blocked
  - protected path/workspace escape blocked
- Full fault injection (Postgres disconnect, exchange delays, etc): NOT_RUN in
  this harness.
