# Round-4 six-blocker repair receipt

```text
ROUND4_BASE_SHA = ffe21ad764e14e227565b3db081ec58a496d1120
ROUND4_BRANCH = codex/core-growth-v2-review4-fixes
ROUND4_IMPLEMENTATION_SHA = ddf646d444ee3c55df8a0c7df0f69e76236ab9bc
Previous exact review = ffe21ad (CHANGES_REQUIRED, thread 01a0938e)
Migration head = 0044_growth_review_attempt_bindings (single head)
```

## Reviewer record normalization

Source record: `/Users/huhongjie/.dsh/codex-dispatch/records/2026-09-12T02-59-32-806Z-01a0938e.json`

The final message summary says “6 finding: 4 P1 / 2 P2”; the逐项 labels confirm exactly
**4 P1 + 2 P2**:

```text
P1: F02 legacy memory boundary
P1: F03 actual mapper mutation connection
P1: F06 revoked lesson resurrection in compression
P1: new activation regression (lesson status vs final pattern)
P2: F04 public budget configuration error swallowed
P2: F13 trace override ignoring ranking policy
```

(F04 is P2 in the original record; the handoff’s apparent “5 × P1” was a reading
ambiguity only. No reviewer text was altered.)

## Fix matrix

| Finding | Fix | Tests | Status |
| --- | --- | --- | --- |
| NEW-P1 lesson/pattern reconciliation | `_activate_staged` now selects the final staged pattern per exact proposition, inserts it, then synchronizes every latest authoritative + staged member lesson of that exact proposition to the final verdict in the same fenced transaction. | T01/T02/T03 in `test_round4_invariants.py` | PASS |
| F06 revoked resurrection | `_statements_for_pattern` resolves latest non-staging version with `known_at <= as_of` first, then checks status/expiry; older VALIDATED cannot fall back. | T04 | PASS |
| F02 legacy memory boundary | Effective request account/mode, explicit `GLOBAL_EXPLICIT` sharing, status allowlist `{ACTIVE, WATCH}`, latest-visible version first and `known_at <= as_of`; loader instance scope cannot override request scope. | T05/T05b/T06/T07/T08 | PASS |
| F04 public budget contract | Typed `EvidenceBudgetConfigurationError`; registry re-raises it instead of manufacturing `UNAVAILABLE`; fixed reserve removed; real final serialized cost enforced on success/empty/failure. | T09/T10, card budget policy probes | PASS |
| F13 trace policy identity | Policy fingerprint is part of deterministic trace identity and override compatibility; incompatible override is re-keyed to the new identity. | T11 | PASS |
| F03 actual import connection | Each import mapper is exercised with `PRAGMA database_list` through `bind_arguments` in the same session used for mutation; URL labels and custom `async_creator` alternate DBs fail closed for import and rollback. | T12/T13 | PASS |

## Preserved passes

F01, F05, F07, F08, F09, F10, F11, F12, R02, R05 were not redesigned; the
full Growth/Core regressions and prior adversarial probes remain green.

## Gates on the frozen SHA

```text
Round-4 T01-T13 = 13 passed
Growth bundle   = 190 passed, 1 skipped
Core bundle     = 188 passed
Migration       = 5 passed, 1 skipped (real PostgreSQL NOT_VERIFIED)
Full backend    = 1199 passed, 1 skipped, 2 warnings (second run;
                  first run had one order-dependent flake that passed isolated)
Ruff            = All checks passed
Alembic head    = 0044_growth_review_attempt_bindings (single head)
```

## Review status

A Round-4 exact-SHA review was attempted but the Codex account usage limit was
reached before a formal verdict. The first attempt returned one concrete
counterexample (loader acct-a + request acct-b private-card leak), which was
fixed in `ddf646d` and covered by T05b. A retry is scheduled after the stated
reset time (2026-09-12 15:59 +08 / 07:59Z).

```text
INDEPENDENT_REVIEW_NEW_SHA = PENDING
GROWTH_FINAL_ACCEPTANCE = PENDING_REVIEW
```

## Safety

```text
REAL_PROVIDER_SMOKE=NOT_VERIFIED
NATURAL_PAPER_GROWTH_LOOP=PENDING
REAL_POSTGRES_EXECUTION=NOT_VERIFIED
MIGRATION_AUTHORIZATION=NOT_GRANTED
DEPLOYMENT_AUTHORIZATION=NOT_GRANTED
RUNTIME_AUTHORIZED=false
DEPLOYED=false
PRODUCTION_DB_WRITE=NO
EXECUTION_LEASE_TOUCHED=NO
LIVE_TRADING=NO
REAL_ORDER=NO
FAKE_EPISODE=NO
FORCED_PAPER_TRADE=NO
REAL_MONEY_READY=NO
```
