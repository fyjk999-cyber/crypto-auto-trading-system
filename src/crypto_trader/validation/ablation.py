"""Research-only evidence ablation primitives (no execution authority)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class AblationResult:
    name: str
    baseline: Decimal
    ablated: Decimal

    @property
    def evidence_effect(self) -> Decimal:
        """Positive means removing this evidence reduced the metric."""
        return self.baseline - self.ablated


def compare_ablation(
    name: str, *, baseline: Decimal, ablated: Decimal
) -> AblationResult:
    return AblationResult(name=name, baseline=baseline, ablated=ablated)
