# AI POSITION LIFECYCLE AUDIT

A. Canonical Position Manager: ai_brain/position_manager/manager.py (decision)
   plus ai_brain/position_manager/state.py (state machine). The standalone
   src/crypto_trader/position_manager/engine.py becomes a compatibility wrapper.
B. Existing duplicate logic merged into ai_brain canonical; no third system.
C. Portfolio expresses positions through portfolio/ positions and perpetual
   engine state; position quantity is authoritative from Portfolio/Ledger.
D. Perpetual close mechanism: PerpetualPaperEngine.close_position side+quantity.
E. SignalIntent / ManualOrderBody carry side and quantity; new/intent types are
   represented by side + quantity semantics. Exact runtime intent mapping must
   reuse TradingEngine.process_signal() / manual path.
F. Minimal integration point: AI produces TradingIntent; an adapter maps to
   existing SignalIntent and invokes existing runtime path. No AI->Exchange.
