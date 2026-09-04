"""Canonical Live-LLM entry adapter.

Quant/factor/strategy engines are evidence providers only.  This adapter is the
only StrategyPlugin allowed to emit a new directional SignalIntent in the
official runtime: it gathers factual evidence, asks the ChiefTraderEngine for
the direction, durably audits that decision, then creates the TradePlan before
returning a signal to the existing Risk -> ExecutionAuthority pipeline.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from crypto_trader.alpha.ensemble import MultiStrategyAlpha
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.observability.audit import AuditService
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class LiveLLMDecisionStrategy(StrategyPlugin):
    """Evidence -> Live LLM -> durable decision -> TradePlan -> SignalIntent.

    The wrapped quant engine never emits executable signals.  LLM failure or an
    invalid/non-directional decision fails closed to no entry.
    """

    name = "live_llm"
    version = "canonical-1.0.0"

    def __init__(
        self,
        *,
        evidence_engine: MultiStrategyAlpha,
        chief: ChiefTraderEngine,
        planner: LiveLLMTradePlanner,
        audit: AuditService,
        risk_summary: dict[str, Any] | None = None,
        retry_cooldown_seconds: float = 30.0,
    ) -> None:
        self.evidence_engine = evidence_engine
        self.chief = chief
        self.planner = planner
        self.audit = audit
        self.risk_summary = risk_summary or {}
        self.symbol = evidence_engine.symbol
        self.retry_cooldown = timedelta(seconds=max(1.0, retry_cooldown_seconds))
        # This is an attempt cooldown, not an entry cooldown.  Every provider
        # call consumes the interval, including NO_TRADE and fail-closed output.
        self._last_decision_attempt: datetime | None = None

    async def on_market_data(self, ctx: StrategyContext):
        # OPEN-position management is a separate canonical LLM lifecycle.  New
        # directional entry authority must not pyramid through this entry path.
        position = ctx.positions.get(ctx.symbol)
        if position is not None and Decimal(str(position.quantity)) != 0:
            return []

        now = ctx.clock_time.astimezone(UTC)
        if (
            self._last_decision_attempt is not None
            and now - self._last_decision_attempt < self.retry_cooldown
        ):
            return []

        evidence = self.evidence_engine.analyze_evidence(ctx)
        chief_ctx = ChiefTraderContext(
            symbol=ctx.symbol,
            market_snapshot=self._market_snapshot(ctx),
            regime=self._regime(evidence),
            quant_evidence=[evidence],
            portfolio_state=self._portfolio_state(ctx),
            risk_summary=self.risk_summary,
        )
        self._last_decision_attempt = now
        decision = await self.chief.decide(chief_ctx)

        # This commit is deliberately before TradePlan creation.  It is the
        # durable factual proof that the LLM owned the proposed direction.
        await self.audit.log(
            "LIVE_LLM_DECISION",
            target=decision.decision_id,
            actor="live_llm",
            run_id=ctx.run_id,
            after={
                "decision": decision.model_dump(mode="json"),
                "evidence_source": self.evidence_engine.name,
                "decision_authority": "LIVE_LLM_ONLY",
            },
        )

        if decision.action not in {"LONG", "SHORT"}:
            return []
        try:
            _plan, signal = await self.planner.create_entry_signal(decision)
        except (TypeError, ValueError) as exc:
            await self.audit.log(
                "LIVE_LLM_DECISION_INVALID",
                target=decision.decision_id,
                actor="live_llm",
                run_id=ctx.run_id,
                after={"reason": str(exc), "action": decision.action},
            )
            return []
        return [signal] if signal is not None else []

    @staticmethod
    def _regime(evidence: dict[str, Any]) -> str:
        raw = evidence.get("regime", "UNKNOWN")
        if isinstance(raw, dict):
            return str(raw.get("regime") or raw.get("value") or "UNKNOWN")
        return str(raw)

    @staticmethod
    def _portfolio_state(ctx: StrategyContext) -> dict[str, Any]:
        return {
            "account": ctx.account.model_dump(mode="json"),
            "positions": {
                symbol: position.model_dump(mode="json")
                for symbol, position in ctx.positions.items()
            },
        }

    @staticmethod
    def _market_snapshot(ctx: StrategyContext) -> dict[str, Any]:
        best_bid = ctx.book.best_bid()
        best_ask = ctx.book.best_ask()
        mid = ctx.book.mid_price()
        return {
            "symbol": ctx.symbol,
            "timestamp": ctx.clock_time.isoformat(),
            "best_bid": str(best_bid.price) if best_bid is not None else None,
            "best_ask": str(best_ask.price) if best_ask is not None else None,
            "mid": str(mid) if mid is not None else None,
            "mark_price": str(ctx.mark_price) if ctx.mark_price is not None else None,
            "index_price": str(ctx.index_price) if ctx.index_price is not None else None,
            "funding": str(ctx.funding) if ctx.funding is not None else None,
            "open_interest": str(ctx.oi) if ctx.oi is not None else None,
            "basis": str(ctx.basis) if ctx.basis is not None else None,
            "source": "OKX_PUBLIC",
        }
