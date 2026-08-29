"""AI-first entry policy for the canonical PAPER runtime.

Architecture doctrine: AI-FIRST, QUANT-AS-EVIDENCE.
Quant/strategy fit, regime classification, opportunity scores, and confidence
statistics are evidence for the Chief Trader. They do not veto an otherwise
valid AI LONG/SHORT decision. Hard entry gates here are limited to real-data
availability, current-symbol anti-pyramiding, and temporal safety. RiskEngine,
ExecutionAuthority, kill switch, and exchange/account constraints remain
unchanged downstream.
"""

from __future__ import annotations

import time

from crypto_trader.domain.models import SignalIntent
from crypto_trader.llm_chief.context import ChiefTraderContext
from crypto_trader.runtime.chief_trader_strategy import ChiefTraderStrategyAdapter
from crypto_trader.strategy.base import StrategyContext


class AIFirstChiefTraderStrategyAdapter(ChiefTraderStrategyAdapter):
    """Chief Trader entry adapter where quantitative evidence is advisory."""

    version = "2.1.0"

    async def _decide(self, ctx: StrategyContext) -> list[SignalIntent]:
        chief_ctx = await self._build_context(ctx)
        evidence = chief_ctx.strategy_evidence

        # Genuine data-safety gate: AI must not invent a trade when the real
        # FactorSnapshot is unavailable or malformed.
        snapshot_id = str(
            chief_ctx.factor_snapshot.get("snapshot_id")
            or chief_ctx.factor_snapshot.get("id")
            or ""
        )
        if not snapshot_id:
            decision = self._gate_decision(
                chief_ctx,
                reason_code="FACTOR_CONTEXT_UNAVAILABLE",
                thesis=(
                    "No real FactorSnapshot available (market data insufficient "
                    "or provider failure); new entries fail closed"
                ),
            )
            await self._persist_evidence(decision, ctx, chief_ctx)
            return []

        # A usable evidence package is required, but its fit/confidence values
        # are never used here as permission thresholds.
        if not evidence.get("strategy_candidates"):
            decision = self._gate_decision(
                chief_ctx,
                reason_code="STRATEGY_EVIDENCE_UNAVAILABLE",
                thesis=(
                    "No strategy evidence package available; new entries fail "
                    "closed without AI evaluation"
                ),
            )
            await self._persist_evidence(decision, ctx, chief_ctx)
            return []

        # UNKNOWN regime is evidence, not a veto. The AI may still reason from
        # price/volume/order-flow/derivatives/strategy evidence and choose
        # LONG, SHORT, WAIT, or NO_TRADE.

        # Anti-pyramiding is scoped to the current symbol. A BTC position must
        # not prevent ETH/SOL/etc from being independently considered.
        current_position = ctx.positions.get(ctx.symbol)
        if current_position is not None and float(current_position.quantity or 0) != 0:
            decision = self._gate_decision(
                chief_ctx,
                reason_code="POSITION_ALREADY_OPEN",
                thesis=(
                    f"Entry skipped: {ctx.symbol} already has an active position; "
                    "management is handled by the runtime bridge"
                ),
            )
            await self._persist_evidence(decision, ctx, chief_ctx)
            return []

        # §10 duplicate-entry gate includes PAPER PERPETUAL state: a new
        # ChiefTrader entry can never stack on an open BTCUSDT_PERP LONG/SHORT.
        # Position management (HOLD/ADD/REDUCE/EXIT) is owned by the bridge.
        # If the perpetual state check itself fails, fail closed: unknown
        # position state must never permit pyramiding.
        if self.perpetual_position_provider is not None:
            try:
                has_perp = self.perpetual_position_provider(ctx.symbol)
                if hasattr(has_perp, "__await__"):
                    has_perp = await has_perp
                if has_perp:
                    decision = self._gate_decision(
                        chief_ctx,
                        reason_code="POSITION_ALREADY_OPEN",
                        thesis=(
                            "Entry skipped: a PAPER PERPETUAL position is already "
                            "open; management is handled by the runtime bridge"
                        ),
                    )
                    await self._persist_evidence(decision, ctx, chief_ctx)
                    return []
            except Exception:
                decision = self._gate_decision(
                    chief_ctx,
                    reason_code="PERPETUAL_STATE_UNAVAILABLE",
                    thesis=(
                        "Entry skipped: perpetual position state could not be "
                        "verified; fail closed rather than risk pyramiding"
                    ),
                )
                await self._persist_evidence(decision, ctx, chief_ctx)
                return []

        # Temporal safety remains distinct from quant judgement.
        # P1 correction: cooldown is SYMBOL-SCOPED (a trade in symbol A must
        # not preempt the decision for symbol B).
        now_monotonic = time.monotonic()
        last_entry_for_symbol = self._last_entry_initiated_at.get(ctx.symbol)
        if (
            last_entry_for_symbol is not None
            and now_monotonic - last_entry_for_symbol < self.entry_cooldown_seconds
        ):
            decision = self._gate_decision(
                chief_ctx,
                reason_code="ENTRY_COOLDOWN_ACTIVE",
                thesis=(
                    "Entry skipped: last "
                    f"{ctx.symbol} entry "
                    f"{now_monotonic - last_entry_for_symbol:.0f}s ago, "
                    f"cooldown {self.entry_cooldown_seconds:.0f}s"
                ),
            )
            await self._persist_evidence(decision, ctx, chief_ctx)
            return []

        # No pre-LLM min-fit gate and no quant-based exploration sampling.
        decision = await self.engine.decide(chief_ctx)
        decision = self._enrich_from_evidence(decision, chief_ctx)

        if decision.action in ("LONG", "SHORT"):
            decision = self._annotate_evidence_strength(decision, chief_ctx)

        signals = self._map_to_signals(decision, ctx, chief_ctx)
        if signals:
            self._last_entry_initiated_at[ctx.symbol] = now_monotonic
        await self._persist_evidence(
            decision,
            ctx,
            chief_ctx,
            execution_reference=signals[0].signal_id if signals else "",
        )
        return signals

    def _annotate_evidence_strength(self, decision, chief_ctx: ChiefTraderContext):
        """Attach weak-evidence warnings without changing the AI action."""
        fit = float(
            decision.strategy_fit_score
            or self._selected_candidate_fit(chief_ctx, decision.selected_strategy)
            or 0.0
        )
        confidence = self._confidence_of(decision)
        reason_codes = list(decision.reason_codes)

        if fit < self.min_strategy_fit and "LOW_STRATEGY_FIT_EVIDENCE" not in reason_codes:
            reason_codes.append("LOW_STRATEGY_FIT_EVIDENCE")
        if (
            confidence < self.min_trade_confidence
            and "LOW_CONFIDENCE_EVIDENCE" not in reason_codes
        ):
            reason_codes.append("LOW_CONFIDENCE_EVIDENCE")
        if str(chief_ctx.regime).upper() == "UNKNOWN" and "REGIME_UNKNOWN" not in reason_codes:
            reason_codes.append("REGIME_UNKNOWN")

        # Exploration mode may reduce PAPER size, but it does not decide
        # whether the AI is allowed to trade.
        if self.exploration_mode and (
            fit < self.normal_fit_threshold
            or confidence < self.normal_confidence_threshold
        ):
            decision_class = "EXPLORATION_ENTRY"
        else:
            decision_class = "NORMAL_ENTRY"

        return decision.model_copy(
            update={
                "strategy_fit_score": fit,
                "reason_codes": reason_codes,
                "decision_class": decision_class,
                "exploration_mode": self.exploration_mode,
                "evidence_adjusted_confidence": (
                    decision.evidence_adjusted_confidence or decision.raw_llm_confidence
                ),
            }
        )
