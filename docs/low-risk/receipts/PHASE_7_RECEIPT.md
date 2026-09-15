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

## Round 55-56 update - runtime hardening + real PAPER soak started

Commits:
- `6e50870` fix: CoreLLMRouter no longer forwards `state_version` as a provider kwarg
  (real DeepSeek/GLM `complete_json` signatures rejected it; runtime startup crashed with
  TypeError). `state_version` is now popped and bound to the response metadata. Regression:
  strict-signature provider test in `tests/low_risk/test_phase4_llm_failover.py` (12 passed).
- `666c1a2` fix: `llm_offline_mode` health polarity.
  OLD BEHAVIOR: online -> health ok=False; offline -> ok=True, so `/health` reported OVERALL
  UNHEALTHY at all times and never surfaced the offline condition.
  NEW BEHAVIOR: online -> ok=True (detail NORMAL); offline -> ok=False (detail
  LLM_OFFLINE_MODE); actual state remains in `runtime_snapshot()["llm_offline_mode"]`.
  WHY SUPERSEDED: the health registry reads ok=False as a failure, so the old polarity made
  healthy runtimes look broken and could mask a real offline violation.
  Test updated in `tests/low_risk/test_phase4_offline_mode.py` with this OLD/NEW/WHY note.

Real PAPER soak (genuine, no fabricated evidence):
- Runner: clean detached worktree `/tmp/lr2-soak` at commit `666c1a2418ac`, own SQLite DB at
  alembic head `0028_opportunity_outcomes`.
- Mode: `TRADING_MODE=PAPER`, `PAPER_MODE=PAPER_REAL_MARKET`, `LIVE_TRADING_ENABLED=false`,
  `AUTO_START_RUNTIME=true`; real OKX public data; real DeepSeek key loaded from macOS
  Keychain (never printed). Listener `127.0.0.1:8010`; log `data/low-risk-paper.log`.
- Start time: 2026-09-16T05:12+08:00 (SHA `666c1a2418ac`).
- Baseline factual evidence at 2026-09-16T05:22+08:00:
  - `/health` OVERALL **OK**, all 9 components ok (adapter, restart recovery, recovery,
    execution lease, llm_offline_mode, market_data, strategy:live_llm, engine_loop,
    reconciliation).
  - `/market/sources`: ticker + orderbook + mark_price `OKX_PUBLIC` HEALTHY (age 0s).
  - `/llm/health`: provider deepseek configured + reachable, `last_success_ts`
    2026-09-15T21:09Z.
  - Real Core LLM decisions persisted: 12 by 05:22+08 (latest
    `llm_6099b013c6574dc4` NO_TRADE); positions `{}` so no lifecycle has occurred yet.
  - `data/low-risk-paper.log`: zero tracebacks/errors.
- Soak observations continue via scheduled jobs `cron-40` (day-1, 2026-09-17 05:20 +08) and
  `cron-41` (>=72h point, 2026-09-19 05:25 +08). FINAL_STATUS remains PARTIAL until a natural
  complete lifecycle and the full soak window are observed.

Hazard: the main implementation worktree carries the concurrent writer's uncommitted (and
currently startup-breaking) `llm_chief` edits; the soak deliberately runs from the clean
detached worktree at the pushed SHA.
