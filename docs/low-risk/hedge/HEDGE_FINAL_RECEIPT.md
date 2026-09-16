# HEDGE / POSITION-LEG FINAL CLOSURE RECEIPT

- SPEC_SHA: 779f7e17d0e948ba54bacb817d14d37078c811b4
- STARTING_SHA: 779f7e17d0e948ba54bacb817d14d37078c811b4 (implementation branch created from frozen Spec)
- BASELINE_SHA_IN_SPEC: 8dc0ca43451372b877f95bf7bc054170492a04ec
- BRANCH: codex/low-risk-hedge-position-leg-final-closure
- WORKTREE: /Users/huhongjie/Documents/ChatGPT/crypto-hedge-final-closure
- MODE: PAPER ONLY; LIVE never enabled.
- LAST ENGINEERING SHA BEFORE OPERATIONAL ACCUMULATION: 0ac0cf0fbc6b; final H8 switch SHA: ebd200227ef3. FINAL_SHA = branch tip reported in the final response (operational obs docs may follow).

## Checkpoint status

| Checkpoint | Status | Evidence |
|---|---|---|
| H0 forensic map | PASS | docs/low-risk/hedge/HEDGE_H0_FORENSIC_MAP.md (038f096e77c5) |
| H1 canonical leg accounting | PASS | migration 0032, VWAP/realized/exit-VWAP/fees/funding/idempotent fills; 449a074cc003 |
| H2 order/fill leg allocation | PASS | migration 0033, position_leg_orders/position_leg_fills, allocate_fill idempotency, LEG_TARGET_REQUIRED/UNKNOWN guards; e561dd7ea7fb |
| H3 independent exits | PASS | per-leg deterministic scan independent of net; leg Base Exit / Fast Profit / Risk hard exit tests; 12e10581c109 + H7 additions |
| H4 reconcile/restart | PASS | canonical status matrix, orphan/quantity/aggregate checks, recovery halt, restart preservation; 0264908d2ea5 |
| H5 PnL/economics | PASS | leg_economics/symbol_economics, portfolio comparison; 5533c02d25a0 |
| H6 API/observability | PASS | enriched /position-legs, /position-legs/summary, /position-legs/{leg_id}; 4acab03dd8db |
| H7 full regression | PASS | tests 922 passed; ruff clean; 0ac0cf0fbc6b |
| H8 natural PAPER acceptance | AUTONOMOUSLY_ACCUMULATING | no hedge forced or fabricated |

## Required result flags

- POSITION_LEG_CANONICAL_TRUTH: PASS (independent leg rows are the accounting truth; net is a view)
- SAME_SYMBOL_LONG_SHORT: PASS (both legs coexist, independent basis/Base Exit/remaining/PnL)
- LEG_ORDER_ALLOCATION: PASS (every leg order carries leg_id/plan/decision/client/reduce_only/intent/source; unique allocation row)
- LEG_FILL_ALLOCATION: PASS (fill_id -> exactly one leg; partial fills update only that leg)
- PARTIAL_FILL_LEG_SAFE: PASS
- LEG_BASE_EXIT: PASS (per-leg scanner, quantity capped to that leg)
- LEG_FAST_PROFIT: PASS (leg-specific controller test; LONG triggers, independent SHORT untouched)
- LEG_RISK_EXIT: PASS (leg-specific RISK_HARD_EXIT; independent SHORT untouched)
- ADD_TARGETS_LEG: PASS (LEG_TARGET_REQUIRED without explicit leg_id)
- HEDGE_INDEPENDENT_THESIS: PASS (validate_hedge_leg; loss-mitigation-only rejected)
- REVERSE_CLOSE_OPEN_LINEAGE: PASS (existing reverse_source validation + reverse_of lineage persisted; no signed flip)
- NET_ZERO_GROSS_RISK_SAFE: PASS (net-zero reports gross 2 and both_sides; GROSS_VIEW_REQUIRED vs net-only portfolio view)
- LEG_RECONCILIATION: PASS (MATCH/PENDING_ORDER/PARTIAL_FILL/UNKNOWN/ORPHAN_FILL/LEG_QUANTITY_MISMATCH/AGGREGATE_MISMATCH/CLOSED/RECOVERED)
- UNKNOWN_DUPLICATE_PROTECTION: PASS (leg guard + canonical unsettled-entry guard; unknown reconciliation blocks replacement)
- RESTART_RECOVERY: PASS (two legs preserved, closed leg stays closed, no double-apply)
- ORPHAN_FILL_RECOVERY: PASS (unallocated fills detected as ORPHAN_FILL; recovery halts on unsafe leg state)
- LEG_REALIZED_PNL: PASS
- LEG_UNREALIZED_PNL: PASS (mark-to-market per leg)
- LEG_FEES: PASS
- LEG_FUNDING: PASS
- PORTFOLIO_AGGREGATION_MATCH: PASS (single-side leg PnL == real PAPER portfolio PnL within 1e-8; net-zero returns explicit GROSS_VIEW_REQUIRED instead of a false match)
- API_LEG_VISIBILITY: PASS (read-only list/summary/detail with economics, orders, fills, reconciliation, lineage)
- GROWTH_LINEAGE_AVAILABLE: PASS (leg_id/strategy/direction/decision/plan/reverse_of/orders/fills/PnL/exit reason exposed; Growth runtime untouched)

## Runtime-change flags

CORE_LLM_AUTHORITY_CHANGED = NO
RISK_AUTHORITY_CHANGED = NO
EXECUTION_SAFETY_CHANGED = NO (only additive rejections/guards)
GROWTH_RUNTIME_CHANGED = NO
ML_RUNTIME_CHANGED = NO
FLASH_HIGH_POLICY_CHANGED = NO

## Test evidence

- Focused hedge/leg suites: tests/low_risk/test_hedge_h1_leg_accounting.py, test_hedge_h2_leg_allocation.py, test_hedge_h3_leg_exits.py, test_hedge_h4_reconciliation.py, test_hedge_h5_pnl.py plus existing test_phase4d_hedge_legs.py / test_phase4d_leg_reconciliation.py.
- LOW_RISK_TESTS: latest tests/low_risk run passed (included in full suite).
- FULL_TEST_SUITE: 922 passed (pytest tests -q, keyless env, PAPER mode) at code SHA 0ac0cf0fbc6b.
- RUFF: ruff check src scripts tests -> clean.
- Detached exact-SHA acceptance: executed on the tip of this receipt commit in a clean detached worktree (results in final response).

## P0_BLOCKERS

None identified.

## P1_ISSUES

- leg_execution_enabled remains false by default in the runtime; operational hedge execution still requires the net-model retirement switch. Engineering behavior is fully covered by the leg-level tests and guards.
- Portfolio's existing net position view does not expose gross-leg PnL; the leg API summary is the authoritative gross view and the comparator returns GROSS_VIEW_REQUIRED for net-zero dual-leg symbols.
- Natural same-symbol hedge/reverse has not yet occurred in live PAPER data; no forced trade or fabricated evidence was created.

HEDGE_ENGINEERING = PASS
HEDGE_OPERATIONAL_EVIDENCE = AUTONOMOUSLY_ACCUMULATING
