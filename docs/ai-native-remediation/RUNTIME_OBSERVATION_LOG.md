# Runtime Observation Log (fullmarket PAPER)

Last updated: 2026-09-10T00:10Z
Running SHA: 4719d42e4725fff730c3a85c7a74ff1037ff4926
URL: http://127.0.0.1:8001

Status: RUNNING / lease held / single_writer true / kill off / health OK

Lifecycle counts:
- llm_decisions: 3038
- trade_plans: 7
- orders: 0
- fills: 0
- trade_episodes: 0

Natural directional decisions observed:
- multiple SHORT TradePlans invalidated due MARKET_DATA_STALE before refresh fix
- after refresh fix, no new directional decisions yet

Pending: natural order -> fill -> ACTIVE position -> exit -> CLOSED -> episode

Additional fixes during observation:
- market re-fetch before Risk and again immediately before ExecutionAuthority
- DeepSeek decision timeout widened from 30s to 45s to reduce LLM_TIMEOUT fail-closed
