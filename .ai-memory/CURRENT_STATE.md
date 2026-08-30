# CURRENT_STATE

- Updated: 2026-08-30T03:00Z (P2-1 Phase 3 LIVE): dynamic all-market observer
  live on the running runtime — /runtime.market_observer: available=True,
  source=WS (bounded OKX public WS candidate stream), Layer-1 breadth 1383
  SPOT + 458 SWAP instruments LIVE (one batch REST scan per class, 60s
  throttle), 5 factual candidates (held/core pinned + top 24h notional
  volume; no score, no gate), dynamic rotation = core symbols first +
  bounded candidates (<=40 total). Engine tick polls the observer; multi
  adapter injects advisory evidence into decision context. STARTUP LESSON
  recorded: OKXPublicDataClient requires OKXAdapter; the swallowed
  construction exception made the observer silently absent for two boots —
  now logger.exception + audit MARKET_OBSERVER_START_FAILED (failures never
  silent). Runtime PID rotates; health OK, lease held, recon clean.
- Updated: 2026-08-30T02:40Z (P2-1 Phase 2 LIVE): runtime hot-reloadable
  bounded policy layer deployed and validated on the live runtime (same
  process, zero restarts after activation): /policy/runtime serves v1
  baseline; governance CLI applied v2 (240->300s cooldown) and the RUNNING
  engine hot-applied it (audit POLICY_HOT_APPLIED v2@02:34:42Z), rolled back
  to v3 (=v1 params, pickup v3@02:35:10Z); kill_switch attempt rejected
  fail-closed at the CLI allowlist AND would be rejected again in
  apply_update (§22 double fence). Active policy back at 240s baseline.
  Engine tick safe-checkpoint + 5s throttle; DecisionEvidence carries
  policy_version. Tests 12/12; suite 816 passed / 2 pre-existing network.
- Updated: 2026-08-30T02:20Z (P2-1 Phase 1 COMPLETE: code + tests + CONTROLLED
  RESTART done). New runtime PID 68587 (old 48151/48144 gracefully SIGTERMed
  02:03Z, lease expired naturally 0 rows, no manual lease mutation). Episode
  canonicalization: AI_EXIT_INTENT evidence backfill (ord_faa443) + idempotent
  rebuild + 2 stale pre-P0 rows deleted (audited STALE_EPISODE_CLEANUP) -> 93
  episodes, 0 leverage=0, 0 UNKNOWN. Restart found + cleared a LIVE
  reconciliation halt (DOGE local=0.001 vs exchange=-0.001 divergence from
  recon-halt era; ledger-first hydration resolved; recon ALERT->OK). LIVE
  VALIDATION within 10s of start: bridge correctly TIME_STOP-closed the 4
  aged positions the halt had been blocking (BNB 4.4h / DOGE 4.7h / LINK 4.3h
  / SUI 4.1h) as reduce-only at real prices, episodes TIME_STOP-attributed,
  ZERO re-entries (reversal fence live), no churn. /runtime now exposes
  position_lifecycle (new-code marker). Phase 1 acceptance (§18):
  TRX_CHURN_ROOT_CAUSE=IDENTIFIED, STALE_SIGNAL_GUARD=PASS,
  REVERSAL_LIFECYCLE=PASS, POSITION_STATE_FENCE=PASS,
  EXIT_REASON_ATTRIBUTION=PASS, NO_CROSS_SYMBOL_BLOCKING=PASS.
  NEXT: Phase 2 RuntimePolicy hot-reload layer. Calibration stays OBSERVE ONLY.
- Updated: 2026-08-30T01:55Z (P2-1 Phase 1 CODE COMPLETE + TESTED, pending
  controlled restart): TRX churn ROOT CAUSE IDENTIFIED + FIXED in code —
  stale `_first_seen_open` epoch inheritance (60s grace) caused spurious
  instant TIME_STOP on a 4.5s-old re-entry; NOT cooldown insufficiency. New
  PositionLifecycleTracker + provider-authoritative bridge age + engine
  STALE_POSITION_STATE guard + REVERSAL_COOLDOWN_ACTIVE fence + SPOT fill
  lineage enrichment (exit_reason). tests/integration/test_trx_churn_lifecycle.py
  12/12 PASS (§16 TEST1-9 + §17 attribution); full suite 804 passed / 2
  pre-existing live-OKX failures (verified unrelated via clean-HEAD A/B).
  Entry cooldown UNCHANGED (240) — no churn masking. Runtime PID 48151 still
  on OLD code until supervisor-controlled restart; PAPER ACTIVE throughout.
  NEXT: controlled restart to apply Phase 1 → live verification → Phase 2
  (RuntimePolicy hot-reload layer). Calibration stays OBSERVE ONLY per §72.
- Updated: 2026-08-30T01:00:00+00:00 (cron-7: window 16 TRX 45s-flip churn -> CONTRACT re-staged 300; UNKNOWN exit_reason flagged; zero restarts)
- Updated: 2026-08-30T00:30:00+00:00 (cron-7: window 15 clean, episodes 90, steady state, zero restarts)
- Updated: 2026-08-30T00:00:00+00:00 (cron-7: window 14 clean, episodes 87, steady state, zero restarts)
- Updated: 2026-08-29T23:30:00+00:00 (cron-7: window 13 clean, 4h lifecycle verified, episodes 85, zero restarts)
- Updated: 2026-08-29T23:00:00+00:00 (cron-7: window 12 clean, rollback validated, episodes 81, zero restarts)
- Updated: 2026-08-29T22:30:00+00:00 (cron-7: window 11 clean, staged-CONTRACT rolled back per sec.64, episodes 79, zero restarts)
- Updated: 2026-08-29T22:00:00+00:00 (cron-7: window 10 churn cleared, RPNL improved -0.2611, episodes 78, staged-300 rollback decision due; zero restarts)
- Updated: 2026-08-29T21:30:00+00:00 (cron-7: window 9 first CONTRACT - cooldown 240->300 staged in .env, episodes 74, zero restarts)
- Updated: 2026-08-29T21:00:00+00:00 (cron-7: window 8 - episodes 69, flip-pattern watch active, Phase G HOLD; zero restarts)
- Updated: 2026-08-29T20:30:00+00:00 (cron-7: window 7 - 5 real fills, episodes 65, Phase G HOLD; zero restarts)
- Updated: 2026-08-29T20:00:00+00:00 (cron-7: window 6 active - 7 fills/6 symbols incl BTC_PERP 5-min cycle, episodes 63, Phase G HOLD; zero restarts)
- Updated: 2026-08-29T19:30:00+00:00 (cron-7: window 5 best diversity - 7 fills/7 symbols, episodes 58, Phase G HOLD; zero restarts)
- Updated: 2026-08-29T19:00:00+00:00 (cron-7: window 4 - ADA round-trip + ONDO perp entry, episodes 55, Phase G HOLD; zero restarts)
- Updated: 2026-08-29T18:30:00+00:00 (cron-7: window 3 quiet - 1 real fill, episodes 55, Phase G HOLD; zero restarts)
- Updated: 2026-08-29T18:00:00+00:00 (cron-7: window 2 green - 5 real fills/5 symbols, episodes 54, Phase G HOLD; zero restarts)
- Updated: 2026-08-29T17:30:00+00:00 (cron-7 deep checkpoint: all green - funnel 145 decisions/7 fills, episodes 53, dups 0, Phase G baseline HOLD; registry 2029 instruments; next Phase C/D)
- Updated: 2026-08-29T17:30:00+00:00 (LONG GOAL Phase A+B complete: capability
  matrix from live OKX audit, dynamic instrument registry live with 2029
  instruments, resolver + batch endpoints, tests 7/7, commit 6b21658 pushed;
  Phase G baseline HOLD logged; runtime PID 48151 stable, PAPER, zero
  restarts; NEXT = Phase C/D: websocket expansion + Market Observer scaling
  onto the dynamic universe)
- Updated: 2026-08-29T17:35:00+00:00 (P0 corrections committed 28c5d1a and
  pushed to origin/main; episodes re-derived 52 clean rows; NOTE: the RUNNING
  runtime PID 48151 still executes pre-correction code until the
  Supervisor-authorized restart - any episodes inserted before that restart
  bind leverage=0 and MUST be re-derived (delete + record_all_cycles_sync) as
  part of the restart procedure; fail-closed routes activate on restart)
- Updated: 2026-08-29T17:20:00+00:00 (P0 corrections implemented + committed for Supervisor review: fail-closed manual routes, real-mark perp read model, symbol-scoped cooldown P1, episode quarantine/leverage/migration corrections, canonical episodes rebuilt 50; runtime PID 48151 still stable since 15:11Z, zero restarts; frontend CONNECTED)
- Updated: 2026-08-29T16:30:00+00:00 (P2 BACKEND AVAILABILITY: canonical supervisor .ops/backend_supervisor.sh active, blind lease DELETE removed, cron-6 monitor-only, runtime PID 48151 stable since 15:11Z with zero restarts, frontend 5173 relaunched and CONNECTED, WS 101 OK, recon PASS, episodes 47)
- Updated: 2026-08-29T15:31:00+00:00 (cron-5 deep: 16 open positions, FUTURES_RPNL cum -0.503194, episodes 46 all TIME_STOP, zero errors) (checkpoint: 15 fills/13 LLM/44 episodes since 13:35Z; backend ALIVE via cron-4 revive; PAPER confirmed; TRADE_EPISODE_PIPELINE operational) (P2 TRADE EPISODE PIPELINE COMPLETE + runtime
  backend killed externally 3rd time; relaunched via direct
  `uv run python -m crypto_trader.runtime.local_runner` nohup, health OK 14:23Z)
- **TRADE_EPISODE_PIPELINE = OPERATIONAL** (P2 interrupt 3 repair):
  - ROOT CAUSE of ai_trade_episodes=0: `LLMMemoryStore.save_episode` was NEVER
    called by any runtime path; trade_memory_records are per-fill entry
    captures, not completed trades.
  - NEW `src/crypto_trader/governance/trade_episodes.py`: canonical fills x orders
    replay -> flat-to-flat trade cycles -> AITradeEpisode rows. Deterministic,
    idempotent (episode_id = eps-{sha1(symbol|market|entry_fills|exit_fills)}),
    quarantined fills (EVIDENCE_QUARANTINE) excluded, weighted avg entry/exit,
    fees = SUM(fill.fee) (no double count), perp gross from FUTURES_REALIZED_PNL
    ledger metadata (canonical), spot gross = deterministic rebuild,
    net = gross - fees, result WIN/LOSS/BREAKEVEN, exit_reason classification
    (payload exit_reason -> AI_EXIT_INTENT audit -> legacy ai_brain+4h -> TIME_STOP;
    else UNKNOWN; TIME_STOP NEVER labelled AI_EXIT).
  - SCHEMA: ai_trade_episodes + market_type/direction/exit_reason/gross_pnl/fees/
    net_pnl/lineage_json (idempotent ALTER TABLE + ORM mapping).
  - WIRING: engine `_settle_fill` spot flat check + perp reduce-only fill ->
    `_record_trade_episode` (exception-safe, never blocks trading); bridge
    `_submit_exit` now writes metadata {exit_reason} (TIME_STOP/RISK_EXIT/AI_EXIT)
    on the exit SignalIntent; engine perp fill payload passes exit_reason through.
  - PROOF (live DB): 34 backfilled + 3 hook-created = 37 episodes, incl.
    LINKUSDT 07:25->11:25 cycle exit_reason=TIME_STOP holding 14405s (NOT
    AI_EXIT), BTCUSDT_PERP 2 cycles (24210s/14401s, net -0.611312/-0.124806
    from ledger), ENAUSDT_PERP natural 14:17Z 4h exit carried
    exit_reason=TIME_STOP through bridge->engine->fill payload->episode.
  - Daily Review input: LLMMemoryStore.load_episodes reads completed episodes
    (tested); scheduler continues reading trade_memory entries + episodes now
    available as outcome unit.
- Runtime backend killed externally again (3rd time, graceful SIGTERM, ~14:15Z);
  launchd watchdog unusable (macOS TCC blocks ~/Documents). Recovery: direct
  nohup `uv run alembic upgrade head && uv run python -m crypto_trader.runtime.local_runner`
  (bypasses start-local-system.sh trap). Health 200, lease held, 19 open
  positions (10 spot + 9 perp), PAPER_EXPLORATION_MODE=true.
- Updated: 2026-08-29T08:30:00+00:00 (checkpoint cron-2: continuous cycling - 3 exits + 4 AI re-entries since 08:00; 12 positions; 16 LLM calls; 0 errors; health OK)
- **PHASE 2  OVERNIGHT LONG-RUN PAPER OBSERVATION MODE**
- FIRST_AI_PAPER_FILL = YES
- PAPER_TRADE_E2E_READY = YES (PHASE 1 milestone; see PAPER_TRADE_E2E_ACCEPTANCE_REPORT.md)
- OVERNIGHT_PAPER_TRADING = ACTIVE
- REVIEW_DATA_READY = CONTINUOUSLY_UPDATING (OVERNIGHT_PAPER_REVIEW.md)
- PROJECT_COMPLETE =  do not stop the runtime until the user's manual review
- Session index: .ai-memory/OVERNIGHT_PAPER_STATE.md (30-min checkpoints)
- Clean E2E proof: run_256d3e15648542ee976cbefa55bb9cd4 / decision
  dec_a6d0a388dbc34ab082fd / LLM llm_d30a4f2b3429456ca423be4bec8ce7f4
  (LIVE, live_analysis, deepseek-chat) / risk APPROVE RISK_PASS / order
  ord_6a07813a44df44b3b471ebedea407b16 / fill
  fill_8396534b10d74e25843509a357d6e0ab @ 77753.05 REAL OKX price
  (BTCUSDT_PERP LONG 0.001, fee 0.038876525) / ledger txn_467ed207928443e98aa35a09.
- NEW_RUNTIME_BASELINE_SHA = ebcff589921d4c03b4c952cb8ffd80bac60a5ab6
- Post-fix autonomous fills: BNBUSDT 0.001 @ 690.40 (02:00:50), DOGEUSDT
  0.0005 @ 0.08525 (02:09:19) - both full chain, real OKX prices, zero holds.
- Fixed after the v1 report: order-id restart collision (f28e2fe, per-process
  namespace), base-asset balance-vs-position reconciliation scope (7f3fa43),
  event-failure traceback logging (d3589dd), architecture guardrail recorded
  (e36d166; EXPLORATION_PROBABILITY=1.0 - AI sees every symbol every cycle).
- Runtime live: PAPER_REAL_MARKET, OKX REAL feeds healthy (age 0s), recon ok,
  overall OK, LLM_PROVIDER_RUNTIME_VALIDATED=YES.
- Anti-pyramiding: symbol-scoped perp gate restored in AI-first path
  (af426a1 + 53d46c4). A stacked 0.002 BTC position exists from the gate-gap
  window; the bridge owns its HOLD/time-stop; not counted as clean evidence.
- Missing (documented, non-blocking): multi-symbol perpetual registry,
  MAE/MFE tracking, funding scheduler, stale-lease takeover UX, 2 live-OKX
  test fixtures. See MISSING_FEATURE_REPORT.md.
- REAL_MONEY_READY = NO. REAL_MONEY_ENABLED = NO. TRADING_MODE = PAPER only.

## Historical (2026-08-28)

- Updated: 2026-08-28T05:52:00+00:00
- EXECUTION LOCK ACTIVE. POST_COMPLETION_MAINTENANCE_MODE = NOT_ACTIVE.
- PRE_COMPLETION_AUDIT_ONLY = YES.
- CHAPTER 10 = BLOCKED_BY_ENVIRONMENT.
- Frozen runtime qualification baseline: 7b746df09ba5a8e2e9e10cd676fa5d14a2535f10
- REAL_MONEY_READY = NO. REAL_MONEY_ENABLED = NO.
- LLM provider runtime: VALIDATED (deepseek-chat, 6/6 routes) for PAPER-only three-brain use.
- PAPER_SMOKE_TEST = PASS. 24H_PAPER_QUALIFICATION_READY = NO (environment only).
- 2026-08-28 (harness LLM takeover): Shared LLM runtime integrated; earlier baseline
  20a4db8... superseded by
  NEW_RUNTIME_QUALIFICATION_BASELINE_SHA = 7b746df09ba5a8e2e9e10cd676fa5d14a2535f10.
  Session commits: efc25b1 (opt-in DoH transport against fake-IP VPN DNS + route
  output schema examples + DecisionId anchoring + 60s entry decision rate limit),
  e5e3711 (honest /risk metrics + frontend NOT_AVAILABLE/空仓 rendering),
  7b746df (DecisionEvidence persistence for every live decision incl. NO_TRADE,
  with llm_invocation_id correlation).
  Smoke evidence: 27 live correlated decisions, 0 orders/fills, LLM failure
  isolation proven live (disable -> 0 invocations -> re-enable -> recovery),
  market-data DNS outage handled fail-closed. See docs/PAPER_SMOKE_TEST_REPORT.md.
  Blocked for Chapter 10: PostgreSQL absent on this machine; local VPN DNS unstable.
  PAPER ONLY: REAL_MONEY_READY=NO, REAL_MONEY_ENABLED=NO, LIVE_TRADING_ENABLED=false.
- 2026-08-28 (trading logic wiring hardening, PAPER only): Live decision philosophy
  changed from all-conditions gating to STRATEGY SELECTION + EVIDENCE WEIGHTING.
  Five canonical strategies now produce regime-adjusted fit-score candidates
  (StrategyEvidenceBuilder); real FactorSnapshot lineage wired into every Live
  decision (snapshot_id + factor_set_version, no more ""); deterministic PAPER
  gates live_min_strategy_fit=0.45 / live_min_trade_confidence=0.55 (Settings,
  documented); exhaustive entry action mapping (WAIT/unknown/ADD/REDUCE/EXIT
  fail closed, never SELL); evidence persistence instrumented (never silent);
  /decision-context read-only API + frontend strategy-fit panel (real values).
  See docs/TRADING_LOGIC_HARDENING.md. Tests: 669 passed. New baseline recorded
  at the hardening commit SHA (git log -1). RiskEngine/ExecutionAuthority/Ledger
  untouched.
- 2026-08-28 (PAPER exploration + CORE_TRADING_DOCTRINE_V1): STAGE_A_EXPLORATION
  active (.env PAPER_EXPLORATION_MODE=true; guarded by Settings validator that
  REFUSES unsafe configs — exploration only in PAPER with no live/real-money).
  PAPER decision gates: exploration_min_fit=0.40,
  exploration_min_confidence=0.45, borderline-band sampling
  exploration_probability=0.30 (fit 0.40-0.50; skips persisted as
  EXPLORATION_SKIPPED counterfactuals), NORMAL band fit>=0.55 & conf>=0.55,
  exploration entries 0.5x size (0.0005 vs 0.001 BTC),
  decision classes NORMAL_ENTRY/EXPLORATION_ENTRY/NO_TRADE recorded in
  evidence + signal metadata, entry_cooldown_seconds=240 (separate from 60s
  LLM cadence), one open position blocks new entries (POSITION_ALREADY_OPEN),
  bridge PAPER time stop 4h (EXPLORATION_TIME_STOP).
  FINAL CONTEXT PATCH: factor/strategy context fails closed for NEW ENTRY —
  missing snapshot (FACTOR_CONTEXT_UNAVAILABLE), missing candidates
  (STRATEGY_EVIDENCE_UNAVAILABLE), or UNKNOWN regime from context failure
  (MARKET_CONTEXT_UNAVAILABLE) all persist NO_TRADE without calling the
  Live LLM; position safety remains alive. Real Memory -> Live: bounded
  read-only LiveMemoryProvider (confirmed lessons <=5, patterns <=5, similar
  episodes <=5, compressed experience <=5) populates ChiefTraderContext
  knowledge/similar_episodes/compressed_experience and every DecisionEvidence
  records memory_refs; memory is soft evidence only. Learning analytics split
  decision_coverage / executed_trade_coverage / completed_trade_coverage;
  valid_completed_samples exclude INVALID_LEARNING_SAMPLE (mandatory lineage
  filter). Live smoke: real factors -> strategy candidates -> memory refs ->
  LLM -> decision -> signal -> RiskEngine (1 RISK_REJECT SPOT_OVERSHORT)
  verified; LLM invoked on eligible decisions only. Tests: 692 passed.
  RiskEngine/ExecutionAuthority/Ledger unchanged.


## 2026-08-29T11:30Z - cron-2 checkpoint: bridge 4h time-stop exit closed LINK cycle on exact anniversary (entry->exit loop verified); all healthy
## 2026-08-29T11:00Z - cron-2 checkpoint: 3 more new-symbol perp fills incl FIRST perp SHORT (WLDUSDT_PERP SELL); bidirectionality proven; all healthy
## 2026-08-29T10:30Z - cron-2 checkpoint: FIRST new-symbol paper-perp fill (ENAUSDT_PERP, exploration size, real price, full lineage); expansion chain proven
## 2026-08-29T10:12Z - cron-2 checkpoint: ADA fill lineage logged (fit 1.0 watch item); all healthy
## 2026-08-29T09:43Z - P2 closure + 30-symbol expansion deployed (bb4fa37)
- P2 CS-20260829-064844-P2-EXIT pass conditions implemented+tested (d26e4e8): result-aware EXIT retry (Risk REJECT / authority HOLD-REJECT / exception / stale in-flight clear suppression; process_signal returns the FINAL authority outcome), snapshot durability telemetry (SNAPSHOT_PERSIST_FAILED audit + health flag + evidence marker factor_snapshot_persist_ok), whole tainted ETH episode quarantined (derived exit fill + memory rows; loader handles SQLite TEXT JSON + PG native JSON). 10 exit-lifecycle tests; suite 746 passed (2 documented live-OKX network failures only).
- INCIDENT root-caused: 09:18-09:26Z kill switch execution-lease-lost - harness deleted the active canonical runtime_leases row while the Runtime ran. Recovery via normal single-writer launcher restart; kill switch never bypassed; acceptance: duplicate fill/order/client_order/decision/trade IDs 0, kill-window fills/orders 0, positions intact, reconciliation 9/9 OK. Invariants in DECISIONS.md. Harness stashes now exclude .ai-memory/CODEX_SUPERVISOR_*.
- EXPANSION (bb4fa37): universe 20 -> 30 (HYPE ZEC ENA WLD ONDO FIL TAO AAVE XLM HBAR - all verified live OKX SPOT+SWAP pre-deploy). Generic bidirectional paper-perpetual registry: one PerpetualPaperEngine, 11 contracts via contract_for(symbol); unregistered perp fails closed; SPOT_OVERSHORT preserved; no new engines/forced trades; AI authority untouched. 8 expansion tests.
- Deployed with corrected restart procedure (all processes stopped -> lease cleared -> single launch). Post-deploy health: all OK, one renewing lease, kill switch clear.


## 2026-08-29T12:15Z - Position read-model repair deployed (c1f31b6)
- HIGH PRIORITY ADDENDUM complete: cross-symbol mark fallback REMOVED (frontend + backend); /positions now returns per-symbol real OKX marks (missing = NOT_AVAILABLE, fail visibly), backend-computed SPOT unrealized PnL, PERPETUAL engine accounting per registered contract (base/quote/leverage/margin/liquidation), NOT_AVAILABLE vs NOT_APPLICABLE semantics, zero-quantity positions filtered. 5 read-model tests + frontend suite 34 passed + tsc clean; suite 752 passed. Deployed with safe restart; live acceptance: ETH mark=2435.345 (ETH book), SOL mark=103.465 (SOL book), perp rows engine-computed, 24 positions shown / 0 zero-qty rows.


## 2026-08-29T13:20Z - Order/Fill/PnL observability repair deployed (fe82ae1)
- /orders read model: real fee_total from canonical fills, fill_count, fill-payload lineage, PnL attribution POSITION_LEVEL (latest entry per symbol+market, same /positions source, perp ROI basis unrealized/initial_margin) vs TRADE_LEVEL (realized from FUTURES_REALIZED_PNL ledger row of exact closing order); order.price semantics preserved (MARKET=null); episode guard prevents current-position PnL overlay on old entries; spot closed realized stays honestly NOT_AVAILABLE.
- Frontend OrdersPage: MARKET orders show market price + real avg_fill_price (user screenshot orders TAO/HYPE/FIL PERP SHORT + UNIUSDT verified live with real prices/fees/floating PnL); fee, PnL (floating/realized label), sign-based coloring, expanded lineage detail; real zero renders 0.00 dollars.
- Tests: 9 backend order-read-model cases + 4 frontend cases; suite 761 passed (2 pre-existing live-OKX network failures); frontend 38 passed + tsc clean.
- Deployed safe restart; integrity: dup IDs 0, orphan fills 0, filled-no-fill 0, recon OK 13:15Z, lease 1.


## 2026-08-29T13:35Z - Checkpoint: backend vanished + safe restart, 22 real fills since 11:30Z, recon OK, PAPER intact
