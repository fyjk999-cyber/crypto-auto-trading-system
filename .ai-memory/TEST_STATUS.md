# TEST_STATUS

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
