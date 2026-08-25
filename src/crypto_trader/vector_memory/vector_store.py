"""In-memory vector store with cosine similarity."""

from __future__ import annotations

import math

from crypto_trader.vector_memory.schemas import MemoryVector


class MemoryVectorStore:
    def __init__(self) -> None:
        self.vectors: dict[str, MemoryVector] = {}

    def add(self, vector: MemoryVector) -> None:
        self.vectors[vector.id] = vector

    def search(
        self, embedding: list[float], top_k: int = 5, object_type: str | None = None
    ) -> list[dict]:
        results = []
        for vec in self.vectors.values():
            if object_type and vec.object_type != object_type:
                continue
            similarity = self.cosine(embedding, vec.embedding)
            results.append({"vector": vec, "similarity": similarity})
        results.sort(key=lambda r: r["similarity"], reverse=True)
        return results[:top_k]

    @staticmethod
    def cosine(a: list[float], b: list[float]) -> float:
        if len(a) != len(b) or not a or not b:
            return 0.0
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
        norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (norm_a * norm_b)
