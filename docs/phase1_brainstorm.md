# PHASE  Lean Brainstorm Grill (auto)

Date: 2026-08-24 (harness clock)
Mode: AUTO-CONTINUE, no phase confirmation prompts.
Reference repos: read-only audit completed (see reference-source-baseline.md).

## 1. Product boundary (grill: what is IN / OUT)

IN (core system):
- Crypto-native event-driven automated trading infrastructure.
- Decimal-safe domain model (Price, Quantity, Money, Balance, Fee, PnL, CostBasis, Margin, Funding).
- Exchange-independent Adapter layer (Binance first; OKX/Bybit boundaries).
- Async order state machine with ack/fill reordering, idempotency, cancel/fill races.
- Append-only double-entry Ledger as the single source of money truth, with replayable projections.
- Pre-trade Risk engine + final ExecutionAuthority gate.
- Paper/Live/Shadow shared core; SimulatedExchangeAdapter for tests and paper.
- Run Lease (single writer), crash recovery, reconciliation, observability, FastAPI control plane.
- Pluggable StrategyPlugin interface with DummyStrategy/TestStrategy only.

OUT (non-goals):
- Alpha/strategy research: MACD, moving average, arbitrage, trend, AI prediction, coin selection, buy/sell point algorithms.
- Forking or copying whole SilverQuant/Kalshi repositories.
- A-share rules (100-share lots, T+1, ST, price limits, qfq, CN stamp tax, CN/HK session calendars).
- Kalshi-specific market/order semantics.
- UI trading algorithms (phase 1 has no UI requirement; a lightweight console would be read-only if added).
- Real-money orders during harness testing.

## 2. Architecture grill (questions asked, answers locked)

Q1. Where does money truth live?
A1. Only in the Ledger. Account/Position/PnL are projections rebuilt by replay. Direct balance mutation is forbidden.

Q2. Can a strategy call the exchange directly?
A2. No. Strategy -> SignalIntent -> Risk -> ExecutionAuthority -> OrderManager -> Adapter. No bypass.

Q3. Is place_order synchronous fill?
A3. No. Submission returns order state; fills arrive as async ExchangeEvents and are applied by the state machine.

Q4. How do we make orders idempotent?
A4. client_order_id unique in DB; same ID returns the existing business order; different payload for same ID is rejected with IdempotencyConflict. Retry after timeout = query/recover, never blind resubmit.

Q5. How do we handle ack/fill reordering and duplicate events?
A5. State machine transitions based on events, not arrival order assumptions. event_id and fill_id are unique constraints; duplicate application is a no-op. Fill may advance state before ACK; late ACK is recorded and ignored for transition.

Q6. What does the adapter own?
A6. Exchange JSON, auth, transport, retries, error-code mapping, symbol/order/fill normalization. Core never sees exchange-specific codes or JSON.

Q7. What happens on orderbook sequence gap?
A7. Book invalidated -> resync snapshot -> replay continuous deltas. If resync fails: MARKET_DATA_UNHEALTHY; ExecutionAuthority holds new orders.

Q8. What prevents dual-engine duplicate orders?
A8. Database-backed run lease: only one instance holds a valid, renewable execution lease; others run read-only and cannot write orders. Lease recovery after expiry is atomic (single UPDATE CAS).

Q9. What is the crash recovery contract?
A9. Never blind resubmit. Load open orders -> query exchange -> reconcile -> restore state -> resume. SUBMITTING/SUBMITTED are resolved by exchange query, not by placing new orders.

Q10. Where do float values live?
A10. Nowhere in financial core. All Price/Quantity/Money/Balance/Fee/PnL/CostBasis/Margin/Funding fields are Decimal. Float only at I/O boundaries where a third-party JSON parser already produced it, and it is immediately converted via string/Decimal before entering core.

## 3. Final architecture decision (free-dp-pro analysis)

Chosen architecture (edge weights = coupling + rework risk, dynamic-programming minimization):
- Layered hexagonal core: domain <- services <- adapters/runtime <- API.
- Ledger-first projections instead of mutable balances (chosen over mutable-state because replay/reconciliation/audit constraints dominate).
- Async state machine with persisted events (chosen over synchronous fill because WebSocket-first + recovery constraints dominate).
- One shared core for LIVE/PAPER/SHADOW with SimulatedExchangeAdapter implementing the same adapter contract (chosen over a separate paper engine because it eliminates divergent behavior; PaperBroker from SilverQuant is intentionally NOT copied as a separate core path).
- SQLAlchemy 2 async + SQLite(aiosqlite) for tests, PostgreSQL URL supported for production; Alembic migration as source of schema truth.

DP result: total complexity score 18 vs 31 (separate paper core) and 27 (float naive). Selected plan wins on invariants per complexity unit.

## 4. Non-negotiable invariants (from reference analysis)
1. Debits == Credits for every ledger transaction (journal balanced).
2. Every fill/event has a globally unique ID and is consumed at most once.
3. client_order_id maps to at most one business order.
4. A cancelled/rejected/expired order can never become OPEN again.
5. Kill switch ON => no new orders, regardless of all other checks.
6. Sequence gap => orderbook invalidated before any consumer can use it.
7. Only the execution lease holder may submit/cancel orders.
8. Projection state before replay == projection state after replay.
9. No Binary float in financial fields; Decimal arithmetic through canonical helpers.
10. Source repos SilverQuant, kalshi-paper-trader, kalshi-paper-trader-v2 remain untouched.

## 5. SPAC traceability
The decisions above are frozen into SPAC.md; any later code/SPAC drift is resolved by deciding whether code or SPAC is wrong, then syncing.
