# CHANGELOG

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
