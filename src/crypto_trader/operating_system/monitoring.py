"""OS monitoring and alerting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OSMetric:
    name: str
    value: float
    threshold: float
    alert: str


class OSMonitor:
    def __init__(self) -> None:
        self.metrics: list[OSMetric] = []
        self.alerts: list[str] = []

    def record(self, name: str, value: float, threshold: float, alert: str) -> None:
        self.metrics.append(OSMetric(name, value, threshold, alert))
        if value > threshold:
            self.alerts.append(alert)

    def active_alerts(self) -> list[str]:
        return list(self.alerts)
