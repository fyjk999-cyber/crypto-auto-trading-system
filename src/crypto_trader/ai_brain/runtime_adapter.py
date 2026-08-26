"""Runtime adapter: maps AI TradingIntent to existing SignalIntent semantics.

This module DOES NOT execute. It only converts decisions into the intent
shape consumed by the existing TradingEngine.process_signal() path.
RiskEngine and ExecutionAuthority remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IntentMapping:
    action: str
    side: str  # BUY | SELL
    quantity: float
    reason: str
    executable: bool
    reduce_only: bool = False


def map_trading_intent(
    *,
    intent_action: str,
    position_side: str,
    position_quantity: float,
    requested_change: float = 0.0,
) -> IntentMapping:
    side = position_side.upper()
    if intent_action in ("HOLD", "NO_TRADE", "NO_ACTION"):
        return IntentMapping(intent_action, "", 0.0, "no order", False)
    if intent_action in ("OPEN_LONG", "OPEN_SHORT"):
        if position_quantity > 0:
            return IntentMapping("NO_TRADE", "", 0.0, "position exists", False)
        return IntentMapping(
            intent_action,
            "BUY" if intent_action == "OPEN_LONG" else "SELL",
            requested_change or 0.0,
            "entry",
            True,
        )
    if intent_action == "ADD":
        if position_quantity <= 0:
            return IntentMapping("NO_TRADE", "", 0.0, "no position to add", False)
        return IntentMapping(
            "ADD",
            "BUY" if side == "LONG" else "SELL",
            min(requested_change, position_quantity),
            "add exposure",
            True,
        )
    if intent_action == "REDUCE":
        if position_quantity <= 0:
            return IntentMapping("NO_TRADE", "", 0.0, "no position to reduce", False)
        quantity = min(requested_change, position_quantity)
        return IntentMapping(
            "REDUCE",
            "SELL" if side == "LONG" else "BUY",
            quantity,
            "reduce exposure",
            True,
            reduce_only=True,
        )
    if intent_action == "EXIT":
        if position_quantity <= 0:
            return IntentMapping("NO_ACTION", "", 0.0, "already closed", False)
        return IntentMapping(
            "EXIT",
            "SELL" if side == "LONG" else "BUY",
            position_quantity,
            "close position",
            True,
            reduce_only=True,
        )
    return IntentMapping("NO_TRADE", "", 0.0, "unknown action", False)
