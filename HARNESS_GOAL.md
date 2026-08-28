# HARNESS GOAL

## CORE_TRADING_DOCTRINE_V1 (permanent)

因子负责描述市场，策略负责解释机会，LLM 负责选择当前最合适的交易逻辑，RiskEngine 决定能不能执行。

FACTORS DESCRIBE THE MARKET.
STRATEGIES INTERPRET OPPORTUNITIES.
THE LLM SELECTS THE MOST APPROPRIATE TRADING LOGIC.
THE RISK ENGINE DECIDES WHETHER IT MAY BE EXECUTED.

Layers stay separate forever: factors never execute, strategies never execute, the
LLM only PROPOSES, RiskEngine/ExecutionAuthority always decide. Regression tests:
tests/runtime/test_chief_trader_entry.py (doctrine A/D/E/F + exploration contract).

## Current capability

Canonical three-brain autonomous trading system.
- Live Trading Brain: COMPLETE
- Daily Learning Brain: COMPLETE + DURABLE
- Evolution Brain: Research/Hypothesis/SelfMod/Candidate/Validation/SafePromotion COMPLETE
- Runtime qualification: PARTIAL (Postgres engine loop + 24h soak pending staging)
- Learning stage: STAGE_A_EXPLORATION (PAPER_EXPLORATION_MODE, PAPER only)
- REAL_MONEY_READY: NO

## Phase 8D-1.5 LLM provider runtime

- Shared LLM gateway, provider routing, encrypted secret storage, API and frontend configuration: IMPLEMENTED.
- Real provider qualification: NOT_RUN (requires a user-supplied key).
- 24H_SOAK_VALIDATED: NO.
