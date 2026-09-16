# HEDGE OPERATIONAL PAPER OBSERVATION RUN

- Branch: codex/low-risk-hedge-position-leg-final-closure
- Launch SHA: ebd200227ef33ec1065e1a8cfc50bcd1302d5384
- Run dir: /Users/huhongjie/Documents/ChatGPT/crypto-hedge-acceptance-run
- DB: data/crypto_trader.db (alembic 0033_position_leg_allocation, initially empty)
- Endpoint: http://127.0.0.1:8020
- Mode: PAPER / PAPER_REAL_MARKET, LIVE_TRADING_ENABLED=false
- LEG_EXECUTION_ENABLED=true (explicit operational switch; default remains false)
- Real OKX public market data and real DeepSeek Core LLM are allowed; orders remain PAPER.
- Process start: 2026-09-16T20:24+08 (pid recorded in run dir/runner.pid)
- Supervisor: durable cron every 6 hours harvests facts; never forces a hedge.

No natural same-symbol two-leg hedge has been observed yet.
HEDGE_OPERATIONAL_EVIDENCE = AUTONOMOUSLY_ACCUMULATING
