# C6-C8 Working Status (Harness)

Date: 2026-09-10
SHA: cc47d1421a61ee341fa6d214a9b1740ee59ae6fb
Branch: codex/full-market-factor-layer

C1-C4 are being handed to Codex; this document records C6-C8 work only.

## C6 - LONG/SHORT chaos lifecycle

Verified suites on this SHA:

```text
tests/chaos
tests/local_stability
tests/integration/test_recovery.py
tests/integration/test_live_llm_position_lifecycle.py

result: 60 passed
```

Covered evidence:

```text
LONG full chain ACTIVE -> HOLD -> REDUCE -> EXIT -> zero -> CLOSED
SHORT full chain ACTIVE -> HOLD -> REDUCE -> EXIT -> zero -> CLOSED
restart restores ACTIVE position without fabricating fill
partial exit remains ACTIVE until factual zero
duplicate exit ticks create one pending close lifecycle
unsettled entry blocks position action
stale writer fence blocked
```

Still open for full C6:

```text
duplicate ACK / duplicate fill / fill-before-ACK / out-of-order fill
restart unsettled entry
restart before Episode creation
lease loss before cancel
lease loss before submit
DB failure during settlement
DB failure during Episode creation
exact one-Episode assertion under all above
```

Status: C6 = PARTIAL.

## C7 - frontend executable scope contract

Implemented:

```text
AI page now renders:
  EXECUTABLE_SCOPE = <backend value or UNKNOWN>
  SPOT / FUTURES / INVERSE = NOT_EXECUTABLE
```

Commands on this SHA:

```text
npm test          -> 24 passed
npm run typecheck -> PASS
npm run build     -> PASS
```

Still open for full C7:

```text
valuation status / valuation_id / missing marks
raw MTM equity / adjusted equity / peak / drawdown
funding state
Daily Review PENDING / RUNNING / FAILED / SUCCEEDED
attempt_count / episode_count / last_error
0 vs null vs UNKNOWN vs STALE display regressions
button API / permission / timeout / duplicate click verification
browser E2E
```

Status: C7 = PARTIAL.

## C8 - engineering gate dry run on current SHA

This is not the final freeze; C1-C4 are still owned by Codex.

Commands and results on cc47d:

```text
git rev-parse HEAD
  cc47d1421a61ee341fa6d214a9b1740ee59ae6fb

pytest -q
  715 passed, 1 warning

ruff check .
  All checks passed

frontend npm test
  24 passed

frontend npm run typecheck
  PASS

frontend npm run build
  PASS

tools/agent_project_test.py
  agent-project-test: PASS
  exit code = 0
```

Still open for full C8:

```text
FINAL_CANDIDATE_SHA freeze after Codex C1-C4 work
fresh migration DB
existing DB upgrade migration
migration restart
runtime recovery
Daily Review recovery on final DB
lease / fencing
agent-project-test re-run on final frozen SHA
user manual review material
final runtime authorization (user blocker)
fixed-SHA natural runtime acceptance
```

Status: C8 = PARTIAL (gate dry run only; no final SHA, no runtime authorization).

## C8 additional gate evidence

On cc47d / 4ce3c2b code state:

```text
pytest -q \
  tests/opportunity/test_full_market_factor_layer.py::test_migration_chain_extends_llm_decisions_with_lineage \
  tests/integration/test_bootstrap.py \
  tests/runtime_unit/test_supervisor.py \
  tests/integration/test_recovery.py

result: 11 passed
```

Covers:

```text
alembic upgrade head migration chain
stale writer recovery in bootstrap
lease renewal / zombie writer / stale fence
order recovery after restart
```
