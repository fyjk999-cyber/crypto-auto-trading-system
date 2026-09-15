# LOW-RISK V2 — MASTER IMPLEMENTATION SPEC

Status: FROZEN IMPLEMENTATION CONTRACT
Scope: LOW-RISK only. Turbo is out of scope except explicitly adopted ideas below.
Repository: fyjk999-cyber/crypto-auto-trading-system
Baseline branch at authoring: codex/final-canonical-ai-runtime-bootstrap
Baseline SHA at authoring: a548db928cd9c063ff33eb2a69c864f47f9ac64a
Safety: PAPER ONLY until final acceptance. Do not enable live trading.

---

## 0. MASTER GOAL / NON-NEGOTIABLE CONSTITUTION

Build Low-Risk V2 as a conservative, long-term compounding crypto trading system whose optimization order is:

1. Long-term net compounding growth.
2. Drawdown control.
3. Win rate.
4. Opportunity count.

The Core LLM is the only trading intelligence allowed to originate new risk. Primary Core LLM = DeepSeek. Backup Core LLM = GLM. The 25 models, News, Growth, market data, portfolio data and execution data are evidence/tools for the Core LLM, never independent trading authorities.

Legal new-risk path:

Market -> 25 Models + News + Growth + Account + Execution Evidence -> Core LLM -> TradePlan -> Execution -> OKX/PAPER.

Forbidden new-risk paths:

- Model -> OPEN/ADD/HEDGE/REVERSE.
- Growth -> OPEN/ADD/HEDGE/REVERSE.
- News -> OPEN/ADD/HEDGE/REVERSE.
- Risk -> OPEN/ADD/HEDGE/REVERSE.
- Aggregator/consensus -> OPEN/ADD/HEDGE/REVERSE.

Authorized deterministic risk-reducing exits are exceptions to the requirement for a fresh LLM decision: active Base Exit, preauthorized partial exit, Fast Profit Protection Exit, Risk hard exit, and true-offline exit logic.

Core LLM authority includes TRADE/WAIT/REJECT, LONG/SHORT, strategy, entry, partial entry/exit, capital allocation, leverage, ADD, HOLD, REDUCE, CLOSE, HEDGE, REVERSE, Base Exit changes, strategy changes, and NEXT_REASSESSMENT.

Hard limits:

- Maximum leverage per order: 20x.
- Maximum capital allocation per individual new-risk order: 25% of total account equity.
- The 25% limit is per order, NOT per symbol or Position Episode. Repeated ADD/HEDGE orders may make cumulative symbol exposure exceed 25%.
- No hard total account exposure cap.
- No hard maximum holding time.
- Avoid economically meaningless tiny positions/orders; expected net value must justify all estimated costs.
- LONG and SHORT are both allowed.
- Same-symbol LONG and SHORT may coexist when the reverse leg has an independent strategy/model thesis. A reverse leg is invalid if its only reason is “reduce the loss of the existing leg.”

Cost/edge constitution:

Expected net edge must exceed fees + spread + estimated slippage + funding where relevant + safety margin. High confidence alone never justifies a trade whose expected net return is economically trivial.

All profit/loss classification must use estimated net exit PnL, including known/estimated entry fee, exit fee, spread, slippage, funding and other estimable execution costs.

---

# PHASE 0 — FORENSIC BASELINE, SAFETY AND MIGRATION PLAN

## Objective

Understand the existing repository before modifying behavior. Preserve working functionality, current PAPER facts and authority boundaries. Produce a gap map from current code to this SPEC.

## Tasks

1. Record exact STARTING_SHA, branch, worktree status and runtime/source SHA if a runtime exists.
2. Inventory current market scanner, factor/model layer, LLM providers, risk engine, execution engine, order state machine, Growth/memory, DB schema, API/dashboard and tests.
3. Locate every code path capable of creating, modifying or submitting orders.
4. Identify current Factor System behavior and plan a compatibility-safe migration to the 25-model evidence layer.
5. Inventory current OKX public market data, order book, trades, CVD/taker flow, OI, funding, basis and news availability/freshness.
6. Inventory existing PAPER databases and migrations. Do not destroy historical facts.
7. Find all current order TTL, retry, UNKNOWN-order reconciliation, partial-fill and restart-recovery behavior.
8. Find all LLM timeout/retry/failover logic and current telemetry.
9. Confirm live trading is disabled. Do not access or use private live-order credentials for acceptance.
10. Write a Phase-0 gap report and implementation map before invasive changes.

## Acceptance

- Exact SHA/source/worktree facts recorded.
- Every new-risk order creation path enumerated.
- Existing DB/migration/runtime compatibility risks documented.
- No live trading started.
- No fake trades/fills/episodes created.
- Existing dirty/shared worktrees are not reset/cleaned/overwritten.

---

# PHASE 1 — MARKET UNIVERSE, DATA CONTRACT AND CANDIDATE SCAN

## Objective

Scan the full OKX USDT perpetual universe, cheaply prefiltering before expensive analysis, while providing factual, timestamped, quality-scored evidence.

## Tasks

1. Universe = OKX USDT perpetual markets available to the runtime.
2. Apply liquidity/volume/data-quality prefilter before 25-model evaluation.
3. Keep closed candles separate from live price/order-book/trade observations.
4. Maintain bounded multi-symbol caches with freshness, source, timestamp, quality and retry semantics.
5. Provide at least: OHLCV multi-timeframe, real-time price, spread, L1/L5/L10 depth when available, trade/taker flow, CVD, OI, funding, basis, volume/trade-count velocity and liquidity quality.
6. Define stale/incomplete data behavior. Stale evidence must reduce confidence and cannot be silently presented as fresh.
7. Candidate ranking must use only information available at decision time.

## Acceptance

- Full-market discovery works without hard-coded symbols.
- Prefilter reduces expensive downstream work while retaining traceability.
- Every evidence object has source/timestamp/freshness/data_quality.
- Closed/live data are not mixed incorrectly.
- No market-data component can submit orders.

---

# PHASE 2 — 25-MODEL EXPERT EVIDENCE LAYER

## Objective

Replace the factor-as-authority concept with 25 independent expert tools. Models advise; Core LLM decides.

## Required models

TREND
01 EMA Multi-TF — EMA20/50/200, price/order/slope/multi-TF.
02 MACD Momentum — 12/26/9; histogram acceleration/divergence, not simple cross only.
03 ADX + DI — ADX14; regime-sensitive trend strength.
11 SMA Structure — SMA20/50/200.
12 SuperTrend — initial ATR10 x3, later calibratable through validated Growth.

MOMENTUM
04 RSI Context — RSI14, regime-aware; never mechanically “RSI>70=SHORT.”
13 Stochastic RSI — 14/14/3/3 initial.
14 ROC — ROC12 + multi-TF standardization.
15 CCI — CCI20.

STRUCTURE / VOLATILITY
05 Bollinger Regime — 20, 2 sigma; squeeze/expansion/reversion context.
06 VWAP Deviation — daily + rolling + anchored VWAP.
07 ATR Volatility — ATR14 / NATR; volatility and edge geometry.
16 Price Z-Score — rolling 50/100 initial.
17 Support/Resistance — swing + volume profile + multi-TF; nearest levels, strength, room and invalidation.

VOLUME / FLOW
08 Volume Breakout — relative volume versus rolling baseline/median.
09 CVD / Taker Flow — aggressive buy-sell flow and divergence.
18 OBV — slope/divergence.
19 MFI — MFI14.
20 CMF — CMF20.
21 Order Flow ML — predict probability future return exceeds cost threshold; inputs may include trades/CVD/imbalance/velocity/spread/microprice.
22 Order Book Imbalance — L1/L5/L10 depth, microprice, spread, persistence/cancel velocity.

DERIVATIVES
10 Price + OI — price/OI quadrant context, combined with flow/regime.
23 Funding + Basis — crowding/context; never mechanical contrarian rule.

ENVIRONMENT / ML
24 Market Regime — TREND_UP, TREND_DOWN, RANGE, BREAKOUT_EXPANSION, HIGH_VOLATILITY, LIQUIDATION_DISLOCATION, UNCERTAIN.
25 XGBoost Meta Forecast — restrained statistical predictor such as P(NetReturn_horizon > MinimumEdge), never a second trading authority.

## Provisional timeframe roles

- 4H macro trend/context.
- 1H primary trend.
- 15m trade structure.
- 5m entry/short-term change.
- 1m execution/microstructure only, not dominant directional vote.

Do not encode timeframe percentages as immutable trading law; keep them configurable and auditable.

## Mandatory model output contract

Each model emits at least:

- model_id, model_version, family.
- asset, timestamp, timeframes.
- direction = LONG/SHORT/NEUTRAL.
- direction_score [-1,+1].
- confidence [0,1].
- theory.
- supporting_evidence[].
- counter_evidence[].
- regime_compatibility.
- strategy_compatibility.
- entry_use.
- exit_use.
- reassessment_use / reassessment_trigger.
- hard_exit_capable (normally false).
- invalidation[].
- data_quality and freshness.
- Growth reliability, sample size and memory tier when available.

Direction, confidence and historical reliability are separate concepts.

## Acceptance

- All 25 models run on factual candidate data.
- All 25 raw outputs are preserved and traceable.
- Opposing/neutral evidence is never dropped.
- No model has execution/new-risk authority.
- Stale order-book/CVD evidence visibly lowers evidence quality.

---

# PHASE 3 — CONSENSUS / RECOMMENDATION LAYER

## Objective

Compress 25 outputs without hiding disagreement or double-counting correlated indicators. Recommendation is evidence, never an order.

## Required outputs

1. Raw consensus counts/ratios.
2. Opposition ratio.
3. Neutral count/ratio.
4. Family consensus.
5. Correlation-adjusted/effective consensus.
6. Effective Independent Evidence.
7. Growth reliability + sample size/tier.
8. Regime compatibility.
9. Data quality/freshness.
10. Strategy fit.
11. Strongest supporting evidence.
12. Devil’s Advocate: strongest 3 counterarguments where available.
13. Qualitative strength: VERY_WEAK/WEAK/MODERATE/STRONG/VERY_STRONG/EXTREME.
14. Explicit `NOT_AN_ORDER=true` semantic contract.

Correlation logic should use auditable rolling score-output correlations (e.g. 30D/90D initial windows) so EMA/SMA/MACD/SuperTrend agreement is not treated as four fully independent facts.

## Acceptance tests

- 20L/0S/5N != 20L/5S/0N.
- 20 correlated technical LONG votes != broad independent-family LONG agreement.
- RSI compatibility differs by regime.
- Growth n=8 cannot masquerade as validated high-reliability law.
- 25/25 LONG cannot create an order.
- Aggregator has no execution API.
- Counter-evidence survives end-to-end into the LLM evidence package.

---

# PHASE 4 — CORE LLM DECISION ENGINE, TRADEPLAN, POSITION MANAGEMENT AND RISK

## 4A. Evidence Package

Every Core LLM decision receives the latest coherent package containing:

A. Market: price/K-lines/ATR/volume/order book/CVD/OI/funding/basis.
B. All 25 model outputs + raw/family/effective consensus + counter-evidence.
C. News: event_type, asset_scope, direction, impact/severity, confidence, freshness, source quality, surprise, priced-in estimate where available.
D. Growth: relevant Fast/Pattern/Validated memories with sample size/reliability/tier.
E. Account: equity, existing legs, cumulative exposure, PnL, related exposure.
F. Execution: spread/depth/slippage/fees/funding/feasibility.

News is evidence only and cannot originate an order.

## 4B. Core LLM structured decision contract

The LLM must answer structurally, not by prose parsing:

- SHOULD_TRADE = TRADE/WAIT/REJECT.
- ACTION = OPEN/HOLD/ADD/REDUCE/CLOSE/HEDGE/REVERSE/MODIFY_EXIT/etc as context permits.
- DIRECTION.
- STRATEGY.
- CAPITAL_ALLOCATION (new-risk order <=25% equity).
- LEVERAGE (1..20x).
- EXPECTED_EDGE and cost assumptions.
- CONFIDENCE.
- THESIS.
- SUPPORTING_EVIDENCE and COUNTER_EVIDENCE.
- BASE_EXIT_PRICE for every new entry.
- EXIT_APPROACH definition.
- ADVERSE_TRIGGER.
- THESIS_INVALIDATION.
- PARTIAL_ENTRY/EXIT policy if chosen.
- REENTRY/T policy if chosen.
- POSITION_PLAN_VERSION / based_on_state_version.
- NEXT_REASSESSMENT.

Natural-language reasoning may be logged but execution reads only validated structured fields.

## 4C. Strategy-before-order

Every new-risk order must identify a strategy before submission. Initial library includes TREND_FOLLOWING, PULLBACK, BREAKOUT, MOMENTUM, MEAN_REVERSION, SUPPORT_REBOUND, VWAP_REVERSION. Additional strategies require explicit schema/versioning.

Strategy changes during a position must record FROM, TO, REASON, NEW_THESIS, NEW_EXIT_PROTOCOL, EVIDENCE and Core-LLM approval. Do not silently rename a losing trend trade as mean reversion.

## 4D. Base Exit and Exit Protocol

Every entry MUST have a Base Exit Price. There is no indefinite entry without an initial exit target/protocol.

TradePlan contains:

1. Strategy.
2. Entry thesis.
3. Exit protocol: hard exits + soft/reassessment triggers.
4. Reassessment rules.
5. Partial exits.
6. Re-entry / T rules.
7. Invalidation.
8. Optional time exit; default NONE.

Base Exit is always active until a newer plan version is atomically persisted and activated. If Base Exit is reached while an LLM reassessment is pending, execute the old active Exit. After sale, call Core LLM again for post-exit reassessment/re-entry search.

When a position is losing, the LLM may not simply lower a LONG exit below entry (or mirror for SHORT) to defer recognition of a failed thesis. It may CLOSE/REDUCE, or if there is a genuinely independent opposite thesis, create HEDGE/REVERSE. Loss reason/thesis failure must be written into Growth.

## 4E. Partial trading

LLM may choose partial buys and sells. It may:

- preauthorize future conditional orders; or
- require a fresh LLM reassessment when a condition is reached.

Each new-risk child order remains <=25% equity. Child intents/fills are independently logged but linked to the same Position Episode/TradePlan.

## 4F. HEDGE / simultaneous opposite legs

Same-symbol LONG and SHORT may coexist. A new opposite leg must contain an independent reason tied to a valid strategy or explicit model/model-family logic. “Reduce the loss” alone is invalid.

Each leg has independent TradePlan, Base Exit, PnL, Risk/Growth facts and event history. Dashboard may display net position/net exposure, but logs and Growth must preserve leg-level truth.

## 4G. Event-driven LLM position management

Do not poll the LLM blindly at a fixed high rate. Invocation is driven by material events and position importance.

Core concepts:

`InvocationPriority = f(CumulativePositionExposure, CurrentOrderSize, Leverage, Notional, PnL, EventSeverity, InformationNovelty, Urgency)`.

Large/high-leverage/cumulatively large positions may call the LLM repeatedly over short periods when genuinely new material information arrives. Small positions use a higher trigger threshold.

Same-event deduplication is mandatory. Example 104.01 -> 103.99 -> 104.02 -> 103.98 within the same zone, with no material new information, may trigger only one reassessment.

Material new information can override temporal suppression, including:

- large opposite/same-side trade burst;
- rapid relative-volume expansion;
- abnormal ATR-normalized price velocity/acceleration;
- activity/notional-turnover/trade-count anomaly;
- CVD/taker-flow reversal;
- order-book depth/spread/microprice dislocation;
- OI/funding/basis/liquidation anomaly;
- material news;
- L1;
- LLM-requested NEXT_REASSESSMENT condition.

One position/leg should have one active reassessment request at a time; new evidence updates pending state. State-version rules below prevent stale responses from executing.

## 4H. NEXT_REASSESSMENT capability

Core LLM may request future reassessment based on PRICE, TIME, INDICATOR or EVENT conditions with AND/OR semantics and NORMAL/HIGH/URGENT priority. This is a wake-up condition, not an order and not a stop. Existing exits/risk protections remain active while waiting.

## 4I. Risk daemon — post-entry deterministic protection only

Risk is NOT a pre-trade sizing/leverage approval gate. It cannot reduce/deny LLM-selected leverage or size before entry and cannot originate new positions.

Risk is deterministic, non-LLM, 24/7 and operates on factual position/market/account data.

Online rule: if either DeepSeek OR GLM is available, L1 is a reassessment warning only. At L1 the online Core LLM may HOLD/ADD/REDUCE/CLOSE. L2 is a forced hard exit and cannot be vetoed.

Critical race rule: if L1 is hit and the system attempts reassessment but DeepSeek + its one immediate retry fail and GLM + its one immediate retry fail, L1 immediately upgrades to a forced close; do not wait for the five-minute recovery probe.

L1/L2 belong to a Position Risk Episode, not one child order. ADD after L1 does not reset risk history. Track original entry, current average entry, L1 trigger history, adds after L1, max drawdown, total margin/notional and leg facts.

Do not invent final numeric L1/L2 thresholds merely to complete implementation. If current production thresholds exist, preserve/audit them unless this SPEC or validated evidence authorizes a change. Threshold calibration is a Growth/validation task.

Risk logs are structured facts, not LLM prose.

## 4J. Fast Profit Protection Exit

This deterministic profit-protection exit is valid online and offline and may bypass a fresh LLM call.

It requires:

- position is profitable by estimated NET EXIT PnL; AND
- rapid profit/price expansion relative to recent volatility/ATR; AND
- material reversal evidence, such as large opposite trade, CVD sharp reversal, order-book deterioration, volume climax or strong price rejection.

A lone large trade is insufficient. Rapid rise/fall without reversal evidence is insufficient.

It applies symmetrically to LONG and SHORT. It may reduce 1%..100% of the position, including full close when reversal severity justifies it. Avoid economically meaningless fragments after costs.

After any Fast Profit Protection sale, immediately request a fresh Core LLM post-exit reassessment to decide WAIT, re-entry or a new opposite opportunity. Old pre-sale LLM responses are stale.

Major profit jumps may tighten profit protection immediately; do not wait for a periodic timer.

## 4K. DeepSeek -> GLM -> true offline

Primary = DeepSeek. Backup Core LLM = GLM. Both use the exact same Evidence Package and Decision Contract.

Normal failover sequence:

1. DeepSeek call.
2. On failure/timeout, one immediate DeepSeek retry.
3. If still failed, call GLM with the latest factual state/evidence, not a stale prompt.
4. On GLM failure/timeout, one immediate GLM retry.
5. If both providers are unavailable after these attempts, enter `LLM_OFFLINE_MODE` immediately.

Observed baseline mean LLM call duration supplied for design: ~8.6 seconds. Do not hard-code a timeout solely from this mean. Instrument mean/p50/p90/p95/p99/max/timeout/retry rates and use factual latency evidence for timeout tuning.

## 4L. True offline mode — five-minute windows

While both Core LLMs are unavailable:

- No OPEN.
- No ADD.
- No new HEDGE.
- No REVERSE/new opposite risk.
- No RE-ENTRY.
- Cancel/reconcile all pending new-risk orders.
- Existing reduce-only/protective exits remain active.
- Existing positions use BOTH deterministic Hard Risk Exit and 25-model strategic exit logic.

Non-profitable position: L1 becomes a forced-close line.

Profitable position: initialize a protection line from current factual price +/-0.5% (LONG below, SHORT above), but never intentionally turn a profitable position into a loss solely because the 0.5% line is below break-even protection.

For LONG, if the calculated offline line is below estimated break-even exit price (entry/cost basis plus estimable fees/costs), prefer the estimated break-even protection line when current price permits. If current price is between cost basis and estimated break-even such that fees cannot be fully protected, set protection at the cost basis rather than below it. Mirror for SHORT.

Periodic offline profit line refresh = every 30 minutes, tightening only, never loosening. Major profit jumps may tighten immediately.

25-model offline strategic logic may only HOLD/REDUCE/CLOSE. It can never OPEN/ADD/HEDGE/REVERSE. Implement a documented, testable correlation-adjusted exit score/decision algorithm; thresholds must be configurable and validated rather than hidden magic numbers.

Offline recovery schedule:

- Enter OFFLINE immediately after both providers fail as above.
- Use offline rules continuously for the next five minutes.
- At T+5m, probe Core LLM availability again (DeepSeek first, then GLM as needed).
- If either Core LLM is available, perform rapid factual exchange/local/pending-order/position-plan synchronization and immediately return to NORMAL mode; L1 becomes warning-only again and normal LLM permissions resume.
- If neither is available, remain offline for another five-minute window and repeat at T+10m, T+15m, etc.
- Do not delay hard/protective exits while waiting for a recovery probe.

---

# PHASE 5 — GROWTH V2 / LEARNING CLOSED LOOP

## Objective

Learn from the entire opportunity and position lifecycle without ever gaining order authority. Fast learning may influence LLM context quickly; core formulas/hard rules change slowly and only after validation.

## 5A. Episode taxonomy

Growth must reconstruct and review:

1. OPPORTUNITY.
2. ENTRY.
3. POSITION MANAGEMENT: HOLD/ADD/PARTIAL BUY/PARTIAL SELL/HEDGE/REVERSE/MODIFY EXIT/strategy transition.
4. EXIT: Base Exit/Fast Profit/LLM Exit/L2/Offline Exit.
5. RE-ENTRY.
6. RISK: L1 behavior, L2 quality, offline protection quality.
7. LLM INVOCATION quality.

## 5B. Daily Top-10 opportunity review

Every day, freeze the Top 10 opportunities from all opportunities proposed/ranked at decision time, regardless of whether traded. If 48 opportunities existed and only one traded, the Top-10 review still studies non-traded opportunities.

At decision time save symbol/time/direction, all 25 outputs, raw/effective/family consensus, News, Regime, relevant Growth, LLM reasoning/structured decision, TRADE/WAIT/REJECT, confidence, expected edge, strategy/TradePlan, and non-fill/non-trade reason.

Post-event horizons should include at least +15m/+30m/+1h/+4h/+12h/+24h where data exists, with MFE, MAE, estimated post-cost actual/counterfactual PnL.

Classify at minimum:

- TRADED + CORRECT.
- TRADED + WRONG.
- NOT TRADED + CORRECTLY AVOIDED.
- NOT TRADED + MISSED PROFITABLE OPPORTUNITY.

Never use hindsight to redefine the original Top-10 ranking.

## 5C. ADD review

Every ADD records pre-add PnL/exposure/average entry, why ADD, strategy/model support, CVD/OI/volume/regime/news, added capital/leverage/new cumulative exposure and costs. Compare actual outcome versus no-ADD counterfactual.

## 5D. HEDGE review

Every Hedge records independent thesis/strategy/model logic, original leg, hedge leg, ratio, costs/funding. Compare at least:

A actual hedge;
B close original immediately;
C hold original without hedge;
D close original + full reverse.

## 5E. Exit modification / Fast Profit / Re-entry review

For every Base Exit modification compare actual result with original-exit counterfactual. Review whether raising/lowering targets added value or caused profit giveback.

Fast Profit review compares actual partial/full exit against original Base Exit, no fast exit, and alternate partial/full exits where factual replay permits.

Re-entry review evaluates whether post-exit LLM re-entry recovered continuation value or created churn/cost.

## 5F. L1/L2 Risk review

Every L2 forced close enters Growth. Review price/market state for 24h before and 24h after exit when data exists, with useful checkpoints such as -24h/-12h/-4h/-1h/-30m/-15m/exit/+15m/+30m/+1h/+4h/+12h/+24h. Include MFE/MAE, ATR, volatility, regime, 25-model state, CVD, OI, funding and News.

Estimate avoided loss vs premature exit. Also review what the LLM did after L1 (HOLD/ADD/REDUCE/CLOSE) and the result.

Risk parameter candidates may be learned by Asset x Leverage x Strategy x Regime x Volatility x Liquidity, but a single event must never mutate production hard-risk parameters.

## 5G. LLM invocation learning

Log trigger type, position importance, event severity, novelty, urgency, LLM decision and future outcome. Learn which event types actually change valuable decisions and which cause wasteful calls. This may tune invocation thresholds after validation; it never grants non-LLM new-risk authority.

## 5H. Three-speed memory

FAST EXPERIENCE MEMORY:
- immediate/lightweight/provisional;
- quickly retrievable by LLM;
- low confidence/quick decay;
- may influence context immediately.

PATTERN MEMORY:
- clusters similar cards by Asset x Regime x Strategy/Horizon and other relevant dimensions;
- rough engineering sample tier 20–100.

VALIDATED KNOWLEDGE:
- larger samples;
- post-cost;
- walk-forward/stability validation;
- eligible to propose durable configuration changes through explicit versioned promotion.

Initial engineering confidence tiers (not immutable laws): n<20 provisional; 20<=n<50 emerging; 50<=n<100 candidate; n>=100 formal-validation eligible.

Principle: fast learning, slow core changes. Fast memory must not directly change model formulas, Risk hard limits or execution safety rules.

## 5I. Rationalization detection

Flag possible thesis rationalization when a losing position changes strategy primarily after adverse movement. Do not forbid genuine strategy adaptation; preserve evidence and outcome so Growth can learn adaptation versus excuse-making.

## Acceptance

- Growth has no order submission/new-risk API.
- Daily Top-10 includes traded and untraded opportunities.
- ADD/HEDGE/Exit/FastProfit/Re-entry/L1/L2/Invocation reviews are reconstructable.
- Counterfactual calculations are post-cost and labeled as counterfactual, never factual fills.
- Fast memories are visible to LLM with tier/sample-size uncertainty.
- Production hard rules cannot be changed by one experience card.

---

# PHASE 6 — EXECUTION AND POSITION LIFECYCLE

## Objective

Make strategy semantics survive real asynchronous order behavior: latency, partial fills, cancel/fill races, UNKNOWN states, provider failover, restart and simultaneous exit triggers.

## 6A. Identity lineage

Persist linkage:

OpportunityID -> DecisionID -> PositionEpisodeID -> LegID -> TradePlanVersion -> IntentID -> ExecutionID -> ClientOrderID -> ExchangeOrderID -> FillID(s).

Idempotency is mandatory across retries, DeepSeek->GLM failover, process restart and network timeout.

## 6B. Order state machine

At minimum:

CREATED -> SUBMITTED -> ACKNOWLEDGED -> PARTIALLY_FILLED -> FILLED,
with REJECTED/CANCEL_PENDING/CANCELLED/EXPIRED/UNKNOWN branches.

UNKNOWN != FAILED. UNKNOWN must reconcile against factual exchange/simulator state before any replacement order can create duplicate exposure.

## 6C. Strategy-aware TTL and repricing

Order execution policy may include order type, max wait/TTL, reprice policy/count and max slippage. Do not use one arbitrary TTL for every strategy. TTL expiry cannot automatically chase price. Cancel/reconcile, then return to Core LLM when changed price/edge requires a new decision.

## 6D. Partial fills

Partial fill immediately creates factual position quantity and activates Risk/protection for the filled amount. Remaining quantity follows the TradePlan execution policy and may be cancelled/reassessed if market facts materially change.

## 6E. Actual fills and costs

Track intended entry separately from actual VWAP entry. If execution deviation materially changes expected edge/TradePlan, emit EXECUTION_DEVIATION_EVENT and reassess.

## 6F. Atomic Exit versioning

Old Base Exit remains active until the new TradePlan/Exit version is validated, persisted and atomically activated. If old Exit fills first, later LLM response is stale.

## 6G. State-version stale decision protection

Every LLM request is bound to a factual position/account state version. If fills/exits/material state changes before response, a response based on the old version cannot execute new risk or mutate a closed position. Mark STALE_DECISION and request a fresh reassessment where needed.

## 6H. Exit Coordinator

Coordinate Base Exit, Fast Profit Exit, LLM reduce/close, offline exits and Risk exits. Track current quantity, reserved reduce quantity, pending reduce orders and fills. Never allow total reduce quantity to exceed actual leg quantity.

Priority:

1. Risk hard exit.
2. Offline hard exit.
3. Fast Profit Protection.
4. Active Base Exit.
5. LLM REDUCE/CLOSE.
6. LLM OPEN/ADD/HEDGE/other new risk.

A higher-priority risk-reducing event may cancel/block pending new-risk orders as required.

## 6I. Offline transition

On true LLM_OFFLINE_MODE, cancel/reconcile all pending new-risk orders so old LIMIT buys cannot fill five minutes later while new risk is forbidden. Keep reduce-only/protective orders.

## 6J. Recovery

At each five-minute recovery probe, if either provider recovers, rapidly reconcile exchange position, local DB, fills, pending orders and active PositionPlan. On successful factual synchronization, immediately return to NORMAL mode. Do not impose an additional arbitrary recovery waiting period.

## 6K. Pre-submit economic feasibility

Immediately before submitting new risk, refresh fees/spread/slippage/funding/current price and ensure the LLM’s expected edge remains economically feasible. If feasibility has materially failed, do not silently alter the LLM decision; emit EXECUTION_FEASIBILITY_FAILED and return to Core LLM.

## 6L. Immutable-style factual event ledger

Persist events sufficient to replay:

OPPORTUNITY, MODEL_EVIDENCE, LLM_REQUEST, LLM_RESPONSE, PLAN_CREATED/CHANGED, ORDER_INTENT, ORDER_SUBMITTED, ORDER_ACK, PARTIAL_FILL, FILL, CANCEL, EXIT_TRIGGER, RISK_EVENT, FAST_PROFIT_EVENT, HEDGE, REENTRY, POSITION_CLOSED, provider failover/offline/recovery and reconciliation events.

Every event should carry timestamp, source, relevant IDs, state version and factual payload.

## Acceptance race tests

Must cover at least:

- DeepSeek timeout while its prior intent/order actually succeeded.
- DeepSeek failure -> GLM takeover without duplicate order.
- LLM response simultaneous with Base Exit fill.
- LLM response simultaneous with Fast Profit fill.
- L2 while ADD is pending.
- Partial fill followed by market reversal.
- Cancel/fill race.
- Offline transition with old pending BUY/ADD/HEDGE.
- Duplicate WebSocket fill notification.
- Temporary REST/WS disagreement.
- Exit V1->V2 activation race.
- Same-symbol LONG+SHORT.
- repeated ADD causing cumulative symbol allocation >25% (legal).
- single new-risk order >25% equity (must reject).
- partial Fast Exit + Base Exit simultaneous trigger.
- post-sale stale LLM response.
- restart recovery of all Position Episodes/legs/orders.

No race may create duplicate exposure, oversell, ghost positions, offline new risk or execution of a stale LLM decision.

---

# PHASE 7 — SYSTEM ACCEPTANCE, SHADOW AND PAPER SOAK

## Objective

Prove the system works factually, not merely that code exists or tests are green.

Final status must be one of PASS / PARTIAL / BLOCKED.

## 7A. Static authority acceptance

Prove no Model/Growth/News/Risk/Aggregator path can originate new risk. Prove deterministic authorized exits are reduce-only.

## 7B. 25-model factual acceptance

On real OKX public market observations, show all 25 outputs, timestamps, quality/freshness and full delivery to the Core LLM including opposition/neutral evidence.

## 7C. Consensus acceptance

Test 20L/0S/5N vs 20L/5S/0N; correlated-family versus independent-family agreement; small-sample Growth uncertainty; stale microstructure downgrade; and 25/25 consensus cannot order.

## 7D. Real Core LLM acceptance

Use real configured DeepSeek for PAPER decision flow; no mock for final factual evidence. Demonstrate structured TradePlan with Strategy, <=25% individual order allocation, <=20x leverage, Base Exit, invalidation and NEXT_REASSESSMENT when TRADE occurs.

## 7E. GLM failover acceptance

Induce/observe primary unavailability safely and prove one immediate DeepSeek retry then GLM takeover using latest state. GLM success means NORMAL mode remains available.

## 7F. True offline + five-minute recovery acceptance

Prove both providers failing enters OFFLINE immediately; all new risk is blocked/cancelled; offline exit rules operate; virtual-clock tests prove T+5m/T+10m probes; either provider recovery returns to NORMAL after rapid factual synchronization.

## 7G. L1 acceptance

Online with either LLM available: L1 = reassessment warning only. If L1 triggers and all primary/backup attempts fail, L1 immediately force-closes without waiting five minutes.

## 7H. Base Exit and latency acceptance

Simulate/observe Exit Approach while LLM is pending; active Exit must still execute if touched. Later response is STALE and cannot mutate the closed state. Post-exit fresh reassessment occurs.

## 7I. Dynamic invocation acceptance

Same-zone oscillation 104.01/103.99/104.02/103.98 with no new information -> one call. Material large trade/volume/CVD/order-book/OI/news event may allow a second call even seconds later. Large/high-leverage exposure lowers material-event invocation threshold but never bypasses same-event deduplication.

## 7J. Partial trading / Hedge acceptance

Prove partial entry/exit, preauthorized and reassess-before-entry modes, <=25% per child new-risk order, cumulative same-symbol >25% allowed. Prove simultaneous LONG+SHORT legs are independent in logs/Growth and hedge requires an independent strategy/model thesis. Dashboard may show net exposure.

## 7K. Fast Profit acceptance

Test LONG and SHORT symmetry. Rapid profit expansion + material reversal evidence may reduce 1..100% before Base Exit and without waiting for LLM; a lone large trade or rapid move alone cannot. After sale, fresh LLM reassessment occurs.

## 7L. Cost acceptance

All profitability and edge classifications use estimated all-in costs. A superficially positive price move that is negative after fees/spread/slippage/funding must not be labeled profitable.

## 7M. Growth acceptance

Demonstrate Daily Top-10, traded/untraded review, ADD/HEDGE/Exit modification/Fast Profit/Re-entry/L1/L2/Missed Opportunity/Good Avoidance/Invocation review. Deterministic replay may validate rare branches, but counterfactuals must be clearly labeled.

## 7N. Natural PAPER lifecycle

Final factual acceptance requires at least one natural PAPER lifecycle driven by real OKX public market observations and a real configured Core LLM:

real market -> 25 real model outputs -> real Core LLM decision -> natural TradePlan -> PAPER order -> natural fill -> position monitoring -> natural exit -> Growth review.

Do not force a trade, fake a fill, fake an LLM decision or manufacture an episode to pass acceptance. If no natural lifecycle occurs during the observation window, report BLOCKED/PARTIAL and continue soak rather than fabricate evidence.

## 7O. PAPER soak

Target final soak: at least 72 continuous hours after all pre-soak gates pass. Record runtime uptime, data health, LLM latency distribution, provider success/retry/failover/offline counts, opportunities, trades/fills/partial fills, invocation/suppression counts, Risk/Fast Profit events, Growth reviews, exceptions and reconciliation health.

Re-measure LLM mean/p50/p90/p95/p99/max/timeout/retry rates. The current design baseline mean is ~8.6s, but factual runtime telemetry controls future timeout tuning. Five-minute offline recovery cadence remains a separate rule.

## P0 zero-tolerance blockers

Any of the following prevents PASS:

- duplicate new-risk order;
- oversell;
- stale LLM decision executed;
- Growth/Model/News/Risk directly creates new risk;
- new-risk order executes during true offline mode;
- individual new-risk order >25% equity;
- leverage >20x;
- unreconciled UNKNOWN order treated as failed and duplicated;
- ghost position/untracked fill;
- exit quantity exceeds factual leg quantity;
- new trade without TradePlan;
- new trade without Base Exit;
- fake/fabricated factual acceptance evidence;
- live trading enabled for this acceptance.

## Required final report

Report exact factual evidence:

LOW_RISK_V2_FINAL_ACCEPTANCE
- STARTING_SHA
- FINAL_SHA
- BRANCH
- REMOTE_SHA_MATCH
- WORKTREE_CLEAN
- ARCHITECTURE PASS/FAIL
- MARKET_DATA PASS/FAIL
- 25_MODELS PASS/FAIL
- CONSENSUS PASS/FAIL
- CORE_LLM PASS/FAIL
- GLM_FAILOVER PASS/FAIL
- OFFLINE_5M PASS/FAIL
- RISK PASS/FAIL
- BASE_EXIT PASS/FAIL
- DYNAMIC_CALLING PASS/FAIL
- PARTIAL_TRADING PASS/FAIL
- HEDGE PASS/FAIL
- FAST_PROFIT_EXIT PASS/FAIL
- EXECUTION PASS/FAIL
- GROWTH PASS/FAIL
- NATURAL_PAPER PASS/FAIL
- 72H_SOAK PASS/FAIL
- P0_BLOCKERS[]
- P1_ISSUES[]
- FINAL = PASS/PARTIAL/BLOCKED

Attach evidence using exact tests, DB/event IDs, Decision IDs, Position Episode IDs, timestamps, runtime telemetry and exact SHA. “Implemented successfully” is not evidence.

---

# HARNESS EXECUTION RULES

1. Treat this document as the controlling Low-Risk V2 contract. Do not silently reinterpret it.
2. Work phase-by-phase in dependency order. Before each phase, reread this SPEC and the previous phase receipt.
3. Maintain `docs/low-risk/receipts/PHASE_<N>_RECEIPT.md` containing baseline SHA, changes, tests, evidence, unresolved blockers and next-phase gate.
4. Do not proceed past a hard gate by weakening/removing tests or fabricating evidence.
5. Preserve main/default branch unless explicitly authorized. Work on a dedicated implementation/review branch/worktree.
6. No destructive git operations on shared/dirty worktrees: no reset --hard, clean, destructive checkout, force push or deleting unrelated work.
7. Keep commits phase-scoped and auditable. Push review refs when appropriate.
8. PAPER ONLY. Never enable live trading as part of this goal.
9. Never expose/log API keys or secrets.
10. Do not manufacture trades merely to satisfy acceptance.
11. Prefer factual integration/replay tests over mocks for behavior that can be tested factually; final Core-LLM/PAPER evidence must be real where required above.
12. If repository reality conflicts with this SPEC, stop only the affected subtask, document the exact conflict/evidence, implement safe prerequisites if unambiguous, and continue all independent work. Do not silently change the constitution.
13. If a numerical threshold is not explicitly frozen here, make it configurable, document the initial engineering default and validate it; do not present an arbitrary default as user-approved trading law.
14. Preserve authority boundaries through every refactor.
15. Final acceptance cannot start until all deterministic/static/integration gates required for soak pass.

---

# DEFINITION OF DONE

Low-Risk V2 is DONE only when:

- Phases 0–6 implementation/acceptance gates pass;
- Phase 7 factual requirements are satisfied;
- at least one natural end-to-end PAPER lifecycle exists;
- required 72h PAPER soak passes without a P0 blocker;
- Growth reconstructs the lifecycle and Daily Top-10 correctly;
- DeepSeek/GLM failover and five-minute true-offline behavior are evidenced;
- no unauthorized module can create new risk;
- final exact SHA is pushed and the final report is evidence-backed.

Until then report PARTIAL or BLOCKED, never a false PASS.
