# PHASE 7 RECEIPT - RACE/AUTHORITY MATRIX, NATURAL PAPER, SOAK

Status: **IN PROGRESS** (deterministic race matrix largely covered; natural PAPER lifecycle and
>=72h soak NOT yet observed - no fabricated evidence)

BASE_SHA: 422ddee7cc7d
LATEST_SHA: 36d8fdf49086 (receipts) - race commits 514b17e, 123afec, 422ddee, a00583d,
09f26c2, 9521cc6

## SPEC race coverage map

- DeepSeek timeout, previous order succeeded: test_phase4_llm_failover.py (primary timeout ->
  retry; no blind order replay)
- DeepSeek->GLM duplicate prevention: failover tests (fresh-state rebuilder required; stale prompt
  skipped)
- LLM vs Base Exit race: test_phase4_exit_coordinator.py + engine stale DETERMINISTIC_EXIT_STALE guard
- LLM vs Fast Exit race: test_phase4_fast_profit.py + coordinator priority tests
- L2 while ADD pending: test_phase7_exit_races.py::test_l2_survives_add_and_stays_latched_after_recovery
- partial fill then reversal: chaos partial-fill tests + lifecycle partial-exit test
- cancel/fill race: test_phase7_exit_races.py::test_cancel_then_late_fill_does_not_change_factual_position
- offline with pending BUY/ADD/HEDGE: test_phase4_offline_mode.py (enter -> cancel pending new
  risk, protections still run)
- duplicate WS fill: test_phase7_exit_races.py duplicate fill + test_phase7_market_races.py duplicate delta
- REST/WS disagreement: test_phase7_market_races.py::test_stale_ws_sequence_against_rest_snapshot_never_applies
- Exit V1->V2 race: test_phase7_exit_races.py::test_exit_v1_to_v2_race_rejects_resurrecting_old_version
- LONG+SHORT same symbol: test_phase4d_hedge_legs.py (independent contract) + engine
  HEDGE_EXECUTION_BLOCKED_NET_MODEL until leg portfolio exists
- cumulative exposure >25% allowed / child >25% reject: test_phase4_authority_contract.py
  (V2 contract gate: child <=25% equity, leverage <=20x, reject not resize)
- Fast partial exit + Base Exit: test_phase7_exit_races.py::test_fast_profit_partial_then_base_exit_never_oversells
- stale LLM after exit: engine stale-state cancellation + test_phase4_base_exit.py STALE_DECISION
- restart recovery: canonical chaos/recovery tests exist; full Low-Risk V2 restart e2e still open

## Test/regression evidence

- tests/low_risk -> 193 passed at round 51; ruff check src/ tests clean at every commit.
- Race files: test_phase7_exit_races.py (11), test_phase7_market_races.py (3).

## P0 blockers

None in the current net-position model (hedge execution is fail-closed).

## P1 issues

- Leg-source-of-truth portfolio not implemented: the portfolio remains net per symbol, so hedge
  execution stays blocked (HEDGE_EXECUTION_BLOCKED_NET_MODEL); LegPositionReconciler + engine gate
  are ready for the flip when legs become authoritative.
- Restart-recovery e2e for the Low-Risk V2 paths (lineage, leg rows, exit reservations) pending.
- Natural PAPER acceptance (real OKX market -> 25 models -> real DeepSeek -> TradePlan -> PAPER
  order -> fill -> exit -> Growth review) not yet observed; requires real credentials + market
  opportunity. No fake evidence will be produced.
- >=72h PAPER soak not started (requires deterministic gates + natural lifecycle first).

## Next

1. Restart-recovery e2e over lineage/leg/exit-reservation state.
2. Natural PAPER lifecycle with real OKX public data + real configured DeepSeek (GLM backup),
   recorded with IDs/timestamps/SHA; report PARTIAL/BLOCKED if no natural trade occurs.
3. Start the >=72h soak after deterministic gates pass; observe uptime, market/25-model health,
   DeepSeek latency p50/p90/p95/p99, retries, GLM failover, offline windows/recovery,
   opportunities, decisions, orders, fills, Fast Profit, Risk, dedup, Growth Top-10,
   reconciliation, exceptions.
