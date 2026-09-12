"""Market research agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MarketResearchReport:
    market_regime: str
    important_changes: list[str]
    new_patterns: list[str]
    failed_patterns: list[str]
    risk_warning: list[str]
    opportunities: list[str]


class MarketResearcher:
    def research(
        self, *, regime: str, anomalies: list, strategy_stats: dict, patterns: list[dict]
    ) -> MarketResearchReport:
        changes = [a.description for a in anomalies]
        risk = [a.description for a in anomalies if a.severity >= 0.7]
        opportunities = [p.get("strategy", "trend") for p in patterns if p.get("win_rate", 0) > 0.5]
        failed = [
            p.get("strategy", "mean_reversion") for p in patterns if p.get("win_rate", 0) < 0.4
        ]
        return MarketResearchReport(
            market_regime=regime,
            important_changes=changes,
            new_patterns=opportunities,
            failed_patterns=failed,
            risk_warning=risk,
            opportunities=opportunities,
        )
