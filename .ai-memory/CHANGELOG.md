# CHANGELOG

- 2026-08-30T01:55Z (P2-1 TRX direction-flip churn root-cause repair, directive
  Phase 1): ROOT CAUSE (00:40Z incident, 7s flip) = bridge `_first_seen_open`
  symbol-keyed age cache inherited the DEAD episode's open time when a position
  closed and re-opened inside the 60s forget-grace window → instant spurious
  TIME_STOP on a 4.5s-old position; plus no exit→re-entry fence and SPOT fill
  payload missing exit_reason (→ episode UNKNOWN). FIXES: (1) NEW
  runtime/position_lifecycle.py — canonical PositionLifecycleTracker
  (per-instrument version + completed-exit timestamps; EXIT_UNBLOCKED doctrine).
  (2) ai_position_bridge.py — provider (real per-episode open time) is now
  AUTHORITATIVE and re-validated every evaluation; cache only a fallback.
  (3) engine.py — stale-signal guard: entry intents carrying
  expected_position_version are REJECTED (STALE_POSITION_STATE, audited
  STALE_SIGNAL_REJECT) when position state changed since decision (§11/§12);
  lifecycle OPENED/CLOSED/CHANGED recorded on perp open/close + spot
  settlement; settled SPOT fills enriched with SignalIntent lineage
  (exit_reason/decision_id/signal_id/llm_invocation_id) so episodes attribute
  TIME_STOP/AI_EXIT correctly (§17); runtime_snapshot exposes
  position_lifecycle observability (§74). (4) chief_trader_strategy.py +
  ai_first_chief_trader.py — REVERSAL_COOLDOWN_ACTIVE entry gate after a
  completed exit for the SAME instrument (settings.reversal_cooldown_seconds,
  default 240s, env REVERSAL_COOLDOWN_SECONDS; timing safety, NOT a quant
  gate; exits never gated; other symbols never blocked) +
  expected_position_version captured into entry intents. (5) bootstrap.py
  wiring (one shared tracker into engine + chief trader). NO change to AI
  decision authority, RiskEngine, ExecutionAuthority, sizing, ledger
  semantics. Entry cooldown value unchanged (240).

- 2026-08-29T17:20Z (P0 Corrections per CS-20260829-132209 + linked P1/P2):
  src/crypto_trader/api/app.py: /manual-orders + /paper/perpetual/open|close
  fail-closed (403 always, audited); /paper/perpetual/positions real marks;
  /positions authoritative leverage. chief_trader_strategy.py +
  ai_first_chief_trader.py: symbol-scoped entry cooldown (P1). governance/
  trade_episodes.py: after_json.tainted_fill_ids quarantine + full-episode
  scope + ledger-OPEN leverage + Decimal end-to-end + verify-only ensure_columns.
  migrations/versions/0018_trade_episode_lineage.py (new, applied, head).
  tests/integration/test_p0_corrections.py (7 tests). Canonical ai_trade_episodes
  rebuilt from clean facts (50 rows). No change to Chief Trader AI authority,
  RiskEngine, sizing, entry-exit policy, ledger semantics, episode learning
  semantics (corrections enforce them).

- 2026-08-29T16:30Z (P2 Backend Availability / Single-Writer): NEW
  .ops/backend_supervisor.sh (canonical single-instance supervisor: port-scoped
  liveness, evidence-gated recovery, lease-TTL wait + existing LeaseManager CAS
  takeover instead of blind DELETE, restart-storm guard 3/30min,
  runtime_state.json, no trading-DB access); .ops/backend_watchdog.sh retired
  (had blind lease DELETE); local_runner shutdown forensics (SIGTERM/SIGINT
  context log); DSH cron redefined: cron-6 */5 monitor-only, cron-7 */30 deep
  checkpoint (no restart authority outside supervisor); frontend dev server
  relaunched (5173). No trading-logic changes.

- 2026-08-29T14:45Z (P2 Trade Episode / Learning Pipeline repair): NEW
  governance/trade_episodes.py (canonical cycle replay -> AITradeEpisode,
  deterministic idempotent backfill + runtime hook), engine close hooks
  (spot flat + perp reduce-only), bridge exit metadata exit_reason
  (TIME_STOP/RISK_EXIT/AI_EXIT) + engine payload passthrough, ai_trade_episodes
  schema extension, 15 targeted integration tests, live-DB backfill 37 episodes.
  No trading-architecture changes; exits are the same natural 4h time-stops,
  now durably labelled.

- 2026-08-29: PAPER E2E loop: fixed restart reconciliation halt (ledger
  hydration, 2f1c527), reference-symbol refresh (11a93bf), fake-price match
  clobber (53c4f57), futures-aware reconciliation (1b83f05, c432a06),
  AI-first perp duplicate-entry gate + symbol scoping (af426a1, 53d46c4).
  Clean AI-autonomous perpetual fill @ real OKX price achieved.
- 2026-08-27T14:36:17.029344+00:00: post-completion maintenance audit cycle MC-2026-08-27.
- 2026-08-28: added canonical shared LLM provider runtime integration, encrypted local secrets, route configuration, usage audit, qualification tooling, and frontend controls.
- 2026-08-28: feat: integrate shared llm runtime for three-brain paper trading
  (commit 20a4db8): gateway+providers+secretstore+domain models+API+frontend,
  migrations 0016/0017, harness takeover audit docs, harness repair fixes
  (schema-anchored prompts, route readiness gate, decision interval).

## 8d6f505 - 2026-08-29T07:25:18+00:00 - P1 position lifecycle + P2 snapshot durability
- process_signal refreshes reference book per signal (real-market adapters only)
- bridge time-stop age hydrates from real position open time; grace-based stale cleanup; EXIT in-flight guard
- reduce-only settlement survives None avg entry
- factor snapshots persisted at decision time; EVIDENCE_QUARANTINE enforced for learning
- SQLite WAL + busy_timeout


## bb4fa37 - 20->30 universe + generic paper-perpetual registry (2026-08-29T09:43Z)
- 10 new OKX-verified symbols under a generic registry; 11 paper-perp contracts on one engine; fail-closed unregistered perp; SPOT_OVERSHORT intact; final-outcome process_signal return; snapshot persistence telemetry; full ETH episode quarantine; lease-loss invariants in DECISIONS.md.


## c1f31b6 - Position read-model repair (2026-08-29T12:15Z)
- Per-symbol real marks, backend SPOT PnL, PERPETUAL engine accounting per contract, NOT_AVAILABLE/NOT_APPLICABLE semantics, zero-position filter; cross-symbol fallback removed from frontend and backend.


## fe82ae1 - Order/Fill/PnL observability repair (2026-08-29T13:20Z)
- /orders read model + OrdersPage: real fees/avg fill price/canonical PnL attribution (POSITION_LEVEL vs TRADE_LEVEL), MARKET=market order display, episode guard, NOT_AVAILABLE semantics; 9+4 tests.

- 2026-08-30T02:20Z (P2-1 Phase 1 CONTROLLED RESTART + live validation):
  Old runtime 48151/48144 gracefully SIGTERMed 02:03Z (no orders in flight;
  exits were AUTHORITY_HOLD-blocked, not in-flight), lease expired naturally
  (0 rows; no manual mutation). Episode canonicalization in the window:
  evidence-based AI_EXIT_INTENT backfill for the spurious 7s exit ord_faa443
  (reconstructed, documented) + record_all_cycles_sync + deletion of 2 stale
  pre-P0 rows (STALE_EPISODE_CLEANUP audit) -> 93 episodes, 0 leverage=0,
  0 UNKNOWN exit_reason. New runtime PID 68587 via
  .venv/bin/python -m crypto_trader.runtime.local_runner (supervisor scripts
  were found removed from .ops; DECISIONS (C) manual safe procedure applied).
  RESTART FINDING: reconciliation_halted=TRUE was live since the DOGE
  divergence (local 0.001 vs exchange -0.001) — it blocked ALL orders
  including bridge TIME_STOP exits (AUTHORITY_HOLD loop). Ledger-first
  hydration on start resolved the divergence: recon ALERT -> OK. Within 10s
  of start the bridge correctly closed the 4 halt-blocked aged positions
  (BNB/DOGE/LINK/SUI, all ~4h+, reduce-only, real prices, TIME_STOP
  attributed, ZERO re-entries — reversal fence live). Integrity: dup fills 0,
  dup orders 0, lease 1, PAPER confirmed. /runtime exposes position_lifecycle.
