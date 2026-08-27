"""Safe promotion contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class UpgradeReadinessSnapshot:
    timestamp_utc: str
    candidate_id: str
    champion_version: str
    open_positions: int
    open_orders: int
    in_flight_orders: int
    pending_execution: int
    recent_entry_count: int
    market_volatility_state: str
    spread_state: str
    liquidity_state: str
    market_data_health: str
    exchange_health: str
    reconciliation_health: str
    ledger_health: str
    portfolio_health: str
    risk_health: str
    kill_switch_state: str
    runtime_lease_health: str
    critical_incidents: int
    safe_window: bool = False
    reasons: tuple[str, ...] = ()


@dataclass
class TradingRelease:
    release_id: str
    strategy_version: str
    factor_set_version: str
    prompt_version: str
    model_routing_version: str
    code_commit: str
    config_hash: str
    parent_release_id: str
    candidate_id: str
    promotion_id: str
    status: str = "ACTIVE"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "release_id": self.release_id,
            "strategy_version": self.strategy_version,
            "factor_set_version": self.factor_set_version,
            "prompt_version": self.prompt_version,
            "model_routing_version": self.model_routing_version,
            "code_commit": self.code_commit,
            "config_hash": self.config_hash,
            "parent_release_id": self.parent_release_id,
            "candidate_id": self.candidate_id,
            "promotion_id": self.promotion_id,
            "status": self.status,
            "created_at_utc": self.created_at_utc,
        }


@dataclass
class ChampionSnapshot:
    snapshot_id: str
    champion_version: str
    commit_hash: str
    config_hash: str
    factor_set_version: str
    strategy_version: str
    prompt_version: str
    model_routing_version: str
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "champion_version": self.champion_version,
            "commit_hash": self.commit_hash,
            "config_hash": self.config_hash,
            "factor_set_version": self.factor_set_version,
            "strategy_version": self.strategy_version,
            "prompt_version": self.prompt_version,
            "model_routing_version": self.model_routing_version,
            "created_at_utc": self.created_at_utc,
        }


@dataclass
class PromotionRecord:
    promotion_id: str
    candidate_id: str
    previous_champion: str
    target_release_id: str
    status: str = "PENDING"
    started_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    completed_at_utc: str = ""
    failure_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "promotion_id": self.promotion_id,
            "candidate_id": self.candidate_id,
            "previous_champion": self.previous_champion,
            "target_release_id": self.target_release_id,
            "status": self.status,
            "started_at_utc": self.started_at_utc,
            "completed_at_utc": self.completed_at_utc,
            "failure_reason": self.failure_reason,
        }
