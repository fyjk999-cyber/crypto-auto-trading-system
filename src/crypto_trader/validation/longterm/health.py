"""Long-term run health."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RunHealth:
    uptime_seconds: float = 0.0
    api_latency_ms: list[float] = field(default_factory=list)
    data_freshness: list[float] = field(default_factory=list)
    execution_latency_ms: list[float] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "uptime_seconds": self.uptime_seconds,
            "avg_api_latency_ms": sum(self.api_latency_ms) / len(self.api_latency_ms)
            if self.api_latency_ms
            else 0.0,
            "avg_data_freshness": sum(self.data_freshness) / len(self.data_freshness)
            if self.data_freshness
            else 0.0,
            "avg_execution_latency_ms": sum(self.execution_latency_ms)
            / len(self.execution_latency_ms)
            if self.execution_latency_ms
            else 0.0,
        }
