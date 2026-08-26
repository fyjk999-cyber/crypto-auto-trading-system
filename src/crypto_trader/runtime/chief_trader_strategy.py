"""Canonical LLM Chief Trader entry strategy adapter.

MultiStrategyAlpha remains a shadow/benchmark evidence provider. This adapter is
the canonical entry decision path: it builds ChiefTraderContext, invokes
ChiefTraderEngine, and maps LONG/SHORT to SignalIntent. NO_TRADE submits nothing.
"""

from __future__ import annotations

from crypto_trader.domain.enums import OrderSide, OrderType
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import SignalIntent
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMProvider
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class ChiefTraderStrategyAdapter(StrategyPlugin):
    name = "llm_chief_trader"
    version = "1.0.0"

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        factor_intelligence_provider=None,
    ) -> None:
        self.provider = provider
        self.engine = ChiefTraderEngine(provider=provider)
        self.factor_intelligence_provider = factor_intelligence_provider

    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        factor_intelligence = {}
        if self.factor_intelligence_provider is not None:
            try:
                factor_intelligence = await self.factor_intelligence_provider(ctx.symbol)
            except Exception:
                factor_intelligence = {}
        chief_ctx = ChiefTraderContext(
            symbol=ctx.symbol,
            market_snapshot={
                "symbol": ctx.symbol,
                "clock_time": ctx.clock_time.isoformat(),
                "mark_price": str(ctx.mark_price) if ctx.mark_price is not None else None,
                "funding": str(ctx.funding) if ctx.funding is not None else None,
                "oi": str(ctx.oi) if ctx.oi is not None else None,
            },
            regime="UNKNOWN",
            quant_evidence=[],
            portfolio_state={
                "account_equity": str(ctx.account.equity),
                "positions": {
                    symbol: {
                        "quantity": str(position.quantity),
                        "avg_entry_price": str(position.avg_entry_price or 0),
                        "cost_basis": str(position.cost_basis),
                    }
                    for symbol, position in ctx.positions.items()
                },
            },
            risk_summary={
                "factor_intelligence_available": bool(factor_intelligence),
                "factor_intelligence": factor_intelligence,
            },
        )
        decision = await self.engine.decide(chief_ctx)
        if decision.action == "NO_TRADE":
            return []
        side = OrderSide.BUY if decision.action in ("LONG", "OPEN_LONG") else OrderSide.SELL
        quantity = "0.001"
        return [
            SignalIntent(
                signal_id=new_id("llm"),
                strategy_id=self.name,
                symbol=ctx.symbol,
                side=side,
                quantity=quantity,
                order_type=OrderType.MARKET,
                reason=decision.thesis[:200] or "llm_chief_trader",
                metadata={
                    "decision_id": decision.decision_id,
                    "thesis": decision.thesis[:500],
                    "model_version": decision.model_version,
                },
            )
        ]
