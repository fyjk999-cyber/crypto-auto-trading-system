# AI POSITION LIFECYCLE FINAL

- Canonical Position Manager: src/crypto_trader/ai_brain/position_manager/manager.py
- State machine: ai_brain/position_manager/state.py (explicit legal transitions)
- Legacy wrapper: src/crypto_trader/position_manager/engine.py (compatibility only)
- Entry vs active-position routing implemented in AITradingBrain.analyze()
- HOLD: explicit decision, recorded, no order.
- ADD: only when thesis strengthens; still requires Risk.
- REDUCE: partial close; quantity capped to current position; reduce_only.
- EXIT: full close; closes current side; never reverses.
- Exit priority: HARD_RISK_EXIT > THESIS_INVALIDATED > THESIS_WEAKENING > profit/time > HOLD.
- Runtime path: AITradingBrain -> TradingIntent -> runtime_adapter -> existing
  SignalIntent/TradingEngine.process_signal -> Risk -> ExecutionAuthority.
- Partial fills: state stays EXIT_PENDING until Portfolio quantity == 0.
- Restart: portfolio/ledger/orders are authoritative for lifecycle rebuild.
