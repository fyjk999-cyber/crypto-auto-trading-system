# REAL RUNTIME QUALIFICATION

- Updated: 2026-08-28T05:50:00+00:00
- Baseline: NEW_RUNTIME_QUALIFICATION_BASELINE_SHA = 7b746df09ba5a8e2e9e10cd676fa5d14a2535f10 (supersedes 20a4db8… and af9e393…)
- 24-hour soak: NOT_RUN (CHAPTER_10 = BLOCKED_BY_ENVIRONMENT: no local PostgreSQL; unstable local VPN DNS)
- Multi-day soak: NOT_RUN (permanently out of scope)
- Real 00:05 UTC boundary: NOT_OBSERVED (requires 24h run)
- Real PostgreSQL: NOT_RUN (not installed on this machine)
- Paper closed-loop smoke (time-compressed): PASS
- Paper live smoke (30-60 min, real LLM): PASS — see docs/PAPER_SMOKE_TEST_REPORT.md
- Failure injection: unit-level PASS; live LLM provider disable/enable isolation PASS; market-data outage PASS (fail-closed)
- Promotion/rollback dry-run: unit-level PASS; real runtime NOT_RUN
- REAL_MONEY_READY = NO. REAL_MONEY_ENABLED = NO. PAPER ONLY.
