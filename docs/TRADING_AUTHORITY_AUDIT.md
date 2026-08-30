# TRADING AUTHORITY AUDIT

Generated from source inspection; PAPER only; no runtime restart.

## CURRENT AUTHORITY GRAPH

FLAT (no position):
  Real OKX market data -> Factor/Strategy evidence
  -> ChiefTraderStrategyAdapter/AIFirstChiefTraderStrategyAdapter
  -> Live LLM (ChiefTraderEngine via configured LLMGateway)
  -> LONG / SHORT / NO_TRADE / WAIT
  -> SignalIntent -> RiskEngine -> ExecutionAuthority -> Order/Fill

OPEN position:
  Engine tick -> AIPositionRuntimeBridge -> AITradingBrain
  -> PositionManager.decide() deterministic Python rules:
     THESIS_INVALIDATED=EXIT, THESIS_WEAKENING=REDUCE,
     THESIS_STRENGTHENING=ADD, profit+running=HOLD
  -> HOLD / REDUCE / EXIT / ADD
  -> reduce/exit SignalIntent -> Risk -> Execution -> Fill
  TIME_STOP (4h) is the de-facto primary exit for many PAPER episodes.

## WHO DECIDES (current)
ENTRY:          LIVE_LLM
LONG/SHORT:     LIVE_LLM
NO_TRADE/WAIT:  LIVE_LLM
HOLD:           PYTHON_RULES (PositionManager)
REDUCE:         PYTHON_RULES (PositionManager)
ADD:            PYTHON_RULES (PositionManager)
EXIT:           PYTHON_RULES (PositionManager) + TIME_STOP timer
TIME_STOP:      SYSTEM timer
RISK:           RiskEngine
EXECUTION:      ExecutionAuthority

## TARGET AUTHORITY GRAPH (directive)
FLAT:  unchanged (Live LLM entry authority)
OPEN:  Position Review Context (TradePlan + current position + market evidence
       + memory/tools + risk context)
       -> LiveLLMPositionManager (same configured Live LLM)
       -> HOLD / REDUCE / EXIT (ADD disabled initially)
       -> RiskEngine -> ExecutionAuthority -> Fill
Safety: Kill Switch / RiskEngine / TIME_STOP / reconciliation remain
        hard safety overrides independent of LLM.

## REQUIRED TRANSFORMATIONS
1. TradePlan durable persistence (current TradeThesis is in-memory/dict only).
2. PositionManager rules demoted to safety/mapping/fallback.
3. LiveLLMPositionManager canonical; ShadowPositionManager is the existing
   shadow vehicle and must feed promotion evidence.
4. TIME_STOP becomes max-hold safety fallback; AI_EXIT is primary target.
5. Post-exit lifecycle fence already exists in PositionLifecycleTracker.
