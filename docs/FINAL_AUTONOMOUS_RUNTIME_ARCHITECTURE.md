# FINAL AUTONOMOUS RUNTIME ARCHITECTURE

Production path:
FastAPI lifespan -> TradingEngine.start() -> TradingEngine._tick_loop() ->
TradingEngine.tick() -> AIPositionRuntimeBridge -> HOLD/ADD/REDUCE/EXIT ->
TradingEngine.process_signal() -> RiskEngine -> ExecutionAuthority -> OrderManager -> Portfolio.

No second scheduler is required. AIPositionRuntimeBridge is attached to
TradingEngine via dependency injection in build_system().
