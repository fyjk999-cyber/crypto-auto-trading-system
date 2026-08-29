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

## ARCHITECTURE INVARIANT (2026-08-29, permanent, above all optimization goals)

AI-FIRST / QUANT-AS-EVIDENCE is a permanent architecture invariant.

No quantitative score, ranking, technical indicator, strategy-fit metric,
confidence threshold, regime classifier, or opportunity score may acquire
trade-decision authority.

Only the Chief Trader AI may choose LONG / SHORT / NO_TRADE / WAIT.
RiskEngine and ExecutionAuthority may block execution only for safety,
validity, account, market-data, or execution constraints.

Fixed authority structure:
Quant / Factors / Technical Indicators / Strategy Evidence / Memory /
Research = EVIDENCE ONLY. Market Observer = ATTENTION / CONTEXT ONLY.
Chief Trader AI = TRADING DECISION AUTHORITY.
RiskEngine = SAFETY AUTHORITY. ExecutionAuthority = EXECUTION SAFETY
AUTHORITY.

Explicitly forbidden forever (ARCHITECTURE REGRESSION if reintroduced):
composite/total opportunity score gates, Top-K execution eligibility,
strategy-fit veto, confidence veto, regime veto, forced/fallback
LONG/SHORT, NO_TRADE→LONG rewrites, WAIT→LONG rewrites, trade quotas or
mandatory trade frequency, prompt coercion ("you must choose LONG or
SHORT"), removing NO_TRADE/WAIT from the action space, and exploration
modes that open positions without an AI decision.

NO_TRADE and WAIT are first-class decisions. Low fill rate is NEVER a
reason to violate this invariant (priority: PAPER safety > AI-FIRST
integrity > Risk/Execution safety > data integrity > Long Goal completion
> trading frequency > fill count). Any new score/threshold/ranking/filter/
scanner in the live path must pass the Authority Review (Q1–Q4) first.

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
