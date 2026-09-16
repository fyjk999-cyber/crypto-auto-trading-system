# LOW-RISK V2 — CORE RUNTIME CONSTITUTION CLOSURE SPEC

Status: FROZEN TARGET CONTRACT
Repository: fyjk999-cyber/crypto-auto-trading-system
Baseline SHA: 8dc0ca43451372b877f95bf7bc054170492a04ec
Scope: runtime authority semantics, position reassessment, exit precedence, stale-state protection and constitutional alignment
Trading mode: PAPER ONLY until final integrated acceptance

This document refines the runtime/authority portions of `docs/low-risk/LOW_RISK_V2_MASTER_SPEC.md`.

---

## 0. WHY THIS SPEC EXISTS

The Low-Risk V2 codebase already contains:

- Core LLM entry and position-management paths;
- TradePlan / Base Exit;
- PositionManager;
- Fast Profit;
- Risk exits;
- offline safety;
- NEXT_REASSESSMENT support;
- execution authority and lease/reconciliation safety;
- state-version and decision lineage infrastructure.

The remaining goal is to prove that every runtime action obeys the latest constitution and that no older semantic shortcut remains authoritative.

A verified example of semantic drift is current use of `max_holding_time_seconds` in the position manager as a possible reduce-only safety fallback, while the latest V2 constitution states there is no hard maximum holding time.

The target is therefore not a new runtime. It is a constitutional closure of the existing canonical runtime.

---

# 1. FINAL AUTHORITY TABLE

The final implementation must encode and test the following authority model.

## 1.1 NEW RISK — Core LLM only

Only Core LLM may originate:

- OPEN
- ADD
- HEDGE
- REVERSE
- RE-ENTRY

Models, Growth, News, Risk, consensus and deterministic runtime rules may provide evidence/protection only.

## 1.2 Position-management intelligence — Core LLM

Core LLM may decide:

- HOLD
- ADD
- REDUCE
- CLOSE
- HEDGE
- REVERSE
- MODIFY_EXIT
- NEXT_REASSESSMENT

subject to hard execution/safety contracts.

## 1.3 Deterministic risk-reducing authority

The following may reduce/close without a fresh Core-LLM order decision where already authorized by constitution:

- active Base Exit;
- preauthorized partial exit;
- Fast Profit Protection;
- Risk hard exit;
- true-offline protection/reduce logic;
- exchange/broker emergency protection where explicitly defined.

These paths must be reduce-only.

They may not originate new risk.

---

# 2. NO HARD MAXIMUM HOLDING TIME

The final Low-Risk V2 constitution has:

```
NO hard maximum holding time
```

Therefore any existing behavior equivalent to:

```
if time_in_trade >= max_holding_time_seconds:
    force reduce/close
```

must be removed or demoted from deterministic exit authority.

A legacy `max_holding_time_seconds` field may remain for backward compatibility if necessary, but its final semantic must be one of:

- informational expectation;
- reassessment trigger;
- urgency input;
- migration/deprecated field.

It must NOT directly force an exit.

Target behavior:

```
time threshold reached
-> high-priority Core LLM reassessment
-> fresh factual state
-> LLM decides HOLD / REDUCE / CLOSE / MODIFY_EXIT / etc.
```

Existing active Base Exit / Fast Profit / Risk hard exit remain in force while reassessment occurs.

---

# 3. EXPECTED HOLDING PERIOD VS HARD EXIT

Distinguish:

- expected_holding_period;
- reassessment timing;
- strategy thesis horizon;
- hard deterministic exit.

Expected duration is not an order.

Time passage alone does not prove thesis failure.

Any deterministic time-based close must be explicitly authorized by strategy/Base Exit contract; default is NONE.

---

# 4. POSITION REASSESSMENT

Reassessment must use fresh factual state.

Required inputs include where available:

- current position/leg state;
- fills;
- pending orders;
- plan version;
- state version;
- mark/price;
- order book;
- trades/CVD;
- OI/funding/basis;
- regime/evidence;
- PnL;
- relevant News;
- relevant Growth context.

No stale prompt replay after provider failover/retry.

---

# 5. REASSESSMENT TRIGGERS

A Core LLM reassessment may be triggered by:

- material price movement;
- ATR-normalized abnormal velocity;
- large trade;
- RVOL/volume anomaly;
- CVD/taker-flow reversal;
- order-book dislocation;
- OI/funding/basis anomaly;
- material News;
- Risk L1 escalation;
- Fast Profit action requiring fresh continuation decision;
- Base Exit fill requiring re-entry/new-opportunity assessment;
- LLM-requested NEXT_REASSESSMENT;
- expected holding horizon reached.

Triggering reassessment does not itself authorize an order.

---

# 6. DEDUP / INFORMATION NOVELTY

Repeated oscillation without material new facts must not repeatedly invoke Core LLM.

Example:

```
104.01
103.99
104.02
103.98
```

with unchanged evidence should not create four equivalent reassessments.

Use:

- event identity;
- materiality;
- information novelty;
- position state version;
- pending invocation state;
- cooldown where justified.

One active reassessment per leg/position.

New facts may update pending context.

---

# 7. STALE RESPONSE PROTECTION

Every actionable LLM decision must prove it is based on the current relevant state.

Required lineage:

- decision_id;
- based_on_state_version;
- trade_plan_id / plan version;
- position/leg version;
- relevant pending-order state.

If material state changes while LLM is thinking:

- response becomes stale;
- stale response must not create new risk or alter exits;
- fresh reassessment required.

Examples:

- old Base Exit fills;
- position quantity changes;
- another reduce-only action fills;
- order moves to UNKNOWN;
- leg closes;
- new hedge/reverse opens.

---

# 8. BASE EXIT

Every new entry/new-risk leg requires an active Base Exit contract.

Rules:

- old Base Exit remains active until replacement is validated, persisted and atomically activated;
- MODIFY_EXIT must create a new version;
- no gap where no exit protection exists because LLM is thinking;
- stale replacement cannot activate after factual state changed;
- Base Exit is reduce-only;
- Base Exit fill closes/reduces the intended position/leg only.

---

# 9. FAST PROFIT PROTECTION

Fast Profit is deterministic risk-reducing protection.

It may reduce/close only when the configured factual conditions are satisfied, including:

- position is profitable;
- rapid ATR-normalized expansion;
- material reversal evidence.

One random large trade alone is insufficient.

After Fast Profit action:

- persist factual action/fill;
- call Core LLM fresh if further continuation/re-entry decision is needed;
- do not let Fast Profit create new risk.

---

# 10. RISK L1 / L2 / HARD EXIT

Risk remains observation/protection, not a pre-trade strategy authority.

## L1
May trigger reassessment / warning.

## L2
May escalate urgency and apply defined protection where constitution permits.

## Hard exit
May deterministically reduce/close when a hard safety condition is met.

Risk must not:

- invent OPEN/ADD/HEDGE/REVERSE;
- choose a substitute position size as strategy;
- silently resize an invalid Core-LLM new-risk order.

Invalid new-risk constitutional contract is rejected, not silently transformed.

---

# 11. EXECUTION AUTHORITY

Preserve all mature non-strategy safety gates:

- execution lease;
- kill switch;
- reconciliation halt;
- market/order-book health;
- exchange/balance freshness;
- precision/min-notional;
- duplicate client-order protection;
- rate limiting;
- order ownership/fencing;
- UNKNOWN reconciliation.

ExecutionAuthority may reject structurally unsafe/invalid new-risk intent.

It may not become a strategy engine.

---

# 12. OFFLINE MODE

When Core LLM providers are unavailable:

```
LLM_OFFLINE_MODE
```

must immediately prohibit:

- OPEN;
- ADD;
- HEDGE;
- REVERSE;
- RE-ENTRY.

Pending new-risk orders must be cancelled/reconciled safely.

Existing protection remains:

- Base Exit;
- Fast Profit where preauthorized/deterministic;
- Risk hard exit;
- true-offline reduce-only safety logic.

At recovery probe:

- rebuild fresh factual state;
- reconcile;
- return to NORMAL immediately when provider is usable;
- no arbitrary extra delay.

No synthetic decision.

---

# 13. BASE EXIT / FAST PROFIT / RISK PRECEDENCE

The final runtime must have one explicit and tested precedence policy.

Reference target:

1. exchange/emergency hard safety;
2. Risk hard exit;
3. Fast Profit protection;
4. active Base Exit;
5. Core LLM discretionary position-management action.

Where two actions race:

- state version and fill truth decide;
- later stale action is rejected/reconciled.

No double-close.

No reduce beyond remaining quantity.

---

# 14. PARTIAL REDUCE / CLOSE

REDUCE and CLOSE must operate on factual remaining quantity.

Required:

- partial fill support;
- remaining quantity update;
- idempotency;
- no over-close;
- no sign flip from a reduce-only order;
- stale second close rejected.

For leg-capable systems, target specific leg lineage.

---

# 15. ADD / HEDGE / REVERSE CONTRACT

Every new-risk child must satisfy:

- Core LLM decision;
- valid strategy/thesis;
- TradePlan;
- Base Exit;
- <=25% equity allocation per child;
- <=20x leverage;
- factual instrument/economics;
- current state version;
- execution safety.

Invalid child:

REJECT

not silent resize.

---

# 16. NEXT_REASSESSMENT

NEXT_REASSESSMENT is a wake-up contract, not an order.

Supported condition classes may include:

- PRICE;
- TIME;
- INDICATOR;
- EVENT;
- logical AND/OR;
- priority.

When condition becomes true:

- invoke Core LLM with fresh state;
- do not execute a trade merely because reassessment condition fired.

---

# 17. STATE MACHINE

At minimum distinguish:

- NORMAL;
- LLM_REASSESSMENT_PENDING;
- LLM_OFFLINE_MODE;
- RECONCILING;
- EXIT_PENDING;
- ORDER_UNKNOWN;
- DEGRADED;
- HALTED where hard safety requires.

State must reflect actual runtime truth.

No “NORMAL” while unresolved UNKNOWN new-risk exposure exists.

---

# 18. AUDIT / LINEAGE

For every significant runtime transition persist enough evidence to answer:

- what state existed;
- what event triggered action;
- who had authority;
- what plan/version applied;
- what order was created;
- what fill occurred;
- why later action was accepted/rejected as stale.

At minimum link:

decision_id
trade_plan_id
leg_id where applicable
order_id
fill_id
state_version
event/audit id

---

# 19. REQUIRED TEST MATRIX

## Max-hold semantics
1. time threshold does not force close;
2. time threshold triggers reassessment;
3. Base Exit remains active during reassessment;
4. Risk hard exit still works before/after time threshold.

## Authority
5. model cannot OPEN;
6. Growth cannot OPEN;
7. Risk cannot OPEN;
8. Core LLM required for OPEN/ADD/HEDGE/REVERSE;
9. deterministic exits are reduce-only.

## Stale response
10. Base Exit fills while LLM thinks -> LLM response rejected stale;
11. partial reduction changes state -> old ADD rejected;
12. UNKNOWN order -> no duplicate new-risk replacement;
13. leg closed -> old MODIFY_EXIT rejected.

## Exit precedence
14. Risk hard exit beats discretionary action;
15. Fast Profit vs Base Exit no double-close;
16. Base Exit vs later stale LLM close no double-close;
17. quantity cannot go below zero.

## Offline
18. offline blocks new risk;
19. protection continues;
20. recovery reconciles then NORMAL;
21. no fabricated decisions.

## NEXT_REASSESSMENT
22. trigger wakes LLM only;
23. no order emitted by trigger itself;
24. dedup/no novelty suppresses repeated wakeups.

## Execution
25. constitutional >25% child rejected;
26. >20x rejected;
27. invalid new-risk order not silently resized;
28. execution lease/kill/reconcile gates preserved.

---

# 20. CHECKPOINT PLAN

R0 — forensic runtime authority map
R1 — max-hold semantic correction
R2 — reassessment/dedup/stale-state closure
R3 — exit precedence and partial-close safety
R4 — offline/recovery semantics
R5 — NEXT_REASSESSMENT closure
R6 — authority/execution contract audit
R7 — observability/lineage
R8 — fresh full regression
R9 — natural PAPER acceptance

Every checkpoint:

implement
-> focused tests
-> ruff
-> commit
-> push
-> verify remote SHA
-> clean detached exact-SHA acceptance

---

# 21. NATURAL PAPER ACCEPTANCE

Do not force trades solely for acceptance.

Required natural evidence where available:

- Core LLM entry;
- active Base Exit;
- one or more fresh reassessments;
- no hard time-stop forced exit;
- stale-response rejection after factual state change;
- deterministic protection lineage;
- offline/recovery if naturally testable in controlled PAPER environment.

Synthetic unit/integration fixtures may test engineering semantics.

Natural runtime facts must remain factual.

If a rare event does not occur naturally:

```
RUNTIME_ENGINEERING = PASS
RUNTIME_OPERATIONAL_EVIDENCE = AUTONOMOUSLY_ACCUMULATING
```

---

# 22. FINAL RECEIPT

Return:

STARTING_SHA
SPEC_SHA
FINAL_SHA
REMOTE_SHA_MATCH
WORKTREE_CLEAN
DETACHED_EXACT_SHA_ACCEPTANCE

HARD_MAX_HOLD_EXIT_REMOVED
TIME_THRESHOLD_REASSESSMENT
EXPECTED_HOLDING_NOT_ORDER

CORE_LLM_NEW_RISK_AUTHORITY
MODEL_NEW_RISK_AUTHORITY = NO
GROWTH_NEW_RISK_AUTHORITY = NO
RISK_NEW_RISK_AUTHORITY = NO

BASE_EXIT_ACTIVE_DURING_REASSESSMENT
BASE_EXIT_ATOMIC_REPLACEMENT
FAST_PROFIT_REDUCE_ONLY
RISK_HARD_EXIT_REDUCE_ONLY
OFFLINE_NEW_RISK_BLOCK

STALE_RESPONSE_PROTECTION
STATE_VERSION_ENFORCED
UNKNOWN_DUPLICATE_PROTECTION

EXIT_PRECEDENCE
NO_DOUBLE_CLOSE
PARTIAL_REDUCE_SAFE
NO_SIGN_FLIP_REDUCE_ONLY

NEXT_REASSESSMENT_WAKES_ONLY
REASSESSMENT_DEDUP
INFORMATION_NOVELTY_GATE

EXECUTION_LEASE_PRESERVED
KILL_SWITCH_PRESERVED
RECONCILIATION_GATE_PRESERVED
INVALID_NEW_RISK_REJECTED_NOT_RESIZED

AUDIT_LINEAGE_COMPLETE

GROWTH_RUNTIME_CHANGED = NO
ML_RUNTIME_CHANGED = NO
FLASH_HIGH_POLICY_CHANGED = NO

FOCUSED_TESTS
LOW_RISK_TESTS
FULL_TEST_SUITE
RUFF

P0_BLOCKERS
P1_ISSUES

RUNTIME_ENGINEERING =
PASS | PARTIAL | BLOCKED

RUNTIME_OPERATIONAL_EVIDENCE =
PASS | AUTONOMOUSLY_ACCUMULATING | PARTIAL | BLOCKED

---

# 23. FINAL GOAL

The runtime is constitutionally closed only when every action can be explained as:

```
fresh factual state
-> authorized decision/protection source
-> versioned plan/state
-> safe execution contract
-> factual order/fill
-> reconciled state
```

and no legacy shortcut can silently create or destroy risk outside that authority model.
