"""Canonical Live-LLM entry authority.

Quant evidence is supplied as context only; this strategy is the sole source
of directional entry intents and never calls risk or execution directly.
"""

from __future__ import annotations

from decimal import Decimal

from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.trade_planner import LiveLLMTradePlanner
from crypto_trader.observability.audit import AuditService
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class LiveLLMStrategy(StrategyPlugin):
    name = "live_llm"
    version = "1"

    def __init__(
        self, *, chief: ChiefTraderEngine, planner: LiveLLMTradePlanner, audit: AuditService
    ):
        self.chief = chief
        self.planner = planner
        self.audit = audit
        self.decision_calls = 0
        self._last_decision_at = None

    async def on_market_data(self, ctx: StrategyContext) -> list:
        # Existing positions are deliberately excluded until the OPEN lifecycle
        # has its separate HOLD/REDUCE/EXIT contract.
        if ctx.positions.get(ctx.symbol) and ctx.positions[ctx.symbol].quantity != 0:
            return []
        if self._last_decision_at is not None and (
            ctx.clock_time - self._last_decision_at
        ).total_seconds() < 30:
            return []
        book = ctx.book
        mid = book.mid_price()
        if mid is None:
            return []
        decision = await self.chief.decide(
            ChiefTraderContext(
                symbol=ctx.symbol,
                market_snapshot={
                    "price": str(mid),
                    "mark_price": str(ctx.mark_price) if ctx.mark_price is not None else None,
                    "funding": str(ctx.funding) if ctx.funding is not None else None,
                    "open_interest": str(ctx.oi) if ctx.oi is not None else None,
                },
                regime="UNKNOWN",
                quant_evidence=[],
                portfolio_state={"equity": str(ctx.account.equity)},
                risk_summary={},
            )
        )
        self.decision_calls += 1
        self._last_decision_at = ctx.clock_time
        await self.audit.log(
            "LIVE_LLM_DECISION",
            target=decision.decision_id,
            run_id=ctx.run_id,
            after={"action": decision.action, "symbol": decision.symbol},
        )
        if decision.action not in {"LONG", "SHORT"}:
            return []
        _, signal = await self.planner.create_entry_signal(decision, limit_price=Decimal(mid))
        return [signal] if signal is not None else []
