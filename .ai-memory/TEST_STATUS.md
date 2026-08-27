# TEST_STATUS

- Updated: 2026-08-27 (after three-brain support workstream)
- uv run pytest (full suite, single process): 625 passed, 8 skipped, 0 failed
  - 4 skips: bare-skipped engine-loop integration tests
    (tests/integration/test_canonical_runtime_bootstrap.py - see audit doc)
  - 3 skips: postgres qualification requires DATABASE_URL (not set locally)
  - 1 skip: OKX network smoke (network unavailable locally)
- ruff check .: PASS (previously 9 baseline errors, all cleaned this workstream)
- New suites: tests/evolution/test_hierarchical_service.py (+21),
  tests/evolution/test_candidate_contracts.py (+13), factor health (+18) and
  factor profiles (+14) from earlier chapters of the same workstream.
- CI postgres qualification workflow unaffected; integration job unchanged.
