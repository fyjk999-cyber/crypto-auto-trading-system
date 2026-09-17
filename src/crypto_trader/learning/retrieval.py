# Canonical Growth SQL retriever with strict as-of version history.
from __future__ import annotations

import hashlib
import json
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


class GrowthPublishInputMissing(RuntimeError):
    """Raised when a knowledge publication has no exact input to bind."""


def proposition_identity(object_type: str, object_id: str) -> str:
    canonical = (object_type.upper() + "|" + object_id).encode("utf-8")
    return "prop:" + hashlib.sha256(canonical).hexdigest()[:24]


def input_revision_hash(object_type: str, object_id: str, fields: dict) -> str:
    canonical_input = {
        "object_type": object_type.upper(),
        "object_id": object_id,
        "fields": {key: value for key, value in fields.items() if key not in {"payload_json"}},
    }
    payload = json.dumps(canonical_input, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def record_version(
    session_factory,
    *,
    object_type: str,
    object_id: str,
    available_at: datetime | None = None,
    proposition_id: str | None = None,
    input_hash: str | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    **fields,
) -> int:
    if not object_type or not object_id or not fields:
        raise GrowthPublishInputMissing("NO_PUBLISH_INPUT")
    payload = dict(fields.get("payload_json") or {})
    known_at = available_at or datetime.now(UTC)
    proposition = proposition_id or proposition_identity(object_type, object_id)
    revision_hash = input_hash or input_revision_hash(object_type, object_id, fields)
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
        payload["_meta"] = {
            "proposition_id": proposition,
            "input_hash": revision_hash,
            "known_at": known_at.isoformat(),
            "revision": version,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "revoked_at": revoked_at.isoformat() if revoked_at else None,
        }
        fields["payload_json"] = payload
        session.add(
            GrowthMemoryVersionORM(
                object_type=object_type,
                object_id=object_id,
                version=version,
                available_at=known_at,
                **fields,
            )
        )
        await session.commit()
        return version


def _aware_datetime(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


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
            "latest_visible_deduped": 0,
            "scope_fail_closed": 0,
            "expired_filtered": 0,
            "revoked_filtered": 0,
            "budget_omitted": 0,
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
        max_serialized_bytes: int = 65536,
        strict_scope: bool = True,
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
            int(top_k),
            int(max_serialized_bytes),
            bool(strict_scope),
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

        # As-of truth is one latest visible version per logical proposition.
        latest_visible: dict[tuple[str, str], object] = {}
        for row in rows:
            identity = (str(row.object_type), str(row.object_id))
            current = latest_visible.get(identity)
            if current is None or int(row.version) > int(current.version):
                latest_visible[identity] = row
        deduped = list(latest_visible.values())
        self.metrics["latest_visible_deduped"] += max(0, len(rows) - len(deduped))

        results = []
        wanted_symbol = symbol.upper()
        for row in deduped:
            payload = dict(row.payload_json or {})
            row_symbol = str(payload.get("symbol") or payload.get("asset") or "").upper()
            if wanted_symbol not in ("", "UNKNOWN"):
                if strict_scope and not row_symbol:
                    self.metrics["scope_fail_closed"] += 1
                    continue
                if row_symbol and row_symbol != wanted_symbol:
                    self.metrics["scope_fail_closed"] += 1
                    continue
            available_at = row.available_at
            if available_at.tzinfo is None:
                available_at = available_at.replace(tzinfo=UTC)
            meta = dict(payload.get("_meta") or {})
            expires_at = _aware_datetime(meta.get("expires_at"))
            if expires_at is not None and expires_at <= as_of:
                self.metrics["expired_filtered"] += 1
                continue
            revoked_at = _aware_datetime(meta.get("revoked_at"))
            if revoked_at is not None and revoked_at <= as_of:
                self.metrics["revoked_filtered"] += 1
                continue
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
                    "known_at": meta.get("known_at") or available_at.isoformat(),
                    "proposition_id": meta.get("proposition_id"),
                    "input_hash": meta.get("input_hash"),
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
        budget = max(1024, int(max_serialized_bytes))
        budgeted = []
        used_bytes = 0
        omitted = 0
        for item in selected:
            item_bytes = len(json.dumps(item, default=str))
            if used_bytes + item_bytes > budget:
                omitted += 1
                continue
            budgeted.append(item)
            used_bytes += item_bytes
        selected = budgeted
        self.metrics["budget_omitted"] += omitted
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
            "budget": {
                "max_serialized_bytes": budget,
                "used_serialized_bytes": used_bytes,
                "omitted_count": omitted,
            },
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
