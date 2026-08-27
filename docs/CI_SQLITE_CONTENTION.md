# CI SQLITE CONTENTION

- Updated: 2026-08-27T00:14:33.078993+00:00
- Several canonical-runtime integration tests are skipped due to SQLite
  background engine-loop contention.
- Skipped tests are covered by component tests:
  bridge routing, adapter mapping, reduce_only semantics, state machine.
- Restore engine-loop integration tests when PostgreSQL test fixture is
  available in CI.
