# LOW-RISK V2 — HEDGE / POSITION-LEG FINAL CLOSURE SPEC

Status: FROZEN TARGET CONTRACT
Repository: fyjk999-cyber/crypto-auto-trading-system
Baseline SHA: 8dc0ca43451372b877f95bf7bc054170492a04ec
Scope: same-symbol independent LONG/SHORT leg truth, execution lineage, reconciliation, PnL, exits and observability
Authority: Core LLM remains sole intelligence that may originate NEW RISK
Trading mode: PAPER ONLY until final integrated acceptance

This document refines the hedge/leg portions of `docs/low-risk/LOW_RISK_V2_MASTER_SPEC.md`.

---

## 0. VERIFIED CURRENT STATE / WHY THIS SPEC EXISTS

The repository already contains substantial Phase-4D scaffolding:

- `PositionLegORM` with side/kind/strategy/thesis/Base Exit/invalidation/evidence lineage;
- `PositionLegService`;
- `LegPositionReconciler`;
- Core-LLM HEDGE / REVERSE handling in `LiveLLMPositionManager`;
- independent `HedgeLegContract` validation;
- separate hedge/reverse TradePlan creation;
- execution metadata carrying lifecycle and reduce-only semantics;
- API exposure for `/position-legs`.

However, the final system must prove an authoritative leg-level accounting and execution model where the same symbol can factually carry simultaneous independent LONG and SHORT legs without collapsing all semantics into one net position.

The target is not “allow an opposite order.” The target is a complete factual lineage:

```
Core LLM thesis
-> independent leg contract
-> leg TradePlan
-> order intent
-> order/fill allocation
-> leg quantity / basis / fees / funding / realized/unrealized PnL
-> leg Base Exit / Risk / Fast-Profit action
-> leg reconciliation
-> leg closure
-> portfolio net aggregation
-> Growth factual episode lineage
```

---

# 1. NON-NEGOTIABLE AUTHORITY

Only Core LLM may originate:

- OPEN
- ADD
- HEDGE
- REVERSE

A same-symbol opposite leg requires an independent thesis.

“Reduce loss”, “offset exposure”, or “make net smaller” is NOT by itself a valid new-risk thesis.

Risk, Growth, models, consensus and execution safety may not originate the opposite leg.

Deterministic reduce-only exits remain permitted under the Low-Risk constitution.

---

# 2. CANONICAL POSITION TRUTH

The final system must distinguish:

## 2.1 Leg truth

Each leg has independent:

- leg_id;
- symbol;
- side LONG/SHORT;
- kind ENTRY/HEDGE/REVERSE;
- strategy;
- thesis;
- Base Exit;
- invalidation;
- evidence lineage;
- decision_id;
- trade_plan_id;
- state_version;
- opened quantity;
- remaining quantity;
- average entry price;
- realized PnL;
- unrealized PnL;
- fees;
- funding;
- opened_at;
- closed_at;
- terminal reason;
- state.

## 2.2 Portfolio aggregation truth

Portfolio-level symbol exposure may show:

- gross long quantity/notional;
- gross short quantity/notional;
- gross exposure;
- net quantity/notional;
- net PnL;
- leg count.

Net aggregation is a VIEW.

It must not destroy or replace independent leg truth.

---

# 3. ORDER / FILL ALLOCATION

Every new-risk and reduce-only order that belongs to a leg must carry:

- leg_id;
- trade_plan_id;
- decision_id;
- client_order_id;
- side;
- intended quantity;
- reduce_only flag;
- source action.

Every fill must be allocatable deterministically to exactly the intended leg(s).

No ambiguous “symbol-only fill changed the net position” may be accepted for final leg accounting.

Partial fills must update the target leg incrementally.

Order UNKNOWN must not create a duplicate replacement until reconciliation establishes factual state.

---

# 4. SAME-SYMBOL LONG + SHORT SEMANTICS

The system must support:

```
BTCUSDT
  leg_A LONG  thesis_A
  leg_B SHORT thesis_B
```

simultaneously in PAPER.

Required:

- each leg has its own entry basis;
- each leg has its own Base Exit;
- each leg may be reduced/closed independently;
- one leg closing must not implicitly close the other;
- a later ADD must identify which leg it belongs to;
- HEDGE and REVERSE must have explicit target/reverse lineage;
- net-zero symbol exposure does NOT imply no open risk if gross legs remain.

---

# 5. HEDGE VS REVERSE

## HEDGE

Creates an independent opposite leg while the original remains open.

## REVERSE

Must have an explicit transition contract.

A reverse may mean:

1. close/reduce the original leg; then
2. create an independent opposite new-risk leg.

Do not implement REVERSE as an opaque signed-quantity flip.

The final lineage must show which quantity closed and which quantity opened as new risk.

---

# 6. BASE EXIT / FAST PROFIT / RISK EXIT PER LEG

Exit evaluation must operate against the intended leg.

For each leg, the system must know:

- active Base Exit version;
- Fast Profit eligibility/state;
- Risk hard-exit state;
- partial-exit state;
- remaining quantity.

Precedence follows the Low-Risk constitution, but all resulting orders must target a factual leg and be reduce-only.

One leg’s exit condition must not automatically liquidate an independent opposite leg.

---

# 7. LEG-LEVEL RECONCILIATION

`LegPositionReconciler` must become authoritative enough to prove:

local leg state
vs
broker/PAPER fills
vs
orders
vs
portfolio aggregate

Required reconciliation outcomes:

- MATCH;
- PENDING_ORDER;
- PARTIAL_FILL;
- UNKNOWN;
- ORPHAN_FILL;
- LEG_QUANTITY_MISMATCH;
- AGGREGATE_MISMATCH;
- CLOSED;
- RECOVERED;
- HALTED / DEGRADED where safety requires.

Unknown facts must fail safe.

No new-risk replacement while an unresolved UNKNOWN may duplicate exposure.

---

# 8. RESTART / RECOVERY

After process restart, rebuild leg truth from durable facts:

- PositionLeg rows;
- orders;
- fills;
- TradePlans;
- LLM decisions;
- factual PAPER position/broker state.

Restart must not:

- merge two legs into one;
- lose reverse_of lineage;
- double-apply fills;
- reopen closed legs;
- invent Base Exit state.

---

# 9. PNL AND ECONOMICS

Each leg must have auditable:

- entry VWAP;
- exit VWAP;
- gross PnL;
- realized PnL;
- unrealized PnL;
- fees;
- slippage where estimated;
- funding;
- post-cost net PnL.

Portfolio total must equal the deterministic aggregation of leg economics plus any explicitly external/account-level cashflows.

Tests must prove reconciliation between:

leg PnL
-> symbol aggregate
-> account aggregate

within explicit precision/tolerance rules.

---

# 10. GROWTH LINEAGE

Growth is learning-only but must later be able to reconstruct factual leg episodes.

Every episode/review must be able to identify:

- leg_id;
- original/reverse leg;
- strategy;
- direction;
- plan versions;
- decision versions;
- entry/exit fills;
- leg PnL.

Do not change Growth runtime in this mission.

Only make canonical leg lineage available for later consumption.

---

# 11. API / OBSERVABILITY

Read-only surfaces must expose:

## Symbol summary
- long gross;
- short gross;
- net;
- gross exposure;
- leg count;
- unrealized/realized PnL.

## Leg detail
- leg_id;
- side;
- kind;
- state;
- strategy;
- thesis;
- Base Exit;
- plan/decision lineage;
- quantity/remaining;
- entry/mark;
- PnL;
- fees/funding;
- orders/fills;
- reconciliation state.

No API mutation path may bypass Core LLM new-risk authority.

---

# 12. REQUIRED TEST MATRIX

At minimum:

1. independent LONG + SHORT same symbol both open;
2. partial fill on LONG affects LONG only;
3. partial fill on SHORT affects SHORT only;
4. reduce-only exit closes one leg without altering other;
5. Base Exit is leg-specific;
6. Fast Profit is leg-specific;
7. Risk hard exit is leg-specific unless explicitly account-wide;
8. ADD targets explicit leg;
9. HEDGE requires independent thesis;
10. “reduce loss only” hedge rejected;
11. REVERSE shows close-old + open-new lineage;
12. net-zero with gross legs remains open risk;
13. restart preserves two-leg truth;
14. duplicate fill idempotency;
15. UNKNOWN order blocks unsafe replacement;
16. orphan fill recovery;
17. leg PnL sums to symbol PnL;
18. symbol PnL sums to portfolio PnL;
19. API reports both legs;
20. no model/Growth/Risk new-risk authority;
21. Core LLM decision lineage mandatory;
22. no live trading enabled.

---

# 13. CHECKPOINT PLAN

H0 — forensic leg/accounting map
H1 — canonical leg accounting model
H2 — order/fill leg allocation
H3 — independent exits and state transitions
H4 — reconciliation/restart recovery
H5 — PnL/economics
H6 — API/observability
H7 — full regression
H8 — natural PAPER acceptance

Each checkpoint:

implement
-> focused tests
-> ruff
-> commit
-> push
-> verify remote SHA
-> clean detached exact-SHA acceptance

---

# 14. NATURAL PAPER ACCEPTANCE

No forced trade solely for acceptance.

Required if natural opportunity occurs:

- one factual same-symbol two-leg lifecycle;
- each leg has independent thesis;
- independent fills;
- independent Base Exit;
- one leg may close independently;
- remaining leg stays correct;
- restart/reconcile succeeds;
- final PnL lineage is consistent.

If no natural hedge/reverse opportunity occurs:

```
HEDGE_ENGINEERING = PASS
HEDGE_OPERATIONAL_EVIDENCE = AUTONOMOUSLY_ACCUMULATING
```

Do not fabricate a hedge.

---

# 15. FINAL RECEIPT

Return:

STARTING_SHA
SPEC_SHA
FINAL_SHA
REMOTE_SHA_MATCH
WORKTREE_CLEAN
DETACHED_EXACT_SHA_ACCEPTANCE

POSITION_LEG_CANONICAL_TRUTH
SAME_SYMBOL_LONG_SHORT
LEG_ORDER_ALLOCATION
LEG_FILL_ALLOCATION
PARTIAL_FILL_LEG_SAFE
LEG_BASE_EXIT
LEG_FAST_PROFIT
LEG_RISK_EXIT
ADD_TARGETS_LEG
HEDGE_INDEPENDENT_THESIS
REVERSE_CLOSE_OPEN_LINEAGE
NET_ZERO_GROSS_RISK_SAFE

LEG_RECONCILIATION
UNKNOWN_DUPLICATE_PROTECTION
RESTART_RECOVERY
ORPHAN_FILL_RECOVERY

LEG_REALIZED_PNL
LEG_UNREALIZED_PNL
LEG_FEES
LEG_FUNDING
PORTFOLIO_AGGREGATION_MATCH

API_LEG_VISIBILITY
GROWTH_LINEAGE_AVAILABLE

CORE_LLM_AUTHORITY_CHANGED = NO
RISK_AUTHORITY_CHANGED = NO
EXECUTION_SAFETY_CHANGED = NO
GROWTH_RUNTIME_CHANGED = NO
ML_RUNTIME_CHANGED = NO

FOCUSED_TESTS
LOW_RISK_TESTS
FULL_TEST_SUITE
RUFF

P0_BLOCKERS
P1_ISSUES

HEDGE_ENGINEERING =
PASS | PARTIAL | BLOCKED

HEDGE_OPERATIONAL_EVIDENCE =
PASS | AUTONOMOUSLY_ACCUMULATING | PARTIAL | BLOCKED

---

# 16. FINAL GOAL

A same-symbol hedge is complete only when the system can prove exactly:

```
which LLM thesis created which leg
-> which plan authorized which order
-> which fills belong to which leg
-> what each leg owns now
-> what each leg earned/lost after costs
-> what exit protects each leg
-> how all legs reconcile to portfolio truth
```

Netting may summarize exposure, but it may never erase the factual leg model.
