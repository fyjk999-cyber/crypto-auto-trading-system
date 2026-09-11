"""Canonical read-only FactorService adapters for ChiefTrader."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from crypto_trader.factors.evaluator import FactorEvaluator
from crypto_trader.factors.models import FactorPerformance
from crypto_trader.llm.tools.registry import LLMToolRegistry, ToolEvidence


def register_factor_runtime_tools(registry: LLMToolRegistry, service) -> None:
    registry.register(
        "factor_snapshot", _snapshot(service),
        description="Latest stored factor snapshot",
    )
    registry.register(
        "factor_history", _history(service),
        description="Last 100 factor observations",
    )
    registry.register(
        "factor_performance", _performance(service),
        description="Recent sample sizes and out-of-sample factor performance",
    )
    registry.register(
        "factor_health", _health(service),
        description="Canonical FactorEvaluator health status for stored factors",
    )


def _timestamp(payload, fallback: datetime) -> datetime:
    value = payload.get("timestamp") if isinstance(payload, dict) else None
    if not value:
        return fallback
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _evidence(name, symbol, payload, as_of):
    rows = payload if isinstance(payload, list) else [payload] if payload else []
    timestamps = [_timestamp(row, as_of) for row in rows if isinstance(row, dict)]
    return ToolEvidence(
        tool_name=name,
        symbol=symbol,
        timestamp=max(timestamps, default=as_of),
        features={"rows": rows},
        supporting_evidence=[],
        contrary_evidence=[] if rows else ["no factor observations"],
        confidence_of_measurement=1.0 if rows else 0.0,
        data_quality="FACTUAL_STORED" if rows else "NO_DATA",
        source_refs=[f"factor:{symbol}:{name}"] if rows else [],
    )


def _snapshot(service):
    async def execute(symbol, context):
        payload = await service.latest_snapshot(symbol)
        return _evidence("factor_snapshot", symbol, payload, context["as_of"])
    return execute


def _history(service):
    async def execute(symbol, context):
        payload = await service.recent_values(symbol, 100)
        return _evidence("factor_history", symbol, payload, context["as_of"])
    return execute


def _performance(service):
    async def execute(symbol, context):
        payload = await service.recent_performance(symbol, 25)
        return _evidence("factor_performance", symbol, payload, context["as_of"])
    return execute


def _health(service):
    async def execute(symbol, context):
        rows = await service.recent_performance(symbol, 25)
        evaluator = FactorEvaluator()
        health_rows = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            try:
                performance = FactorPerformance(
                    factor_name=str(row.get("factor_name") or "UNKNOWN"),
                    symbol=str(row.get("symbol") or symbol),
                    timeframe=str(row.get("timeframe") or ""),
                    sample_size=int(row.get("sample_size") or 0),
                    win_rate=Decimal(str(row.get("win_rate") or "0")),
                    average_return=Decimal(str(row.get("average_return") or "0")),
                    sharpe=Decimal(str(row.get("sharpe") or "0")),
                    max_drawdown=Decimal(str(row.get("max_drawdown") or "0")),
                    profit_factor=Decimal(str(row.get("profit_factor") or "0")),
                )
            except Exception:
                continue
            health_rows.append(evaluator.evaluate(performance).to_dict())
        return _evidence("factor_health", symbol, health_rows, context["as_of"])
    return execute
