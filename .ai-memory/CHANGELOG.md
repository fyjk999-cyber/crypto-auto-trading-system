# CHANGELOG

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
