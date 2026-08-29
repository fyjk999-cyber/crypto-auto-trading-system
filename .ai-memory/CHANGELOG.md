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
