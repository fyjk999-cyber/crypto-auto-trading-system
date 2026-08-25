"""Factor combination candidate generator."""

from __future__ import annotations

from itertools import combinations


class CombinationGenerator:
    def generate(self, factors: list[str], max_size: int = 3) -> list[list[str]]:
        out: list[list[str]] = []
        for size in range(2, min(max_size, len(factors)) + 1):
            for combo in combinations(factors, size):
                out.append(list(combo))
        return out

    def candidate_name(self, factors: list[str]) -> str:
        return "_".join(factors[:3])
