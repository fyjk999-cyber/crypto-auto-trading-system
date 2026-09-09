# RUNTIME ACCEPTANCE PLAN (Chapter 15 preparation)

Candidate SHA: e037d6c (update when changed)
Branch: codex/full-market-factor-layer
Mode: PAPER_REAL_MARKET / LIVE_TRADING_ENABLED=false
Runtime: exactly one execution writer via lease/fencing
Market data: real OKX public only, no synthetic/cross-symbol fallback
DeepSeek: existing Keychain launcher, model deepseek-v4-pro

Observation:
- 24h continuous healthy runtime
- cross at least 2 lease TTLs
- cross UTC 00:05 daily review boundary
- record RUNNING_SHA, run_id, DB, provider/model, fence generation
- capture natural entry -> plan -> risk -> order -> fill -> position
- capture natural exit -> reduce_only fill -> zero position -> CLOSED -> episode
- if no natural event: PENDING_NO_NATURAL_TRADE

Stop/rollback:
- stop runtime through canonical stop script
- no manual lease/order/DB mutation
- on anomaly, fail closed and preserve logs
