# C0 Baseline Manifest

Date: 2026-09-10
Worktree: /Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-fullmarket
Branch: codex/full-market-factor-layer
Remote: https://github.com/fyjk999-cyber/crypto-auto-trading-system.git
HEAD at C0: c6d94cdbbcc99babca4fc0001bd044f0bd178f36

## Worktree / dirty classification

```text
M data/paper-runtime.log   -> runtime log, never commit
?? .ops/                   -> local evidence/runtime scratch, never commit
```

## Retained fixes and evidence

| Area | Production caller | Regression | Commit |
|---|---|---|---|
| cancel lease/fence | engine._cancel_unsettled_entry_order | lifecycle/cancel tests | b66224b |
| factual instrument registry | PaperRealMarketAdapter.get_exchange_info / runtime_strategy | simulator/lifecycle tests | f4c92a6 |
| no synthetic depth fallback | PaperRealMarketAdapter.get_orderbook/refresh/submit | unit/test_simulator.py | 3331b8c |
| EXECUTABLE_SCOPE | API /opportunity/stats | integration/test_api.py | e93249d |
| factual sizing inputs | runtime_strategy sizing path | llm_chief/runtime_strategy tests | f302ceb |
| backtest terminal close | BacktestEngine close paths | governance_unit | dcbfb77 |
| UTC-only review | bootstrap DailyReviewScheduler | lifecycle/scheduler tests | 9d8003d |
| full-day pagination | TradeEpisodeStore.load_all_closed_on | lifecycle/scheduler tests | 172ba13 |
| restart-safe exchange_order_id | SimulatedExchangeAdapter._local_order_for | unit/test_simulator.py | c6db0b1 |
| MTM/adjusted drawdown | engine + PortfolioService.record_equity_drawdown | ledger/risk tests | f03b3b8 |
| transaction-level cumulative cash flow | PortfolioService.record_equity_drawdown | integration/test_ledger.py | 2405d7e |
| multi-position stale mark refresh | engine.process_signal valuation | lifecycle/runtime health tests | c6d94cd |

## Reproducible test entry

```bash
PYTHONPATH=src /Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-p0p1/.venv/bin/python -m pytest -q
/Users/huhongjie/Documents/ChatGPT/crypto-auto-trading-system-p0p1/.venv/bin/ruff check .
```

Latest self-verification on c6d94cd:

```text
backend: 689 passed
ruff: PASS
```

## Pre-existing / unmerged

```text
No unmerged worktree conflicts observed.
.ops/ and data/paper-runtime.log are intentionally excluded from commits.
```

## C0 status

```text
C0_SELF_VERIFICATION = PASS
NEXT_PACKAGE = C1
```
