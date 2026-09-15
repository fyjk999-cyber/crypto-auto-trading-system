"""Position-aware dynamic Core-LLM invocation (Low-Risk V2 Phase 4E).

Event deduplication + material-information gate + position-aware priority.
This module only decides *whether and when* to wake the Core LLM; it never
creates risk and never submits an order. One active reassessment is allowed
per leg; newer facts while active are queued as the latest pending state.

Material override events always bypass ordinary dedup: large trades, volume
surge, abnormal ATR-normalized price velocity, activity surge, CVD reversal,
order-book dislocation, OI/funding/basis anomaly, major news, Risk L1 and
LLM-requested reassessment.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum


class InvocationPriority(StrEnum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


PRIORITY_ORDER = {
    InvocationPriority.NORMAL: 0,
    InvocationPriority.HIGH: 1,
    InvocationPriority.URGENT: 2,
}


MATERIAL_EVENT_KINDS = {
    "LARGE_TRADE",
    "VOLUME_SURGE",
    "PRICE_VELOCITY",
    "ACTIVITY_SURGE",
    "CVD_REVERSAL",
    "ORDERBOOK_DISLOCATION",
    "OI_CHANGE",
    "FUNDING_BASIS_ANOMALY",
    "MAJOR_NEWS",
    "RISK_L1",
    "LLM_REQUESTED_REASSESSMENT",
}


@dataclass(slots=True)
class MaterialEvent:
    kind: str
    severity: float = 0.5  # [0, 1]
    novelty: float = 0.5  # [0, 1]
    urgency: float = 0.0  # [0, 1]
    payload: dict = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_material(self) -> bool:
        return self.kind.upper() in MATERIAL_EVENT_KINDS


@dataclass(slots=True)
class PositionInvocationState:
    leg_id: str
    symbol: str
    state_version: str = "v0"
    exposure_usd: Decimal = Decimal("0")
    equity_usd: Decimal = Decimal("1")
    leverage: Decimal = Decimal("1")
    notional_usd: Decimal = Decimal("0")
    unrealized_pnl_pct: float = 0.0
    last_price: Decimal | None = None
    zone_anchor: Decimal | None = None
    last_invocation_at: datetime | None = None
    active: bool = False
    active_since: datetime | None = None
    queued_event: MaterialEvent | None = None


@dataclass(slots=True)
class InvocationDecision:
    action: str  # INVOKE | DEFER_ACTIVE | DEDUPED
    priority: InvocationPriority
    sensitivity_score: float
    reason_codes: list[str] = field(default_factory=list)
    state_version: str = "v0"
    queued_event_kind: str | None = None

    @property
    def should_invoke(self) -> bool:
        return self.action == "INVOKE"

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "priority": self.priority.value,
            "sensitivity_score": self.sensitivity_score,
            "reason_codes": list(self.reason_codes),
            "state_version": self.state_version,
            "queued_event_kind": self.queued_event_kind,
        }


class ReassessmentInvocationManager:
    """Per-leg dynamic invocation gate. Deterministic and broker-free."""

    def __init__(
        self,
        *,
        base_dedup_seconds: float = 30.0,
        urgent_dedup_seconds: float = 3.0,
        zone_epsilon_bps: float = 8.0,
        min_material_severity: float = 0.35,
        min_material_novelty: float = 0.25,
        exposure_weight: float = 1.0,
        leverage_weight: float = 0.5,
        pnl_weight: float = 2.0,
    ) -> None:
        self.base_dedup_seconds = float(base_dedup_seconds)
        self.urgent_dedup_seconds = float(urgent_dedup_seconds)
        self.zone_epsilon_bps = float(zone_epsilon_bps)
        self.min_material_severity = float(min_material_severity)
        self.min_material_novelty = float(min_material_novelty)
        self.exposure_weight = float(exposure_weight)
        self.leverage_weight = float(leverage_weight)
        self.pnl_weight = float(pnl_weight)
        self.positions: dict[str, PositionInvocationState] = {}
        self.invocations = 0
        self.deduped = 0
        self.deferred = 0
        self.events: list[dict] = []

    # ------------------------------------------------------------- positions
    def register(
        self,
        leg_id: str,
        *,
        symbol: str,
        state_version: str = "v0",
        exposure_usd: Decimal = Decimal("0"),
        equity_usd: Decimal = Decimal("1"),
        leverage: Decimal = Decimal("1"),
        notional_usd: Decimal = Decimal("0"),
        unrealized_pnl_pct: float = 0.0,
    ) -> PositionInvocationState:
        state = PositionInvocationState(
            leg_id=leg_id,
            symbol=symbol,
            state_version=state_version,
            exposure_usd=exposure_usd,
            equity_usd=max(equity_usd, Decimal("1")),
            leverage=leverage,
            notional_usd=notional_usd,
            unrealized_pnl_pct=unrealized_pnl_pct,
        )
        self.positions[leg_id] = state
        return state

    def update_position(
        self,
        leg_id: str,
        *,
        state_version: str,
        exposure_usd: Decimal | None = None,
        equity_usd: Decimal | None = None,
        leverage: Decimal | None = None,
        notional_usd: Decimal | None = None,
        unrealized_pnl_pct: float | None = None,
    ) -> PositionInvocationState:
        state = self._require(leg_id)
        state.state_version = state_version
        if exposure_usd is not None:
            state.exposure_usd = exposure_usd
        if equity_usd is not None:
            state.equity_usd = max(equity_usd, Decimal("1"))
        if leverage is not None:
            state.leverage = leverage
        if notional_usd is not None:
            state.notional_usd = notional_usd
        if unrealized_pnl_pct is not None:
            state.unrealized_pnl_pct = unrealized_pnl_pct
        return state

    # ---------------------------------------------------------------- decide
    def decide(
        self,
        leg_id: str,
        *,
        now: datetime | None = None,
        price: Decimal | None = None,
        event: MaterialEvent | None = None,
    ) -> InvocationDecision:
        moment = now or datetime.now(UTC)
        state = self._require(leg_id)
        if price is not None:
            self._observe_price(state, price)
        sensitivity = self._sensitivity(state, event)
        if state.active:
            self.deferred += 1
            if event is not None and (
                state.queued_event is None or event.severity >= state.queued_event.severity
            ):
                state.queued_event = event
            self._record("DEFER_ACTIVE", state, event, sensitivity)
            return InvocationDecision(
                action="DEFER_ACTIVE",
                priority=self._priority(sensitivity, event),
                sensitivity_score=sensitivity,
                reason_codes=["ACTIVE_REASSESSMENT_IN_PROGRESS"],
                state_version=state.state_version,
                queued_event_kind=state.queued_event.kind if state.queued_event else None,
            )

        if event is not None and not self._material_enough(event):
            event = None  # informational noise does not bypass dedup

        elapsed = (
            None
            if state.last_invocation_at is None
            else (moment - state.last_invocation_at).total_seconds()
        )
        if event is not None and event.is_material:
            priority = self._priority(sensitivity, event)
            # Material events bypass ordinary dedup entirely.
            self._start_invocation(state, moment, priority, sensitivity, event)
            return InvocationDecision(
                action="INVOKE",
                priority=priority,
                sensitivity_score=sensitivity,
                reason_codes=[f"MATERIAL_EVENT:{event.kind}", "DEDUP_BYPASSED"],
                state_version=state.state_version,
            )

        dedup_window = self.base_dedup_seconds / (1.0 + max(0.0, sensitivity))
        if elapsed is not None and elapsed < dedup_window:
            self.deduped += 1
            self._record("DEDUPED", state, event, sensitivity, {"elapsed": elapsed})
            return InvocationDecision(
                action="DEDUPED",
                priority=self._priority(sensitivity, event),
                sensitivity_score=sensitivity,
                reason_codes=["DEDUP_WINDOW_ACTIVE"],
                state_version=state.state_version,
            )
        if not self._zone_moved(state):
            self.deduped += 1
            self._record("DEDUPED", state, event, sensitivity, {"zone": "SAME_ZONE"})
            return InvocationDecision(
                action="DEDUPED",
                priority=self._priority(sensitivity, event),
                sensitivity_score=sensitivity,
                reason_codes=["SAME_ZONE_NO_NEW_INFORMATION"],
                state_version=state.state_version,
            )
        priority = self._priority(sensitivity, event)
        self._start_invocation(state, moment, priority, sensitivity, event)
        return InvocationDecision(
            action="INVOKE",
            priority=priority,
            sensitivity_score=sensitivity,
            reason_codes=["ZONE_MOVED"],
            state_version=state.state_version,
        )

    def complete_invocation(
        self, leg_id: str, *, now: datetime | None = None
    ) -> MaterialEvent | None:
        """Mark the active reassessment done; return a queued newer event."""
        moment = now or datetime.now(UTC)
        state = self._require(leg_id)
        state.active = False
        state.active_since = None
        queued = state.queued_event
        state.queued_event = None
        self._record("INVOCATION_COMPLETE", state, queued, 0.0)
        if queued is not None:
            self._start_invocation(
                state, moment, self._priority(self._sensitivity(state, queued), queued), 0.0, queued
            )
        return queued

    def snapshot(self, leg_id: str) -> dict:
        state = self._require(leg_id)
        return {
            "leg_id": state.leg_id,
            "symbol": state.symbol,
            "state_version": state.state_version,
            "active": state.active,
            "queued_event": state.queued_event.kind if state.queued_event else None,
            "last_invocation_at": (
                state.last_invocation_at.isoformat() if state.last_invocation_at else None
            ),
            "zone_anchor": str(state.zone_anchor) if state.zone_anchor else None,
            "invocations": self.invocations,
            "deduped": self.deduped,
            "deferred": self.deferred,
        }

    # -------------------------------------------------------------- internals
    def _start_invocation(
        self,
        state: PositionInvocationState,
        moment: datetime,
        priority: InvocationPriority,
        sensitivity: float,
        event: MaterialEvent | None,
    ) -> None:
        state.active = True
        state.active_since = moment
        state.last_invocation_at = moment
        state.zone_anchor = state.last_price
        self.invocations += 1
        self._record("INVOKE", state, event, sensitivity, {"priority": priority.value})

    def _sensitivity(self, state: PositionInvocationState, event: MaterialEvent | None) -> float:
        exposure_ratio = float(state.exposure_usd / state.equity_usd)
        leverage_ratio = float(state.leverage) / 20.0
        pnl_ratio = min(1.0, abs(state.unrealized_pnl_pct) / 10.0)
        score = (
            self.exposure_weight * min(1.5, exposure_ratio)
            + self.leverage_weight * min(1.0, leverage_ratio)
            + self.pnl_weight * pnl_ratio
        )
        if event is not None:
            score += 0.5 * event.severity + 0.3 * event.novelty + 0.3 * event.urgency
        return max(0.0, score)

    def _priority(self, sensitivity: float, event: MaterialEvent | None) -> InvocationPriority:
        urgent = sensitivity >= 1.6 or (
            event is not None and (event.urgency >= 0.7 or event.kind == "RISK_L1")
        )
        if urgent:
            return InvocationPriority.URGENT
        if sensitivity >= 0.8 or (event is not None and event.severity >= 0.6):
            return InvocationPriority.HIGH
        return InvocationPriority.NORMAL

    def _material_enough(self, event: MaterialEvent) -> bool:
        return (
            event.is_material
            and event.severity >= self.min_material_severity
            and event.novelty >= self.min_material_novelty
        )

    def _observe_price(self, state: PositionInvocationState, price: Decimal) -> None:
        state.last_price = price

    def _zone_moved(self, state: PositionInvocationState) -> bool:
        if state.zone_anchor is None or state.last_price is None or state.zone_anchor <= 0:
            return True
        move_bps = abs(float((state.last_price - state.zone_anchor) / state.zone_anchor)) * 10_000.0
        return move_bps >= self.zone_epsilon_bps

    def _require(self, leg_id: str) -> PositionInvocationState:
        state = self.positions.get(leg_id)
        if state is None:
            raise KeyError(f"unknown invocation leg: {leg_id}")
        return state

    def _record(
        self,
        action: str,
        state: PositionInvocationState,
        event: MaterialEvent | None,
        sensitivity: float,
        extra: dict | None = None,
    ) -> None:
        self.events.append(
            {
                "action": action,
                "leg_id": state.leg_id,
                "state_version": state.state_version,
                "event": event.kind if event else None,
                "sensitivity": sensitivity,
                **(extra or {}),
            }
        )
