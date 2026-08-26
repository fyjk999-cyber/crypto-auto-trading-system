"""Read-only Live Trading Brain factor tools. No mutation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class LiveFactorToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class LiveFactorTools:
    def __init__(self, gateway) -> None:
        self.gateway = gateway

    async def get_factor_snapshot(
        self, symbol: str, timeframe: str, candles: list[dict], market_data: dict | None = None
    ) -> LiveFactorToolResult:
        try:
            snapshot = self.gateway.calculate_snapshot(
                symbol=symbol, timeframe=timeframe, candles=candles, market_data=market_data
            )
            return LiveFactorToolResult(True, snapshot.to_dict(), None)
        except Exception as exc:
            return LiveFactorToolResult(False, {}, f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_active_factor_set_version(self) -> LiveFactorToolResult:
        return LiveFactorToolResult(True, self.gateway.get_active_factor_set().to_dict(), None)

    async def set_factor_weight(self, *args, **kwargs) -> LiveFactorToolResult:
        return LiveFactorToolResult(False, {}, "MUTATION_DENIED_LIVE_RUNTIME")

    async def create_factor(self, *args, **kwargs) -> LiveFactorToolResult:
        return LiveFactorToolResult(False, {}, "MUTATION_DENIED_LIVE_RUNTIME")

    async def modify_factor_formula(self, *args, **kwargs) -> LiveFactorToolResult:
        return LiveFactorToolResult(False, {}, "MUTATION_DENIED_LIVE_RUNTIME")

    async def activate_factor_candidate(self, *args, **kwargs) -> LiveFactorToolResult:
        return LiveFactorToolResult(False, {}, "MUTATION_DENIED_LIVE_RUNTIME")
