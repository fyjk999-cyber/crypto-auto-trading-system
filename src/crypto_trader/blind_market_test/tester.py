"""Out-of-sample blind market challenge."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BlindResult:
    generalization: float
    adaptability: float
    risk_control: float
    overall: float


class BlindMarketTester:
    def evaluate(self, *, environments: list[str], results: list[dict]) -> BlindResult:
        if not results:
            return BlindResult(0.0, 0.0, 0.0, 0.0)
        gen = sum(r.get("generalization", 0) for r in results) / len(results)
        adapt = sum(r.get("adaptability", 0) for r in results) / len(results)
        risk = sum(r.get("risk_control", 0) for r in results) / len(results)
        return BlindResult(
            round(gen, 3), round(adapt, 3), round(risk, 3), round((gen + adapt + risk) / 3, 3)
        )
