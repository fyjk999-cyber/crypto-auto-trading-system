"""Hybrid retrieval: vector + metadata + recency + quality + confidence."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_trader.vector_memory.embedding_provider import LocalHashEmbeddingProvider
from crypto_trader.vector_memory.vector_store import MemoryVectorStore


class HybridRetriever:
    def __init__(
        self,
        store: MemoryVectorStore | None = None,
        provider: LocalHashEmbeddingProvider | None = None,
    ) -> None:
        self.store = store or MemoryVectorStore()
        self.provider = provider or LocalHashEmbeddingProvider()

    def retrieve(
        self,
        *,
        query_text: str,
        symbol: str | None = None,
        regime: str | None = None,
        top_k: int = 5,
    ) -> dict:
        embedding = self.provider.embed(query_text)
        candidates = self.store.search(embedding, top_k=top_k * 3)
        scored = []
        for item in candidates:
            vec = item["vector"]
            similarity = item["similarity"]
            meta = vec.metadata
            quality = float(meta.get("quality", 0.5))
            recency = 1.0 / (
                1.0 + (datetime.now(UTC) - _parse_ts(vec.created_at)).total_seconds() / 86400
            )
            coin_match = 1.0 if symbol and meta.get("symbol") == symbol else 0.3
            regime_match = 1.0 if regime and meta.get("regime") == regime else 0.3
            score = (
                similarity * 0.5
                + quality * 0.2
                + recency * 0.1
                + coin_match * 0.1
                + regime_match * 0.1
            )
            scored.append((score, vec))
        scored.sort(key=lambda x: x[0], reverse=True)
        similar_cases = [
            {
                "symbol": v.metadata.get("symbol", "unknown"),
                "pattern": v.metadata.get("pattern", "unknown"),
                "result": v.metadata.get("result", "unknown"),
                "similarity": round(score, 3),
            }
            for score, v in scored[:top_k]
        ]
        return {"similar_cases": similar_cases, "lessons": [], "warnings": []}


def _parse_ts(value: str):
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return datetime.now(UTC)
