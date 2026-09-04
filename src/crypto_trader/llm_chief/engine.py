"""LLM Chief Trader engine. Decision layer only, no execution."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import ValidationError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import (
    ChiefTraderDecision,
    FlatAction,
    OpenAction,
    PositionState,
)
from crypto_trader.llm_chief.provider import LLMProvider


class ChiefTraderEngine:
    def __init__(self, provider: LLMProvider | None = None, model_version: str = "0.1.0") -> None:
        self.provider = provider
        self.model_version = model_version

    async def decide(self, ctx: ChiefTraderContext) -> ChiefTraderDecision:
        prompt = self.render_prompt(ctx)
        response = await self.provider.complete_json(prompt=prompt) if self.provider else None
        if response is not None and response.ok and response.parsed_json:
            try:
                return self.parse_decision(
                    response.parsed_json,
                    ctx,
                    provider=response.provider,
                    model=response.model,
                )
            except (TypeError, ValueError, ValidationError):
                return self.fail_closed(ctx, "INVALID_LLM_OUTPUT")
        return self.fail_closed(ctx, response.error if response is not None else "LLM_UNAVAILABLE")

    def fail_closed(self, ctx: ChiefTraderContext, reason: str | None) -> ChiefTraderDecision:
        return ChiefTraderDecision(
            decision_id=new_id("llm"),
            symbol=ctx.symbol,
            position_state=ctx.position_state,
            action=FlatAction.FAIL_CLOSED
            if ctx.position_state == PositionState.FLAT
            else OpenAction.FAIL_CLOSED,
            market_regime=ctx.regime,
            thesis="FAIL_CLOSED",
            reason_codes=[reason or "LLM_UNAVAILABLE"],
            model_version=self.model_version,
            created_at=datetime.now(UTC).isoformat(),
            model_provider=getattr(self.provider, "name", "unconfigured"),
            model=getattr(self.provider, "model", "unconfigured"),
        )

    def render_prompt(self, ctx: ChiefTraderContext) -> str:
        allowed_actions = (
            "LONG,SHORT,NO_TRADE,WAIT"
            if ctx.position_state == PositionState.FLAT
            else "HOLD,REDUCE,EXIT"
        )
        return (
            "You are the Chief Trader of a crypto fund. Return JSON only.\n"
            f"Symbol: {ctx.symbol}\nRegime: {ctx.regime}\n"
            f"PositionState: {ctx.position_state.value}\n"
            f"AllowedActions: {allowed_actions}\n"
            f"Market: {ctx.market_snapshot}\nQuantEvidence: {ctx.quant_evidence}\n"
            f"Portfolio: {ctx.portfolio_state}\nRisk: {ctx.risk_summary}\n"
            f"OpenPosition: {ctx.position_context}\n"
            f"Knowledge: {ctx.knowledge}\nSimilarEpisodes: {ctx.similar_episodes}\n"
            f"CoinProfile: {ctx.coin_profile}\nExperience: {ctx.compressed_experience}\n"
            "Output keys: decision_id,symbol,action,market_regime,strategy_selected,thesis,"
            "position_size_request,leverage_request,raw_llm_confidence,reason_codes."
        )

    def parse_decision(
        self,
        raw: dict,
        ctx: ChiefTraderContext,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> ChiefTraderDecision:
        # Model-supplied identifiers must never become authoritative lineage.
        # The runtime owns both the decision id and the contextual symbol.
        raw = dict(raw)
        raw["decision_id"] = new_id("llm")
        raw["symbol"] = ctx.symbol
        raw["position_state"] = ctx.position_state
        raw.setdefault("market_regime", ctx.regime)
        raw.setdefault(
            "action",
            FlatAction.NO_TRADE
            if ctx.position_state == PositionState.FLAT
            else OpenAction.HOLD,
        )
        raw.setdefault("created_at", datetime.now(UTC).isoformat())
        raw["model_provider"] = provider or getattr(self.provider, "name", "unknown")
        raw["model"] = model or getattr(self.provider, "model", "unknown")
        raw.setdefault("model_version", self.model_version)
        return ChiefTraderDecision(**raw)
