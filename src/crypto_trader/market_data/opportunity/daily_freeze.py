"""Growth V2 daily TOP-10 freeze (Phase 5).

SPEC: every day freeze the TOP-10 opportunities regardless of whether they were
traded. Selection uses only information available at freeze time and the frozen
rows never change afterwards (no hindsight re-selection).

This service is LEARNING/OBSERVABILITY ONLY: it never submits an order and
never influences Risk or Execution.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from crypto_trader.persistence.models import DailyOpportunityTop10ORM

TOP_N = 10


class DailyOpportunityFreezer:
    label = "DAILY_OPPORTUNITY_TOP10"
    authority = "LEARNING_ONLY"
    is_order = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def freeze(
        self,
        trading_day: str,
        candidates: list[dict],
        *,
        frozen_at: datetime | None = None,
    ) -> dict:
        """Freeze the decision-time Top-10 for ``trading_day`` (idempotent).

        Ordering uses only the ``score`` observed now; the first freeze wins and
        later calls return the original list unchanged.
        """
        existing = await self.get(trading_day)
        if existing:
            return {
                "trading_day": trading_day,
                "frozen": True,
                "already_frozen": True,
                "entries": existing,
                "authority": self.authority,
                "not_an_order": True,
            }
        ranked = sorted(
            candidates,
            key=lambda item: (-float(item.get("score") or 0.0), str(item.get("symbol") or "")),
        )[:TOP_N]
        moment = frozen_at or datetime.now(UTC)
        async with self._session_factory() as session:
            for rank, candidate in enumerate(ranked, start=1):
                session.add(
                    DailyOpportunityTop10ORM(
                        trading_day=trading_day,
                        rank=rank,
                        symbol=str(candidate.get("symbol") or ""),
                        score=float(candidate.get("score") or 0.0),
                        candidate_source=str(candidate.get("candidate_source") or ""),
                        factor_evidence_json=list(candidate.get("factor_evidence") or []),
                        frozen_at=moment,
                    )
                )
            await session.commit()
        return {
            "trading_day": trading_day,
            "frozen": True,
            "already_frozen": False,
            "entries": await self.get(trading_day),
            "authority": self.authority,
            "not_an_order": True,
        }

    async def get(self, trading_day: str) -> list[dict]:
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(DailyOpportunityTop10ORM)
                        .where(DailyOpportunityTop10ORM.trading_day == trading_day)
                        .order_by(DailyOpportunityTop10ORM.rank.asc())
                    )
                )
                .scalars()
                .all()
            )
        return [
            {
                "rank": row.rank,
                "symbol": row.symbol,
                "score": row.score,
                "candidate_source": row.candidate_source,
                "factor_evidence": row.factor_evidence_json or [],
                "frozen_at": row.frozen_at.isoformat() if row.frozen_at else None,
            }
            for row in rows
        ]
