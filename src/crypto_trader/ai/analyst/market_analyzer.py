"""Rule-based AI market analyst (no LLM)."""

from __future__ import annotations

from crypto_trader.ai.analyst.opinion_schema import AIMarketOpinion
from crypto_trader.ai.context_builder import AIAnalysisContext


class MarketAnalyzer:
    def analyze(self, ctx: AIAnalysisContext) -> AIMarketOpinion:
        reasons: list[str] = []
        score = 0.0
        feature = ctx.feature_vector
        if feature.get("regime") == "BULL":
            score += 1.0
            reasons.append("REGIME_BULL")
        elif feature.get("regime") == "BEAR":
            score -= 1.0
            reasons.append("REGIME_BEAR")
        roc = float(feature.get("roc5", 0))
        if roc > 0.002:
            score += 0.5
            reasons.append("MOMENTUM_POS")
        elif roc < -0.002:
            score -= 0.5
            reasons.append("MOMENTUM_NEG")
        rsi = float(feature.get("rsi14", 50))
        if rsi > 65:
            score -= 0.25
            reasons.append("OVERBOUGHT")
        elif rsi < 35:
            score += 0.25
            reasons.append("OVERSOLD")
        opp = ctx.opportunity
        if opp.get("side") == "LONG":
            score += 0.5
        elif opp.get("side") == "SHORT":
            score -= 0.5
        direction = "LONG" if score > 0.5 else "SHORT" if score < -0.5 else "NEUTRAL"
        confidence = min(0.9, abs(score) / 2.5)
        risk = "HIGH" if abs(score) > 1.5 else "MEDIUM" if abs(score) > 0.8 else "LOW"
        return AIMarketOpinion(
            symbol=ctx.symbol,
            direction_bias=direction,
            confidence=round(confidence, 3),
            risk_level=risk,
            timeframe="1h",
            reason_codes=reasons,
            timestamp=ctx.prepared_at,
        )
