# ruff: noqa: E501
"""Canonical News-triggered Core-LLM reassessment seam.

A News reassessment request is a WAKE-UP ONLY. This module never builds an
order. It dispatches through the existing canonical LiveLLMPositionManager and
TradingEngine.process_signal path, preserving Risk/ExecutionAuthority and the
state-version stale-response boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.news.models import BROAD_SYMBOL, ReassessmentStatus
from crypto_trader.news.repository import NewsRepository


class NewsReassessmentService:
    def __init__(self, session_factory, *, repository: NewsRepository | None = None) -> None:
        self.session_factory = session_factory
        self.repository = repository or NewsRepository(session_factory)

    async def claim_for_symbol(
        self,
        symbol: str,
        *,
        state_version: str,
        leg_id: str | None = None,
    ) -> dict | None:
        pending = await self.repository.list_pending_reassessments(limit=50, symbol=symbol)
        for request in pending:
            if await self.repository.reassessment_exists_for_state(
                event_id=request["event_id"],
                event_version=int(request["event_version"]),
                symbol=symbol,
                state_version=state_version,
            ):
                await self.repository.finish_reassessment(
                    request["request_id"],
                    status=ReassessmentStatus.SUPPRESSED,
                    error="DUPLICATE_EVENT_VERSION_STATE",
                )
                continue
            claimed = await self.repository.claim_reassessment(
                request["request_id"], leg_id=leg_id, state_version=state_version
            )
            if claimed:
                return {**request, "leg_id": leg_id, "state_version": state_version}
        return None

    async def mark_completed(self, request_id: str) -> None:
        await self.repository.finish_reassessment(
            request_id, status=ReassessmentStatus.COMPLETED
        )

    async def mark_stale(self, request_id: str, reason: str = "STATE_VERSION_CHANGED") -> None:
        await self.repository.finish_reassessment(
            request_id, status=ReassessmentStatus.STALE, error=reason
        )

    async def mark_failed(self, request_id: str, reason: str) -> None:
        await self.repository.finish_reassessment(
            request_id, status=ReassessmentStatus.FAILED, error=reason
        )

    async def mark_flat_skipped(self, request_id: str) -> None:
        await self.repository.finish_reassessment(
            request_id, status=ReassessmentStatus.SKIPPED_FLAT, error="NO_OPEN_POSITION"
        )


class NewsReassessmentRuntime:
    """One dispatch pass per canonical engine tick. Never a separate daemon."""

    def __init__(self, service: NewsReassessmentService) -> None:
        self.service = service

    async def dispatch_due(self, engine) -> dict:
        metrics = {
            "due": 0,
            "dispatched": 0,
            "completed": 0,
            "stale": 0,
            "flat_skipped": 0,
            "suppressed": 0,
            "failed": 0,
        }
        repository = self.service.repository
        positions = await engine.portfolio.get_positions()
        pending = await repository.list_pending_reassessments(limit=20)
        metrics["due"] = len(pending)
        for request in pending:
            symbol = request.get("symbol")
            if not symbol or symbol == BROAD_SYMBOL:
                await repository.finish_reassessment(
                    request["request_id"],
                    status=ReassessmentStatus.SUPPRESSED,
                    error="BROAD_REASSESSMENT_DEFERRED",
                )
                metrics["suppressed"] += 1
                continue
            position = positions.get(symbol)
            if position is None or getattr(position, "quantity", 0) == 0:
                await self.service.mark_flat_skipped(request["request_id"])
                metrics["flat_skipped"] += 1
                continue
            plan = await engine.trade_plans.get_active_for_symbol(symbol)
            if plan is None:
                await self.service.mark_flat_skipped(request["request_id"])
                metrics["flat_skipped"] += 1
                continue
            state_version = engine._position_state_version(position, plan)
            claimed = await self.service.claim_for_symbol(
                symbol, state_version=state_version, leg_id=getattr(plan, "trade_plan_id", None)
            )
            if claimed is None:
                metrics["suppressed"] += 1
                continue
            try:
                ctx = await engine._strategy_context(symbol)
                if ctx is None:
                    await self.service.mark_failed(claimed["request_id"], "NO_FRESH_MARKET_CONTEXT")
                    metrics["failed"] += 1
                    continue
                signal = await engine.position_manager.review(ctx, position, force=True)
                if signal is not None:
                    await engine.process_signal(signal)
                refreshed_positions = await engine.portfolio.get_positions()
                refreshed = refreshed_positions.get(symbol)
                if refreshed is None or engine._position_state_version(refreshed, plan) != state_version:
                    await self.service.mark_stale(claimed["request_id"])
                    metrics["stale"] += 1
                else:
                    await self.service.mark_completed(claimed["request_id"])
                    metrics["completed"] += 1
            except Exception as exc:
                await self.service.mark_failed(claimed["request_id"], f"{type(exc).__name__}: {exc}")
                metrics["failed"] += 1
            metrics["dispatched"] += 1
        return metrics


def utcnow() -> datetime:
    return datetime.now(UTC)
