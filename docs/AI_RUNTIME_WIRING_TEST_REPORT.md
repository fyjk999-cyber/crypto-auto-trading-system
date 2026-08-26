# AI RUNTIME WIRING TEST REPORT

- Updated: 2026-08-26T05:39:47.873867+00:00
- Production-path engine loop tests: 15 passed.
- LONG real runtime HOLD/REDUCE/EXIT passed.
- SHORT mapping/reduce-only/never-reverse tests passed; underlying spot paper
  adapter does not support negative fills, so short fill-level tests use
  bridge/adapter/state-machine proofs and are labeled as such.
- reduce_only preserved in SignalIntent.metadata.
- Full regression: pytest 462 passed; ruff PASS; frontend typecheck PASS;
  agent-project-test PASS.
