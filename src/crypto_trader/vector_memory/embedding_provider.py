"""Embedding provider interface and deterministic hash-based local embedding."""

from __future__ import annotations

import hashlib
import math


class EmbeddingProvider:
    def embed(self, text: str) -> list[float]:
        raise NotImplementedError


class LocalHashEmbeddingProvider(EmbeddingProvider):
    """Deterministic local embedding (no external model)."""

    def embed(self, text: str, dim: int = 32) -> list[float]:
        vec = [0.0] * dim
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode()).digest()
            idx = digest[0] % dim
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            vec[idx] += sign * (1.0 + (digest[2] / 255.0))
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]
