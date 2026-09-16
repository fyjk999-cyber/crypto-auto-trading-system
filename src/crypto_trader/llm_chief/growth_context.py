# Canonical Growth memory context built on GrowthRetriever (read-only).
from __future__ import annotations

_TYPE_BUCKETS = {
    "FAST_EXPERIENCE": "similar_episodes",
    "REVIEWED_EPISODE": "similar_episodes",
    "REGIME_PATTERN": "patterns",
    "GENERALIZED_KNOWLEDGE": "generalized_knowledge",
    "COIN_PROFILE": "coin_profile",
    "COMPRESSED_PATTERN": "compressed_experience",
    "VALIDATED_COMPRESSED_KNOWLEDGE": "compressed_experience",
}
_REF_PREFIX = {
    "FAST_EXPERIENCE": "episode",
    "REVIEWED_EPISODE": "episode",
    "REGIME_PATTERN": "pattern",
    "GENERALIZED_KNOWLEDGE": "generalized",
    "COIN_PROFILE": "profile",
    "COMPRESSED_PATTERN": "compressed",
    "VALIDATED_COMPRESSED_KNOWLEDGE": "compressed",
}


def memory_ref(item: dict) -> str:
    prefix = _REF_PREFIX.get(item.get("memory_type"), "memory")
    return f"{prefix}:{item['memory_id']}:v{item['version']}"


async def build_growth_context(
    retriever,
    *,
    symbol: str,
    regime: str = "",
    strategy: str = "",
    horizon: str = "",
    setup_signature: str = "",
    as_of_timestamp=None,
    top_k: int = 8,
) -> dict:
    response = await retriever.search(
        symbol=symbol,
        regime=regime,
        strategy=strategy,
        horizon=horizon,
        setup_signature=setup_signature,
        as_of_timestamp=as_of_timestamp,
        top_k=top_k,
    )
    context = {
        "similar_episodes": [],
        "patterns": [],
        "generalized_knowledge": [],
        "coin_profile": [],
        "compressed_experience": [],
        "warnings": [],
        "memory_refs": [],
        "strategy": strategy,
        "direction": None,
        "as_of_timestamp": response["as_of_timestamp"],
        "query_version": response["query_version"],
    }
    for item in response["results"]:
        bucket = _TYPE_BUCKETS.get(item.get("memory_type"))
        enriched = {
            "id": item["memory_id"],
            "memory_type": item["memory_type"],
            "version": item["version"],
            "available_at": item["available_at"],
            "sample_tier": item["sample_tier"],
            "memory_speed": item["memory_speed"],
            "sample_count": item["sample_count"],
            "quality": item["quality"],
            "retrieval_score": item["score"],
            "score_components": item["score_components"],
            "strategy": item.get("strategy"),
            "direction": item.get("direction"),
            "source_refs": item.get("source_refs") or {},
        }
        if bucket:
            context[bucket].append(enriched)
        else:
            context["warnings"].append(
                {
                    "warning": "UNMAPPED_MEMORY_TYPE",
                    "memory_type": item["memory_type"],
                    "id": item["memory_id"],
                }
            )
        context["memory_refs"].append(memory_ref(item))
        if enriched["direction"]:
            context["direction"] = enriched["direction"]
    context["sources"] = {"scan_source": None, "trading_source": None}
    return context
