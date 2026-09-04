"""Selective, read-only quantitative evidence tools for the Live LLM."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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


class EvidenceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    symbol: str
    timestamp: datetime
    finding: dict[str, Any] = Field(default_factory=dict)
    supporting_evidence: list[str] = Field(default_factory=list)
    contrary_evidence: list[str] = Field(default_factory=list)
    confidence_of_measurement: float = Field(ge=0.0, le=1.0)
    data_quality: str
    freshness: str
    source_refs: list[str] = Field(default_factory=list)


class DynamicEvidencePackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    selected_tools: list[str]
    items: list[EvidenceItem]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def source_refs(self) -> list[str]:
        return sorted({ref for item in self.items for ref in item.source_refs})


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

    async def build_package(
        self,
        names: list[str],
        symbol: str,
        context: dict[str, Any],
        *,
        now: datetime,
        max_age_seconds: float = 30.0,
    ) -> DynamicEvidencePackage:
        if len(names) != len(set(names)) or any(name not in self._tools for name in names):
            raise ValueError("tool selection contains unknown or duplicate tools")
        items: list[EvidenceItem] = []
        for name in names:
            evidence = await self.call(name, symbol, context)
            timestamp = (
                evidence.timestamp.astimezone(UTC)
                if evidence.timestamp.tzinfo is not None
                else evidence.timestamp.replace(tzinfo=UTC)
            )
            age = max(0.0, (now.astimezone(UTC) - timestamp).total_seconds())
            freshness = "FRESH" if age <= max_age_seconds else "STALE"
            items.append(
                EvidenceItem(
                    tool_name=evidence.tool_name,
                    symbol=evidence.symbol,
                    timestamp=timestamp,
                    finding=evidence.features,
                    supporting_evidence=evidence.supporting_evidence,
                    contrary_evidence=evidence.contrary_evidence,
                    confidence_of_measurement=evidence.confidence_of_measurement,
                    data_quality=evidence.data_quality,
                    freshness=freshness,
                    source_refs=evidence.source_refs,
                )
            )
        return DynamicEvidencePackage(symbol=symbol, selected_tools=names, items=items)
