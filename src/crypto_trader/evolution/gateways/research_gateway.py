"""Canonical ResearchGateway. Research is read/experiment/proposal only."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ResearchGateway:
    reports: list[dict] = field(default_factory=list)
    experiments: list[dict] = field(default_factory=list)

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
