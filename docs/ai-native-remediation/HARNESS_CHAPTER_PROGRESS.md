# Harness Chapter Progress (auto-advance)

This file records Harness self-verified chapter progress on
`codex/full-market-factor-layer`. It is NOT Codex approval.

Last update: 2026-09-09 (later rounds).

Latest HEAD at update: 13f127a

## Test baseline
```text
PYTHONPATH=src pytest -q             -> 651 passed, 1 warning
ruff check .                         -> PASS
frontend npm test                    -> 23 passed
frontend npm run typecheck           -> PASS
frontend npm run build               -> PASS
```

## Chapter records
| Ch | Candidate SHA | Harness Self Verification | Codex Review | Final State |
|----|---------------|--------------------------|--------------|-------------|
| 00 | 20202a6 | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 01 | 7953130 | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 02 | ddeb01c | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 03 | 4c8b057 | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 04 | 012cc32 | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 05 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 06 | 492543e | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 07 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_VIA_EXISTING_TESTS |
| 08 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_VIA_EXISTING_TESTS |
| 09 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_VIA_EXISTING_TESTS |
| 10 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_VIA_EXISTING_TESTS |
| 11 | f840b68 | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 12 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_VIA_EXISTING_TESTS |
| 13 | 0135e80 | PASS | NOT_REVIEWED | SELF_VERIFIED_COMPLETE |
| 14 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_VIA_EXISTING_TESTS |
| 15 | c06aec2 | PASS | NOT_REVIEWED | SELF_VERIFIED_VIA_EXISTING_TESTS |

Notes:
- Chapters 07-15 were not newly rewritten in this Harness run; they were
  verified through the existing full backend/frontend test suite and prior
  fullmarket baseline code.
- Long-running 24h runtime/natural lifecycle evidence remains outside this
  code-only Harness gate and is NOT claimed complete.


## MASTER CORRECTION ORDER STATUS (supersedes prior completion claims)

This section supersedes all prior `SELF_VERIFIED_COMPLETE` / `SELF_VERIFIED_VIA_EXISTING_TESTS` states below.

```text
00 = PASS
01 = CHANGES_REQUESTED
02 = CHANGES_REQUESTED
03 = CHANGES_REQUESTED
04 = PARTIAL_PASS
05 = CHANGES_REQUESTED
06 = CHANGES_REQUESTED
07 = CHANGES_REQUESTED
08 = NOT_FULLY_REVIEWED
09 = NOT_FULLY_REVIEWED
10 = BLOCKED_BY_UPSTREAM
11 = CHANGES_REQUESTED
12 = CHANGES_REQUESTED
13 = CHANGES_REQUESTED
14 = PROVISIONAL_PASS
15 = BLOCKED

PENDING_NO_NATURAL_TRADE = NOT_CURRENTLY_VALID
OBJECTIVE_STATUS = ACTIVE
ENGINEERING_ACCEPTANCE = FAIL
NATURAL_ACCEPTANCE = NOT_READY
CURRENT_PHASE = CORRECTION_AND_CONVERGENCE
```

AUTO_CORRECTION_MODE = TRUE
CODEX_REVIEW_REQUIRED_FOR_NEXT_STEP = FALSE
USER_CONFIRMATION_REQUIRED_BETWEEN_CHAPTERS = FALSE

## MASTER CORRECTION PROGRESS (auto-correction)

Latest HEAD: 732d661
Backend gate: 686 passed
Ruff: PASS

| Ch | Status | Evidence |
|----|--------|----------|
| 01 | FIXED_PENDING_REGRESSION | cancel mutation fenced by current lease/fence |
| 02 | FIXED_PENDING_REGRESSION | full factual USDT linear-SWAP registry, no forced LINEAR_PERP |
| 03 | FIXED_PENDING_REGRESSION | no `or Decimal("1")`; missing real depth fails closed; no synthetic book seed |
| 04 | PARTIAL_PASS | existing indicator tests green |
| 05 | CHANGES_REQUESTED | execution scope still must be declared/scoped truthfully |
| 06 | PARTIAL_PASS | factual daily net PnL into Risk; drawdown history still pending |
| 07 | FIXED_PENDING_REGRESSION | missing volatility rejects; factual orderbook size used as liquidity |
| 08 | NOT_FULLY_REVIEWED | targeted verification pending after P0/P1 |
| 09 | NOT_FULLY_REVIEWED | targeted verification pending after P0/P1 |
| 10 | BLOCKED_BY_UPSTREAM | full lifecycle regression after upstream fixes |
| 11 | PARTIAL_PASS | reversal PnL + periodic equity returns; more hand-calc cases pending |
| 12 | PARTIAL_PASS | ordered split complete; OOS/ablation still pending |
| 13 | PARTIAL_PASS | UTC-only bootstrap; durable run-state table still pending |
| 14 | PROVISIONAL_PASS | frontend green |
| 15 | BLOCKED | fixed-SHA natural acceptance requires engineering acceptance first |

## FINAL ENGINEERING CONVERGENCE PROGRESS

Latest HEAD: 172ba13 (plus later commits)
Backend gate: 688 passed
Ruff: PASS

```text
PRIORITY_0 restart-safe global PAPER exchange_order_id = DONE (c6db0b1)
06 MTM equity + durable cash-flow adjusted drawdown = IMPLEMENTED (f03b3b8)
13 paginated full-day review + startup backfill = IMPLEMENTED (172ba13)
11 terminal close canonical slippage semantics = DONE (dcbfb77)
05 EXECUTABLE_SCOPE = USDT_LINEAR_SWAP_ONLY = DONE (e93249d)
```

Still open:
```text
06 cash-flow test matrix and stale valuation exhaustive tests
13 PENDING->RUNNING CAS lifecycle proof and >1000 episode regression
08 targeted verification
09 targeted verification
10 full lifecycle chaos/restart regression
11 full hand-calculated backtest matrix
12 OOS/ablation/counterexample/leakage
14 frontend final contract regression
15 fixed-SHA natural acceptance
```

ENGINEERING_ACCEPTANCE = NOT_YET_PASS
NATURAL_ACCEPTANCE = NOT_READY
