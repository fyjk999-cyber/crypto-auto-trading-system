"""Canonical LLM Chief Trader entry strategy adapter.

MultiStrategyAlpha remains a shadow/benchmark evidence provider. This adapter is
the canonical entry decision path: it builds ChiefTraderContext, invokes
ChiefTraderEngine, and maps LONG/SHORT to SignalIntent. NO_TRADE submits nothing.
Every completed decision (including NO_TRADE) is persisted as DecisionEvidence
when an evidence backend is wired, so the decision chain stays auditable.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from crypto_trader.domain.enums import OrderSide, OrderType
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import SignalIntent
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMProvider
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin


class ChiefTraderStrategyAdapter(StrategyPlugin):
    name = "llm_chief_trader"
    version = "1.1.0"

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        factor_intelligence_provider=None,
        min_decision_interval_seconds: float = 60.0,
        evidence_backend=None,
    ) -> None:
        self.provider = provider
        self.engine = ChiefTraderEngine(provider=provider)
        self.factor_intelligence_provider = factor_intelligence_provider
        self.evidence_backend = evidence_backend
        # Entry-path invocation bound: market data ticks arrive far more often
        # than a Chief Trader decision is needed. Existing-position safety
        # (reduce/exit/stop) does NOT depend on this interval: it lives in the
        # independent runtime bridge.
        self.min_decision_interval_seconds = max(min_decision_interval_seconds, 0.0)
        self._last_decision_completed_at: float | None = None

    async def on_market_data(self, ctx: StrategyContext) -> list[SignalIntent]:
        # An unconfigured/degraded shared gateway must not create repeated
        # provider invocations. Existing-position safety remains owned by the
        # independent runtime bridge, risk engine, and execution authority.
        if self.provider is None or not self.provider.healthy():
            return []
        if not getattr(self.provider, "route_ready", lambda: True)():
            return []
        now = time.monotonic()
        if (
            self._last_decision_completed_at is not None
            and now - self._last_decision_completed_at < self.min_decision_interval_seconds
        ):
            return []
        try:
            return await self._decide(ctx)
        finally:
            self._last_decision_completed_at = time.monotonic()

    async def _decide(self, ctx: StrategyContext) -> list[SignalIntent]:
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
        await self._persist_evidence(decision, ctx, chief_ctx)
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
                    "domain_model_version": getattr(self.provider, "domain_model_version", ""),
                    "llm_invocation_id": decision.llm_invocation_id,
                },
            )
        ]

    async def _persist_evidence(
        self, decision, ctx: StrategyContext, chief_ctx: ChiefTraderContext
    ) -> None:
        """Persist every completed decision as DecisionEvidence (best-effort).

        Evidence failure must never block or alter trading; failures are
        swallowed because the decision itself has already been taken.
        """
        if self.evidence_backend is None:
            return
        now = datetime.now(UTC).isoformat()
        evidence = {
            "decision_id": decision.decision_id,
            "timestamp_utc": now,
            "symbol": ctx.symbol,
            "timeframe": "runtime",
            "strategy_id": self.name,
            "strategy_version": self.version,
            "model_version": decision.model_version,
            "prompt_version": "chief-prompt-v1",
            "factor_snapshot_id": "",
            "factor_set_version": "factorset-v1",
            "factor_profile": "FULL",
            "market_data_reference": f"tick:{ctx.symbol}@{ctx.clock_time.isoformat()}",
            "analysis_evidence": {
                "llm_invocation_id": decision.llm_invocation_id,
                "provider": getattr(self.provider, "name", ""),
                "domain_model_version": getattr(self.provider, "domain_model_version", ""),
                "market_regime": decision.market_regime,
                "raw_confidence": decision.raw_llm_confidence,
            },
            "decision": decision.model_dump(mode="json"),
            "risk_decision": {
                "status": "PENDING",
                "note": "NO_TRADE decisions are never submitted to RiskEngine",
            },
            "execution_intent_reference": "",
            "created_at_utc": now,
        }
        try:
            await self.evidence_backend.store_decision(evidence)
        except Exception:
            return
