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

## P0 FOUND IN REAL PAPER SOAK + FIX (round 60) - f392074e4817

### Factual evidence (first soak window, SHA 666c1a2418ac, DB preserved)

- Real Core LLM decision `llm_ae03aa89b02e4197ac86b0751d58fe2a` (CAPUSDT SHORT, 2026-09-15T21:18:16Z).
- TradePlan `plan_487c03568218493698f8f687a3aba429`: `plan_version=1`,
  `base_exit_json=null`, `based_on_state_version=null`.
- Order `ord_208a5fde163148559b47b67189b80f05` (SELL 122 CAPUSDT) -> 6 partial fills
  (`fill_57190f...` ... `fill_62682a...`) -> FILLED; plan stayed ACTIVE, no exit order.
- Soak restart then lost the in-memory PAPER simulator position; the DB still held the
  factual fills, and recovery did not detect the divergence.

### P0 classification

1. **Trade without Base Exit**: `derive_execution_terms` returned `order_contract=None`
   for legacy (plan_version<2) entries, bypassing the execution hard contract, so a real
   PAPER entry without any Base Exit was submitted. This is on the SPEC P0 list.
2. **Untracked factual exposure after restart**: local factual fills implied a short
   position the portfolio/exchange did not show; recovery neither halted nor flagged it.

### Fix (commit `f392074e4817`, tests 214 passed low_risk+bootstrap+api)

- `execution/contract.py`: legacy entries no longer bypass the contract. Every new-risk
  child builds `NewRiskOrderContract` with `base_exit_present` (plan or metadata), the
  Core-LLM allocation and leverage; missing Base Exit -> `BASEEXIT_MISSING`, missing
  allocation -> `NEW_RISK_ALLOCATION_MISSING`, >25% -> `NEW_RISK_CHILD_OVER_25PCT_EQUITY`,
  >20x -> `LEVERAGE_OVER_20X`; rejection never resizes. New observation mode
  `V2_HARD_CONTRACT_APPLIED_TO_LEGACY_PLAN`. Reduces/exits keep the legacy path.
- `tests/low_risk/test_phase4_risk_gate_adapt.py` updated with
  OLD BEHAVIOR / NEW BEHAVIOR / WHY SUPERSEDED (real P0 order id cited).
- `runtime/engine.py`: `_run_recovery` compares signed DB fill exposure per symbol with the
  live portfolio; divergence -> audit `RECOVERY_FACTUAL_DIVERGENCE`,
  `reconciliation_halted=True` (existing authority rejects new risk),
  health `recovery_factual_state=False`; matching state -> ok=True.
- `tests/low_risk/test_phase6_lineage.py`: seeded CAPUSDT SELL 122 fill with no portfolio
  position -> recovery returns the divergence flag, halts and audits it.

### Soak consequence

- First window stopped on detection and its DB kept as evidence at
  `/tmp/lr2-soak/data/crypto_trader.db` (order/plan/decision ids above).
- New clean window started 2026-09-16T05:42+08 from `/tmp/lr2-soak2` at `f392074e4817`
  (fresh DB, real OKX public data, real DeepSeek, PAPER only, LIVE disabled);
  `/health` OVERALL OK at start. Scheduled checks `cron-42` (day 1) and `cron-43` (>=72h).
- FINAL_STATUS stays PARTIAL: the prior window cannot count toward the 72h gate.

## Soak window attempt #3 - V2 prompt verified against real DeepSeek (5269cd63d2fe)

- Window started 2026-09-16T05:49+08 in `/tmp/lr2-soak2` (detached worktree at `5269cd63d2fe`,
  fresh DB at alembic head `0028`, real OKX public data, real DeepSeek key from macOS Keychain,
  `TRADING_MODE=PAPER` / `LIVE_TRADING_ENABLED=false`, port 8010).
- Factual evidence at 2026-09-16T05:52+08 (uptime 02:45, `/health` OVERALL OK, no error lines):
  - 5 real Core LLM decisions persisted; 0 trade plans, 0 orders, 0 fills (no fabricated trade).
  - Latest real decision payload (audit `LIVE_LLM_DECISION`):
    `action=NO_TRADE`, `plan_contract_version=2`, `capital_allocation_pct=0.0`,
    `leverage_request=0.0`, `base_exit=null` - i.e. the new prompt contract is being
    followed by the real provider; NO_TRADE correctly carries no Base Exit obligation.
  - Earlier `FAIL_CLOSED` decisions show `plan_contract_version=1` (internally constructed
    fail-closed objects, never submitted).
- Interpretation: the round-61 prompt fix works against the real DeepSeek API. A natural
  lifecycle requires the LLM to choose LONG/SHORT with a Base Exit and allocation during the
  soak window; until then FINAL_STATUS stays PARTIAL (no fabrication).
- Scheduled durable checks: `cron-44` (day 1, 2026-09-17 06:05 +08) and `cron-45`
  (>=72h, 2026-09-19 06:10 +08); harvester `scripts/low_risk_soak_report.py` is read-only.

## P1 note - dashboard legs panel

`frontend/` has no `node_modules` in this environment and dependency installation/verification
could not be performed offline, so the legs panel was not modified without a way to run
`frontend-verify.sh`/tests. The backend `/position-legs` API (contracts + lineage, authority
`NEW_REQUIRES_CORE_LLM`, `not_an_order`) remains available for the UI to consume.

## NATURAL PAPER LIFECYCLE OBSERVED (window attempt #4, SHA 1ef721d6d491)

Started 2026-09-16T05:57+08 in `/tmp/lr2-soak2` (clean DB at alembic head 0028, real OKX public
data, real DeepSeek key, PAPER only, LIVE disabled, port 8010).

Factual chain observed (no forcing, no fabrication):

1. Real Core LLM decisions -> natural V2 TradePlans (`plan_version=2`, real Base Exit):
   - `plan_443020240b35479780c814f12963ad18` MSTRUSDT SHORT, state ACTIVE,
     base_exit = {"type":"PRICE","trigger":"128.5","size_pct":100.0,"reason_code":"STOP_LOSS"}.
   - `plan_b04336a683844daeaf290227e80b51ba` AIUSDT SHORT, state APPROVED, V2 Base Exit
     (trigger 0.02072, size_pct 100.0).
2. Canonical PAPER execution:
   - `ord_e528edf81f4f4fbebf2da14e74375a22` MSTRUSDT SELL 0.5 -> FILLED.
   - natural fill `fill_205b343e5f6b47b6b3a72e6425c749a7` @ 128.09 (2026-09-15T21:59:30Z),
     persisted `FILL_SETTLED` + `FILL_LINEAGE` (trade_complete chain).
   - `ord_6a48ea30717444c9922a91d4e560f9ce` AIUSDT SELL 226 remains OPEN at snapshot.
3. Canonical position (GET /positions): MSTRUSDT quantity -0.5, avg_entry 128.09,
   leverage 1, instrument LINEAR_PERP, mark 128.30, unrealized_pnl -0.105.
4. Position management: `LIVE_LLM_POSITION_DECISION` audit entries present (Core LLM
   reassessing the live position); latest decision HOLD with
   reason codes NO_INVALIDATION / TREND_REMAINS_BEARISH / PLAN_CONDITIONS_NOT_MET.
5. `DETERMINISTIC_EXIT_LEG_KEY` audits show the active Base Exit registered for both plans.

Exit leg (deterministic Base Exit fill -> Growth review) is still pending at snapshot time, so
the lifecycle is IN PROGRESS, not complete. FINAL_STATUS remains PARTIAL until the exit and
Growth review are observed and the >=72h soak completes.

### Diagnostics added this window

- `INVALID_LLM_OUTPUT` now carries the exact validation detail and raw keys (commit `1ef721d`).
  First observed cause: `base_exit.size_pct` returned as 0 (must be >0). Committed prompt
  clarification `ab83a42` ("size_pct ... (0,100], use 100 for full exit; 0 is invalid") for
  future windows; the running acceptance window keeps SHA `1ef721d6d491` untouched.
- Previous window attempt #3 (5269cd6) verified the V2 prompt but produced no trades before
  being replaced for diagnostics.

## Growth daily Top-10 freeze wired to the live runtime (46b9b245075a)

- Added `scripts/freeze_daily_top10.py`: reads the live runtime's real
  `/opportunity/candidates` (FACTOR_SCANNER decision-time candidates), maps
  `score = factor_trigger_count + sum(triggered strength)/1000`, and persists the
  first freeze for the trading day through the canonical `DailyOpportunityFreezer`
  (idempotent, no hindsight; learning-only, never an order).
- Executed against acceptance window #4 at 2026-09-16T06:08+08:
  `trading_day=2026-09-16`, `frozen=true`, `already_frozen=false`,
  `candidate_count=12`, 10 persisted rows; top ranks: CAPUSDT (3.0019),
  CLUSDT (2.0018), PONSUSDT (2.0017), all `FACTOR_SCANNER`.
- DB evidence: `daily_opportunity_top10` rows = 10 for `2026-09-16`.
- The running acceptance process was not restarted; `/health` stayed OVERALL OK and
  the natural position (MSTRUSDT -0.5) remained live.
- Durable schedule `cron-48` runs the same command daily at 00:05 Asia/Shanghai and
  verifies first-freeze immutability on re-run.

## NATURAL PAPER LIFECYCLE COMPLETE (window #4, SHA 1ef721d6d491) - 2026-09-16T06:08+08

One fully natural lifecycle occurred with no forcing and no fabricated evidence:

1. Real OKX public market -> factual factor/evidence context (live scanner candidates,
   fee/freshness checks) -> real DeepSeek Core LLM.
2. Natural V2 decision and TradePlan: `plan_443020240b35479780c814f12963ad18` MSTRUSDT SHORT,
   `plan_version=2`, Base Exit `{"type":"PRICE","trigger":"128.5","size_pct":100.0,
   "reason_code":"STOP_LOSS"}`, state CLOSED. Entry decision
   `llm_a63bc93866134df490c6f7aa6483b567`.
3. Canonical PAPER entry order `ord_e528edf81f4f4fbebf2da14e74375a22` SELL 0.5 -> FILLED;
   natural fill `fill_205b343e5f6b47b6b3a72e6425c749a7` @ 128.09
   (2026-09-15T21:59:30.848107Z), persisted `FILL_SETTLED` + `FILL_LINEAGE`.
4. Position management by Core LLM: 8 `LIVE_LLM_POSITION_DECISION` audits (HOLD/reassessments)
   while the position was live (GET /positions: MSTRUSDT -0.5 @ 128.09, leverage 1,
   LINEAR_PERP, mark 127.95, unrealized +0.070).
5. Natural exit by Core LLM: decision `llm_b2a7f455d45d43f1b5a0d9fd377e661d` action=EXIT at
   2026-09-15T22:08:31.704547Z -> reduce-only order
   `ord_...` MSTRUSDT BUY 0.5, metadata `{lifecycle_action: EXIT, reduce_only: true,
   trade_plan_id: plan_443...}` -> FILLED in two natural fills
   `fill_44a9efaeafeb4fa5866b5...` @128.12 (0.32) and `fill_b084157e59ff4ec2a5d12...` @128.13
   (0.18); position returned to 0 and the plan closed.
6. Growth: `TRADE_EPISODE_CREATED` audit and persisted episode
   `episode_plan_443020240b35479780c814f12963ad18` (direction SHORT,
   entry_decision_id `llm_a63bc938...`, exit_decision_id `llm_b2a7f455...`,
   created_at/closed_at 2026-09-15T22:08:34Z).
7. Growth daily Top-10 frozen for `2026-09-16` (10 rows, real FACTOR_SCANNER candidates,
   first-freeze immutable; `cron-48` repeats daily at 00:05 Asia/Shanghai).

Integrity at snapshot: `orders=3`, `fills=3`, `FILL_SETTLED=3`, `FILL_LINEAGE=3`,
`ORDER_SUBMITTED=3`; no duplicate client order ids, no oversell, no ghost position
(second plan AIUSDT remains APPROVED with a resting SELL 226, untouched).

Remaining before PASS: the >=72h soak window (started 2026-09-16T05:57+08; durable checks
`cron-46`/`cron-47`) and P1 items (Growth seven-review write-through scheduling, leg-level
portfolio/dashboard panel). `NATURAL_PAPER` = ACHIEVED; `FINAL_STATUS` = PARTIAL pending soak.
