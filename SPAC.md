#  Crypto Automated Trading System

> SPAC is the single source of truth for this project. When code and SPAC disagree, decide which one is wrong (code bug vs stale SPAC), fix the wrong side, and record the decision.

## 1. Project Goal
Build a **Crypto-Native Automated Trading Infrastructure** that is exchange-independent, event-driven, ledger-first, idempotent, and recoverable. The system reliably moves a signal through Risk -> ExecutionAuthority -> OrderManager -> ExchangeAdapter -> Ledger -> Projections with full auditability.

## 2. Non-Goals
- No alpha strategy development (no MACD, MA, arbitrage, trend, AI prediction, coin selection, buy/sell algorithms).
- No fork or wholesale copy of SilverQuant / Kalshi repos.
- No A-share semantics (lot size 100, T+1, ST, price limits, qfq, CN stamp tax, CN/HK session rules).
- No Kalshi-specific market semantics.
- No real-money orders during harness tests.
- Phase 1 has no UI requirement.

## 3. Architecture
Layered hexagonal core:

```
Market Event -> StrategyPlugin -> SignalIntent
  -> PreTrade Risk -> ExecutionAuthority
  -> OrderManager -> ExchangeAdapter
  -> Exchange Events -> Order State Machine -> Ledger
  -> Account/Position/PnL Projections -> Audit
```

- `domain/` unified objects only; no exchange JSON beyond adapters.
- `market_data/` orderbook snapshot+delta with sequence validation.
- `exchange/` ExchangeAdapter contract; Binance implementation; OKX/Bybit boundaries.
- `order/` async state machine and idempotent OrderManager.
- `ledger/` append-only double-entry ledger and replay projections.
- `portfolio/` read-model projections.
- `risk/` trading-system risk only; global kill switch.
- `execution/` final authority before any order leaves core.
- `runtime/` engine, event bus, run lease, scheduler, recovery, state machine, health.
- `simulator/` SimulatedExchangeAdapter (paper shares core; no second core).
- `reconciliation/` scheduled local-vs-exchange comparison.
- `persistence/` SQLAlchemy models, repositories, migrations.
- `observability/` structured logs + audit events.
- `api/` FastAPI control plane; routes only validate/auth/call service/respond.
- `strategy/` StrategyPlugin interface + DummyStrategy + TestStrategy.

## 4. Domain Model
Instrument, TradingPair, Price, Quantity, Money, Balance, OrderIntent, Order, OrderEvent, Fill, Trade, Position, Account, Fee, LedgerEntry, RiskDecision, ExchangeEvent.
All financial fields use `Decimal` (never binary float): Price, Quantity, Money, Balance, Fee, PnL, CostBasis, Margin, Funding.

## 5. Order Lifecycle
```
CREATED -> VALIDATED -> SUBMITTING -> SUBMITTED -> ACKNOWLEDGED -> OPEN
OPEN -> PARTIALLY_FILLED -> FILLED
OPEN -> PARTIALLY_FILLED -> CANCEL_PENDING -> CANCELLED
any active state -> REJECTED | EXPIRED | UNKNOWN
```
Supported behaviors:
- ack and fill arrival order may be reversed (fill may advance before late ack; late ack recorded).
- duplicate WebSocket events are no-ops via unique event_id/fill_id.
- REST timeout with unknown state => UNKNOWN -> query exchange -> reconcile; never blind resubmit.
- cancel/fill race: a fill that arrives in CANCEL_PENDING wins (fills the order); a fill after CANCELLED with remaining quantity is applied only when exchange truth wins and is audited.
- exchange rejection maps to REJECTED via adapter error model.

## 6. Ledger Model
Append-only double-entry journal is the single money truth.

Entry types: TRADE, FEE, DEPOSIT, WITHDRAWAL, TRANSFER, FUNDING, INTEREST, REALIZED_PNL, MARGIN_CHANGE.
Invariant per transaction: sum(DEBIT) == sum(CREDIT). Writes are atomic (all rows of a transaction commit or none). Ledger replay rebuilds AccountProjection, PositionProjection, PnLProjection; rebuild-before == rebuild-after.

Buy trade journal (p=price,q=quantity,f=fee):
- Dr POSITION_ASSET:{base} p*q
- Dr FEE_EXPENSE f
- Cr CASH p*q+f

Sell trade journal (c=cost released, g=gross proceeds p*q, f=fee, realized=g-c):
- Dr CASH g
- Cr POSITION_ASSET:{base} c
- Dr/Cr REALIZED_PNL realized (gain credit / loss debit)
- Dr FEE_EXPENSE f
- Cr CASH f

## 7. Exchange Adapter Contract
Methods: connect, disconnect, get_exchange_info, get_balances, get_positions, get_orderbook, get_ticker, submit_order, cancel_order, get_order, subscribe_market_data, subscribe_order_updates, subscribe_account_updates, normalize_symbol, normalize_order, normalize_fill.
Adapter owns transport/auth/retries and maps exchange-specific errors into domain errors: ExchangeUnavailable, RateLimited, AuthenticationError, InvalidOrder, InsufficientBalance, OrderNotFound, OrderRejected, StaleMarketData, SequenceGap, TemporaryNetworkError, UnknownExecutionState.
Binance implemented; OKX and Bybit expose adapter boundaries but are not implemented in phase 1.

## 8. Risk Boundaries
Trading-system risk only: max_order_notional, max_position_notional, max_account_exposure, max_open_orders, max_daily_loss, max_drawdown, max_leverage, max_symbol_exposure, max_exchange_exposure, max_consecutive_failures, plus GLOBAL KILL SWITCH. Kill switch ON => no new orders.

## 9. Runtime
Single-writer run lease stored in DB with renew/expire/recover. Only lease holder may submit or cancel orders. Engine loops over market events and adapter events through EventBus, and persists everything with run_id/order_id/client_order_id/exchange_order_id/event_id/timestamp context.

## 10. Recovery
Restart sequence: load open orders -> query exchange -> reconcile -> restore state -> resume. Never blind resubmit. SUBMITTING/SUBMITTED orders are resolved by exchange query. Ledger-before-projection and ledger-after-projection crashes are recovered by replay.

## 11. Data Model (minimum tables)
engine_runs, runtime_leases, orders, order_events, fills, trades, ledger_entries, accounts_projection, positions_projection, market_snapshots, reconciliation_runs, risk_decisions, audit_events.
Unique constraints: client_order_id, fill_id, event_id, transaction_id (ledger_transactions).

## 12. API
`/health`, `/ready`, `/runtime`, `/orders`, `/positions`, `/account`, `/ledger`, `/audit`. Routes are thin. Business logic lives in services/core only.

## 13. Testing
Each subchapter: implement -> unit tests -> pass -> next subchapter; no concurrent ad-hoc test runs. Each big chapter: run agent-project-test gate (code, functional, integration, regression, SPAC coverage). Required chaos suite is enumerated in tests/chaos and includes all 20 mandatory cases plus database integration tests.

## 14. Security
Default mode PAPER_TRADING. LIVE_TRADING_ENABLED defaults to false. No real-money orders in tests. Secrets only from environment/secret store; `.env.example` contains placeholders; no API keys are committed. Kill switch and lease are enforced server-side.

## 15. Definition of Done
All SPAC requirements implemented; pytest (unit + integration + chaos) green; decimal precision tests green; ledger invariants green; duplicate order protection green; partial fill, crash recovery, WebSocket resync, run lease, reconciliation, kill switch all green; paper automated E2E green; no real-money orders; no secrets committed; SOURCE_PROVENANCE complete; reference repos unchanged (SilverQuant modified: NO, Kalshi v1 modified: NO, Kalshi v2 modified: NO); GitHub repository created and main pushed; FINAL_REPORT.md written.

## 16. Alpha Layer (PHASE 16 amendment)

The strategy/alpha layer sits exclusively behind the `StrategyPlugin` boundary and
only emits `SignalIntent` / `TradeProposal`. It must never import or touch
Ledger, OrderManager, submit_order, cancel_order, or private exchange execution APIs.

Pipeline:
Exchange Market Data -> Market Data Engine -> Feature Engine -> Regime Engine
-> Multi-Strategy Alpha (Trend 40% / Momentum 20% / Breakout 15% / MeanReversion 10% / FundingBasis 15%)
-> ML Meta (ensemble weights, confidence calibration, meta decision)
-> Meta Decision -> Confidence -> Position Sizing -> Dynamic Leverage
-> SignalIntent -> Risk -> High-Risk Review -> ExecutionAuthority -> OrderManager -> ExchangeAdapter
-> Trade Result -> Performance / Memory / Learning.

Rules:
- ML Meta is not a 5% directional sub-strategy. It operates after the ensemble.
- Base weights: Trend 40%, Momentum 20%, Breakout 15%, MeanReversion 10%, FundingBasis 15%.
  Per-decision effective weights may be adjusted by Regime + Performance + ML Meta;
  production base weights only change via the Slow Learning promotion pipeline.
- Fast Learning updates strategy performance, confidence calibration, failure memory,
  and regime statistics only. It must not directly modify production strategy parameters.
- Slow Learning candidates must pass: backtest -> out-of-sample -> walk-forward -> shadow -> promotion.
- alpha/sizing.py and alpha/leverage.py only output recommended_position and
  recommended_leverage. Final authority remains Risk -> ExecutionAuthority.
- LONG/SHORT are fully symmetric; NO_TRADE is a first-class decision.
- All financial values Decimal-only; no future leakage; every regime/feature/strategy
  output carries timestamp/version/reason_codes; every decision is replayable/auditable.
