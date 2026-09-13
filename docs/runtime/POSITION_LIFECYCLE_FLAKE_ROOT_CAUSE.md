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

No sleeps, no timeouts, no retries: `join()` simply waits until every event the
adapter emitted inline has been fully processed. Before the fix this test failed
**every single time**, with exactly the flaky symptom (`plan == APPROVED`,
venue order `FILLED`).

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
   `_sync_submitted_order_state`).
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

## 4. Production impact

**This was a real runtime defect, not a test-only artefact.**

In production the same window exists whenever the venue's event stream beats the
REST response plus the local commit — normal for a marketable order, since the
exchange can fill it before the local row records the venue order id. The
consequences were:

* a **factual fill missing from the local ledger and position projection**
  (silent divergence from the venue),
* a trade plan stuck at `APPROVED`,
* **position management wedged**: every subsequent REDUCE/EXIT blocked by the
  entry-order terminality guard,
* `ReconciliationService` detects such a divergence (`POSITION_MISMATCH`) but
  only *reports* it; it does not repair it.

Risk classification: high. Money-relevant state could be lost with no error, no
alert and no audit record.

## 5. Fix

`src/crypto_trader/runtime/engine.py`:

1. **Durable-identity fallback.** `process_exchange_event` resolves the local
   order by `exchange_order_id`, then falls back to the event payload's
   `client_order_id`, which **is** written before submission (and is uniquely
   constrained). The ack transition then persists the venue id, so all later
   events resolve by either key. Event delivery no longer depends on when the
   event happened to be dequeued — the race is removed, not narrowed.
2. **No silent loss.** An event that resolves to no local order now sets engine
   health and writes an `EXCHANGE_EVENT_UNMATCHED` audit record instead of
   returning invisibly.
3. **No invisible failures.** `_event_loop` records an `EXCHANGE_EVENT_FAILED`
   audit event (event type, ids, error type) in addition to flipping health, so
   a failed fill/ack/cancel can never again be lost without a durable trace.
4. **Dead code removed.** `_apply_exchange_order_fill` was deleted; it implied a
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

L1 is the direct root-cause regression: it failed 100 % of the time before the
fix and passes 100 % after.

## 7. Stress result

See the closure report accompanying this change for the measured numbers
(isolated root-cause test x100, lifecycle file x50, determinism suite x20,
order-varied runs x20, full suite x5). Instrumented runs after the fix show
`EVENT_DROPPED_LOCAL_ORDER_NOT_VISIBLE` for fills at **zero**, and no
`EXCHANGE_EVENT_FAILED` records at all.

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
4. **Auto scale-in remains disabled.** `OpenAction.ADD` is still refused
   (`LIVE_LLM_POSITION_ADD_REFUSED`); nothing in this change enables it.
