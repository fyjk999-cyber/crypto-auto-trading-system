# Stopped PAPER Runtime — Durable-State Preflight (read-only)

Scope: the runtime `PID 45868` (started 2026-09-12 14:45:07 +08:00 from
`crypto-paper-deployment-candidate`, SHA `a8a61ad`) is no longer running. This
document records the FACTS needed before any cold-start recovery mission. No
process was started, stopped or signalled; no production database was written
(all queries ran against a copy).

---

## 1. Which database the runtime actually used

Not the deployment worktree's own `data/crypto_trader.db` (that file is empty —
every table has 0 rows except `alembic_version` — and its mtime, 2026-09-12
14:07, predates the runtime's start).

The runtime wrote to:

```
/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-fullmarket/data/crypto_trader.db
```

Evidence (all three agree to the second):

| artifact | value |
|---|---|
| `engine_runs` (that DB) | `run_4b1a1f5d8b6e448685c4fdb9b5c955b0`, mode `PAPER`, started **2026-09-12 06:45:10 UTC**, ended **2026-09-13 06:36:09 UTC**, state **STOPPED** |
| `audit_events` | `ENGINE_STARTED` 06:45:11.484194 UTC · `ENGINE_STOPPED` 06:36:09.705497 UTC |
| `paper-runtime.log` | `Started server process [45868]` at 14:45:07 +08:00 · `Shutting down` … `Finished server process [45868]` at 14:36 +08:00 |

`integrity_check = ok` on the copy.

## 2. Stop classification

```
STOP_CLASSIFICATION = CLEAN_STOP
```

* uvicorn's full graceful sequence is present: `Shutting down` → `Waiting for
  application shutdown.` → `Application shutdown complete.` → `Finished server
  process [45868]`.
* The engine's own shutdown ran: `ENGINE_STOPPED` audit row and
  `engine_runs.state = STOPPED` with `ended_at` set.
* The execution lease was **released**: `runtime_leases.expires_at = 0.0`
  (last renewal ≈ 06:36:09 UTC, the stop instant).
* Normal trading activity continued to **51 seconds** before the stop
  (last `LIVE_LLM_POSITION_DECISION` at 06:35:18.398651 UTC), and to ~06:34 for
  position-action reconciliation.
* No fatal traceback accompanies the shutdown. The log does contain 143
  tracebacks, but they are **request-handler 500s** on `GET /learning`
  (`DecimalError: binary float is forbidden in financial core`) from the
  deployment SHA's API layer; the process kept serving afterwards.

The stop was therefore an orderly, externally-initiated shutdown — not a crash.
WHO initiated it is not determinable from these artifacts and is not inferred.

## 3. Durable state (fresh read)

```
POSITION_COUNT            = 5 rows, 1 with quantity != 0
UNRESOLVED_ORDER_COUNT    = 2   (status OPEN)
UNKNOWN_ORDER_COUNT       = 1
PARTIAL_FILL_ORDER_COUNT  = 0   (among unresolved orders)
MISSING_ORDER_COUNT       = 1   (non-terminal order with no exchange_order_id)
ACTIVE_PLAN_COUNT         = 1
APPROVED_PLAN_COUNT       = 2   ("imminent": approved, not yet active)
PLANNED_PLAN_COUNT        = 9
CLOSED / REJECTED / INVALIDATED = 9 / 12 / 5
FILLS                     = 60
LEDGER_TRANSACTIONS       = 66 (latest: PAPER funding receipts, 2026-09-13 04:00 UTC)
EPISODES                  = 9
```

Orders by status (whole DB): `FILLED 41`, `CANCELLED 18`, `REJECTED 7`,
`OPEN 2`, `UNKNOWN 1`. 57 of the 69 orders belong to the stopped run; the last
order was created 2026-09-13 00:05:06 UTC.

### Position facts

| symbol | qty | avg entry | updated_at | linked plan |
|---|---|---|---|---|
| **IOSTUSDT** | **29** | 0.0008783 | 2026-09-12 23:18:02 | `plan_ca0660c80a154bfc88f2415f0e6bf258` (ACTIVE, LONG, opened 2026-09-12 22:37:43) |
| BEATUSDT | 0 | — | 2026-09-12 23:18:02 | — |
| CPUSDT | 0 | — | 2026-09-12 23:18:02 | — |
| ETHFIUSDT | 0 | — | 2026-09-12 23:18:02 | — |
| LABUSDT | 0 | — | 2026-09-12 23:18:02 | — |

The one nonzero position (`IOSTUSDT`) has an ACTIVE plan, and that plan's
position-action chain is present (entries, reductions, one TTL-cancelled
remainder). No nonzero position lacks an ACTIVE plan.

### Unresolved order facts

| order_id | client_order_id | exchange_order_id | symbol | side | qty | filled | state | identity |
|---|---|---|---|---|---|---|---|---|
| `ord_f9edfa0a…b0b22` | `live_llm_llm_6b3117…1f8` | `sim_81ef1044…3db` | SOPHUSDT | SELL | 3000 | 0 | OPEN | complete |
| `ord_3f643bbf…d2f5` | `live_llm_llm_dd4255…b9e` | `sim_b43a8a98…b57` | IOSTUSDT | BUY | 2468 | 0 | OPEN | complete |
| `ord_4b4d845c…7328` | `live_llm_position_position_decision_c307943e…` | **(none)** | IOSTUSDT | SELL | 15 | 0 | UNKNOWN | **missing venue id** |

### Account

```
ACCOUNT_PROJECTION_TOTAL   = 199,998.67019089452207811414 USDT (updated 2026-09-12 23:18:02)
LATEST_EQUITY_SNAPSHOT     = 100,000.39826248409714494275 USDT
                             (MARK_TO_MARKET_EQUITY, HEALTHY, as_of 2026-09-13 00:05:03)
                             external_cash_flow_adjustment = 100,000 → cash-flow-adjusted 0.398…
```

The projection total and the mark-to-market equity differ by ~99,998 (the
external cash-flow adjustment); both figures are reported rather than one being
chosen.

## 4. Writer / lease state

```
ACTIVE_RUNTIME_PROCESS_COUNT   = 0        (PID 45868 gone; no process holds that DB)
ACTIVE_EXECUTION_WRITER_COUNT  = 0
ACTIVE_LEASE_OWNER_COUNT       = 0
LEASE_OWNER                    = engine_run_4b1a1f5d8b6e448685c4fdb9b5c955b0
LEASE_EXPIRES_AT               = 0.0      (released)
STALE_LEASE_SUSPECTED          = NO
```

No contradiction: 0 processes, 0 writer, 0 lease holder. (One unrelated runtime
is up on port 8123 from a different worktree, `growth-three-blockers`; it is not
this runtime and does not hold this lease.)

## 5. Consistency checks

```
DB_INTEGRITY_CHECK                    = ok
duplicate client_order_id             = 0
duplicate exchange_order_id           = 0
ACTIVE plans referencing a missing order = 0
nonzero position without ACTIVE plan  = 0
plans_with_order_id_not_in_orders     = 0
ACTIVE plan whose entry order is TERMINAL = 1  — EXPLAINED, not a defect
```

The single "terminal entry under an ACTIVE plan" is
`plan_ca0660c8…` (IOSTUSDT) whose entry `ord_cdfe3e48…` is `CANCELLED` after a
PARTIAL fill (86 of 3984). That is the intended F3 ENTRY-TTL outcome: the
remaining entry quantity expired while the factual position stayed open, and a
terminal entry order is exactly what lets position management act on it.

## 6. Recovery eligibility (static assessment, nothing started)

```
POSITION_RECOVERY_SUPPORTED    = YES  (F6 restores broker positions from the durable projection; the
                                        IOSTUSDT position has an ACTIVE plan and a linked order chain)
ORDER_RECOVERY_SUPPORTED       = YES  (both OPEN orders carry internal + client + venue ids and a
                                        remaining quantity; F6 rebuilds them verbatim in the broker)
PLAN_RECOVERY_SUPPORTED        = YES  (ACTIVE/APPROVED/PLANNED plan states are first-class; the ACTIVE
                                        plan's terminal entry order satisfies the position-action guard)
ACCOUNTING_RECOVERY_SUPPORTED  = YES  (60 fills + 66 ledger transactions are durable and idempotent;
                                        recovery never replays a fill)
COLD_START_RECOVERY_ELIGIBLE   = YES  — subject to the two notes below
```

Notes a recovery mission must carry forward:

1. `ord_4b4d845c…7328` is `UNKNOWN` **and** has no venue id. F6 will not restore
   it (an unknown status is not restored as open, and a missing broker identity
   is never invented); `RecoveryService.recover()` will find it absent on the
   fresh broker and mark it terminal with "no blind resubmit". That is the
   designed, safe outcome — but it must be observed, not assumed, at cold start.
2. `ord_f9edfa0a…b0b22` is an OPEN **SELL 3000 SOPHUSDT** while no SOPHUSDT
   position exists in the projection. Recovery will restore it as a resting
   order; reconciliation (and/or the position-action guard) is what surfaces it.
   No position or plan is fabricated for it.

## 7. This mission did not

```
RUNTIME_STARTED = NO
DEPLOYED        = NO
DB_MUTATION     = NONE (all queries on a /tmp copy; original files untouched)
ORDER_ACTION    = NONE
POSITION_ACTION = NONE
PRIVATE_EXCHANGE_ACTION = NONE
```
