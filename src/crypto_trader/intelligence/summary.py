"""Market summary engine: factor/regime/research/anomaly -> human readable summary."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MarketSummary:
    market_state: str
    summary: str
    supporting: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "market_state": self.market_state,
            "summary": self.summary,
            "supporting": self.supporting,
            "risks": self.risks,
        }


class MarketSummaryEngine:
    def summarize(
        self,
        *,
        regime: dict,
        factors: dict,
        anomalies: list[dict],
        research: list[dict] | None = None,
    ) -> MarketSummary:
        market_state = regime.get("regime", "UNKNOWN")
        supporting = []
        risks = []
        if factors.get("trend", 0) > 0.3:
            supporting.append("trend healthy")
        elif factors.get("trend", 0) < -0.3:
            risks.append("downtrend")
        if factors.get("open_interest", 0) > 0:
            supporting.append("OI confirmation")
        for anomaly in anomalies:
            if anomaly.get("severity", 0) >= 0.6:
                risks.append(anomaly.get("type", "market anomaly"))
        if factors.get("funding", 0) > 0.5:
            risks.append("funding extreme")
        summary = f"{market_state}: " + (
            "trend remains constructive but risk factors exist"
            if risks
            else "constructive with confirmation"
        )
        return MarketSummary(
            market_state=market_state, summary=summary, supporting=supporting[:3], risks=risks[:3]
        )
