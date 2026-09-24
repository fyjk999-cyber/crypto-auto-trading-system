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

    async def get_factor_snapshot(self, symbol: str, *, as_of=None) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        try:
            snapshot = await self.factor_service.latest_snapshot(symbol, as_of=as_of)
            if snapshot is None:
                return FactorToolResult(True, {"symbol": symbol, "status": "NO_DATA"}, None)
            return FactorToolResult(True, snapshot, None)
        except Exception as exc:
            return FactorToolResult(False, {}, f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_factor_history(
        self, symbol: str, factor: str, limit: int = 100, *, as_of=None
    ) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, [], "FACTOR_SERVICE_UNAVAILABLE")
        try:
            rows = await self.factor_service.history(symbol, factor, limit, as_of=as_of)
            return FactorToolResult(True, rows, None)
        except Exception as exc:
            return FactorToolResult(False, [], f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_market_factor_context(self, symbol: str, *, as_of=None) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        snapshot_result = await self.get_factor_snapshot(symbol, as_of=as_of)
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
        self, factor: str, symbol: str, timeframe: str = "15m", *, as_of=None
    ) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        try:
            perf = await self.factor_service.latest_performance(factor, symbol, as_of=as_of)
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

    async def get_factor_health(
        self, factor: str, symbol: str, *, as_of=None
    ) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        perf = await self.get_factor_performance(factor, symbol, as_of=as_of)
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

    async def get_trade_factor_attribution(
        self, trade_id: str, *, as_of=None
    ) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, [], "FACTOR_SERVICE_UNAVAILABLE")
        try:
            rows = await self.factor_service.attribution_for_trade(trade_id, as_of=as_of)
            return FactorToolResult(True, rows, None)
        except Exception as exc:
            return FactorToolResult(False, [], f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def get_factor_decay_status(
        self, factor: str, symbol: str, *, as_of=None
    ) -> FactorToolResult:
        if self.factor_service is None:
            return FactorToolResult(False, {}, "FACTOR_SERVICE_UNAVAILABLE")
        try:
            decay = await self.factor_service.latest_decay(factor, symbol, as_of=as_of)
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


_FACTOR_TOOL_NAMES = (
    "factor_snapshot",
    "factor_history",
    "market_factor_context",
    "factor_performance",
    "factor_health",
    "factor_attribution",
    "factor_decay",
)


def register_factor_tools(registry, factor_tools: FactorTools) -> None:
    """Register existing read-only FactorTools in the single canonical registry."""
    for name in _FACTOR_TOOL_NAMES:
        registry.register(
            name,
            _adapter(factor_tools, name),
            description=f"Read-only factor evidence: {name}",
            version="1.0.0",
            source="FactorService+runtime_db",
            data_time_semantics="factor data timestamp must be <= decision_as_of",
            quality_semantics="EXPLICIT_AVAILABLE_UNAVAILABLE_STALE_NO_DATA",
        )


def _decision_as_of(context: dict):
    raw = context.get("decision_as_of")
    if raw is None:
        chief = context.get("chief_context")
        raw = getattr(chief, "prepared_at", None)
    if raw is None:
        strategy = context.get("strategy_context")
        raw = getattr(strategy, "clock_time", None)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _parse_ts(raw):
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def _adapter(factor_tools: FactorTools, name: str):
    async def execute(symbol: str, context: dict):
        from crypto_trader.llm.tools.registry import ToolEvidence

        as_of = _decision_as_of(context)
        if as_of is None:
            return ToolEvidence(
                tool_name=name,
                symbol=symbol,
                timestamp=datetime.now(UTC),
                features={},
                supporting_evidence=[],
                contrary_evidence=["DECISION_AS_OF_REQUIRED"],
                confidence_of_measurement=0.0,
                data_quality="UNAVAILABLE",
                source_refs=[f"tool:{name}", "factor:UNAVAILABLE"],
            )
        factor = str(context.get("factor_name") or context.get("factor") or "")
        timeframe = str(context.get("timeframe") or "15m")
        trade_id = str(context.get("trade_id") or context.get("position_id") or "")
        try:
            if name == "factor_snapshot":
                result = await factor_tools.get_factor_snapshot(symbol, as_of=as_of)
            elif name == "market_factor_context":
                result = await factor_tools.get_market_factor_context(symbol, as_of=as_of)
            elif name == "factor_history":
                result = await factor_tools.get_factor_history(
                    symbol,
                    factor or "UNKNOWN",
                    limit=int(context.get("limit") or 100),
                    as_of=as_of,
                )
            elif name == "factor_performance":
                result = await factor_tools.get_factor_performance(
                    factor or "UNKNOWN", symbol, timeframe, as_of=as_of
                )
            elif name == "factor_health":
                result = await factor_tools.get_factor_health(
                    factor or "UNKNOWN", symbol, as_of=as_of
                )
            elif name == "factor_attribution":
                if not trade_id:
                    return ToolEvidence(
                        tool_name=name,
                        symbol=symbol,
                        timestamp=as_of,
                        features={},
                        supporting_evidence=[],
                        contrary_evidence=["TRADE_ID_REQUIRED"],
                        confidence_of_measurement=0.0,
                        data_quality="UNAVAILABLE",
                        source_refs=[f"tool:{name}"],
                    )
                result = await factor_tools.get_trade_factor_attribution(trade_id, as_of=as_of)
            elif name == "factor_decay":
                result = await factor_tools.get_factor_decay_status(
                    factor or "UNKNOWN", symbol, as_of=as_of
                )
            else:
                raise ValueError(f"unknown factor tool adapter: {name}")
        except Exception as exc:
            return ToolEvidence(
                tool_name=name,
                symbol=symbol,
                timestamp=as_of,
                features={},
                supporting_evidence=[],
                contrary_evidence=[f"factor tool unavailable: {type(exc).__name__}"],
                confidence_of_measurement=0.0,
                data_quality="UNAVAILABLE",
                source_refs=[f"tool:{name}"],
            )
        data = getattr(result, "data", None)
        data_ts = None
        if isinstance(data, dict):
            data_ts = _parse_ts(data.get("timestamp"))
        ts = data_ts or as_of
        if data_ts is not None and data_ts > as_of:
            data_quality = "UNAVAILABLE"
            contrary = ["FUTURE_FACTOR_DATA"]
            features = {}
            confidence = 0.0
        elif not getattr(result, "ok", False):
            data_quality = "UNAVAILABLE"
            contrary = [str(getattr(result, "error", None) or "FACTOR_UNAVAILABLE")]
            features = {}
            confidence = 0.0
        else:
            if data is None or data == {} or data == []:
                data_quality = "NO_DATA"
                features = {}
                confidence = 0.0
                contrary = ["NO_FACTOR_DATA"]
            elif isinstance(data, dict) and str(data.get("status") or "") == "NO_DATA":
                data_quality = "NO_DATA"
                features = {}
                confidence = 0.0
                contrary = ["NO_FACTOR_DATA"]
            else:
                age = max(0.0, (as_of - ts).total_seconds())
                data_quality = "STALE" if age > 3600 else "AVAILABLE"
                features = data if isinstance(data, dict) else {"data": data}
                confidence = 1.0
                contrary = []
        return ToolEvidence(
            tool_name=name,
            symbol=symbol,
            timestamp=ts,
            features=features,
            supporting_evidence=[],
            contrary_evidence=contrary,
            confidence_of_measurement=confidence,
            data_quality=data_quality,
            source_refs=[f"tool:{name}", "factor_service"],
        )

    return execute
