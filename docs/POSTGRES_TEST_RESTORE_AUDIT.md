# PostgreSQL Integration Test Restoration Audit

- Date: 2026-08-27
- Scope: read-only audit of skipped engine-loop / DB-dependent integration tests,
  test database fixtures, CI topology, and the documented claims about them.
- Task reference: WORKSTREAM F — PostgreSQL integration test restoration audit.

```text
POSTGRES_TEST_RESTORE_READY = NO
```

Blockers are listed in [Restoration blockers](#restoration-blockers).
No assertion was weakened and no new skip decorator was added as part of this audit.

---

## 1. Findings inventory

### 1.1 Engine-loop tests with stacked skips

File: `tests/integration/test_canonical_runtime_bootstrap.py`

| Line | Test | Decorators | Runs where today |
|---|---|---|---|
| 145-149 | `test_reduce_real_runtime_path` | `skipif(CI=true)` **+ bare `skip`** | nowhere |
| 167-171 | `test_exit_real_runtime_path` | `skipif(CI=true)` **+ bare `skip`** | nowhere |
| 263-266 | `test_engine_loop_auto_reevaluates_hold` | `skipif(CI=true)` only | locally only |
| 281-285 | `test_engine_loop_reduce_real_path` | `skipif(CI=true)` **+ bare `skip`** | nowhere |
| 304-308 | `test_engine_loop_exit_real_path` | `skipif(CI=true)` **+ bare `skip`** | nowhere |

Key observations:

1. Four of the five tests carry a **bare `@pytest.mark.skip`**. These four can never
   run: not in CI, not locally, not on PostgreSQL, not under any future workflow.
   The CI-condition skipif beneath it is dead code for those tests.
2. The single test that is only CI-gated (`test_engine_loop_auto_reevaluates_hold`)
   **passes against the current SQLite fixture outside CI**
   (`1 passed` in local run on 2026-08-27). This is direct evidence that at least
   part of the "engine loop cannot run" rationale no longer holds, and that the
   bare-skipped siblings were never re-validated after the flake that caused them.
3. The tests exercise the canonical runtime through `build_system(...)`
   (`engine_tick_seconds=3600`, manual `await engine.tick()` invocation) - they do
   not reproduce the historical 20 Hz loop. The flake label ("sqlite event loop
   flake") predates the current shape of these tests.

### 1.2 Test database fixture status

File: `tests/conftest.py:19-24`

- The shared `database` fixture creates **SQLite only**
  (`sqlite+aiosqlite:///{tmp_path}/crypto_test.db`), function-scoped.
- Teardown calls `db.close()` only. There is:
  - no PostgreSQL branch (ignores `DATABASE_URL`),
  - no per-test schema isolation beyond `tmp_path`,
  - no transaction-rollback lifecycle,
  - no background-task/join verification before close.

### 1.3 PostgreSQL qualification suite

File: `tests/postgres_qualification/test_postgres_runtime.py:15-19`

- Module-level `skipif(not DATABASE_URL.startswith("postgresql"))` guards three
  persistence/recovery tests. This gate itself is correct and remains necessary;
  the issue is coverage scope, see §1.4.

### 1.4 CI topology

- `.github/workflows/ci.yml` `integration-test` job sets **no `DATABASE_URL`**:
  every integration test runs on aiosqlite regardless of runner capabilities.
- `.github/workflows/postgres-runtime-qualification.yml` provisions a postgres:16
  service, runs `alembic upgrade head`, then executes **only**
  `tests/postgres_qualification`.
- Consequence: the PostgreSQL workflow covers persistence/migration semantics but
  executes none of the five engine-loop tests listed in §1.1.

### 1.5 Network-conditional skips (not DB-related)

File: `tests/ai_brain/test_forward_shadow_smoke.py:18-20`

- Skips when OKX API is unreachable or non-200. This is a legitimate external-service
  condition (smoke guard), unrelated to the database restoration workstream, and is
  left untouched.

### 1.6 Migration chain note

`migrations/versions/` contains two files with the same numeric prefix
(`0014_learning_persistence_tables.py`, `0014_order_contract_fields.py`) but the
revision graph is **linear**: `0013_factor_v10 -> 0014_learning ->
0014_order_contract -> 0015_hierarchical`. Single head, no branching problem -
the duplication is filename-cosmetic only.

---

## 2. Documentation discrepancy (correction)

`docs/POSTGRES_RUNTIME_VALIDATION.md` states:

> Previous SQLite skips: superseded by PostgreSQL workflow coverage for
> persistence/runtime bootstrap paths.

This claim is **not accurate** for the engine-loop paths:

- The bare-skipped tests (§1.1 rows 1/2/4/5) are skipped unconditionally and are
  therefore not covered anywhere - neither by the SQLite-based integration job nor
  by the PostgreSQL qualification workflow (which selects only
  `tests/postgres_qualification`).
- What the PostgreSQL workflow *does* cover is migrations plus the qualification
  module's own persistence/recovery/hierarchy/bootstrap-store tests.
- `docs/CI_SQLITE_CONTENTION.md` records the intent correctly: restore
  engine-loop integration tests once a PostgreSQL test fixture exists.

The truthful summary: **"partially superseded": persistence paths are covered on
PostgreSQL; real-runtime engine-loop paths are covered nowhere.**

---

## 3. Root cause assessment

Evidence available today supports this history rather than a single cause:

1. Historical CI failures happened while the integration suite ran on aiosqlite
   with high-frequency background loops (the shared chaos/e2e helper
   `make_paper_engine` defaults to `engine_tick_seconds=0.05`, i.e. a 20 Hz loop
   issuing writes over aiosqlite's single-writer lock). That shape genuinely
   contends on SQLite.
2. The currently checked-in engine-loop tests were later rewritten to use manual
   single ticks at `engine_tick_seconds=3600` via `build_system` bundles; the one
   such test that is allowed to run passes consistently today (§1.1 observation 2).
3. No experiment on record reproduces an active failure for the four bare-skipped
   tests, because they are unreachable by construction.

Conclusion: the original skips encoded both a real contention class (20 Hz loops)
and a stale event-loop teardown flake; the guard has since drifted from the code
it protects. They should be replaced by DB-aware gating, not by silence.

---

## 4. Restoration plan (ordered)

All steps are additive; none weaken assertions or add skips.

1. Extend `tests/conftest.py` with a PostgreSQL-capable fixture path
   (e.g. parametrize/branch on `DATABASE_URL`: keep SQLite default for unit/local
   runs, use asyncpg URL + dedicated ephemeral schema when provided), including
   deterministic setup/teardown and background-task join before close.
2. Remove the four bare `@pytest.mark.skip` decorators in
   `tests/integration/test_canonical_runtime_bootstrap.py`; keep
   DB-conditional `skipif` gates only where a test genuinely requires Postgres
   semantics (those gates must consult the fixture capability, not `CI == true`).
3. Point the restored engine-loop tests at the new fixture; re-run repeatedly
   (≥20 iterations) against postgres:16 to confirm the flake class is gone rather
   than hidden.
4. Wire `DATABASE_URL` into the `integration-test` job (or move the restored tests
   behind the existing postgres workflow) so the skipped-in-CI state disappears.
5. Update `docs/POSTGRES_RUNTIME_VALIDATION.md` so its claim matches reality
   after restoration completes.

## Restoration blockers (current state)

1. No PostgreSQL-capable test fixture exists (`tests/conftest.py` is SQLite-only).
2. Four tests are unconditionally skipped by bare decorators and have never been
   validated against PostgreSQL.
3. The `integration-test` CI job cannot reach any PostgreSQL instance.
4. Flake-class fix is unproven: without repeated green runs on Postgres,
   removing skips would risk re-introducing red CI rather than restoring coverage.

Because of blockers 1-4, engine-loop integration coverage still does not exist on
PostgreSQL, and declaring restoration complete would be false:

```text
POSTGRES_TEST_RESTORE_READY = NO
```
