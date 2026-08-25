# PERFORMANCE TEST REPORT

- Updated: 2026-08-25T15:47:16.949572+00:00
- Test: scripts/performance_smoke.py (deterministic, no external services)
- Environment: macOS x86_64, Python 3.12 venv
- Results:
  - capital_allocate: 0.034 ms/op (2000 iterations)
  - portfolio_risk: 0.016 ms/op (2000 iterations)
  - liquidity_assess: 0.026 ms/op (2000 iterations)
  - execution_plan: 0.006 ms/op (2000 iterations)
- Full symbol scan (50/100/300) not executed; no external market feed in harness.
- Soak: NOT_FULL_DURATION. Short deterministic smoke only.
- No unbounded resource growth observed in smoke path.
