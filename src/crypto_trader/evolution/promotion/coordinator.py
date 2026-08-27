"""Safe promotion coordinator."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.evolution.promotion.contracts import (
    ChampionSnapshot,
    PromotionRecord,
    TradingRelease,
    UpgradeReadinessSnapshot,
)
from crypto_trader.evolution.promotion.entry_gate import NewEntryGate


@dataclass
class PromotionResult:
    promotion_id: str
    status: str
    reason: str


@dataclass
class SafePromotionCoordinator:
    gate: NewEntryGate = field(default_factory=NewEntryGate)
    active_release: TradingRelease | None = None
    snapshots: dict = field(default_factory=dict)
    records: dict = field(default_factory=dict)
    _lock: str = ""

    def evaluate_safe_window(self, snapshot: UpgradeReadinessSnapshot) -> tuple[bool, list]:
        reasons = []
        if snapshot.open_positions != 0:
            reasons.append("OPEN_POSITIONS")
        if snapshot.open_orders != 0:
            reasons.append("OPEN_ORDERS")
        if snapshot.in_flight_orders != 0:
            reasons.append("IN_FLIGHT")
        if snapshot.pending_execution != 0:
            reasons.append("PENDING_EXECUTION")
        if snapshot.market_volatility_state == "EXTREME":
            reasons.append("EXTREME_VOLATILITY")
        if snapshot.spread_state == "ABNORMAL":
            reasons.append("ABNORMAL_SPREAD")
        if snapshot.liquidity_state == "CRITICAL":
            reasons.append("CRITICAL_LIQUIDITY")
        for name, state in (
            ("market_data", snapshot.market_data_health),
            ("exchange", snapshot.exchange_health),
            ("reconciliation", snapshot.reconciliation_health),
            ("ledger", snapshot.ledger_health),
            ("portfolio", snapshot.portfolio_health),
            ("risk", snapshot.risk_health),
            ("lease", snapshot.runtime_lease_health),
        ):
            if state != "HEALTHY":
                reasons.append(f"{name.upper()}_UNHEALTHY")
        if snapshot.kill_switch_state != "OFF":
            reasons.append("KILL_SWITCH")
        if snapshot.critical_incidents != 0:
            reasons.append("CRITICAL_INCIDENTS")
        return (not reasons), reasons

    def promote(
        self,
        *,
        promotion_id: str,
        candidate_id: str,
        certified: bool,
        snapshot: UpgradeReadinessSnapshot,
        target_release: TradingRelease,
        health_pass: bool,
        smoke_pass: bool,
    ) -> PromotionResult:
        if self._lock:
            return PromotionResult(promotion_id, "REJECTED", "PROMOTION_LOCK_HELD")
        if not certified:
            return PromotionResult(promotion_id, "REJECTED", "NOT_CERTIFIED")
        safe, reasons = self.evaluate_safe_window(snapshot)
        if not safe:
            return PromotionResult(promotion_id, "WAIT_SAFE_WINDOW", ",".join(reasons))
        self._lock = promotion_id
        champion_snapshot = ChampionSnapshot(
            snapshot_id=f"champ_{promotion_id}",
            champion_version=snapshot.champion_version,
            commit_hash=target_release.parent_release_id,
            config_hash=target_release.config_hash,
            factor_set_version=target_release.factor_set_version,
            strategy_version=target_release.strategy_version,
            prompt_version=target_release.prompt_version,
            model_routing_version=target_release.model_routing_version,
        )
        self.snapshots[promotion_id] = champion_snapshot
        self.gate.block()
        record = PromotionRecord(
            promotion_id,
            candidate_id,
            snapshot.champion_version,
            target_release.release_id,
            status="ACTIVATING",
        )
        self.records[promotion_id] = record
        if not health_pass or not smoke_pass:
            record.status = "ROLLING_BACK"
            record.failure_reason = "HEALTH_SMOKE_FAIL"
            self.gate.open()
            self._lock = ""
            return PromotionResult(promotion_id, "ROLLED_BACK", record.failure_reason)
        target_release.status = "ACTIVE"
        target_release.parent_release_id = snapshot.champion_version
        self.active_release = target_release
        self.gate.open()
        record.status = "ACTIVE"
        record.completed_at_utc = datetime.now(UTC).isoformat()
        self._lock = ""
        return PromotionResult(promotion_id, "ACTIVE", "OK")

    def rollback(self, *, promotion_id: str, health_pass: bool) -> PromotionResult:
        snapshot = self.snapshots.get(promotion_id)
        if snapshot is None:
            return PromotionResult(promotion_id, "REJECTED", "NO_SNAPSHOT")
        if self._lock and self._lock != promotion_id:
            return PromotionResult(promotion_id, "REJECTED", "PROMOTION_LOCK_HELD")
        if not health_pass:
            self.gate.block()
            self.records[promotion_id].status = "SAFE_DEGRADED"
            return PromotionResult(promotion_id, "SAFE_DEGRADED", "ROLLBACK_HEALTH_FAIL")
        self.active_release = None
        self.gate.open()
        self.records[promotion_id].status = "ROLLED_BACK"
        self._lock = ""
        return PromotionResult(promotion_id, "ROLLED_BACK", "OK")
