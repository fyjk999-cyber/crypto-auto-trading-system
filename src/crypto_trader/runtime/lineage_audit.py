"""Factual-fill lineage coverage audit (Phase 6 recovery guard).

Recovery/ops must be able to prove that every persisted factual fill carries the
identity links required by the SPEC lineage:

    ClientOrderID -> ExchangeOrderID -> FillID

A fill missing those links is an UNTRACKED_FACTUAL_FILL risk (it could be
followed by blind retries or ghost positions), so it is surfaced explicitly.

Read-only audit: never mutates, never submits an order.
"""

from __future__ import annotations

from sqlalchemy import or_, select

from crypto_trader.persistence.models import FillORM

UNTRACKED_FACTUAL_FILL = "UNTRACKED_FACTUAL_FILL"


def fill_lineage_issues(
    *,
    fill_id: str | None,
    client_order_id: str | None,
    exchange_order_id: str | None,
) -> list[str]:
    issues: list[str] = []
    if not fill_id:
        issues.append("MISSING_FILL_ID")
    if not client_order_id:
        issues.append("MISSING_CLIENT_ORDER_ID")
    if not exchange_order_id:
        issues.append("MISSING_EXCHANGE_ORDER_ID")
    return issues


class LineageCoverageAuditor:
    authority = "RECONCILIATION_ONLY"
    is_order = False

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    async def audit(self, *, limit: int = 500) -> dict:
        async with self._session_factory() as session:
            rows = (
                (await session.execute(select(FillORM).order_by(FillORM.id.desc()).limit(limit)))
                .scalars()
                .all()
            )
        untracked = []
        for row in rows:
            issues = fill_lineage_issues(
                fill_id=row.fill_id,
                client_order_id=row.client_order_id,
                exchange_order_id=row.exchange_order_id,
            )
            if issues:
                untracked.append(
                    {
                        "fill_id": row.fill_id,
                        "symbol": row.symbol,
                        "client_order_id": row.client_order_id,
                        "exchange_order_id": row.exchange_order_id,
                        "issues": issues,
                    }
                )
        return {
            "fill_count": len(rows),
            "untracked_count": len(untracked),
            "untracked": untracked[:20],
            "ok": not untracked,
            "flag": UNTRACKED_FACTUAL_FILL if untracked else None,
            "authority": self.authority,
            "is_order": False,
        }


def untracked_fill_filter():
    """SQL filter selecting fills with broken identity lineage."""
    return or_(
        FillORM.client_order_id.is_(None),
        FillORM.client_order_id == "",
        FillORM.exchange_order_id.is_(None),
        FillORM.exchange_order_id == "",
    )
