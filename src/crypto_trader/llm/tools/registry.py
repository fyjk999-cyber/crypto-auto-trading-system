"""Selective, read-only quantitative evidence tools for the Live LLM."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

MAX_SELECTED_TOOLS = 8


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
    tool_versions: dict[str, str] = Field(default_factory=dict)
    contract_version: str = "tool-round-v1"
    schema_version: str = "evidence-package-v1"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def source_refs(self) -> list[str]:
        return sorted({ref for item in self.items for ref in item.source_refs})

    def refs_with_prefix(self, prefix: str) -> list[str]:
        return sorted(ref for ref in self.source_refs if ref.startswith(prefix))


EvidenceTool = Callable[[str, dict[str, Any]], Awaitable[ToolEvidence]]


class LLMToolRegistry:
    """A registry; it does not schedule or require every tool to run."""

    def __init__(self) -> None:
        self._tools: dict[str, EvidenceTool] = {}
        self._descriptions: dict[str, str] = {}
        self._versions: dict[str, str] = {}

    def register(
        self,
        name: str,
        tool: EvidenceTool,
        *,
        description: str = "",
        version: str = "v1",
    ) -> None:
        if not name or name in self._tools:
            raise ValueError(f"duplicate or invalid LLM evidence tool: {name}")
        if not version:
            raise ValueError("tool version must be explicit")
        self._tools[name] = tool
        self._descriptions[name] = description
        self._versions[name] = version

    def available(self) -> list[str]:
        return sorted(self._tools)

    def catalog(self) -> dict[str, str]:
        return {name: self._descriptions[name] for name in self.available()}

    def tool_versions(self) -> dict[str, str]:
        return {name: self._versions[name] for name in self.available()}

    async def call(
        self,
        name: str,
        symbol: str,
        context: dict[str, Any],
        *,
        timeout_seconds: float = 10.0,
    ) -> ToolEvidence:
        if name not in self._tools:
            raise KeyError(f"unknown LLM evidence tool: {name}")
        try:
            return await asyncio.wait_for(
                self._tools[name](symbol, context),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            return ToolEvidence(
                tool_name=name,
                symbol=symbol,
                timestamp=datetime.now(UTC),
                features={},
                supporting_evidence=[],
                contrary_evidence=["tool timeout"],
                confidence_of_measurement=0.0,
                data_quality="UNAVAILABLE",
                source_refs=[],
            )
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
        timeout_seconds: float = 10.0,
        max_tools: int = MAX_SELECTED_TOOLS,
        overall_timeout_seconds: float = 30.0,
    ) -> DynamicEvidencePackage:
        if len(names) != len(set(names)) or any(name not in self._tools for name in names):
            raise ValueError("tool selection contains unknown or duplicate tools")
        if len(names) > max_tools:
            raise ValueError("tool budget exceeded")
        items: list[EvidenceItem] = []
        deadline = asyncio.get_running_loop().time() + overall_timeout_seconds
        for name in names:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise ValueError("overall tool deadline exceeded")
            evidence = await self.call(
                name, symbol, {**context, "as_of": now},
                timeout_seconds=min(timeout_seconds, remaining),
            )
            if evidence.symbol != symbol:
                evidence = ToolEvidence(
                    tool_name=evidence.tool_name,
                    symbol=symbol,
                    timestamp=evidence.timestamp,
                    features={},
                    supporting_evidence=[],
                    contrary_evidence=["wrong symbol evidence rejected"],
                    confidence_of_measurement=0.0,
                    data_quality="UNAVAILABLE",
                    source_refs=[],
                )
            timestamp = (
                evidence.timestamp.astimezone(UTC)
                if evidence.timestamp.tzinfo is not None
                else evidence.timestamp.replace(tzinfo=UTC)
            )
            age = (now.astimezone(UTC) - timestamp).total_seconds()
            if age < 0:
                evidence = ToolEvidence(
                    tool_name=name, symbol=symbol, timestamp=timestamp,
                    features={}, supporting_evidence=[],
                    contrary_evidence=["future evidence rejected"],
                    confidence_of_measurement=0.0, data_quality="UNAVAILABLE", source_refs=[],
                )
            freshness = "FRESH" if age <= max_age_seconds else "STALE"
            if age < 0:
                freshness = "FUTURE_REJECTED"
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
        return DynamicEvidencePackage(
            symbol=symbol,
            selected_tools=names,
            items=items,
            tool_versions={name: self._versions[name] for name in names},
            created_at=now,
        )
