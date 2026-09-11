# RUNTIME ACCEPTANCE PLAN (Chapter 15 preparation)

Engineering baseline: 57c3ee32f068b528a20f49cfd7da302604eac277
Hardening branch: codex/pre-phase2-hardening-57c3ee3
Candidate SHA: freeze from the review ref after same-SHA gates
Mode: PAPER_REAL_MARKET / LIVE_TRADING_ENABLED=false
Runtime: exactly one execution writer via lease/fencing
Market data: real OKX public only, no synthetic/cross-symbol fallback
DeepSeek: configured live provider; exact model is reported by /ready and /llm/health

Preflight readiness:
- database Alembic version must equal repository head
- PAPER_MODE must be PAPER_REAL_MARKET; unknown values fail closed
- LIVE_TRADING_ENABLED=false
- execution lease held by one writer
- kill switch disabled
- DeepSeek configured + reachable
- factual OKX public BTCUSDT market state HEALTHY
- provider/data source must be OKX_PUBLIC / REAL
- synthetic market data is never accepted by /ready

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
