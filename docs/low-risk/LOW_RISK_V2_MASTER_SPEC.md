# LOW-RISK V2 — IN-PLACE EVOLUTION MASTER SPEC

Status: FROZEN TARGET CONTRACT + EXISTING-CODE MIGRATION CONTRACT
Scope: LOW-RISK only. Turbo is out of scope except explicitly adopted profit-protection ideas.
Repository: fyjk999-cyber/crypto-auto-trading-system
Target branch at rewrite: codex/final-canonical-ai-runtime-bootstrap
Safety: PAPER ONLY until final acceptance. Never enable live trading for this goal.

## 0. THIS IS NOT A GREENFIELD REWRITE

Low-Risk V2 MUST be implemented by evolving the existing crypto_trader architecture in place. The repository already contains substantial AI, decision, risk, execution, runtime, recovery, memory, market, persistence, API/UI and test infrastructure. Preserve and extend proven components instead of creating a parallel `low_risk_v2` application or replacing working subsystems wholesale.

Observed existing architecture on the target branch includes, among others:

- `src/crypto_trader/ai/` — context/evaluation/memory and analyst infrastructure.
- `src/crypto_trader/ai_decision/` — existing decision/fusion/conflict layer. `AIDecisionEngine` already declares “No direct execution”; evolve this boundary rather than bypassing it.
- `src/crypto_trader/ai_memory/` — embedding, market memory and similarity primitives; reuse/extend for Growth retrieval where appropriate.
- `src/crypto_trader/ai_risk/` — existing AI-risk review/approval concepts. Audit carefully because Low-Risk V2 changes authority semantics.
- `src/crypto_trader/risk/` — existing deterministic risk engine, kill switch and leverage utilities.
- `src/crypto_trader/execution/authority.py` — mature final execution gate with execution lease, kill switch, reconciliation halt, market/order-book health, exchange/balance freshness, duplicate-client-order protection, precision/min-notional and rate limiting.
- `src/crypto_trader/execution/` — existing execution guards/rate limiting.
- `src/crypto_trader/runtime/engine.py` — large existing runtime orchestration engine; extend rather than build a second runtime.
- `src/crypto_trader/runtime/ai_position_bridge.py` — existing AI/position bridge; preferred integration point for event-driven position reassessment if compatible.
- `src/crypto_trader/runtime/recovery.py`, `lease.py`, `event_bus.py`, `state_machine.py`, `health.py`, `bootstrap.py` — existing recovery/ownership/state/health/bootstrap foundations; preserve their semantics and extend them.
- existing domain models/enums, persistence/migrations, PAPER simulator, market adapters, API/dashboard and tests discovered during Phase 0.

The current `ExecutionAuthority` explicitly requires a `risk_decision` of APPROVE/SCALE_DOWN before an order can pass. Low-Risk V2 constitution says Risk must NOT be a pre-trade sizing/leverage decision-maker. This is a known migration point: preserve all non-strategy execution safety gates, but refactor the pre-trade risk-approval coupling without deleting execution lease, kill switch, reconciliation, market health, exchange health, precision, min-notional, duplicate-order or rate-limit protections.

Likewise, the existing `AIDecisionEngine` fuses quant and AI directional decisions. Low-Risk V2 must evolve this into the Core-LLM authority/evidence contract while preserving compatible interfaces and callers where practical; do not simply add a second unrelated decision engine.

### Mandatory migration rule

Before changing a subsystem, classify it as:

- KEEP — behavior already satisfies V2.
- EXTEND — preserve implementation/API and add fields/behavior.
- ADAPT — behavior conflicts with V2 but existing subsystem remains canonical after migration.
- DEPRECATE — old behavior cannot remain authoritative; keep compatibility shim/migration path until callers/tests are moved.
- ADD — capability genuinely does not exist.

Every Phase receipt MUST include this KEEP/EXTEND/ADAPT/DEPRECATE/ADD map with exact files/classes/functions. New parallel subsystems are prohibited unless Phase 0 proves extension is technically unsafe and the receipt documents why.

---

# 1. NON-NEGOTIABLE LOW-RISK V2 CONSTITUTION

Optimization order:
1. Long-term net compounding growth.
2. Drawdown control.
3. Win rate.
4. Opportunity count.

Core LLM is the only intelligence allowed to originate new risk. Primary = DeepSeek; backup Core LLM = GLM. The 25 models, News, Growth, market data, portfolio/account data, consensus and Risk are evidence/protection tools, not independent new-risk authorities.

Legal new-risk path must be implemented through the EXISTING canonical runtime/domain/execution pipeline:

existing market/runtime -> evidence -> existing/evolved decision boundary -> Core LLM -> versioned TradePlan/OrderIntent -> existing/evolved ExecutionAuthority -> existing broker/PAPER path.

Do not bypass canonical OrderIntent/domain models, execution lease, reconciliation, persistence or simulator to implement V2.

Forbidden: Model/Growth/News/Risk/consensus directly creates OPEN/ADD/HEDGE/REVERSE.

Authorized deterministic risk-reducing exits: active Base Exit, preauthorized partial exit, Fast Profit Protection, Risk hard exit and true-offline sell/reduce logic.

Limits:
- leverage per new-risk order <=20x;
- capital allocation per individual new-risk order <=25% total equity;
- 25% is per child order, not per symbol/episode; repeated LLM-authorized ADD/HEDGE may make cumulative symbol exposure >25%;
- no hard total-account exposure cap;
- no hard maximum holding time;
- avoid economically meaningless tiny orders after costs;
- LONG and SHORT allowed;
- same-symbol LONG+SHORT allowed only with independent strategy/model thesis for the opposite leg; “reduce loss” alone is invalid.

All edge/profitability calculations use estimated all-in economics: entry/exit fees, spread, slippage, funding where relevant and other estimable costs. High confidence with trivial post-cost edge is not a valid trade.

---

# PHASE 0 — FORENSIC CURRENT-ARCHITECTURE MAP (MANDATORY BEFORE CODE CHANGES)

## Objective

Build V2 on the actual repository, not assumptions. No invasive V2 implementation before this receipt passes.

## Required audit

Inspect the complete target branch and produce `docs/low-risk/receipts/PHASE_0_RECEIPT.md` containing:

1. exact STARTING_SHA/branch/worktree/runtime SHA and DB/migration head;
2. package/module tree for runtime, domain, persistence, market, AI/LLM, decision, risk, execution, broker/simulator, portfolio/positions, Growth/memory, news, API/UI and tests;
3. every order/new-risk creation path and every deterministic reduce-only path;
4. current DeepSeek provider/call/retry/latency path and any existing provider abstraction suitable for GLM;
5. current Factor/indicator/model implementation and which of the required 25 models already exist wholly/partially;
6. current evidence/context builder and decision schemas;
7. current TradePlan/OrderIntent/order/fill/position/leg/domain models and DB tables;
8. current RiskDecision/pre-trade approval coupling, deterministic risk behavior, kill switch and leverage rules;
9. current execution authority, lease, idempotency/client-order IDs, UNKNOWN reconciliation, TTL, partial-fill, cancel/fill and restart recovery;
10. current Growth/review/memory system, including any implementation outside an obvious `growth/` package; search by behavior/schema/scripts/tables, not folder name only;
11. current market universe/scanner/data sources/caches/order-book/trades/CVD/OI/funding/basis/news;
12. current API/dashboard position presentation and whether hedge-mode/net-vs-leg data is already supported;
13. test inventory and current full-suite baseline;
14. migration risks/backward-compatibility constraints.

## Required migration matrix

For every V2 capability identify CURRENT -> TARGET -> ACTION -> EXACT EXISTING INTEGRATION POINT.

At minimum map:
- market scan;
- 25-model evidence;
- consensus;
- context/evidence package;
- Core LLM;
- DeepSeek provider;
- GLM backup;
- TradePlan;
- Base Exit;
- NEXT_REASSESSMENT;
- event-driven position monitor;
- Risk L1/L2;
- Fast Profit;
- partial trading;
- hedge legs;
- Growth;
- execution authority;
- reconciliation/recovery;
- persistence;
- API/UI.

## Gate

PHASE_0 cannot PASS with vague statements such as “existing module found.” Exact files/classes/functions/tables/tests are required. Do not delete/rewrite existing architecture before this map exists.

---

# PHASE 1 — EVOLVE EXISTING MARKET/DATA PIPELINE

Use the repository’s existing market adapters/scanner/runtime caches as canonical. Do NOT create a second market-data service if current abstractions can be extended.

Target behavior:
- scan full OKX USDT perpetual universe available to runtime;
- liquidity/volume/data-quality prefilter before expensive model/LLM work;
- preserve existing market-source compatibility unless it conflicts with factual OKX requirements;
- distinguish closed candles from live price/order-book/trade observations;
- bounded multi-symbol caches with source/timestamp/freshness/quality/retry semantics;
- expose OHLCV, real-time price, spread, L1/L5/L10 depth where available, trades/taker flow/CVD, OI, funding, basis, relative volume, trade-count/notional activity and liquidity quality;
- stale/incomplete evidence explicitly degrades quality.

Migration rule: extend existing market/domain DTOs and cache services first. Any new DTO must interoperate with current runtime callers and persistence.

Acceptance: factual full-market discovery, traceable prefilter, freshness/quality evidence, no market component order authority, existing market tests remain green plus new V2 tests.

---

# PHASE 2 — EVOLVE FACTOR/ANALYTICS INTO 25-MODEL EXPERT EVIDENCE

Do not throw away existing factor/indicator implementations. Audit and wrap/reuse mathematically equivalent code. Replace authority semantics, not proven calculations.

Required expert set:
01 EMA Multi-TF (20/50/200)
02 MACD (12/26/9; histogram acceleration/divergence)
03 ADX+DI (14)
04 RSI Context (14, regime-aware)
05 Bollinger Regime (20,2σ)
06 VWAP Deviation (daily/rolling/anchored)
07 ATR/NATR (14)
08 Volume Breakout / relative volume
09 CVD/Taker Flow
10 Price+OI
11 SMA Structure (20/50/200)
12 SuperTrend (initial ATR10 x3, configurable)
13 Stochastic RSI (14/14/3/3)
14 ROC (12 initial)
15 CCI (20)
16 Price Z-Score (50/100 initial)
17 Support/Resistance (swing+volume-profile+multi-TF)
18 OBV
19 MFI14
20 CMF20
21 Order Flow ML — probability future return exceeds cost threshold
22 Order Book Imbalance — L1/L5/L10/microprice/spread/persistence/cancel velocity
23 Funding+Basis crowding/context
24 Market Regime — TREND_UP/TREND_DOWN/RANGE/BREAKOUT_EXPANSION/HIGH_VOLATILITY/LIQUIDATION_DISLOCATION/UNCERTAIN
25 XGBoost Meta Forecast — restrained P(NetReturn_horizon > MinimumEdge)

Provisional timeframe roles: 4H macro, 1H primary trend, 15m trade structure, 5m entry/change, 1m execution/microstructure. Keep configurable.

Evolve existing domain/model result types to carry:
model_id/version/family, asset/timestamp/timeframes, LONG/SHORT/NEUTRAL, direction_score, confidence, theory, support/counter evidence, regime/strategy compatibility, entry/exit/reassessment use, invalidation, data_quality/freshness and Growth reliability/sample/tier.

Do not create an isolated 25-model result format that the existing context builder/runtime cannot consume. Prefer extending canonical evidence DTOs/adapters.

Acceptance: all 25 factual outputs available to existing/evolved context path; raw opposition preserved; no model execution authority; existing factor callers either migrated or compatibility-adapted with tests.

---

# PHASE 3 — EVOLVE EXISTING `ai_decision` FUSION INTO RECOMMENDATION, NOT AUTHORITY

Existing `src/crypto_trader/ai_decision/decision_engine.py`, `fusion.py`, `conflict.py` are migration targets. Preserve compatible interfaces where useful, but their quant/AI fusion must no longer be capable of becoming an independent trading authority.

Target recommendation includes raw consensus, opposition, neutral count, family consensus, correlation-adjusted/effective consensus, Effective Independent Evidence, Growth reliability/sample/tier, regime compatibility, data quality, strategy fit, strongest support and strongest 3 Devil’s Advocate counterarguments.

Rolling 30D/90D score-output correlation is an initial auditable approach; configurable, not immutable law.

20L/0S/5N must differ from 20L/5S/0N. Correlated EMA/SMA/MACD/SuperTrend votes must not count as four independent facts. 25/25 consensus remains `NOT_AN_ORDER`.

Acceptance must include regression tests for existing decision/fusion callers and prove no direct execution path was introduced.

---

# PHASE 4 — EVOLVE EXISTING AI/RUNTIME INTO CORE-LLM TRADEPLAN + POSITION MANAGEMENT

## 4A. Reuse existing AI/context/runtime seams

Prefer evolving `src/crypto_trader/ai/context_builder.py`, existing AI analyst/provider abstractions, `ai_decision`, `runtime/engine.py`, `runtime/ai_position_bridge.py`, event bus/state machine and existing domain models. Do not add a second orchestration loop unless Phase 0 proves the canonical engine cannot safely host V2.

Core LLM evidence package = Market + all 25 raw outputs/consensus/counter-evidence + News + relevant Growth + Account/positions + Execution economics.

## 4B. Structured Core LLM contract

Evolve existing decision/domain DTOs to structurally carry:
SHOULD_TRADE TRADE/WAIT/REJECT; ACTION OPEN/HOLD/ADD/REDUCE/CLOSE/HEDGE/REVERSE/MODIFY_EXIT; direction; strategy; capital allocation; leverage; expected edge/cost assumptions; confidence; thesis; support/counter evidence; mandatory Base Exit for new entry; Exit Approach; Adverse Trigger; Thesis Invalidation; partial entry/exit; re-entry/T; PositionPlan version/based_on_state_version; NEXT_REASSESSMENT.

Execution must never parse prose to infer an order.

## 4C. Strategy / Base Exit / plan versioning

Every new entry requires strategy + versioned TradePlan + Base Exit. Initial strategies: TREND_FOLLOWING, PULLBACK, BREAKOUT, MOMENTUM, MEAN_REVERSION, SUPPORT_REBOUND, VWAP_REVERSION.

No maximum holding time. Optional time exit defaults NONE.

Old active Base Exit remains valid until a new plan is validated, persisted and atomically activated. If old Exit fills while LLM is thinking, later response is stale. After Base/Fast sale, call LLM fresh for re-entry/new opportunity.

When losing, LLM may not simply move a LONG target below entry (mirror SHORT) to postpone failure. It may CLOSE/REDUCE or open a valid independent opposite HEDGE/REVERSE thesis. Record loss/thesis failure to Growth.

## 4D. Partial trading / hedge

Reuse canonical OrderIntent/order/position representations. Extend them with episode/leg/plan lineage rather than bypassing them.

Partial buys/sells are allowed. LLM may preauthorize conditional child orders or require reassessment before child entry. Every new-risk child <=25% equity; cumulative same-symbol may exceed 25%.

Same-symbol LONG+SHORT may coexist. Backend logs/Growth/Risk facts are leg-independent; dashboard may show net exposure with expandable legs. Opposite leg requires independent strategy/model reason; “reduce loss” alone invalid.

## 4E. Event-driven position reassessment

Integrate into existing runtime/event bus/position bridge. No second polling daemon if canonical scheduler/event bus can host it.

`InvocationPriority=f(cumulative exposure,current order size,leverage,notional,PnL,event severity,information novelty,urgency)`.

Large/high-leverage positions can invoke LLM repeatedly over short intervals only when material NEW information exists. Same-zone oscillation such as 104.01/103.99/104.02/103.98 without new evidence triggers once.

Material override events: large trades, RVOL/volume surge, ATR-normalized abnormal price velocity, activity/notional-turnover/trade-count anomaly, CVD/taker reversal, order-book dislocation, OI/funding/basis/liquidation anomaly, material News, L1 or LLM-requested reassessment.

One active reassessment per leg/position; newer facts update pending state. State-version protection controls stale response execution.

## 4F. NEXT_REASSESSMENT

LLM may request PRICE/TIME/INDICATOR/EVENT conditions with AND/OR and priority. This wakes LLM only; it is not an order/stop and existing exits remain active.

## 4G. DeepSeek -> GLM -> OFFLINE

Reuse current provider/runtime call infrastructure. Extend provider abstraction for GLM rather than duplicating the entire decision path.

DeepSeek call -> one immediate retry -> GLM using latest factual state -> one immediate GLM retry -> if both unavailable, immediately `LLM_OFFLINE_MODE`.

Known design baseline mean call duration ~8.6s. Instrument actual mean/p50/p90/p95/p99/max/timeout/retry. Do not infer final timeout from mean alone.

True offline runs in five-minute windows. At T+5m, T+10m, ... probe again. If either provider recovers, rapidly reconcile factual exchange/local/pending-order/plan state and immediately return NORMAL; no arbitrary extra recovery delay.

Offline prohibits OPEN/ADD/HEDGE/REVERSE/RE-ENTRY and cancels/reconciles pending new-risk orders. Reduce/protective exits remain.

## 4H. Adapt existing Risk without destroying safety infrastructure

This is a critical migration. Existing deterministic `risk/`, `ai_risk/` and `ExecutionAuthority.risk_decision` coupling must be audited and adapted.

Target authority:
- Risk does NOT choose/scale/reject LLM leverage or position size as a strategy decision before entry.
- Keep kill switch, execution lease, reconciliation halt, market/orderbook health, exchange/balance freshness, precision/min-notional, duplicate protection, rate limiting and other non-strategy execution safety checks.
- Keep a structural/safety validation that an LLM order obeys hard constitutional limits (<=20x, <=25% equity per new-risk child, valid instrument/precision/etc). This is execution contract validation, not Risk choosing a smaller trade.
- Online, if either DeepSeek or GLM is available: L1 = reassessment warning only; LLM may HOLD/ADD/REDUCE/CLOSE. L2 = forced hard exit.
- If L1 hits and DeepSeek+retry and GLM+retry all fail, L1 immediately force-closes; do not wait five minutes.
- L1/L2 history belongs to Position Risk Episode; ADD does not reset it.

Do not delete `ExecutionAuthority` and replace it with a permissive executor. Refactor only the incompatible `RISK_NOT_VALID`/SCALE_DOWN semantics while preserving its safety gates and regression tests.

Do not invent final L1/L2 numerical thresholds if not already authorized. Preserve/audit existing factual thresholds or make candidates configurable and Growth-validated.

## 4I. Offline exits

Every existing leg in true offline has two sell/reduce mechanisms:

1. Hard Risk Exit.
   - non-profitable by estimated net-exit PnL: L1 is forced close;
   - profitable: initial protection = current factual price +/-0.5%, mirrored LONG/SHORT, but do not intentionally convert a profitable position into loss. If the 0.5% line is below estimated break-even protection and current price permits, use estimated break-even; if current is between cost basis and fee-inclusive break-even, protect at cost basis. Refresh every 30m tightening only; major profit jump may tighten immediately.
2. 25-model strategic exit: HOLD/REDUCE/CLOSE only, using documented correlation-adjusted evidence; never OPEN/ADD/HEDGE/REVERSE.

## 4J. Fast Profit Protection

Integrate with existing position/execution event flow, not a separate broker path. Applies online/offline, LONG/SHORT symmetric. Requires estimated-net-profitable position + rapid profit expansion relative to ATR/volatility + material reversal evidence (large opposite trade/CVD reversal/orderbook deterioration/volume climax/price rejection). A lone large trade or fast move alone is insufficient.

May sell 1..100%, including full close. Avoid uneconomic fragments. After sale trigger fresh Core LLM reassessment. Major profit jump may tighten protection immediately.

---

# PHASE 5 — EVOLVE EXISTING MEMORY/REVIEW INTO GROWTH V2

Phase 0 must find the canonical existing Growth implementation even if it is spread across AI memory, optimization/research, scripts, persistence or runtime. Do not assume “no `growth/` folder” means no Growth. Reuse existing episode/review/memory tables and retrieval pipelines where compatible; migrate schemas instead of creating a disconnected second memory universe.

Growth remains evidence only; zero order authority.

Required review taxonomy:
1 OPPORTUNITY;
2 ENTRY;
3 POSITION MANAGEMENT — HOLD/ADD/PARTIAL BUY/PARTIAL SELL/HEDGE/REVERSE/MODIFY EXIT/strategy transition;
4 EXIT — Base/Fast/LLM/L2/Offline;
5 RE-ENTRY;
6 RISK — L1 behavior/L2/offline quality;
7 LLM INVOCATION quality.

Daily Top-10: freeze top 10 from all opportunities at decision time, traded or not. Preserve all 25 outputs, consensus, News, Regime, relevant memory, LLM decision/reason/edge/confidence/strategy/plan/non-fill reason. Evaluate +15m/+30m/+1h/+4h/+12h/+24h, MFE/MAE and post-cost actual/counterfactual outcomes. Classify traded-correct, traded-wrong, correctly-avoided, missed-opportunity.

ADD review compares actual versus no-ADD. HEDGE review compares actual hedge vs close original vs hold original vs close+full reverse. Exit modification compares actual vs old Base Exit. Fast Profit compares actual partial/full exit vs original Base/no-fast/alternate fractions. Re-entry evaluates continuation recovery vs churn. Every L2 gets 24h before/after review where data exists. LLM invocation review learns which triggers justify expensive calls.

Three memory speeds should be implemented by extending existing memory/retrieval primitives where possible:
- FAST EXPERIENCE: immediate/provisional/decaying;
- PATTERN: clustered Asset x Regime x Strategy/Horizon etc;
- VALIDATED: larger post-cost walk-forward/stability evidence.

Initial engineering sample tiers: <20 provisional, 20–49 emerging, 50–99 candidate, >=100 formal-validation eligible. Configurable; not immutable trading law.

Fast learning may affect LLM context immediately but may not directly mutate model formulas, Risk hard rules or execution safety. Detect possible strategy rationalization after losses and preserve evidence rather than banning genuine adaptation.

Acceptance: existing memory/review history remains readable/migrated; no duplicate parallel truth store; Daily Top-10 and all required reviews reconstruct from canonical factual events; counterfactuals clearly labeled non-factual.

---

# PHASE 6 — EVOLVE EXISTING EXECUTION/RUNTIME/RECOVERY, DO NOT REPLACE THEM

Canonical implementation must continue through existing domain OrderIntent/order models, `execution/authority.py`, runtime engine, execution lease, reconciliation/recovery and PAPER simulator/broker.

## Identity lineage

Extend existing IDs/schema to preserve:
OpportunityID -> DecisionID -> PositionEpisodeID -> LegID -> TradePlanVersion -> IntentID -> ExecutionID -> ClientOrderID -> ExchangeOrderID -> FillID(s).

Reuse current idempotency/client-order mechanisms; extend, do not invent a second ledger.

## Order lifecycle

Preserve/evolve existing statuses to support CREATED/SUBMITTED/ACK/PARTIAL/FILLED and REJECTED/CANCEL_PENDING/CANCELLED/EXPIRED/UNKNOWN. UNKNOWN != FAILED and must reconcile before replacement.

## TTL / partial fill / economics

Use existing order expiry/TTL fields and scheduler where possible. Strategy-aware TTL; expiry never automatically chases price. Partial fills immediately create factual protected position quantity. Track intended entry separately from actual VWAP/costs. Material execution deviation -> fresh LLM reassessment.

## State/version concurrency

Extend canonical persisted plan/position state with version. Every LLM request binds to state version. If fills/exits/material state change, old response is STALE and cannot execute. Base Exit replacement is atomic; old Exit stays active until new version commits.

## Exit Coordinator

Integrate coordination into canonical runtime/execution layer so Base Exit, Fast Profit, LLM reduce/close, offline exit and Risk exit cannot oversell. Track actual qty/reserved reduce/pending reduce/fills.

Priority:
1 Risk hard exit;
2 Offline hard exit;
3 Fast Profit;
4 Active Base Exit;
5 LLM REDUCE/CLOSE;
6 LLM new risk.

## ExecutionAuthority migration

KEEP all current safety gates unless Phase 0 proves a defect: lease, mode/live-enable, kill switch, reconciliation halt, expiry, market/orderbook freshness/health, symbol tradeability, exchange/balance health, valid state, duplicate-client protection, precision, min qty/notional, rate limit.

ADAPT the current requirement that `risk_decision` must APPROVE/SCALE_DOWN. Replace strategy-risk approval with explicit V2 order-contract validation and deterministic hard-safety state. Do not permit Risk to silently SCALE_DOWN an LLM trade. An invalid >20x or >25%-equity child order is rejected as a constitutional contract violation, not resized.

## Offline/recovery

On true offline cancel/reconcile pending new-risk orders using existing broker/recovery machinery. At five-minute probe recovery, reconcile factual state through existing recovery service and return NORMAL immediately when coherent.

## Event ledger

Extend canonical persistence/event infrastructure to replay OPPORTUNITY, MODEL_EVIDENCE, LLM_REQUEST/RESPONSE, PLAN_CREATED/CHANGED, ORDER_INTENT/SUBMIT/ACK/PARTIAL/FILL/CANCEL, EXIT_TRIGGER, RISK, FAST_PROFIT, HEDGE, REENTRY, POSITION_CLOSED, provider failover/offline/recovery/reconciliation. Do not create an unconnected shadow ledger if existing persistence can be migrated.

## Required race/regression tests

- DeepSeek timeout while prior intent/order succeeded;
- DeepSeek->GLM no duplicate;
- LLM response simultaneous Base/Fast exit;
- L2 while ADD pending;
- partial fill then reversal;
- cancel/fill race;
- offline with old pending BUY/ADD/HEDGE;
- duplicate WS fill;
- temporary REST/WS disagreement;
- Exit V1->V2 race;
- same-symbol LONG+SHORT;
- cumulative symbol >25% legal;
- individual new-risk child >25% rejected;
- Fast partial exit + Base simultaneous;
- post-sale stale LLM response;
- restart recovery of episodes/legs/orders;
- all pre-existing execution/recovery/lease/reconciliation tests remain green unless a test encoded superseded authority semantics, in which case update it with explicit migration rationale.

No race may create duplicate exposure, oversell, ghost position, offline new risk or stale-decision execution.

---

# PHASE 7 — FACTUAL ACCEPTANCE ON THE EVOLVED EXISTING SYSTEM

Final result = PASS / PARTIAL / BLOCKED. Code existence is insufficient.

## Pre-soak acceptance

Prove on the evolved canonical runtime:
- authority: Models/Growth/News/Risk/consensus cannot originate new risk;
- 25 factual model outputs reach Core LLM including opposition;
- consensus correlation/opposition tests;
- real configured DeepSeek structured decision path;
- DeepSeek one retry -> GLM latest-state failover;
- both unavailable -> immediate OFFLINE and five-minute windows;
- online L1 warning-only; L1 becomes force close when both calls fail;
- Base Exit remains active during ~8.6s-class LLM wait and stale reply is rejected;
- same-zone oscillation dedup; material new event may call again seconds later;
- larger/high-leverage cumulative position increases invocation sensitivity without defeating dedup;
- partial buys/sells, preauthorized and reassess-before-entry modes;
- <=25% per child order and cumulative >25% symbol exposure;
- independent-leg hedge contract;
- Fast Profit 1..100%, LONG/SHORT symmetry, requires profit expansion + reversal evidence;
- all-in cost classification;
- Growth Daily Top-10 and counterfactual reviews;
- restart/reconciliation preserves canonical existing system facts.

## Natural PAPER lifecycle

At least one natural end-to-end PAPER episode using real OKX public observations and real configured Core LLM:
real market -> 25 factual models -> real Core LLM -> natural TradePlan -> canonical PAPER OrderIntent/execution -> natural fill -> canonical position monitoring -> natural exit -> Growth review.

NO forced trades, fake fills, fake LLM decisions or fake episodes. If none occurs, report PARTIAL/BLOCKED and continue observation.

## 72h soak

After deterministic gates pass, target >=72 continuous hours. Measure uptime/data health, mean/p50/p90/p95/p99/max LLM latency, timeout/retry, DeepSeek success, GLM failover, offline windows/recovery, opportunities/orders/fills/partial fills, LLM calls/dedup/material calls, Risk/Fast events, Growth reviews, reconciliation and exceptions.

Known design baseline mean LLM call ~8.6s is comparison evidence, not a hard timeout rule. Five-minute offline recovery cadence is separate and fixed.

## P0 blockers

No PASS if any duplicate new-risk order, oversell, stale LLM decision execution, unauthorized new-risk authority, offline new-risk fill, individual child >25% equity, leverage >20x, UNKNOWN duplicated, ghost/untracked fill, exit qty > factual leg qty, trade without TradePlan/Base Exit, fabricated acceptance evidence, live trading, or regression that breaks canonical lease/reconciliation/persistence safety.

---

# REQUIRED PHASE RECEIPTS / ANTI-REWRITE CONTROL

For every Phase create/update `docs/low-risk/receipts/PHASE_<N>_RECEIPT.md` with:
- BASE_SHA / FINAL_PHASE_SHA;
- exact existing modules inspected;
- KEEP/EXTEND/ADAPT/DEPRECATE/ADD table;
- files changed;
- schema/migration changes;
- backward-compatibility notes;
- tests before/after;
- factual evidence;
- P0/P1 issues;
- next gate.

Before creating ANY new top-level package/service/table, receipt must answer:
1. What existing component was considered?
2. Why can it not be safely extended?
3. How will there remain exactly one canonical source of truth/path?

If those cannot be answered, extend existing architecture instead.

Do not remove mature safety/recovery functionality merely because V2 changes strategy semantics. In particular, never discard execution lease, kill switch, reconciliation, idempotency, UNKNOWN handling, persistence or runtime recovery to simplify implementation.

---

# GIT / OPERATING RULES

- Dedicated implementation/review branch/worktree; do not modify main without authorization.
- No reset --hard, clean, destructive shared checkout, force push or unrelated-history rewrite.
- Preserve dirty/shared worktrees.
- Phase-scoped auditable commits.
- PAPER ONLY.
- Never expose secrets/API keys.
- No manufactured trades for acceptance.
- If repository reality conflicts with this document, preserve the constitution, document exact conflict in the receipt, adapt the existing architecture safely, and do not silently greenfield-rewrite.
- Numerical thresholds not frozen here must be configurable and labeled engineering defaults until validated.

---

# FINAL REPORT

Return evidence-backed:
STARTING_SHA, FINAL_SHA, BRANCH, REMOTE_REF, REMOTE_SHA_MATCH, WORKTREE_CLEAN;
PHASE_0..PHASE_7;
ARCHITECTURE, EXISTING_CODE_REUSE, MARKET_DATA, 25_MODELS, CONSENSUS, CORE_LLM, GLM_FAILOVER, OFFLINE_5M, RISK, BASE_EXIT, DYNAMIC_CALLING, PARTIAL_TRADING, HEDGE, FAST_PROFIT_EXIT, EXECUTION, GROWTH, NATURAL_PAPER, 72H_SOAK;
P0_BLOCKERS, P1_ISSUES;
FINAL_STATUS=PASS/PARTIAL/BLOCKED.

Every PASS requires tests plus factual IDs/timestamps/DB/runtime evidence/exact SHA where applicable. “Implemented successfully” is not evidence.

# DEFINITION OF DONE

DONE means the EXISTING canonical crypto_trader system has been evolved in place, not replaced by a parallel Low-Risk app; Phase 0 proves the migration map; compatible existing AI/runtime/risk/execution/recovery/memory/persistence components are reused; conflicting authority semantics are explicitly adapted; Phases 0–6 gates pass; at least one natural PAPER lifecycle exists; 72h soak passes without P0; Growth reconstructs the lifecycle/Top-10; DeepSeek/GLM/five-minute offline behavior is evidenced; and final exact SHA is pushed. Otherwise report PARTIAL/BLOCKED.