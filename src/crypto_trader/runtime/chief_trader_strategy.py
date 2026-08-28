"""Canonical LLM Chief Trader entry strategy adapter.

Decision philosophy: STRATEGY SELECTION + EVIDENCE WEIGHTING, not an
all-conditions AND gate. A StrategyEvidencePackage (five canonical strategies,
regime-adjusted fit scores, supporting/contradicting factors) is built from
real market data and handed to CryptoTrader-Live, which selects the dominant
strategy. Contradicting factors reduce confidence; they do not veto.

HARD GATES (may block): kill switch, market-data health, min strategy fit,
min evidence-adjusted confidence, RiskEngine, ExecutionAuthority.
SOFT EVIDENCE (never a veto): trend/momentum/breakout/mean-reversion/volume/
orderflow/funding/OI/volatility/liquidation factors.

Entry vocabulary only: LONG/SHORT/NO_TRADE/WAIT. Position management
(ADD/REDUCE/EXIT/HOLD) is owned by the independent runtime bridge; those
actions never map to an entry signal. Unknown actions fail closed.

Every completed decision (including NO_TRADE/WAIT) is persisted as
DecisionEvidence with full lineage: factor_snapshot_id, factor_set_version,
market_regime, selected_strategy, llm_invocation_id, domain model version.
Persistence is best-effort and instrumented; failures are logged, never silent.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from crypto_trader.domain.enums import OrderSide, OrderType
from crypto_trader.domain.identifiers import new_id
from crypto_trader.domain.models import SignalIntent
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.llm_chief.engine import ChiefTraderEngine
from crypto_trader.llm_chief.provider import LLMProvider
from crypto_trader.strategy.base import StrategyContext, StrategyPlugin

logger = logging.getLogger("crypto_trader.chief_trader")

# Exhaustive entry mapping. Anything not listed produces NO signal (fail
# closed). WAIT/NO_TRADE and position-management actions never become orders.
_LONG_ACTIONS = {"LONG", "OPEN_LONG"}
_SHORT_ACTIONS = {"SHORT", "OPEN_SHORT"}
_NO_SIGNAL_ACTIONS = {
    "NO_TRADE", "WAIT", "ADD", "REDUCE", "EXIT", "HOLD", "HEDGE", "CLOSE",
}


class ChiefTraderStrategyAdapter(StrategyPlugin):
    name = "llm_chief_trader"
    version = "2.0.0"

    def __init__(
        self,
        *,
        provider: LLMProvider | None = None,
        factor_intelligence_provider=None,
        min_decision_interval_seconds: float = 60.0,
        evidence_backend=None,
        decision_context_provider=None,
        min_strategy_fit: float = 0.45,
        min_trade_confidence: float = 0.55,
    ) -> None:
        self.provider = provider
        self.engine = ChiefTraderEngine(provider=provider)
        self.factor_intelligence_provider = factor_intelligence_provider
        self.evidence_backend = evidence_backend
        self.decision_context_provider = decision_context_provider
        # §20 configurable PAPER-only decision gates. Defaults are conservative
        # without requiring unanimity: 0.45 fit = the best regime-adjusted
        # candidate must clear noise-level confidence; 0.55 = the LLM's
        # evidence-adjusted confidence must exceed coin-flip before an entry
        # reaches RiskEngine. Never tuned to manufacture trades.
        self.min_strategy_fit = min_strategy_fit
        self.min_trade_confidence = min_trade_confidence
        self.evidence_persist_failures = 0
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

    async def _build_context(self, ctx: StrategyContext) -> ChiefTraderContext:
        factor_intelligence = {}
        if self.factor_intelligence_provider is not None:
            try:
                factor_intelligence = await self.factor_intelligence_provider(ctx.symbol)
            except Exception:
                factor_intelligence = {}
        bundle = None
        if self.decision_context_provider is not None:
            market_data = {
                "funding_rate": str(ctx.funding) if ctx.funding is not None else None,
                "open_interest": str(ctx.oi) if ctx.oi is not None else None,
            }
            try:
                bundle = await self.decision_context_provider.build(market_data)
            except Exception as exc:
                logger.warning(
                    "LIVE_DECISION_CONTEXT_UNAVAILABLE symbol=%s error=%s",
                    ctx.symbol,
                    type(exc).__name__,
                )
                bundle = None
        evidence = bundle.evidence if bundle is not None else {}
        regime = str(evidence.get("market_regime") or "UNKNOWN")
        champion_release = {
            "strategy_version": self.version,
            "entry_strategy": self.name,
            "factor_set_version": bundle.factor_set_version if bundle else "",
            "domain_model_version": getattr(self.provider, "domain_model_version", ""),
            "note": "running PAPER release versions (no promoted override)",
        }
        return ChiefTraderContext(
            symbol=ctx.symbol,
            market_snapshot={
                "symbol": ctx.symbol,
                "clock_time": ctx.clock_time.isoformat(),
                "mark_price": str(ctx.mark_price) if ctx.mark_price is not None else None,
                "funding": str(ctx.funding) if ctx.funding is not None else None,
                "oi": str(ctx.oi) if ctx.oi is not None else None,
            },
            regime=regime,
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
            strategy_evidence=evidence,
            factor_snapshot=bundle.factor_snapshot if bundle is not None else {},
            champion_release=champion_release,
        )

    async def _decide(self, ctx: StrategyContext) -> list[SignalIntent]:
        chief_ctx = await self._build_context(ctx)
        evidence = chief_ctx.strategy_evidence

        # HARD GATE (PAPER, configurable): no strategy currently carries a
        # regime-adjusted fit above the minimum edge. The LLM is not invoked;
        # the decision is recorded honestly as NO_TRADE. Only applies when a
        # real evidence package exists; without one the LLM judges as before.
        evidence_present = bool(evidence.get("strategy_candidates"))
        candidates = [
            c for c in (evidence.get("strategy_candidates") or [])
            if c.get("direction") in ("LONG", "SHORT")
        ]
        if evidence_present:
            best = (
                max(candidates, key=lambda c: float(c.get("fit_score", 0)))
                if candidates
                else None
            )
            best_fit = float(best.get("fit_score", 0)) if best is not None else 0.0
            if best_fit < self.min_strategy_fit:
                decision = self._gate_decision(
                    chief_ctx,
                    reason_code="INSUFFICIENT_STRATEGY_EDGE",
                    thesis=(
                        (
                            f"Best strategy {best.get('strategy_id')} fit "
                            f"{best.get('fit_score')} below minimum "
                            f"{self.min_strategy_fit}"
                        )
                        if best is not None
                        else "No directional strategy candidate fits the current market"
                    ),
                    selected_strategy=str(best.get("strategy_id", "")) if best else "",
                    fit_score=best_fit,
                )
                await self._persist_evidence(decision, ctx, chief_ctx)
                return []

        decision = await self.engine.decide(chief_ctx)
        decision = self._enrich_from_evidence(decision, chief_ctx)

        # HARD GATE (PAPER, configurable): the LLM proposes an entry, but its
        # evidence-adjusted confidence does not clear the minimum. Fail closed.
        if decision.action in ("LONG", "SHORT"):
            if (
                decision.evidence_adjusted_confidence
                and decision.evidence_adjusted_confidence < self.min_trade_confidence
            ):
                decision = decision.model_copy(
                    update={
                        "action": "NO_TRADE",
                        "reason_codes": list(decision.reason_codes)
                        + ["INSUFFICIENT_EVIDENCE_ADJUSTED_CONFIDENCE"],
                    }
                )
            else:
                selected = next(
                    (
                        c
                        for c in candidates
                        if c.get("strategy_id") == decision.selected_strategy
                    ),
                    None,
                )
                if selected is not None and not decision.strategy_fit_score:
                    decision = decision.model_copy(
                        update={
                            "strategy_fit_score": float(selected.get("fit_score", 0.0)),
                            "strategy_version": selected.get("strategy_version", ""),
                        }
                    )

        await self._persist_evidence(decision, ctx, chief_ctx)
        return self._map_to_signals(decision, ctx, chief_ctx)

    def _enrich_from_evidence(self, decision, chief_ctx: ChiefTraderContext):
        """Fill lineage + attribution fields the LLM may have left empty."""
        snapshot = chief_ctx.factor_snapshot or {}
        candidates = [
            c for c in (chief_ctx.strategy_evidence or {}).get("strategy_candidates") or []
            if c.get("direction") in ("LONG", "SHORT")
        ]
        selected = next(
            (c for c in candidates if c.get("strategy_id") == decision.selected_strategy),
            None,
        )
        updates: dict = {
            "factor_snapshot_id": decision.factor_snapshot_id
            or str(snapshot.get("snapshot_id", "")),
            "factor_set_version": decision.factor_set_version
            or str(snapshot.get("factor_set_version", "")),
            "market_regime": decision.market_regime
            if decision.market_regime not in ("", "UNKNOWN")
            else chief_ctx.regime,
        }
        if selected is not None:
            updates.setdefault("strategy_version", "")  # keep LLM value if set
            if not decision.strategy_version:
                updates["strategy_version"] = str(selected.get("strategy_version", ""))
            if not decision.supporting_factors:
                updates["supporting_factors"] = list(selected.get("supporting_factors", []))
            if not decision.contradicting_factors:
                updates["contradicting_factors"] = list(
                    selected.get("contradicting_factors", [])
                )
        if not decision.dominant_factor:
            dominant = (chief_ctx.strategy_evidence or {}).get("dominant_factors") or []
            if dominant:
                updates["dominant_factor"] = str(dominant[0])
        return decision.model_copy(update=updates)

    def _gate_decision(
        self, chief_ctx: ChiefTraderContext, *, reason_code: str, thesis: str,
        selected_strategy: str, fit_score: float,
    ):
        from crypto_trader.llm_chief.decision import ChiefTraderDecision

        return ChiefTraderDecision(
            decision_id=f"gate_{datetime.now(UTC).timestamp()}",
            symbol=chief_ctx.symbol,
            action="NO_TRADE",
            market_regime=chief_ctx.regime,
            thesis=thesis,
            reason_codes=[reason_code],
            selected_strategy=selected_strategy,
            strategy_fit_score=fit_score,
            model_version=self.engine.model_version,
            created_at=datetime.now(UTC).isoformat(),
        )

    def _map_to_signals(
        self, decision, ctx: StrategyContext, chief_ctx: ChiefTraderContext
    ) -> list[SignalIntent]:
        """Exhaustive entry mapping. Unknown/management actions -> no signal."""
        action = decision.action.upper()
        if action in _LONG_ACTIONS:
            side = OrderSide.BUY
        elif action in _SHORT_ACTIONS:
            side = OrderSide.SELL
        elif action in _NO_SIGNAL_ACTIONS:
            return []
        else:
            # Fail closed: never let an unrecognized action become a trade.
            logger.warning(
                "UNRECOGNIZED_ENTRY_ACTION_FAIL_CLOSED action=%s decision_id=%s",
                decision.action,
                decision.decision_id,
            )
            return []
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
                    "selected_strategy": decision.selected_strategy,
                    "strategy_fit_score": str(decision.strategy_fit_score),
                    "market_regime": decision.market_regime,
                    "factor_snapshot_id": decision.factor_snapshot_id,
                    "raw_llm_confidence": str(decision.raw_llm_confidence),
                    "evidence_adjusted_confidence": str(
                        decision.evidence_adjusted_confidence
                    ),
                },
            )
        ]

    async def _persist_evidence(
        self, decision, ctx: StrategyContext, chief_ctx: ChiefTraderContext
    ) -> None:
        """Persist every completed decision as DecisionEvidence (best-effort).

        Evidence failure must never block or alter trading, but it is never
        silent: a structured warning with the failure count is emitted.
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
            "prompt_version": "chief-prompt-v2-strategy-fit",
            "factor_snapshot_id": decision.factor_snapshot_id
            or str(chief_ctx.factor_snapshot.get("snapshot_id", "")),
            "factor_set_version": decision.factor_set_version
            or str(chief_ctx.factor_snapshot.get("factor_set_version", "")),
            "factor_profile": "FULL",
            "market_data_reference": f"tick:{ctx.symbol}@{ctx.clock_time.isoformat()}",
            "analysis_evidence": {
                "llm_invocation_id": decision.llm_invocation_id,
                "provider": getattr(self.provider, "name", ""),
                "domain_model_version": getattr(self.provider, "domain_model_version", ""),
                "market_regime": decision.market_regime,
                "raw_confidence": decision.raw_llm_confidence,
                "selected_strategy": decision.selected_strategy,
                "strategy_version": decision.strategy_version,
                "strategy_fit_score": decision.strategy_fit_score,
                "secondary_strategies": decision.secondary_strategies,
                "supporting_factors": decision.supporting_factors,
                "contradicting_factors": decision.contradicting_factors,
                "dominant_factor": decision.dominant_factor,
                "evidence_adjusted_confidence": decision.evidence_adjusted_confidence,
                "position_size_request": decision.position_size_request,
                "leverage_request": decision.leverage_request,
                "strategy_candidates": (
                    chief_ctx.strategy_evidence or {}
                ).get("strategy_candidates", []),
                "risk_flags": (chief_ctx.strategy_evidence or {}).get("risk_flags", []),
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
        except Exception as exc:
            self.evidence_persist_failures += 1
            logger.warning(
                "DECISION_EVIDENCE_PERSIST_FAILED decision_id=%s failures=%d "
                "error=%s",
                decision.decision_id,
                self.evidence_persist_failures,
                type(exc).__name__,
            )
