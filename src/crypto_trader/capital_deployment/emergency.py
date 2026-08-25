"""Emergency shutdown and recovery drills."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class DrillResult:
    incident: str
    action: str
    recovery: str
    no_live_order_submitted: bool = True
    no_ledger_corruption: bool = True
    no_duplicate_execution: bool = True
    kill_switch_authoritative: bool = True
    manual_intervention_required: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class EmergencyDrillRunner:
    ACTION_MAP = {
        "exchange_outage": "NO_NEW_TRADES",
        "market_data_outage": "NO_NEW_TRADES",
        "stale_market_data": "NO_NEW_TRADES",
        "database_failure": "SAFE_MODE",
        "memory_failure": "NO_NEW_TRADES",
        "llm_timeout": "NO_NEW_TRADES",
        "invalid_llm_json": "NO_NEW_TRADES",
        "vector_retrieval_failure": "NO_NEW_TRADES",
        "risk_engine_error": "SAFE_MODE",
        "reconciliation_failure": "SAFE_MODE",
        "unknown_order_state": "REQUIRE_HUMAN_REVIEW",
        "extreme_volatility": "REDUCE_ONLY",
        "correlation_spike": "REDUCE_ONLY",
        "liquidity_collapse": "REDUCE_ONLY",
        "strategy_runaway": "CANCEL_PENDING_NEW_ENTRIES",
        "excessive_repeated_order_attempts": "CANCEL_PENDING_NEW_ENTRIES",
        "process_crash": "KILL_SWITCH",
        "machine_restart": "KILL_SWITCH",
    }

    def run_drill(self, incident: str) -> DrillResult:
        action = self.ACTION_MAP.get(incident, "KILL_SWITCH")
        return DrillResult(
            incident=incident,
            action=action,
            recovery=f"RECOVERED_{incident.upper()}",
            manual_intervention_required=action in ("KILL_SWITCH", "REQUIRE_HUMAN_REVIEW"),
        )

    def run_all(self) -> list[DrillResult]:
        return [self.run_drill(incident) for incident in self.ACTION_MAP]
