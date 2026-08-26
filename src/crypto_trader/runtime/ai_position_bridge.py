"""AI position re-evaluation bridge.

Calls AITradingBrain for each active position on the existing supervisor loop.
This module NEVER executes orders; it only produces decisions and maps them to
existing SignalIntent-compatible shapes via runtime_adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.ai_brain.decision.decision_engine import AITradingBrain
from crypto_trader.ai_brain.runtime_adapter import map_trading_intent


@dataclass
class AIPositionEvaluation:
    symbol: str
    action: str
    confidence: float
    reason: str
    thesis_status: str
    executable: bool
    side: str
    quantity: float
    reduce_only: bool
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "confidence": self.confidence,
            "reason": self.reason,
            "thesis_status": self.thesis_status,
            "executable": self.executable,
            "side": self.side,
            "quantity": self.quantity,
            "reduce_only": self.reduce_only,
            "timestamp": self.timestamp,
        }


class AIPositionRuntimeBridge:
    def __init__(self, brain: AITradingBrain | None = None, cooldown_seconds: float = 5.0) -> None:
        self.brain = brain or AITradingBrain()
        self.cooldown_seconds = cooldown_seconds
        self.last_evaluation: dict[str, str] = {}
        self.last_decision: dict[str, str] = {}
        self.decision_history: list[dict] = []
        self.thesis_overrides: dict[str, str] = {}
        self.requested_change_overrides: dict[str, float] = {}
        self.hard_risk_overrides: dict[str, bool] = {}

    def evaluate(
        self,
        *,
        symbol: str,
        active_position: dict,
        market_state: str = "UNKNOWN",
        factor_intelligence: dict | None = None,
        now: datetime | None = None,
    ) -> AIPositionEvaluation:
        now = now or datetime.now(UTC)
        if self._on_cooldown(symbol, now):
            return AIPositionEvaluation(
                symbol, "COOLDOWN", 0.0, "cooldown", "", False, "", 0.0, False
            )
        intent = self.brain.analyze(
            symbol=symbol,
            market_state=market_state,
            factor_intelligence=factor_intelligence,
            active_position=active_position,
        )
        side = str(active_position.get("side", "LONG")).upper()
        quantity = float(active_position.get("quantity", 0.0))
        requested_change = float(active_position.get("requested_change", 0.0))
        mapping = map_trading_intent(
            intent_action=intent.action,
            position_side=side,
            position_quantity=quantity,
            requested_change=requested_change,
        )
        evaluation = AIPositionEvaluation(
            symbol=symbol,
            action=intent.action,
            confidence=intent.confidence,
            reason=intent.thesis or "position analysis",
            thesis_status=str(active_position.get("thesis_status", "")),
            executable=mapping.executable,
            side=mapping.side,
            quantity=mapping.quantity,
            reduce_only=mapping.reduce_only,
        )
        self.last_decision[symbol] = evaluation.action
        self.last_evaluation[symbol] = now.isoformat()
        self.decision_history.append(evaluation.to_dict())
        return evaluation

    def _on_cooldown(self, symbol: str, now: datetime) -> bool:
        last = self.last_evaluation.get(symbol)
        if last is None:
            return False
        try:
            last_ts = datetime.fromisoformat(last)
            return (now - last_ts).total_seconds() < self.cooldown_seconds
        except Exception:
            return False

    async def evaluate_active_positions(self, engine, portfolio) -> list[AIPositionEvaluation]:
        positions = await portfolio.get_positions()
        evaluations = []
        for symbol, position in positions.items():
            quantity = float(position.quantity or 0)
            if quantity <= 0:
                continue
            active_position = {
                "quantity": quantity,
                "side": "LONG" if quantity > 0 else "SHORT",
                "entry_price": float(position.avg_entry_price or 0),
                "current_price": float(position.avg_entry_price or 0),
                "unrealized_pnl": 0.0,
                "realized_pnl": float(position.realized_pnl or 0),
                "age_seconds": 0.0,
                "thesis_status": self.thesis_overrides.get(symbol, "THESIS_INTACT"),
                "thesis": "position management",
                "hard_risk_exit": self.hard_risk_overrides.get(symbol, False),
                "requested_change": self.requested_change_overrides.get(symbol, 0.0),
            }
            evaluation = self.evaluate(symbol=symbol, active_position=active_position)
            evaluations.append(evaluation)
            if evaluation.executable and evaluation.action in ("ADD", "REDUCE", "EXIT"):
                await self._apply_to_engine(engine, symbol, evaluation)
        return evaluations

    async def _apply_to_engine(self, engine, symbol: str, evaluation: AIPositionEvaluation) -> None:
        from datetime import UTC, datetime

        from crypto_trader.domain.enums import OrderSide, OrderType
        from crypto_trader.domain.models import SignalIntent

        side = OrderSide.BUY if evaluation.side == "BUY" else OrderSide.SELL
        signal_id = f"ai_{symbol}_{int(datetime.now(UTC).timestamp() * 1000)}"
        signal = SignalIntent(
            signal_id=signal_id,
            strategy_id="ai_brain",
            symbol=symbol,
            side=side,
            quantity=str(evaluation.quantity),
            order_type=OrderType.MARKET,
            reason=evaluation.reason,
        )
        await engine.process_signal(signal)
