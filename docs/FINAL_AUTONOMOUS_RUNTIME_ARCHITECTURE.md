# FINAL AUTONOMOUS RUNTIME ARCHITECTURE

Market Data -> TradingEngine Tick/Event -> Portfolio Snapshot ->
No position: Entry Analysis (AI) | Active position: Position Re-evaluation (AI)
-> runtime_adapter -> existing SignalIntent -> Risk -> Execution -> Order ->
Exchange/Paper -> Ledger -> Portfolio -> next tick.

build_system() now creates AIPositionRuntimeBridge and registers
ai_position_callback on TradingRuntimeSupervisor.
