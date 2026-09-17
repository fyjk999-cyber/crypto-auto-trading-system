"""LLM Chief Trader engine. Decision layer only, no execution."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import (
    ChiefTraderDecision,
    FlatAction,
    OpenAction,
    PositionState,
)
from crypto_trader.llm_chief.policy import (
    OPERATION_TOOL_SELECTION,
    OPERATION_TRADING_DECISION,
    reasoning_effort_for,
    thinking_for,
)
from crypto_trader.llm_chief.provider import LLMProvider
from crypto_trader.market_data.opportunity.context import (
    render_opportunity_context_block,
)


class ToolSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[str] = Field(default_factory=list, max_length=12)


class ChiefTraderEngine:
    def __init__(self, provider: LLMProvider | None = None, model_version: str = "0.1.0") -> None:
        self.provider = provider
        self.model_version = model_version

    async def select_tools(
        self, ctx: ChiefTraderContext, available_tools: list[str]
    ) -> tuple[list[str] | None, str | None]:
        if self.provider is None:
            return None, "LLM_UNAVAILABLE"
        prompt = (
            "You are the same Chief Trader that will make the final decision. "
            "Select only the factual read-only tools needed for this context. "
            'Return JSON only as {"tools":[...]}.\n'
            f"Symbol: {ctx.symbol}\nPositionState: {ctx.position_state.value}\n"
            f"Market: {ctx.market_snapshot}\nAvailableTools: {available_tools}"
        )
        response = await self.provider.complete_json(
            prompt=prompt,
            temperature=0.0,
            timeout_seconds=20.0,
            retries=1,
            max_tokens=768,
            # Pure tool routing: intentionally no hidden reasoning.
            thinking=thinking_for(OPERATION_TOOL_SELECTION),
            operation=OPERATION_TOOL_SELECTION,
        )
        if not response.ok or response.parsed_json is None:
            return None, response.error or "TOOL_SELECTION_FAILED"
        try:
            selection = ToolSelection(**response.parsed_json)
        except ValidationError:
            return None, "INVALID_TOOL_SELECTION"
        if len(selection.tools) != len(set(selection.tools)):
            return None, "INVALID_TOOL_SELECTION"
        if any(tool not in available_tools for tool in selection.tools):
            return None, "UNKNOWN_TOOL_SELECTED"
        return selection.tools, None

    async def decide(self, ctx: ChiefTraderContext, *, rebuild_context=None) -> ChiefTraderDecision:
        prompt = self.render_prompt(ctx)
        provider_kwargs = dict(
            prompt=prompt,
            temperature=0.2,
            timeout_seconds=30.0,
            retries=1,
            max_tokens=2400,
            # The real trading decision (and, because PositionReview reuses this
            # same path, every HOLD/REDUCE/EXIT) takes its reasoning budget from
            # the canonical policy. It must never be hard-coded low here.
            thinking=thinking_for(OPERATION_TRADING_DECISION),
            reasoning_effort=reasoning_effort_for(OPERATION_TRADING_DECISION),
            operation=OPERATION_TRADING_DECISION,
        )
        # Phase 4A seam: a Core LLM router may use a per-call fresh-state
        # rebuilder so the GLM backup never receives a stale prompt.
        if rebuild_context is not None and hasattr(self.provider, "prompt_rebuilder"):
            provider_kwargs["prompt_rebuilder"] = rebuild_context
        response = await self.provider.complete_json(**provider_kwargs) if self.provider else None
        if response is not None and response.ok and response.parsed_json:
            try:
                return self.parse_decision(
                    response.parsed_json,
                    ctx,
                    provider=response.provider,
                    model=response.model,
                )
            except (TypeError, ValueError, ValidationError) as exc:
                # Keep the factual rejection detail for Growth/ops diagnostics;
                # never execute a partially parsed decision.
                detail = str(exc).replace("\n", " ")[:240]
                keys = ",".join(sorted(str(key) for key in response.parsed_json))
                return self.fail_closed(ctx, f"INVALID_LLM_OUTPUT:{detail}|keys={keys[:120]}")
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
        action_contract = (
            '{"action":"LONG|SHORT|NO_TRADE|WAIT","plan_contract_version":2,'
            '"market_regime":"string",'
            '"strategy_selected":["string"],"thesis":"string",'
            '"supporting_evidence":["string"],"contradicting_evidence":["string"],'
            '"position_size_request":number,"requested_exposure":number|null,'
            '"capital_allocation_pct":number,"leverage_request":number,'
            '"base_exit":{"type":"PRICE|TIME|INDICATOR|EVENT","trigger":"string",'
            '"size_pct":number,"reason_code":"string"},'
            '"raw_llm_confidence":number,'
            '"stop_loss":number,"take_profit":number|null,'
            '"entry_plan":"string","expected_holding_period":"string",'
            '"invalidation_conditions":["string"],'
            '"reduce_conditions":["string"],"exit_conditions":["string"],'
            '"reason_codes":["string"]}'
            if ctx.position_state == PositionState.FLAT
            else '{"action":"HOLD|REDUCE|EXIT","market_regime":"string",'
            '"thesis":"string","supporting_evidence":["string"],'
            '"contradicting_evidence":["string"],'
            '"position_size_request":number,"reason_codes":["string"]}'
        )
        return (
            "You are the Chief Trader of a crypto fund. Return exactly one JSON "
            "object: no markdown, no code fences, no commentary before or after.\n"
            f"Symbol: {ctx.symbol}\nRegime: {ctx.regime}\n"
            f"PositionState: {ctx.position_state.value}\n"
            f"AllowedActions: {allowed_actions}\n"
            f"Market: {ctx.market_snapshot}\nQuantEvidence: {ctx.quant_evidence}\n"
            f"ExpertEvidence25: {ctx.model_evidence or 'UNAVAILABLE'}\n"
            f"Portfolio: {ctx.portfolio_state}\nRisk: {ctx.risk_summary}\n"
            f"OpenPosition: {ctx.position_context}\n"
            f"Knowledge: {ctx.knowledge}\nSimilarEpisodes: {ctx.similar_episodes}\n"
            f"CoinProfile: {ctx.coin_profile}\nExperience: {ctx.compressed_experience}\n"
            f"FailureWarnings: {ctx.failure_warnings}\n"
            + (
                render_opportunity_context_block(ctx.opportunity_context) + "\n"
                if ctx.opportunity_context
                else ""
            )
            + f"OutputContract: {action_contract}\n"
            "Do not add fields outside this contract. Numeric fields must be JSON numbers. "
            "Every LONG/SHORT new-risk decision MUST set plan_contract_version=2 with "
            "capital_allocation_pct in (0,25] (percent of account equity for THIS child), "
            "leverage_request in (0,20], and a concrete base_exit with trigger and "
            "size_pct as a JSON number in (0,100] (use 100 for a full exit; 0 is invalid). "
            "A decision missing any of those fields is rejected by execution "
            "and no order is placed. LONG/SHORT also require a positive quantity or "
            "requested exposure and a positive stop_loss invalidation price. "
            "The application creates decision_id and binds symbol."
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
        raw["created_at"] = datetime.now(UTC).isoformat()
        raw["model_provider"] = provider or getattr(self.provider, "name", "unknown")
        raw["model"] = model or getattr(self.provider, "model", "unknown")
        raw["model_version"] = self.model_version
        return ChiefTraderDecision(**raw)
