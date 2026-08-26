# CANONICAL AI RUNTIME AUDIT

- Updated: 2026-08-26T14:59:06.691937+00:00
- Canonical entry path now: ChiefTraderStrategyAdapter -> ChiefTraderEngine ->
  SignalIntent -> RiskEngine -> ExecutionAuthority -> OrderManager.
- MultiStrategyAlpha is shadow/benchmark evidence only; not canonical entry.
- Position path: TradingEngine.tick -> AIPositionRuntimeBridge -> PositionManager
  -> RiskEngine -> ExecutionAuthority.
- Integration gaps fixed: Chief Trader canonical entry; real price/PnL in
  bridge active positions.
