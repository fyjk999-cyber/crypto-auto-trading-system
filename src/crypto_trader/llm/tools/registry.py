"""Selective, read-only quantitative evidence tools for the Live LLM."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ToolEvidence:
    tool_name: str
    symbol: str
    timestamp: datetime
    features: dict[str, Any]
    supporting_evidence: list[str]
    contrary_evidence: list[str]
    confidence_of_measurement: float
    data_quality: str
    source_refs: list[str]


EvidenceTool = Callable[[str, dict[str, Any]], Awaitable[ToolEvidence]]


class LLMToolRegistry:
    """A registry; it does not schedule or require every tool to run."""

    def __init__(self) -> None:
        self._tools: dict[str, EvidenceTool] = {}

    def register(self, name: str, tool: EvidenceTool) -> None:
        if not name or name in self._tools:
            raise ValueError(f"duplicate or invalid LLM evidence tool: {name}")
        self._tools[name] = tool

    def available(self) -> list[str]:
        return sorted(self._tools)

    async def call(self, name: str, symbol: str, context: dict[str, Any]) -> ToolEvidence:
        if name not in self._tools:
            raise KeyError(f"unknown LLM evidence tool: {name}")
        try:
            return await self._tools[name](symbol, context)
        except Exception as exc:
            return ToolEvidence(
                tool_name=name,
                symbol=symbol,
                timestamp=datetime.now(UTC),
                features={},
                supporting_evidence=[],
                contrary_evidence=[f"tool unavailable: {type(exc).__name__}"],
                confidence_of_measurement=0.0,
                data_quality="UNAVAILABLE",
                source_refs=[],
            )
