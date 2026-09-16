# HEDGE OPERATIONAL PAPER OBSERVATION RUN

- Branch: codex/low-risk-hedge-position-leg-final-closure
- Engineering SHA at launch: ebd200227ef33ec1065e1a8cfc50bcd1302d5384
- Run dir: /Users/huhongjie/Documents/ChatGPT/crypto-hedge-acceptance-run
- DB: data/crypto_trader.db (alembic 0033_position_leg_allocation, initially empty)
- Endpoint: http://127.0.0.1:8020
- Mode: PAPER / PAPER_REAL_MARKET, LIVE_TRADING_ENABLED=false
- LEG_EXECUTION_ENABLED=true (explicit operational switch; default remains false)
- Real OKX public market data and real DeepSeek Core LLM are allowed; orders stay PAPER.
- Runtime: fully detached process (`start_new_session=True`), pid in run dir/runner.pid.
- Heartbeat/lineage collector: detached 6-hour loop, pid in run dir/heartbeat.pid.
  - Raw measured evidence: run dir/operational_evidence.log
  - Natural two-leg capture (when it occurs): run dir/natural_hedge_seen.json
- Platform agent cron was unavailable in this environment; the detached heartbeat plus
  session rounds provide the factual accumulation path. The heartbeat never trades,
  never restarts LIVE, and never writes to the git worktree.
- Verified start: /ready=true, mode=PAPER, live=false, runtime state=RUNNING, lease held,
  /health OVERALL OK; heartbeat recorded its first factual line at 2026-09-16T12:36Z.

No natural same-symbol two-leg hedge has been observed yet.
HEDGE_OPERATIONAL_EVIDENCE = AUTONOMOUSLY_ACCUMULATING

## Observed operational limitation (factual, 2026-09-16T12:39Z)
- The PAPER runtime is alive and safe (PAPER, live=false, lease held) but is in LLM_OFFLINE_MODE:
  real DeepSeek decisions returned LLM_TIMEOUT then INVALID_JSON, so new risk is correctly blocked.
- With no open positions, no LLM call is attempted during offline mode, so the router cannot clear
  its own offline flag without an external probe. This belongs to the broader Core-LLM runtime
  contract, not to the hedge/position-leg subsystem; no hedge code or gate was changed to bypass it.
- No natural hedge can occur until Core LLM decisions parse successfully again; this is recorded as P1.
