# RUNBOOK

- Updated: 2026-08-27T14:32:15.776538+00:00
- Startup/shutdown/restart: standard uv app run; use canonical bootstrap.
- PostgreSQL migration: alembic upgrade head.
- PostgreSQL outage: fail explicit; no SQLite/memory fallback.
- Market data outage: block unsafe entries; exits/reduce remain.
- Learning outage: live trading continues.
- Evolution outage: live + learning continue; Champion unchanged.
- Candidate quarantine: CandidateRegistry.mark_quarantined.
- Promotion/rollback: SafePromotionCoordinator; health/smoke fail -> rollback; rollback health fail -> SAFE_DEGRADED.
- Kill switch: always authoritative.
- SAFE_DEGRADED: no new entries; risk/exit/ledger/reconciliation active.
