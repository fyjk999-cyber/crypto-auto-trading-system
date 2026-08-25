"""Factor research tools for LLM. Read-only research interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.factors.catalog import FactorCatalog


@dataclass
class FactorResearchToolResult:
    ok: bool
    data: dict | list
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class FactorResearchTools:
    def __init__(self, factor_service=None) -> None:
        self.factor_service = factor_service
        self._catalog = FactorCatalog()
        self._experiments: dict[str, dict] = {}
        self._research_results: dict[str, dict] = {}

    async def get_factor_catalog(self) -> FactorResearchToolResult:
        return FactorResearchToolResult(True, self._catalog.list(), None)

    async def get_factor_history(
        self, symbol: str, factor: str, limit: int = 100
    ) -> FactorResearchToolResult:
        if self.factor_service is None:
            return FactorResearchToolResult(False, [], "FACTOR_SERVICE_UNAVAILABLE")
        try:
            rows = await self.factor_service.history(symbol, factor, limit)
            return FactorResearchToolResult(True, rows, None)
        except Exception as exc:
            return FactorResearchToolResult(False, [], f"FACTOR_UNAVAILABLE:{type(exc).__name__}")

    async def analyze_factor(
        self,
        question_id: str,
        hypothesis: str,
        factor: str,
        dataset: str,
        timeframe: str,
        observations: list[dict],
    ) -> FactorResearchToolResult:
        from crypto_trader.factors.researcher import FactorResearcher

        result = FactorResearcher().research(
            question_id, hypothesis, factor, dataset, timeframe, observations
        )
        data = {
            "question_id": result.question_id,
            "hypothesis": result.hypothesis,
            "factor": result.factor,
            "sample_size": result.sample_size,
            "result": result.result,
            "confidence": str(result.confidence),
            "conclusion": result.conclusion,
        }
        self._research_results[question_id] = data
        return FactorResearchToolResult(True, data, None)

    async def create_factor_experiment(
        self,
        experiment_id: str,
        hypothesis: str,
        factor: str,
        dataset: str,
        timeframe: str,
        observations: list[dict],
    ) -> FactorResearchToolResult:
        from crypto_trader.factors.experiment import ExperimentRunner

        experiment = ExperimentRunner().run(
            experiment_id, hypothesis, factor, dataset, timeframe, observations
        )
        data = {
            "experiment_id": experiment.experiment_id,
            "hypothesis": experiment.hypothesis,
            "factor": experiment.factor,
            "result": experiment.result,
            "confidence": experiment.confidence,
            "conclusion": experiment.conclusion,
        }
        self._experiments[experiment_id] = data
        return FactorResearchToolResult(True, data, None)

    async def get_factor_research_result(self, question_id: str) -> FactorResearchToolResult:
        result = self._research_results.get(question_id)
        if result is None:
            return FactorResearchToolResult(
                True, {"question_id": question_id, "status": "NOT_FOUND"}, None
            )
        return FactorResearchToolResult(True, result, None)
