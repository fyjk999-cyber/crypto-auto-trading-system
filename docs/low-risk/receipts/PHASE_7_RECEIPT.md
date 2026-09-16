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

## Growth review materialised from the natural episode (49a88b0f7b5e)

- Added `scripts/growth_lifecycle_review.py`: reads the canonical DB only, derives entry/exit
  VWAP from the persisted fills of the closed plan, counts Core-LLM position decisions, and
  writes the applicable review taxonomy entries through `GrowthPersistence` into the existing
  `ai_trade_reviews` table. Learning-only; every finding cites persisted ids.
- Executed against acceptance window #4 (real data, no fabrication):
  - episode `episode_plan_443020240b35479780c814f12963ad18`, MSTRUSDT SHORT,
    entry_vwap 128.09 / exit_vwap 128.1236 over 3 fills -> net_bps = -2.6232.
  - written 2 reviews: `EXIT_MODIFICATION_REVIEW` and `LLM_INVOCATION_REVIEW`, both
    verdict DEFECT (factual small loss), persisted with lesson
    `... defect with outcome_bps=-2.623155593723163` and future_rule
    `<REVIEW>:DEFECT`. Other taxonomy types (ADD/HEDGE/FAST_PROFIT/REENTRY/RISK) were not
    applicable to this lifecycle and were not fabricated.
- Durable daily job `cron-49` (00:10 Asia/Shanghai) runs the Top-10 freeze plus this
  post-close review derivation and reports NO_NEW_EPISODE honestly when no new close exists.
- The running soak process was not restarted; `/health` stayed OVERALL OK and the natural
  lifecycle remains the acceptance evidence.

## Full canonical regression on a clean HEAD worktree (ed88fd1dbd91)

Method: detached worktree `/tmp/lr2-verify` at the exact committed SHA, canonical venv,
keyless environment (`DEEPSEEK_API_KEY` unset so no test can call the real API),
`PYTHONPATH=<worktree>/src TRADING_MODE=PAPER LIVE_TRADING_ENABLED=false pytest tests -q`.

Result: **859 passed** (second run; 0 failures). One earlier run showed a single
intermittent simulator fill-timing failure
(`test_short_reduce_exit_is_factual_reduce_only_and_never_reverses`), which passed 3/3
isolated runs and in the full rerun - same known load-dependent fill-timing flake class
as previous rounds, not an order/authority defect.

### Superseded legacy tests migrated to the V2 constitution (10 tests)

`tests/integration/test_live_llm_position_lifecycle.py` previously encoded legacy
pre-trade Risk coupling and Base-Exit-free entries.

- OLD BEHAVIOR: legacy entries bypassed the hard contract; Risk SCALE_DOWN resized the
  child (quantity 2 -> 1) and reduced leverage (10 -> 5); plans had no Base Exit.
- NEW BEHAVIOR: every new-risk entry carries `plan_contract_version=2` +
  `capital_allocation_pct` + `base_exit`; ExecutionAuthority rejects or executes the
  LLM child unchanged; the LLM's leverage (10, <=20x) and size reach the order path.
- WHY SUPERSEDED: round-60 real-PAPER P0 (legacy order without Base Exit) plus the SPEC
  rule "Risk is not a pre-trade sizing gate; reject invalid contracts, never resize".
- File header records this OLD/NEW/WHY; the Risk-resize test was renamed to
  `test_risk_scale_down_no_longer_resizes_v2_child` and asserts the LLM size is preserved.

## Soak observations: more natural V2 entries + OFFLINE window with 5-minute recovery

Window #4 (SHA 1ef721d6d491) continued, no restart:

- Two additional natural V2 entries before the offline window:
  - order `ord...` LITUSDT SELL 146 -> FILLED at 2026-09-15T22:22:07Z
    (plan `plan_64bfd1ff6e6a4342ada1280d78f...`, v2 SHORT ACTIVE, Base Exit present);
  - order `ord...` CRCLUSDT SELL 8.5 -> FILLED at 2026-09-15T22:22:43Z
    (plan `plan_ab18912e6af145e3b0bd6dd58ea...`, v2 SHORT ACTIVE).
- LLM_OFFLINE_MODE entered 2026-09-15T22:24:54Z (`reason=CORE_LLM_ROUTER_OFFLINE`;
  DeepSeek call chain failed and GLM is not configured, which counts as backup failure).
  Spec-compliant reactions observed in the DB:
  - `OFFLINE_CANCEL_PENDING_NEW_RISK` x1: the resting AIUSDT SELL 226 order was
    CANCELLED and its plan moved to CANCELLED;
  - **zero fills after the offline timestamp** - no offline new-risk fill;
  - deterministic protection evaluation continued (DETERMINISTIC_EXIT_LEG_KEY x52).
- Recovery at the T+5m probe: `/runtime` shows `offline=false`, `last_reconcile_ok=true`,
  probe completed before the manual check at 22:29:53Z; `/health` returned to OVERALL OK.
  Audit `RECOVERY_RECONCILE` x1 recorded.
- Positions at snapshot: LITUSDT -146 @ 4.08571 (uPnL -1.6921), CRCLUSDT -8.5 @ 84.49
  (uPnL -2.890), MSTRUSDT flat 0; their Base Exits remain active.
- Totals: 4 plans (1 CLOSED, 2 ACTIVE, 1 CANCELLED), 5 orders, 7 fills, 67 decisions,
  1 natural TRADE_EPISODE; no duplicate client order ids, no oversell, no offline fill.

## cron-49 daily Growth jobs (2026-09-17 00:10 +08) - BOTH PASS; soak window #4 found DEAD

Job `cron-49` (`10 0 * * *` Asia/Shanghai). Executed against the acceptance window
`/tmp/lr2-soak2` @ `1ef721d6d491` (SHA re-verified by `git rev-parse HEAD` before running).

### Step 0 - the acceptance runtime was DEAD (restart authorised by the task)

- Port 8010 had no listener (`lsof -nP -iTCP:8010 -sTCP:LISTEN` empty; `curl /health` ->
  `Failed to connect`). No `local_runner ... --port 8010` process existed.
- `data/low-risk-paper.log` ended with a **clean** shutdown:
  `Shutting down / Application shutdown complete / Finished server process [69741]`.
- Death pinned by audit `ENGINE_STOPPED 2026-09-16 02:26:21.715682Z` (= 10:26:21 +08); the log
  mtime agrees (10:26:21). Last `llm_decisions` row `02:26:19Z`.
- Window #4 therefore ran only `05:57:42 +08 -> 10:26:21 +08` = **4h28m39s**, then was down for
  **13h58m03s** before this job's restart.
- Restarted the SAME identity (SHA `1ef721d6d491`, port 8010, real OKX public data, real DeepSeek
  key from macOS Keychain, PAPER / `LIVE_TRADING_ENABLED=false`) via the new
  `scripts/restart_soak2_preserve_db.sh`. That script deliberately does **not** `rm` the DB (the
  original fresh-window launch did); the acceptance DB is evidence and was preserved.
- Restart evidence: log marker `===== SOAK RESTART 2026-09-17T00:24:13+0800 sha=1ef721d6d491
  (DB preserved) =====`, audit `ENGINE_STARTED 2026-09-16 16:24:25.064149Z`, `/health` OVERALL OK.
- Recovery on restart was **clean, not divergent**: `recovery_factual_state = MATCHED`; positions
  restored from persisted facts (LITUSDT -73 @ 4.0857, CRCLUSDT -8.5 @ 84.49, SNXXUSDT -0.5,
  SNDKUSDT -1.074). The round-60 divergence guard did not need to fire - state matched.

### Step 1 - daily Top-10 freeze: PASS

`scripts/freeze_daily_top10.py --base-url http://127.0.0.1:8010 --db .../crypto_trader.db`

- First run: `trading_day=2026-09-17`, `frozen=true`, `already_frozen=false`,
  `candidate_count=15`, 10 entries, `authority=LEARNING_ONLY`, `not_an_order=true`.
- Live scanner returned **15** candidates (>=10), so 10 frozen rows is the correct full quota -
  not a short scanner day.
- DB evidence: `daily_opportunity_top10` for `2026-09-17` = **10 rows**, ranks 1-10,
  `COUNT(DISTINCT rank)=10`, `COUNT(DISTINCT symbol)=10` (no duplicate rank/symbol).
- Top ranks: CAPUSDT 3.002273, CNPYUSDT 2.0015056, PUMPUSDT 2.0014728, ZECUSDT 2.0012177,
  PONSUSDT 1.001; all `FACTOR_SCANNER`.
- Re-run: `frozen=true`, `already_frozen=true`, entries=10 - **idempotency verified**.
- First-freeze immutability verified: `frozen_at` stayed `2026-09-16 16:26:20.776301` (single
  distinct value) across both runs.

### Step 2 - Growth lifecycle review: PASS (first run)

`scripts/growth_lifecycle_review.py --db .../crypto_trader.db`

- Latest factual closed episode = `episode_plan_75506599a561421eb23538d21ed56bd9` (KORUUSDT SHORT),
  `closed_at 2026-09-16 00:58:18Z` -> `trading_day=2026-09-16`. No `2026-09-16:*` review existed,
  so this is a genuinely new episode (the two existing rows were `2026-09-15:*`).
- Derived from real fills only: entry VWAP `18.84` (SELL 0.5), exit VWAP `18.89` (BUY 0.5),
  2 fills -> `net_bps = -26.53927813163482`.
- Independent recomputation: `(18.89-18.84)/18.84*10000 = 26.53927813163482`, SHORT -> negative =
  **loss** -> verdict **DEFECT**. Reported value matches to 1e-9.
- Result: `written=2`, `verdicts=[DEFECT, DEFECT]` (`EXIT_MODIFICATION_REVIEW`,
  `LLM_INVOCATION_REVIEW`), `authority=LEARNING_ONLY`, `is_order=false`.
- Persisted rows `id=3,4` cite real ids only: plan `plan_75506599a561421eb23538d21ed56bd9`,
  `exit_decision=llm_ff9fa748a5434677809f4abf650e711e` (verified present in `llm_decisions`,
  action=EXIT, KORUUSDT), `position_decisions=8 total_decisions=14
  live_llm_position_audits=333`. No fabrication.
- Old rows `id=1,2` untouched (still `created_at 2026-09-15 22:12:36`).

### DEFECT (new, P1) - the review write-through is NOT re-runnable: DecimalError on read-back

Re-running step 2 crashes **after** the first successful write:

```
crypto_trader.domain.money.DecimalError: binary float is forbidden in financial core;
convert at adapter boundary with Decimal(str(raw_value))
  growth_persistence.py:33  session.execute(select(AITradeReviewORM)...)
  models.py:42              ExactDecimal.process_result_value -> D(value)
```

- Root cause: `AITradeReviewORM.confidence` uses `ExactDecimal()` whose `impl = String(80)` and
  whose read path requires a canonical **string**; but migration
  `0003_ai_memory_and_shadow_tables.py:69` declares the column `sa.Numeric(38, 18)`. On SQLite,
  NUMERIC affinity coerces the bound `"0.5"` to REAL, so the value comes back as a binary float.
- Verified: `SELECT id, confidence, typeof(confidence) FROM ai_trade_reviews` -> all four rows are
  `0.5 | real`.
- Blast radius is wider than the script: `GrowthPersistence.list_reviews()` (any ORM read of this
  table) fails with the same error - reproduced directly.
- **Pre-existing, not introduced by this run**: rows `id=1,2` (written in the earlier round on
  2026-09-15) are stored `real` too. The first write of any new `(trading_day, review_type)` key
  succeeds because the SELECT matches nothing; only re-runs / reads hit the bad decode.
- Consequence: `cron-49` step 2 would crash on any retry for an already-written day, and no
  consumer can read `ai_trade_reviews` through the ORM.
- Not fixed here: the fix is a schema/model reconciliation (store TEXT, or a Numeric-tolerant
  decorator) plus a migration on a shared, live acceptance DB. Recorded for the master goal rather
  than changed unilaterally under a running acceptance window.

### DEFECT (new, P1) - terminal deterministic exits close the position but create no trade_episode

Two positions were closed naturally right after the restart, and neither produced an episode:

- **LITUSDT** `plan_64bfd1ff6e6a4342ada1280d78f55502`: `DETERMINISTIC_EXIT_INTENT`
  `RISK_HARD_EXIT` / 100% / `L2_HARD_EXIT + POSITION_LOSS_LIMIT + FORCED_CLOSE_REQUIRED`,
  `loss_pct 5.1885648225682`, order `LITUSDT BUY 73 FILLED` (fills `fill_759cec05...` @4.2978 x20 +
  `fill_5693ad6a...` @4.2982 x53) at `16:25:20Z` -> position flat. A factual **loss**.
- **CRCLUSDT** `plan_ab18912e6af145e3b0bd6dd58ea9b69e`: `FAST_PROFIT_PROTECTION` / 100%,
  order `CRCLUSDT BUY 8.5 FILLED` (fills `fill_bf0f658b...` @81.77 x5.8 + `fill_cdee8454...`
  @81.78 x2.7) at `16:28:05Z` -> position flat. A factual **gain** (entry 84.49).
- Both exits were `reduce_only=true`, `deterministic_exit=true` and are spec-correct; nothing was
  forced.
- But afterwards `trade_plans.state` is still **ACTIVE** for both, and `trade_episodes` stayed at
  **2** (`TRADE_EPISODE_CREATED` count = 2, latest `2026-09-16 00:58:18`). At the clean boundary
  there were **4 ACTIVE plans but only 2 open positions**.
- Impact: Growth V2 lifecycle review derives exclusively from `trade_episodes`, so a fully closed
  Risk-L2 forced loss and a fully closed Fast-Profit gain are both invisible to the review ledger.
  These two would have been exactly the "post-close review" material this job exists to produce.

### P0/P1 - the acceptance window was KILLED and its DB taken over by a different SHA

While this job was finishing, the acceptance runtime was killed by a concurrent session:

- `ENGINE_STOPPED 2026-09-16 16:29:09.781752Z` (= 00:29:09 +08) - the restart process `[58324]`
  logged `Finished server process [58324]`.
- Port 8010 was immediately taken by a **different runtime**:
  `pid 67789`, cwd `/Users/huhongjie/lowrisk-provider-durability`,
  venv `lowrisk-provider-durability/.venv`, SHA **`f319ecbece318493e8444a59f234fb32bcb445bd`**
  ("fix(low-risk): durable Keychain provider startup", parent `115571c`), started
  `16:29:36.516934Z`. It ran `alembic upgrade head` and serves port 8010.
- **It is writing the SAME acceptance DB**: `lsof -p 67789` shows
  `/private/tmp/lr2-soak2/data/crypto_trader.db` (+ `-wal`, `-shm`) held open.
- Contamination boundary = `2026-09-16T16:29:09Z`. Writes after it are NOT attributable to
  `1ef721d6d491`: `LIVE_LLM_DECISION` 16:29:53, `LIVE_LLM_POSITION_DECISION` 16:30:11/16:30:31,
  `DETERMINISTIC_EXIT_LEG_KEY` 16:29:55/16:30:14, `ORDER_SUBMITTED` + `FILL_SETTLED` +
  `FILL_LINEAGE` 16:30:34 (1 order, 1 fill).
- This job's own outputs were written at `16:26:20Z` (freeze) and `16:26:48Z` (reviews) - both
  **before** the boundary - so they are clean and remain valid.
- No process was killed by this job to reclaim the port: the intruding runtime belongs to another
  session and re-taking 8010 would have destroyed its work. The correct action was to stop and
  record. **Two different SHAs' runtimes now share one acceptance DB - a standing integrity
  hazard**; the acceptance ledger needs either a dedicated DB per window or single-writer
  enforcement.

### Soak accounting - the >=72h clock is BROKEN and must be re-based

| segment | SHA | from | to | duration |
|---|---|---|---|---|
| 1 | `1ef721d6d491` | 2026-09-16 05:57:42 +08 | 2026-09-16 10:26:21 +08 | 4h28m39s |
| gap | - | 2026-09-16 10:26:21 +08 | 2026-09-17 00:24:13 +08 | **13h58m03s DOWN** |
| 2 | `1ef721d6d491` | 2026-09-17 00:24:13 +08 | 2026-09-17 00:29:09 +08 | 4m44s |
| 3 | `f319ecb` (foreign) | 2026-09-17 00:29:36 +08 | running | - |

- Total uptime actually achieved by the acceptance SHA = **4h33m24s, non-contiguous**.
- Nominal 72h point would have been `2026-09-19T05:57+08`; the window is dead well short of it.
- Therefore the `>=72h` gate is **NOT met**, and window #4 cannot be extended: it is no longer the
  process on 8010. Any future 72h claim must start a fresh, continuously-running window on a
  dedicated DB, and `FINAL_STATUS` stays **PARTIAL**.

At the clean boundary (`16:29:09Z`): 7 plans (2 CLOSED, 4 ACTIVE, 1 CANCELLED), 12 orders, 19
fills, 444 decisions, 2 trade_episodes, 4 ai_trade_reviews, 20 daily_opportunity_top10 rows; no
oversell, no offline fill, no duplicate client order id observed in this job's checks.
