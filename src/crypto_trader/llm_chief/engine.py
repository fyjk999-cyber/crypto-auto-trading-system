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
        invocation_id = getattr(response, "invocation_id", "") if response else ""
        if response is not None and response.ok and response.parsed_json:
            decision = self.parse_decision(response.parsed_json, ctx)
            return decision.model_copy(update={"llm_invocation_id": invocation_id})
        # Fail safe: LLM unavailable or invalid JSON -> NO_TRADE
        return ChiefTraderDecision(
            decision_id=f"fail_{datetime.now(UTC).timestamp()}",
            symbol=ctx.symbol,
            action="NO_TRADE",
            market_regime=ctx.regime,
            llm_invocation_id=invocation_id,
            thesis="LLM_UNAVAILABLE",
            reason_codes=["LLM_UNAVAILABLE"],
            model_version=self.model_version,
            created_at=datetime.now(UTC).isoformat(),
        )

    def render_prompt(self, ctx: ChiefTraderContext) -> str:
        return (
            "You are the Chief Trader of a crypto fund. Return JSON only.\n"
            "Determine which available trading strategy best fits the current market"
            " state. You do NOT need all strategies or all factors to agree. Select"
            " the dominant strategy based on regime and evidence. Contradicting"
            " factors should lower confidence or alter sizing, but should not"
            " automatically veto a trade unless they invalidate the selected"
            " strategy. Only choose NO_TRADE when no strategy currently has"
            " sufficient evidence-adjusted edge or a hard safety gate prevents"
            " entry.\n"
            f"Symbol: {ctx.symbol}\nRegime: {ctx.regime}\n"
            f"Market: {ctx.market_snapshot}\n"
            f"StrategyEvidencePackage: {ctx.strategy_evidence}\n"
            f"FactorSnapshot: {ctx.factor_snapshot}\n"
            f"QuantEvidence: {ctx.quant_evidence}\n"
            f"Portfolio: {ctx.portfolio_state}\nRisk: {ctx.risk_summary}\n"
            f"Knowledge: {ctx.knowledge}\nSimilarEpisodes: {ctx.similar_episodes}\n"
            f"CoinProfile: {ctx.coin_profile}\nExperience: {ctx.compressed_experience}\n"
            "Output keys: decision_id,symbol,action(LONG|SHORT|NO_TRADE|WAIT),"
            "market_regime,selected_strategy,strategy_fit_score,secondary_strategies,"
            "supporting_factors,contradicting_factors,dominant_factor,thesis,"
            "position_size_request,leverage_request,raw_llm_confidence,"
            "evidence_adjusted_confidence,invalidation_conditions,reason_codes."
        )

    # Entry vocabulary only. Position management actions (ADD/REDUCE/EXIT) and
    # anything unknown fail closed to WAIT (never an entry signal).
    _ACTION_ALIASES = {
        "LONG": "LONG", "OPEN_LONG": "LONG", "BUY": "LONG",
        "SHORT": "SHORT", "OPEN_SHORT": "SHORT", "SELL": "SHORT",
        "NO_TRADE": "NO_TRADE", "WAIT": "WAIT",
    }

    def parse_decision(self, raw: dict, ctx: ChiefTraderContext) -> ChiefTraderDecision:
        raw = dict(raw)
        raw.setdefault("decision_id", f"llm_{datetime.now(UTC).timestamp()}")
        raw.setdefault("symbol", ctx.symbol)
        raw.setdefault("market_regime", ctx.regime)
        raw_action = str(raw.get("action", "NO_TRADE")).upper()
        raw["action"] = self._ACTION_ALIASES.get(raw_action, "WAIT")
        if raw["action"] == "WAIT":
            raw.setdefault("reason_codes", [])
            if "ACTION_UNRECOGNIZED_FAIL_CLOSED" not in raw["reason_codes"]:
                raw["reason_codes"] = list(raw["reason_codes"]) + [
                    "ACTION_UNRECOGNIZED_FAIL_CLOSED"
                ]
        raw.setdefault("created_at", datetime.now(UTC).isoformat())
        allowed = set(ChiefTraderDecision.model_fields)
        filtered = {k: v for k, v in raw.items() if k in allowed}
        decision = ChiefTraderDecision(**filtered)
        if not decision.selected_strategy:
            dominant = (ctx.strategy_evidence or {}).get("strategy_candidates") or []
            directional = [c for c in dominant if c.get("direction") in ("LONG", "SHORT")]
            if directional:
                best = max(directional, key=lambda c: float(c.get("fit_score", 0)))
                decision = decision.model_copy(
                    update={
                        "selected_strategy": best["strategy_id"],
                        "strategy_version": best.get("strategy_version", ""),
                        "strategy_fit_score": float(best.get("fit_score", 0.0)),
                    }
                )
        return decision
