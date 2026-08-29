# TEST_STATUS

- 2026-08-29T14:45Z: tests/integration/test_trade_episodes.py NEW (15 tests, all
  passing): TIME_STOP episode single+idempotent, entry-only no episode, partial
  close stays open / full close completes, two same-symbol cycles -> 2 episodes,
  multiple entries weighted avg (106.666...), LONG+SHORT pnl signs (perp SHORT
  via canonical engine path), fees=SUM(fill.fee) relational, runtime hook creates
  episode on close fill, quarantined fills excluded, perp gross from
  FUTURES_REALIZED_PNL ledger, AI_EXIT payload passthrough, UNKNOWN honest for
  foreign strategy, lineage_json auditability, daily-review load_episodes,
  episode key stable across unrelated cycles. Full integration suite: 111
  passed / 4 skipped. ruff clean on all touched files.
- 2026-08-29: backend 725 passed / 7 skipped / 2 failed (pre-existing
  live-OKX fixture tests, unrelated); ruff clean; frontend 34 tests + tsc +
  build OK. New regression tests: futures-aware reconciliation, perp
  duplicate-entry gate (open/failed/flat), fake-price match guard.
- Updated: 2026-08-27T14:36:17.029344+00:00
- pytest: 628 passed, 8 skipped
- ruff: PASS
- frontend typecheck: PASS
- agent-project-test: PASS
- 2026-08-28: Phase 8D-1.5 plus domain model layer full pytest: 647 passed, 7 skipped; ruff check: PASS; phase formatting scope: PASS; frontend tests/typecheck/build: PASS; agent-project-test previously passed. Full-repository ruff format check still has pre-existing unrelated drift.
- 2026-08-28: uv run pytest: 651 passed, 7 skipped (4 documented engine-loop bare
  skips + 3 postgres-URL-conditional), 0 failed. ruff check .: PASS.
  Frontend: 21 tests passed, typecheck+build PASS. Alembic: 0017_domain_model_evidence (head).
- 2026-08-28 (final smoke baseline 7b746df): uv run pytest 654 passed, 7 skipped,
  0 failed; ruff check . PASS; frontend 21 tests + typecheck + build PASS.
  LLM qualification 6/6 PASS live; paper smoke PASS (docs/PAPER_SMOKE_TEST_REPORT.md).

- 2026-08-29T07:25:18+00:00: 734 passed / 7 skipped / 2 failed (pre-existing live-OKX, unrelated). Added test_exit_lifecycle.py (6): reduce-only time-stop EXIT through Risk+Execution, duplicate-EXIT guard, age hydration, snapshot persistence, settlement robustness.


## 2026-08-29T09:43Z (bb4fa37)
- test_exit_lifecycle.py: 10 passed (risk-reject retry, authority-hold retry, outstanding-order duplicate suppression, quarantine JSON dialects, snapshot-failure observability + prior 5).
- test_symbol_expansion.py: 8 passed (registry mapping, 30 universe, new-symbol perp SHORT via real Risk+Execution, SPOT_OVERSHORT preserved, symbol-scoped gate, fail-closed unregistered perp, restart idempotency, multi-perp reconciliation).
- Full suite: 746 passed / 7 skipped / 2 pre-existing live-OKX network failures (documented).
- Chaos contract updated: process_signal returns the FINAL authority outcome.
