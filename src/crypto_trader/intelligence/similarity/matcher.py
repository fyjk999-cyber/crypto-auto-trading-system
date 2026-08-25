"""Similarity matcher: weighted feature distance, explainable."""

from __future__ import annotations

import math

from crypto_trader.intelligence.similarity.features import feature_vector
from crypto_trader.intelligence.similarity.models import SimilarCase


class SimilarityMatcher:
    def match(
        self,
        *,
        current_regime: str,
        current_factors: dict,
        historical_cases: list[dict],
        top_k: int = 5,
    ) -> dict:
        current = feature_vector(current_regime, current_factors)
        results = []
        for case in historical_cases:
            vector = feature_vector(case.get("regime", "UNKNOWN"), case.get("factors", {}))
            similarity = self._cosine(current, vector)
            results.append(
                SimilarCase(
                    case.get("case_id", ""),
                    round(similarity, 3),
                    case.get("outcome", "unknown"),
                    case.get("regime", "UNKNOWN"),
                )
            )
        results.sort(key=lambda c: c.similarity, reverse=True)
        top = results[:top_k]
        outcomes = {}
        for case in top:
            outcomes[case.outcome] = outcomes.get(case.outcome, 0) + 1
        return {
            "current": {"regime": current_regime, "factors": current_factors},
            "similar_cases": [c.to_dict() for c in top],
            "outcomes": outcomes,
        }

    @staticmethod
    def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
        norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (norm_a * norm_b)
