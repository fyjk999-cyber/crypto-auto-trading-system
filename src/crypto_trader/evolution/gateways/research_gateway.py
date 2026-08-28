"""Canonical ResearchGateway. Research is read/experiment/proposal only."""

from __future__ import annotations

from dataclasses import dataclass, field

from crypto_trader.llm_runtime.contracts import (
    CandidateReasoningResult,
    HypothesisReasoningResult,
    LLMRequest,
    ResearchReasoningResult,
)


@dataclass
class ResearchGateway:
    reports: list[dict] = field(default_factory=list)
    experiments: list[dict] = field(default_factory=list)
    llm_gateway: object | None = None
    domain_model_runtime: object | None = None

    def create_experiment(self, experiment: dict) -> dict:
        experiment.setdefault("status", "PROPOSED")
        self.experiments.append(experiment)
        return experiment

    def add_report(self, report: dict) -> None:
        self.reports.append(report)

    def latest_reports(self, top_k: int = 5) -> list[dict]:
        return self.reports[-top_k:]

    def execution_authority(self) -> None:
        raise PermissionError("research gateway cannot execute")

    async def reason(self, evidence: dict) -> dict | None:
        return await self._invoke("evolution_research", ResearchReasoningResult, evidence)

    async def generate_hypothesis(self, evidence: dict) -> dict | None:
        return await self._invoke("evolution_hypothesis", HypothesisReasoningResult, evidence)

    async def reason_candidate(self, evidence: dict) -> dict | None:
        return await self._invoke(
            "evolution_candidate_reasoning", CandidateReasoningResult, evidence
        )

    async def _invoke(self, route: str, response_model, evidence: dict) -> dict | None:
        if self.llm_gateway is None:
            return None
        import json

        if self.domain_model_runtime is not None:
            response = await self.domain_model_runtime.invoke(
                route=route,
                context={
                    "ResearchContext": evidence,
                    "ConfirmedLessons": [],
                    "RejectionMemory": [],
                },
                response_model=response_model,
            )
        else:
            response = await self.llm_gateway.invoke(
                LLMRequest(
                    route=route,
                    brain="EVOLUTION",
                    prompt=(
                        "Return structured reasoning from immutable evidence: "
                        f"{json.dumps(evidence)}"
                    ),
                ),
                response_model,
            )
        # Failure returns no proposal and cannot mutate Champion or protected core.
        return response.content if response.ok else None
