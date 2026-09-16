# Event-level factual lifecycle counterfactual reviews (LEARNING_ONLY).
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import GrowthEventReviewORM

REVIEW_VERSION = "review-v1"
PROVENANCE_LABEL = "COUNTERFACTUAL_NOT_FACTUAL_EXECUTION"
ADD_REVIEW = "ADD_REVIEW"
HEDGE_REVIEW = "HEDGE_REVIEW"
EXIT_MODIFICATION_REVIEW = "EXIT_MODIFICATION_REVIEW"
FAST_PROFIT_REVIEW = "FAST_PROFIT_REVIEW"
REENTRY_REVIEW = "REENTRY_REVIEW"
RISK_REVIEW = "RISK_REVIEW"
LLM_INVOCATION_REVIEW = "LLM_INVOCATION_REVIEW"
REVIEW_TYPES = (
    ADD_REVIEW,
    HEDGE_REVIEW,
    EXIT_MODIFICATION_REVIEW,
    FAST_PROFIT_REVIEW,
    REENTRY_REVIEW,
    RISK_REVIEW,
    LLM_INVOCATION_REVIEW,
)

EVENT_KIND_TO_REVIEW = {
    "ADD": ADD_REVIEW,
    "ADDED": ADD_REVIEW,
    "HEDGE": HEDGE_REVIEW,
    "HEDGE_OPENED": HEDGE_REVIEW,
    "BASE_EXIT_MODIFIED": EXIT_MODIFICATION_REVIEW,
    "EXIT_MODIFICATION": EXIT_MODIFICATION_REVIEW,
    "FAST_PROFIT": FAST_PROFIT_REVIEW,
    "FAST_PROFIT_EXIT": FAST_PROFIT_REVIEW,
    "REENTRY": REENTRY_REVIEW,
    "RE_ENTRY": REENTRY_REVIEW,
    "RISK_L1": RISK_REVIEW,
    "RISK_L2": RISK_REVIEW,
    "RISK_HARD_EXIT": RISK_REVIEW,
    "OFFLINE_EXIT": RISK_REVIEW,
    "LLM_DECISION": LLM_INVOCATION_REVIEW,
    "LLM_INVOCATION": LLM_INVOCATION_REVIEW,
}


def counterfactual_definition(review_type: str) -> dict:
    definitions = {
        ADD_REVIEW: "original exposure without the ADD, same factual path",
        HEDGE_REVIEW: "hold original, close original, and close plus independent reverse",
        EXIT_MODIFICATION_REVIEW: "previous active Base Exit on the factual post-modification path",
        FAST_PROFIT_REVIEW: "original Base/no-fast exit and alternate partial fractions",
        REENTRY_REVIEW: "remaining flat instead of re-entering",
        RISK_REVIEW: "pre-action factual window versus post-action window",
        LLM_INVOCATION_REVIEW: "prior plan state without the invocation",
    }
    return {"definition": definitions.get(review_type, "unknown"), "provenance": PROVENANCE_LABEL}


class LifecycleReviewEngine:
    authority = "LEARNING_ONLY"
    is_order = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def ingest_events(
        self,
        episode_id: str,
        events: list[dict],
        *,
        decision_id: str | None = None,
        trade_plan_id: str | None = None,
        source_refs: dict | None = None,
    ) -> int:
        created = 0
        async with self._session_factory() as session:
            existing = {
                (row[0], row[1], row[2], row[3])
                for row in (
                    await session.execute(
                        select(
                            GrowthEventReviewORM.episode_id,
                            GrowthEventReviewORM.source_event_id,
                            GrowthEventReviewORM.review_type,
                            GrowthEventReviewORM.review_version,
                        )
                    )
                ).all()
            }
            for event in events:
                source_event_id = str(event.get("event_id") or event.get("id") or "")
                kind = str(event.get("kind") or event.get("event_kind") or "").upper()
                review_type = EVENT_KIND_TO_REVIEW.get(kind)
                if not source_event_id or review_type is None:
                    continue
                identity = (episode_id, source_event_id, review_type, REVIEW_VERSION)
                if identity in existing:
                    continue
                session.add(
                    GrowthEventReviewORM(
                        review_id=new_id("rev"),
                        episode_id=episode_id,
                        source_event_id=source_event_id,
                        decision_id=decision_id,
                        trade_plan_id=trade_plan_id,
                        review_type=review_type,
                        review_version=REVIEW_VERSION,
                        status="PENDING",
                        actual_json={"event": event},
                        counterfactual_json=counterfactual_definition(review_type),
                        source_refs_json=source_refs or {},
                        authority="LEARNING_ONLY",
                        is_order=False,
                    )
                )
                existing.add(identity)
                created += 1
            await session.commit()
        return created

    async def mature(
        self,
        review_id: str,
        *,
        actual_net_bps: float,
        counterfactual_net_bps: float,
        verdict: str,
        confidence: float,
        mfe_bps: float | None = None,
        mae_bps: float | None = None,
        cost_bps: float | None = None,
        fees: float | None = None,
        slippage_bps: float | None = None,
        funding_bps: float | None = None,
        maturity_horizon: str | None = None,
    ) -> dict | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(GrowthEventReviewORM).where(GrowthEventReviewORM.review_id == review_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.status == "MATURE":
                return self._as_dict(row)
            row.actual_net_bps = float(actual_net_bps)
            row.counterfactual_net_bps = float(counterfactual_net_bps)
            row.delta_bps = float(actual_net_bps) - float(counterfactual_net_bps)
            row.mfe_bps = mfe_bps
            row.mae_bps = mae_bps
            row.cost_bps = cost_bps
            row.fees = fees
            row.slippage_bps = slippage_bps
            row.funding_bps = funding_bps
            row.maturity_horizon = maturity_horizon
            row.verdict = verdict
            row.confidence = float(confidence)
            row.status = "MATURE"
            row.matured_at = datetime.now(UTC)
            row.updated_at = datetime.now(UTC)
            await session.commit()
            return self._as_dict(row)

    @staticmethod
    def _as_dict(row: GrowthEventReviewORM) -> dict:
        return {
            "review_id": row.review_id,
            "episode_id": row.episode_id,
            "source_event_id": row.source_event_id,
            "decision_id": row.decision_id,
            "trade_plan_id": row.trade_plan_id,
            "review_type": row.review_type,
            "review_version": row.review_version,
            "status": row.status,
            "actual_json": row.actual_json,
            "counterfactual_json": row.counterfactual_json,
            "actual_net_bps": row.actual_net_bps,
            "counterfactual_net_bps": row.counterfactual_net_bps,
            "delta_bps": row.delta_bps,
            "mfe_bps": row.mfe_bps,
            "mae_bps": row.mae_bps,
            "cost_bps": row.cost_bps,
            "fees": row.fees,
            "slippage_bps": row.slippage_bps,
            "funding_bps": row.funding_bps,
            "maturity_horizon": row.maturity_horizon,
            "verdict": row.verdict,
            "confidence": row.confidence,
            "source_refs_json": row.source_refs_json,
            "authority": "LEARNING_ONLY",
            "is_order": False,
        }

    async def mark_inconclusive(self, review_id: str, reason: str) -> dict | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(GrowthEventReviewORM).where(GrowthEventReviewORM.review_id == review_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            if row.status != "MATURE":
                row.status = "INCONCLUSIVE"
                row.verdict = reason
                row.updated_at = datetime.now(UTC)
                await session.commit()
            return self._as_dict(row)

    async def resolve_maturity(self, review_id: str, facts: dict) -> dict | None:
        """Mature only with explicit factual inputs; otherwise INCONCLUSIVE."""
        actual = facts.get("actual_net_bps")
        counter = facts.get("counterfactual_net_bps")
        if actual is None or counter is None:
            return await self.mark_inconclusive(review_id, "INSUFFICIENT_FACTUAL_INPUTS")
        delta = float(actual) - float(counter)
        verdict = "HELPFUL" if delta > 0 else ("HARMFUL" if delta < 0 else "NEUTRAL")
        return await self.mature(
            review_id,
            actual_net_bps=float(actual),
            counterfactual_net_bps=float(counter),
            verdict=verdict,
            confidence=float(facts.get("confidence", 0.5)),
            mfe_bps=facts.get("mfe_bps"),
            mae_bps=facts.get("mae_bps"),
            cost_bps=facts.get("cost_bps"),
            fees=facts.get("fees"),
            slippage_bps=facts.get("slippage_bps"),
            funding_bps=facts.get("funding_bps"),
            maturity_horizon=facts.get("maturity_horizon"),
        )

    async def list_reviews(
        self, *, episode_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[dict]:
        query = select(GrowthEventReviewORM)
        if episode_id:
            query = query.where(GrowthEventReviewORM.episode_id == episode_id)
        if status:
            query = query.where(GrowthEventReviewORM.status == status)
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        query.order_by(GrowthEventReviewORM.created_at.desc()).limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [self._as_dict(row) for row in rows]

    async def pending(self, limit: int = 100) -> list[dict]:
        return await self.list_reviews(status="PENDING", limit=limit)
