"""Experiment planner: designs experiments for research hypotheses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExperimentPlan:
    hypothesis_id: str
    dataset: str
    symbol: str
    timeframe: str
    entry_condition: str
    measurement: str
    evaluation_metric: str
    status: str = "PLANNED"

    def to_dict(self) -> dict:
        return {
            "hypothesis_id": self.hypothesis_id,
            "dataset": self.dataset,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "entry_condition": self.entry_condition,
            "measurement": self.measurement,
            "evaluation_metric": self.evaluation_metric,
            "status": self.status,
        }


class ExperimentPlanner:
    def plan(self, hypothesis: dict) -> ExperimentPlan:
        factor = hypothesis.get("factor", "unknown")
        return ExperimentPlan(
            hypothesis_id=hypothesis.get("id", ""),
            dataset=f"okx_{factor}_history",
            symbol=hypothesis.get("question", "").split(" in ")[-1].split(" ")[0]
            if " in " in hypothesis.get("question", "")
            else "BTC-USDT",
            timeframe="15m",
            entry_condition=f"{factor} extreme + confirm",
            measurement="forward return over 4h",
            evaluation_metric="win_rate + sharpe",
        )
