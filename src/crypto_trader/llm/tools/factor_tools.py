"""Factor tools for LLM context. Read-only; never trades."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class FactorToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FactorTools:
    def __init__(self, factor_service=None) -> None:
        self.factor_service = factor_service

    async def get_factor_snapshot(self, symbol: str) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        try:
            snapshot = await self.factor_service.latest_snapshot(symbol)
            if snapshot is None:
                return FactorToolResult(True, {"symbol": symbol, "status": "NO_DATA"}, None)
            return FactorToolResult(True, snapshot, None)
        except Exception as exc:
            return FactorToolResult(False, {}, f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_factor_history(
        self, symbol: str, factor: str, limit: int = 100
    ) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, [], "FACTOR_SERVICE_UNAVAILABLE")
        try:
            rows = await self.factor_service.history(symbol, factor, limit)
            return FactorToolResult(True, rows, None)
        except Exception as exc:
            return FactorToolResult(False, [], f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_market_factor_context(self, symbol: str) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        snapshot_result = await self.get_factor_snapshot(symbol)
        if not snapshot_result.ok:
            return snapshot_result
        data = snapshot_result.data if isinstance(snapshot_result.data, dict) else {}
        market_state = data.get("market_state", data)
        return FactorToolResult(
            True,
            {
                "symbol": symbol,
                "market_state": market_state,
                "summary": _summarize(market_state),
            },
            None,
        )

    async def get_factor_performance(
        self, factor: str, symbol: str, timeframe: str = "15m"
    ) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        try:
            perf = await self.factor_service.latest_performance(factor, symbol)
            return FactorToolResult(
                True,
                perf
                or {
                    "factor_name": factor,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "sample_size": 0,
                },
                None,
            )
        except Exception as exc:
            return FactorToolResult(False, {}, f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_factor_health(self, factor: str, symbol: str) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        perf = await self.get_factor_performance(factor, symbol)
        if not perf.ok or not isinstance(perf.data, dict):
            return FactorToolResult(
                True,
                {
                    "factor_name": factor,
                    "symbol": symbol,
                    "status": "EXPERIMENTAL",
                    "sample_size": 0,
                },
                None,
            )
        data = perf.data
        sample_size = int(data.get("sample_size", 0))
        win_rate = float(data.get("win_rate", 0))
        sharpe = float(data.get("sharpe", 0))
        if sample_size < 30:
            status = "EXPERIMENTAL"
        elif sharpe < 0.2 or win_rate < 0.45:
            status = "DEGRADING"
        elif win_rate < 0.52:
            status = "TESTING"
        else:
            status = "HEALTHY"
        return FactorToolResult(
            True,
            {"factor_name": factor, "symbol": symbol, "status": status, "sample_size": sample_size},
            None,
        )

    async def get_trade_factor_attribution(self, trade_id: str) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, [], "FACTOR_SERVICE_UNAVAILABLE")
        try:
            rows = await self.factor_service.attribution_for_trade(trade_id)
            return FactorToolResult(True, rows, None)
        except Exception as exc:
            return FactorToolResult(False, [], f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_factor_decay_status(self, factor: str, symbol: str) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        try:
            decay = await self.factor_service.latest_decay(factor, symbol)
            return FactorToolResult(
                True, decay or {"factor_name": factor, "symbol": symbol, "status": "HEALTHY"}, None
            )
        except Exception as exc:
            return FactorToolResult(False, {}, f"FACTOR_UNAVAILABLE:{type(exc).__name__}")


def _summarize(market_state: dict) -> str:
    if not market_state:
        return "Factor data unavailable"
    trend = market_state.get("trend", 0)
    momentum = market_state.get("momentum", 0)
    volatility = market_state.get("volatility", 0)
    orderflow = market_state.get("orderflow", 0)
    funding = market_state.get("funding", 0)
    parts = []
    parts.append(
        "Trend: " + ("bullish" if trend > 0.2 else "bearish" if trend < -0.2 else "neutral")
    )
    parts.append(
        "Momentum: " + ("positive" if momentum > 0 else "negative" if momentum < 0 else "flat")
    )
    parts.append(
        "Volatility: " + ("high" if volatility > 0.6 else "medium" if volatility > 0.3 else "low")
    )
    parts.append(
        "Orderflow: "
        + (
            "buy pressure"
            if orderflow > 0.1
            else "sell pressure"
            if orderflow < -0.1
            else "balanced"
        )
    )
    parts.append(
        "Funding: "
        + ("crowded long" if funding > 0.5 else "normal" if funding > -0.5 else "crowded short")
    )
    return "; ".join(parts)
