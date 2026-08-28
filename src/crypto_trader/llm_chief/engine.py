"""LLM Chief Trader engine. Decision layer only, no execution."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import ChiefTraderDecision
from crypto_trader.llm_chief.provider import LLMProvider


class ChiefTraderEngine:
    def __init__(self, provider: LLMProvider | None = None, model_version: str = "0.1.0") -> None:
        self.provider = provider
        self.model_version = model_version

    async def decide(self, ctx: ChiefTraderContext) -> ChiefTraderDecision:
        prompt = self.render_prompt(ctx)
        if self.provider and hasattr(self.provider, "complete_domain_analysis"):
            response = await self.provider.complete_domain_analysis(
                context=ctx.domain_model_context()
            )
        else:
            response = await self.provider.complete_json(prompt=prompt) if self.provider else None
        if response is not None and response.ok and response.parsed_json:
            return self.parse_decision(response.parsed_json, ctx)
        # Fail safe: LLM unavailable or invalid JSON -> NO_TRADE
        return ChiefTraderDecision(
            decision_id=f"fail_{datetime.now(UTC).timestamp()}",
            symbol=ctx.symbol,
            action="NO_TRADE",
            market_regime=ctx.regime,
            thesis="LLM_UNAVAILABLE",
            reason_codes=["LLM_UNAVAILABLE"],
            model_version=self.model_version,
            created_at=datetime.now(UTC).isoformat(),
        )

    def render_prompt(self, ctx: ChiefTraderContext) -> str:
        return (
            "You are the Chief Trader of a crypto fund. Return JSON only.\n"
            f"Symbol: {ctx.symbol}\nRegime: {ctx.regime}\n"
            f"Market: {ctx.market_snapshot}\nQuantEvidence: {ctx.quant_evidence}\n"
            f"Portfolio: {ctx.portfolio_state}\nRisk: {ctx.risk_summary}\n"
            f"Knowledge: {ctx.knowledge}\nSimilarEpisodes: {ctx.similar_episodes}\n"
            f"CoinProfile: {ctx.coin_profile}\nExperience: {ctx.compressed_experience}\n"
            "Output keys: decision_id,symbol,action,market_regime,strategy_selected,thesis,"
            "position_size_request,leverage_request,raw_llm_confidence,reason_codes."
        )

    def parse_decision(self, raw: dict, ctx: ChiefTraderContext) -> ChiefTraderDecision:
        raw.setdefault("decision_id", f"llm_{datetime.now(UTC).timestamp()}")
        raw.setdefault("symbol", ctx.symbol)
        raw.setdefault("market_regime", ctx.regime)
        raw.setdefault("action", "NO_TRADE")
        raw.setdefault("created_at", datetime.now(UTC).isoformat())
        return ChiefTraderDecision(**raw)
