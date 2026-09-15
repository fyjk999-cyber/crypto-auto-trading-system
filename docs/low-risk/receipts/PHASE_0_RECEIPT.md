# PHASE 0 RECEIPT — FORENSIC ARCHITECTURE MAP

Status: **PASS** (in-place evolution map established; no invasive V2 code written before this receipt)
Date: 2026-09-16 (+08:00)

## 0. Reproduction facts

| Item | Value |
|---|---|
| REPOSITORY | `fyjk999-cyber/crypto-auto-trading-system` |
| STARTING_SHA | `de5c5f7571fdfc37297101aa3915e786279909ac` |
| TARGET BRANCH | `codex/final-canonical-ai-runtime-bootstrap` (remote head = STARTING_SHA) |
| AUTHORITATIVE SPEC | `docs/low-risk/LOW_RISK_V2_MASTER_SPEC.md` @ `de5c5f75` (505 lines) |
| SPEC REWRITE COMMIT | `de5c5f7571fdfc37297101aa3915e786279909ac` (ancestor of working HEAD, verified) |
| IMPLEMENTATION BRANCH | `codex/low-risk-v2-inplace-evolution` |
| IMPLEMENTATION WORKTREE | `/Users/huhongjie/Documents/ChatGPT/crypto-low-risk-v2` (linked worktree of the canonical clone) |
| REMOTE_REF | `origin/codex/final-canonical-ai-runtime-bootstrap` = `de5c5f75` (`git ls-remote` verified) |
| MIGRATION HEAD | `0023_opportunity_lineage` (down_revision `0022_episode_risk_lineage`), 23 migration files |
| DATABASE AT AUDIT | worktree `data/crypto_trader.db` **absent** (fresh). No runtime was started for audit; no DB mutation. |
| RUNTIME SHA ON THIS WORKTREE | none running (audit is read-only; no engine started) |
| TEST BASELINE | `PYTHONPATH=src .venv/bin/python -m pytest tests -q` → **653 passed, 1 warning, 75.70s** (log `/tmp/lr_v2_phase0_pytest.log`) |
| PYTHON | 3.11+ required; verified with canonical venv Python 3.12.13; `PYTHONPATH=$PWD/src` resolves `crypto_trader` to this worktree |

Commands used to establish identity:

```
git -C <canonical clone> fetch origin codex/final-canonical-ai-runtime-bootstrap
git ls-remote origin | grep final-canonical-ai-runtime-bootstrap   # de5c5f75…
git worktree add -b codex/low-risk-v2-inplace-evolution <wt> de5c5f75
git rev-parse HEAD                                                  # de5c5f75…
git merge-base --is-ancestor de5c5f75 HEAD                          # YES
```

No `low_risk_v2` package, table, runtime, ledger or parallel memory store exists on this branch. V2 must be built by extending `crypto_trader`.

---

## 1. Package / module tree (target branch)

### runtime (`src/crypto_trader/runtime/`)
- `engine.py` (1248 lines) — `TradingEngine`: `start()`, `stop()`, `tick()`, `_tick_loop()`, `_event_loop()`, `_lease_loop()`, `_reconciliation_loop()`, `_strategy_context()`, `process_signal()`, `process_exchange_event()`, `_settle_fill()`, `_sync_terminal_entry_plan(s)()`, `_run_recovery()`, `_seed_initial_balances()`, `_load_instruments()`, `_restore_paper_adapter_state()`, `runtime_snapshot()`.
- `bootstrap.py` (259) — `build_system(settings) -> RuntimeBundle` wires the entire canonical graph (DB, ledger, portfolio, order manager, market data, risk, lease, reconciliation, audit, adapter, evidence router, opportunity scanner, trade plans, chief engine/provider, position manager, `TradingEngine`).
- `recovery.py` (200) — `RecoveryService.recover()`, `_resync_sim_from_ledger()`, `_close_orphan_positions()`; `event_type_for_exchange_status()`.
- `lease.py` — `Lease`, `LeaseManager.acquire/renew/release/is_held/is_current/status` (token + `fence_generation`, TTL 10s / renew 3s in `Settings`).
- `event_bus.py` — `EventBus.subscribe/publish`.
- `state_machine.py` — `RuntimeStateMachine.transition`.
- `health.py`, `local_runner.py` (FastAPI host), `scheduler.py` (`DailyReviewScheduler`), `supervisor.py`.
- `ai_position_bridge.py` — `AIPositionRuntimeBridge` (legacy AI-brain adapter; NOT wired into `RuntimeBundle`; evidence/decision-only, never executes).

### domain / order / trade plan / persistence
- `domain/enums.py` — `OrderSide`, `OrderType`, `TimeInForce`, `OrderStatus` (CREATED…UNKNOWN), `OrderEventType`, `LedgerEntryType`, `TradingMode`, `RuntimeState`, `MarketDataStatus`, `ExchangeEventType`, `ExecutionDecision` (APPROVE/SCALE_DOWN/HOLD/REJECT), `HealthStatus`.
- `domain/models.py` — `Instrument`, `OrderIntent`, `OrderEvent`, `Order` (+`remaining_quantity`), `Fill`, `Trade`, `Position`, `Balance`, `Account`, `LedgerEntry/Transaction`, `RiskDecision`, `ExchangeEvent`, `SignalIntent`, `MarketSnapshot`.
- `domain/money.py` (`D`, `round_tick`, `floor_to_step`, `format_decimal`, `StrictDecimal`), `domain/identifiers.py` (`new_id(prefix)`), `domain/errors.py`, `domain/clock.py`.
- `order/manager.py` — `OrderManager.create_from_intent()` (idempotent per `client_order_id`, `_reuse_or_conflict`), `transition`, `validate/submitting/submitted/ack/opened/cancel_pending/cancel_confirm/reject/expire/mark_unknown`, `apply_fill` (fill-id unique), `has_pending_position_action()`, `get_by_client()`, `get_by_exchange()`.
- `order/state_machine.py` — order status transition table.
- `trade_plan/service.py` — `TradePlan` dataclass, `TradePlanState` (PLANNED/APPROVED/ACTIVE/REJECTED/CANCELLED/EXPIRED/INVALIDATED/CLOSED), `TradePlanService.create/get/get_by_order/get_active_for_symbol/transition/link/link_position_decision`.
- `persistence/models.py` — 60 SQLAlchemy tables (list in §8); `persistence/database.py` — `Database.init_schema`, WAL/busy-timeout settings.

### market data / factors
- `market_data/service.py` — `MarketDataService` (per-symbol `OrderBook` cache, `ingest_snapshot`, `is_fresh`, `is_healthy`).
- `market_data/okx_public_feed.py` (288) — `OKXPublicMarketFeed.warmup()`, `refresh(symbol)` → `MarketState` from `/tickers`, order book, `/mark-price`, `/index-price`, `/funding-rate`, `/open-interest`; `_update_source_ages`, `_update_realized_volatility`; per-source `SourceStatus` health.
- `market_data/state.py` — `MarketState` (price/mark/index/best_bid/best_ask/spread/depth/imbalance/trade_volume/volume/funding_rate/OI/OI-change/basis/realized_volatility/source health/generation/`new_risk_allowed`), `SourceStatus`, `DataHealth`.
- `market_data/orderbook.py` — `OrderBook` snapshot/delta, `mid_price`, health.
- `market_data/public_feed.py`, `market_data/websocket.py` — feed abstractions.
- `market_data/new_risk_gate.py` — `can_add_risk()`, `classify_order_action()`, `new_risk_blocked_for_action()` (stale data blocks new risk only, never reduce/close).
- `market_data/opportunity/` — `universe.py` (`OkxUniverseManager` full USDT-swap universe), `scanner.py` (`FactorScanner`, `FactorCandidate`, `RotationScheduler`, `ScanStats`), `factors.py` (9 evidence factors: Momentum/Breakout/Volume/MeanReversion/Volatility/Funding/OI/OrderbookImbalance/LiquidityAnomaly; `validate_no_direction_semantics()` hard evidence-only guard), `board.py` (`OpportunityBoard`), `eligibility.py`, `service.py` (`OpportunityScannerService.run_forever`), `context.py`.
- `factors/` — `registry.py` (7 built-ins), `catalog.py`, `calculators/{momentum,trend,volatility,volume,orderflow,funding,open_interest}.py`, `regime/{classifier,detector,history,models}.py`, `anomaly/{detector,rules,history,models}.py`, `engine.py`, `service.py`, `models.py`, `analytics.py`, `confidence/decay/importance/lifecycle/…`, 9 test files under `tests/factors/`.

### AI / LLM / decision / risk
- `llm_chief/provider.py` (249) — **`LLMProvider` Protocol** (`complete_json`, `healthy`) and `DeepSeekProvider` (single provider; one bounded retry; JSON object response; diagnostics per operation).
- `llm_chief/engine.py` — `ChiefTraderEngine.select_tools()`, `decide()`, `fail_closed()`, `render_prompt()`, `parse_decision()`.
- `llm_chief/decision.py` — `ChiefTraderDecision` (FLAT: LONG/SHORT/NO_TRADE/WAIT/FAIL_CLOSED; OPEN: HOLD/REDUCE/EXIT/FAIL_CLOSED) + validator.
- `llm_chief/runtime_strategy.py` (419) — `LiveLLMDecisionStrategy` (`strategy_id="live_llm"`): evidence → Chief → `LLMDecisionStore` → TradePlan → `SignalIntent`; per-symbol attempt cooldown; `desired_symbol()` agenda from `OpportunityBoard`.
- `llm_chief/position_manager.py` (267) — `LiveLLMPositionManager` (`strategy_id="live_llm_position"`): OPEN-position review → HOLD/REDUCE/EXIT (+`TIME_STOP_SAFETY_FALLBACK`), reduce-only `SignalIntent`.
- `llm_chief/trade_planner.py` — `LiveLLMTradePlanner.create_entry_signal()` (TradePlan before SignalIntent; never executes).
- `llm_chief/decision_store.py` — `LLMDecisionStore` (`llm_decisions` table).
- `llm_chief/context_loader.py`, `context.py`, `knowledge.py`, `memory.py`, `conviction.py`, `coin_profile.py`, `temporal_guard.py`, `tool_orchestrator.py`, `engines.py`, `persistence.py`.
- `deepseek/` — legacy `DeepSeekClient` (`client.py`), `decision_engine.py`, `schemas.py`, `market_selector.py`, `risk_committee.py`, `context_builder.py` (not the primary runtime path).
- `ai_decision/` — `AIDecisionEngine.decide()` + `fuse()` + `resolve_conflict()` (declares “No direct execution”; small, not wired as authority).
- `ai_risk/` — `RiskPolicy` (max_position_pct 10, max_leverage 5), `AIRiskCommittee.review()` (APPROVE/REDUCE/REJECT with `max_leverage`/`max_position` resize), `ApprovalRecord`.
- `risk/engine.py` (299) — `RiskEngine.check()`: kill switch; reduce-only validation (`REDUCE_ONLY_NO_POSITION/DIRECTION_REVERSAL/CROSSES_ZERO`); notional/leverage clamps (`SCALE_DOWN`); open-order/daily-loss/drawdown/symbol/account/exchange exposure limits; returns `RiskDecision`.
- `risk/kill_switch.py` (`KillSwitch`), `risk/leverage.py` (`clamp_leverage`).

### execution / broker / simulator / portfolio / ledger
- `execution/authority.py` (143) — `ExecutionAuthority.authorize(intent, ctx) -> (ExecutionDecision, notes)`; `AuthorizationContext` with 13 gates: lease, mode/live-enable, kill switch, reconciliation halt, order expiry, market/orderbook freshness+health, symbol tradeability, exchange connection, balance freshness, order state validity, duplicate client id, **`risk_decision` APPROVE/SCALE_DOWN**, precision/min-qty/min-notional, rate-limit budget.
- `execution/rate_limiter.py`, `execution/cross_exchange_guard.py`.
- `simulator/exchange.py` — `SimulatedExchangeAdapter` (PAPER matching engine, inline event emission, balances/positions/ledger).
- `simulator/real_market_paper.py` — `PaperRealMarketAdapter` (`PAPER_REAL_MARKET`): real OKX public books drive paper fills; factual instrument universe; fail-closed on unavailable book.
- `portfolio/` — `PortfolioService` (positions/account projections), `exposure.py` (`ExposureService`, `InstrumentExposureSpec`), `capital.py`, `correlation.py`, `allocator.py`.
- `ledger/` — `service.py`, `projections.py` (`replay_projections`), settlement path from `TradingEngine._settle_fill`.
- `reconciliation/service.py` — `ReconciliationService.reconcile(adapter)`: compares ledger projection vs exchange balances/positions; `halt=True` on BALANCE/POSITION_MISMATCH; persists `reconciliation_runs`.
- `observability/audit.py` — `AuditService.log(...)` → `audit_events`.

### Growth / memory / review (found by behavior, not folder name)
- `governance/trade_episode.py` — `FactualTradeEpisode`, `TradeEpisodeStore.build_for_closed_plan()` (canonical closed-lifecycle facts), `load_closed_on()`, `mark_reviewed()`.
- `learning/` — `TradeEvaluator`, `MistakeLog`, `PatternMemory`, `TradeReview`, `MistakeRecord`, `LessonRecord`.
- `llm_chief/memory.py` — `ExperienceMemory` (`store_episode`, `update_pattern`, `similar_episodes`, `compress_experience`); `llm_chief/knowledge.py` — `KnowledgeBase` (`add_strategy`, `add_tool`, `add_document`, `retrieve`).
- `ai_memory/` — `embedding.py`, `market_memory.py`, `similarity.py`; `vector_memory/` — `embedding_provider.py`, `retrieval.py`, `schemas.py`, `vector_store.py`; `memory_graph/`, `memory_governance/`.
- `daily_report/`, `runtime/scheduler.py` (`DailyReviewScheduler`), API `/reviews`, `/daily-reviews`, `/learning`, `/trade-episodes`.
- Tables: `trade_episodes`, `trade_memory_records`, `daily_review_runs`, `ai_trade_episodes`, `ai_trade_reviews`, `ai_market_patterns`, `ai_coin_profiles`, `ai_compressed_experience`, `llm_strategy_cards`, `knowledge_relations`, `knowledge_decay`.
- **No `growth/` package exists on this branch and no file contains the token “growth”.** Growth V2 must EXTEND the above episode/review/memory primitives (see §11).

### API / frontend
- `api/app.py` (1007) + `api/deps.py` (171) — FastAPI app and `AppState`; ~70 routes incl. `/health`, `/llm/health`, `/llm/decisions`, `/trade-plans`, `/trade-episodes`, `/opportunity/*`, `/orders`, `/positions`, `/account`, `/ledger`, `/risk`, `/reviews`, `/daily-reviews`, `/learning`, `/killswitch`, `/manual-orders`, `/ws`.
- `frontend/` (Vite + React + TS): `src/App.tsx`, `pages/`, `components/`, `api/`, `hooks/`; no hedge/leg presentation exists (grep hedge/leg → none). Net position presentation only.

---

## 2. Every order / new-risk creation path (exhaustive)

`SignalIntent` creation sites (grep, whole `src/`):

1. **Canonical entry** — `llm_chief/runtime_strategy.py` `LiveLLMDecisionStrategy.on_market_data()` → `LiveLLMTradePlanner.create_entry_signal()` (`trade_planner.py:59`). Runs only through `TradingEngine.tick()` → `process_signal()`.
2. **Canonical position management (reduce-only)** — `llm_chief/position_manager.py:201` (`LiveLLMPositionManager.review`), `strategy_id="live_llm_position"`, `metadata.reduce_only=True`.
3. **Manual API** — `api/app.py:896` `/manual-orders`, `strategy_id="manual_api"`; returns HTTP 403 when `engine.enforce_llm_entry_authority` (true whenever `auto_start_runtime`, i.e. the deployed PAPER runtime).
4. **Test-only** — `strategy/test_strategy.py:43`, `strategy/dummy.py` (`DummyStrategy`, installed only when `auto_start_runtime=False`).

`TradingEngine.process_signal()` (`engine.py:522`) is the **only** path to `ExecutionAuthority` and `adapter.submit_order()`. Authority chain inside it:
`enforce_llm_entry_authority` strategy allow-list (`live_llm`, `live_llm_position`) → idempotent client-id check → TradePlan existence/shape validation (entry) → position/reduce-only validation (position action) → factual book refresh → `RiskEngine.check()` → `ExecutionAuthority.authorize()` → `OrderManager.create_from_intent()` → `validate/submitting/submitted` → `adapter.submit_order()` → inline event stream applies fills; UNKNOWN/timeouts go to recovery, never blind resubmit.

**Authority-relevant constants today:** `RiskConfig.max_leverage=5`, `max_order_notional=1_000_000`, `max_position_notional=1_000_000`, `max_symbol_exposure=1_000_000`, `max_account_exposure=5_000_000`, `max_open_orders=20`; `Settings.max_holding_time_seconds=86400`; cooldowns: entry retry 30s, position review 30s, opportunity scan 90s, engine tick 0.5s.

---

## 3. Every deterministic reduce-only path

1. `LiveLLMPositionManager.review()` → `SignalIntent(reduce_only=True, lifecycle_action ∈ {REDUCE, EXIT})`.
2. **TIME_STOP safety fallback** — `position_manager.py:166-220`: once `time_in_trade >= plan.max_holding_time_seconds`, any HOLD/FAIL_CLOSED/partial becomes a **full** reduce-only `TIME_STOP_SAFETY_FALLBACK`.
3. `TradingEngine.process_signal()` reduce-only validation (`engine.py:606-660`): plan ACTIVE, `latest_position_decision_id` matches, reduce-only flag, correct side, `qty <= abs(position.quantity)`, no pending position action.
4. `RiskEngine.check()` reduce-only branch (`risk/engine.py:110-123`): no-position / direction-reversal / crosses-zero rejection; exposure-reducing orders bypass sizing clamps.
5. `RecoveryService._close_orphan_positions()` (prices at real market, no new entry) and `_resync_sim_from_ledger()` — restart/recovery flatten path (`recovery.py:169-200`, invoked from `engine.py:_run_recovery`).
6. `OrderManager.cancel_pending/cancel_confirm` and `engine._cancel_unsettled_entry_order()` — cancel-not-oversell path when an entry is unsettled.

No other deterministic exit exists today. There is **no** Base Exit, no Fast Profit, no Risk L1/L2 hard exit, no offline exit, no exit coordinator, no partial-exit reservation arithmetic.

---

## 4. DeepSeek provider / retry / latency path and GLM readiness

- Primary/only runtime provider: `llm_chief/provider.py::DeepSeekProvider` implementing `LLMProvider` Protocol. `complete_json(prompt, temperature, timeout_seconds, retries, max_tokens, thinking, reasoning_effort, operation)`.
  - `retries=1` call sites: `ChiefTraderEngine.decide` (`llm_chief/engine.py:67`, timeout 30s, thinking on, `operation="trading_decision"`), `select_tools` (timeout 20s, `operation="tool_selection"`).
  - HTTP non-200 handling: 4xx (≠429) breaks; timeout/transport continue; malformed JSON → one JSON-recovery attempt; fail-closed otherwise.
  - Diagnostics: `last_success_ts`, `last_error`, `last_latency_ms`, `last_token_usage`, `last_attempt_count`, `_operation_diagnostics` — **last value only; no mean/p50/p90/p95/p99/max/timeout-rate/retry-rate aggregation**.
- Secondary legacy client: `deepseek/client.py::DeepSeekClient` (timeout 30s, retries=2) — not part of the bootstrap graph.
- **GLM: zero hits** for `glm|zhipu|bigmodel` in `src/`. No backup provider, no failover, no `LLM_OFFLINE_MODE`, no 5-minute probe windows.
- `LLMDecisionStore` persists provider/model/version/`prompt_version` but no per-call latency/cost columns; `LLMDecisionORM` has exposure/qty/leverage/position context fields useful for the V2 contract.

---

## 5. Existing factor/model inventory vs the required 25 models

Legend: FULL = production-plausible implementation exists; PARTIAL = math piece exists but not as required evidence model; MISSING = no implementation.

| # | Required model | Existing implementation | Status |
|---|---|---|---|
| 01 | EMA Multi-TF 20/50/200 | `factors/calculators/trend.py::ema_slope` (single-period EMA slope only) | PARTIAL |
| 02 | MACD 12/26/9 | none | MISSING |
| 03 | ADX+DI 14 | none | MISSING |
| 04 | RSI Context 14 | none | MISSING |
| 05 | Bollinger Regime 20/2σ | none | MISSING |
| 06 | VWAP deviation | none | MISSING |
| 07 | ATR/NATR 14 | `factors/calculators/volatility.py` (mean true range, metadata `atr`) | PARTIAL |
| 08 | Volume breakout / relative volume | `volume.py` (change/anomaly), `opportunity/factors.py::VolumeFactor` | PARTIAL |
| 09 | CVD / taker flow | orderflow uses bid/ask totals; **no public trades feed** | MISSING |
| 10 | Price+OI | `calculators/open_interest.py` (`price_oi_divergence`), `MarketState.open_interest_change` | PARTIAL |
| 11 | SMA structure 20/50/200 | none (only `ma_distance` 20) | PARTIAL |
| 12 | SuperTrend ATR10×3 | none | MISSING |
| 13 | Stochastic RSI | none | MISSING |
| 14 | ROC 12 | none | MISSING |
| 15 | CCI 20 | none | MISSING |
| 16 | Price Z-Score 50/100 | `opportunity/factors.py::MeanReversionFactor` (z-score, single window) | PARTIAL |
| 17 | Support/Resistance | none | MISSING |
| 18 | OBV | none | MISSING |
| 19 | MFI 14 | none | MISSING |
| 20 | CMF 20 | none | MISSING |
| 21 | Order-Flow ML | none | MISSING |
| 22 | Order-book imbalance L1/L5/L10/microprice | `opportunity/factors.py::OrderbookImbalanceFactor`, `MarketState.imbalance`, book L1 only in engine context | PARTIAL |
| 23 | Funding + basis crowding | `calculators/funding.py`, `MarketState.basis` (`compute_basis`), `OKXPublicMarketFeed._refresh_funding` | PARTIAL |
| 24 | Market regime classifier | `factors/regime/classifier.py::RegimeClassifier` labels unverified; `market_data/opportunity/factors.py::VolatilityFactor` | PARTIAL |
| 25 | XGBoost meta forecast | none; **no numpy/pandas/sklearn/xgboost dependency in `pyproject.toml`** | MISSING |

Existing result DTOs: `factors/models.py::FactorResult/FactorSnapshot/FactorPerformance/FactorHealth/…`; `opportunity/factors.py::FactorObservation` (`status`, `strength`, `facts`, `observed_at`, `symbol`). None carry model family/regime compatibility/strategy compatibility/Growth reliability/counter-evidence as required.

---

## 6. Evidence / context builder and decision schemas

- `llm_chief/context.py::ChiefTraderContext` — market_snapshot, regime, quant_evidence, portfolio_state, risk_summary, position_state/context, knowledge, similar_episodes, coin_profile, compressed_experience, failure_warnings, memory/research/episode/pattern refs, opportunity_context, `estimate_tokens()`.
- `llm_chief/context_loader.py::ChiefContextLoader` — DB-backed knowledge/memory/coin-profile enrichment.
- `ai/context_builder.py::AIContextBuilder` — minimal analysis context (not the chief path).
- `deepseek/context_builder.py`, `deepseek/schemas.py` — legacy opinion/review schemas.
- Prompt contract: `ChiefTraderEngine.render_prompt()` JSON contract (see §1). No state-version binding, no Base Exit/NEXT_REASSESSMENT/all-in-economics fields, no capital-allocation semantics beyond size/leverage; REDUCE takes `position_size_request` as a quantity without explicit units validation against leg state version.
- `LLMDecisionStore.save()` persists decisions with lineage refs; `link_trade_plan()` binds decision→plan.

---

## 7. Domain models and DB tables

Domain: see §1 (`OrderIntent` has `client_order_id/symbol/side/type/TIF/price/quantity/quote_order_qty/strategy_id/run_id/expires_at/metadata`; `metadata` is the current lineage carrier: `signal_id`, `trade_plan_id`, `decision_id`, `direction`, `lifecycle_action`, `reduce_only`, instrument fields).

Tables (60): `engine_runs`, `runtime_leases`, `orders`, `order_events`, `fills`, `trades`, `ledger_transactions`, `ledger_entries`, `accounts_projection`, `positions_projection`, `market_snapshots`, `reconciliation_runs`, `risk_decisions`, `trade_plans`, `llm_decisions`, `trade_episodes`, `audit_events`, `trade_memory_records`, `daily_review_runs`, `llm_strategy_cards`, `ai_trade_episodes`, `ai_trade_reviews`, `ai_market_patterns`, `ai_coin_profiles`, `ai_compressed_experience`, `shadow_campaigns`, `capital_allocations`, `factor_*` (registry/values/snapshots/performance/attribution/decay/catalog/regime performance/confidence/combinations/importance/lifecycle/forecasts/evolution), `market_regime_history`, `market_anomalies`, `research_*`, `market_intelligence_context`, `market_similarity_cases`, `knowledge_relations`, `knowledge_decay`, `regime_forecasts`, `confidence_forecasts`, `prediction_results`, `feedback_validation`, `research_feedback`.

Gaps vs SPEC lineage (`OpportunityID → DecisionID → PositionEpisodeID → LegID → TradePlanVersion → IntentID → ExecutionID → ClientOrderID → ExchangeOrderID → FillIDs`): no leg table, no plan version column, no episode id on orders/intents (only `trade_episodes` rows built post-close from plan/order/fill joins), opportunity lineage only recorded on `llm_decisions.opportunity_source/triggered_factors`.

---

## 8. Risk / pre-trade coupling

- `TradingEngine.process_signal` calls `RiskEngine.check()` **before** `ExecutionAuthority.authorize()`; `AuthorizationContext.risk_decision` is mandatory; `ExecutionAuthority` rejects unless `APPROVE|SCALE_DOWN`.
- `RiskEngine` can **SCALE_DOWN** quantity (`MAX_ORDER_NOTIONAL`) and **clamp leverage** (`clamp_leverage`) before execution — i.e. Risk currently resizes the LLM's trade. This is the **known migration point** (SPEC §4H / ExecutionAuthority migration).
- Non-strategy safety that must be KEPT: kill switch, lease, reconciliation halt, market freshness, orderbook health, exchange/balance freshness, duplicate client order, precision/min-qty/min-notional, rate-limit, mode/live-enable, order-state validity, expiry.
- Missing per SPEC: hard constitutional checks for `leverage <= 20x` and `single new-risk child <= 25% equity` as **reject-not-resize** contract validation; per-child vs per-symbol cumulative semantics; risk episode history across ADDs; L1/L2 states.
- `ai_risk/AIRiskCommittee` (REDUCE with max_leverage/max_position) is the same superseded semantics if wired; currently not in bootstrap path.

---

## 9. ExecutionAuthority / lease / idempotency / UNKNOWN / TTL / partial fill / restart recovery

- **Lease**: `runtime_leases` with token + `fence_generation`; acquired after recovery; renewed immediately and every 3s (TTL 10s); loss engages kill switch (`engine.py:_lease_loop`).
- **Idempotency**: `client_order_id = f"{strategy_id}_{signal_id}"[:60]`; `OrderManager.create_from_intent` reuses identical or rejects conflicting reuse; `process_signal` short-circuits existing client ids.
- **UNKNOWN**: adapter raises `UnknownExecutionState` / transient errors → `mark_unknown` → `_run_recovery`; `RecoveryService` queries exchange by exchange/client id, applies factual fills, and **rejects when not found (`no blind resubmit`)**.
- **TTL**: `OrderIntent.expires_at`; authority rejects `ORDER_EXPIRED`; plan TTL sync via `_sync_terminal_entry_plan(s)`.
- **Partial fills**: `OrderManager.apply_fill` idempotent by `fill_id`; `TradingEngine._settle_fill` → ledger; simulator emits inline events and engine tolerates already-applied transitions (`ORDER_STATE_SYNC_SKIPPED`).
- **Cancel/fill race**: cancel path checks state machine and tolerates inline fill events (commits `67b0d2a`, `4d7b85a`, `a548db9`).
- **Reconciliation**: periodic `ReconciliationService.reconcile()` → `reconciliation_halted` → authority HOLD (`RECONCILIATION_HALT`).
- **Restart recovery**: `_run_recovery` runs before the lease is acquired; `_restore_paper_adapter_state` + `_sync_terminal_entry_plans`; `_close_orphan_positions` at real prices.
- Gaps vs SPEC: no exit coordinator / reduce-qty reservation, no leg/version state, no stale-decision guard on LLM responses, no offline/pending new-risk cancellation, no exchange/WS/REST disagreement handling beyond order recovery, no duplicate-WS-fill dedup test coverage (fill ids are unique but no explicit duplicate-event test).

---

## 10. Market universe / scanner / data sources

- Universe: `market_data/opportunity/universe.py::OkxUniverseManager` (full OKX USDT linear-SWAP), instrument facts from `PaperRealMarketAdapter.get_exchange_info()`.
- Scanner: `OpportunityScannerService.run_forever()` (90s) → `FactorScanner.scan()` over `SymbolFacts` → `OpportunityBoard` (active set 40 + rotation 10) → `LiveLLMDecisionStrategy.desired_symbol()` agenda → DeepSeek review. Evidence-only guard: `validate_no_direction_semantics()`.
- Feed sources: tickers, order book snapshot, mark/index price, funding rate, OI, closed candles (kline warmup); **no public trades stream (no CVD/taker flow), no liquidation data, no news**.
- `MarketState.value` cache health: `SourceStatus` per source; `MarketDataService` bounded per-symbol books; engine invalidates stale books before authorizing.

---

## 11. Growth / review / memory (behavior search)

Canonical existing pieces (keep, extend): `governance/trade_episode.py` (factual closed episodes + review marking), `learning/*`, `llm_chief/memory.py::ExperienceMemory` (episode/pattern/compress), `llm_chief/knowledge.py::KnowledgeBase`, `ai_memory/*`, `vector_memory/*`, `daily_report/*`, `DailyReviewScheduler`, tables `trade_episodes/trade_memory_records/daily_review_runs/ai_*`.

Missing vs SPEC: Daily Top-10 freeze at decision time with +15m/+30m/+1h/+4h/+12h/+24h evaluation, MFE/MAE/counterfactual labels, 7-taxonomy review (OPPORTUNITY/ENTRY/POSITION MANAGEMENT/EXIT/RE-ENTRY/RISK/LLM INVOCATION), fast/pattern/validated memory speeds with sample tiers, rationalization detection, ADD/HEDGE/exit-modification/fast-profit/re-entry/LLM-invocation comparison reviews, no-ADD/no-hedge counterfactuals. Growth must have **zero order authority**; existing `validate_no_direction_semantics` is the right pattern to extend.

---

## 12. Tests and baseline

- 89 test modules across `tests/{unit,integration,factors,llm_chief,opportunity,runtime_unit,execution_unit,chaos,e2e,local_stability,ai_brain,deepseek,okx_credential,governance_unit,perpetual_*,phase*,...}`.
- Baseline command/result (this worktree, this SHA): **653 passed, 1 warning, 75.70s** (`/tmp/lr_v2_phase0_pytest.log`).
- Existing canonical safety tests to protect: `tests/integration/test_lease.py`, `test_recovery.py`, `test_order_manager.py`, `test_portfolio_reconciliation.py`, `test_live_llm_position_lifecycle.py`, `test_live_llm_trade_planner.py`, `test_trade_plans.py`, `tests/chaos/test_chaos.py`, `tests/e2e/test_paper_trading_e2e.py`, `tests/local_stability/test_p0_stale_market.py`.
- No tests exist yet for: >25% child reject, ≤25% per child/cumulative >25% symbol, leverage 20x contract reject, stale-LLM-after-exit, DeepSeek timeout + successful prior order, DeepSeek→GLM dedup, offline pending BUY/ADD/HEDGE, duplicate WS fill, REST/WS disagreement, Exit V1→V2 race, LONG+SHORT legs, fast partial exit + Base race, restart of episodes/legs.

---

## 13. Migration risks / backward-compatibility constraints

1. **Risk coupling**: removing `risk_decision` from `AuthorizationContext` requires updating `TradingEngine.process_signal`, `tests/unit`/`integration` expectations, and any API docs; tests that encode SCALE_DOWN sizing must be re-expressed as reject-on-violation + execution contract validation with explicit OLD/NEW rationale.
2. **Schema**: head `0023`; new migrations must chain from it. Additive/nullable columns + new tables only; existing PAPER DBs from this branch must remain readable. `ExactDecimal` (string affinity) pitfalls (see historical `ai_trade_episodes` Decimal-coercion lesson).
3. **Domain DTOs**: `OrderIntent.metadata` JSON is the current lineage carrier; extending `OrderIntent`/`SignalIntent` with optional typed fields must keep `extra="forbid"` compatibility for existing tests/callers.
4. **Position model is net per symbol** (`positions_projection` quantity single sign). Hedge legs require a new leg projection without changing net accounting semantics for existing paths.
5. **LLM prompt contract**: `ChiefTraderDecision` has `model_config extra="forbid"`; adding fields is backward compatible for callers but old-format provider outputs must be tolerated until prompts/contracts are migrated (defaults).
6. **`TradePlanService.create` requires `max_holding_time_seconds > 0`**; SPEC says no maximum holding time (time exit defaults NONE). Migration must default NONE without breaking the existing TIME_STOP safety path.
7. **No numpy/xgboost**: model 25 and ML-based model 21 need either pure-Python/Decimal implementations or an explicit optional dependency; binary deps must not be added casually to PAPER runtime (macOS Intel wheel constraint noted in `pyproject.toml`).
8. **Evidence-only guards** (`validate_no_direction_semantics`) must not be weakened while adding 25 models.
9. **`apply_fill`/recovery invariants**: all new exits must flow through `OrderManager` + ledger + `fills` (single source of truth); no direct DB or simulator mutation.
10. **One runtime per lease**: no second polling daemon; all new loops must be hosted by `TradingEngine` tasks (`tick`, event loop, lease, reconciliation, scheduler, opportunity) to preserve single-writer.
11. **API role gates** (`require_role_dependency`) and `enforce_llm_entry_authority` must continue to block non-LLM new direction in auto-start mode.

---

## 14. CURRENT → TARGET → ACTION → EXACT INTEGRATION POINT

| Capability | CURRENT | TARGET (V2) | ACTION | EXACT INTEGRATION POINT |
|---|---|---|---|---|
| Market scan | `OpportunityScannerService` + `OkxUniverseManager` + `FactorScanner` (90s, 9 factors) | full-universe factual scan with liquidity/quality prefilter, richer market facts | EXTEND | `market_data/opportunity/service.py`, `scanner.py`, `universe.py`, `market_data/okx_public_feed.py` (+ trades/CVD fetch) |
| 25-model evidence | 7 primitive calculators + 9 opportunity factors (PARTIAL for 8, MISSING for 17) | complete 25 factual expert models with support/counter/neutral + reliability | EXTEND + ADD | `factors/` package (new expert modules reusing calculators), `factors/models.py` DTO extension, `market_data/opportunity/factors.py` evidence adapters |
| Consensus | none (`ai_decision.fuse` only) | correlation-adjusted consensus, opposition preserved, `NOT_AN_ORDER` | ADD | new `factors/consensus.py` or `ai_decision` extension consuming 25-model DTOs |
| Context/evidence package | `ChiefTraderContext` + `ChiefContextLoader` | Market + 25 outputs/consensus + News + Growth + account + economics | EXTEND | `llm_chief/context.py`, `context_loader.py`, `runtime_strategy.py`/`position_manager.py` context assembly |
| Core LLM | `ChiefTraderEngine` + `DeepSeekProvider`; FLAT/OPEN action contract | structured SHOULD_TRADE/ACTION incl. ADD/HEDGE/REVERSE/MODIFY_EXIT, Base Exit, NEXT_REASSESSMENT, state version binding | ADAPT + EXTEND | `llm_chief/engine.py`, `decision.py`, `provider.py`, `runtime_strategy.py`, `position_manager.py`, `trade_planner.py` |
| DeepSeek provider | primary provider, last-value diagnostics | one immediate retry + full latency percentile instrumentation | EXTEND | `llm_chief/provider.py` (+ metrics accumulator), `llm_chief/engine.py` |
| GLM backup | absent | `GLMProvider` behind same `LLMProvider` Protocol, latest-state reprompt, no stale replay | ADD | `llm_chief/provider.py` (new class), factory in `runtime/bootstrap.py` |
| TradePlan | plan + states, no version/exit protocol | versioned plan with Base Exit, Exit Approach, adverse trigger, thesis invalidation, reassessment rules, `based_on_state_version` | EXTEND | `trade_plan/service.py`, `TradePlanORM`, `llm_chief/trade_planner.py`, migration 0024+ |
| Base Exit | absent (only LLM review/time-stop) | always-present active Base Exit per position; survives LLM wait; atomic replacement | ADD | new `execution/exit_coordinator.py` (or `position_manager` extension) + plan fields + runtime loops |
| NEXT_REASSESSMENT | absent | PRICE/TIME/INDICATOR/EVENT conditions AND/OR with priority → wake LLM only | ADD | `llm_chief/decision.py` fields, runtime wake scheduler inside `TradingEngine` (`engine.py`) |
| Event-driven position monitor | fixed 30s per-symbol review cooldown | dedup + material-information gate + position-aware dynamic invocation; one active reassessment per leg | ADAPT | `runtime/engine.py:tick`, `llm_chief/position_manager.py`, `runtime/event_bus.py` |
| Risk L1/L2 | `RiskEngine` sizing/clamp + kill switch; no L1/L2 | L1 warning→LLM reassess; L1 forced close if providers fail; L2 forced hard exit; risk episode per position | ADAPT + ADD | `risk/engine.py`, new `risk/episode.py`, engine wiring, plan/position state version |
| Fast Profit | absent | net-profitable + rapid ATR-normalized expansion + reversal evidence → 1–100% partial/full exit, online/offline, then fresh LLM call | ADD | new `risk/fast_profit.py` + exit coordinator + `TradingEngine` event handling |
| Partial trading | `position_size_request` REDUCE quantity | partial entry/exit, preauthorized child orders, reassessment-before-child | EXTEND | `llm_chief/decision.py`, `position_manager.py`, `engine.process_signal`, `order/manager.py` |
| Hedge legs | net position only | independent leg records + LONG+SHORT same symbol; leg-specific thesis/Base Exit | ADD | new `position/leg` projection + migration; `portfolio` extension; API legs view |
| Growth | episodes + learning + memory + daily reviews | 7-taxonomy reviews + Daily Top-10 + counterfactuals + 3 memory speeds + rationalization detection | EXTEND | `governance/trade_episode.py`, `learning/*`, `llm_chief/memory.py`, `daily_report/`, new review workers/tables |
| Execution authority | lease/kill/recon/health/dup/precision + RiskDecision gate | same safety gates + V2 order-contract validation (≤20x, ≤25% child reject-not-resize) | ADAPT | `execution/authority.py`, `runtime/engine.py`, `risk/engine.py` |
| Reconciliation/recovery | canonical RecoveryService + ReconciliationService | + offline cancel/reconcile of pending new-risk orders; 5-min probe recovery | EXTEND | `runtime/recovery.py`, `runtime/engine.py`, new offline coordinator |
| Persistence | 60 tables, head 0023 | + leg/plan-version/state-version/risk-episode/top10/review/econ tables | EXTEND | `persistence/models.py`, `migrations/versions/0024+` |
| API/UI | net positions, orders, plans, episodes | + legs/hedge expandable view, assessment/review views | EXTEND | `api/app.py`, `frontend/src/pages`, `frontend/src/types` |

---

## 15. Audit findings to fix (pre-implementation backlog)

**Constitution conflicts (must be ADAPTed, treated as P0 if left):**
- `ExecutionAuthority` `RISK_NOT_VALID` pre-trade gate + `RiskEngine` SCALE_DOWN/clamp: Risk currently decides smaller size/leverage. V2: execution contract validation rejects invalid orders; Risk keeps non-strategy safety only.
- Fixed cooldowns (30s entry/position) are the only invocation policy: no dedup/material-information gate/position-aware priority.
- `AIDecisionEngine`/`fuse` is a quant+AI directional fusion that could become an authority if wired; keep as evidence/recommendation only.

**P1 engineering gaps:**
- No GLM failover, no offline mode, no provider latency percentiles.
- No stale-decision (`STALE_DECISION`) state-version protection for in-flight LLM responses.
- No Base Exit, no exit coordinator, no Fast Profit, no partial-exit reservation → oversell risk if multiple exits appear later.
- Net position model cannot represent hedge legs.
- TradePlan lacks version/exit protocol fields.
- No Daily Top-10 / review taxonomy / counterfactuals.
- No trades/CVD feed → models 9 & 21 blocked on data.
- `new_risk_gate._is_reduce_or_close` is dead code (returns False always).

**Audit P0 blockers:** none at audit time (no code changed; baseline suite green; no runtime started; no live trading enabled).

---

## 16. Phase plan (master goal)

- PHASE 1 — extend market/data pipeline (universe, prefilter, trades/CVD, bounded caches, freshness/quality, no authority).
- PHASE 2 — 25-model evidence layer (wrap existing calculators; add missing models; DTO extension; opposition preserved; no authority).
- PHASE 3 — evolve `ai_decision` fusion into recommendation/consensus (correlation-adjusted, NOT_AN_ORDER), preserve callers.
- PHASE 4 — Core LLM TradePlan + position management: structured contract, Base Exit, NEXT_REASSESSMENT, event-driven invocation, DeepSeek→GLM→offline, Risk L1/L2 adaptation, Fast Profit, partial/hedge, exit coordination.
- PHASE 5 — Growth V2 on existing episode/learning/memory tables: Daily Top-10, 7-taxonomy reviews, counterfactuals, memory speeds, rationalization detection.
- PHASE 6 — execution/runtime/recovery evolution: lineage IDs, plan/state versions, order lifecycle/TTL, exit coordinator, offline cancel/reconcile, event ledger extension, race/regression tests.
- PHASE 7 — factual acceptance: authority tests, real configured LLM path, natural PAPER lifecycle with real OKX data, ≥72h PAPER soak; PASS/PARTIAL/BLOCKED with IDs/timestamps/SHA evidence.

Each phase: focused tests + relevant regressions + receipt update + small auditable commit + continue.

## Gate

PHASE_0 = **PASS** — repository reality mapped with exact files/classes/functions/tables/tests; no invasive change made before this map; one canonical source of truth identified per subsystem; migration action and integration point assigned for every required capability.
