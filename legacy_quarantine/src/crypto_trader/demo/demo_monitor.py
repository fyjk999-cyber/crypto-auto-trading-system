"""Demo monitoring stats."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DemoMonitor:
    order_latency_ms: list[float] = field(default_factory=list)
    fill_ratio: float = 0.0
    reject_ratio: float = 0.0
    slippage_bps: list[float] = field(default_factory=list)
    api_failures: int = 0
    position_mismatch: int = 0

    def record_latency(self, ms: float) -> None:
        self.order_latency_ms.append(ms)

    def record_rejection(self) -> None:
        self.api_failures += 1

    def snapshot(self) -> dict:
        avg_latency = (
            sum(self.order_latency_ms) / len(self.order_latency_ms)
            if self.order_latency_ms
            else 0.0
        )
        return {
            "order_latency_ms": self.order_latency_ms,
            "avg_order_latency_ms": avg_latency,
            "fill_ratio": self.fill_ratio,
            "reject_ratio": self.reject_ratio,
            "slippage_bps": self.slippage_bps,
            "api_failures": self.api_failures,
            "position_mismatch": self.position_mismatch,
        }
