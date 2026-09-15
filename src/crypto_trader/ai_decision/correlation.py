"""Rolling score-output correlation for model evidence (Low-Risk V2 Phase 3).

Correlated models must not be counted as independent facts. This tracker keeps
bounded per-model score history and clusters models whose output correlation
exceeds a configurable threshold. The 30D/90D windows are an initial auditable
engineering default — configurable, not immutable law.

Recommendation only: nothing here can create, size or submit an order.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass(slots=True)
class CorrelationCluster:
    cluster_id: int
    members: list[str]
    representative_score: float


@dataclass
class RollingScoreCorrelation:
    """Bounded rolling correlation of per-model direction scores."""

    window_days: int = 90
    reference_windows: tuple[int, ...] = (30, 90)
    cluster_threshold: float = 0.7
    min_overlap: int = 8
    _history: dict[str, deque[float]] = field(default_factory=dict, repr=False)
    samples_recorded: int = 0

    def record(self, scores: dict[str, float]) -> None:
        self.samples_recorded += 1
        for model_id, score in scores.items():
            self._history.setdefault(model_id, deque(maxlen=self.window_days)).append(float(score))

    def history_size(self) -> dict[str, int]:
        return {model_id: len(values) for model_id, values in self._history.items()}

    def correlation(self, model_a: str, model_b: str, *, window: int | None = None) -> float | None:
        left = list(self._history.get(model_a, ()))
        right = list(self._history.get(model_b, ()))
        if window is not None:
            left = left[-window:]
            right = right[-window:]
        size = min(len(left), len(right))
        if size < self.min_overlap:
            return None
        left = left[-size:]
        right = right[-size:]
        mean_left = sum(left) / size
        mean_right = sum(right) / size
        numerator = sum(
            (left[i] - mean_left) * (right[i] - mean_right) for i in range(size)
        )
        var_left = sum((value - mean_left) ** 2 for value in left)
        var_right = sum((value - mean_right) ** 2 for value in right)
        denominator = (var_left * var_right) ** 0.5
        if denominator <= 0:
            # A constant identical series is perfectly dependent.
            return 1.0 if left == right else 0.0
        return numerator / denominator

    def correlation_matrix(self, model_ids: list[str]) -> dict[str, dict[str, float | None]]:
        matrix: dict[str, dict[str, float | None]] = {}
        for model_a in model_ids:
            row: dict[str, float | None] = {}
            for model_b in model_ids:
                row[model_b] = (
                    1.0 if model_a == model_b else self.correlation(model_a, model_b)
                )
            matrix[model_a] = row
        return matrix

    def clusters(
        self, model_ids: list[str], *, threshold: float | None = None
    ) -> list[list[str]]:
        """Union-find clusters of correlated models (correlation >= threshold)."""
        cutoff = self.cluster_threshold if threshold is None else threshold
        parent = {model_id: model_id for model_id in model_ids}

        def find(item: str) -> str:
            while parent[item] != item:
                parent[item] = parent[parent[item]]
                item = parent[item]
            return item

        def union(left: str, right: str) -> None:
            root_left, root_right = find(left), find(right)
            if root_left != root_right:
                parent[root_right] = root_left

        for index, model_a in enumerate(model_ids):
            for model_b in model_ids[index + 1 :]:
                value = self.correlation(model_a, model_b)
                if value is not None and abs(value) >= cutoff:
                    union(model_a, model_b)
        groups: dict[str, list[str]] = {}
        for model_id in model_ids:
            groups.setdefault(find(model_id), []).append(model_id)
        return list(groups.values())

    def effective_independent_count(
        self,
        model_ids: list[str],
        *,
        threshold: float | None = None,
    ) -> int:
        """Distinct correlation clusters; falls back to model count without history."""
        with_history = [
            model_id
            for model_id in model_ids
            if len(self._history.get(model_id, ())) >= self.min_overlap
        ]
        if not with_history:
            return 0
        clusters = self.clusters(with_history, threshold=threshold)
        uncorrelated = len(model_ids) - len(with_history)
        return len(clusters) + uncorrelated

    def as_dict(self) -> dict:
        return {
            "window_days": self.window_days,
            "reference_windows": list(self.reference_windows),
            "cluster_threshold": self.cluster_threshold,
            "min_overlap": self.min_overlap,
            "samples_recorded": self.samples_recorded,
            "history_size": self.history_size(),
            "note": "rolling 30D/90D correlation is a configurable engineering default",
        }
