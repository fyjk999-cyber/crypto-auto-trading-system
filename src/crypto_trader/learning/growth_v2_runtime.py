"""Runtime adapter: factual market/factor state → canonical card signatures.

This is wiring support only (I03).  It does not create a new retrieval or
learning engine; it maps the existing runtime ``StrategyContext`` and
opportunity observations into the canonical Trigger/Context inputs.
"""

from __future__ import annotations

from typing import Any

STATUS_MAP = {
    "TRIGGERED": "TRIGGERED",
    "NOT_TRIGGERED": "NOT_TRIGGERED",
    "UNAVAILABLE": "UNKNOWN",
}

_CONTEXT_KEYS = (
    "instrument_class",
    "regime",
    "trend_state",
    "volatility_state",
    "liquidity_state",
    "direction",
    "timeframe",
)


def factor_states_from_observations(observations: list[Any] | None) -> list[dict[str, Any]]:
    """Canonical factor states from opportunity ``FactorObservation`` objects.

    Missing/unknown detector versions are preserved as ``UNKNOWN``; they are
    never invented.  Factor ids are kept exactly as observed (the canonical
    signature normalizes case for ids/states).
    """
    states: list[dict[str, Any]] = []
    for observation in observations or []:
        factor_id = getattr(observation, "factor", None)
        if not factor_id:
            continue
        raw_status = str(getattr(observation, "status", "") or "").upper()
        state = STATUS_MAP.get(raw_status, "UNKNOWN")
        definition_version = getattr(observation, "detector_version", None) or "UNKNOWN"
        states.append(
            {
                "factor_id": str(factor_id),
                "state": state,
                "definition_version": str(definition_version),
                "observed_at": getattr(observation, "observed_at", None) or None,
            }
        )
    return states


def _position_direction(ctx: Any) -> str:
    """Return a known position direction or UNKNOWN; never infer from prices."""
    positions = getattr(ctx, "positions", None) or {}
    sides: set[str] = set()
    for position in positions.values():
        quantity = getattr(position, "quantity", None)
        try:
            if quantity is None or float(quantity) == 0.0:
                continue
        except (TypeError, ValueError):
            continue
        side = getattr(position, "side", None)
        if side in {"LONG", "SHORT"}:
            sides.add(str(side))
    if len(sides) == 1:
        return sides.pop()
    return "UNKNOWN"


def market_state_from_strategy_context(
    ctx: Any,
    *,
    regime: str | None = None,
    candidate_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the canonical context only from known factual fields."""
    instrument = getattr(ctx, "instrument", None)
    candidate_context = candidate_context or {}
    state: dict[str, Any] = {
        "symbol": getattr(ctx, "symbol", None),
        "instrument_class": (
            getattr(instrument, "instrument_type", None)
            if instrument is not None
            else None
        ),
        "regime": regime,
        "trend_state": None,
        "volatility_state": None,
        "liquidity_state": None,
        "direction": _position_direction(ctx),
        "timeframe": None,
    }
    for key in _CONTEXT_KEYS:
        value = candidate_context.get(key)
        if value not in (None, "", "UNKNOWN"):
            state[key] = value
    if not state.get("regime"):
        state["regime"] = candidate_context.get("regime")
    return {key: (value if value not in (None, "") else "UNKNOWN") for key, value in state.items()}


def build_card_tool_context(
    ctx: Any,
    *,
    chief_context: Any,
    candidate: Any | None,
    account_id: str,
    mode: str,
    as_of: Any,
    card_trace_id: str | None = None,
) -> dict[str, Any]:
    observations = list(getattr(candidate, "triggered", None) or []) if candidate else []
    return {
        "strategy_context": ctx,
        "chief_context": chief_context,
        "as_of": as_of,
        "account_id": account_id,
        "mode": mode,
        "factor_states": factor_states_from_observations(observations),
        "market_state": market_state_from_strategy_context(
            ctx,
            regime=getattr(chief_context, "regime", None),
            candidate_context=getattr(candidate, "context", None) if candidate else None,
        ),
        "card_trace_id": card_trace_id,
    }
