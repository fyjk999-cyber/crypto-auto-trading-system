"""Production monitoring and alerts."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AlertSystem:
    alerts: list[dict] = field(default_factory=list)

    def check(
        self,
        *,
        market_connected: bool,
        risk_halted: bool,
        drawdown_pct: float,
        exchange_available: bool,
        ai_confidence_drift: float,
    ) -> list[dict]:
        fired = []
        if not market_connected:
            fired.append({"alert": "MARKET_DISCONNECTED"})
        if risk_halted:
            fired.append({"alert": "RISK_HALTED"})
        if drawdown_pct >= 20:
            fired.append({"alert": "DD_WARNING"})
        if not exchange_available:
            fired.append({"alert": "EXCHANGE_UNAVAILABLE"})
        if ai_confidence_drift > 0.3:
            fired.append({"alert": "AI_CONFIDENCE_DRIFT"})
        self.alerts.extend(fired)
        return fired

    def active(self) -> list[dict]:
        return list(self.alerts)
