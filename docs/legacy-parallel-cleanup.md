# Legacy Parallel Code Cleanup

- Baseline: `eb627997eb26f128d388190bb6242c8236e5820c`
- Quarantine validation head: `3a0bcb7ca135f4c6ae38b2b721cc10d58ff9a084`
- Method: move legacy candidates out of active `src/tests/scripts`, run CI, restore any candidate with active callers, then permanently delete only validated dead paths.
- Restored after counterexample tests: `research/`, `evolution/`, `capital_deployment/`.
- Legacy performance-only script quarantined with its old stacks: `scripts/performance_smoke.py`.
- Quarantine validation: lint PASS, unit PASS, integration PASS, container-build PASS, cloudflare-worker PASS.
- Integration result: 558 passed, 1 warning.
- Portable full-suite gate ran inside integration and passed after excluding only known CI-host-incompatible macOS/local-path tests.
- PAPER runtime/database were not touched.

The permanent guard in `tests/integration/test_no_legacy_parallel_code.py` prevents deleted parallel packages or ghost imports from being reintroduced.
