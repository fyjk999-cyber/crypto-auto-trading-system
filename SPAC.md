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

## 17. Perpetual Futures Program (PHASE 17+)

New phases extend the existing core; they never create a second trading core or
second source of financial truth.

- Ledger remains the single source of financial truth. Perpetual margin,
  funding, liquidation, SHORT all enter the same append-only double-entry ledger
  and are replayed into projections.
- Instruments are separated into SPOT and PERPETUAL by `instrument_type`.
  SPOT SELL is never used to fake a perpetual SHORT.
- Position model: ONE_WAY first (LONG or SHORT net per symbol); HEDGE mode is
  explicitly deferred as a known limitation. All side transitions are
  deterministic, auditable, replayable.
- Margin: ISOLATED first, CROSS later. Mark price is used for risk/liquidation,
  not last trade price.
- Funding is a first-class ledger event (payment and receipt).
- Hard max leverage 6x; any alpha recommendation above 6x is capped or rejected.
- Leverage decision chain: recommended_leverage -> risk_capped_leverage ->
  review_approved_leverage -> effective_leverage, each recorded with
  original/new value, reason, authority, timestamp, policy version.
- Drawdown policy is configurable; DD >= 50% engages the global kill switch.
  Risk-reducing actions (REDUCE/CLOSE) always remain allowed.
- Trade governance levels L1-L4. L4 requires human approval; timeout rejects.
- Reviews are deterministic and structured; LLM may only assist explanations.
- Learning V2: Fast Learning updates statistics only; Slow Learning candidates
  must pass backtest -> OOS -> walk-forward -> paper -> shadow -> promotion.
  Self-modifying production code and self-modifying risk authority are forbidden.
- Backtest reuses the real MarketState/Alpha/Risk/Margin/Ledger interfaces.
- Defaults remain TRADING_MODE=PAPER and LIVE_TRADING_ENABLED=false.

## 18. Cloudflare Deployment (CLOUD PHASE)

- Cloudflare Worker `crypto-trading-gateway` is an edge gateway only: auth,
  routing, rate limiting, security headers, request IDs, WebSocket forwarding.
  No trading/risk/ledger/order logic in the Worker.
- Python trading core runs in a Cloudflare Container (`crypto-trading-primary`).
  DB Run Lease remains the single-writer guard; duplicate containers cannot both
  trade.
- Financial persistence remains PostgreSQL + Alembic. Ledger stays the single
  financial truth. D1 is not used for money facts.
- Cloudflare R2 stores backups only, never transactional data.
- Cloudflare Access protects the API. Codex receives a read-only service token
  (`crypto-codex-readonly`) limited to GET/HEAD/read WS; control endpoints are denied.
- Cron/Workflows only trigger backend endpoints idempotently; they never
  reimplement DailyReview, Learning, or Ledger logic.
- Environment: TESTNET. `LIVE_TRADING_ENABLED=false`. Real-money orders are forbidden.
- Worker/Container configs must match current Wrangler v4+ and Cloudflare
  Container lifecycle semantics (validated against official docs at implementation time).

## 19. LLM Chief Trader Architecture (PHASE 31+ amendment)

- LLM Chief Trader is the investment decision layer; quant models are Evidence
  Providers only. Legacy quant/AI fusion is retained only for shadow A/B and
  backtest comparison.
- LLM may decide LONG/SHORT/NO_TRADE/WAIT/ADD/REDUCE/EXIT/HEDGE and propose
  strategy, size, leverage, stop/take-profit, and invalidation conditions.
- LLM MUST NOT submit orders, modify Ledger/Order State, bypass Risk, change
  system risk limits, disable kill switch, or modify production strategy.
- Hard pipeline: LLM ChiefTrader -> TradeProposal -> ConvictionEngine ->
  RiskEngine -> ExecutionAuthority -> OrderManager -> ExchangeAdapter.
- Knowledge Base (theory/tools) and Experience Memory (what happened) are
  separate, versioned, auditable stores.
- Multi-coin paper learning first. LIVE_TRADING_ENABLED=false always.
- Decision traces must be replayable: context hash, market/quant/knowledge/
  memory versions, prompt, response, parsed decision, conviction, risk,
  execution decision.

## 20. PHASE 111-120 Capital Management & Real Market Validation Amendment

- Distinguish IMPLEMENTED / FRAMEWORK_READY / HISTORICAL_SIMULATION_VALIDATED /
  FORWARD_SHADOW_RUNNING / FORWARD_SHADOW_COMPLETE / EMPIRICALLY_VALIDATED / LIVE_READY.
- Capital allocation, portfolio risk, liquidity and execution planning are advisory
  layers. RiskEngine and ExecutionAuthority remain final authorities.
- Forward shadow must use real chronological data only. No future data leakage.
  Historical replay does not count as forward validation.
- 90 real calendar days of valid observations are required for
  FORWARD_SHADOW_COMPLETE.
- Micro-capital deployment requires manual human approval; no automatic live.
- Live trading remains disabled (LIVE_TRADING_ENABLED=false).
