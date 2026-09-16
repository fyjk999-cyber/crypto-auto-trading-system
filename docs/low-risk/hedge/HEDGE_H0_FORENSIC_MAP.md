# H0 - FORENSIC LEG / ACCOUNTING MAP

- SPEC_SHA: 779f7e17d0e948ba54bacb817d14d37078c811b4
- AUTHORITATIVE_SPEC: docs/low-risk/hedge/HEDGE_POSITION_LEG_FINAL_CLOSURE_SPEC.md
- IMPLEMENTATION_BRANCH: codex/low-risk-hedge-position-leg-final-closure
- WORKTREE: /Users/huhongjie/Documents/ChatGPT/crypto-hedge-final-closure
- MODE: PAPER ONLY; LIVE never enabled.

## Existing components (KEEP / EXTEND)

| Component | Location | H0 status |
|---|---|---|
| PositionLegORM | persistence/models.py:984 | KEEP; missing accounting fields |
| PositionLegService | execution/hedge_legs.py:144 | EXTEND with VWAP/PnL/fees/funding |
| LegPositionReconciler | execution/hedge_legs.py:357 | ADAPT to full status set |
| HedgeLegContract / validation | execution/hedge_legs.py:43-140 | KEEP (independent thesis gate) |
| Engine leg-keyed deterministic exits | runtime/engine.py:637-710 | EXTEND for multiple independent legs |
| Engine fill allocation by order metadata.leg_id | runtime/engine.py:1451-1471 | EXTEND: intended quantity, idempotency, audit |
| Core-LLM HEDGE/REVERSE handling | llm_chief/position_manager.py | KEEP authority; verify explicit reverse close+open |
| API /position-legs | api/app.py:311 | EXTEND PnL/exits/orders/fills/reconciliation |
| Tests | tests/low_risk/test_phase4d_hedge_legs.py, test_phase4d_leg_reconciliation.py | EXTEND to SPEC test matrix |

## Gap map to checkpoints

- H1 canonical leg accounting: ORM/SQL has quantity/remaining only. Missing
  average_entry_price, realized_pnl, unrealized_pnl, fees, funding, terminal_reason.
  No migration. PositionLegService has no accounting transitions. Required: migration
  0032_position_leg_accounting, ORM columns, service open/add/reduce/close accounting with
  entry/exit VWAP and precision rules.
- H2 order/fill allocation: fill settlement maps order.metadata.leg_id -> leg row
  (engine 1451). Missing intended_quantity validation, per-fill idempotency (duplicate fill_id),
  explicit allocation audit, and UNKNOWN-order protection. Required: deterministic allocation
  function + tests.
- H3 independent exits: deterministic exits resolve a single persisted leg only when exactly
  one open leg matches the position side; multi-leg symbols fall back to a synthetic plan key.
  Required: per-leg exit evaluation and reduce-only orders that always name the intended leg;
  one leg's exit must never touch the other.
- H4 reconciliation/restart: LegPositionReconciler returns only MATCHED /
  UNTRACKED_NET_POSITION / DIVERGED. Required: MATCH, PENDING_ORDER, PARTIAL_FILL, UNKNOWN,
  ORPHAN_FILL, LEG_QUANTITY_MISMATCH, AGGREGATE_MISMATCH, CLOSED, RECOVERED, HALTED/DEGRADED;
  restart reconstruction from durable rows without double-apply or leg merge.
- H5 PnL/economics: no leg PnL, fees or funding anywhere; no proof
  leg PnL -> symbol -> portfolio. Required: economic fields + aggregation reconciliation tests.
- H6 API: /position-legs returns contract/lineage basics; needs side/kind/state, quantity/
  remaining, entry/mark, realized/unrealized, fees/funding, Base Exit, reconciliation and
  orders/fills, plus per-symbol gross long/short/net summary.
- H7 full regression: run focused hedge/leg tests, tests/low_risk, tests/, ruff on the
  exact final SHA in a clean detached worktree.
- H8 natural PAPER acceptance: do not force; otherwise
  HEDGE_ENGINEERING=PASS, HEDGE_OPERATIONAL_EVIDENCE=AUTONOMOUSLY_ACCUMULATING.

## Authority invariants (must remain unchanged)

- Core LLM is the only originator of OPEN/ADD/HEDGE/REVERSE.
- A hedge/reverse requires an independent thesis; loss-reduction-only is rejected.
- Reduce-only exits may only reduce an identified leg and can never flip it.
- Net aggregation is a view; leg truth is never destroyed by netting.
- No live trading. Protected branches and Growth/ML runtimes are untouched.
