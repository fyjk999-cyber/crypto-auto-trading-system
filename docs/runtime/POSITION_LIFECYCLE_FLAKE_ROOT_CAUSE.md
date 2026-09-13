# Position Lifecycle Timing Flake — Root Cause & Closure

Status: **CLOSED**
Branch: `codex/position-lifecycle-flake-fix`
Base: `79f339b3dc98752acade8a89ac467ef5569dcefd` (frozen Position Sizing V2 + scale-in candidate)

---

## 1. Symptom

`tests/integration/test_live_llm_position_lifecycle.py` (and one episode test in
`tests/integration/test_v4_review4.py` that reuses its
`_close_engine_lifecycle` helper) failed intermittently — never in a way that
reproduced on demand. Observed failing assertions, all on the same theme:

| assertion | observed | meaning |
|---|---|---|
| `plan.state == ACTIVE` | `APPROVED` | the entry never settled |
| `position is not None and position.quantity == 0.1` | `None` / `0.06` | the entry/exit projection was wrong |
| `closed_position.quantity == 0` | `0.06` | an exit only partly landed |
| `expected is not None` | `None` | a restarted position was missing |
| `len(created) == 1` (position action) | `0` | a review produced no order |

Measured before the fix:

* lifecycle file alone: 11 clean runs, 1 failure observed (≈8 %)
* full suite: 2 failures in 13 runs (≈15 %)
* `v4_review4.py` episode test: 1 failure
* isolated file runs on the base commit: 5/5 clean

It was never reproducible on demand, never accompanied by a stack trace (the
failing assertion was always a *downstream* observation), and never failed in
the same test twice.

## 2. Exact reproduction

Probability was replaced by causality. `tests/integration/test_position_lifecycle_determinism.py`
(L1) drives the engine with an adapter that drains the engine's event queue
*inside* `submit_order`:

```python
class InlineEventDrainedAdapter(SimulatedExchangeAdapter):
    async def submit_order(self, order):
        result = await super().submit_order(order)
        if self.event_gate is not None:
            await asyncio.wait_for(self.event_gate.join(), timeout=10)
        return result
```

`join()` waits until every event the adapter emitted inline has been fully
processed, so the reproduction depends on no sleep, no retry and no wall-clock
threshold. The `asyncio.wait_for(..., timeout=10)` in the harness is a bounded
hang guard only; it is never the mechanism. Its one side effect is that a
stalled event loop would surface as a `TimeoutError` out of `submit_order`
rather than as "event loop stalled" — a harness-only concern, since the gate
exists only in the test.

Before the fix this reproduction failed **every single time** (measured: 20/20
and 10/10 on the unfixed base, with the resolved engine module asserted to be
the base tree's), with exactly the flaky symptom (`plan == APPROVED`, venue
order `FILLED`).

Because *which* interleaving the scheduler picks is ultimately not something a
test can own, the contract is ALSO pinned without any timing dependence by L18,
which places one order row in exactly the race-window state (submitted locally,
no venue id persisted) and dispatches the fill. L18 fails deterministically on
the unfixed revision and passes on the fixed one.

Instrumentation of a *passing* run showed the leak is normally present but
mostly benign:

```
   51 FILL_EVENT_LOCATED
   23 EVENT_DROPPED_LOCAL_ORDER_NOT_VISIBLE   (all ORDER_ACK)
```

In the deterministic reproduction the same instrumentation showed the fatal
variant:

```
DROP ORDER_ACK      exchange_id=sim_86e9… client_id=live_llm_race-entry-1
DROP ORDER_OPENED   exchange_id=sim_86e9… client_id=live_llm_race-entry-1 filled=0.1
DROP ORDER_FILLED   exchange_id=sim_86e9… client_id=live_llm_race-entry-1 fill_qty=0.1
```

The fill — a factual, irreversible venue event — was discarded.

## 3. Root cause

**Classification: `B. REAL_RUNTIME_RACE`** (primary), realised through
`E. DB_TRANSACTION_VISIBILITY` and `G. EVENT_LOOP_SCHEDULING`.

The causal chain, in order:

1. `TradingEngine.process_signal` submits an order at
   `exchange_order = await self.adapter.submit_order(order)`
   (`src/crypto_trader/runtime/engine.py`).
2. The exchange adapter emits `ORDER_ACK`, `ORDER_OPENED` and
   `ORDER_PARTIALLY_FILLED`/`ORDER_FILLED` events **inline, while
   `submit_order` is still in flight** (this is documented in
   `_sync_submitted_order_state`). In this revision the adapter that actually
   does so is `SimulatedExchangeAdapter`; see §4 for what that means for live
   adapters.
3. The engine's background `_event_loop` task consumes those events
   concurrently. Every handler began with
   `local = await self.order_manager.get_by_exchange(exchange_order_id)`.
4. `exchange_order_id` is only persisted **after** `submit_order` returns, in
   `_sync_submitted_order_state` → `order_manager.ack(...)`.
5. Therefore any event consumed inside that window resolved to `None`, and the
   handler executed `return` — **the event was dropped, permanently and
   silently**.
6. `_apply_exchange_order_fill` — the only apparent catch-up — was **dead code
   with no caller**, so nothing ever re-applied a lost fill.

Which events fell inside the window depended purely on how the asyncio scheduler
interleaved the submitting coroutine with the event consumer. In the common case
only `ORDER_ACK` was dropped, which `_sync_submitted_order_state` re-applies
afterwards, so the loss was invisible. Under different scheduling the window
also swallowed `ORDER_OPENED` and `ORDER_FILLED`, and the fill was gone.

The damage is not confined to the fill itself: because the trade plan only
becomes `ACTIVE` on a settled entry, and because the position-action guard
requires the local entry order to be in `TERMINAL_ORDER_STATUSES`, a lost fill
left the plan `APPROVED` and **blocked every subsequent REDUCE/EXIT** — which is
exactly the family of assertions that failed.

### Why it was intermittent

Two coroutines race: the submitter (which must reach the post-submit DB write)
and the event consumer (which must resolve the order before that write lands).
The winner is decided by event-loop scheduling, so the outcome varies with
machine load, suite length and unrelated I/O — the flake correlated with
full-suite runs and with concurrent work, and never reproduced in a short
isolated run.

### Why it was silent

`_event_loop` wrapped `process_exchange_event` in `except Exception` and still
called `task_done()` in `finally`. The queue therefore always drained, so
`wait_for_event_queue()` — the tests' synchronisation primitive — reported
success even when the fill had been lost. A dropped *matching* failure was
equally invisible: the handler simply returned.

## 4. Impact

**Classification of impact: PAPER-runtime defect today; latent live-adapter
defect tomorrow.** The reviewer of the first revision of this document was right
to reject an earlier, stronger claim, and the corrected scope is:

* **Reachable today (PAPER).** `SimulatedExchangeAdapter` emits `ORDER_ACK`,
  `ORDER_OPENED` and `ORDER_FILLED` inline from inside `submit_order`, and those
  payloads carry `exchange_order_id`, so they reach the affected code path. A
  dropped fill in PAPER corrupts the paper ledger/position projection, wedges the
  trade plan at `APPROVED`, and blocks every later REDUCE/EXIT through the
  entry-order terminality guard. This is exactly the flake that was observed.
* **A real runtime race, not a test artefact.** The defect lives in the engine's
  event/identity contract, and it is exercised by production code paths — not
  only by tests.
* **NOT a live-money defect in this revision.** No live adapter wired in this
  repository emits routable normalized order events:
  `exchange/okx.py::subscribe_order_updates` registers a handler but nothing in
  the OKX adapter ever emits an `ExchangeEvent`; `exchange/binance.py::
  dispatch_raw_event` emits `{"raw": ...}` payloads (no `exchange_order_id`) and
  has no caller; the only `ExchangeEvent` constructors in `src/` are
  `exchange/base.py` and `simulator/exchange.py`. So the "silent divergence from
  a real venue" scenario is a **precondition, not a present fact**: it becomes
  live the moment a live adapter is wired to emit normalized order events.
  Closing it now is precisely why the fix belongs in the engine contract rather
  than in the simulator.

Severity if the precondition is met: high. Money-relevant state could be lost
with no error, no alert and no audit record.

## 5. Fix

`src/crypto_trader/runtime/engine.py`:

1. **Durable-identity fallback, with validated binding.**
   `process_exchange_event` resolves the local order by `exchange_order_id`, then
   falls back to the event payload's `client_order_id`, which **is** written
   before submission (and is uniquely constrained). The ack transition then
   persists the venue id, so all later events resolve by either key. Event
   delivery no longer depends on when the event happened to be dequeued — the
   race is removed, not narrowed.
   The binding is **validated, never assumed**: a local row that already carries
   a *different* venue order id belongs to a different order, so the event is
   refused and audited as `EXCHANGE_EVENT_ID_MISMATCH` rather than applied.
   Without that guard the fallback would have traded "drop the event" for
   "misapply it" — a misrouted or replayed event could rewrite a real order's
   fills and venue identity.
2. **No silent loss — for events that carry an order identity.** An event that
   resolves to no local order writes an `EXCHANGE_EVENT_UNMATCHED` (or
   `EXCHANGE_EVENT_ID_MISMATCH`) audit record instead of returning invisibly, and
   a payload that contradicts the order it resolved to (different symbol form or
   different client order) is refused and audited the same way. Symbol
   comparison is canonical (the adapter's own `normalize_symbol`, with a
   case-insensitive fallback), so a naming variant accepts rather than wedges.
   Scope limit, stated honestly: an order event with **no** `exchange_order_id`
   at all still returns before this path — it is not silent *by design*, it is
   simply not routed here. `BinanceAdapter.dispatch_raw_event` is such a shape
   and currently has no caller; wiring it as-is would need this addressed first.
   Health is deliberately **not** touched by any of these anomalies: the consumer
   is working, and one foreign/replayed event is not a component failure. They
   are counted in `runtime_snapshot()["exchange_event_identity_anomalies"]` and
   audited instead.
3. **No invisible failures, and no latched health.** `_event_loop` records an
   `EXCHANGE_EVENT_FAILED` audit event (event type, ids, error type) in addition
   to flipping health, and the next successfully processed event clears
   `event_processing` again. Before this, a single failed event would have pinned
   engine health for the life of the process, because `HealthRegistry.overall()`
   is an AND over every component.
4. **Account-scoped events are reachable.** `BALANCE_UPDATE` is now handled
   before the order-identity requirement. It carries no exchange order id, so as
   written the branch was unreachable.
5. **Dead code removed.** `_apply_exchange_order_fill` was deleted; it implied a
   catch-up that never ran.

Explicitly **not** done: no timeout was increased, no assertion relaxed, no
retry/sleep added, no lifecycle guard removed. The ordering/terminality rules,
TIME_STOP boundary, pending-action dedupe and reconciliation cadence are
untouched.

## 6. Regression tests

`tests/integration/test_position_lifecycle_determinism.py` — L1–L12:

| id | guarantee |
|---|---|
| L1 | the inline-fill scenario settles deterministically, with no sleep |
| L1b | an unmatchable event is auditable, never silent |
| L2 | TIME_STOP outranks ADD at the factual holding boundary |
| L3 | ADD remains explicitly refused, audited, zero orders |
| L4 | a pending ADD cannot fall through into REDUCE |
| L5 | HOLD creates no order |
| L6 | REDUCE is reduce-only and bounded by the position |
| L7 | EXIT precedence is deterministic at three clock offsets |
| L8 | a partially filled entry blocks a conflicting action |
| L9 | a lifecycle run leaves zero background tasks |
| L10 | repeated runs produce an identical final state |
| L11 | a prior lifecycle on the same database does not change the next one |
| L12 | the clock boundary exactly at TIME_STOP is deterministic |
| L13 | an event bound to another venue order is refused, not applied |
| L14 | an anomaly is audited; a real processing failure marks health unhealthy and the next good event recovers it |
| L15 | account-scoped balance updates (no order id) are reachable |
| L16 | a payload that contradicts the order it resolved to is refused |
| L17 | identity anomalies are counted in the runtime snapshot (pageable, non-latching) |
| L18 | a fill arriving before the venue id is durable still lands (no timing dependence) |
| L19 | a symbol naming variant is accepted, not refused (the guard cannot wedge a plan) |

L1 is the direct root-cause regression: it failed 100 % of the time before the
fix (20/20 on the unfixed base) and passes 100 % after (100/100). L1 also asserts
that a settled entry leaves **zero** `EXCHANGE_EVENT_UNMATCHED` /
`EXCHANGE_EVENT_ID_MISMATCH` / `EXCHANGE_EVENT_FAILED` records, so a silently
tolerated event cannot pass. L13–L15 close the defects found when the first
revision of this fix was independently reviewed.

## 7. Stress result

Measured on the fixed revision unless stated otherwise; each figure is
reproducible with the command in parentheses.

| measurement | result | command |
|---|---|---|
| root-cause test on the UNFIXED base | 20/20 and 10/10 **fail** | `pytest "tests/integration/test_position_lifecycle_determinism.py::test_L1_lifecycle_transition_is_deterministic_without_any_sleep"` in a worktree at the base SHA (assert the resolved `crypto_trader.runtime.engine.__file__` first) |
| root-cause test on the fixed revision | 100/100 **pass** | same test, 100 iterations |
| determinism suite (L1-L18) | 60/60 clean | full file, 60 iterations |
| lifecycle file | 30/30 and 50/50 clean | `pytest tests/integration/test_live_llm_position_lifecycle.py` |
| order-varied context | 20/20 clean | lifecycle file adjacent to `test_order_reconciliation.py`, both orders |
| full suite | 1546 passed x3, then 1549 passed x3 | `pytest -q` (external OKX file included; it failed on the network in one earlier run and is classified separately) |

Instrumentation of a passing run BEFORE the fix showed 23
`EVENT_DROPPED_LOCAL_ORDER_NOT_VISIBLE` records, all `ORDER_ACK`, plus the fatal
`ORDER_FILLED` drop (`fill_quantity=0.1`) in the deterministic reproduction.
After the fix, fills are never dropped and no `EXCHANGE_EVENT_FAILED` record is
produced.

## 8. Remaining limitations

1. **Reconciliation does not repair.** `ReconciliationService` reports position
   mismatches but never re-applies a missing fill. The cause of such a mismatch
   is fixed; a venue that never delivers a fill message at all is still an
   unhealed case (`J. EXTERNAL_IO_DEPENDENCY`). A durable fill-repair path is a
   separate mission.
2. **Real-time review timeout.** `_review_positions_once` wraps each review in
   `asyncio.wait_for(..., timeout=30.0)`, which is wall-clock while the injected
   clock is virtual. On a machine stalled for >30 s this could suppress a review
   and back it off. It was not observed and is not the root cause, but it is a
   genuine clock-source inconsistency worth a dedicated review.
3. **`_event_loop` still swallows exceptions** (availability is deliberate: one
   bad event must not kill the consumer). It now records them durably instead —
   including market-data events, which is a deliberate trade-off: a feed that
   raises repeatedly will add audit rows, and that evidence is preferred over
   silence. If audit volume ever becomes a problem, the right fix is bounded
   aggregation (`health` already carries the current state), not removing the
   record.
4. **A live adapter still has to be wired.** No live adapter in this revision
   emits routable normalized order events, so the engine fix is a precondition
   for going live rather than a fix to a running live path. That wiring must
   demonstrate the identity contract (durable `client_order_id` on every order
   event) when it happens.
5. **Identity anomalies are audited and counted, not alerted.** A single
   unmatched/foreign event must not latch engine health (that was worse), and a
   systemic identity failure would leave `event_processing` OK. The count is
   therefore surfaced as `runtime_snapshot()["exchange_event_identity_anomalies"]`
   and every anomaly is an audit row, so a growing count is pageable — but no
   threshold, alert rule or dashboard consumes those yet. Adding rate-based
   alerting (or splitting the health component by event class) is a follow-up.
6. **Auto scale-in remains disabled.** `OpenAction.ADD` is still refused
   (`LIVE_LLM_POSITION_ADD_REFUSED`); nothing in this change enables it.
