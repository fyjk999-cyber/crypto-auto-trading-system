# Canonical Growth SQL retriever with strict as-of version history.
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from crypto_trader.persistence.models import GrowthMemoryVersionORM

RETRIEVAL_VERSION = "retrieval-v1"
SEARCH_TYPES = (
    "REGIME_PATTERN",
    "GENERALIZED_KNOWLEDGE",
    "COIN_PROFILE",
    "COMPRESSED_PATTERN",
    "VALIDATED_COMPRESSED_KNOWLEDGE",
    "FAST_EXPERIENCE",
    "REVIEWED_EPISODE",
)
_TIER_BONUS = {"VALIDATED_KNOWLEDGE": 20.0, "CANDIDATE": 10.0, "EMERGING": 5.0}
_SPEED_BONUS = {"VALIDATED_KNOWLEDGE": 8.0, "PATTERN": 4.0, "FAST_EXPERIENCE": 1.0}


async def record_version(session_factory, *, object_type: str, object_id: str, **fields) -> int:
    async with session_factory() as session:
        version = 1 + int(
            (
                await session.execute(
                    select(GrowthMemoryVersionORM.version)
                    .where(GrowthMemoryVersionORM.object_type == object_type)
                    .where(GrowthMemoryVersionORM.object_id == object_id)
                    .order_by(GrowthMemoryVersionORM.version.desc())
                    .limit(1)
                )
            ).scalar()
            or 0
        )
        session.add(
            GrowthMemoryVersionORM(
                object_type=object_type,
                object_id=object_id,
                version=version,
                available_at=fields.pop("available_at", None) or datetime.now(UTC),
                **fields,
            )
        )
        await session.commit()
        return version


class GrowthRetriever:
    """SQL-canonical; cache is reconstructible convenience only."""

    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory
        self.generation = 0
        self._cache: dict = {}
        self.metrics = {
            "queries": 0,
            "nonempty": 0,
            "zero_hit": 0,
            "hits": 0,
            "misses": 0,
            "invalidations": 0,
            "candidates_scanned": 0,
            "hindsight_filtered": 0,
            "returned": 0,
            "score_sum": 0.0,
        }

    def invalidate(self, reason: str = "memory_update") -> None:
        self.generation += 1
        self._cache.clear()
        self.metrics["invalidations"] += 1

    async def search(
        self,
        *,
        symbol: str,
        regime: str = "",
        strategy: str = "",
        horizon: str = "",
        setup_signature: str = "",
        as_of_timestamp: datetime | None = None,
        top_k: int = 10,
    ) -> dict:
        as_of = as_of_timestamp or datetime.now(UTC)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        key = (
            self.generation,
            symbol.upper(),
            regime.upper(),
            strategy.upper(),
            horizon,
            setup_signature,
            as_of.replace(second=0, microsecond=0),
            top_k,
        )
        self.metrics["queries"] += 1
        if key in self._cache:
            self.metrics["hits"] += 1
            return self._cache[key]
        self.metrics["misses"] += 1
        async with self._session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GrowthMemoryVersionORM)
                        .where(GrowthMemoryVersionORM.available_at <= as_of)
                        .where(GrowthMemoryVersionORM.object_type.in_(SEARCH_TYPES))
                        .order_by(GrowthMemoryVersionORM.available_at.desc())
                        .limit(2000)
                    )
                )
                .scalars()
                .all()
            )
            future = await session.scalar(
                select(GrowthMemoryVersionORM.id)
                .where(GrowthMemoryVersionORM.available_at > as_of)
                .limit(1)
            )
        self.metrics["candidates_scanned"] += len(rows)
        self.metrics["hindsight_filtered"] += 1 if future is not None else 0
        results = []
        wanted_symbol = symbol.upper()
        for row in rows:
            payload = dict(row.payload_json or {})
            row_symbol = str(payload.get("symbol") or payload.get("asset") or "").upper()
            if wanted_symbol not in ("", "UNKNOWN") and row_symbol and row_symbol != wanted_symbol:
                continue
            available_at = row.available_at
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=UTC)
            components = {
                "factual_quality": float(row.quality or 0.0) * 20.0,
                "memory_speed": _SPEED_BONUS.get(row.memory_speed, 0.0),
                "sample_tier": _TIER_BONUS.get(row.sample_tier, 0.0),
                "sample_count": min(1.0, int(row.sample_count or 0) / 100.0) * 15.0,
                "symbol_match": 10.0 if row_symbol == wanted_symbol else 0.0,
                "regime_match": 8.0
                if regime and str(payload.get("regime") or "").upper() == regime.upper()
                else 0.0,
                "strategy_match": 8.0
                if strategy and str(payload.get("strategy") or "").upper() == strategy.upper()
                else 0.0,
                "horizon_match": 5.0
                if horizon and str(payload.get("horizon") or "") == horizon
                else 0.0,
                "setup_similarity": 5.0
                if setup_signature and str(payload.get("setup_signature") or "") == setup_signature
                else 0.0,
                "post_cost_expectancy": max(
                    -20.0, min(20.0, float(row.post_cost_expectancy_bps or 0.0))
                ),
                "recency": 1.0 / (1.0 + max(0.0, (as_of - available_at).total_seconds()) / 86400.0),
                "contradiction_penalty": -5.0 * int(row.contradictions or 0),
            }
            results.append(
                {
                    "memory_id": row.object_id,
                    "memory_type": row.object_type,
                    "version": row.version,
                    "available_at": available_at.isoformat(),
                    "sample_tier": row.sample_tier,
                    "memory_speed": row.memory_speed,
                    "sample_count": row.sample_count,
                    "quality": row.quality,
                    "post_cost_expectancy_bps": row.post_cost_expectancy_bps,
                    "contradictions": row.contradictions,
                    "strategy": payload.get("strategy"),
                    "direction": payload.get("direction"),
                    "score": round(sum(components.values()), 4),
                    "score_components": components,
                    "source_refs": row.source_refs_json or {},
                }
            )
        results.sort(key=lambda item: item["score"], reverse=True)
        selected = results[: max(1, min(int(top_k), 100))]
        if selected:
            self.metrics["nonempty"] += 1
            self.metrics["returned"] += len(selected)
            self.metrics["score_sum"] += sum(item["score"] for item in selected)
        else:
            self.metrics["zero_hit"] += 1
        response = {
            "as_of_timestamp": as_of.isoformat(),
            "query_version": RETRIEVAL_VERSION,
            "generation": self.generation,
            "result_count": len(selected),
            "results": selected,
            "authority": "LEARNING_ONLY",
            "is_order": False,
        }
        self._cache[key] = response
        return response

    def cache_metrics(self) -> dict:
        keys = len(self._cache)
        hit_rate = self.metrics["hits"] / max(1, self.metrics["hits"] + self.metrics["misses"])
        return {
            **self.metrics,
            "cache_size": keys,
            "cache_hit_rate": hit_rate,
            "query_hit_rate": self.metrics["nonempty"] / max(1, self.metrics["queries"]),
            "zero_hit_rate": self.metrics["zero_hit"] / max(1, self.metrics["queries"]),
            "mean_selected_score": self.metrics["score_sum"] / max(1, self.metrics["returned"]),
        }
