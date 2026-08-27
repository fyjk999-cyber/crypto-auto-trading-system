"""Canonical validation pipeline for evolution candidates."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class GateResult:
    gate: str
    passed: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {"gate": self.gate, "passed": self.passed, "reason": self.reason}


@dataclass
class ValidationRun:
    run_id: str
    candidate_id: str
    gate_results: list = field(default_factory=list)
    champion_metrics: dict = field(default_factory=dict)
    challenger_metrics: dict = field(default_factory=dict)
    success_metrics: dict = field(default_factory=dict)
    guardrail_metrics: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    status: str = "PENDING"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {"run_id": self.run_id, "candidate_id": self.candidate_id,
                "gate_results": [g.to_dict() for g in self.gate_results],
                "champion_metrics": dict(self.champion_metrics),
                "challenger_metrics": dict(self.challenger_metrics),
                "success_metrics": dict(self.success_metrics),
                "guardrail_metrics": dict(self.guardrail_metrics),
                "failures": list(self.failures), "warnings": list(self.warnings),
                "status": self.status, "created_at_utc": self.created_at_utc}


class ValidationPipeline:
    def run(self, *, run_id: str, candidate_id: str,
            gate_results: list[dict], champion_metrics: dict,
            challenger_metrics: dict, success_metrics: dict,
            guardrail_metrics: dict) -> ValidationRun:
        run = ValidationRun(run_id=run_id, candidate_id=candidate_id,
                            champion_metrics=champion_metrics,
                            challenger_metrics=challenger_metrics,
                            success_metrics=success_metrics,
                            guardrail_metrics=guardrail_metrics)
        for item in gate_results:
            run.gate_results.append(GateResult(item["gate"], item.get("passed", False),
                                               item.get("reason", "")))
        failures = [g for g in run.gate_results if not g.passed]
        run.failures = [g.to_dict() for g in failures]
        guardrail_failures = [
            key for key, value in guardrail_metrics.items()
            if isinstance(value, dict) and not value.get("passed", True)
        ]
        if guardrail_failures:
            run.status = "REJECTED"
            run.warnings.append(f"GUARDRAIL_FAILURE:{','.join(guardrail_failures)}")
        elif failures:
            run.status = "REJECTED"
        else:
            run.status = "VALIDATED"
        return run
