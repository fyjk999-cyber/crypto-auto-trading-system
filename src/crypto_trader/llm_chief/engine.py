"""LLM Chief Trader engine. Decision layer only, no execution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from crypto_trader.domain.identifiers import new_id
from crypto_trader.llm.tools.registry import MAX_SELECTED_TOOLS
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.decision import (
    ChiefTraderDecision,
    FlatAction,
    OpenAction,
    PositionState,
)
from crypto_trader.llm_chief.provider import LLMProvider
from crypto_trader.market_data.opportunity.context import (
    render_opportunity_context_block,
)
from crypto_trader.market_data.opportunity.selection import (
    ST_FAILED,
    ST_INVALID_OUTPUT,
    ST_LLM_UNAVAILABLE,
    ST_SUCCESS,
    ST_TIMEOUT,
    MarketSelectionOutput,
    parse_selection_payload,
    render_selection_prompt,
)


class ToolSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tools: list[str] = Field(default_factory=list, max_length=MAX_SELECTED_TOOLS)


@dataclass(slots=True)
class MarketSelectionResult:
    """Outcome of one ChiefTrader market-selection phase (research attention)."""

    ok: bool
    status: str
    output: MarketSelectionOutput | None = None
    error_code: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ChiefTraderEngine:
    def __init__(self, provider: LLMProvider | None = None, model_version: str = "0.1.0") -> None:
        self.provider = provider
        self.model_version = model_version

    async def select_tools(
        self,
        ctx: ChiefTraderContext,
        available_tools: list[str] | dict[str, str],
        *,
        timeout_seconds: float | None = None,
    ) -> tuple[list[str] | None, str | None]:
        if self.provider is None:
            return None, "LLM_UNAVAILABLE"
        names = list(available_tools)
        prompt = (
            "You are the same Chief Trader that will make the final decision. "
            "Select only the factual read-only tools needed for this context. "
            "Return JSON only as {\"tools\":[...]}.\n"
            f"Select at most {MAX_SELECTED_TOOLS} tools.\n"
            f"Symbol: {ctx.symbol}\nPositionState: {ctx.position_state.value}\n"
            f"OpenPosition: {ctx.position_context}\n"
            f"Portfolio: {ctx.portfolio_state}\nRisk: {ctx.risk_summary}\n"
            f"Opportunity: {ctx.opportunity_context}\n"
            f"Market: {ctx.market_snapshot}\nAvailableTools: {available_tools}"
        )
        response = await self.provider.complete_json(
            prompt=prompt,
            temperature=0.0,
            timeout_seconds=min(20.0, timeout_seconds or 20.0),
            retries=1,
            max_tokens=768,
            thinking=False,
            operation="tool_selection",
        )
        if not response.ok or response.parsed_json is None:
            return None, response.error or "TOOL_SELECTION_FAILED"
        try:
            selection = ToolSelection(**response.parsed_json)
        except ValidationError:
            return None, "INVALID_TOOL_SELECTION"
        if len(selection.tools) != len(set(selection.tools)):
            return None, "INVALID_TOOL_SELECTION"
        if any(tool not in names for tool in selection.tools):
            return None, "UNKNOWN_TOOL_SELECTED"
        return selection.tools, None

    async def select_markets(
        self,
        selection_context: dict,
        *,
        timeout_seconds: float = 40.0,
        selection_id: str,
        scan_id: str,
        known_symbols: set[str] | None = None,
    ) -> MarketSelectionResult:
        """Phase 1 of the SAME ChiefTrader authority: research attention only.

        It cannot emit direction, quantity, leverage, stops or orders — the
        strict schema plus the explicit authority-leak scan rejects them.
        """
        if self.provider is None:
            return MarketSelectionResult(
                ok=False, status=ST_LLM_UNAVAILABLE, error_code="LLM_UNAVAILABLE"
            )
        prompt = render_selection_prompt(selection_context)
        try:
            response = await self.provider.complete_json(
                prompt=prompt,
                temperature=0.0,
                timeout_seconds=max(1.0, float(timeout_seconds)),
                retries=1,
                max_tokens=900,
                thinking=False,
                operation="market_selection",
            )
        except TimeoutError:
            return MarketSelectionResult(
                ok=False, status=ST_TIMEOUT, error_code="SELECTION_TIMEOUT"
            )
        except Exception as exc:  # provider explosion -> fail closed, never fake
            return MarketSelectionResult(
                ok=False,
                status=ST_FAILED,
                error_code=f"{type(exc).__name__}"[:64],
            )
        usage = response.token_usage or {}
        result_kwargs = {
            "provider": response.provider,
            "model": response.model,
            "latency_ms": int(response.latency_ms),
            "input_tokens": _token(usage, "prompt_tokens", "input_tokens"),
            "output_tokens": _token(usage, "completion_tokens", "output_tokens"),
        }
        if not response.ok or response.parsed_json is None:
            return MarketSelectionResult(
                ok=False,
                status=ST_LLM_UNAVAILABLE,
                error_code=(response.error or "LLM_UNAVAILABLE")[:64],
                **result_kwargs,
            )
        parsed = parse_selection_payload(
            response.parsed_json,
            selection_id=selection_id,
            scan_id=scan_id,
            known_symbols=None,  # pool/directory membership checked by the service
        )
        if isinstance(parsed, str):
            return MarketSelectionResult(
                ok=False,
                status=ST_INVALID_OUTPUT,
                error_code=parsed,
                **result_kwargs,
            )
        return MarketSelectionResult(ok=True, status=ST_SUCCESS, output=parsed, **result_kwargs)

    async def decide(self, ctx: ChiefTraderContext) -> ChiefTraderDecision:
        prompt = self.render_prompt(ctx)
        response = (
            await self.provider.complete_json(
                prompt=prompt,
                temperature=0.2,
                # DeepSeek reasoning responses observed at 20-30s; keep a
                # bounded margin so transient slowness becomes retryable
                # instead of a durable LLM_TIMEOUT fail-closed decision.
                timeout_seconds=45.0,
                retries=1,
                max_tokens=2400,
                thinking=True,
                reasoning_effort="low",
                operation="trading_decision",
            )
            if self.provider
            else None
        )
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
        action_contract = (
            '{"action":"LONG|SHORT|NO_TRADE|WAIT","market_regime":"string",'
            '"strategy_selected":["string"],"thesis":"string",'
            '"supporting_evidence":["string"],"contradicting_evidence":["string"],'
            '"position_size_request":number,"requested_exposure":number|null,'
            '"leverage_request":number,"raw_llm_confidence":number,'
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
            "You are the Chief Trader of a crypto fund. Return JSON only.\n"
            f"Symbol: {ctx.symbol}\nRegime: {ctx.regime}\n"
            f"PositionState: {ctx.position_state.value}\n"
            f"AllowedActions: {allowed_actions}\n"
            f"Market: {ctx.market_snapshot}\nQuantEvidence: {ctx.quant_evidence}\n"
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
            "LONG/SHORT require a positive quantity or requested exposure, positive leverage, "
            "and a positive stop_loss invalidation price. "
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


def _token(usage: dict, *keys: str) -> int | None:
    for key in keys:
        value = usage.get(key) if isinstance(usage, dict) else None
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None
