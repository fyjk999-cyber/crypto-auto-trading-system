"""Database persistence for non-secret LLM configuration and safe usage metadata."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import case, delete, func, select

from crypto_trader.llm_runtime.contracts import ModelRoute, ProviderConfig
from crypto_trader.persistence.models import LLMProviderORM, LLMRouteORM, LLMUsageORM


class LLMRepository:
    def __init__(self, session_factory) -> None:
        self.session_factory = session_factory

    async def upsert_provider(self, config: ProviderConfig) -> ProviderConfig:
        async with self.session_factory() as session:
            row = await session.get(LLMProviderORM, config.provider_id)
            values = config.model_dump()
            if row is None:
                session.add(LLMProviderORM(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.updated_at = datetime.now(UTC)
            await session.commit()
        return config

    async def get_provider(self, provider_id: str) -> ProviderConfig | None:
        async with self.session_factory() as session:
            row = await session.get(LLMProviderORM, provider_id)
            return self._provider(row) if row else None

    async def list_providers(self) -> list[ProviderConfig]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(LLMProviderORM))).scalars().all()
            return [self._provider(row) for row in rows]

    async def delete_provider(self, provider_id: str) -> None:
        async with self.session_factory() as session:
            await session.execute(delete(LLMRouteORM).where(LLMRouteORM.provider_id == provider_id))
            await session.execute(
                delete(LLMProviderORM).where(LLMProviderORM.provider_id == provider_id)
            )
            await session.commit()

    async def replace_routes(self, routes: list[ModelRoute]) -> list[ModelRoute]:
        async with self.session_factory() as session:
            for route in routes:
                row = await session.get(LLMRouteORM, route.route_name)
                values = route.model_dump()
                if row is None:
                    session.add(LLMRouteORM(**values))
                else:
                    for key, value in values.items():
                        setattr(row, key, value)
                    row.updated_at = datetime.now(UTC)
            await session.commit()
        return routes

    async def list_routes(self) -> list[ModelRoute]:
        async with self.session_factory() as session:
            rows = (await session.execute(select(LLMRouteORM))).scalars().all()
            return [
                ModelRoute(
                    route_name=row.route_name,
                    provider_id=row.provider_id,
                    model_name=row.model_name,
                    enabled=row.enabled,
                    temperature=row.temperature,
                    max_tokens=row.max_tokens,
                    timeout_seconds=row.timeout_seconds,
                )
                for row in rows
            ]

    async def record_usage(self, values: dict) -> None:
        async with self.session_factory() as session:
            session.add(LLMUsageORM(**values))
            await session.commit()

    async def usage_today(self) -> dict:
        today = datetime.now(UTC).date()
        start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(
                        func.count(LLMUsageORM.invocation_id),
                        func.coalesce(func.sum(LLMUsageORM.total_tokens), 0),
                        func.coalesce(
                            func.sum(case((LLMUsageORM.success.is_(False), 1), else_=0)),
                            0,
                        ),
                        func.coalesce(func.avg(LLMUsageORM.latency_ms), 0.0),
                    ).where(LLMUsageORM.timestamp >= start)
                )
            ).one()
        return {
            "today_calls": int(row[0] or 0),
            "today_tokens": int(row[1] or 0),
            "failed_calls": int(row[2] or 0),
            "average_latency_ms": round(float(row[3] or 0.0), 2),
        }

    @staticmethod
    def _provider(row: LLMProviderORM) -> ProviderConfig:
        return ProviderConfig(
            provider_id=row.provider_id,
            provider_type=row.provider_type,
            display_name=row.display_name,
            base_url=row.base_url,
            api_key_secret_ref=row.api_key_secret_ref,
            default_model=row.default_model,
            enabled=row.enabled,
            timeout_seconds=row.timeout_seconds,
            max_retries=row.max_retries,
        )
