"""90-day forward shadow campaign manager.

Persists campaign state across restarts via serializable state.
Historical replay DOES NOT count toward real elapsed days.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class CampaignStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    DEGRADED = "DEGRADED"
    COMPLETED = "COMPLETED"
    INVALIDATED = "INVALIDATED"


@dataclass
class ShadowCampaignManager:
    campaign_id: str = "campaign_v1"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    start_time: str | None = None
    last_observation_time: str | None = None
    elapsed_real_calendar_days: float = 0.0
    valid_observation_days: int = 0
    decision_count: int = 0
    trade_count: int = 0
    no_trade_count: int = 0
    symbol_coverage: list[str] = field(default_factory=list)
    regime_coverage: list[str] = field(default_factory=list)
    downtime_hours: float = 0.0
    provider_failures: int = 0
    market_data_failures: int = 0
    critical_incidents: int = 0
    data_quality_score: float = 100.0
    campaign_status: str = CampaignStatus.NOT_STARTED.value
    _observations: list[dict] = field(default_factory=list)
    _decisions: set[str] = field(default_factory=set)

    def start(self, now: datetime | None = None) -> None:
        now = now or datetime.now(UTC)
        if self.campaign_status == CampaignStatus.NOT_STARTED.value:
            self.start_time = now.isoformat()
        self.campaign_status = CampaignStatus.RUNNING.value

    def pause(self) -> None:
        if self.campaign_status == CampaignStatus.RUNNING.value:
            self.campaign_status = CampaignStatus.PAUSED.value

    def resume(self) -> None:
        if self.campaign_status == CampaignStatus.PAUSED.value:
            self.campaign_status = CampaignStatus.RUNNING.value

    def record_observation(
        self,
        *,
        timestamp: str,
        symbol: str,
        regime: str,
        is_decision: bool,
        is_trade: bool,
        valid: bool = True,
    ) -> bool:
        """Returns True if observation was accepted in chronological order."""
        if self.last_observation_time is not None and timestamp <= self.last_observation_time:
            return False
        self.last_observation_time = timestamp
        self._observations.append(
            {
                "timestamp": timestamp,
                "symbol": symbol,
                "regime": regime,
                "valid": valid,
            }
        )
        if valid:
            self.valid_observation_days = len(
                {o["timestamp"][:10] for o in self._observations if o["valid"]}
            )
        if symbol not in self.symbol_coverage:
            self.symbol_coverage.append(symbol)
        if regime not in self.regime_coverage:
            self.regime_coverage.append(regime)
        if is_decision:
            self.decision_count += 1
        if is_trade:
            self.trade_count += 1
        elif is_decision:
            self.no_trade_count += 1
        return True

    def record_decision(self, decision_id: str) -> bool:
        if decision_id in self._decisions:
            return False
        self._decisions.add(decision_id)
        return True

    def record_downtime(self, hours: float) -> None:
        self.downtime_hours += hours
        self.data_quality_score = max(0.0, 100.0 - self.downtime_hours * 2)

    def update_elapsed_days(self, now: datetime | None = None) -> float:
        now = now or datetime.now(UTC)
        if self.start_time is None:
            return 0.0
        start = datetime.fromisoformat(self.start_time)
        self.elapsed_real_calendar_days = max(0.0, (now - start).total_seconds() / 86400)
        return self.elapsed_real_calendar_days

    def maybe_complete(
        self, *, min_elapsed_days: float = 90.0, min_valid_observation_days: int = 70
    ) -> str:
        self.update_elapsed_days()
        if self.elapsed_real_calendar_days < min_elapsed_days:
            return self.campaign_status
        if self.valid_observation_days >= min_valid_observation_days:
            self.campaign_status = CampaignStatus.COMPLETED.value
        else:
            self.campaign_status = CampaignStatus.DEGRADED.value
        return self.campaign_status

    def to_dict(self) -> dict:
        return {
            "campaign_id": self.campaign_id,
            "created_at": self.created_at,
            "start_time": self.start_time,
            "last_observation_time": self.last_observation_time,
            "elapsed_real_calendar_days": self.elapsed_real_calendar_days,
            "valid_observation_days": self.valid_observation_days,
            "decision_count": self.decision_count,
            "trade_count": self.trade_count,
            "no_trade_count": self.no_trade_count,
            "symbol_coverage": list(self.symbol_coverage),
            "regime_coverage": list(self.regime_coverage),
            "downtime_hours": self.downtime_hours,
            "provider_failures": self.provider_failures,
            "market_data_failures": self.market_data_failures,
            "critical_incidents": self.critical_incidents,
            "data_quality_score": self.data_quality_score,
            "campaign_status": self.campaign_status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ShadowCampaignManager:
        campaign = cls()
        for key, value in data.items():
            if hasattr(campaign, key):
                setattr(campaign, key, value)
        return campaign
