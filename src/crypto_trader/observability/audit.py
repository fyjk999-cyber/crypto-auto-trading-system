"""Structured audit trail persisted to audit_events."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from crypto_trader.domain.identifiers import new_id
from crypto_trader.persistence.models import AuditEventORM


class AuditService:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def log(
        self,
        action: str,
        *,
        target: str = "",
        actor: str = "engine",
        run_id: str | None = None,
        order_id: str | None = None,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        event_id: str | None = None,
    ) -> str:
        audit_event_id = new_id("audit")
        event_id = event_id or new_id("evt")
        async with self.session_factory() as session:
            session.add(
                AuditEventORM(
                    audit_event_id=audit_event_id,
                    event_id=event_id,
                    run_id=run_id,
                    action=action,
                    actor=actor,
                    target=target,
                    order_id=order_id,
                    client_order_id=client_order_id,
                    exchange_order_id=exchange_order_id,
                    before_json=before or {},
                    after_json=after or {},
                    timestamp=datetime.now(UTC),
                )
            )
            await session.commit()
        return audit_event_id

    async def list_recent(self, limit: int = 50):
        from sqlalchemy import select

        from crypto_trader.persistence.models import AuditEventORM as ORM

        async with self.session_factory() as session:
            rows = (
                (await session.execute(select(ORM).order_by(ORM.id.desc()).limit(limit)))
                .scalars()
                .all()
            )
            return [row for row in rows]
