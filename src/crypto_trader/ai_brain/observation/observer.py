"""Market observation layer."""

from __future__ import annotations

from crypto_trader.ai_brain.models.schemas import MarketSituation


class MarketObserver:
    def observe(
        self,
        *,
        market_state: str,
        factor_intelligence: dict | None = None,
        portfolio: dict | None = None,
    ) -> MarketSituation:
        intelligence = factor_intelligence or {}
        opportunities = list(intelligence.get("positive_evidence", []))
        risks = list(intelligence.get("risk_notes", []))
        if isinstance(intelligence.get("factor_summary"), dict):
            risks.extend(intelligence["factor_summary"].get("risks", []))
            opportunities.extend(intelligence["factor_summary"].get("supporting", []))
        uncertainties = []
        portfolio = portfolio or {}
        if not portfolio.get("positions"):
            uncertainties.append("no existing positions")
        return MarketSituation(
            market_state=market_state,
            opportunities=list(dict.fromkeys(opportunities)),
            risks=list(dict.fromkeys(risks)),
            uncertainties=uncertainties,
        )
