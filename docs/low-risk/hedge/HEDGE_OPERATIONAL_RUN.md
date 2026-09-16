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
