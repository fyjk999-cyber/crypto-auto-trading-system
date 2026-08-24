"""Hard gate: stale/unavailable market data blocks NEW risk, never reduce/close."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.domain.enums import OrderSide
from crypto_trader.market_data.state import DataHealth, MarketState


def _is_reduce_or_close(side: OrderSide) -> bool:
    # For this paper gate, SELL is treated as potential reduce/close of LONG;
    # BUY is potential reduce/close of SHORT. The caller passes intent side and
    # the existing position sign when available.
    return False


def can_add_risk(
    market_state: MarketState | None, *, orderbook_max_age: float = 5.0, mark_max_age: float = 10.0
) -> tuple[bool, str]:
    """Return (allowed, reason_code)."""
    if market_state is None:
        return False, "MARKET_STATE_MISSING"
    now = datetime.now(UTC)

    def age(updated_at):
        if updated_at is None:
            return 999.0
        return (now - updated_at).total_seconds()

    if market_state.generation < 1:
        return False, "MARKET_STATE_NO_GENERATION"
    if market_state.health in (DataHealth.UNAVAILABLE, DataHealth.STALE):
        return False, "MARKET_DATA_UNAVAILABLE"
    if market_state.best_bid <= 0 or market_state.best_ask <= 0:
        return False, "ORDERBOOK_UNAVAILABLE"
    if market_state.best_ask < market_state.best_bid:
        return False, "ORDERBOOK_INVALID"
    book_age = age(
        market_state.sources.get("orderbook").updated_at
        if "orderbook" in market_state.sources
        else market_state.updated_at
    )
    if book_age > orderbook_max_age:
        return False, "ORDERBOOK_STALE"
    mark_source = market_state.sources.get("mark_price")
    if mark_source is not None and age(mark_source.updated_at) > mark_max_age:
        return False, "MARK_PRICE_STALE"
    if market_state.mark_price <= 0:
        return False, "MARK_PRICE_UNAVAILABLE"
    return True, "MARKET_DATA_HEALTHY"


def classify_order_action(side: OrderSide, existing_position: Decimal) -> str:
    """Classify an intent as INCREASE or REDUCE/CLOSE relative to position."""
    if side == OrderSide.BUY:
        return "INCREASE_LONG" if existing_position >= 0 else "REDUCE_SHORT"
    return "INCREASE_SHORT" if existing_position <= 0 else "REDUCE_LONG"


def new_risk_blocked_for_action(
    market_state: MarketState | None, side: OrderSide, existing_position: Decimal
) -> tuple[bool, str]:
    action = classify_order_action(side, existing_position)
    if action in ("REDUCE_LONG", "REDUCE_SHORT"):
        return False, "RISK_REDUCING_ALLOWED"
    allowed, reason = can_add_risk(market_state)
    return (not allowed), reason
